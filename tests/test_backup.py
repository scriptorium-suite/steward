import sqlite3

import pytest

from steward.backup import BackupError, run_backup
from steward.config import Profile


def make_data_dir(tmp_path):
    data = tmp_path / "zdata"
    (data / "storage" / "ABCD1234").mkdir(parents=True)
    (data / "storage" / "ABCD1234" / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    con = sqlite3.connect(data / "zotero.sqlite")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    return data


def test_backup_verifies_and_writes_manifest(tmp_path):
    data = make_data_dir(tmp_path)
    prof = Profile(data_dir=str(data), backup_dir=str(tmp_path / "bak"))
    dest = run_backup(prof)
    assert (dest / "zotero.sqlite").is_file()
    assert (dest / "storage" / "ABCD1234" / "paper.pdf").is_file()
    assert (dest / "backup-manifest.json").is_file()


def test_backup_refuses_journal_residue(tmp_path):
    data = make_data_dir(tmp_path)
    (data / "zotero.sqlite-journal").write_bytes(b"")
    prof = Profile(data_dir=str(data), backup_dir=str(tmp_path / "bak"))
    with pytest.raises(BackupError, match="RUNNING"):
        run_backup(prof)
    # --force proceeds
    dest = run_backup(prof, force=True)
    assert dest.exists()


def test_backup_rejects_non_zotero_dir(tmp_path):
    prof = Profile(data_dir=str(tmp_path), backup_dir=str(tmp_path / "bak"))
    with pytest.raises(BackupError, match="zotero.sqlite"):
        run_backup(prof)
