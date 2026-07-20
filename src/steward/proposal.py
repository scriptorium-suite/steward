"""Proposal files (scriptorium-spec proposal/1.0): scaffold, load, validate, summarize.

The proposal file is the product's core contract: an offline, human-reviewable,
diff-able plan. `steward propose` only writes a SCAFFOLD (plus a prompt file);
the targets are filled in by an LLM, an agent, or a human - all equivalent.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .audit import open_snapshot

SCHEMA_VERSION = "proposal/1.0"
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
CONFIDENCE = {"high", "medium", "low"}

PROMPT_TEMPLATE = """\
# How to fill this proposal (for an LLM, an agent, or a human)

You are reorganizing a reference library. `proposal.json` contains one entry
per item with its metadata (title/year/abstract/tags) and current collections.

For EVERY entry, fill in:
- `targets`: 1-3 collection paths chosen from `target_tree` (first = primary
  home; add a second only when the item genuinely serves two lines).
- `confidence`: "high" | "medium" | "low".
- `needsReview`: true when a human must look before applying.
- `note`: one short sentence of reasoning when confidence is not high.

Rules:
1. Judge by title + abstract content first; current collections are only a hint.
2. Use target paths EXACTLY as written in `target_tree` (character for character).
3. Do not invent new paths; if nothing fits, use the inbox path and say so in note.
4. Do not modify any other field. Do not remove entries.

When done, the user reviews the file (and the per-folder summary from
`steward apply <file>` dry-run), edits whatever they disagree with, and runs
`steward apply <file> --run`.
"""


class ProposalError(RuntimeError):
    pass


# -- scaffold ----------------------------------------------------------------

def scaffold(sqlite_path: Path, target_tree: list[str], inbox: str | None = None) -> dict:
    """Build a proposal skeleton from a read-only library snapshot."""
    con, tmp = open_snapshot(sqlite_path)
    try:
        q = con.execute
        row = q("SELECT libraryID FROM libraries WHERE type='user'").fetchone()
        lib = row[0] if row else None
        lib_item = f"AND i.libraryID = {lib}" if lib is not None else ""

        fields = {r["fieldName"]: r["fieldID"] for r in q(
            "SELECT fieldID, fieldName FROM fields WHERE fieldName IN "
            "('title','date','abstractNote')")}

        def field_of(item_id, name):
            r = q("SELECT v.value FROM itemData d JOIN itemDataValues v "
                  "ON d.valueID=v.valueID WHERE d.itemID=? AND d.fieldID=?",
                  (item_id, fields.get(name, -1))).fetchone()
            return r["value"] if r else ""

        cols = {r["collectionID"]: dict(r) for r in q(
            "SELECT collectionID, collectionName, parentCollectionID FROM collections")}

        def col_path(cid):
            parts, cur = [], cid
            while cur is not None and cur in cols:
                parts.append(cols[cur]["collectionName"])
                cur = cols[cur]["parentCollectionID"]
            return "/".join(reversed(parts))

        entries = []
        for r in q(f"""
            SELECT i.itemID, i.key FROM items i
            WHERE i.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes
                                       WHERE typeName IN ('attachment','note','annotation'))
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems) {lib_item}"""):
            iid = r["itemID"]
            current = [col_path(x["collectionID"]) for x in q(
                "SELECT collectionID FROM collectionItems WHERE itemID=?", (iid,))]
            tags = [t["name"] for t in q(
                "SELECT t.name FROM itemTags it JOIN tags t ON it.tagID=t.tagID "
                "WHERE it.itemID=?", (iid,))]
            entries.append({
                "key": r["key"],
                "title": field_of(iid, "title"),
                "targets": [inbox] if inbox else [],
                "confidence": "low",
                "needsReview": True,
                "note": "(prefilled inbox - replace with a real target)" if inbox else "",
                "currentCollections": current,
                # extra context fields - spec-legal (consumers ignore unknown fields)
                "year": (field_of(iid, "date") or "")[:4],
                "abstract": (field_of(iid, "abstractNote") or "")[:400],
                "tags": tags,
            })
    finally:
        con.close()
        tmp.unlink(missing_ok=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "steward propose (scaffold - targets must be filled in)",
        "target_tree": target_tree,
        "proposals": entries,
    }


# -- load & validate ---------------------------------------------------------

def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    errors = validate(doc)
    if errors:
        shown = errors[:20]
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise ProposalError(f"{path} is not a valid proposal:\n  "
                            + "\n  ".join(shown) + more)
    return doc


def validate(doc: dict) -> list[str]:
    errors = []
    sv = doc.get("schema_version", "")
    if not re.match(r"^proposal/1\.\d+$", sv):
        errors.append(f"schema_version missing or unsupported: {sv!r}")
        return errors
    tree = doc.get("target_tree")
    if not isinstance(tree, list) or not tree:
        errors.append("target_tree missing or empty (the scaffold always writes it; "
                      "an absent tree means a mangled file)")
        tree = None
    props = doc.get("proposals")
    if not isinstance(props, list) or not props:
        errors.append("proposals: missing or empty")
        return errors
    seen = set()
    for i, p in enumerate(props):
        where = f"proposals[{i}]"
        key = p.get("key", "")
        if not KEY_RE.match(key or ""):
            errors.append(f"{where}: bad key {key!r}")
        if key in seen:
            errors.append(f"{where}: duplicate key {key}")
        seen.add(key)
        targets = p.get("targets")
        if not isinstance(targets, list) or not (1 <= len(targets) <= 3) \
                or not all(isinstance(t, str) and t for t in targets):
            errors.append(f"{where} ({key}): targets must be 1-3 non-empty paths "
                          "(unfilled scaffold?)")
            continue
        if len(set(targets)) != len(targets):
            errors.append(f"{where} ({key}): duplicate targets {targets}")
        for t in targets:
            if t != t.strip() or "//" in t or t.startswith("/") or t.endswith("/"):
                errors.append(f"{where} ({key}): malformed path {t!r} "
                              "(whitespace or empty segment)")
            elif tree and t not in tree:
                errors.append(f"{where} ({key}): target not in target_tree: {t!r}")
        conf = p.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            errors.append(f"{where} ({key}): invalid confidence {conf!r}")
    return errors


# -- summaries ---------------------------------------------------------------

def summarize(doc: dict) -> str:
    props = doc["proposals"]
    per_target = Counter(p["targets"][0] for p in props)
    review = [p for p in props if p.get("needsReview")]
    low = [p for p in props if p.get("confidence") == "low"]
    lines = [f"proposal: {len(props)} items -> {len(per_target)} primary targets "
             f"(low confidence: {len(low)}, flagged for review: {len(review)})", ""]
    for tgt, n in sorted(per_target.items()):
        lines.append(f"  {tgt}: {n}")
    if review:
        lines.append("")
        lines.append("FLAGGED FOR REVIEW:")
        for p in review[:20]:
            lines.append(f"  - {p['key']} {p.get('title', '')[:60]}"
                         f"  [{p.get('confidence')}] {p.get('note', '')[:80]}")
        if len(review) > 20:
            lines.append(f"  ... and {len(review) - 20} more")
    return "\n".join(lines)
