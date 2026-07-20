import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def fake_zotero_db(tmp_path):
    """Minimal Zotero-like sqlite with the tables audit reads."""
    db = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(db)
    c = con.cursor()
    c.executescript("""
    CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
    CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
    CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, key TEXT,
                        dateAdded TEXT, libraryID INTEGER);
    CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
    CREATE TABLE collections (collectionID INTEGER PRIMARY KEY,
                              collectionName TEXT, parentCollectionID INTEGER,
                              libraryID INTEGER);
    CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
    CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
    CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER);
    CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
    CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
    CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
    CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER,
                                  contentType TEXT);
    """)
    c.executemany("INSERT INTO libraries VALUES (?,?)", [(1, "user"), (2, "group")])
    c.executemany("INSERT INTO itemTypes VALUES (?,?)",
                  [(1, "journalArticle"), (2, "attachment"), (3, "note"), (4, "annotation")])
    # user lib: 3 papers (one in trash), 1 standalone + 1 child attachment;
    # group lib: 1 paper that must NOT appear anywhere in the report
    c.executemany("INSERT INTO items VALUES (?,?,?,?,?)", [
        (1, 1, "AAAAAAA1", "2024-01-01 00:00:00", 1),
        (2, 1, "AAAAAAA2", "2024-01-02 00:00:00", 1),
        (3, 1, "AAAAAAA3", "2024-01-03 00:00:00", 1),
        (4, 2, "AAAAAAA4", "2024-01-04 00:00:00", 1),
        (5, 2, "AAAAAAA5", "2024-01-05 00:00:00", 1),
        (6, 1, "GROUPIT1", "2024-01-06 00:00:00", 2),
    ])
    c.execute("INSERT INTO deletedItems VALUES (3)")
    c.executemany("INSERT INTO collections VALUES (?,?,?,?)",
                  [(1, "Projects", None, 1), (2, "ML", 1, 1), (3, "Empty", None, 1),
                   (4, "TrashedCol", None, 1), (5, "GroupCol", None, 2)])
    c.execute("INSERT INTO deletedCollections VALUES (4)")
    # item 3 is trashed: its membership/tag must not count
    c.executemany("INSERT INTO collectionItems VALUES (?,?)", [(1, 1), (2, 2), (2, 3)])
    c.executemany("INSERT INTO tags VALUES (?,?)", [(1, "ai:ml"), (2, "Read")])
    c.executemany("INSERT INTO itemTags VALUES (?,?,?)",
                  [(1, 1, 1), (1, 2, 0), (2, 1, 1), (3, 1, 1)])
    c.executemany("INSERT INTO fields VALUES (?,?)", [(1, "extra"), (2, "DOI")])
    c.executemany("INSERT INTO itemDataValues VALUES (?,?)", [
        (1, "TLDR: nice paper\nRead_Status: Read\nRead_Status_Date: 2026-01-01T00:00:00Z"),
        (2, "Read_Status: To Read"),
        (3, "10.0000/scriptorium-demo-duplicate"),
        (4, "10.0000/scriptorium-demo-duplicate"),
    ])
    c.executemany("INSERT INTO itemData VALUES (?,?,?)", [
        (1, 1, 1), (2, 1, 2),       # extras
        (1, 2, 3), (2, 2, 4),       # duplicate DOIs
    ])
    c.executemany("INSERT INTO itemAttachments VALUES (?,?,?)",
                  [(4, None, "application/pdf"), (5, 1, "application/pdf")])
    con.commit()
    con.close()
    return db
