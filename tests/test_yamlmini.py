# [SYNTHETIC] XQ-17 fixtures only; no value represents a real paper, author, DOI, or research record.
from steward import yamlmini as y


def test_scalars_and_types():
    doc = y.parse(
        "n_splits: 10\n"
        "ratio: 0.03\n"
        "neg: -0.1\n"
        "flag: true\n"
        "off: false\n"
        "empty:\n"
        "name: plain text\n"
        "quoted: '0'\n"
        "ts: '2026-06-11T19:56:50.503146'\n"
    )
    assert doc["n_splits"] == 10 and isinstance(doc["n_splits"], int)
    assert doc["ratio"] == 0.03
    assert doc["neg"] == -0.1
    assert doc["flag"] is True and doc["off"] is False
    assert doc["empty"] is None
    assert doc["name"] == "plain text"
    assert doc["quoted"] == "0"               # quoted digit stays a string
    assert doc["ts"] == "2026-06-11T19:56:50.503146"


def test_nested_maps_and_block_sequences():
    doc = y.parse(
        "data_shape:\n"
        "  n_features: 18\n"
        "  by_set:\n"
        "    Liquid: 18\n"
        "    NoLiquid: 9\n"
        "feature_sets:\n"
        "- NoLiquid\n"
        "- Liquid\n"
    )
    assert doc["data_shape"]["n_features"] == 18
    assert doc["data_shape"]["by_set"] == {"Liquid": 18, "NoLiquid": 9}
    assert doc["feature_sets"] == ["NoLiquid", "Liquid"]   # seq items at the key's indent


def test_sequence_of_mappings_with_nested_blocks():
    doc = y.parse(
        "experiments:\n"
        "- exp_id: E01\n"
        "  model_module: ert\n"
        "  model_params:\n"
        "    max_depth: 15\n"
        "    n_jobs: 4\n"
        "  data_params:\n"
        "    feature_names:\n"
        "    - SiO2.xq17_synthetic\n"
        "    - TiO2.xq17_synthetic\n"
        "    n_aug: 15\n"
        "- exp_id: E02\n"
        "  model_module: stacking\n"
        "  model_params:\n"
        "    base_model_params:\n"
        "      catboost:\n"
        "        depth: 6\n"
        "    inner_cv: 5\n"
    )
    exps = doc["experiments"]
    assert len(exps) == 2
    assert exps[0]["exp_id"] == "E01"
    assert exps[0]["model_params"] == {"max_depth": 15, "n_jobs": 4}
    assert exps[0]["data_params"]["feature_names"] == ["SiO2.xq17_synthetic", "TiO2.xq17_synthetic"]
    assert exps[0]["data_params"]["n_aug"] == 15
    assert exps[1]["model_params"]["base_model_params"]["catboost"]["depth"] == 6
    assert exps[1]["model_params"]["inner_cv"] == 5


def test_inline_flow_and_empty_collections():
    doc = y.parse(
        "next_actions: [回复审稿意见 R2, V8-m32 消融实验收尾]\n"
        "corr_params: {}\n"
        "empties: []\n"
        "obj: {a: 1, b: two}\n"
    )
    assert doc["next_actions"] == ["回复审稿意见 R2", "V8-m32 消融实验收尾"]
    assert doc["corr_params"] == {}
    assert doc["empties"] == []
    assert doc["obj"] == {"a": 1, "b": "two"}


def test_multiline_plain_scalar_continuation():
    doc = y.parse(
        "version_info:\n"
        "  python_version: 3.10.13 | packaged by Anaconda, Inc. | (main, Sep 11 2023)\n"
        "    [MSC v.1916 64 bit (AMD64)]\n"
        "  timestamp: '2026-06-11T19:56:50'\n"
    )
    assert "MSC v.1916" in doc["version_info"]["python_version"]
    assert doc["version_info"]["timestamp"] == "2026-06-11T19:56:50"   # sibling, not gobbled


def test_parse_frontmatter():
    md = (
        "---\n"
        "schema_version: project/1.0\n"
        "project_id: ml-xq17_synthetic\n"
        "linked_repo: C:/ScriptoriumDemo/repos/xq17-benchmark\n"
        "next_actions: [a, b]\n"
        "---\n"
        "\n# body\nstuff\n"
    )
    fm = y.parse_frontmatter(md)
    assert fm["project_id"] == "ml-xq17_synthetic"
    assert fm["linked_repo"] == "C:/ScriptoriumDemo/repos/xq17-benchmark"  # colon in value preserved
    assert fm["next_actions"] == ["a", "b"]


def test_parse_frontmatter_absent():
    assert y.parse_frontmatter("# just a note\nno frontmatter here\n") == {}
    assert y.parse_frontmatter("﻿---\nk: v\n---\n")["k"] == "v"   # tolerates a BOM
