"""Read-only library audit: structure, tag hygiene, reading status, duplicates.

Reads a TEMP COPY of zotero.sqlite (never the live file), or any backup copy.
Zero credentials required - this is the recommended first command.

Scope: the personal library only (libraryID of the 'user' library); synced
group libraries and feeds are excluded so counts mean "my library". Trashed
items (deletedItems) and trashed collections (deletedCollections) are excluded
everywhere.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote


def open_snapshot(sqlite_path: Path) -> tuple[sqlite3.Connection, Path]:
    """Copy the db to a temp file and open read-only (safe while Zotero runs)."""
    fd, name = tempfile.mkstemp(suffix=".sqlite", prefix="steward_audit_")
    os.close(fd)  # keep only the path; an open fd would lock the file on Windows
    tmp = Path(name)
    shutil.copy2(sqlite_path, tmp)
    uri = f"file:{quote(tmp.as_posix(), safe='/:')}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con, tmp


def _table_exists(con, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def collect(con: sqlite3.Connection) -> dict:
    q = con.execute

    def one(sql, *args):
        return q(sql, args).fetchone()[0]

    # personal library scope (fall back to no filter on exotic schemas)
    lib = None
    if _table_exists(con, "libraries"):
        row = q("SELECT libraryID FROM libraries WHERE type='user'").fetchone()
        lib = row[0] if row else None
    lib_item = f"AND i.libraryID = {lib}" if lib is not None else ""
    lib_col = f"AND c.libraryID = {lib}" if lib is not None else ""

    not_trashed = "i.itemID NOT IN (SELECT itemID FROM deletedItems)"
    trashed_cols = ("SELECT collectionID FROM deletedCollections"
                    if _table_exists(con, "deletedCollections") else "SELECT NULL WHERE 0")

    report: dict = {}

    report["top_level_items"] = one(f"""
        SELECT COUNT(*) FROM items i
        WHERE i.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes
                                   WHERE typeName IN ('attachment','note','annotation'))
          AND {not_trashed} {lib_item}""")
    report["trash"] = one(f"""
        SELECT COUNT(*) FROM deletedItems d JOIN items i ON d.itemID = i.itemID
        WHERE 1=1 {lib_item}""")
    report["by_type"] = dict(q(f"""
        SELECT it.typeName, COUNT(*) FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        WHERE it.typeName NOT IN ('attachment','note','annotation')
          AND {not_trashed} {lib_item}
        GROUP BY it.typeName ORDER BY COUNT(*) DESC""").fetchall())

    # collection tree (live collections, live items only)
    cols = {r["collectionID"]: dict(r) for r in q(f"""
        SELECT c.collectionID, c.collectionName, c.parentCollectionID
        FROM collections c
        WHERE c.collectionID NOT IN ({trashed_cols}) {lib_col}""")}
    counts = dict(q(f"""
        SELECT ci.collectionID, COUNT(*) FROM collectionItems ci
        JOIN items i ON ci.itemID = i.itemID
        WHERE {not_trashed}
        GROUP BY ci.collectionID""").fetchall())

    def path_of(cid):
        parts, cur = [], cid
        while cur is not None and cur in cols:
            parts.append(cols[cur]["collectionName"])
            cur = cols[cur]["parentCollectionID"]
        return "/".join(reversed(parts))

    report["collections"] = {path_of(cid): counts.get(cid, 0) for cid in cols}
    report["empty_collections"] = sorted(p for p, n in report["collections"].items() if n == 0)
    report["items_without_collection"] = one(f"""
        SELECT COUNT(*) FROM items i
        WHERE i.itemTypeID NOT IN (SELECT itemTypeID FROM itemTypes
                                   WHERE typeName IN ('attachment','note','annotation'))
          AND {not_trashed} {lib_item}
          AND i.itemID NOT IN (SELECT itemID FROM collectionItems)""")

    # tags (live items only)
    tag_rows = q(f"""
        SELECT t.name, it.type, COUNT(*) AS n FROM itemTags it
        JOIN tags t ON it.tagID = t.tagID
        JOIN items i ON it.itemID = i.itemID
        WHERE {not_trashed} {lib_item}
        GROUP BY t.name, it.type""").fetchall()
    usage: Counter = Counter()
    auto = manual = 0
    for r in tag_rows:
        usage[r["name"]] += r["n"]
        if r["type"] == 1:
            auto += r["n"]
        else:
            manual += r["n"]
    report["tags_distinct"] = len(usage)
    report["tag_assignments"] = {"manual": manual, "automatic": auto}
    report["top_tags"] = usage.most_common(30)
    report["singleton_tags"] = sum(1 for n in usage.values() if n == 1)

    # reading status from extra field (zotero-reading-list convention)
    extra_field = q("SELECT fieldID FROM fields WHERE fieldName='extra'").fetchone()
    status_hist: Counter = Counter()
    if extra_field:
        for r in q(f"""
            SELECT v.value FROM itemData d
            JOIN itemDataValues v ON d.valueID = v.valueID
            JOIN items i ON d.itemID = i.itemID
            WHERE d.fieldID=? AND {not_trashed} {lib_item}""",
                   (extra_field["fieldID"],)).fetchall():
            m = re.findall(r"^Read_Status:\s*(.+)$", r["value"], flags=re.M | re.I)
            if len(m) == 1:
                status_hist[m[0].strip()] += 1
            elif len(m) > 1:
                status_hist["(INVALID: multiple Read_Status lines)"] += 1
    report["read_status"] = dict(status_hist)

    # attachments (live only)
    report["items_with_pdf"] = one(f"""
        SELECT COUNT(DISTINCT a.parentItemID) FROM itemAttachments a
        JOIN items i ON a.itemID = i.itemID
        WHERE a.contentType='application/pdf' AND a.parentItemID IS NOT NULL
          AND {not_trashed} {lib_item}
          AND a.parentItemID NOT IN (SELECT itemID FROM deletedItems)""")
    report["standalone_attachments"] = one(f"""
        SELECT COUNT(*) FROM itemAttachments a
        JOIN items i ON a.itemID = i.itemID
        WHERE a.parentItemID IS NULL AND {not_trashed} {lib_item}""")

    # duplicate suspects by DOI
    doi_field = q("SELECT fieldID FROM fields WHERE fieldName='DOI'").fetchone()
    dup_doi = 0
    if doi_field:
        dup_doi = one(f"""
            SELECT COUNT(*) FROM (
              SELECT LOWER(TRIM(v.value)) d, COUNT(*) c FROM itemData id
              JOIN itemDataValues v ON id.valueID = v.valueID
              JOIN items i ON id.itemID = i.itemID
              WHERE id.fieldID=? AND TRIM(v.value)<>''
                AND {not_trashed} {lib_item}
              GROUP BY LOWER(TRIM(v.value)) HAVING c>1)""", doi_field["fieldID"])
    report["duplicate_doi_groups"] = dup_doi

    return report


def render(report: dict) -> str:
    lines = []
    lines.append(f"Top-level items: {report['top_level_items']}   (trash: {report['trash']})")
    lines.append("By type: " + ", ".join(f"{k} {v}" for k, v in report["by_type"].items()))
    lines.append("")
    lines.append(f"Collections: {len(report['collections'])} "
                 f"(empty: {len(report['empty_collections'])}); "
                 f"items in no collection: {report['items_without_collection']}")
    for path in sorted(report["collections"]):
        depth = path.count("/")
        lines.append("  " * depth + f"- {path.rsplit('/', 1)[-1]} [{report['collections'][path]}]")
    lines.append("")
    ta = report["tag_assignments"]
    lines.append(f"Tags: {report['tags_distinct']} distinct "
                 f"({ta['manual']} manual / {ta['automatic']} automatic assignments; "
                 f"{report['singleton_tags']} used once)")
    lines.append("Top tags: " + ", ".join(f"{n}×{c}" for n, c in report["top_tags"][:15]))
    lines.append("")
    rs = report["read_status"]
    lines.append("Read status: " + (", ".join(f"{k}: {v}" for k, v in rs.items()) if rs else "(none set)"))
    lines.append(f"Items with PDF: {report['items_with_pdf']}; "
                 f"standalone attachments: {report['standalone_attachments']}")
    lines.append(f"Duplicate-DOI groups: {report['duplicate_doi_groups']}")
    return "\n".join(lines)


def run_audit(sqlite_path: Path, as_json: bool = False) -> str:
    con, tmp = open_snapshot(sqlite_path)
    try:
        report = collect(con)
    finally:
        con.close()
        tmp.unlink(missing_ok=True)
    return json.dumps(report, ensure_ascii=False, indent=1) if as_json else render(report)
