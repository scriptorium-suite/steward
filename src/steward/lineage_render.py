"""lineage_render: a lineage-graph/1.0 -> a self-contained Markdown note.

The deterministic PROJECTION half of P4: the `synthesize-direction` skill saves
its ENRICHED `lineage-graph/1.0` (typed relations + clusters), then this turns
that JSON into the canonical, reproducible visual — a single Markdown note that
renders in vanilla Obsidian with **no plugin**: a native Mermaid flowchart
(relation-labeled edges, cluster subgraphs), a chronological timeline, a plain
edge table (Dataview gets more), and a provenance footer.

`render()` is a pure, deterministic function: same graph in -> identical string
out, no I/O, no clocks (it reuses the graph's own `direction.created`). The
machine source of truth stays the `lineage-graph/1.0` JSON; this note is a
human-/plugin-readable view, kept self-contained so it does NOT depend on
per-paper notes existing (lean-vault, see scriptorium-spec specs/vault-layout.md).
"""
from __future__ import annotations

import re

from . import __version__, yamlmini

SCHEMA_VERSION = "lineage-graph/1.0"

# The five canonical edge relations (scriptorium-spec lineage-graph/1.0 enum) =
# the Breadcrumbs-compatible frontmatter keys (relationship-field convention,
# specs/literature-reading.md §3).
RELATIONS = ("cites", "extends", "supersedes", "method-of", "contrasts")


class RenderError(RuntimeError):
    pass


# -- helpers -----------------------------------------------------------------

def _oneline(text) -> str:
    """Collapse CR/LF/tabs so a value can never break/forge YAML or a table row."""
    return re.sub(r"\s+", " ", str(text)).strip()


def _y(value) -> str:
    """A YAML-safe scalar: a JSON string is valid YAML, with newlines escaped."""
    import json
    return json.dumps(_oneline(value), ensure_ascii=False)


def _node_label(node: dict) -> str:
    """A short, readable node label: title (truncated) + year if present, else
    the citekey. Mermaid-escaped (no quotes/parens/newlines that break a node)."""
    title = _oneline(node.get("title") or "")
    year = _oneline(node.get("year") or "")
    if title:
        label = title if len(title) <= 48 else title[:47].rstrip() + "…"
        if year:
            label = f"{label} ({year})"
    else:
        label = _oneline(node.get("citekey") or "")
    return _mermaid_label(label)


def _mermaid_label(text: str) -> str:
    """Make a string safe to sit inside a Mermaid `["..."]` quoted label:
    strip quotes/brackets/parens/pipes that would terminate the label, and
    collapse any whitespace (newlines included)."""
    text = re.sub(r"\s+", " ", str(text))
    text = text.replace('"', "").replace("(", "").replace(")", "")
    text = text.replace("[", "").replace("]", "").replace("{", "").replace("}", "")
    text = text.replace("|", "/")
    return text.strip()


def _mermaid_id(citekey: str, used: dict) -> str:
    """A Mermaid-safe node id from a citekey: keep [A-Za-z0-9_], map everything
    else (spaces, CJK, punctuation) to `_`, prefix `n_` so it never starts with a
    digit, and disambiguate collisions deterministically."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", str(citekey))
    base = re.sub(r"_+", "_", base).strip("_") or "x"
    nid = f"n_{base}"
    if nid in used and used[nid] != citekey:
        # two different citekeys collapsed to the same safe id -> suffix the 2nd+
        n = 2
        while f"{nid}_{n}" in used and used[f"{nid}_{n}"] != citekey:
            n += 1
        nid = f"{nid}_{n}"
    used[nid] = citekey
    return nid


def _cell(text) -> str:
    """A Markdown-table-cell-safe value: one line, escape pipes."""
    return _oneline(text).replace("|", "\\|")


# -- render ------------------------------------------------------------------

def render(graph: dict, *, slug: str | None = None) -> str:
    """Render a lineage-graph/1.0 dict into a self-contained Markdown note.

    Deterministic and side-effect-free: no I/O, no clock — `created` is copied
    from `graph.direction.created`, never regenerated. Raises RenderError if the
    input is not a lineage-graph/1.0.

    `slug` is only used in a frontmatter `slug:` echo for traceability; the note
    body never depends on it.
    """
    if not isinstance(graph, dict):
        raise RenderError("expected a lineage-graph/1.0 object")
    sv = graph.get("schema_version")
    if sv != SCHEMA_VERSION:
        raise RenderError(
            f"not a {SCHEMA_VERSION} graph (schema_version={sv!r}). "
            "Run `steward lineage` (and enrich via synthesize-direction) first.")

    direction = graph.get("direction") or {}
    query = _oneline(direction.get("query") or "")
    scope_method = _oneline(direction.get("scope_method") or "")
    created = _oneline(direction.get("created") or "")
    nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("citekey")]
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    clusters = [c for c in (graph.get("clusters") or []) if isinstance(c, dict) and c.get("id")]
    timeline = [t for t in (graph.get("timeline") or []) if isinstance(t, str)]

    by_key = {n["citekey"]: n for n in nodes}
    # stable Mermaid ids, assigned in node order so the output is deterministic
    used: dict = {}
    mid = {n["citekey"]: _mermaid_id(n["citekey"], used) for n in nodes}

    title = query or "Lineage"

    L: list[str] = []
    # -- frontmatter (small; the JSON is the machine SSoT) --------------------
    L += ["---", "note_type: lineage"]
    if query:
        L.append(f"direction_query: {_y(query)}")
    if created:
        L.append(f"created: {_y(created)}")
    if slug:
        L.append(f"slug: {_y(slug)}")
    L += [
        f"node_count: {len(nodes)}",
        f"edge_count: {len(edges)}",
        f"generated_by: steward lineage-render ({__version__})",
        "tags: [lineage]",
        "---",
        "",
        f"# {_oneline(title)} · 脉络 / lineage",
        "",
    ]

    # -- Mermaid flowchart (the always-works baseline render) -----------------
    L += [
        "> [!info] 机器权威 = lineage-graph/1.0 JSON。本图为自包含视图，"
        "原生 Mermaid，vanilla Obsidian 无需插件。",
        "",
        "```mermaid",
        "graph LR",
    ]
    L += _mermaid_body(nodes, edges, clusters, by_key, mid)
    L += ["```", ""]

    # -- timeline -------------------------------------------------------------
    L += ["## Timeline / 阅读路线", ""]
    order = [k for k in timeline if k in by_key] or _year_sorted(nodes)
    if order:
        for k in order:
            n = by_key[k]
            year = _oneline(n.get("year") or "")
            t = _oneline(n.get("title") or "")
            line = f"- {year + ' · ' if year else ''}`{k}`"
            if t:
                line += f" — {t}"
            L.append(line)
    else:
        L.append("- (no nodes)")
    L.append("")

    # -- edge table (Dataview-friendly; renders without Dataview) -------------
    L += ["## Edges / 关系表", "",
          "| from | relation | to | evidence |",
          "| --- | --- | --- | --- |"]
    for e in edges:
        frm = _cell(e.get("from") or "")
        rel = _cell(e.get("relation") or "")
        to = _cell(e.get("to") or "")
        ev = _cell(e.get("evidence") or "")
        L.append(f"| `{frm}` | {rel} | `{to}` | {ev} |")
    L.append("")

    # -- provenance footer ----------------------------------------------------
    rel_counts = {r: 0 for r in RELATIONS}
    for e in edges:
        r = e.get("relation")
        if r in rel_counts:
            rel_counts[r] += 1
    counts = ", ".join(f"{r}={rel_counts[r]}" for r in RELATIONS if rel_counts[r])
    L += ["---", ""]
    L.append(f"> **direction.query:** {query or '(none)'}")
    if scope_method:
        L.append(f"> **scope_method:** {scope_method}")
    L.append(f"> **{len(nodes)} nodes, {len(edges)} edges"
             + (f" ({counts})" if counts else "") + ".**")
    L.append("> Machine source of truth: the lineage-graph/1.0 JSON "
             "(this note is a derived, regenerable view).")
    L.append("")
    return "\n".join(L)


def _mermaid_body(nodes, edges, clusters, by_key, mid) -> list[str]:
    """The indented Mermaid statements: node decls (grouped into cluster
    subgraphs when clusters are present) + relation-labeled edges."""
    lines: list[str] = []

    def decl(node) -> str:
        return f'    {mid[node["citekey"]]}["{_node_label(node)}"]'

    if clusters:
        # group nodes by cluster id; declare clustered nodes in subgraphs, then
        # any node without a (known) cluster at top level.
        cluster_ids = [c["id"] for c in clusters]
        grouped: dict = {cid: [] for cid in cluster_ids}
        ungrouped = []
        for n in nodes:
            cid = n.get("cluster")
            (grouped[cid] if cid in grouped else ungrouped).append(n)
        for c in clusters:
            cid = c["id"]
            members = grouped[cid]
            if not members:
                continue
            sg_id = _mermaid_id(f"cluster_{cid}", {})
            lines.append(f'    subgraph {sg_id}["{_mermaid_label(c.get("label") or cid)}"]')
            for n in members:
                lines.append(decl(n))
            lines.append("    end")
        for n in ungrouped:
            lines.append(decl(n))
    else:
        for n in nodes:
            lines.append(decl(n))

    for e in edges:
        frm, to = e.get("from"), e.get("to")
        if frm not in by_key or to not in by_key:
            continue  # self-contained: never emit an edge to a non-node
        rel = _mermaid_label(e.get("relation") or "")
        lines.append(f"    {mid[frm]} -->|{rel}| {mid[to]}")
    return lines


def _year_sorted(nodes: list[dict]) -> list[str]:
    """Citekeys year-ascending; missing/unparseable years last, input order kept
    (stable). The fallback reading path when the graph has no `timeline`."""
    def key(idx_node):
        idx, n = idx_node
        m = re.match(r"\d{4}", _oneline(n.get("year") or ""))
        return (0, int(m.group()), idx) if m else (1, 0, idx)

    return [n["citekey"] for _, n in sorted(enumerate(nodes), key=key)]


# -- opportunistic Breadcrumbs frontmatter stamping --------------------------
#
# OPT-IN (`steward lineage-render --stamp-notes`, default OFF). The lineage-graph
# JSON + the rendered Reviews/ note are the canonical, self-contained outputs;
# this is the *opportunistic* extra: where a per-paper note already exists in the
# vault, append the typed relations onto it as Breadcrumbs-compatible frontmatter
# (relationship-field convention, scriptorium-spec specs/literature-reading.md §3).
#
# Guarantees: NEVER create a paper note (lean-vault — absent notes live in
# Provenance, skip silently); NEVER touch human-input zones; MERGE, never clobber
# existing frontmatter; append a citekey idempotently (re-running is a no-op).

# Per the convention, a relation key lives on the SOURCE (`from`) note and points
# to the `to` target. We search only tool-/derived note locations.
_NOTE_DIRS = ("Literature", "reading-notes")


def find_note(vault, citekey: str):
    """Return the path of an EXISTING `<citekey>.md` note under the vault's
    Literature/ or reading-notes/ dir, or None. Never creates anything.

    Matches `<citekey>.md` exactly (the suite keys notes by Better BibTeX
    citekey). A `<citekey>.json` parsed/reading-note file is data, not a
    frontmatter-bearing note, so it is not a stamp target.
    """
    from pathlib import Path
    vault = Path(vault)
    for d in _NOTE_DIRS:
        cand = vault / d / f"{citekey}.md"
        if cand.is_file():
            return cand
    return None


def stamp_notes(graph: dict, vault) -> list:
    """Opportunistically append typed relations to EXISTING per-paper notes.

    For each edge, find the `from` paper's note (if it already exists) and merge
    the `to` citekey into the matching relation key's frontmatter list. Returns
    the list of note paths actually modified. Notes that do not exist are skipped
    silently (lean-vault). Idempotent: a citekey already present is not re-added.
    """
    from pathlib import Path
    vault = Path(vault)

    # group targets by (source citekey, relation), de-duplicated and ordered
    wanted: dict = {}
    for e in graph.get("edges") or []:
        if not isinstance(e, dict):
            continue
        frm, to, rel = e.get("from"), e.get("to"), e.get("relation")
        if not (frm and to and rel in RELATIONS):
            continue
        wanted.setdefault(frm, {}).setdefault(rel, [])
        if to not in wanted[frm][rel]:
            wanted[frm][rel].append(to)

    changed = []
    for frm, rels in wanted.items():
        note = find_note(vault, frm)
        if note is None:
            continue  # lean-vault: the note lives in Provenance, skip silently
        original = note.read_text(encoding="utf-8-sig")
        merged = _merge_frontmatter(original, rels)
        if merged != original:
            note.write_text(merged, encoding="utf-8")
            changed.append(note)
    return changed


def _merge_frontmatter(text: str, rels: dict) -> str:
    """Merge `{relation: [citekeys]}` into a note's YAML frontmatter, in place.

    Existing frontmatter is preserved verbatim except the relation keys, which
    are updated (existing values kept, new citekeys appended idempotently). A
    note without frontmatter gets a fresh block prepended. Other keys are never
    touched. Values are written as Breadcrumbs `[[wikilink]]` lists.
    """
    lines = text.splitlines()
    has_fm = bool(lines) and lines[0].strip() == "---"
    if has_fm:
        end = None
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                end = j
                break
        if end is None:
            has_fm = False  # unterminated -> treat as no frontmatter, prepend fresh
    if not has_fm:
        block = ["---"]
        for rel in RELATIONS:
            if rels.get(rel):
                block.append(f"{rel}: [{_wikilinks(rels[rel])}]")
        block.append("---")
        block.append("")
        return "\n".join(block) + ("\n" + text if text else "\n")

    head, body = lines[1:end], lines[end:]  # body keeps the closing '---'
    # parse existing relation lists so we can merge, not clobber
    existing = yamlmini.parse_frontmatter(text)
    new_head: list[str] = []
    handled: set = set()
    for line in head:
        key = _line_key(line)
        if key in rels:
            handled.add(key)
            new_head.append(f"{key}: [{_wikilinks(_merge_list(existing.get(key)), rels[key])}]")
        else:
            new_head.append(line)
    # append relation keys that were not already present
    for rel in RELATIONS:
        if rel in rels and rel not in handled:
            new_head.append(f"{rel}: [{_wikilinks([], rels[rel])}]")
    return "\n".join([lines[0]] + new_head + body) + ("\n" if text.endswith("\n") else "")


def _line_key(line: str):
    """The top-level YAML key of a frontmatter line (None for nested/continuation)."""
    if not line or line[0] in " \t-#":
        return None
    idx = line.find(":")
    return line[:idx].strip() if idx > 0 else None


def _merge_list(value) -> list:
    """Coerce an existing frontmatter relation value into a list of bare citekeys
    (stripping any `[[ ]]` wikilink wrapper)."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for it in items:
        s = str(it).strip()
        m = re.match(r"^\[\[(.+?)\]\]$", s)
        out.append(m.group(1) if m else s)
    return out


def _wikilinks(existing, additions=None) -> str:
    """A comma-separated `[[wikilink]]` flow-list body, existing first then any
    new additions, de-duplicated and order-preserving."""
    seen, ordered = set(), []
    for k in list(existing or []) + list(additions or []):
        k = str(k).strip()
        if k and k not in seen:
            seen.add(k)
            ordered.append(k)
    return ", ".join(f'"[[{k}]]"' for k in ordered)
