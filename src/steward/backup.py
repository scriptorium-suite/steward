"""Full backup of the Zotero data directory, with verification and a manifest.

Procedure (per the official guidance: copy the WHOLE data directory with
Zotero closed):
  1. preflight: data dir sanity, journal/WAL residue check (Zotero running?),
     backup_dir must lie outside data_dir
  2. copytree to <backup_dir>/<stamp>.partial/ (symlinks preserved as links)
  3. verify: file count + total bytes match, PRAGMA integrity_check on the copy
  4. only then: write backup-manifest.json and rename to the final name —
     a directory without the .partial suffix and with a manifest IS verified
"""
from __future__ import annotations

import datetime
import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import quote

from .config import Profile


class BackupError(RuntimeError):
    pass


def _tree_stats(root: Path) -> tuple[int, int]:
    count = total = 0
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            count += 1
            total += p.stat().st_size
    return count, total


def preflight(data_dir: Path, backup_root: Path, force: bool = False) -> list[str]:
    warnings = []
    if not (data_dir / "zotero.sqlite").is_file():
        raise BackupError(f"{data_dir} does not look like a Zotero data directory "
                          "(no zotero.sqlite)")
    try:
        inside = backup_root.resolve().is_relative_to(data_dir.resolve())
    except OSError:
        inside = False
    if inside:
        raise BackupError("backup_dir must be OUTSIDE the Zotero data directory "
                          f"({backup_root} is inside {data_dir})")
    for residue in ("zotero.sqlite-journal", "zotero.sqlite-wal"):
        if (data_dir / residue).exists():
            msg = (f"{residue} present - Zotero appears to be RUNNING or was not "
                   "closed cleanly. Close Zotero first.")
            if force:
                warnings.append(f"WARNING (forced): {msg}")
            else:
                raise BackupError(msg)
    return warnings


def _sqlite_ro_uri(path: Path) -> str:
    # percent-escape so '#', '?', '%' in paths cannot truncate the URI
    return f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"


def integrity_check(sqlite_path: Path) -> str:
    con = sqlite3.connect(_sqlite_ro_uri(sqlite_path), uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def run_backup(profile: Profile, force: bool = False, tag: str = "") -> Path:
    data_dir = Path(profile.data_dir)
    if not profile.backup_dir:
        raise BackupError("backup_dir is not configured (run `steward setup`)")
    backup_root = Path(profile.backup_dir)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    final = backup_root / (f"{stamp}_{tag}" if tag else stamp)
    partial = final.with_name(final.name + ".partial")
    if final.exists() or partial.exists():
        raise BackupError(f"destination already exists: {final}")

    warnings = preflight(data_dir, backup_root, force=force)
    for w in warnings:
        print(w)

    print(f"backing up {data_dir} -> {final} ...")
    try:
        shutil.copytree(data_dir, partial, symlinks=True)

        src_count, src_bytes = _tree_stats(data_dir)
        dst_count, dst_bytes = _tree_stats(partial)
        ok_bytes = (src_count, src_bytes) == (dst_count, dst_bytes)
        integrity = integrity_check(partial / "zotero.sqlite")
        if not ok_bytes or integrity != "ok":
            raise BackupError(
                f"verification FAILED (bytes "
                f"{'match' if ok_bytes else f'src={src_count}/{src_bytes} dst={dst_count}/{dst_bytes}'}, "
                f"integrity={integrity}) - partial copy removed, do not trust it")
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    manifest = {
        "created": stamp,
        "source": str(data_dir),
        "files": dst_count,
        "bytes": dst_bytes,
        "verified": True,
        "integrity_check": integrity,
        "warnings": warnings,
        "restore": ("Close Zotero. Move the broken data dir aside, copy this "
                    "directory back to the original location, start Zotero, "
                    "verify item counts. Keep auto-sync OFF until verified."),
    }
    (partial / "backup-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.rename(final)

    print(f"files: {dst_count}, bytes: {dst_bytes}, integrity_check: {integrity}")
    print(f"BACKUP OK -> {final}")
    return final


def latest_backup(profile: Profile) -> dict | None:
    root = Path(profile.backup_dir) if profile.backup_dir else None
    if not root or not root.is_dir():
        return None
    for d in sorted(root.iterdir(), reverse=True):
        if d.name.endswith(".partial"):
            continue
        mf = d / "backup-manifest.json"
        if mf.is_file():
            data = json.loads(mf.read_text(encoding="utf-8"))
            if data.get("verified"):
                data["path"] = str(d)
                return data
    return None
