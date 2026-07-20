# [SYNTHETIC] XQ-17 fixtures only; no value represents a real paper, author, DOI, or research record.
import json

import pytest

from steward import review as rv

# A small synthetic library-kb: topic "01_ML" must capture 01_ML and 01_ML/...
# never 01_MLX (prefix boundary) nor folderless items.
KB = {
    "schema_version": "library-kb/1.0",
    "generated_by": "steward test",
    "library": {"type": "user", "id": "1"},
    "items": [
        {"key": "AAAAAAA1", "title": "[SYNTHETIC] XQ-17 Study 16",
         "authors": ["[SYNTHETIC] Researcher XQ-17-12", "[SYNTHETIC] Researcher XQ-17-13"], "year": "2003", "doi": "",
         "folders": ["01_ML/Group-A"], "aiTags": ["xq17_synthetic"],
         "tldr": "xq17_synthetic basics", "readStatus": "To Read", "abstract": "abc",
         "dateAdded": "2025-01-01T00:00:00Z"},
        {"key": "BBBBBBB2", "title": "[SYNTHETIC] XQ-17 Study 17", "authors": ["[SYNTHETIC] Researcher XQ-17-01"],
         "year": "2023", "doi": "10.0000/scriptorium-demo-xq17-015", "folders": ["01_ML"], "aiTags": ["ml"],
         "tldr": "RF provenance", "readStatus": "Read", "abstract": "def",
         "dateAdded": "2026-06-20T00:00:00Z"},
        {"key": "CCCCCCC3", "title": "[SYNTHETIC] XQ-17 Study 18", "authors": ["[SYNTHETIC] Researcher XQ-17-14"], "year": "2024",
         "doi": "10.0000/scriptorium-demo-xq17-016", "folders": ["01_ML/Group-A/Metric"], "aiTags": ["ml"],
         "tldr": "synthetic calibration", "readStatus": "In Progress", "abstract": "ghi",
         "dateAdded": "2026-06-01T00:00:00Z"},
        {"key": "DDDDDDD4", "title": "Unrelated MLX paper", "authors": ["Other"],
         "year": "2020", "doi": "", "folders": ["01_MLX"], "aiTags": [],
         "tldr": "", "readStatus": "", "abstract": "", "dateAdded": "2020-01-01T00:00:00Z"},
        {"key": "EEEEEEE5", "title": "No folders", "authors": [], "year": "",
         "folders": []},
    ],
}

DRAFT = {
    "schema_version": "review-draft/1.0",
    "framing": "From classical discriminants to high-dimensional ML.",
    "intro": "Intro prose.",
    "sections": [
        {"title": "Foundations", "body": "Foundations body.", "covered_keys": ["AAAAAAA1"]},
        {"title": "ML mainline", "body": "ML body.", "covered_keys": ["BBBBBBB2"]},
    ],
    "gaps_future": "Gaps prose.",
    "priority_reads": ["AAAAAAA1", "BBBBBBB2"],
}


@pytest.fixture
def kb_file(tmp_path):
    p = tmp_path / "library.json"
    p.write_text(json.dumps(KB, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.mark.parametrize("schema_version", ["library-kb/1.0", "library-kb/1.1"])
def test_load_kb_items_accepts_both_1x_envelopes(tmp_path, schema_version):
    path = tmp_path / "library.json"
    path.write_text(json.dumps({**KB, "schema_version": schema_version}),
                    encoding="utf-8")
    assert len(rv.load_kb_items(path)) == len(KB["items"])


def test_load_kb_items_retains_legacy_array(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(KB["items"]), encoding="utf-8")
    assert len(rv.load_kb_items(path)) == len(KB["items"])


# -- scaffold: prefix boundary ----------------------------------------------

def test_scaffold_prefix_boundary(kb_file):
    doc = rv.scaffold(kb_file, "01_ML")
    keys = [p["key"] for p in doc["papers"]]
    assert keys == ["AAAAAAA1", "BBBBBBB2", "CCCCCCC3"]   # sorted by year; 01_MLX excluded
    assert "DDDDDDD4" not in keys                          # 01_MLX is NOT under 01_ML
    assert "EEEEEEE5" not in keys                          # folderless item excluded
    assert doc["count"] == 3 and doc["schema_version"] == rv.INPUT_SCHEMA
    # abstract is truncated and only the documented fields are carried
    paper = doc["papers"][0]
    assert set(paper) == {"key", "title", "authors", "year", "doi", "tldr",
                          "aiTags", "readStatus", "abstract"}


def test_scaffold_exact_match_only(kb_file):
    # the prefix can also be the deeper exact path
    doc = rv.scaffold(kb_file, "01_ML/Group-A")
    assert [p["key"] for p in doc["papers"]] == ["AAAAAAA1", "CCCCCCC3"]
    # a non-existent prefix yields zero papers (no crash)
    assert rv.scaffold(kb_file, "99_None")["count"] == 0


# -- scaffold: R13 what's-new selection (since / unread) ----------------------

def test_scaffold_since_filter(kb_file):
    # only items added on/after the floor survive (lexical ISO-date compare),
    # AND-ed with the topic prefix. BBBB (2026-06-20) is recent; CCCC
    # (2026-06-01) and AAAA (2025) are not.
    doc = rv.scaffold(kb_file, "01_ML", since="2026-06-15")
    assert [p["key"] for p in doc["papers"]] == ["BBBBBBB2"]
    assert doc["selection"] == {"topic": "01_ML", "since": "2026-06-15", "unread": False}


def test_scaffold_unread_filter(kb_file):
    # "Read" is dropped; To Read / In Progress / unset are kept.
    doc = rv.scaffold(kb_file, "01_ML", unread=True)
    assert [p["key"] for p in doc["papers"]] == ["AAAAAAA1", "CCCCCCC3"]
    assert "BBBBBBB2" not in [p["key"] for p in doc["papers"]]   # Read excluded


def test_scaffold_whatsnew_combined(kb_file):
    # the weekly digest: recent additions that are still unread, no topic.
    # BBBB recent-but-Read -> out; CCCC recent+InProgress -> in; AAAA unread-but-old
    # -> out; DDDD old -> out; EEEE no dateAdded -> out.
    doc = rv.scaffold(kb_file, since="2026-05-01", unread=True, label="库内新进展")
    assert [p["key"] for p in doc["papers"]] == ["CCCCCCC3"]
    assert doc["topic"] == "" and doc["label"] == "库内新进展"
    assert doc["selection"] == {"topic": "", "since": "2026-05-01", "unread": True}


def test_scaffold_no_filters_takes_whole_library(kb_file):
    # core is permissive (the CLI requires >=1 filter); folderless items included.
    doc = rv.scaffold(kb_file)
    assert doc["count"] == 5


def test_default_scaffold_out_is_date_stamped():
    # mirrors lit-run.ps1's <name>-<date> convention so repeated runs don't clobber.
    p = rv.default_scaffold_out(today="2026-06-22")
    assert p.name == "review.input-2026-06-22.json"
    # the default (no today) is today's local date in the same shape.
    from datetime import date
    assert rv.default_scaffold_out().name == f"review.input-{date.today().isoformat()}.json"


def test_render_uses_digest_label(kb_file):
    # with no topic and no draft title, the heading falls back to the label.
    # the unread digest drops BBBBBBB2 (Read), so cite only surviving keys.
    input_doc = rv.scaffold(kb_file, unread=True, label="库内新进展")
    draft = {
        "schema_version": "review-draft/1.0",
        "framing": "From classical discriminants to high-dimensional ML.",
        "intro": "Intro prose.",
        "sections": [
            {"title": "Foundations", "body": "Foundations body.",
             "covered_keys": ["AAAAAAA1", "CCCCCCC3"]},
        ],
        "gaps_future": "Gaps prose.",
        "priority_reads": ["AAAAAAA1"],
    }
    md = rv.render(input_doc, draft)            # no "title"
    assert "# 库内新进展 · 文献综述草稿" in md


# -- validate ----------------------------------------------------------------

def test_validate_good_draft():
    assert rv.validate_draft(DRAFT, KB["items"]) == []


def test_validate_rejects_unknown_keys():
    bad = json.loads(json.dumps(DRAFT))
    bad["sections"][0]["covered_keys"] = ["ZZZZZZZ9"]      # fabricated
    bad["priority_reads"] = ["YYYYYYY8"]                   # fabricated
    errs = rv.validate_draft(bad, KB["items"])
    assert any("covered_keys references unknown key 'ZZZZZZZ9'" in e for e in errs)
    assert any("priority_reads references unknown key 'YYYYYYY8'" in e for e in errs)


def test_validate_rejects_missing_fields():
    bad = {"schema_version": "review-draft/1.0", "sections": []}
    errs = rv.validate_draft(bad, KB["items"])
    assert any("intro: missing" in e for e in errs)
    assert any("framing: missing" in e for e in errs)
    assert any("gaps_future: missing" in e for e in errs)
    assert any("sections: missing or empty" in e for e in errs)


def test_validate_rejects_wrong_schema():
    assert any("schema_version must be" in e
               for e in rv.validate_draft({"intro": "x"}, KB["items"]))


# -- render: refs come from the KB, never the draft -------------------------

def test_render_reference_table_is_authoritative(kb_file):
    input_doc = rv.scaffold(kb_file, "01_ML")
    md = rv.render(input_doc, DRAFT)

    # banner reports total + read counts (only BBBBBBB2 is "Read")
    assert "本稿由 3 篇文献" in md and "仅 1 篇标记已读" in md

    # EVERY topic paper appears in the authoritative table with its KB metadata,
    # even CCCCCCC3 which the draft never cites.
    assert "## 全部文献（3 篇" in md
    assert "`AAAAAAA1`" in md and "`BBBBBBB2`" in md and "`CCCCCCC3`" in md
    # read-status marks from the KB
    assert "✅ `BBBBBBB2`" in md          # Read
    assert "📖 `CCCCCCC3`" in md          # In Progress
    assert "▢ `AAAAAAA1`" in md           # To Read
    # DOIs come from the KB (the draft has none)
    assert "[doi:10.0000/scriptorium-demo-xq17-015]" in md and "[doi:10.0000/scriptorium-demo-xq17-016]" in md

    # 涉及 lines use KB Author+Year, not anything in the draft
    assert "*涉及*：[SYNTHETIC] Researcher XQ-17-12 2003" in md
    assert "*涉及*：[SYNTHETIC] Researcher XQ-17-01 2023" in md

    # priority reads rendered from KB
    assert "[SYNTHETIC] Researcher XQ-17-12 2003" in md and "[SYNTHETIC] Researcher XQ-17-01 2023" in md

    # coverage note: 2 of 3 discussed, 1 (CCCCCCC3) not
    assert "3 篇中 2 篇在主题章节中被明确讨论，1 篇未被讨论" in md


# -- readStatus normalization: filter and render agree -----------------------

def test_read_status_normalizes_whitespace():
    # the single normalize helper trims surrounding whitespace.
    assert rv._read_status({"readStatus": " Read "}) == "Read"
    assert rv._read_status({"readStatus": "In Progress\n"}) == "In Progress"
    assert rv._read_status({}) == ""
    # and _is_unread is built on it (whitespace-padded "Read" is still read).
    assert rv._is_unread({"readStatus": " Read "}) is False
    assert rv._is_unread({"readStatus": "To Read"}) is True


def test_render_read_count_and_marker_strip_status():
    # a padded "Read"/"In Progress" must count and mark the same as a clean one,
    # i.e. the read-count path and the marker path use the same normalization as
    # the unread filter (no Read/read inconsistency).
    input_doc = {
        "topic": "01_ML",
        "papers": [
            {"key": "AAAAAAA1", "title": "Padded read", "authors": ["A"],
             "year": "2020", "doi": "", "readStatus": " Read "},
            {"key": "BBBBBBB2", "title": "Padded in-progress", "authors": ["B"],
             "year": "2021", "doi": "", "readStatus": "In Progress\n"},
        ],
    }
    draft = {
        "schema_version": "review-draft/1.0",
        "framing": "f", "intro": "i", "gaps_future": "g",
        "sections": [{"title": "T", "body": "b", "covered_keys": ["AAAAAAA1"]}],
        "priority_reads": [],
    }
    md = rv.render(input_doc, draft)
    # the padded "Read" is counted as read (1 of 2), not dropped to 0
    assert "仅 1 篇标记已读" in md
    # and gets the ✅ / 📖 markers, not the fallback ▢
    assert "✅ `AAAAAAA1`" in md
    assert "📖 `BBBBBBB2`" in md


def test_render_rejects_unvalidated_draft(kb_file):
    # a malformed draft must raise ReviewError at the top of render, not fail
    # later with a bare KeyError/TypeError on a missing/None field.
    input_doc = rv.scaffold(kb_file, "01_ML")
    with pytest.raises(rv.ReviewError, match="unvalidated draft"):
        rv.render(input_doc, {"schema_version": "review-draft/1.0"})  # no intro/sections
    # a draft missing only `intro` (previously a bare KeyError) is caught too
    bad = json.loads(json.dumps(DRAFT))
    del bad["intro"]
    with pytest.raises(rv.ReviewError, match="unvalidated draft"):
        rv.render(input_doc, bad)


def test_render_does_not_trust_draft_fabricated_doi(kb_file):
    # even if the draft body contains a fake DOI string, it is not promoted into
    # the reference table (the table is built only from input papers).
    input_doc = rv.scaffold(kb_file, "01_ML")
    draft = json.loads(json.dumps(DRAFT))
    draft["sections"][0]["body"] = "Body mentioning doi:10.0000/scriptorium-demo-xq17-017"
    md = rv.render(input_doc, draft)
    # the fabricated DOI never appears as a reference-table citation
    assert "[doi:10.0000/scriptorium-demo-xq17-018]" not in md
