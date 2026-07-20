"""Tests for the lineage-graph/1.0 -> Markdown projection (lineage_render.py).

Renders a representative lineage-graph/1.0 (inlined, mirroring the shipped
scriptorium-spec example) and
asserts the self-contained note carries: a ```mermaid block, one relation-labeled
mermaid edge per graph edge, a node per graph node, a timeline, and a
|from|relation|to| edge table. Plus determinism (same input -> identical output),
wrong schema_version -> RenderError, and that --stamp-notes never creates a
missing note while merging (not clobbering) an existing one. stdlib-only.
"""
import re

import pytest

from steward import lineage_render


# A representative lineage-graph/1.0, inlined so the test is self-contained and
# portable (no dependency on a sibling repo's checkout path). Mirrors the example
# shipped with the schema: a fully synthetic XQ-17 calibration family —
# 4 nodes, 4 edges (one per typed relation), 2 clusters, and a timeline.
def _example_graph() -> dict:
    return {
        "schema_version": "lineage-graph/1.0",
        "direction": {
            "query": "[SYNTHETIC] XQ-17 calibration lineage",
            "scope_method": "own-library reference walk (Steward lineage) + agent typing during synthesis",
            "created": "2026-06-22T11:00:00Z",
        },
        "nodes": [
            {"citekey": "xq17SyntheticStudy000", "title": "[SYNTHETIC] Preliminary XQ-17 observations", "year": "1983", "cluster": "xq17-foundations"},
            {"citekey": "xq17SyntheticStudy001", "title": "[SYNTHETIC] Baseline calibration for XQ-17 sensors", "year": "1996", "cluster": "xq17-models"},
            {"citekey": "xq17SyntheticStudy004", "title": "[SYNTHETIC] Expanded XQ-17 calibration dataset", "year": "2003", "cluster": "xq17-models"},
            {"citekey": "xq17SyntheticStudy002", "title": "[SYNTHETIC] Robust XQ-17 calibration across operating ranges", "year": "2008", "cluster": "xq17-models"},
        ],
        "edges": [
            {"from": "xq17SyntheticStudy001", "to": "xq17SyntheticStudy000", "relation": "cites"},
            {"from": "xq17SyntheticStudy004", "to": "xq17SyntheticStudy001", "relation": "extends", "evidence": "_parsed/xq17SyntheticStudy004.grobid.json#sec-calibration (expands the synthetic baseline dataset)"},
            {"from": "xq17SyntheticStudy002", "to": "xq17SyntheticStudy004", "relation": "supersedes", "evidence": "_parsed/xq17SyntheticStudy002.grobid.json#sec-model (the updated synthetic formulation replaces the earlier version)"},
            {"from": "xq17SyntheticStudy002", "to": "xq17SyntheticStudy000", "relation": "method-of", "evidence": "_parsed/xq17SyntheticStudy002.grobid.json#sec-validation"},
        ],
        "clusters": [
            {"id": "xq17-foundations", "label": "Synthetic XQ-17 foundations"},
            {"id": "xq17-models", "label": "Synthetic XQ-17 calibration models"},
        ],
        "timeline": ["xq17SyntheticStudy000", "xq17SyntheticStudy001", "xq17SyntheticStudy004", "xq17SyntheticStudy002"],
    }


# -- render: structure -------------------------------------------------------

def test_render_has_a_mermaid_block():
    md = lineage_render.render(_example_graph())
    assert "```mermaid" in md
    assert "graph LR" in md
    # the fenced block is closed
    assert md.count("```") == 2


def test_render_has_one_relation_labeled_edge_per_graph_edge():
    graph = _example_graph()
    md = lineage_render.render(graph)
    # every graph edge appears as a `-->|relation|` mermaid arrow
    arrows = re.findall(r"-->\|([a-z-]+)\|", md)
    rels = [e["relation"] for e in graph["edges"]]
    assert sorted(arrows) == sorted(rels)
    assert len(arrows) == len(graph["edges"])


def test_render_declares_a_node_per_graph_node():
    graph = _example_graph()
    md = lineage_render.render(graph)
    # one `n_..["label"]` declaration per node; ids derive from the citekey
    for n in graph["nodes"]:
        safe = re.sub(r"[^A-Za-z0-9_]", "_", n["citekey"])
        assert f"n_{safe}[" in md


def test_render_groups_clusters_into_subgraphs():
    graph = _example_graph()
    md = lineage_render.render(graph)
    for c in graph["clusters"]:
        assert c["label"] in md
    assert md.count("subgraph") == len(graph["clusters"])
    assert "end" in md


def test_render_has_a_timeline_in_graph_order():
    graph = _example_graph()
    md = lineage_render.render(graph)
    assert "## Timeline" in md
    # the timeline citekeys appear in the graph's stated order
    positions = [md.index(f"`{k}`") for k in graph["timeline"]]
    assert positions == sorted(positions)


def test_render_has_a_from_relation_to_edge_table():
    graph = _example_graph()
    md = lineage_render.render(graph)
    assert "| from | relation | to | evidence |" in md
    assert "| --- | --- | --- | --- |" in md
    # one table row per edge, carrying from/relation/to (+ evidence when present)
    for e in graph["edges"]:
        assert f"`{e['from']}`" in md and f"`{e['to']}`" in md
        if e.get("evidence"):
            assert e["evidence"] in md


def test_render_frontmatter_reuses_graph_created_not_a_clock():
    graph = _example_graph()
    md = lineage_render.render(graph)
    assert md.startswith("---\n")
    assert "tags: [lineage]" in md
    # created is COPIED from the graph, never regenerated
    assert graph["direction"]["created"] in md


def test_render_footer_states_machine_source_of_truth():
    md = lineage_render.render(_example_graph())
    assert "Machine source of truth: the lineage-graph/1.0 JSON" in md
    assert "4 nodes, 4 edges" in md


# -- render: determinism + validation ----------------------------------------

def test_render_is_deterministic():
    a = lineage_render.render(_example_graph())
    b = lineage_render.render(_example_graph())
    assert a == b


def test_render_rejects_wrong_schema_version():
    with pytest.raises(lineage_render.RenderError, match="not a lineage-graph/1.0"):
        lineage_render.render({"schema_version": "library-kb/1.0", "nodes": []})


def test_render_rejects_non_dict():
    with pytest.raises(lineage_render.RenderError):
        lineage_render.render([])  # type: ignore[arg-type]


def test_render_self_contained_drops_edges_to_unknown_nodes():
    graph = {
        "schema_version": "lineage-graph/1.0",
        "direction": {"query": "q", "scope_method": "m", "created": "2026-01-01"},
        "nodes": [{"citekey": "a", "title": "A", "year": "2001"}],
        "edges": [{"from": "a", "to": "ghost", "relation": "cites"}],
    }
    md = lineage_render.render(graph)
    # no mermaid arrow to a node that isn't declared
    assert "-->|" not in md


def test_render_escapes_problematic_node_labels():
    graph = {
        "schema_version": "lineage-graph/1.0",
        "direction": {"query": "q", "scope_method": "m", "created": "2026-01-01"},
        "nodes": [{"citekey": "wei2022", "title": 'Chain-of-Thought ("CoT")\nprompting',
                   "year": "2022"}],
        "edges": [],
    }
    md = lineage_render.render(graph)
    block = md.split("```mermaid", 1)[1].split("```", 1)[0]
    # the quote/paren/newline never survive into the mermaid node label
    assert '"CoT"' not in block
    assert "\n" not in _node_decl_line(block)


def _node_decl_line(block: str) -> str:
    for ln in block.splitlines():
        if ln.strip().startswith("n_wei2022["):
            return ln
    return ""


# -- stamp-notes: opportunistic, merge-not-clobber ---------------------------

def _stamp_graph() -> dict:
    return {
        "schema_version": "lineage-graph/1.0",
        "direction": {"query": "q", "scope_method": "m", "created": "2026-01-01"},
        "nodes": [
            {"citekey": "a2008", "title": "A", "year": "2008"},
            {"citekey": "b2003", "title": "B", "year": "2003"},
            {"citekey": "c1996", "title": "C", "year": "1996"},
        ],
        "edges": [
            {"from": "a2008", "to": "b2003", "relation": "supersedes"},
            {"from": "a2008", "to": "c1996", "relation": "method-of"},
            {"from": "b2003", "to": "c1996", "relation": "extends"},  # b2003 note absent
        ],
    }


def test_stamp_notes_never_creates_a_missing_note(tmp_path):
    (tmp_path / "Literature").mkdir()
    # only a2008's note exists; b2003 / c1996 are lean-vault (absent)
    note = tmp_path / "Literature" / "a2008.md"
    note.write_text("---\ncitekey: a2008\n---\n\nbody\n", encoding="utf-8")

    changed = lineage_render.stamp_notes(_stamp_graph(), tmp_path)

    assert (tmp_path / "Literature" / "a2008.md").is_file()
    assert not (tmp_path / "Literature" / "b2003.md").exists()
    assert not (tmp_path / "Literature" / "c1996.md").exists()
    assert changed == [note]  # only the existing note was touched


def test_stamp_notes_merges_does_not_clobber_existing_frontmatter(tmp_path):
    (tmp_path / "Literature").mkdir()
    note = tmp_path / "Literature" / "a2008.md"
    note.write_text(
        "---\n"
        "citekey: a2008\n"
        "tags: [paper, keep-me]\n"
        'supersedes: ["[[oldtarget]]"]\n'
        "---\n\n"
        "hand-authored body\n",
        encoding="utf-8")

    lineage_render.stamp_notes(_stamp_graph(), tmp_path)
    out = note.read_text(encoding="utf-8")

    # pre-existing keys are preserved verbatim
    assert "citekey: a2008" in out
    assert "tags: [paper, keep-me]" in out
    assert "hand-authored body" in out
    # the supersedes list MERGED (old kept, new appended) — never clobbered
    assert "[[oldtarget]]" in out
    assert "[[b2003]]" in out
    # a relation key not previously present is added (method-of -> c1996)
    assert re.search(r'method-of: \[.*\[\[c1996\]\].*\]', out)


def test_stamp_notes_is_idempotent(tmp_path):
    (tmp_path / "reading-notes").mkdir()
    note = tmp_path / "reading-notes" / "a2008.md"
    note.write_text("---\ncitekey: a2008\n---\n\nbody\n", encoding="utf-8")

    lineage_render.stamp_notes(_stamp_graph(), tmp_path)
    first = note.read_text(encoding="utf-8")
    changed2 = lineage_render.stamp_notes(_stamp_graph(), tmp_path)
    second = note.read_text(encoding="utf-8")

    assert first == second          # re-running adds nothing
    assert changed2 == []           # nothing reported as changed the 2nd time


def test_stamp_notes_finds_notes_in_reading_notes_too(tmp_path):
    (tmp_path / "reading-notes").mkdir()
    note = tmp_path / "reading-notes" / "a2008.md"
    note.write_text("---\ncitekey: a2008\n---\n\nbody\n", encoding="utf-8")
    changed = lineage_render.stamp_notes(_stamp_graph(), tmp_path)
    assert changed == [note]


def test_find_note_returns_none_for_absent(tmp_path):
    assert lineage_render.find_note(tmp_path, "nope") is None
