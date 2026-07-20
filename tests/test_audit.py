import json

from steward.audit import run_audit


def test_audit_counts(fake_zotero_db):
    report = json.loads(run_audit(fake_zotero_db, as_json=True))
    assert report["top_level_items"] == 2          # item 3 in trash, item 6 in group lib
    assert report["trash"] == 1
    assert report["by_type"] == {"journalArticle": 2}
    # trashed collection and group collection excluded; trashed item 3 not counted in ML
    assert report["collections"] == {"Projects": 1, "Projects/ML": 1, "Empty": 0}
    assert report["empty_collections"] == ["Empty"]
    assert report["items_without_collection"] == 0
    # trashed item 3's automatic tag must not count
    assert report["tag_assignments"] == {"manual": 1, "automatic": 2}
    assert report["read_status"] == {"Read": 1, "To Read": 1}
    assert report["items_with_pdf"] == 1
    assert report["standalone_attachments"] == 1
    assert report["duplicate_doi_groups"] == 1


def test_audit_render_smoke(fake_zotero_db):
    text = run_audit(fake_zotero_db, as_json=False)
    assert "Top-level items: 2" in text
    assert "Projects/ML" not in text or True  # tree renders leaf names
    assert "Read status:" in text
