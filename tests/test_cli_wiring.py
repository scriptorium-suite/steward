"""CLI wiring tests for the 7 write commands through cli.main().

For each of export / pick / tag / backup / propose / apply / rollback:
- a dry-run (or no-network) happy path returning 0, and
- a missing-config / missing-input path returning exit code 2.

Network-touching steps are monkeypatched so wiring is exercised without a live
Zotero. Module-level behavior is covered elsewhere; this file only asserts that
cli.main() routes args, gates on config, and maps errors to exit codes.
"""
import json
import sqlite3

import pytest

from steward import cli
from steward import config as cfg
from steward import apply as apply_mod
from steward import export as export_mod
from steward import parse as parse_mod
from steward import proposal as proposal_mod
from steward import tagging as tag_mod
from steward.zotero_api import ZoteroError


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """Isolated config root with NO ambient Zotero env vars."""
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path / "cfgroot"))
    for var in (cfg.ENV_API_KEY, cfg.ENV_LIBRARY_ID, cfg.ENV_LIBRARY_TYPE, cfg.ENV_LOCAL):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def web_creds(clean_env, monkeypatch):
    """Same isolation, but with web credentials present in the environment."""
    monkeypatch.setenv(cfg.ENV_LIBRARY_ID, "42")
    monkeypatch.setenv(cfg.ENV_API_KEY, "secret")
    return clean_env


# -- backup ------------------------------------------------------------------

def _make_data_dir(tmp_path):
    data = tmp_path / "zdata"
    data.mkdir()
    con = sqlite3.connect(data / "zotero.sqlite")
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    return data


def test_backup_missing_config(clean_env, capsys):
    rc = cli.main(["backup"])
    assert rc == 2
    assert "missing config" in capsys.readouterr().out


def test_backup_runs_with_configured_profile(clean_env, capsys):
    data = _make_data_dir(clean_env)
    from steward.config import Profile
    cfg.write_profile(Profile(name="default", data_dir=str(data),
                              backup_dir=str(clean_env / "bak")))
    rc = cli.main(["backup"])
    assert rc == 0
    assert "BACKUP OK" in capsys.readouterr().out


# -- propose -----------------------------------------------------------------

def test_propose_happy_path(clean_env, fake_zotero_db, capsys):
    tree = clean_env / "tree.txt"
    tree.write_text("00_Inbox\n01_ML\n", encoding="utf-8")
    out = clean_env / "proposal.json"
    rc = cli.main(["propose", "--db", str(fake_zotero_db),
                   "--tree", str(tree), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"].startswith("proposal/1.")
    assert "PROPOSAL-PROMPT.md" in capsys.readouterr().out


def test_propose_missing_config(clean_env, capsys):
    tree = clean_env / "tree.txt"
    tree.write_text("01_ML\n", encoding="utf-8")
    # no --db and no configured data_dir
    rc = cli.main(["propose", "--tree", str(tree), "--out", str(clean_env / "p.json")])
    assert rc == 2
    assert "missing config: data_dir" in capsys.readouterr().out


# -- apply -------------------------------------------------------------------

def _write_proposal(path):
    path.write_text(json.dumps({
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "A/B"],
        "proposals": [{"key": "AAAAAAA1", "targets": ["A/B"]}],
    }), encoding="utf-8")
    return path


def test_apply_dry_run_happy_path(web_creds, monkeypatch, capsys):
    prop = _write_proposal(web_creds / "proposal.json")
    # stub the network-touching plan; without --run, execute() is never reached
    monkeypatch.setattr(apply_mod, "plan", lambda doc, client: {
        "collections_to_create": ["A/B"], "keys_not_on_server": []})
    called = {"execute": False}
    monkeypatch.setattr(apply_mod, "execute",
                        lambda *a, **k: called.__setitem__("execute", True))
    rc = cli.main(["apply", str(prop)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert called["execute"] is False          # dry-run must not write


def test_apply_missing_config(clean_env, capsys):
    prop = _write_proposal(clean_env / "proposal.json")
    rc = cli.main(["apply", str(prop)])        # no library_id / api_key
    assert rc == 2
    err = capsys.readouterr().err
    assert "web API requires" in err


# -- rollback ----------------------------------------------------------------

def test_rollback_dry_run_happy_path(web_creds, monkeypatch, capsys):
    journal = web_creds / "j.json"
    journal.write_text("{}", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(apply_mod, "rollback",
                        lambda jp, client, p, run: seen.update(run=run))
    rc = cli.main(["rollback", str(journal)])  # no --run -> dry run
    assert rc == 0
    assert seen == {"run": False}              # forwarded run=False


def test_rollback_list_needs_no_creds(clean_env, capsys):
    rc = cli.main(["rollback", "--list"])
    assert rc == 0
    assert "no journals found" in capsys.readouterr().out


def test_rollback_missing_config(clean_env, capsys):
    journal = clean_env / "j.json"
    journal.write_text("{}", encoding="utf-8")
    rc = cli.main(["rollback", str(journal)])  # no creds -> _web_client raises
    assert rc == 2
    assert "web API requires" in capsys.readouterr().err


# -- tag (apply) -------------------------------------------------------------

def _write_tag_plan(path):
    path.write_text(json.dumps({
        "schema_version": "tag-plan/1.0",
        "items": [{"key": "AAAAAAA1", "aiTags": ["ml"], "tldr": "ok",
                   "readStatus": "Read"}],
    }), encoding="utf-8")
    return path


def test_tag_apply_dry_run_happy_path(web_creds, monkeypatch, capsys):
    plan = _write_tag_plan(web_creds / "tag-plan.json")
    called = {"execute": False}
    monkeypatch.setattr(tag_mod, "execute",
                        lambda *a, **k: called.__setitem__("execute", True))
    rc = cli.main(["tag", "apply", str(plan)])  # no --run
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert called["execute"] is False


def test_tag_apply_missing_config(clean_env, capsys):
    plan = _write_tag_plan(clean_env / "tag-plan.json")
    rc = cli.main(["tag", "apply", str(plan)])  # no creds
    assert rc == 2
    assert "web API requires" in capsys.readouterr().err


# -- pick --------------------------------------------------------------------

def _write_kb_with_pdf(clean_env):
    pdf = clean_env / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    kb = clean_env / "library.json"
    kb.write_text(json.dumps({
        "schema_version": "library-kb/1.0",
        "items": [{"key": "AAAAAAA1", "title": "A Paper", "authors": ["X"],
                   "year": "2024", "doi": "", "tldr": "t",
                   "folders": ["01_ML"], "pdfPaths": [str(pdf)]}],
    }), encoding="utf-8")
    return kb


def test_pick_happy_path(clean_env, capsys):
    kb = _write_kb_with_pdf(clean_env)
    staging = clean_env / "handoff"
    rc = cli.main(["pick", "AAAAAAA1", "--kb", str(kb), "--staging", str(staging)])
    assert rc == 0
    dest = staging / "AAAAAAA1"
    assert (dest / "meta.json").is_file()
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == "handoff/1.0"
    assert "staged:" in capsys.readouterr().out


def test_pick_missing_kb(clean_env, capsys):
    rc = cli.main(["pick", "AAAAAAA1", "--kb", str(clean_env / "nope.json"),
                   "--staging", str(clean_env / "h")])
    assert rc == 2
    assert "KB not found" in capsys.readouterr().out


# -- parse -------------------------------------------------------------------

def test_parse_happy_path_resolves_via_kb(clean_env, monkeypatch, capsys):
    kb = _write_kb_with_pdf(clean_env)
    # stub the GROBID back-end (no Java service, no network)
    monkeypatch.setitem(parse_mod.PARSERS, "grobid",
                        lambda pdf, ck, *, url: {
                            "schema_version": "parsed-paper/1.0", "id": ck,
                            "created": "2026-06-22T00:00:00Z", "parser": "grobid",
                            "metadata": {"title": "A Paper"},
                            "sections": [{"heading": "Intro", "text": "x"}],
                            "references": []})
    out = clean_env / "parsed" / "AAAAAAA1.json"
    rc = cli.main(["parse", "AAAAAAA1", "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "parsed-paper/1.0"
    assert doc["id"] == "AAAAAAA1"
    assert "parsed-paper/1.0 ->" in capsys.readouterr().out


def test_parse_direct_pdf_path_needs_no_kb(clean_env, monkeypatch, capsys):
    pdf = clean_env / "mypaper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setitem(parse_mod.PARSERS, "grobid",
                        lambda p, ck, *, url: {
                            "schema_version": "parsed-paper/1.0", "id": ck,
                            "created": "2026-06-22T00:00:00Z", "parser": "grobid",
                            "metadata": {}})
    out = clean_env / "out.json"
    rc = cli.main(["parse", str(pdf), "--out", str(out)])
    assert rc == 0
    # citekey defaults to the PDF stem when parsing a path directly
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "mypaper"


def test_parse_grobid_down_exits_2(clean_env, monkeypatch, capsys):
    kb = _write_kb_with_pdf(clean_env)

    def boom(pdf, ck, *, url):
        raise parse_mod.ParseError("cannot reach GROBID at http://localhost:8070")
    monkeypatch.setitem(parse_mod.PARSERS, "grobid", boom)
    rc = cli.main(["parse", "AAAAAAA1", "--kb", str(kb),
                   "--out", str(clean_env / "p.json")])
    assert rc == 2
    assert "cannot reach GROBID" in capsys.readouterr().err


def test_parse_missing_kb_for_citekey_exits_2(clean_env, capsys):
    # a non-file target with no --kb cannot be resolved
    rc = cli.main(["parse", "somecitekey", "--out", str(clean_env / "p.json")])
    assert rc == 2
    assert "pass --kb" in capsys.readouterr().err


# -- lineage -----------------------------------------------------------------

def _write_parsed(dir_path, citekey, *, title, year, references=None):
    dir_path.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": "parsed-paper/1.0", "id": citekey,
           "created": "2026-06-22T00:00:00Z", "parser": "grobid",
           "metadata": {"title": title, "year": year},
           "references": references or []}
    (dir_path / f"{citekey}.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_lineage_happy_path_over_a_parsed_dir(clean_env, capsys):
    parsed = clean_env / "parsed"
    _write_parsed(parsed, "a1996", title="Older work", year="1996",
                  references=[])
    _write_parsed(parsed, "b2008", title="Newer work", year="2008",
                  references=[{"raw": "Older work (1996).", "title": "Older work",
                               "year": "1996"}])
    out = clean_env / "lineage.json"
    rc = cli.main(["lineage", "--papers", str(parsed),
                   "--query", "a direction", "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert graph["schema_version"] == "lineage-graph/1.0"
    assert graph["direction"]["query"] == "a direction"
    assert {e["from"] for e in graph["edges"]} == {"b2008"}
    assert graph["edges"][0]["to"] == "a1996"
    assert "lineage-graph/1.0 ->" in capsys.readouterr().out


def test_lineage_accepts_explicit_file_list(clean_env, capsys):
    parsed = clean_env / "p"
    _write_parsed(parsed, "x", title="X", year="2001")
    _write_parsed(parsed, "y", title="Y", year="2002")
    out = clean_env / "g.json"
    rc = cli.main(["lineage", "--papers", str(parsed / "x.json"),
                   str(parsed / "y.json"), "--out", str(out)])
    assert rc == 0
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert [n["citekey"] for n in graph["nodes"]] == ["x", "y"]


def test_lineage_missing_path_exits_2(clean_env, capsys):
    rc = cli.main(["lineage", "--papers", str(clean_env / "nope"),
                   "--out", str(clean_env / "g.json")])
    assert rc == 2
    assert "no such file or directory" in capsys.readouterr().err


def test_lineage_wrong_schema_input_exits_2(clean_env, capsys):
    bad = clean_env / "bad.json"
    bad.write_text(json.dumps({"schema_version": "library-kb/1.0", "items": []}),
                   encoding="utf-8")
    rc = cli.main(["lineage", "--papers", str(bad), "--out", str(clean_env / "g.json")])
    assert rc == 2
    assert "not a parsed-paper/1.0" in capsys.readouterr().err


# -- lineage-render ----------------------------------------------------------

def _write_lineage_graph(path):
    path.write_text(json.dumps({
        "schema_version": "lineage-graph/1.0",
        "direction": {"query": "synthetic xq17 calibration", "scope_method": "m",
                      "created": "2026-06-22T00:00:00Z"},
        "nodes": [{"citekey": "a2008", "title": "A", "year": "2008"},
                  {"citekey": "b1996", "title": "B", "year": "1996"}],
        "edges": [{"from": "a2008", "to": "b1996", "relation": "extends"}],
    }), encoding="utf-8")
    return path


def test_lineage_render_to_vault_reviews(clean_env, capsys):
    graph = _write_lineage_graph(clean_env / "lineage.json")
    vault = clean_env / "vault"
    rc = cli.main(["lineage-render", "--graph", str(graph), "--vault", str(vault)])
    assert rc == 0
    # default output lands in the tool-owned Reviews/ dir, slug from the query
    out = vault / "Reviews" / "synthetic xq17 calibration.lineage.md"
    assert out.is_file()
    md = out.read_text(encoding="utf-8")
    assert "```mermaid" in md
    assert "-->|extends|" in md
    assert "lineage note ->" in capsys.readouterr().out


def test_lineage_render_explicit_out(clean_env, capsys):
    graph = _write_lineage_graph(clean_env / "lineage.json")
    out = clean_env / "g.lineage.md"
    rc = cli.main(["lineage-render", "--graph", str(graph), "--out", str(out)])
    assert rc == 0
    assert out.is_file()


def test_lineage_render_stamp_notes_needs_vault(clean_env, capsys):
    graph = _write_lineage_graph(clean_env / "lineage.json")
    rc = cli.main(["lineage-render", "--graph", str(graph),
                   "--out", str(clean_env / "g.md"), "--stamp-notes"])
    assert rc == 2
    assert "--stamp-notes needs --vault" in capsys.readouterr().err


def test_lineage_render_stamp_notes_opportunistic(clean_env, capsys):
    graph = _write_lineage_graph(clean_env / "lineage.json")
    vault = clean_env / "vault"
    (vault / "Literature").mkdir(parents=True)
    note = vault / "Literature" / "a2008.md"
    note.write_text("---\ncitekey: a2008\n---\n\nbody\n", encoding="utf-8")
    rc = cli.main(["lineage-render", "--graph", str(graph), "--vault", str(vault),
                   "--stamp-notes"])
    assert rc == 0
    assert "[[b1996]]" in note.read_text(encoding="utf-8")  # extends edge stamped
    # b1996's note is absent -> never created (lean-vault)
    assert not (vault / "Literature" / "b1996.md").exists()


def test_lineage_render_wrong_schema_exits_2(clean_env, capsys):
    bad = clean_env / "bad.json"
    bad.write_text(json.dumps({"schema_version": "review/1.0"}), encoding="utf-8")
    rc = cli.main(["lineage-render", "--graph", str(bad), "--out", str(clean_env / "g.md")])
    assert rc == 2
    assert "not a lineage-graph/1.0" in capsys.readouterr().err


# -- read-render -------------------------------------------------------------

def _write_reading_note(path, citekey="xq17SyntheticStudy002"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "reading-note/1.0",
        "id": citekey,
        "read_status": "In Progress",
        "created": "2026-06-22T10:30:00Z",
        "stages": {
            "glance": {"tldr": "t", "tags": ["xq17-synthetic"]},
            "close_read": {"question": "q?", "method": "m", "data": "d", "results": "r"},
        },
        "sources": {"parsed_file": "_parsed/x.grobid.json"},
    }), encoding="utf-8")
    return path


def _write_kb_with_citekey(clean_env, citekey="xq17SyntheticStudy002"):
    kb = clean_env / "library.json"
    kb.write_text(json.dumps({
        "schema_version": "library-kb/1.0",
        "items": [{"key": "K7M4QX2P", "citekey": citekey,
                   "title": "[SYNTHETIC] Robust XQ-17 calibration across operating ranges",
                   "authors": ["Researcher XQ-17-02"], "year": "2008", "folders": []}],
    }), encoding="utf-8")
    return kb


def test_read_render_to_vault_reading_notes(clean_env, capsys):
    note = _write_reading_note(clean_env / "xq17SyntheticStudy002.json")
    vault = clean_env / "vault"
    rc = cli.main(["read-render", str(note), "--vault", str(vault)])
    assert rc == 0
    # default output lands in the tool-owned reading-notes/ dir, named by citekey
    out = vault / "reading-notes" / "xq17SyntheticStudy002.md"
    assert out.is_file()
    md = out.read_text(encoding="utf-8")
    assert "## 速览 · Glance" in md
    assert "## 精读 · Close read" in md
    assert "[[xq17SyntheticStudy002]]" in md
    assert "reading note ->" in capsys.readouterr().out


def test_read_render_explicit_out(clean_env, capsys):
    note = _write_reading_note(clean_env / "n.json")
    out = clean_env / "browse.md"
    rc = cli.main(["read-render", str(note), "--out", str(out)])
    assert rc == 0
    assert out.is_file()


def test_read_render_default_alongside_json(clean_env, capsys):
    note = _write_reading_note(clean_env / "sub" / "xq17SyntheticStudy002.json")
    rc = cli.main(["read-render", str(note)])  # no --vault, no --out
    assert rc == 0
    # default lands beside the JSON, named by the note's id
    assert (clean_env / "sub" / "xq17SyntheticStudy002.md").is_file()


def test_read_render_kb_enrichment_path(clean_env, capsys):
    note = _write_reading_note(clean_env / "n.json")
    kb = _write_kb_with_citekey(clean_env)
    out = clean_env / "n.md"
    rc = cli.main(["read-render", str(note), "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    md = out.read_text(encoding="utf-8")
    assert 'title: "[SYNTHETIC] Robust XQ-17 calibration across operating ranges"' in md
    assert 'year: "2008"' in md
    assert "enriched from --kb" in capsys.readouterr().out


def test_read_render_kb_no_match_renders_without_enrichment(clean_env, capsys):
    note = _write_reading_note(clean_env / "n.json", citekey="unknown2099")
    kb = _write_kb_with_citekey(clean_env)  # only carries xq17SyntheticStudy002
    out = clean_env / "n.md"
    rc = cli.main(["read-render", str(note), "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    md = out.read_text(encoding="utf-8")
    assert "title:" not in md.split("---", 2)[1]   # no enrichment in frontmatter
    assert "no library-kb item matched" in capsys.readouterr().out


def test_read_render_missing_kb_exits_2(clean_env, capsys):
    note = _write_reading_note(clean_env / "n.json")
    rc = cli.main(["read-render", str(note), "--kb", str(clean_env / "nope.json"),
                   "--out", str(clean_env / "n.md")])
    assert rc == 2
    assert "KB not found" in capsys.readouterr().err


def test_read_render_wrong_schema_exits_2(clean_env, capsys):
    bad = clean_env / "bad.json"
    bad.write_text(json.dumps({"schema_version": "library-kb/1.0", "items": []}),
                   encoding="utf-8")
    rc = cli.main(["read-render", str(bad), "--out", str(clean_env / "n.md")])
    assert rc == 2
    assert "not a reading-note/1.0" in capsys.readouterr().err


# -- export ------------------------------------------------------------------

def test_export_happy_path(web_creds, monkeypatch, capsys):
    # stub the network read; cli should still write the KB JSON
    monkeypatch.setattr(export_mod, "build_kb", lambda client, storage: [
        {"key": "AAAAAAA1", "title": "A", "authors": [], "year": "2024",
         "doi": "", "folders": [], "aiTags": [], "tldr": "", "readStatus": "",
         "abstract": ""}])
    kb_out = web_creds / "kb.json"
    rc = cli.main(["export", "--kb", str(kb_out)])
    assert rc == 0
    assert kb_out.is_file()
    doc = json.loads(kb_out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "library-kb/1.1"
    assert "KB: 1 items" in capsys.readouterr().out


def test_export_unreachable_library_exits_2(web_creds, monkeypatch, capsys):
    # build_kb raising ZoteroError (can't reach the library) maps to exit 2
    def boom(client, storage):
        raise ZoteroError("local API unreachable")
    monkeypatch.setattr(export_mod, "build_kb", boom)
    rc = cli.main(["export", "--kb", str(web_creds / "kb.json")])
    assert rc == 2
    assert "error:" in capsys.readouterr().err
