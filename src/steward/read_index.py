"""read_index: a vault's reading-note/1.0 files -> one reading overview note.

The status DASHBOARD half of staged reading: where `read_render` projects ONE
reading-note into its per-paper archive, this scans the whole `reading-notes/`
directory (the reading-note/1.0 SSoT files), and emits a single overview note —
`reading-notes/_index.md` — so you can see, at a glance, every paper you have a
reading-note for, grouped by Read-Status, with which stages are filled.

It carries four views of the same set so it is useful with OR without a plugin:
- status-grouped sections (`## To Read` / `## In Progress` / …), each a wikilink
  list `- [[citekey]] — title year  (glance·close)`;
- a full static table (citekey | title | year | status | stages | tags);
- a fenced Dataview block for plugin users (the static views still render for
  everyone else).

`build_index()` is a pure, deterministic function over already-parsed notes:
same notes in -> identical string out, no I/O, no clocks. `scan_vault()` is the
thin I/O layer (read the dir, parse each JSON, skip non-reading-note/1.0 with a
warning). The reading-note/1.0 JSONs stay the machine source of truth; `_index.md`
is a derived, idempotently re-rendered view.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import LIBRARY_KB_SCHEMAS, __version__
from .read_render import _oneline, _wikilink

SCHEMA_VERSION = "reading-note/1.0"

# Read-Status display order (reading-note/1.0 enum), lifecycle-ordered; notes with
# no / unrecognized status fall into a trailing "(no status)" group.
_STATUS_ORDER = ("New", "To Read", "In Progress", "Read", "Not Reading")
_NO_STATUS = "(no status)"

# stage key -> short label shown in the section lists + table
_STAGE_LABELS = (("glance", "glance"), ("close_read", "close"),
                 ("deep_read", "deep"), ("situate", "situate"))


class IndexError_(RuntimeError):
    """A reading-index build error (named with a trailing _ to avoid shadowing the
    builtin IndexError)."""


# -- scan (the only I/O) -----------------------------------------------------

def scan_vault(reading_notes_dir: Path) -> tuple[list[dict], list[str]]:
    """Read `<dir>/*.json`, returning (reading_note_dicts, warnings).

    Each file is parsed; a file that is not a reading-note/1.0 (wrong/missing
    `schema_version`, not an object, or invalid JSON) is SKIPPED with a warning
    string rather than aborting the whole build. Files are taken in sorted order
    for determinism. An absent directory yields ([], []) — the caller reports it.
    """
    d = Path(reading_notes_dir)
    notes: list[dict] = []
    warnings: list[str] = []
    if not d.is_dir():
        return notes, warnings
    for path in sorted(d.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            warnings.append(f"skipped {path.name}: not valid JSON ({e})")
            continue
        if not isinstance(doc, dict):
            warnings.append(f"skipped {path.name}: not a reading-note/1.0 object")
            continue
        if doc.get("schema_version") != SCHEMA_VERSION:
            warnings.append(
                f"skipped {path.name}: schema_version={doc.get('schema_version')!r} "
                f"(not {SCHEMA_VERSION})")
            continue
        notes.append(doc)
    return notes, warnings


def load_kb_index(kb_path: Path) -> dict:
    """Load library-kb/1.0 or 1.1 into a {citekey|key|id -> item} lookup.

    Legacy top-level arrays remain accepted. Raises IndexError_ if the file is
    missing, uses an unsupported envelope version, or has no items[].
    """
    try:
        kb = json.loads(Path(kb_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise IndexError_(f"--kb not readable: {kb_path} ({e})")
    if isinstance(kb, list):
        items = kb
    elif isinstance(kb, dict) and kb.get("schema_version") in LIBRARY_KB_SCHEMAS:
        items = kb.get("items")
    elif isinstance(kb, dict):
        raise IndexError_(
            f"--kb has unsupported schema_version={kb.get('schema_version')!r}; "
            f"expected {' or '.join(LIBRARY_KB_SCHEMAS)}")
    else:
        items = None
    if not isinstance(items, list):
        raise IndexError_(f"--kb has no items[]: {kb_path}")
    idx: dict = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        for k in (it.get("citekey"), it.get("key"), it.get("id")):
            if isinstance(k, str) and k and k not in idx:
                idx[k] = it
    return idx


# -- a small per-note row ----------------------------------------------------

def _row(note: dict, kb_by_citekey: dict | None = None) -> dict:
    """Flatten a reading-note into the fields the overview needs. `kb_by_citekey`
    (optional) supplies title/year — which a reading-note rarely carries — from the
    matching library-kb item, looked up by the note's citekey."""
    citekey = _oneline(note.get("id") or "")
    stages = note.get("stages") if isinstance(note.get("stages"), dict) else {}
    glance = stages.get("glance") if isinstance(stages.get("glance"), dict) else {}
    filled = [label for key, label in _STAGE_LABELS
              if isinstance(stages.get(key), dict)]
    status = _oneline(note.get("read_status") or "")
    kb = (kb_by_citekey or {}).get(citekey) or {}
    return {
        "citekey": citekey,
        "title": _oneline(note.get("title") or "") or _oneline(kb.get("title") or ""),
        "year": _oneline(note.get("year") or "") or _oneline(kb.get("year") or ""),
        "status": status if status in _STATUS_ORDER else "",
        "stages": filled,
        "tags": [_oneline(t) for t in (glance.get("tags") or []) if _oneline(t)],
    }


def _status_rank(status: str) -> int:
    return _STATUS_ORDER.index(status) if status in _STATUS_ORDER else len(_STATUS_ORDER)


# -- build (pure projection) -------------------------------------------------

def build_index(notes: list[dict], kb_by_citekey: dict | None = None) -> str:
    """Render a list of reading-note/1.0 dicts into the overview Markdown note.

    Deterministic and side-effect-free (no I/O, no clock). Notes are sorted by
    Read-Status (lifecycle order, no-status last) then citekey. Emits frontmatter,
    status-grouped wikilink sections, a full table, and a fenced Dataview block.
    `kb_by_citekey` (optional) enriches each row's title/year from the library-kb.
    """
    rows = [_row(n, kb_by_citekey) for n in notes if _oneline(n.get("id") or "")]
    rows.sort(key=lambda r: (_status_rank(r["status"]), r["citekey"].lower()))

    # counts per status (incl. no-status), in display order
    by_status: dict[str, list[dict]] = {}
    for r in rows:
        by_status.setdefault(r["status"] or _NO_STATUS, []).append(r)

    L: list[str] = []
    # -- frontmatter ----------------------------------------------------------
    L += ["---", "type: reading-index",
          f"note_count: {len(rows)}",
          f"generated_by: steward read-index ({__version__})",
          "tags: [reading-index]", "---", "",
          "# 阅读总览 · Reading index", "",
          f"> [!info] {len(rows)} reading-note(s). 机器权威 = `reading-notes/*.json`; "
          "本笔记为派生视图,`steward read-index` 幂等重生成。", ""]

    # -- status-grouped sections ---------------------------------------------
    section_order = list(_STATUS_ORDER) + [_NO_STATUS]
    for status in section_order:
        group = by_status.get(status)
        if not group:
            continue
        L += [f"## {status} ({len(group)})", ""]
        for r in group:
            label = r["title"] or r["citekey"]
            year = f" {r['year']}" if r["year"] else ""
            stages = f" ({'·'.join(r['stages'])})" if r["stages"] else ""
            L.append(f"- {_wikilink(r['citekey'])} — {label}{year}{stages}")
        L.append("")

    # -- full table -----------------------------------------------------------
    L += ["## 全部 · All", "",
          "| citekey | title | year | status | stages | tags |",
          "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        title = _cell(r["title"])
        tags = _cell(" ".join(r["tags"]))
        stages = _cell("·".join(r["stages"]))
        status = _cell(r["status"])
        year = _cell(r["year"])
        L.append(f"| `{_cell(r['citekey'])}` | {title} | {year} | {status} "
                 f"| {stages} | {tags} |")
    L.append("")

    # -- Dataview block (plugin users; static views above serve everyone else)-
    L += ["## Dataview", "",
          "> 需要 Dataview 插件;不装也能看上面的静态分组与表格。", "",
          "```dataview",
          "TABLE read_status AS status, file.link AS note",
          'FROM "reading-notes"',
          'WHERE type = "reading-note"',
          "SORT read_status ASC",
          "```", ""]

    # -- footer ---------------------------------------------------------------
    L += ["---", "",
          f"> {len(rows)} note(s) indexed"
          + (": " + ", ".join(f"{s}={len(by_status[s])}"
                              for s in section_order if by_status.get(s))
             if rows else "") + ".",
          "> Machine source of truth: `reading-notes/*.json` "
          "(this overview is a derived, regenerable view).",
          f"> Generated by steward read-index ({__version__}).", ""]
    return "\n".join(L)


def _cell(text) -> str:
    """A Markdown-table-cell-safe value: one line, escape pipes."""
    return _oneline(text).replace("|", "\\|")
