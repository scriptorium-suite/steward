"""tag: AI tags + one-line TLDR + reading status, written to Zotero.

Same proposal-file philosophy as reorg: `tag scaffold` emits items + metadata +
a controlled vocabulary + filling instructions; an LLM/agent/human fills
`aiTags`/`tldr`/`readStatus`; `tag apply` writes them back (journaled).

Write side (scriptorium-spec specs/obsidian-export.md extra conventions):
- ai tags carry the `ai:` prefix and tag type 1 (automatic), separable & reversible
- extra field gets exactly one `TLDR:` line and one `Read_Status:` line
  (+ `Read_Status_Date:`), preserving all other extra content
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from . import __version__
from .audit import open_snapshot
from .zotero_api import ZoteroClient

SCHEMA = "tag-plan/1.0"          # steward-local (not a cross-tool spec format)
KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
STATUS_FIELD = "Read_Status"
DATE_FIELD = "Read_Status_Date"
VALID_STATUS = {"", "New", "To Read", "In Progress", "Read", "Not Reading"}
OLD_STATUS_TAGS = {"Read", "/done", "/reading", "/unread"}

PROMPT = """\
# How to fill this tag plan

For each entry in `items`, fill in:
- `aiTags`: 2-5 topic tags. Prefer terms from `vocabulary`; at most one free tag.
  Do NOT include the `ai:` prefix - steward adds it.
- `tldr`: one sentence (<= ~48 chars), concrete and specific, no "this paper".
- `readStatus`: one of New / To Read / In Progress / Read / Not Reading
  (leave "" to let steward keep the item's current status).

Judge from title + abstract. Do not modify other fields. Then:
  steward tag apply <file>          # dry-run
  steward tag apply <file> --run    # write
"""


class TagError(RuntimeError):
    pass


def scaffold(sqlite_path: Path, vocabulary: list[str], only_untagged: bool = True) -> dict:
    con, tmp = open_snapshot(sqlite_path)
    try:
        q = con.execute
        row = q("SELECT libraryID FROM libraries WHERE type='user'").fetchone()
        lib = row[0] if row else None
        lib_item = f"AND i.libraryID = {lib}" if lib is not None else ""
        fields = {r["fieldName"]: r["fieldID"] for r in q(
            "SELECT fieldID, fieldName FROM fields WHERE fieldName IN "
            "('title','date','abstractNote')")}

        def field_of(iid, name):
            r = q("SELECT v.value FROM itemData d JOIN itemDataValues v "
                  "ON d.valueID=v.valueID WHERE d.itemID=? AND d.fieldID=?",
                  (iid, fields.get(name, -1))).fetchone()
            return r["value"] if r else ""

        items = []
        for r in q(f"""
            SELECT i.itemID, i.key FROM items i
            WHERE i.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes
                                       WHERE typeName IN ('attachment','note','annotation'))
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems) {lib_item}"""):
            iid = r["itemID"]
            tags = [t["name"] for t in q(
                "SELECT t.name FROM itemTags it JOIN tags t ON it.tagID=t.tagID "
                "WHERE it.itemID=?", (iid,))]
            if only_untagged and any(t.startswith("ai:") for t in tags):
                continue
            items.append({
                "key": r["key"],
                "title": field_of(iid, "title"),
                "year": (field_of(iid, "date") or "")[:4],
                "abstract": (field_of(iid, "abstractNote") or "")[:400],
                "existingTags": tags,
                "aiTags": [],
                "tldr": "",
                "readStatus": "",
            })
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    return {"schema_version": SCHEMA,
            "generated_by": f"steward tag scaffold ({__version__})",
            "vocabulary": vocabulary, "items": items}


def validate(doc: dict) -> list[str]:
    errors = []
    if doc.get("schema_version") != SCHEMA:
        errors.append(f"schema_version must be {SCHEMA}")
    items = doc.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items: missing or empty")
        return errors
    for i, it in enumerate(items):
        w = f"items[{i}]"
        if not KEY_RE.match(it.get("key", "") or ""):
            errors.append(f"{w}: bad key")
        tags = it.get("aiTags")
        if not isinstance(tags, list) or not (1 <= len(tags) <= 5) \
                or not all(isinstance(t, str) and t and not t.startswith("ai:") for t in tags):
            errors.append(f"{w} ({it.get('key')}): aiTags must be 1-5 non-empty tags "
                          "without the ai: prefix (unfilled?)")
        tldr = it.get("tldr") or ""
        if not tldr.strip():
            errors.append(f"{w} ({it.get('key')}): empty tldr")
        elif "\n" in tldr or "\r" in tldr:
            errors.append(f"{w} ({it.get('key')}): tldr must be a single line "
                          "(no newlines)")
        if it.get("readStatus", "") not in VALID_STATUS:
            errors.append(f"{w} ({it.get('key')}): invalid readStatus {it.get('readStatus')!r}")
    return errors


def _rebuild_extra(extra: str, tldr: str, status: str, now_iso: str) -> str:
    managed = ("TLDR:", f"{STATUS_FIELD}:", f"{DATE_FIELD}:")
    lines = extra.split("\n")
    # preserve the FIRST existing status/date line (single-status invariant)
    existing_status = next((l for l in lines if l.startswith(f"{STATUS_FIELD}:")), None)
    existing_date = next((l for l in lines if l.startswith(f"{DATE_FIELD}:")), None)
    kept = [l for l in lines if l.strip() and not any(l.startswith(m) for m in managed)]
    kept.append(f"TLDR: {' '.join(tldr.split())}")   # collapse any whitespace/newlines
    if status:                                        # explicit override
        kept += [f"{STATUS_FIELD}: {status}", f"{DATE_FIELD}: {now_iso}"]
    elif existing_status:                             # keep exactly one existing status
        kept.append(existing_status)
        if existing_date:
            kept.append(existing_date)
    return "\n".join(kept)


def execute(doc: dict, client: ZoteroClient, profile, backup_check: bool = True) -> Path:
    """Write ai tags + TLDR + reading status, journaled for rollback."""
    from . import apply as apply_mod  # reuse journal + backup gate + fetch helpers
    if backup_check:
        apply_mod._check_backup(profile)
    keys = [it["key"] for it in doc["items"]]
    server = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        _, _, items = client.request(
            "GET", f"/items?itemKey={'%2C'.join(chunk)}&format=json&limit=50")
        for it in items:
            server[it["key"]] = it
    vanished = [k for k in keys if k not in server]
    if vanished:
        raise TagError(f"{len(vanished)} items no longer exist: {vanished[:5]} - "
                       "re-run `steward tag scaffold`")

    pre = apply_mod._fetch_items(client, keys, fields=("tags", "extra"))
    jpath = apply_mod._write_journal("tag", profile, pre, {})

    updates = plan_updates(doc, server)
    intended = {u["key"]: {"tags": u["tags"], "extra": u["extra"]} for u in updates}
    result = client.post_items(updates)
    if result["failed"]:
        failed_keys = [updates[int(idx)]["key"] for idx in result["failed"]]
        retry, conflicts, gone = apply_mod.resolve_conflicts(
            client, failed_keys, intended, pre, ("tags", "extra"))
        if retry:
            second = client.post_items(retry)
            for idx in second["failed"]:
                conflicts.append(retry[int(idx)]["key"])
        if conflicts or gone:
            raise TagError(
                f"{len(conflicts)} items edited concurrently (left untouched): "
                f"{conflicts[:5]}; {len(gone)} vanished: {gone[:5]}. "
                f"Applied items journaled at {jpath} (use `steward rollback`).")
    print(f"tagged {len(updates)} items")
    print(f"journal: {jpath}")
    print(f"undo: steward rollback \"{jpath}\"")
    return jpath


def plan_updates(doc: dict, server_items: dict) -> list[dict]:
    """Build item update bodies from the filled plan + fresh server items.
    server_items: {key: full item dict from the API}."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    updates = []
    for it in doc["items"]:
        key = it["key"]
        if key not in server_items:
            continue
        data = server_items[key]["data"]
        kept = [t for t in data.get("tags", []) if t["tag"] not in OLD_STATUS_TAGS]
        names = {t["tag"] for t in kept}
        new = [{"tag": f"ai:{t}", "type": 1} for t in it["aiTags"] if f"ai:{t}" not in names]
        extra = _rebuild_extra(data.get("extra", ""), it["tldr"],
                               it.get("readStatus", ""), now_iso)
        updates.append({"key": key, "version": server_items[key]["version"],
                        "tags": kept + new, "extra": extra})
    return updates
