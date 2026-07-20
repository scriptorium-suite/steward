"""pick: stage paper PDF(s) + handoff metadata for Lectern.

Reads an exported KB JSON (library-kb/1.0 or library-kb/1.1). Copies the chosen
item's largest local PDF plus a meta.json into <staging>/<key>/, ready for
Lectern to ingest.

Two shapes (the schema_version distinguishes them; 1.1 is additive over 1.0):
- single paper -> `handoff/1.0`: top-level fields ARE the paper (`stage`).
- multiple papers -> `handoff/1.1`: top-level fields describe the report,
  `papers[]` lists the sources, `report_type` is literature|experiment
  (`stage_report`).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import LIBRARY_KB_SCHEMAS

# Per-paper bibliographic fields. The single-paper (1.0) form also carries
# `key` at the top level; the multi-paper (1.1) `papers[]` entries do NOT
# (the report's `key` lives at the top level instead).
_PAPER_FIELDS = ("title", "authors", "year", "doi", "tldr", "abstract", "folders")

REPORT_TYPES = ("literature", "experiment")


class PickError(RuntimeError):
    pass


def load_kb(kb_path: Path) -> list[dict]:
    doc = json.loads(kb_path.read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc  # legacy array
    if not isinstance(doc, dict) or doc.get("schema_version") not in LIBRARY_KB_SCHEMAS:
        raise PickError(
            f"{kb_path} is not a supported library-kb JSON "
            f"(expected {' or '.join(LIBRARY_KB_SCHEMAS)})")
    items = doc.get("items")
    if not isinstance(items, list):
        raise PickError(f"{kb_path} is not a library-kb JSON (no items list)")
    return items


def find(kb: list[dict], query: str) -> list[dict]:
    exact = [e for e in kb if e["key"] == query]
    if exact:
        return exact
    ql = query.lower()
    return [e for e in kb if ql in e["title"].lower()]


def _largest_pdf(entry: dict) -> Path:
    pdfs = [Path(p) for p in entry.get("pdfPaths", []) if Path(p).exists()]
    if not pdfs:
        raise PickError(f"no local PDF found for {entry['key']} "
                        f"(paths: {entry.get('pdfPaths') or 'none'})")
    return max(pdfs, key=lambda p: p.stat().st_size)


def _write_meta(dest: Path, meta: dict) -> None:
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def stage(entry: dict, staging: Path) -> Path:
    """Single-paper handoff/1.0: copy the largest PDF + top-level meta fields."""
    pdf = _largest_pdf(entry)
    dest = staging / entry["key"]
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, dest / pdf.name)
    meta = {"schema_version": "handoff/1.0", "key": entry["key"]}
    for k in _PAPER_FIELDS:
        if k in entry:
            meta[k] = entry[k]
    meta["pdfFilename"] = pdf.name
    _write_meta(dest, meta)
    return dest


def _report_key(member_keys: list[str]) -> str:
    """Deterministic 8-char report key from the member keys; the uppercase hex
    digest satisfies the handoff `^[A-Z0-9]{8}$` constraint."""
    digest = hashlib.sha1("\n".join(member_keys).encode("utf-8")).hexdigest()
    return digest[:8].upper()


def _default_title(report_type: str, n: int) -> str:
    label = "Experiment" if report_type == "experiment" else "Literature"
    return f"{label} report ({n} papers)"


def stage_report(entries: list[dict], staging: Path, *,
                 report_type: str = "literature", title: str | None = None) -> Path:
    """Multi-paper handoff/1.1: stage each paper's PDF (prefixed `p<i>_` so the
    filenames never collide in one directory) under a derived report key."""
    if report_type not in REPORT_TYPES:
        raise PickError(f"invalid report_type {report_type!r} "
                        f"(expected one of {', '.join(REPORT_TYPES)})")
    report_key = _report_key([e["key"] for e in entries])
    dest = staging / report_key
    dest.mkdir(parents=True, exist_ok=True)
    papers = []
    for idx, entry in enumerate(entries, start=1):
        pdf = _largest_pdf(entry)
        pdf_name = f"p{idx}_{pdf.name}"
        shutil.copy2(pdf, dest / pdf_name)
        paper = {k: entry[k] for k in _PAPER_FIELDS if k in entry}
        paper["pdfFilename"] = pdf_name
        papers.append(paper)
    meta = {
        "schema_version": "handoff/1.1",
        "key": report_key,
        "report_type": report_type,
        "title": title or _default_title(report_type, len(papers)),
        "papers": papers,
    }
    _write_meta(dest, meta)
    return dest
