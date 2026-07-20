import json

from steward import cli
from steward import config as cfg


def test_portfolio_dry_run_then_run(tmp_path, capsys):
    pdir = tmp_path / "Projects"
    pdir.mkdir()
    (pdir / "p1.md").write_text(
        "---\nschema_version: project/1.0\nproject_id: p1\ntitle: One\n"
        "status: active\npriority: high\n---\n", encoding="utf-8")
    rc = cli.main(["portfolio", "--vault", str(tmp_path)])
    assert rc == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (pdir / "_总纲.md").exists()

    rc = cli.main(["portfolio", "--vault", str(tmp_path), "--run"])
    assert rc == 0
    assert (pdir / "_总纲.md").is_file()
    # a second --run is a no-op (snapshot already current)
    rc = cli.main(["portfolio", "--vault", str(tmp_path), "--run"])
    assert "up to date" in capsys.readouterr().out


def test_portfolio_refuses_marker_less_file(tmp_path, capsys):
    pdir = tmp_path / "Projects"
    pdir.mkdir()
    (pdir / "p1.md").write_text(
        "---\nschema_version: project/1.0\nproject_id: p1\ntitle: One\n"
        "status: active\n---\n", encoding="utf-8")
    (pdir / "_总纲.md").write_text("# 我的总纲\n### 静态快照\n| old |\n", encoding="utf-8")
    rc = cli.main(["portfolio", "--vault", str(tmp_path), "--run"])
    assert rc == 2
    assert "no steward markers" in capsys.readouterr().err
    # --init appends instead of refusing
    assert cli.main(["portfolio", "--vault", str(tmp_path), "--run", "--init"]) == 0


_KB = {
    "schema_version": "library-kb/1.0",
    "items": [
        {"key": "AAAAAAA1", "title": "[SYNTHETIC] XQ-17 foundations", "authors": ["Researcher-XQ17-A"],
         "year": "2003", "doi": "", "folders": ["01_ML/Group-A"], "aiTags": [],
         "tldr": "basics", "readStatus": "To Read", "abstract": "a"},
        {"key": "BBBBBBB2", "title": "[SYNTHETIC] XQ-17 classifier", "authors": ["Researcher-XQ17-B"],
         "year": "2023", "doi": "10.0000/scriptorium-demo-xq17-cli", "folders": ["01_ML"], "aiTags": ["ml"],
         "tldr": "rf", "readStatus": "Read", "abstract": "b"},
        {"key": "DDDDDDD4", "title": "MLX paper", "authors": ["Other"], "year": "2020",
         "doi": "", "folders": ["01_MLX"], "aiTags": [], "tldr": "", "readStatus": "",
         "abstract": ""},
    ],
}
_DRAFT = {
    "schema_version": "review-draft/1.0",
    "framing": "framing line",
    "intro": "intro prose",
    "sections": [{"title": "T1", "body": "body", "covered_keys": ["AAAAAAA1"]}],
    "gaps_future": "gaps prose",
    "priority_reads": ["BBBBBBB2"],
}


def test_review_scaffold_then_assemble(tmp_path, capsys):
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    inp = tmp_path / "review.input.json"

    rc = cli.main(["review", "scaffold", "--topic", "01_ML",
                   "--kb", str(kb), "--out", str(inp)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 papers" in out                          # 01_MLX excluded by the boundary
    assert inp.is_file()
    assert (tmp_path / "REVIEW-PROMPT.md").is_file()
    doc = json.loads(inp.read_text(encoding="utf-8"))
    assert [p["key"] for p in doc["papers"]] == ["AAAAAAA1", "BBBBBBB2"]

    # overwrite guard
    assert cli.main(["review", "scaffold", "--topic", "01_ML",
                     "--kb", str(kb), "--out", str(inp)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().out
    assert cli.main(["review", "scaffold", "--topic", "01_ML", "--kb", str(kb),
                     "--out", str(inp), "--force"]) == 0
    capsys.readouterr()

    draft = tmp_path / "review.draft.json"
    draft.write_text(json.dumps(_DRAFT, ensure_ascii=False), encoding="utf-8")
    note = tmp_path / "Reviews" / "xq17-synthetic.md"
    rc = cli.main(["review", "assemble", "--input", str(inp),
                   "--draft", str(draft), "--out", str(note)])
    assert rc == 0
    assert note.is_file()
    md = note.read_text(encoding="utf-8")
    assert "[!warning]" in md and "## 全部文献（2 篇" in md
    assert "[doi:10.0000/scriptorium-demo-xq17-cli]" in md  # DOI from the KB

    # assemble overwrite guard
    assert cli.main(["review", "assemble", "--input", str(inp), "--draft", str(draft),
                     "--out", str(note)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().out


def test_review_assemble_rejects_invalid_draft(tmp_path, capsys):
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    inp = tmp_path / "review.input.json"
    cli.main(["review", "scaffold", "--topic", "01_ML", "--kb", str(kb), "--out", str(inp)])
    capsys.readouterr()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "review-draft/1.0",
                               "sections": [{"title": "t", "body": "b",
                                             "covered_keys": ["ZZZZZZZ9"]}]},
                              ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["review", "assemble", "--input", str(inp), "--draft", str(bad),
                   "--out", str(tmp_path / "n.md")])
    assert rc == 2
    assert "invalid review draft" in capsys.readouterr().err


def test_review_scaffold_missing_kb(tmp_path, capsys):
    rc = cli.main(["review", "scaffold", "--topic", "x",
                   "--kb", str(tmp_path / "nope.json"), "--out", str(tmp_path / "o.json")])
    assert rc == 2
    assert "KB not found" in capsys.readouterr().out


# -- T2.4: empty-week no-op + dated --out default (sunk from lit-run.ps1) ------

def test_review_scaffold_zero_papers_is_noop(tmp_path, capsys):
    # a selection that matches nothing: early-return WITHOUT writing the file, so
    # a caller (lit-run.ps1 / cron) can no-op. Exit 0, clear "nothing to review".
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "review.input.json"
    rc = cli.main(["review", "scaffold", "--topic", "99_None",
                   "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    assert "nothing to review" in capsys.readouterr().out
    assert not out.exists()                       # no review.input.json written
    assert not out.with_name("REVIEW-PROMPT.md").exists()  # nor the prompt


def test_review_scaffold_nonzero_still_scaffolds(tmp_path, capsys):
    # the non-empty path is unchanged: file + prompt are written, exit 0.
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "review.input.json"
    rc = cli.main(["review", "scaffold", "--topic", "01_ML",
                   "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    assert "2 papers" in capsys.readouterr().out
    assert out.is_file()
    assert out.with_name("REVIEW-PROMPT.md").is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [p["key"] for p in doc["papers"]] == ["AAAAAAA1", "BBBBBBB2"]


def test_review_scaffold_dated_out_default(tmp_path, capsys, monkeypatch):
    # with no --out, the output is a date-stamped review.input-<date>.json in CWD
    # (mirrors lit-run.ps1's <name>-<date>), so repeated runs don't clobber.
    from steward import review as rv
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)        # default path is relative to CWD
    rc = cli.main(["review", "scaffold", "--topic", "01_ML", "--kb", str(kb)])
    assert rc == 0
    expected = rv.default_scaffold_out()
    assert expected.name.startswith("review.input-") and expected.suffix == ".json"
    assert (tmp_path / expected.name).is_file()
    assert expected.name in capsys.readouterr().out


# -- T2.1: --since must be a real ISO date -----------------------------------

def test_review_scaffold_rejects_bad_since(tmp_path, capsys):
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    # a slash-separated date silently floored to 0 results before; now exit 2.
    rc = cli.main(["review", "scaffold", "--since", "2026/06/15",
                   "--kb", str(kb), "--out", str(tmp_path / "o.json")])
    assert rc == 2
    assert "--since must be an ISO date" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()        # nothing was written


def test_review_scaffold_accepts_good_since(tmp_path, capsys):
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(_KB, ensure_ascii=False), encoding="utf-8")
    # a valid ISO floor passes the date-format guard (exit 0, not a parse error).
    # KB items have no dateAdded -> 0 match -> the new no-op: nothing written.
    rc = cli.main(["review", "scaffold", "--since", "2026-06-15",
                   "--kb", str(kb), "--out", str(tmp_path / "o.json")])
    assert rc == 0
    assert "nothing to review" in capsys.readouterr().out
    assert not (tmp_path / "o.json").exists()       # 0 papers -> no file written


# -- T2.2: --since-days floors against UTC today -----------------------------

def _freeze_utc(monkeypatch, instant):
    """Pin cli.datetime.now(tz) to a fixed UTC instant for --since-days."""
    import datetime as _dt

    class _Frozen(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(cli, "datetime", _Frozen)


def test_review_since_days_uses_utc_today(tmp_path, monkeypatch):
    import datetime as _dt
    # one recent item so the selection is non-empty and a file is written
    kb_doc = {"schema_version": "library-kb/1.0", "items": [
        {"key": "RECENT01", "title": "Recent", "authors": ["X"], "year": "2026",
         "doi": "", "folders": ["01_ML"], "aiTags": [], "tldr": "",
         "readStatus": "To Read", "abstract": "", "dateAdded": "2026-06-20T00:00:00Z"},
    ]}
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(kb_doc, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "o.json"
    # Freeze "now" to 2026-06-21T01:00 UTC. --since-days 6 -> floor 2026-06-15.
    _freeze_utc(monkeypatch, _dt.datetime(2026, 6, 21, 1, 0, tzinfo=_dt.timezone.utc))
    rc = cli.main(["review", "scaffold", "--since-days", "6",
                   "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["selection"]["since"] == "2026-06-15"


def test_review_since_days_boundary_inclusive(tmp_path, monkeypatch):
    # an item added exactly on the computed UTC floor is kept (>= boundary).
    import datetime as _dt
    kb_doc = {"schema_version": "library-kb/1.0", "items": [
        {"key": "ONFLOOR1", "title": "Added on the floor", "authors": ["X"],
         "year": "2026", "doi": "", "folders": ["01_ML"], "aiTags": [],
         "tldr": "", "readStatus": "To Read", "abstract": "",
         "dateAdded": "2026-06-15T00:00:00Z"},
        {"key": "TOOOLD11", "title": "Day before the floor", "authors": ["Y"],
         "year": "2026", "doi": "", "folders": ["01_ML"], "aiTags": [],
         "tldr": "", "readStatus": "To Read", "abstract": "",
         "dateAdded": "2026-06-14T23:59:59Z"},
    ]}
    kb = tmp_path / "library.json"
    kb.write_text(json.dumps(kb_doc, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "o.json"
    _freeze_utc(monkeypatch, _dt.datetime(2026, 6, 21, 12, 0, tzinfo=_dt.timezone.utc))
    rc = cli.main(["review", "scaffold", "--since-days", "6",
                   "--kb", str(kb), "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert [p["key"] for p in doc["papers"]] == ["ONFLOOR1"]   # floor is inclusive


def test_status_runs_without_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    for var in (cfg.ENV_API_KEY, cfg.ENV_LIBRARY_ID, cfg.ENV_LIBRARY_TYPE, cfg.ENV_LOCAL):
        monkeypatch.delenv(var, raising=False)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "steward" in out
    assert "library-kb/1.0" in out
    assert "library-kb/1.1" in out
    assert "none verified" in out


def test_status_never_prints_api_key_characters(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    monkeypatch.setenv(cfg.ENV_API_KEY, "SECRET-SENTINEL-KEY")
    monkeypatch.setenv(cfg.ENV_LIBRARY_ID, "123")
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "api key:    set" in out
    assert "SECRET" not in out
    assert "SENTINEL" not in out


def test_audit_via_cli(fake_zotero_db, capsys):
    assert cli.main(["audit", "--db", str(fake_zotero_db)]) == 0
    assert "Top-level items: 2" in capsys.readouterr().out


def test_audit_missing_db(tmp_path, capsys):
    assert cli.main(["audit", "--db", str(tmp_path / "nope.sqlite")]) == 2


def test_invalid_profile_name_is_friendly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda *_: "")
    rc = cli.main(["setup", "--profile", "my lab"])
    assert rc == 2
    assert "invalid profile name" in capsys.readouterr().err


def test_corrupt_config_is_friendly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    cfg.tool_dir().mkdir(parents=True)
    cfg.config_path().write_text("not [valid toml", encoding="utf-8")
    rc = cli.main(["status"])
    assert rc == 2
    assert "not valid TOML" in capsys.readouterr().err
