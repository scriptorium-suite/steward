import pytest

from steward import portfolio as pf


# Project records in this file are synthetic XQ-17 fixtures.


def _project(pid, **fields):
    lines = ["---", "schema_version: project/1.0", f"project_id: {pid}"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", "running log"]
    return "\n".join(lines) + "\n"


@pytest.fixture
def vault(tmp_path):
    pdir = tmp_path / "Projects"
    pdir.mkdir()
    (pdir / "xq17-calibration.md").write_text(_project(
        "xq17-calibration", title="[SYNTHETIC] XQ-17 校准基准", status="active",
        stage="验证", priority="high",
        next_actions="[复核合成结果, 完成示例消融]", updated="2026-06-11"),
        encoding="utf-8")
    (pdir / "xq17-followup.md").write_text(_project(
        "xq17-followup", title="[SYNTHETIC] XQ-17 后续实验", status="paused", priority="medium",
        updated="2026-05-01"), encoding="utf-8")
    (pdir / "_使用说明.md").write_text("# how to maintain\n", encoding="utf-8")
    (pdir / "notes.md").write_text("# not a project note, no frontmatter\n", encoding="utf-8")
    return tmp_path


def test_load_projects_filters(vault):
    projects = pf.load_projects(vault)
    ids = [p["project_id"] for p in projects]
    assert "xq17-calibration" in ids and "xq17-followup" in ids
    assert len(projects) == 2                    # _-prefixed and frontmatter-less files skipped


def test_render_sorts_by_priority_and_escapes(vault):
    block = pf.render_snapshot(pf.load_projects(vault))
    assert pf.BEGIN in block and pf.END in block
    # high priority sorts above medium
    assert block.index("xq17-calibration") < block.index("xq17-followup")
    # pipe inside the wikilink alias is escaped so the markdown table stays intact
    assert "[[Projects/xq17-calibration\\|[SYNTHETIC] XQ-17 校准基准]]" in block
    assert "复核合成结果; 完成示例消融" in block


def test_plan_creates_then_idempotent(vault):
    out = vault / "Projects" / "_总纲.md"
    p1 = pf.plan(vault, out)
    assert p1.changed and p1.n_projects == 2
    out.write_text(p1.new_content, encoding="utf-8")
    p2 = pf.plan(vault, out)
    assert not p2.changed                         # nothing changed on a re-run


def test_refresh_preserves_dataview_outside_markers(vault):
    out = vault / "Projects" / "_总纲.md"
    out.write_text(pf.plan(vault, out).new_content, encoding="utf-8")
    dataview = "\n## 动态\n```dataview\nTABLE status FROM \"Projects\"\n```\n"
    out.write_text(out.read_text(encoding="utf-8") + dataview, encoding="utf-8")

    p = pf.plan(vault, out)
    assert not p.changed                          # snapshot data unchanged
    assert "```dataview" in p.new_content         # user's dynamic block survives

    # a project edit re-renders the marked block but keeps the dataview block
    (vault / "Projects" / "xq17-followup.md").write_text(
        _project("xq17-followup", title="[SYNTHETIC] XQ-17 后续实验", status="active",
                 priority="medium", updated="2026-06-17"), encoding="utf-8")
    p2 = pf.plan(vault, out)
    assert p2.changed and "```dataview" in p2.new_content


def test_marker_less_file_refused_then_init_appends(vault):
    out = vault / "Projects" / "_总纲.md"
    # a hand-written snapshot WITHOUT markers must not be silently duplicated
    out.write_text("# 我的总纲\n### 静态快照\n| old | table |\n\n```dataview\nLIST\n```\n",
                   encoding="utf-8")
    with pytest.raises(pf.PortfolioError, match="no steward markers"):
        pf.plan(vault, out)
    # --init appends a fresh managed block, preserving the original content
    new = pf.plan(vault, out, init=True).new_content
    assert "### 静态快照" in new and "```dataview" in new       # original preserved
    assert pf.BEGIN in new and pf.END in new                   # managed block appended


def test_migrate_by_pasting_markers(vault):
    out = vault / "Projects" / "_总纲.md"
    # the recommended migration: drop the two marker lines where the old table was
    out.write_text(f"# 我的总纲\n{pf.BEGIN}\n(old table here)\n{pf.END}\n\n```dataview\nLIST\n```\n",
                   encoding="utf-8")
    new = pf.plan(vault, out).new_content       # no --init needed once markers exist
    assert new.count(pf.BEGIN) == 1 and "(old table here)" not in new   # replaced in place
    assert "```dataview" in new                                          # dynamic block kept


def test_missing_projects_dir_raises(tmp_path):
    with pytest.raises(pf.PortfolioError, match="no Projects/"):
        pf.load_projects(tmp_path)
