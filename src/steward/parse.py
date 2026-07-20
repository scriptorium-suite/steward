"""parse: PDF -> parsed-paper/1.0 via a LOCAL parser (GROBID by default).

The parse layer turns a paper PDF into the suite's normalized structured file
(scriptorium-spec `parsed-paper/1.0`): metadata + sections + reference list,
extracted locally so a downstream reader consumes structure instead of
re-parsing the PDF — and with no cloud egress.

Design seam (P2, specs/literature-reading.md §2): a parser is just a `parse_fn`
- a callable `(pdf_path: Path, citekey: str, *, url: str) -> dict`. GROBID is the
stdlib-clean default (urllib HTTP + xml.etree TEI parse, no new dependency).
Heavier rich parsers (Docling / MinerU) can register additional `parse_fn`s as
OPTIONAL extras later WITHOUT touching the core; they are deliberately NOT built
here. Resolve a parser by name with `get_parser`.

GROBID is a LOCAL Java service the user runs (Docker `grobid/grobid` on
localhost:8070). A connection failure (service not running) is surfaced as a
ParseError with an actionable message — never a raw traceback.
"""
from __future__ import annotations

import datetime
import io
import os
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA_VERSION = "parsed-paper/1.0"

DEFAULT_GROBID_URL = "http://localhost:8070"
ENV_GROBID_URL = "STEWARD_GROBID_URL"

# TEI namespace GROBID emits; every element below lives in it.
TEI = "{http://www.tei-c.org/ns/1.0}"


class ParseError(RuntimeError):
    pass


# -- HTTP transport (stdlib only) -------------------------------------------

def _multipart_pdf(pdf_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """Encode a single-file multipart/form-data body for GROBID's `input` field.

    Returns (body, content_type). Pure stdlib — no `requests`.
    """
    boundary = f"----stewardparse{uuid.uuid4().hex}"
    buf = io.BytesIO()
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="input"; filename="{filename}"\r\n'
        .encode())
    buf.write(b"Content-Type: application/pdf\r\n\r\n")
    buf.write(pdf_bytes)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def grobid_fulltext(pdf_bytes: bytes, filename: str, *, url: str,
                    timeout: int = 300) -> str:
    """POST a PDF to GROBID /api/processFulltextDocument; return the TEI-XML.

    Raises ParseError with an actionable message when GROBID is unreachable
    (service not started) or returns an error status.
    """
    endpoint = url.rstrip("/") + "/api/processFulltextDocument"
    body, content_type = _multipart_pdf(pdf_bytes, filename)
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": content_type, "Accept": "application/xml"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise ParseError(
            f"GROBID returned HTTP {e.code} for {filename}"
            + (f": {detail}" if detail else "")) from e
    except urllib.error.URLError as e:
        # GROBID not running is the common case: give a fully actionable hint.
        raise ParseError(
            f"cannot reach GROBID at {url} ({e.reason}). Start the local "
            "service first, e.g. `docker run --rm -p 8070:8070 grobid/grobid`, "
            f"or point --grobid-url / ${ENV_GROBID_URL} at a running instance.") from e


# -- TEI parsing (xml.etree) -------------------------------------------------

def _text(el) -> str:
    """All descendant text of an element, whitespace-normalized."""
    if el is None:
        return ""
    return " ".join("".join(el.itertext()).split())


def _author_names(analytic_or_monogr) -> list[str]:
    names = []
    for pers in analytic_or_monogr.iter(f"{TEI}author"):
        persname = pers.find(f"{TEI}persName")
        if persname is None:
            continue
        forenames = [_text(f) for f in persname.findall(f"{TEI}forename")]
        surname = _text(persname.find(f"{TEI}surname"))
        full = " ".join([p for p in forenames + [surname] if p])
        if full:
            names.append(full)
    return names


def _parse_metadata(root) -> dict:
    meta: dict = {}
    header = root.find(f"{TEI}teiHeader")
    if header is None:
        return meta
    title_el = header.find(f".//{TEI}titleStmt/{TEI}title")
    title = _text(title_el)
    if title:
        meta["title"] = title
    authors = _author_names(header)
    if authors:
        meta["authors"] = authors
    # year: <date when="2008-..."> or text content under sourceDesc
    year = ""
    for date_el in header.iter(f"{TEI}date"):
        when = date_el.get("when") or _text(date_el)
        if when[:4].isdigit():
            year = when[:4]
            break
    if year:
        meta["year"] = year
    for idno in header.iter(f"{TEI}idno"):
        if (idno.get("type") or "").upper() == "DOI":
            doi = _text(idno)
            if doi:
                meta["doi"] = doi
                break
    abstract = _text(header.find(f".//{TEI}profileDesc/{TEI}abstract"))
    if abstract:
        meta["abstract"] = abstract
    return meta


def _parse_sections(root) -> list[dict]:
    body = root.find(f".//{TEI}text/{TEI}body")
    if body is None:
        return []
    sections = []
    for div in body.findall(f"{TEI}div"):
        head_el = div.find(f"{TEI}head")
        heading = _text(head_el)
        # paragraphs only (exclude the heading's own text)
        paras = [_text(p) for p in div.findall(f"{TEI}p")]
        text = " ".join(p for p in paras if p)
        if not heading and not text:
            continue
        sec: dict = {"heading": heading, "text": text}
        # heading level from <head n="1.2"> depth, when present
        n = head_el.get("n") if head_el is not None else None
        if n:
            sec["level"] = n.count(".") + 1
        sections.append(sec)
    return sections


def _parse_references(root) -> list[dict]:
    refs = []
    # only the bibliography (<listBibl>), never the paper's own header biblStruct
    bibls = [b for lb in root.iter(f"{TEI}listBibl")
             for b in lb.iter(f"{TEI}biblStruct")]
    for bibl in bibls:
        ref: dict = {}
        title = ""
        for t in bibl.iter(f"{TEI}title"):
            if (t.get("level") in ("a", "m")) and _text(t):
                title = _text(t)
                break
        if not title:
            title = _text(bibl.find(f".//{TEI}title"))
        if title:
            ref["title"] = title
        authors = _author_names(bibl)
        if authors:
            ref["authors"] = authors
        for date_el in bibl.iter(f"{TEI}date"):
            when = date_el.get("when") or _text(date_el)
            if when[:4].isdigit():
                ref["year"] = when[:4]
                break
        for idno in bibl.iter(f"{TEI}idno"):
            if (idno.get("type") or "").upper() == "DOI" and _text(idno):
                ref["doi"] = _text(idno)
                break
        raw = _text(bibl.find(f"{TEI}note"))
        if raw:
            ref["raw"] = raw
        if ref:
            refs.append(ref)
    return refs


def tei_to_parsed_paper(tei_xml: str, citekey: str, *, parser: str = "grobid",
                        source_pdf: str = "") -> dict:
    """Normalize a GROBID TEI-XML document into a parsed-paper/1.0 dict."""
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as e:
        raise ParseError(f"GROBID returned non-TEI/invalid XML: {e}") from e
    doc = {
        "schema_version": SCHEMA_VERSION,
        "id": citekey,
        "created": datetime.datetime.now(datetime.timezone.utc)
                   .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "parser": parser,
        "metadata": _parse_metadata(root),
    }
    if source_pdf:
        doc["source_pdf"] = source_pdf
    sections = _parse_sections(root)
    if sections:
        doc["sections"] = sections
    references = _parse_references(root)
    if references:
        doc["references"] = references
    return doc


# -- parser seam -------------------------------------------------------------

def parse_with_grobid(pdf_path: Path, citekey: str, *, url: str) -> dict:
    """The default, stdlib-clean parse_fn: GROBID over HTTP, TEI -> parsed-paper."""
    pdf_bytes = Path(pdf_path).read_bytes()
    tei = grobid_fulltext(pdf_bytes, Path(pdf_path).name, url=url)
    return tei_to_parsed_paper(tei, citekey, parser="grobid",
                               source_pdf=Path(pdf_path).name)


# name -> parse_fn(pdf_path, citekey, *, url). Heavier optional back-ends
# (docling, mineru) register here later WITHOUT changing the core.
PARSERS = {
    "grobid": parse_with_grobid,
}


def get_parser(name: str):
    fn = PARSERS.get(name)
    if fn is None:
        raise ParseError(
            f"unknown parser {name!r} (available: {', '.join(sorted(PARSERS))}). "
            "Heavier parsers (docling/mineru) are optional extras, not bundled.")
    return fn


def grobid_url(explicit: str | None = None, *, profile_url: str | None = None,
               env: dict | None = None) -> str:
    """Resolve the GROBID base URL: CLI flag > env > config > default."""
    env = os.environ if env is None else env
    return (explicit or env.get(ENV_GROBID_URL) or profile_url
            or DEFAULT_GROBID_URL)
