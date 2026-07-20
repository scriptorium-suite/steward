"""Export the library to a KB JSON (library-kb/1.1) and an Obsidian vault.

scriptorium-spec contracts:
- library-kb/1.1 (schemas/library-kb/v1.json)
- Obsidian export convention (specs/obsidian-export.md): Literature/ + MOC are
  fully derived (regenerated each run); other vault folders are left untouched.

Reads the Zotero Web API (web or local mode). PDF paths are resolved against
the local data dir when available, but their existence is not assumed.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from . import __version__
from .zotero_api import ZoteroClient

_SLUG_BAD = re.compile(r'[\\/:*?"<>|#^\[\]\r\n]')


def slug(text: str, maxlen: int = 70) -> str:
    s = _SLUG_BAD.sub(" ", text)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen].strip()


def _oneline(text: str) -> str:
    """Collapse CR/LF/tabs so a value can never break or forge YAML frontmatter."""
    return re.sub(r"\s+", " ", str(text)).strip()


def build_kb(client: ZoteroClient, storage_dir: Path | None) -> list[dict]:
    cols = client.collections()
    by_key = {c["key"]: c["data"] for c in cols}

    def col_path(k):
        parts, cur = [], by_key.get(k)
        while cur:
            parts.append(cur["name"])
            parent = cur.get("parentCollection")
            cur = by_key.get(parent) if parent else None
        return "/".join(reversed(parts))

    # parent item -> [pdf path]
    pdf_of: dict[str, list[str]] = {}
    for a in client.get_all("/items?itemType=attachment"):
        d = a["data"]
        parent = d.get("parentItem")
        if not parent or d.get("contentType") != "application/pdf":
            continue
        if storage_dir:
            local = storage_dir / a["key"]
            fname = d.get("filename") or ""
            pdf_of.setdefault(parent, []).append(str(local / fname) if fname else str(local))

    kb = []
    for it in client.get_all("/items/top?itemType=-attachment"):
        d = it["data"]
        if d["itemType"] in ("attachment", "note", "annotation"):
            continue  # the itemType filter is not always honored; enforce here
        if d.get("title") == "Addon Item":   # plugin housekeeping item, not a paper
            continue
        extra = d.get("extra", "")
        tldr = next((l[5:].strip() for l in extra.split("\n") if l.startswith("TLDR:")), "")
        status = next((l.split(":", 1)[1].strip() for l in extra.split("\n")
                       if l.lower().startswith("read_status:")), "")
        # Better BibTeX writes a `Citation Key: xxx` line into Zotero's extra field;
        # capturing it lets `[[citekey]]` wikilinks resolve to this library note.
        citekey = next((l.split(":", 1)[1].strip() for l in extra.split("\n")
                        if l.lower().startswith("citation key:")), "")
        authors = [c.get("lastName") or c.get("name", "") for c in d.get("creators", [])]
        parsed = it.get("meta", {}).get("parsedDate", "")
        year = parsed[:4] if parsed[:4].isdigit() else ""
        tags = [t["tag"] for t in d.get("tags", [])]
        kb.append({
            "key": it["key"],
            "citekey": citekey,
            "title": d.get("title", ""),
            "authors": authors,
            "year": year,
            "doi": d.get("DOI", ""),
            "itemType": d["itemType"],
            "folders": [col_path(k) for k in d.get("collections", [])],
            "tags": tags,
            "aiTags": [t[3:] for t in tags if t.startswith("ai:")],
            "tldr": tldr,
            "readStatus": status,
            "abstract": d.get("abstractNote", ""),
            "pdfPaths": pdf_of.get(it["key"], []),
            "dateAdded": d.get("dateAdded", ""),
        })
    warn_pdf_coverage(kb, storage_dir)
    return kb


def warn_pdf_coverage(kb: list[dict], storage_dir: Path | None) -> None:
    """Flag (on stderr) a KB that can never feed `steward pick`: no storage dir
    means PDF paths were never resolved, and an all-empty `pdfPaths` means every
    pick would fail with 'no local PDF'. Catching it at export time surfaces the
    problem before a doomed pick instead of after."""
    if storage_dir is None:
        print("warning: Zotero storage dir is unset; KB has no PDF paths, so "
              "`steward pick` will find no local PDF for any item.", file=sys.stderr)
        return
    if kb and not any(e.get("pdfPaths") for e in kb):
        print(f"warning: none of {len(kb)} items has a local PDF path under "
              f"{storage_dir}; `steward pick` will fail for every item.",
              file=sys.stderr)


def write_kb_json(kb: list[dict], out: Path, library_id: str, library_type: str) -> None:
    envelope = {
        "schema_version": "library-kb/1.1",
        "generated_by": f"steward {__version__}",
        "library": {"type": library_type, "id": str(library_id)},
        "items": kb,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, ensure_ascii=False, indent=1), encoding="utf-8")


class ExportError(RuntimeError):
    pass


_MARKER = ".steward-export"


def write_obsidian(kb: list[dict], vault: Path) -> tuple[int, int]:
    """Regenerate Literature/ and MOC/文献库 MOC.md. Other folders untouched.

    Literature/ is steward-owned: it is only deleted if empty or if it carries
    our marker file. A pre-existing non-steward Literature/ aborts (we never
    delete the user's data)."""
    lit = vault / "Literature"
    moc_dir = vault / "MOC"
    if lit.exists():
        if lit.is_file():
            raise ExportError(f"{lit} is a file, not a directory")
        has_content = any(lit.iterdir())
        if has_content and not (lit / _MARKER).exists():
            raise ExportError(
                f"{lit} already exists and was not created by steward "
                f"(no {_MARKER} marker). Refusing to delete it. Move it aside "
                "or point --vault elsewhere.")
        shutil.rmtree(lit)
    lit.mkdir(parents=True)
    (lit / _MARKER).write_text(
        "This folder is regenerated by `steward export`. Do not edit by hand.\n",
        encoding="utf-8")
    moc_dir.mkdir(parents=True, exist_ok=True)

    by_folder: dict[str, list[tuple[str, str, str]]] = {}
    for e in kb:
        first = e["authors"][0] if e["authors"] else "Unknown"
        name = slug(f"{first} {e['year']} {e['title']}") + ".md"

        def y(v):  # YAML-safe scalar: a JSON string is valid YAML, newlines escaped
            return json.dumps(_oneline(v), ensure_ascii=False)

        fm = [
            "---",
            f"zotero-key: {y(e['key'])}",
            f"title: {y(e['title'][:180])}",
            f"authors: {json.dumps([_oneline(a) for a in e['authors'][:8]], ensure_ascii=False)}",
            f"year: {e['year'] or 'null'}",
            f"doi: {y(e['doi'])}",
            f"folders: {json.dumps([_oneline(f) for f in e['folders']], ensure_ascii=False)}",
            f"tags: {json.dumps(['literature'] + [_oneline(t) for t in e['aiTags']], ensure_ascii=False)}",
            f"read-status: {y(e['readStatus'] or 'Unknown')}",
        ]
        # When the item carries a Better BibTeX citekey, expose it as an Obsidian
        # alias + property so suite-wide `[[citekey]]` wikilinks (e.g. from a
        # reading-note) resolve to THIS library note.
        ck = _oneline(e.get("citekey") or "")
        if ck:
            fm += [f"aliases: {json.dumps([ck], ensure_ascii=False)}",
                   f"citekey: {y(ck)}"]
        fm += ["---", "",
               f"# {_oneline(e['title'])}", ""]
        if e["tldr"]:
            fm += [f"> [!tip] TLDR\n> {_oneline(e['tldr'])}", ""]
        fm += [f"[在 Zotero 中打开](zotero://select/library/items/{e['key']})", ""]
        for p in e["pdfPaths"]:
            fm.append(f"PDF: `{p}`")
        if e["abstract"]:
            fm += ["", "## 摘要", "", e["abstract"]]
        # de-collide same author/year/title-prefix
        dest = lit / name
        n = 2
        while dest.exists():
            dest = lit / (name[:-3] + f" ({n}).md")
            n += 1
        dest.write_text("\n".join(fm) + "\n", encoding="utf-8")
        folder = e["folders"][0] if e["folders"] else "未分类"
        by_folder.setdefault(folder, []).append((dest.stem, e["tldr"], e["readStatus"]))

    moc = ["# 文献库 MOC", "",
           f"共 {len(kb)} 篇 | 由 `steward export` 生成,重跑即刷新", ""]
    for folder in sorted(by_folder):
        entries = by_folder[folder]
        moc.append(f"## {folder} ({len(entries)})")
        moc.append("")
        for stem, tldr, st in sorted(entries):
            mark = {"Read": "✅", "In Progress": "📖"}.get(st, "")
            moc.append(f"- {mark}[[Literature/{stem}|{stem}]]"
                       + (f" — {_oneline(tldr)}" if tldr else ""))
        moc.append("")
    (moc_dir / "文献库 MOC.md").write_text("\n".join(moc), encoding="utf-8")
    return len(kb), len(by_folder)
