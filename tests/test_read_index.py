# [SYNTHETIC] XQ-17 fixtures only; no value represents a real paper, author, DOI, or research record.
"""Tests for the reading-notes/ overview dashboard (read_index.py + CLI wiring).

Writes a few sample reading-note/1.0 JSONs to a tmp vault, builds the index, and
asserts: status-grouped sections (To Read / In Progress / Read / …), wikilink
list entries, the full static table rows, the fenced Dataview block, deterministic
ordering, a non-reading-note JSON skipped with a warning, and an empty/absent
reading-notes dir handled with a clear message (no crash, no _index.md written).
stdlib-only, inline fixtures (no host paths).
"""
import json

import pytest

from steward import cli
from steward import read_index


def _note(citekey, *, status="", stages=("glance",), title="", year="", tags=None):
    stage_obj = {}
    if "glance" in stages:
        stage_obj["glance"] = {"tldr": "t", "tags": tags or []}
    if "close_read" in stages:
        stage_obj["close_read"] = {"question": "q?", "method": "m"}
    if "deep_read" in stages:
        stage_obj["deep_read"] = {"critique": "c"}
    if "situate" in stages:
        stage_obj["situate"] = {"direction": "d", "lineage_refs": []}
    note = {
        "schema_version": "reading-note/1.0",
        "id": citekey,
        "created": "2026-06-22T00:00:00Z",
        "stages": stage_obj,
    }
    if status:
        note["read_status"] = status
    if title:
        note["title"] = title
    if year:
        note["year"] = year
    return note


def _write_three(rn_dir):
    rn_dir.mkdir(parents=True, exist_ok=True)
    (rn_dir / "xq17SyntheticStudy015.json").write_text(json.dumps(
        _note("xq17SyntheticStudy015", status="In Progress",
              stages=("glance", "close_read"), title="[SYNTHETIC] XQ-17 Study 15", year="2008",
              tags=["xq17_synthetic"])), encoding="utf-8")
    (rn_dir / "xq17SyntheticStudy023.json").write_text(json.dumps(
        _note("xq17SyntheticStudy023", status="To Read", stages=("glance",),
              year="2018")), encoding="utf-8")
    (rn_dir / "xq17SyntheticStudy016.json").write_text(json.dumps(
        _note("xq17SyntheticStudy016", status="Read",
              stages=("glance", "close_read", "deep_read", "situate"),
              title="[SYNTHETIC] XQ-17 Study 08", year="1983")), encoding="utf-8")
    return rn_dir


# -- scan_vault --------------------------------------------------------------

def test_scan_reads_reading_notes_and_skips_foreign(tmp_path, capsys):
    rn = _write_three(tmp_path / "reading-notes")
    # a non-reading-note JSON in the same dir must be skipped with a warning
    (rn / "_not_a_note.json").write_text(
        json.dumps({"schema_version": "library-kb/1.0", "items": []}),
        encoding="utf-8")
    notes, warnings = read_index.scan_vault(rn)
    assert {n["id"] for n in notes} == {
        "xq17SyntheticStudy015", "xq17SyntheticStudy023", "xq17SyntheticStudy016"}
    assert any("_not_a_note.json" in w for w in warnings)


def test_scan_absent_dir_returns_empty(tmp_path):
    notes, warnings = read_index.scan_vault(tmp_path / "reading-notes")  # never created
    assert notes == [] and warnings == []


def test_scan_skips_invalid_json(tmp_path):
    rn = tmp_path / "reading-notes"
    rn.mkdir()
    (rn / "broken.json").write_text("{not json", encoding="utf-8")
    notes, warnings = read_index.scan_vault(rn)
    assert notes == []
    assert any("broken.json" in w and "not valid JSON" in w for w in warnings)


# -- build_index: --kb title/year enrichment ---------------------------------

def test_build_index_kb_enriches_title_and_year():
    """--kb fills the title/year a reading-note doesn't carry; without it those
    columns stay empty (the citekey is the section/table label)."""
    notes = [{"schema_version": "reading-note/1.0", "id": "xq17SyntheticStudy015",
              "read_status": "Read", "created": "2026-01-01",
              "stages": {"glance": {"tldr": "x"}}}]
    kb = {"xq17SyntheticStudy015":
          {"citekey": "xq17SyntheticStudy015", "title": "[SYNTHETIC] XQ-17 Study 14", "year": "2008"}}
    enriched = read_index.build_index(notes, kb)
    assert "[SYNTHETIC] XQ-17 Study 14" in enriched and "2008" in enriched
    assert "[SYNTHETIC] XQ-17 Study 14" not in read_index.build_index(notes)


@pytest.mark.parametrize("schema_version", ["library-kb/1.0", "library-kb/1.1"])
def test_load_kb_index_maps_keys_for_both_1x_versions(tmp_path, schema_version):
    kb_path = tmp_path / "library.json"
    kb_path.write_text(json.dumps({"schema_version": schema_version, "items": [
        {"key": "K7M4QX2P", "citekey": "xq17SyntheticStudy015", "title": "T", "year": "2008"}]}),
        encoding="utf-8")
    idx = read_index.load_kb_index(kb_path)
    assert idx["xq17SyntheticStudy015"]["title"] == "T"
    assert idx["K7M4QX2P"]["title"] == "T"  # also keyed by the Zotero key


def test_load_kb_index_retains_legacy_array_and_errors_on_missing(tmp_path):
    kb_path = tmp_path / "legacy.json"
    kb_path.write_text(json.dumps([{"key": "K7M4QX2P", "title": "T"}]),
                       encoding="utf-8")
    assert read_index.load_kb_index(kb_path)["K7M4QX2P"]["title"] == "T"
    with pytest.raises(read_index.IndexError_):
        read_index.load_kb_index(tmp_path / "nope.json")


# -- build_index: status grouping + wikilinks --------------------------------

def test_build_groups_by_status_with_wikilinks(tmp_path):
    notes, _ = read_index.scan_vault(_write_three(tmp_path / "reading-notes"))
    md = read_index.build_index(notes)
    assert "type: reading-index" in md
    assert "## To Read (1)" in md
    assert "## In Progress (1)" in md
    assert "## Read (1)" in md
    # a section entry is a wikilink with title/year + filled stages
    inprog = md.split("## In Progress", 1)[1].split("## ", 1)[0]
    assert "[[xq17SyntheticStudy015]]" in inprog
    assert "[SYNTHETIC] XQ-17 Study 15" in inprog and "2008" in inprog
    assert "(glance·close)" in inprog        # both filled stages shown
    read = md.split("## Read (1)", 1)[1].split("## ", 1)[0]
    assert "(glance·close·deep·situate)" in read


def test_build_full_table_has_a_row_per_note(tmp_path):
    notes, _ = read_index.scan_vault(_write_three(tmp_path / "reading-notes"))
    md = read_index.build_index(notes)
    table = md.split("## 全部 · All", 1)[1].split("## ", 1)[0]
    assert "| citekey | title | year | status | stages | tags |" in table
    assert "| `xq17SyntheticStudy015` |" in table
    assert "| `xq17SyntheticStudy023` |" in table
    assert "| `xq17SyntheticStudy016` |" in table
    # the In Progress row carries its status + stages + tag
    row = next(l for l in table.splitlines() if "xq17SyntheticStudy015" in l)
    assert "In Progress" in row and "glance·close" in row and "xq17_synthetic" in row


def test_build_has_a_dataview_block(tmp_path):
    notes, _ = read_index.scan_vault(_write_three(tmp_path / "reading-notes"))
    md = read_index.build_index(notes)
    assert "```dataview" in md
    assert 'FROM "reading-notes"' in md
    assert 'WHERE type = "reading-note"' in md


def test_build_is_deterministic_and_sorted_by_status_then_citekey(tmp_path):
    notes, _ = read_index.scan_vault(_write_three(tmp_path / "reading-notes"))
    a = read_index.build_index(notes)
    b = read_index.build_index(list(reversed(notes)))   # input order must not matter
    assert a == b
    # in the table, To Read precedes In Progress precedes Read (lifecycle order)
    table = a.split("## 全部 · All", 1)[1]
    i_toread = table.index("xq17SyntheticStudy023")
    i_inprog = table.index("xq17SyntheticStudy015")
    i_read = table.index("xq17SyntheticStudy016")
    assert i_toread < i_inprog < i_read


def test_build_no_status_group_and_table(tmp_path):
    rn = tmp_path / "reading-notes"
    rn.mkdir()
    (rn / "xq17SyntheticStudy024.json").write_text(json.dumps(
        _note("xq17SyntheticStudy024", status="", stages=("glance",))), encoding="utf-8")
    notes, _ = read_index.scan_vault(rn)
    md = read_index.build_index(notes)
    assert "## (no status) (1)" in md
    assert "[[xq17SyntheticStudy024]]" in md


# -- CLI wiring --------------------------------------------------------------

def test_cli_read_index_writes_index_md(tmp_path, capsys):
    vault = tmp_path / "vault"
    _write_three(vault / "reading-notes")
    rc = cli.main(["read-index", "--vault", str(vault)])
    assert rc == 0
    out = vault / "reading-notes" / "_index.md"
    assert out.is_file()
    md = out.read_text(encoding="utf-8")
    assert "## In Progress (1)" in md
    assert "[[xq17SyntheticStudy015]]" in md
    printed = capsys.readouterr().out
    assert "reading index ->" in printed
    assert "In Progress=1" in printed


def test_cli_read_index_explicit_out(tmp_path):
    vault = tmp_path / "vault"
    _write_three(vault / "reading-notes")
    out = tmp_path / "overview.md"
    rc = cli.main(["read-index", "--vault", str(vault), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    # the default _index.md is NOT written when --out is given
    assert not (vault / "reading-notes" / "_index.md").exists()


def test_cli_read_index_empty_dir_is_clear_no_crash(tmp_path, capsys):
    vault = tmp_path / "vault"
    (vault / "reading-notes").mkdir(parents=True)   # exists but empty
    rc = cli.main(["read-index", "--vault", str(vault)])
    assert rc == 0
    assert "nothing to index" in capsys.readouterr().out
    assert not (vault / "reading-notes" / "_index.md").exists()  # no file written


def test_cli_read_index_absent_dir_is_clear_no_crash(tmp_path, capsys):
    vault = tmp_path / "vault"
    vault.mkdir()                                   # no reading-notes/ at all
    rc = cli.main(["read-index", "--vault", str(vault)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no reading-notes/ directory" in out


def test_cli_read_index_skips_foreign_with_warning(tmp_path, capsys):
    vault = tmp_path / "vault"
    rn = _write_three(vault / "reading-notes")
    (rn / "stray.json").write_text(
        json.dumps({"schema_version": "review/1.0"}), encoding="utf-8")
    rc = cli.main(["read-index", "--vault", str(vault)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "warning:" in captured.err and "stray.json" in captured.err
    # the three valid notes are still indexed
    assert "3 notes" in captured.out
