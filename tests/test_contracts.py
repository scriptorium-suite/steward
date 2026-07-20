"""Contract hygiene: the package's declared PRODUCES / CONSUMES must match the
schema_version / SCHEMA constants each module actually emits or reads.

This is the guard that caught the experiment-log removal drift: if a module's
contract string changes (or a format is added/dropped) without updating
`steward.__init__`, one of these assertions fails.
"""
import importlib
import json

import pytest

import steward
from steward import pick, proposal, review, tagging


# -- producers ---------------------------------------------------------------

def test_proposal_producer_constant_in_produces():
    # proposal.SCHEMA_VERSION is the producer contract.
    assert proposal.SCHEMA_VERSION == "proposal/1.0"
    assert proposal.SCHEMA_VERSION in steward.PRODUCES


def test_export_produces_library_kb():
    # export has no module constant; the contract string is written inline by
    # write_kb_json. Assert PRODUCES carries it (and the literal still lives in
    # the source as the single emission point).
    assert "library-kb/1.1" in steward.PRODUCES
    assert "library-kb/1.0" not in steward.PRODUCES


def test_pick_emits_both_handoff_versions(tmp_path):
    # pick uses inline literals; drive both code paths and read the real
    # schema_version off the emitted meta.json, then check PRODUCES lists each.
    def entry(key, name):
        pdf = tmp_path / name
        pdf.write_bytes(b"%PDF-1.4 " + key.encode())
        return {"key": key, "title": f"Paper {key}", "authors": ["Ng"],
                "year": "2020", "doi": f"10.1/{key}", "tldr": "t", "abstract": "a",
                "folders": ["X"], "pdfPaths": [str(pdf)]}

    single = pick.stage(entry("AAAAAAA1", "a.pdf"), tmp_path / "h1")
    multi = pick.stage_report([entry("BBBBBBB1", "b.pdf"), entry("BBBBBBB2", "c.pdf")],
                              tmp_path / "h2")
    sv_single = json.loads((single / "meta.json").read_text(encoding="utf-8"))["schema_version"]
    sv_multi = json.loads((multi / "meta.json").read_text(encoding="utf-8"))["schema_version"]
    assert sv_single == "handoff/1.0"          # single-paper subset (D2 default)
    assert sv_multi == "handoff/1.1"           # multi-paper
    assert sv_single in steward.PRODUCES
    assert sv_multi in steward.PRODUCES


def test_produces_is_exactly_the_known_producers():
    # the full producer set after the experiment-removal: no experiment-log.
    assert set(steward.PRODUCES) == {
        "library-kb/1.1", "handoff/1.0", "handoff/1.1", "proposal/1.0",
        "parsed-paper/1.0", "lineage-graph/1.0"}


def test_parse_producer_constant_in_produces():
    from steward import parse
    assert parse.SCHEMA_VERSION == "parsed-paper/1.0"
    assert parse.SCHEMA_VERSION in steward.PRODUCES


def test_lineage_producer_constant_in_produces():
    from steward import lineage
    assert lineage.SCHEMA_VERSION == "lineage-graph/1.0"
    assert lineage.SCHEMA_VERSION in steward.PRODUCES


# -- consumers ---------------------------------------------------------------

def test_tagging_consumer_constant_in_consumes():
    assert tagging.SCHEMA == "tag-plan/1.0"
    assert tagging.SCHEMA in steward.CONSUMES


def test_review_consumes_draft_not_local_input():
    # review consumes the external draft contract; the review-input intermediate
    # is steward-local (scaffold -> assemble) and must NOT be declared as a
    # cross-tool consumed format.
    assert review.DRAFT_SCHEMA == "review-draft/1.0"
    assert review.DRAFT_SCHEMA in steward.CONSUMES
    assert review.INPUT_SCHEMA == "review-input/1.0"
    assert review.INPUT_SCHEMA not in steward.CONSUMES


def test_portfolio_consumes_project():
    # portfolio matches `project/1` frontmatter by prefix (no module constant);
    # assert the declared consumed format is present.
    assert "project/1.0" in steward.CONSUMES


def test_review_also_consumes_library_kb():
    # First-party readers retain 1.0 compatibility while export moves to 1.1.
    assert set(steward.LIBRARY_KB_SCHEMAS) == {
        "library-kb/1.0", "library-kb/1.1"}
    assert set(steward.LIBRARY_KB_SCHEMAS).issubset(steward.CONSUMES)


def test_consumes_is_exactly_the_known_consumers():
    assert set(steward.CONSUMES) == {
        "proposal/1.0", "tag-plan/1.0", "project/1.0",
        "library-kb/1.0", "library-kb/1.1", "review-draft/1.0"}


# -- experiment-log removal regression ---------------------------------------

def test_ingest_module_is_gone():
    # ingest.py was removed with the experiment-tracking teardown; importing it
    # must fail, and no contract may mention experiment-log.
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("steward.ingest")


def test_no_experiment_log_contract():
    assert not any("experiment-log" in c for c in steward.PRODUCES + steward.CONSUMES)
