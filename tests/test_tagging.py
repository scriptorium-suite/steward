# [SYNTHETIC] XQ-17 fixtures only; no value represents a real paper, author, DOI, or research record.
import pytest

from steward import apply as ap
from steward import tagging as tg
from steward.config import Profile


class TagFakeClient:
    """In-memory web-mode client for tagging.execute (GET reads + POST writes).

    `fail_keys` are reported as 412 by post_items; on the conflict re-fetch they
    are made to match their intended state so they HEAL (drop) rather than abort.
    """

    def __init__(self, keys, heal_keys=(), conflict_keys=()):
        self.items = {k: {"version": 1, "tags": [], "extra": ""} for k in keys}
        # heal_keys: first write 412s but the item then matches intended -> drop
        self.heal_keys = set(heal_keys)
        # conflict_keys: write 412s AND the item shows a foreign edit -> conflict
        self.conflict_keys = set(conflict_keys)
        self.batch_sizes = []          # one entry per post_items HTTP batch

    def request(self, method, path, body=None):
        assert method == "GET" and "itemKey=" in path
        keys = path.split("itemKey=")[1].split("&")[0].split("%2C")
        return 200, {}, [{"key": k, "version": self.items[k]["version"],
                          "data": {"tags": self.items[k]["tags"],
                                   "extra": self.items[k]["extra"]}}
                         for k in keys if k in self.items]

    def post_items(self, objects):
        # emulate the >50 batching the real client performs, with global rekeying
        merged = {"success": {}, "unchanged": {}, "failed": {}}
        for base in range(0, len(objects), 50):
            chunk = objects[base:base + 50]
            self.batch_sizes.append(len(chunk))
            for j, o in enumerate(chunk):
                gi, key = str(base + j), o["key"]
                if key in self.conflict_keys:
                    merged["failed"][gi] = {"code": 412}
                    # a foreign edit: differs from BOTH pre and intended
                    self.items[key]["tags"] = [{"tag": "ai:external", "type": 1}]
                    self.items[key]["version"] += 1
                elif key in self.heal_keys:
                    merged["failed"][gi] = {"code": 412}
                    # heal: the item already holds the intended state on re-fetch
                    self.items[key]["tags"] = o["tags"]
                    self.items[key]["extra"] = o["extra"]
                    self.heal_keys.discard(key)        # only the first write 412s
                else:
                    self.items[key]["tags"] = o["tags"]
                    self.items[key]["extra"] = o["extra"]
                    self.items[key]["version"] += 1
                    merged["success"][gi] = key
        return merged


def test_scaffold_skips_already_tagged(fake_zotero_db):
    # item 1 has ai:ml tag -> excluded when only_untagged; item 2 has ai:ml too
    doc = tg.scaffold(fake_zotero_db, ["ml", "geo"], only_untagged=True)
    keys = {it["key"] for it in doc["items"]}
    assert keys == set()        # both live papers already have ai: tags
    doc_all = tg.scaffold(fake_zotero_db, [], only_untagged=False)
    assert {it["key"] for it in doc_all["items"]} == {"AAAAAAA1", "AAAAAAA2"}


def test_validate():
    bad = {"schema_version": "tag-plan/1.0", "items": [
        {"key": "AAAAAAA1", "aiTags": [], "tldr": "", "readStatus": "x"},
        {"key": "AAAAAAA2", "aiTags": ["ai:x"], "tldr": "ok", "readStatus": "Read"},
    ]}
    errs = tg.validate(bad)
    assert any("aiTags must be" in e for e in errs)       # empty
    assert any("empty tldr" in e for e in errs)
    assert any("invalid readStatus" in e for e in errs)
    assert any("ai: prefix" in e for e in errs)           # 'ai:x' rejected

    good = {"schema_version": "tag-plan/1.0", "items": [
        {"key": "AAAAAAA1", "aiTags": ["ml", "geo"], "tldr": "nice", "readStatus": ""}]}
    assert tg.validate(good) == []


def test_rebuild_extra_single_status_line():
    extra = "titleTranslation: foo\nRead_Status: To Read\nRead_Status_Date: old"
    # status untouched (no override) -> keep existing single status line + new TLDR
    out = tg._rebuild_extra(extra, "my tldr", "", "NOW")
    assert out.count("Read_Status:") == 1
    assert "TLDR: my tldr" in out
    assert "titleTranslation: foo" in out
    # override status
    out2 = tg._rebuild_extra(extra, "t", "Read", "NOW")
    assert out2.count("Read_Status:") == 1
    assert "Read_Status: Read" in out2
    assert "Read_Status_Date: NOW" in out2


def test_rebuild_extra_collapses_multiline_tldr_and_dedups_status():
    # two pre-existing status lines (an already-INVALID item) must collapse to one
    extra = "Read_Status: Read\nRead_Status: To Read\nkeep me"
    out = tg._rebuild_extra(extra, "line one\nline two", "", "NOW")
    assert out.count("Read_Status:") == 1                  # invariant restored
    assert "TLDR: line one line two" in out                # newline collapsed
    assert "\nline two" not in out                         # no orphan line
    assert "keep me" in out


def test_validate_rejects_multiline_tldr():
    doc = {"schema_version": "tag-plan/1.0", "items": [
        {"key": "AAAAAAA1", "aiTags": ["ml"], "tldr": "a\nb", "readStatus": ""}]}
    assert any("single line" in e for e in tg.validate(doc))


def test_tag_idempotent_on_clean_extra():
    # repeated apply from a clean single-status extra must not accumulate
    extra = ""
    for _ in range(3):
        extra = tg._rebuild_extra(extra, "summary", "In Progress", "NOW")
    assert extra.count("TLDR:") == 1
    assert extra.count("Read_Status:") == 1


def test_plan_updates_strips_old_status_tags_and_prefixes():
    doc = {"items": [{"key": "AAAAAAA1", "aiTags": ["ml"], "tldr": "t", "readStatus": "Read"}]}
    server = {"AAAAAAA1": {"version": 5, "data": {
        "tags": [{"tag": "Read"}, {"tag": "/unread", "type": 1}, {"tag": "keepme"}],
        "extra": ""}}}
    ups = tg.plan_updates(doc, server)
    assert len(ups) == 1
    tags = {t["tag"] for t in ups[0]["tags"]}
    assert "ai:ml" in tags
    assert "keepme" in tags
    assert "Read" not in tags and "/unread" not in tags   # old status tags removed
    assert "Read_Status: Read" in ups[0]["extra"]
    assert ups[0]["version"] == 5


# -- T5.4 concurrency: tagging.execute >50-item batching ---------------------

@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    from steward import config as cfg
    monkeypatch.setenv(cfg.ENV_CONFIG_ROOT, str(tmp_path))
    return tmp_path


def _tag_plan(keys):
    return {"schema_version": "tag-plan/1.0", "items": [
        {"key": k, "aiTags": ["ml"], "tldr": "t", "readStatus": "Read"} for k in keys]}


def test_execute_batches_over_50_items(state_dir):
    # 120 items must be written in 50/50/20 batches (the API cap).
    keys = [f"K{i:07d}" for i in range(120)]
    client = TagFakeClient(keys)
    profile = Profile(library_id="1", api_key="k")
    jpath = tg.execute(_tag_plan(keys), client, profile, backup_check=False)
    assert client.batch_sizes == [50, 50, 20]
    # every item gained the ai:ml tag and a TLDR line
    for k in keys:
        assert any(t["tag"] == "ai:ml" for t in client.items[k]["tags"])
        assert "TLDR: t" in client.items[k]["extra"]
    assert jpath.is_file()


def test_execute_heals_412_buckets_without_aborting(state_dir):
    # a partial batch where two items 412 but heal on re-fetch: execute must NOT
    # raise (the healed buckets are dropped, not reported as conflicts).
    keys = [f"K{i:07d}" for i in range(60)]
    healing = {keys[10], keys[55]}     # one per batch (batch boundary at 50)
    client = TagFakeClient(keys, heal_keys=healing)
    profile = Profile(library_id="1", api_key="k")
    jpath = tg.execute(_tag_plan(keys), client, profile, backup_check=False)
    # the 412'd items still end up tagged (healed to the intended state)
    for k in healing:
        assert any(t["tag"] == "ai:ml" for t in client.items[k]["tags"])
    assert jpath.is_file()


def test_execute_reports_genuine_conflict(state_dir):
    # a 412 that does NOT heal (the item was genuinely edited elsewhere) must
    # raise TagError and leave the concurrent edit untouched.
    keys = [f"K{i:07d}" for i in range(3)]
    client = TagFakeClient(keys, conflict_keys={"K0000001"})
    profile = Profile(library_id="1", api_key="k")
    with pytest.raises(tg.TagError, match="edited concurrently"):
        tg.execute(_tag_plan(keys), client, profile, backup_check=False)
    # the external edit survives
    assert client.items["K0000001"]["tags"] == [{"tag": "ai:external", "type": 1}]
