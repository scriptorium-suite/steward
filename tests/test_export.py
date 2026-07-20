import json
from pathlib import Path

import pytest

from steward import export as ex


# Bibliographic values in this file are synthetic XQ-17 fixtures.


class FakeReadClient:
    def __init__(self):
        self._cols = [
            {"key": "C1", "data": {"name": "Projects", "parentCollection": None}},
            {"key": "C2", "data": {"name": "ML", "parentCollection": "C1"}},
        ]
        self._items = [
            {"key": "AAAAAAA1", "meta": {"parsedDate": "2018-07-20"}, "data": {
                "itemType": "journalArticle", "title": "[SYNTHETIC] XQ-17 Study 015",
                "creators": [{"lastName": "Researcher-XQ17-A"},
                             {"lastName": "Researcher-XQ17-B"}],
                "DOI": "10.0000/scriptorium-demo-xq17-015", "collections": ["C2"],
                "tags": [{"tag": "ai:ml"}, {"tag": "Importance"}],
                "extra": "TLDR: a snappy summary\nRead_Status: Read\n"
                         "Citation Key: xq17SyntheticStudy015",
                "abstract": "Long abstract.", "dateAdded": "2024-01-01"}},
            {"key": "ADDONITM", "meta": {}, "data": {
                "itemType": "computerProgram", "title": "Addon Item", "creators": [],
                "collections": [], "tags": [], "extra": ""}},
        ]

    def collections(self):
        return self._cols

    def get_all(self, path):
        if "itemType=attachment" in path:
            return [{"key": "ATT1", "data": {"parentItem": "AAAAAAA1",
                     "contentType": "application/pdf", "filename": "p.pdf"}}]
        return self._items


def test_build_kb(tmp_path):
    kb = ex.build_kb(FakeReadClient(), tmp_path / "storage")
    assert len(kb) == 1                      # Addon Item excluded
    e = kb[0]
    assert e["year"] == "2018"               # from parsedDate, not date[:4]
    assert e["folders"] == ["Projects/ML"]
    assert e["aiTags"] == ["ml"]
    assert e["tldr"] == "a snappy summary"
    assert e["readStatus"] == "Read"
    assert e["pdfPaths"] and e["pdfPaths"][0].endswith("p.pdf")
    # the Better BibTeX `Citation Key:` line in `extra` flows to the KB citekey
    assert e["citekey"] == "xq17SyntheticStudy015"


def test_build_kb_citekey_empty_when_extra_has_no_citation_key():
    client = FakeReadClient()
    client._items[0]["data"]["extra"] = "TLDR: x\nRead_Status: Read"  # no Citation Key line
    e = ex.build_kb(client, None)[0]
    assert e["citekey"] == ""                 # absent -> empty string, never missing


def test_obsidian_frontmatter_carries_citekey_alias(tmp_path):
    """A KB item with a citekey gets `aliases: ["<citekey>"]` + `citekey:` in its
    Literature note frontmatter, so `[[citekey]]` wikilinks resolve to it."""
    kb = ex.build_kb(FakeReadClient(), None)
    ex.write_obsidian(kb, tmp_path)
    note = next((tmp_path / "Literature").glob("*.md"))
    text = note.read_text(encoding="utf-8")
    assert 'aliases: ["xq17SyntheticStudy015"]' in text
    assert 'citekey: "xq17SyntheticStudy015"' in text


def test_obsidian_frontmatter_omits_alias_when_no_citekey(tmp_path):
    client = FakeReadClient()
    client._items[0]["data"]["extra"] = "TLDR: x\nRead_Status: Read"  # no Citation Key
    kb = ex.build_kb(client, None)
    ex.write_obsidian(kb, tmp_path)
    note = next((tmp_path / "Literature").glob("*.md"))
    text = note.read_text(encoding="utf-8")
    assert "aliases:" not in text
    assert "citekey:" not in text


def test_write_kb_json_envelope(tmp_path):
    kb = ex.build_kb(FakeReadClient(), None)
    out = tmp_path / "kb" / "library.json"
    ex.write_kb_json(kb, out, "123", "user")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "library-kb/1.1"
    assert doc["library"] == {"type": "user", "id": "123"}
    assert len(doc["items"]) == 1


def test_obsidian_refuses_foreign_literature_dir(tmp_path):
    kb = ex.build_kb(FakeReadClient(), None)
    (tmp_path / "Literature").mkdir()
    (tmp_path / "Literature" / "my-notes.md").write_text("precious", encoding="utf-8")
    with pytest.raises(ex.ExportError, match="not created by steward"):
        ex.write_obsidian(kb, tmp_path)
    assert (tmp_path / "Literature" / "my-notes.md").read_text(encoding="utf-8") == "precious"


def test_obsidian_regenerates_own_dir(tmp_path):
    kb = ex.build_kb(FakeReadClient(), None)
    ex.write_obsidian(kb, tmp_path)                 # first run creates marker
    assert (tmp_path / "Literature" / ".steward-export").is_file()
    ex.write_obsidian(kb, tmp_path)                 # second run allowed (marker present)
    assert len(list((tmp_path / "Literature").glob("*.md"))) == 1


def test_frontmatter_injection_is_neutralized(tmp_path):
    client = FakeReadClient()
    client._items[0]["data"]["title"] = 'Evil\n---\ninjected: true\nmalicious: "yes'
    kb = ex.build_kb(client, None)
    ex.write_obsidian(kb, tmp_path)
    note = next((tmp_path / "Literature").glob("*.md"))
    text = note.read_text(encoding="utf-8")
    # the injected payload must not appear as its own frontmatter line
    assert "\ninjected: true" not in text
    assert text.startswith("---\n")
    # title stays a single quoted scalar line
    title_line = next(l for l in text.splitlines() if l.startswith("title:"))
    assert "injected" in title_line  # neutralized inside the quoted value, not as a key


def test_write_obsidian_layout(tmp_path):
    kb = ex.build_kb(FakeReadClient(), None)
    # pre-existing sibling folder must survive
    (tmp_path / "Conversations").mkdir()
    (tmp_path / "Conversations" / "keep.md").write_text("x", encoding="utf-8")
    n, folders = ex.write_obsidian(kb, tmp_path)
    assert n == 1
    notes = list((tmp_path / "Literature").glob("*.md"))
    assert len(notes) == 1
    assert "Researcher-XQ17-A 2018" in notes[0].name
    text = notes[0].read_text(encoding="utf-8")
    assert 'zotero-key: "AAAAAAA1"' in text
    assert "[!tip] TLDR" in text
    assert (tmp_path / "MOC" / "文献库 MOC.md").is_file()
    assert (tmp_path / "Conversations" / "keep.md").is_file()   # untouched


def test_warns_when_storage_dir_unset(capsys):
    # storage_dir=None -> no PDF paths resolved -> every `steward pick` is doomed.
    ex.build_kb(FakeReadClient(), None)
    err = capsys.readouterr().err
    assert "storage dir is unset" in err


def test_warns_when_all_pdf_paths_empty(capsys):
    # storage dir present but no attachments match -> all pdfPaths empty.
    class NoPdfClient(FakeReadClient):
        def get_all(self, path):
            if "itemType=attachment" in path:
                return []                    # no PDF attachments at all
            return self._items

    kb = ex.build_kb(NoPdfClient(), Path("storage"))
    assert all(not e["pdfPaths"] for e in kb)
    assert "none of 1 items has a local PDF path" in capsys.readouterr().err


def test_no_warning_when_pdfs_present(capsys):
    ex.build_kb(FakeReadClient(), Path("storage"))
    assert "warning" not in capsys.readouterr().err
