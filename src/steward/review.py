"""review: literature-review scaffold + assemble (Phase D).

Same scaffold -> [external LLM/agent/human fills] -> assemble philosophy as
propose/tag, but vault-side and zero-credential. Steward never calls an LLM
itself; it only prepares the inputs and assembles the authoritative output.

- `review scaffold` filters a `library-kb/1.0` or `library-kb/1.1` KB by a
  collection-path prefix into `review.input.json` (the topic's papers +
  title/authors/year/doi/tldr/aiTags/readStatus/abstract) plus a REVIEW-PROMPT.md
  that teaches an LLM/agent/human how to draft `review.draft.json`.
- `review assemble` validates the filled draft (a steward-local `review-draft/1.0`
  contract: framing/intro/sections/gaps_future/priority_reads) and builds the
  vault note: an AI-draft banner + intro + themed sections (each with an
  "涉及: Author Year" line) + research gaps + priority reads + an AUTHORITATIVE
  full-reference table built FROM THE KB (keys/authors/years/DOIs/read-status,
  never from the draft, so citations and DOIs can never be fabricated) +
  a coverage note.

Prefix matching is exact at the boundary: `01_ML` matches `01_ML` and
`01_ML/...` but never `01_MLX`.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import LIBRARY_KB_SCHEMAS, __version__

INPUT_SCHEMA = "review-input/1.0"     # steward-local intermediate (scaffold -> assemble)
DRAFT_SCHEMA = "review-draft/1.0"     # steward-local (filled by an external LLM/agent/human)

_MARK = {"Read": "✅", "In Progress": "📖"}

PROMPT = """\
# How to draft this literature review (for an LLM, an agent, or a human)

`review.input.json` lists every paper in one topic (filtered from the library
KB by a collection-path prefix). Each entry has: `key`, `title`, `authors`,
`year`, `doi`, `tldr`, `aiTags`, `readStatus`, and a truncated `abstract`.

Write a sibling `review.draft.json` conforming to the `review-draft/1.0`
contract below. Steward (`review assemble`) turns it into the final vault note
and builds the authoritative reference list itself.

## Workflow

1. Cluster the papers into 3-6 coherent themes.
2. Draft each theme as a short prose section, citing the papers it covers.
3. Write an `intro` (the topic's arc / why it matters) and `gaps_future`
   (research gaps + concrete next steps).
4. Pick the handful of papers a newcomer should read first (`priority_reads`).

## Rules

- Cite ONLY as "Author Year" in prose. Do NOT write DOIs or a reference list —
  steward builds the authoritative table from the KB so citations cannot be
  fabricated.
- Do NOT invent papers. Every `key` in `covered_keys` / `priority_reads` must be
  a real `key` from `review.input.json`.
- Be honest about evidence: most items are unread and many have only an abstract.
  Say when a claim is abstract-confirmable vs. needs close reading, and flag
  abstract-less classics as lowest-confidence.
- This is a reading roadmap, not a close-reading summary. Do not state specific
  numeric results as established conclusions.

## review-draft/1.0 contract

{
  "schema_version": "review-draft/1.0",
  "title": "optional display name (defaults to the topic's last path segment)",
  "framing": "one sentence orienting the reader to the review's angle",
  "intro": "introduction prose (the topic's arc and why it matters)",
  "sections": [
    {"title": "theme name", "body": "prose", "covered_keys": ["KEY1", "KEY2"]}
  ],
  "gaps_future": "research gaps and concrete next steps",
  "priority_reads": ["KEY3", "KEY1"]
}

Then: steward review assemble --input review.input.json --draft review.draft.json
      --out <vault>/Reviews/<name>.md
"""


class ReviewError(RuntimeError):
    pass


def _oneline(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _y(value) -> str:
    """A YAML-safe scalar: a JSON string is valid YAML, with newlines escaped."""
    return json.dumps(_oneline(value), ensure_ascii=False)


def _first_author(p: dict) -> str:
    authors = p.get("authors") or []
    return authors[0] if authors else "?"


def _ref(p: dict) -> str:
    """An 'Author Year' citation built from the KB (never the draft)."""
    return f"{_first_author(p)} {p.get('year', '')}".strip()


# -- scaffold ----------------------------------------------------------------

def load_kb_items(kb_path: Path) -> list[dict]:
    doc = json.loads(kb_path.read_text(encoding="utf-8-sig"))
    if isinstance(doc, list):
        return doc  # legacy array
    if not isinstance(doc, dict) or doc.get("schema_version") not in LIBRARY_KB_SCHEMAS:
        raise ReviewError(
            f"{kb_path} is not a supported library-kb JSON "
            f"(expected {' or '.join(LIBRARY_KB_SCHEMAS)})")
    items = doc.get("items")
    if not isinstance(items, list):
        raise ReviewError(f"{kb_path} is not a library-kb JSON (no items list) - "
                          "run `steward export` first")
    return items


def _in_topic(item: dict, topic: str) -> bool:
    # exact boundary: 01_ML matches 01_ML and 01_ML/... but never 01_MLX
    return any(f == topic or f.startswith(topic + "/") for f in item.get("folders", []))


def _read_status(item: dict) -> str:
    # the one canonical normalization of readStatus (trim surrounding whitespace),
    # so "unread" filtering and the rendered read-count/marker agree.
    return (item.get("readStatus") or "").strip()


def _is_unread(item: dict) -> bool:
    # "unread" = anything not yet finished (To Read / In Progress / unset)
    return _read_status(item) != "Read"


def _added_since(item: dict, since: str) -> bool:
    # dateAdded is an ISO-8601 instant (e.g. 2026-06-20T12:00:00Z); a lexical
    # compare against a YYYY-MM-DD floor is correct for ISO dates. A missing
    # dateAdded never counts as recent.
    return (item.get("dateAdded") or "") >= since


def _paper(it: dict) -> dict:
    return {
        "key": it.get("key", ""),
        "title": it.get("title", ""),
        "authors": (it.get("authors") or [])[:6],
        "year": it.get("year", "") or "",
        "doi": it.get("doi", "") or "",
        "tldr": it.get("tldr", "") or "",
        "aiTags": it.get("aiTags") or [],
        "readStatus": it.get("readStatus", "") or "",
        "abstract": (it.get("abstract") or "")[:600],
    }


def scaffold(kb_path: Path, topic: str | None = None, *,
             since: str | None = None, unread: bool = False,
             label: str | None = None) -> dict:
    """Filter a library-kb into a review-input doc.

    Selection filters AND together (pass none to take the whole library):
      - `topic`:  collection-path prefix (exact boundary: 01_ML != 01_MLX)
      - `since`:  keep items added on/after this YYYY-MM-DD (the R13 what's-new
                  digest's "recent additions" filter)
      - `unread`: keep only items whose readStatus is not "Read"

    `label` is a display name for the digest (e.g. "库内新进展") used by `render`
    when neither the draft nor a topic supplies one; it never affects selection.
    """
    matched = []
    for it in load_kb_items(kb_path):
        if topic and not _in_topic(it, topic):
            continue
        if since and not _added_since(it, since):
            continue
        if unread and not _is_unread(it):
            continue
        matched.append(_paper(it))
    matched.sort(key=lambda p: (p["year"] or "0000", p["key"]))
    return {
        "schema_version": INPUT_SCHEMA,
        "generated_by": f"steward review scaffold ({__version__})",
        "topic": topic or "",
        "label": label or "",
        "selection": {"topic": topic or "", "since": since or "", "unread": bool(unread)},
        "count": len(matched),
        "papers": matched,
    }


def default_scaffold_out(*, today: str | None = None) -> Path:
    """The date-stamped default output path for `review scaffold`.

    Mirrors the harness's `<name>-<date>` convention (lit-run.ps1) so repeated
    runs do not clobber the previous selection. `today` defaults to the local
    date as YYYY-MM-DD; pass it to keep callers deterministic.
    """
    stamp = today or date.today().isoformat()
    return Path(f"review.input-{stamp}.json")


# -- load & validate ---------------------------------------------------------

def load_input(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or not isinstance(doc.get("papers"), list):
        raise ReviewError(f"{path} is not a review.input.json (no papers list) - "
                          "run `steward review scaffold` first")
    return doc


def validate_draft(doc: dict, papers: list[dict]) -> list[str]:
    """Validate a filled review-draft against the topic's real paper keys."""
    errors = []
    if doc.get("schema_version") != DRAFT_SCHEMA:
        errors.append(f"schema_version must be {DRAFT_SCHEMA} (unfilled draft?)")
    keys = {p.get("key", "") for p in papers}

    for field in ("framing", "intro", "gaps_future"):
        v = doc.get(field)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{field}: missing or empty")

    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections: missing or empty")
        sections = []
    for i, s in enumerate(sections):
        w = f"sections[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{w}: not an object")
            continue
        if not (isinstance(s.get("title"), str) and s["title"].strip()):
            errors.append(f"{w}: empty title")
        if not (isinstance(s.get("body"), str) and s["body"].strip()):
            errors.append(f"{w}: empty body")
        ck = s.get("covered_keys")
        if not isinstance(ck, list):
            errors.append(f"{w}: covered_keys must be a list")
        else:
            for k in ck:
                if k not in keys:
                    errors.append(f"{w}: covered_keys references unknown key {k!r} "
                                  "(not in review.input.json - fabricated?)")

    pr = doc.get("priority_reads", [])
    if not isinstance(pr, list):
        errors.append("priority_reads must be a list")
    else:
        for k in pr:
            if k not in keys:
                errors.append(f"priority_reads references unknown key {k!r} "
                              "(not in review.input.json - fabricated?)")
    return errors


# -- render ------------------------------------------------------------------

def render(input_doc: dict, draft: dict) -> str:
    """Assemble the vault note. Assumes `draft` already passed validate_draft.

    The authoritative reference table, the 涉及 lines, and the priority-read
    list are ALL built from `input_doc` (the KB), never from `draft`, so the
    LLM can never introduce a fabricated citation or DOI.

    Raises ReviewError if `draft` has not passed validate_draft, rather than
    failing later with a bare KeyError/TypeError on a malformed field.
    """
    errors = validate_draft(draft, input_doc.get("papers", []))
    if errors:
        raise ReviewError("cannot render an unvalidated draft (run validate_draft "
                          "first):\n  " + "\n  ".join(errors[:10]))
    papers = {p["key"]: p for p in input_doc["papers"]}
    topic = input_doc.get("topic", "")
    n = len(papers)
    read = sum(1 for p in papers.values() if _read_status(p) == "Read")
    display = (draft.get("title") or input_doc.get("label")
               or (topic.split("/")[-1] if topic else "文献综述"))

    L = [
        "---",
        "note_type: review-draft",
        f"topic: {_y(topic)}",
        f"source_count: {n}",
        "status: ai-draft",
        f"generated_by: steward review ({__version__})",
        "tags: [literature-review, draft]",
        "---",
        "",
        f"# {_oneline(display)} · 文献综述草稿（阅读路线图）",
        "",
        "> [!warning] AI 综述草稿，须核对原文",
        f"> 本稿由 {n} 篇文献的**标题/摘要/一句话主旨**合成（其中仅 {read} 篇标记已读），"
        "是该主题的**主题地图 + 阅读路线图**，不是精读总结。"
        "所有论断与引用务必回原文核实；本稿不含具体数值结论。",
        "",
    ]

    framing = (draft.get("framing") or "").strip()
    if framing:
        L += [framing, ""]

    L += ["## 引言", "", draft["intro"].strip(), "", "## 主题脉络", ""]
    for s in draft["sections"]:
        L += [f"### {_oneline(s['title'])}", "", s["body"].strip(), ""]
        cited = [k for k in s.get("covered_keys", []) if k in papers]
        if cited:
            L += ["*涉及*：" + "；".join(_ref(papers[k]) for k in cited), ""]

    L += ["## 研究空白与下一步", "", draft["gaps_future"].strip(), ""]

    pr = [k for k in (draft.get("priority_reads") or []) if k in papers]
    if pr:
        L += ["## ⭐ 建议优先精读", ""]
        for k in pr:
            p = papers[k]
            line = f"- **{_oneline(p.get('title', ''))}** — {_ref(p)}"
            if p.get("tldr"):
                line += f" · {_oneline(p['tldr'])}"
            L.append(line)
        L.append("")

    # Authoritative reference list - built from the KB, never the draft.
    L += [f"## 全部文献（{n} 篇，按年份）", ""]
    for p in sorted(papers.values(), key=lambda x: (x.get("year") or "0000", x.get("key", ""))):
        mark = _MARK.get(_read_status(p), "▢")
        doi = f" [doi:{p['doi']}]" if p.get("doi") else ""
        L.append(f"- {mark} `{p.get('key', '')}` {_ref(p)}. {_oneline(p.get('title', ''))}.{doi}")
    L.append("")

    covered = {k for s in draft["sections"] for k in s.get("covered_keys", []) if k in papers}
    L += [f"> 覆盖说明：{n} 篇中 {len(covered)} 篇在主题章节中被明确讨论，"
          f"{n - len(covered)} 篇未被讨论（仍在上方文献表中）。", ""]
    return "\n".join(L)
