import json
import re

import pytest

from steward import pick


# Bibliographic values in this file are synthetic XQ-17 fixtures.


def _kb_file(tmp_path, pdf_path, schema_version="library-kb/1.0"):
    kb = {"schema_version": schema_version, "items": [
        {"key": "AAAAAAA1", "title": "[SYNTHETIC] XQ-17 calibration", "authors": ["Researcher-XQ17-A"],
         "year": "2018", "doi": "10.0000/scriptorium-demo-xq17-pick", "tldr": "t", "abstract": "a",
         "folders": ["X"], "pdfPaths": [str(pdf_path)]}]}
    f = tmp_path / "library.json"
    f.write_text(json.dumps(kb), encoding="utf-8")
    return f


@pytest.mark.parametrize("schema_version", ["library-kb/1.0", "library-kb/1.1"])
def test_load_kb_accepts_both_1x_envelopes(tmp_path, schema_version):
    kb = pick.load_kb(_kb_file(tmp_path, tmp_path / "x.pdf", schema_version))
    assert kb[0]["key"] == "AAAAAAA1"


def test_load_kb_retains_legacy_array(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps([{"key": "AAAAAAA1"}]), encoding="utf-8")
    assert pick.load_kb(path) == [{"key": "AAAAAAA1"}]


def _entry(tmp_path, key, name):
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4 " + key.encode())
    return {"key": key, "title": f"[SYNTHETIC] Paper {key}", "authors": ["Researcher-XQ17-A"], "year": "2020",
            "doi": f"10.1/{key}", "tldr": "t", "abstract": "a", "folders": ["X"],
            "pdfPaths": [str(pdf)]}


def test_find_by_key_and_title(tmp_path):
    kb = pick.load_kb(_kb_file(tmp_path, tmp_path / "x.pdf"))
    assert pick.find(kb, "AAAAAAA1")[0]["key"] == "AAAAAAA1"
    assert pick.find(kb, "calibration")[0]["key"] == "AAAAAAA1"
    assert pick.find(kb, "nope") == []


def test_stage_copies_pdf_and_writes_handoff(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 data")
    kb = pick.load_kb(_kb_file(tmp_path, pdf))
    dest = pick.stage(kb[0], tmp_path / "handoff")
    assert (dest / "paper.pdf").is_file()
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "handoff/1.0"
    assert meta["key"] == "AAAAAAA1"
    assert meta["pdfFilename"] == "paper.pdf"


def test_stage_no_pdf_raises(tmp_path):
    kb = pick.load_kb(_kb_file(tmp_path, tmp_path / "missing.pdf"))
    with pytest.raises(pick.PickError, match="no local PDF"):
        pick.stage(kb[0], tmp_path / "handoff")


def test_stage_report_multi_writes_handoff_11(tmp_path):
    entries = [_entry(tmp_path, "BBBBBBB1", "a.pdf"),
               _entry(tmp_path, "BBBBBBB2", "b.pdf")]
    dest = pick.stage_report(entries, tmp_path / "handoff", report_type="experiment",
                             title="My report")
    # report key derived deterministically; one directory per handoff
    assert dest.name == pick._report_key(["BBBBBBB1", "BBBBBBB2"])
    assert re.match(r"^[A-Z0-9]{8}$", dest.name)
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "handoff/1.1"
    assert meta["key"] == dest.name
    assert meta["report_type"] == "experiment"
    assert meta["title"] == "My report"
    assert [p["pdfFilename"] for p in meta["papers"]] == ["p1_a.pdf", "p2_b.pdf"]
    # per-paper entries carry biblio fields but NOT a key (report key is top-level)
    assert all("key" not in p for p in meta["papers"])
    assert meta["papers"][0]["doi"] == "10.1/BBBBBBB1"
    assert (dest / "p1_a.pdf").is_file() and (dest / "p2_b.pdf").is_file()


def test_stage_report_default_title_and_validation(tmp_path):
    entries = [_entry(tmp_path, "CCCCCCC1", "a.pdf"),
               _entry(tmp_path, "CCCCCCC2", "b.pdf")]
    dest = pick.stage_report(entries, tmp_path / "handoff")
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["report_type"] == "literature"
    assert meta["title"] == "Literature report (2 papers)"
    with pytest.raises(pick.PickError, match="invalid report_type"):
        pick.stage_report(entries, tmp_path / "h2", report_type="bogus")
