"""Refresh the portfolio dashboard (总纲) static snapshot from project notes.

Scans the vault's `Projects/*.md` notes whose frontmatter conforms to
scriptorium-spec project/1.0, optionally joins each project's `linked_repo` git
state, and rewrites a marker-delimited *static snapshot* block inside
`Projects/_总纲.md`. Anything outside the markers — notably the Dataview/Bases
dynamic blocks the dashboard is built on — is left untouched.

The snapshot is deterministic (no wall-clock timestamp) so a re-run only
changes the file when the underlying projects or repos actually changed.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import yamlmini

BEGIN = "<!-- steward:portfolio:begin (static snapshot; refreshed by `steward portfolio`) -->"
END = "<!-- steward:portfolio:end -->"

_PRIORITY = {"high": 0, "medium": 1, "low": 2}
_STATUS = {"active": 0, "planned": 1, "paused": 2, "done": 3, "archived": 4}


class PortfolioError(RuntimeError):
    pass


def _oneline(text) -> str:
    return " ".join(str(text).split())


def _cell(text) -> str:
    return _oneline(text).replace("|", "\\|") or "—"


# -- reading -----------------------------------------------------------------

def load_projects(vault: Path) -> list[dict]:
    proj_dir = vault / "Projects"
    if not proj_dir.is_dir():
        raise PortfolioError(f"no Projects/ directory under {vault}")
    projects = []
    for path in sorted(proj_dir.glob("*.md")):
        if path.name.startswith("_"):           # _总纲.md, _使用说明.md are not project notes
            continue
        fm = yamlmini.parse_frontmatter(path.read_text(encoding="utf-8-sig"))
        if not str(fm.get("schema_version", "")).startswith("project/1"):
            continue
        fm["_file"] = path.stem
        projects.append(fm)
    return projects


def git_status(repo: str) -> dict | None:
    rp = Path(repo)
    if not rp.is_dir():
        return None
    try:
        log = subprocess.run(
            ["git", "-C", str(rp), "log", "-1", "--format=%h%x09%cd%x09%s", "--date=short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if log.returncode != 0 or not log.stdout.strip():
            return None
        branch = subprocess.run(
            ["git", "-C", str(rp), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        sha, date, subject = (log.stdout.strip().split("\t", 2) + ["", "", ""])[:3]
        return {"sha": sha, "date": date, "subject": subject,
                "branch": branch.stdout.strip() if branch.returncode == 0 else ""}
    except (OSError, subprocess.SubprocessError):
        return None


# -- rendering ---------------------------------------------------------------

def _sort_key(p: dict):
    return (_PRIORITY.get(str(p.get("priority", "")).lower(), 3),
            _STATUS.get(str(p.get("status", "")).lower(), 9),
            str(p.get("project_id", p.get("_file", ""))))


def _next_action(p: dict) -> str:
    na = p.get("next_actions")
    if isinstance(na, list):
        return "; ".join(_oneline(x) for x in na[:2])
    return _oneline(na) if na else ""


def render_snapshot(projects: list[dict], git: dict | None = None) -> str:
    """Build the marker-delimited static block. `git` maps project_id -> status."""
    git = git or {}
    cols = ["Project", "Status", "Stage", "Priority", "Next action", "Blocked", "Updated"]
    if git:
        cols.append("Repo")
    lines = [
        BEGIN,
        "",
        f"> 静态快照 · {len(projects)} 个项目 · 由 `steward portfolio` 刷新。"
        "标记区外的内容（含 Dataview 动态块）不受影响。",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for p in sorted(projects, key=_sort_key):
        pid = str(p.get("project_id", p.get("_file", "")))
        title = _oneline(p.get("title", pid)) or pid
        link = f"[[Projects/{p.get('_file', pid)}\\|{_cell(title)}]]"
        cells = [link, _cell(p.get("status", "")), _cell(p.get("stage", "")),
                 _cell(p.get("priority", "")), _cell(_next_action(p)),
                 _cell(p.get("blocked_by", "")), _cell(p.get("updated", ""))]
        if git:
            g = git.get(pid)
            cells.append(_cell(f"{g['branch']}@{g['sha']} ({g['date']})") if g else "—")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", END]
    return "\n".join(lines)


def apply_snapshot(existing: str | None, block: str, init: bool = False) -> str:
    """Splice `block` into `existing`, replacing a prior marked block if present.

    A new/empty file is created with the managed block. An existing file that
    already carries the markers has its block replaced in place. An existing,
    non-empty file WITHOUT markers is refused (it would silently grow a second,
    duplicate snapshot) unless `init=True`, which appends a fresh managed block.
    """
    if existing is None or not existing.strip():
        return f"# 项目总纲\n\n{block}\n"
    if BEGIN in existing and END in existing:
        pre = existing.split(BEGIN, 1)[0]
        post = existing.split(END, 1)[1]
        return pre + block + post
    if not init:
        raise PortfolioError(
            "the dashboard already exists but has no steward markers; refusing to "
            "append a second snapshot (it would duplicate an existing one). Either "
            "paste these two lines around the spot the snapshot should occupy "
            "(e.g. replacing a hand-written one), then re-run:\n"
            f"    {BEGIN}\n    {END}\n"
            "or pass --init to append a fresh managed block at the end.")
    sep = "" if existing.endswith("\n") else "\n"
    return f"{existing}{sep}\n{block}\n"


# -- planning ----------------------------------------------------------------

@dataclass
class Plan:
    out: Path
    new_content: str
    changed: bool
    n_projects: int


def plan(vault: Path, out: Path, with_git: bool = False, init: bool = False) -> Plan:
    projects = load_projects(vault)
    git = None
    if with_git:
        git = {}
        for p in projects:
            repo = p.get("linked_repo")
            if repo:
                st = git_status(str(repo))
                if st:
                    git[str(p.get("project_id", p.get("_file", "")))] = st
    block = render_snapshot(projects, git)
    existing = out.read_text(encoding="utf-8") if out.is_file() else None
    new_content = apply_snapshot(existing, block, init=init)
    return Plan(out, new_content, new_content != (existing or ""), len(projects))
