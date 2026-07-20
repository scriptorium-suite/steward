"""Tests for the local parse layer (parse.py).

GROBID HTTP is stubbed entirely (no network, no Java service). A small TEI-XML
fixture stands in for GROBID's /api/processFulltextDocument response; we assert
the normalized parsed-paper/1.0 (sections + references + metadata) and that a
GROBID-down (URLError) yields a clean ParseError, not a traceback. stdlib-only.
"""
import io
import json
import urllib.error

import pytest

from steward import parse


# A minimal GROBID TEI document using fully synthetic XQ-17 metadata, two body
# sections (one with an n= heading level), and two bibliography entries.
TEI_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title level="a" type="main">[SYNTHETIC] Adaptive Calibration of XQ-17 Sensors</title>
      </titleStmt>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <author>
              <persName><forename type="first">Researcher</forename><surname>XQ-17-05</surname></persName>
            </author>
            <author>
              <persName><forename type="first">Researcher</forename><surname>XQ-17-06</surname></persName>
            </author>
            <idno type="DOI">10.0000/scriptorium-demo-xq17-005</idno>
          </analytic>
          <monogr>
            <imprint><date type="published" when="2018-06-27">2018</date></imprint>
          </monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
    <profileDesc>
      <abstract><p>The synthetic XQ-17 benchmark compares two calibration
      strategies across a fabricated operating range.</p></abstract>
    </profileDesc>
  </teiHeader>
  <text>
    <body>
      <div>
        <head n="1">Introduction</head>
        <p>Synthetic XQ-17 sensors support the demonstration benchmark.</p>
        <p>We compare their calibration behavior.</p>
      </div>
      <div>
        <head n="2.1">Methods</head>
        <p>Repeated synthetic measurements with held-out validation.</p>
      </div>
      <div>
        <p>Trailing prose with no heading.</p>
      </div>
    </body>
    <back>
      <div type="references">
        <listBibl>
          <biblStruct>
            <analytic>
              <title level="a">[SYNTHETIC] Baseline XQ-17 observations</title>
              <author><persName><forename>Researcher</forename><surname>XQ-17-00</surname></persName></author>
              <idno type="DOI">10.0000/scriptorium-demo-xq17-000</idno>
            </analytic>
            <monogr><imprint><date when="1983">1983</date></imprint></monogr>
          </biblStruct>
          <biblStruct>
            <note type="raw_reference">Researcher XQ-17-04 (2006) Synthetic validation notes.</note>
          </biblStruct>
        </listBibl>
      </div>
    </back>
  </text>
</TEI>
"""


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_grobid(monkeypatch, response):
    """Stub urlopen in the parse module. `response` is bytes (returned) or an
    Exception (raised). Captures the Request for inspection."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if isinstance(response, BaseException):
            raise response
        return _FakeResp(response)

    monkeypatch.setattr(parse.urllib.request, "urlopen", fake_urlopen)
    return calls


def _write_pdf(tmp_path, name="paper.pdf"):
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4 fake bytes")
    return pdf


# -- happy path: TEI -> normalized parsed-paper/1.0 --------------------------

def test_grobid_parse_normalizes_metadata_sections_references(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path)
    calls = _patch_grobid(monkeypatch, TEI_FIXTURE.encode("utf-8"))

    doc = parse.parse_with_grobid(pdf, "xq17SyntheticStudy005",
                                  url="http://localhost:8070")

    # envelope
    assert doc["schema_version"] == "parsed-paper/1.0"
    assert doc["id"] == "xq17SyntheticStudy005"
    assert doc["parser"] == "grobid"
    assert doc["created"].endswith("Z")
    assert doc["source_pdf"] == "paper.pdf"

    # metadata from <teiHeader>
    md = doc["metadata"]
    assert md["title"] == "[SYNTHETIC] Adaptive Calibration of XQ-17 Sensors"
    assert md["authors"] == ["Researcher XQ-17-05", "Researcher XQ-17-06"]
    assert md["year"] == "2018"
    assert md["doi"] == "10.0000/scriptorium-demo-xq17-005"
    assert "synthetic XQ-17 benchmark" in md["abstract"]

    # sections from <body>/<div>/<head>; trailing un-headed div carried as ""
    sections = doc["sections"]
    assert [s["heading"] for s in sections] == ["Introduction", "Methods", ""]
    assert sections[0]["level"] == 1          # head n="1"
    assert sections[1]["level"] == 2          # head n="2.1" -> depth 2
    assert "Synthetic XQ-17 sensors" in sections[0]["text"]
    assert "compare their calibration" in sections[0]["text"]
    assert sections[2]["text"] == "Trailing prose with no heading."

    # references from <listBibl>/<biblStruct>
    refs = doc["references"]
    assert len(refs) == 2
    assert refs[0]["title"] == "[SYNTHETIC] Baseline XQ-17 observations"
    assert refs[0]["authors"] == ["Researcher XQ-17-00"]
    assert refs[0]["year"] == "1983"
    assert refs[0]["doi"] == "10.0000/scriptorium-demo-xq17-000"
    assert refs[1]["raw"].startswith("Researcher XQ-17-04")

    # the POST hit the fulltext endpoint
    assert calls[0].full_url == "http://localhost:8070/api/processFulltextDocument"
    assert calls[0].method == "POST"


def test_parsed_paper_validates_against_contract(tmp_path, monkeypatch):
    """The emitted file passes the scriptorium-spec parsed-paper validator
    (required id + created, well-formed arrays)."""
    pdf = _write_pdf(tmp_path)
    _patch_grobid(monkeypatch, TEI_FIXTURE.encode("utf-8"))
    doc = parse.parse_with_grobid(pdf, "xq17SyntheticStudy005",
                                  url="http://localhost:8070")
    # inline mirror of tools/validate.py validate_parsed_paper invariants
    assert isinstance(doc["id"], str) and doc["id"]
    assert doc["created"]
    for name in ("sections", "references"):
        assert isinstance(doc.get(name, []), list)
        assert all(isinstance(it, dict) for it in doc.get(name, []))


# -- GROBID down: clean actionable error, not a traceback --------------------

def test_grobid_unreachable_raises_clean_parse_error(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path)
    _patch_grobid(monkeypatch, urllib.error.URLError("Connection refused"))
    with pytest.raises(parse.ParseError) as ei:
        parse.parse_with_grobid(pdf, "x", url="http://localhost:8070")
    msg = str(ei.value)
    assert "cannot reach GROBID" in msg
    assert "docker run" in msg          # actionable hint
    assert "localhost:8070" in msg


def test_grobid_http_error_raises_clean_parse_error(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path)
    err = urllib.error.HTTPError("u", 503, "service unavailable", {},
                                 io.BytesIO(b"down for maintenance"))
    _patch_grobid(monkeypatch, err)
    with pytest.raises(parse.ParseError, match="HTTP 503"):
        parse.parse_with_grobid(pdf, "x", url="http://localhost:8070")


def test_invalid_xml_raises_clean_parse_error():
    with pytest.raises(parse.ParseError, match="non-TEI/invalid XML"):
        parse.tei_to_parsed_paper("<not><closed>", "x")


# -- parser seam -------------------------------------------------------------

def test_get_parser_default_is_grobid():
    assert parse.get_parser("grobid") is parse.parse_with_grobid


def test_get_parser_unknown_is_actionable():
    with pytest.raises(parse.ParseError, match="unknown parser"):
        parse.get_parser("mineru")     # heavier extras are not bundled


def test_pluggable_seam_accepts_a_custom_parse_fn(tmp_path, monkeypatch):
    """The seam is just name -> callable(pdf, citekey, *, url); a Docling/MinerU
    back-end could register here later without touching the core."""
    sentinel = {"schema_version": "parsed-paper/1.0", "id": "z", "created": "now",
                "parser": "fake", "metadata": {}}
    monkeypatch.setitem(parse.PARSERS, "fake", lambda pdf, ck, *, url: sentinel)
    fn = parse.get_parser("fake")
    assert fn(tmp_path / "x.pdf", "z", url="http://h") is sentinel


# -- URL resolution: CLI flag > env > config > default -----------------------

def test_grobid_url_precedence():
    assert parse.grobid_url("http://flag:1") == "http://flag:1"
    assert parse.grobid_url(None, env={parse.ENV_GROBID_URL: "http://env:2"}) \
        == "http://env:2"
    assert parse.grobid_url(None, profile_url="http://cfg:3", env={}) \
        == "http://cfg:3"
    assert parse.grobid_url(None, env={}) == parse.DEFAULT_GROBID_URL
