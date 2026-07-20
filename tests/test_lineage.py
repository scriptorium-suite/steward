"""Tests for the deterministic lineage builder (lineage.py).

Small parsed-paper/1.0 fixtures with cross-references drive the within-set
citation graph: a DOI-matched edge, a normalized-title-matched edge, a reference
to a paper OUTSIDE the set (-> no edge), and a self-citation (-> no edge). We
assert the emitted nodes, `cites` edges (+ evidence = matched reference raw),
and the year-ordered timeline. The agent-enriched typed relations / clusters are
out of scope here. stdlib-only — no GROBID, no network.

All paper identities and domain details below are synthetic XQ-17 fixtures.
"""
import json

import pytest

from steward import lineage


def _paper(citekey, *, title="", year="", doi="", references=None):
    md = {}
    if title:
        md["title"] = title
    if year:
        md["year"] = year
    if doi:
        md["doi"] = doi
    return {
        "schema_version": "parsed-paper/1.0",
        "id": citekey,
        "created": "2026-06-22T00:00:00Z",
        "parser": "grobid",
        "metadata": md,
        "references": references or [],
    }


# A 3-paper set with both match modes + an out-of-set reference:
#   study 002 cites study 001 (DOI match) and an OUTSIDE paper (no edge)
#   study 003 cites study 002 (title match, no DOI on the reference)
def _fixture_set():
    study_001 = _paper(
        "xq17SyntheticStudy001",
        title="[SYNTHETIC] Baseline calibration for XQ-17 sensors",
        year="1996", doi="10.0000/scriptorium-demo-xq17-001")
    study_002 = _paper(
        "xq17SyntheticStudy002",
        title="[SYNTHETIC] Robust XQ-17 calibration across operating ranges",
        year="2008", doi="10.0000/scriptorium-demo-xq17-002",
        references=[
            # DOI match -> edge to study 001 (DOI carries a resolver prefix +
            # uppercase to exercise normalization)
            {"raw": "Researcher XQ-17-01 et al. (1996) Baseline XQ-17 calibration.",
             "title": "[SYNTHETIC] Baseline calibration for XQ-17 sensors",
             "year": "1996", "doi": "https://doi.org/10.0000/SCRIPTORIUM-DEMO-XQ17-001"},
            # out-of-set reference -> NO edge
            {"raw": "Researcher XQ-17-00 (1983) Preliminary XQ-17 observations.",
             "title": "[SYNTHETIC] Preliminary XQ-17 observations",
             "year": "1983", "doi": "10.0000/scriptorium-demo-xq17-000"},
        ])
    study_003 = _paper(
        "xq17SyntheticStudy003",
        title="[SYNTHETIC] An adaptive XQ-17 calibration method",
        year="2017", doi="10.0000/scriptorium-demo-xq17-003",
        references=[
            # title match (no DOI on the reference) -> edge to study 002; the
            # cited title differs in punctuation/case to exercise normalization
            {"raw": "Researcher XQ-17-02 (2008) Robust XQ-17 calibration across operating ranges.",
             "title": "[synthetic] robust xq-17 calibration across operating ranges!",
             "year": "2008"},
        ])
    return [study_001, study_002, study_003]


# -- nodes -------------------------------------------------------------------

def test_nodes_carry_citekey_title_year():
    graph = lineage.build_graph(_fixture_set(), query="[SYNTHETIC] XQ-17 calibration lineage",
                                created="2026-06-22T00:00:00Z")
    assert graph["schema_version"] == "lineage-graph/1.0"
    assert graph["generated_by"] == "steward lineage"
    assert graph["direction"] == {
        "query": "[SYNTHETIC] XQ-17 calibration lineage",
        "scope_method": "own-library citation match",
        "created": "2026-06-22T00:00:00Z",
    }
    nodes = {n["citekey"]: n for n in graph["nodes"]}
    assert set(nodes) == {"xq17SyntheticStudy001", "xq17SyntheticStudy002",
                          "xq17SyntheticStudy003"}
    assert nodes["xq17SyntheticStudy002"]["title"] == \
        "[SYNTHETIC] Robust XQ-17 calibration across operating ranges"
    assert nodes["xq17SyntheticStudy002"]["year"] == "2008"


# -- edges: within-set citation matching -------------------------------------

def test_doi_match_makes_a_cites_edge_with_raw_evidence():
    graph = lineage.build_graph(_fixture_set())
    edges = [e for e in graph["edges"]
             if e["from"] == "xq17SyntheticStudy002"]
    # exactly one edge: the DOI match to 1996 (study 000 is out-of-set)
    assert len(edges) == 1
    e = edges[0]
    assert e == {
        "from": "xq17SyntheticStudy002",
        "to": "xq17SyntheticStudy001",
        "relation": "cites",
        "evidence": "Researcher XQ-17-01 et al. (1996) Baseline XQ-17 calibration.",
    }


def test_title_match_makes_a_cites_edge_when_no_doi():
    graph = lineage.build_graph(_fixture_set())
    edges = [e for e in graph["edges"] if e["from"] == "xq17SyntheticStudy003"]
    assert len(edges) == 1
    assert edges[0]["to"] == "xq17SyntheticStudy002"
    assert edges[0]["relation"] == "cites"
    assert edges[0]["evidence"].startswith("Researcher XQ-17-02 (2008)")


def test_all_edges_are_cites_only():
    # the deterministic builder never emits typed relations (agent does, later)
    graph = lineage.build_graph(_fixture_set())
    assert {e["relation"] for e in graph["edges"]} == {"cites"}
    assert len(graph["edges"]) == 2          # 1996<-2008, 2008<-2017


def test_reference_outside_the_set_makes_no_edge():
    # study 002 references study 000, which is NOT in the set -> no edge to it
    graph = lineage.build_graph(_fixture_set())
    targets = {e["to"] for e in graph["edges"]}
    assert "xq17SyntheticStudy000" not in targets
    assert all(e["to"] in {"xq17SyntheticStudy001", "xq17SyntheticStudy002",
                           "xq17SyntheticStudy003"} for e in graph["edges"])


def test_self_citation_makes_no_edge():
    p = _paper("self2020", title="Self Referential Work", year="2020",
               doi="10.1/self",
               references=[{"raw": "Self (2020) Self Referential Work.",
                            "title": "Self Referential Work", "doi": "10.1/self"}])
    graph = lineage.build_graph([p])
    assert graph["edges"] == []


def test_singleton_set_has_no_edges():
    graph = lineage.build_graph([_paper("only2021", title="Alone", year="2021")])
    assert graph["nodes"] == [{"citekey": "only2021", "title": "Alone", "year": "2021"}]
    assert graph["edges"] == []


# -- timeline ----------------------------------------------------------------

def test_timeline_is_year_ascending():
    graph = lineage.build_graph(_fixture_set())
    assert graph["timeline"] == [
        "xq17SyntheticStudy001",
        "xq17SyntheticStudy002",
        "xq17SyntheticStudy003",
    ]


def test_timeline_puts_yearless_papers_last_keeping_input_order():
    papers = [
        _paper("noyear1", title="No year A"),
        _paper("y2010", title="Has year", year="2010"),
        _paper("noyear2", title="No year B"),
    ]
    graph = lineage.build_graph(papers)
    assert graph["timeline"] == ["y2010", "noyear1", "noyear2"]


# -- normalization helpers ---------------------------------------------------

def test_norm_doi_strips_resolver_and_lowercases():
    assert lineage._norm_doi("https://doi.org/10.1/AbC") == "10.1/abc"
    assert lineage._norm_doi("doi:10.1/X") == "10.1/x"
    assert lineage._norm_doi(None) == ""


def test_norm_title_collapses_punctuation_and_case():
    assert lineage._norm_title("[synthetic] robust XQ-17 calibration!") \
        == lineage._norm_title("[SYNTHETIC] Robust XQ-17 Calibration")


# -- loading -----------------------------------------------------------------

def test_load_set_reads_files_and_dedups_on_citekey(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps(_paper("k1", title="A", year="2001")), encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps(_paper("k1", title="A dup", year="2001")), encoding="utf-8")
    c = tmp_path / "c.json"
    c.write_text(json.dumps(_paper("k2", title="C", year="2002")), encoding="utf-8")
    papers = lineage.load_set([a, b, c])
    assert [p["id"] for p in papers] == ["k1", "k2"]      # b deduped (k1 seen)


def test_load_parsed_rejects_wrong_schema(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"schema_version": "library-kb/1.0", "items": []}),
                 encoding="utf-8")
    with pytest.raises(lineage.LineageError, match="not a parsed-paper/1.0"):
        lineage.load_parsed(f)


def test_load_parsed_rejects_missing_citekey(tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"schema_version": "parsed-paper/1.0", "created": "now"}),
                 encoding="utf-8")
    with pytest.raises(lineage.LineageError, match="no `id`"):
        lineage.load_parsed(f)
