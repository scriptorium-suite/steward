import datetime
import json

import pytest

from steward import apply as ap
from steward import config as cfg
from steward.config import Profile


def _write_backup(backup_dir, created):
    """Create a verified backup dir whose manifest carries `created`.

    `created` may be a real stamp string, a malformed string, or None (to omit
    the key) - exercising the timestamp-parse branches of _check_backup.
    """
    d = backup_dir / (created if isinstance(created, str) and created else "snap")
    d.mkdir(parents=True)
    manifest = {"verified": True, "files": 1, "integrity_check": "ok"}
    if created is not None:
        manifest["created"] = created
    (d / "backup-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


class FakeClient:
    """In-memory stand-in for ZoteroClient (web mode)."""

    def __init__(self):
        self.cols = {"A": "COLA0001"}          # path -> key
        self.items = {                          # key -> {version, collections}
            "AAAAAAA1": {"version": 10, "collections": ["COLA0001"]},
            "AAAAAAA2": {"version": 20, "collections": []},
        }
        self.col_counter = 0
        self.writes = []

    def collection_paths(self):
        return dict(self.cols)

    def collections(self):
        return [{"data": {"name": path.rsplit("/", 1)[-1]}} for path in self.cols]

    def get_versions(self):
        return {k: v["version"] for k, v in self.items.items()}

    def post_collections(self, body):
        out = {"success": {}, "failed": {}}
        for i, obj in enumerate(body):
            self.col_counter += 1
            key = f"NEWCOL{self.col_counter:02d}"
            parent = obj.get("parentCollection")
            parent_path = next((p for p, k in self.cols.items() if k == parent), None)
            path = f"{parent_path}/{obj['name']}" if parent_path else obj["name"]
            self.cols[path] = key
            out["success"][str(i)] = key
        return out

    def post_items(self, objects):
        out = {"success": {}, "unchanged": {}, "failed": {}}
        for i, o in enumerate(objects):
            it = self.items[o["key"]]
            if o["version"] != it["version"]:
                out["failed"][str(i)] = {"code": 412}
                continue
            it["collections"] = o["collections"]
            it["version"] += 1
            self.writes.append(o["key"])
            out["success"][str(i)] = o["key"]
        return out

    def request(self, method, path, body=None):
        assert method == "GET" and "itemKey=" in path
        keys = path.split("itemKey=")[1].split("&")[0].split("%2C")
        return 200, {}, [{"key": k, "version": self.items[k]["version"],
                          "data": {"collections": self.items[k]["collections"]}}
                         for k in keys if k in self.items]


@pytest.fixture
def doc():
    return {
        "schema_version": "proposal/1.0",
        "target_tree": ["A", "A/B", "C"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": ["A/B"]},
            {"key": "AAAAAAA2", "targets": ["C", "A"]},
        ],
    }


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    return tmp_path


def test_plan_lists_missing_collections(doc, state_dir):
    client = FakeClient()
    pl = ap.plan(doc, client)
    assert pl["collections_to_create"] == ["A/B", "C"]
    assert pl["keys_not_on_server"] == []


def test_execute_writes_journal_then_items(doc, state_dir):
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    jpath = ap.execute(doc, client, profile, backup_check=False)

    journal = json.loads(jpath.read_text(encoding="utf-8"))
    assert journal["pre_state"]["AAAAAAA1"]["collections"] == ["COLA0001"]
    assert set(journal["created_collections"]) == {"A/B", "C"}

    assert client.items["AAAAAAA1"]["collections"] == [client.cols["A/B"]]
    assert client.items["AAAAAAA2"]["collections"] == [client.cols["C"], client.cols["A"]]


def test_execute_requires_backup(doc, state_dir):
    profile = Profile(library_id="1", api_key="k", backup_dir=str(state_dir / "none"))
    with pytest.raises(ap.ApplyError, match="backup"):
        ap.execute(doc, FakeClient(), profile, backup_check=True)


def test_backup_gate_passes_with_fresh_backup(doc, state_dir, capsys):
    bdir = state_dir / "bak"
    fresh = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    _write_backup(bdir, fresh)
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    # gate must pass and the run completes (items written)
    ap.execute(doc, FakeClient(), profile, backup_check=True)
    out = capsys.readouterr().out
    assert "backup gate ok" in out
    assert "0h old" in out


def test_backup_gate_rejects_stale_backup(doc, state_dir):
    # a verified backup older than 24h must FAIL the gate (was untested).
    bdir = state_dir / "bak"
    stale = (datetime.datetime.now() - datetime.timedelta(hours=30)) \
        .strftime("%Y-%m-%d_%H%M%S")
    _write_backup(bdir, stale)
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    with pytest.raises(ap.ApplyError, match=r"30h old"):
        ap.execute(doc, FakeClient(), profile, backup_check=True)


def test_backup_gate_fails_closed_on_unparseable_timestamp(doc, state_dir):
    # T5.1: a verified backup whose `created` is garbage must RAISE, not skip.
    bdir = state_dir / "bak"
    _write_backup(bdir, "not-a-timestamp")
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    client = FakeClient()
    with pytest.raises(ap.ApplyError, match="unreadable timestamp"):
        ap.execute(doc, client, profile, backup_check=True)
    # fail-closed: nothing was written
    assert client.writes == []


def test_backup_gate_fails_closed_on_missing_timestamp(doc, state_dir):
    # T5.1: a verified backup with NO `created` key must also fail closed.
    bdir = state_dir / "bak"
    _write_backup(bdir, None)
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    client = FakeClient()
    with pytest.raises(ap.ApplyError, match="unreadable timestamp"):
        ap.execute(doc, client, profile, backup_check=True)
    assert client.writes == []


def test_backup_gate_bypassed_by_no_backup_check(doc, state_dir):
    # --no-backup-check (backup_check=False) is the only bypass; even a garbage
    # backup is ignored and the run proceeds.
    bdir = state_dir / "bak"
    _write_backup(bdir, "not-a-timestamp")
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    client = FakeClient()
    ap.execute(doc, client, profile, backup_check=False)
    assert set(client.writes) == {"AAAAAAA1", "AAAAAAA2"}


def test_tag_shares_failclosed_backup_gate(state_dir):
    # apply + tag share _check_backup; the tag path must fail closed too.
    from steward import tagging as tg
    bdir = state_dir / "bak"
    _write_backup(bdir, "not-a-timestamp")
    profile = Profile(library_id="1", api_key="k", backup_dir=str(bdir))
    plan = {"schema_version": "tag-plan/1.0", "items": [
        {"key": "AAAAAAA1", "aiTags": ["ml"], "tldr": "t", "readStatus": ""}]}
    with pytest.raises(ap.ApplyError, match="unreadable timestamp"):
        tg.execute(plan, FakeClient(), profile, backup_check=True)


def test_rollback_restores_collections(doc, state_dir):
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    jpath = ap.execute(doc, client, profile, backup_check=False)
    assert client.items["AAAAAAA1"]["collections"] != ["COLA0001"]

    ap.rollback(jpath, client, profile, run=False)            # dry-run: no change
    assert client.items["AAAAAAA1"]["collections"] != ["COLA0001"]
    ap.rollback(jpath, client, profile, run=True)
    assert client.items["AAAAAAA1"]["collections"] == ["COLA0001"]
    assert client.items["AAAAAAA2"]["collections"] == []


def test_rollback_refuses_wrong_library(doc, state_dir):
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    jpath = ap.execute(doc, client, profile, backup_check=False)
    other = Profile(library_id="999", api_key="k")
    with pytest.raises(ap.ApplyError, match="refusing to cross-apply"):
        ap.rollback(jpath, client, other, run=True)


def test_412_real_conflict_aborts_without_clobber(doc, state_dir):
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    # simulate a concurrent external edit: bump version AND change collections
    # after pre-state would be captured. We hook post_items' first call.
    orig_fetch = ap._fetch_items
    state = {"n": 0}

    def racy_fetch(c, keys, fields=("collections",)):
        res = orig_fetch(c, keys, fields=fields)
        if state["n"] == 0:  # the pre-state read returns the snapshot...
            state["n"] = 1
            # ...then an external editor changes item 1 before our write
            c.items["AAAAAAA1"]["collections"] = ["EXTERNAL9"]
            c.items["AAAAAAA1"]["version"] = 99
        return res

    ap._fetch_items = racy_fetch
    try:
        with pytest.raises(ap.ApplyError, match="edited concurrently"):
            ap.execute(doc, client, profile, backup_check=False)
    finally:
        ap._fetch_items = orig_fetch
    # the external edit must survive
    assert client.items["AAAAAAA1"]["collections"] == ["EXTERNAL9"]


def test_untouched_inbox_scaffold_refused(state_dir):
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    scaffold = {
        "schema_version": "proposal/1.0",
        "target_tree": ["00_Inbox", "A"],
        "proposals": [
            {"key": "AAAAAAA1", "targets": ["00_Inbox"],
             "note": "(prefilled inbox - replace with a real target)"},
            {"key": "AAAAAAA2", "targets": ["00_Inbox"],
             "note": "(prefilled inbox - replace with a real target)"},
        ],
    }
    with pytest.raises(ap.ApplyError, match="untouched scaffold"):
        ap.execute(scaffold, client, profile, backup_check=False)


# -- T5.4 concurrency edge cases ---------------------------------------------

def test_resolve_conflicts_drops_healed_writes():
    # healed-drop: a 412 whose item ALREADY holds the intended state (a transport
    # double-POST) is silently dropped - neither retried nor reported.
    client = FakeClient()
    client.items["AAAAAAA1"]["collections"] = ["WANTED01"]   # already applied
    client.items["AAAAAAA1"]["version"] = 11
    intended = {"AAAAAAA1": {"collections": ["WANTED01"]}}
    pre = {"AAAAAAA1": {"version": 10, "collections": ["COLA0001"]}}
    retry, conflicts, gone = ap.resolve_conflicts(
        client, ["AAAAAAA1"], intended, pre, ("collections",))
    assert (retry, conflicts, gone) == ([], [], [])         # fully healed, dropped


def test_resolve_conflicts_partial_some_retry_some_conflict_some_gone():
    # one item unchanged externally (safe retry), one genuinely edited (conflict),
    # one deleted (gone) - the three buckets must separate cleanly.
    client = FakeClient()
    client.items = {
        "AAAAAAA1": {"version": 12, "collections": ["COLA0001"]},  # == pre -> retry
        "AAAAAAA2": {"version": 30, "collections": ["EXTERN99"]},  # != pre/want -> conflict
    }
    intended = {k: {"collections": ["WANTED01"]} for k in ("AAAAAAA1", "AAAAAAA2", "GONEITEM")}
    pre = {
        "AAAAAAA1": {"version": 10, "collections": ["COLA0001"]},
        "AAAAAAA2": {"version": 20, "collections": ["ORIGIN00"]},
        "GONEITEM": {"version": 5, "collections": []},
    }
    retry, conflicts, gone = ap.resolve_conflicts(
        client, ["AAAAAAA1", "AAAAAAA2", "GONEITEM"], intended, pre, ("collections",))
    assert [u["key"] for u in retry] == ["AAAAAAA1"]
    assert retry[0]["version"] == 12 and retry[0]["collections"] == ["WANTED01"]
    assert conflicts == ["AAAAAAA2"]
    assert gone == ["GONEITEM"]


def test_execute_partial_batch_412_then_successful_retry(doc, state_dir):
    # a partial batch: AAAAAAA1 writes fine; AAAAAAA2's version moves out from
    # under us (unchanged content) so the first write 412s, then the version-fresh
    # retry succeeds. The run completes without raising.
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    orig_post = client.post_items
    state = {"first": True}

    def flaky_post(objects):
        if state["first"]:
            state["first"] = False
            # bump AAAAAAA2's server version AFTER updates were built -> 412 for it
            client.items["AAAAAAA2"]["version"] += 1
        return orig_post(objects)

    client.post_items = flaky_post
    jpath = ap.execute(doc, client, profile, backup_check=False)
    # both items ended at their intended targets despite the mid-flight bump
    assert client.items["AAAAAAA1"]["collections"] == [client.cols["A/B"]]
    assert client.items["AAAAAAA2"]["collections"] == [client.cols["C"], client.cols["A"]]
    assert jpath.is_file()


def test_rollback_raises_on_412(doc, state_dir):
    # 412 during rollback (item changed since the rollback re-fetch) must surface
    # as a ZoteroError - the user is told to rerun or restore the full backup.
    client = FakeClient()
    profile = Profile(library_id="1", api_key="k")
    jpath = ap.execute(doc, client, profile, backup_check=False)

    orig_post = client.post_items

    def stale_post(objects):
        # invalidate every version right before the rollback write -> all 412
        for o in objects:
            client.items[o["key"]]["version"] += 1
        return orig_post(objects)

    client.post_items = stale_post
    with pytest.raises(ap.ZoteroError, match="rollback failed"):
        ap.rollback(jpath, client, profile, run=True)
