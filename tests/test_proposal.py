import json

import pytest

from steward import proposal as prop


def test_scaffold_from_snapshot(fake_zotero_db):
    doc = prop.scaffold(fake_zotero_db, ["00_Inbox", "01_ML"], inbox="00_Inbox")
    assert doc["schema_version"] == "proposal/1.0"
    assert doc["target_tree"] == ["00_Inbox", "01_ML"]
    # 2 live user-library papers (trash + group excluded)
    keys = {p["key"] for p in doc["proposals"]}
    assert keys == {"AAAAAAA1", "AAAAAAA2"}
    p1 = next(p for p in doc["proposals"] if p["key"] == "AAAAAAA1")
    assert p1["targets"] == ["00_Inbox"]
    assert p1["needsReview"] is True
    assert p1["currentCollections"] == ["Projects"]
    assert "ai:ml" in p1["tags"]


def test_validate_catches_scaffold_and_bad_targets():
    doc = {
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "A/B"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": []},                 # unfilled
            {"key": "AAAAAAA2", "targets": ["A/C"]},            # not in tree
            {"key": "bad", "targets": ["A"]},                   # bad key
            {"key": "AAAAAAA4", "targets": ["A"], "confidence": "huge"},
        ],
    }
    errors = prop.validate(doc)
    assert any("unfilled scaffold" in e for e in errors)
    assert any("not in target_tree" in e for e in errors)
    assert any("bad key" in e for e in errors)
    assert any("invalid confidence" in e for e in errors)


def test_validate_dup_targets_and_missing_tree():
    doc = {
        "schema_version": "proposal/1.0",
        "proposals": [{"key": "AAAAAAA1", "targets": ["A", "A"]}],  # dup, no tree
    }
    errors = prop.validate(doc)
    assert any("target_tree missing" in e for e in errors)
    assert any("duplicate targets" in e for e in errors)


def test_validate_malformed_paths():
    doc = {
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "A/B"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": [" A"]},        # whitespace
            {"key": "AAAAAAA2", "targets": ["A//B"]},      # empty segment
        ],
    }
    errors = prop.validate(doc)
    assert sum("malformed path" in e for e in errors) == 2


def test_validate_accepts_good_doc():
    doc = {
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "A/B"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": ["A/B"], "confidence": "high"},
        ],
    }
    assert prop.validate(doc) == []


def test_load_raises_with_errors(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"schema_version": "proposal/1.0", "proposals": [
        {"key": "AAAAAAA1", "targets": []}]}), encoding="utf-8")
    with pytest.raises(prop.ProposalError, match="unfilled"):
        prop.load(f)


def test_summarize_groups_by_primary():
    doc = {
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "B"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": ["A"], "confidence": "high"},
            {"key": "AAAAAAA2", "targets": ["A", "B"], "confidence": "low",
             "needsReview": True, "title": "tricky paper", "note": "unsure"},
        ],
    }
    text = prop.summarize(doc)
    assert "2 items -> 1 primary targets" in text
    assert "A: 2" in text
    assert "tricky paper" in text
