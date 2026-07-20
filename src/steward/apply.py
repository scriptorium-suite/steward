"""Apply a reviewed proposal: create collections, reassign items, journal everything.

Safety model (the part chat-based tools cannot offer):
- dry-run by default; `--run` is explicit,
- refuses to run without a RECENT verified backup (override: --no-backup-check),
- the journal (pre-state of every touched item, captured from the server
  immediately before writing) is written to disk BEFORE the first write -
  `steward rollback` replays it,
- writes only the `collections` field, with per-object version concurrency,
- a 412 (version conflict) means the item changed since we snapshotted it:
  if it already matches our intended state we heal silently, otherwise we ABORT
  that item and report it - we never overwrite a concurrent edit.
- rollback is itself journaled and library-matched.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from . import __version__
from .backup import latest_backup
from .config import Profile, tool_dir
from .zotero_api import ZoteroClient, ZoteroError

BACKUP_MAX_AGE_HOURS = 24


class ApplyError(RuntimeError):
    pass


def journal_dir() -> Path:
    return tool_dir() / "state" / "journal"


def _collect_targets(doc: dict) -> list[str]:
    paths = set(doc.get("target_tree") or [])
    for p in doc["proposals"]:
        paths.update(p["targets"])
    for path in list(paths):
        parts = path.split("/")
        for i in range(1, len(parts)):
            paths.add("/".join(parts[:i]))
    return sorted(paths)


def _fetch_items(client: ZoteroClient, keys: list[str],
                 fields: tuple[str, ...] = ("collections",)) -> dict:
    """{key: {version, <field>...}} for keys that currently exist on the server."""
    out = {}
    for i in range(0, len(keys), 50):
        chunk = keys[i:i + 50]
        _, _, items = client.request(
            "GET", f"/items?itemKey={'%2C'.join(chunk)}&format=json&limit=50")
        for it in items:
            entry = {"version": it["version"]}
            for f in fields:
                entry[f] = it["data"].get(f, [] if f != "extra" else "")
            out[it["key"]] = entry
    return out


def resolve_conflicts(client: ZoteroClient, failed_keys: list[str], intended: dict,
                      pre: dict, fields: tuple[str, ...]) -> tuple[list[dict], list[str], list[str]]:
    """Classify failed writes without clobbering concurrent edits.

    Returns (retry_updates, conflicts, gone). For each failed key, re-fetch:
    - current == intended  -> healed (transport double-POST); drop
    - current == pre        -> unchanged externally; safe to retry with fresh version
    - else                  -> genuine concurrent edit; report as conflict, do NOT write
    """
    fresh = _fetch_items(client, failed_keys, fields=fields)
    retry, conflicts, gone = [], [], []
    for key in failed_keys:
        if key not in fresh:
            gone.append(key)
            continue
        cur = {f: fresh[key][f] for f in fields}
        want = {f: intended[key][f] for f in fields}
        was = {f: pre[key][f] for f in fields}
        if _eq(cur, want):
            continue                                  # already applied
        elif _eq(cur, was):
            retry.append({"key": key, "version": fresh[key]["version"], **want})
        else:
            conflicts.append(key)
    return retry, conflicts, gone


def _eq(a: dict, b: dict) -> bool:
    def norm(v):
        if isinstance(v, list):
            return sorted(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in v)
        return v
    return all(norm(a[k]) == norm(b[k]) for k in a)


def _check_backup(profile: Profile) -> None:
    last = latest_backup(profile)
    if not last:
        raise ApplyError("no verified backup found - run `steward backup` first "
                         "(or pass --no-backup-check at your own risk)")
    try:
        when = datetime.datetime.strptime(last["created"], "%Y-%m-%d_%H%M%S")
        age_h = (datetime.datetime.now() - when).total_seconds() / 3600
    except (KeyError, ValueError) as e:
        # fail-closed: an unparseable/missing timestamp means we CANNOT prove the
        # backup is recent, so refuse rather than silently skip the 24h gate.
        raise ApplyError(
            f"verified backup has an unreadable timestamp ({last.get('created')!r} "
            f"in {last.get('path')}): {e}. Cannot confirm it is recent - run a "
            "fresh `steward backup` or pass --no-backup-check at your own risk.") from e
    if age_h > BACKUP_MAX_AGE_HOURS:
        raise ApplyError(
            f"newest verified backup is {age_h:.0f}h old "
            f"({last['path']}); run a fresh `steward backup` or pass "
            "--no-backup-check. Note: backups cover the LOCAL data dir, while "
            "apply writes the WEB library - sync before backing up.")
    print(f"backup gate ok: {last['created']} ({last['path']}), {age_h:.0f}h old")


def plan(doc: dict, client: ZoteroClient) -> dict:
    """Read-only planning: what would change."""
    existing = client.collection_paths()
    # detect collection NAMES containing '/' (ambiguous with the path separator)
    raw = client.collections()
    slashy = sorted({c["data"]["name"] for c in raw if "/" in c["data"]["name"]})
    versions = client.get_versions()
    to_create = [p for p in _collect_targets(doc) if p not in existing]
    missing = [p["key"] for p in doc["proposals"] if p["key"] not in versions]
    return {
        "items": len(doc["proposals"]),
        "collections_to_create": to_create,
        "keys_not_on_server": missing,
        "existing_collections": existing,
        "slashy_names": slashy,
        "versions": versions,
    }


def _write_journal(name: str, profile: Profile, pre: dict, created_cols: dict) -> Path:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    jdir = journal_dir()
    jdir.mkdir(parents=True, exist_ok=True)
    jpath = jdir / f"{stamp}-{name}.json"
    jpath.write_text(json.dumps({
        "created": stamp,
        "steward": __version__,
        "kind": name,
        "library": {"type": profile.library_type, "id": str(profile.library_id)},
        "created_collections": created_cols,
        "pre_state": pre,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return jpath


def execute(doc: dict, client: ZoteroClient, profile: Profile,
            backup_check: bool = True) -> Path:
    if backup_check:
        _check_backup(profile)

    prefilled = sum(1 for pr in doc["proposals"]
                    if pr.get("note", "").startswith("(prefilled inbox"))
    if prefilled == len(doc["proposals"]):
        raise ApplyError("this looks like an untouched scaffold: every item still "
                         "has its prefilled inbox target. Fill in real targets first.")
    if prefilled:
        print(f"WARNING: {prefilled} items still have the prefilled inbox target")

    p = plan(doc, client)
    if p["keys_not_on_server"]:
        raise ApplyError(f"{len(p['keys_not_on_server'])} proposal keys do not exist "
                         f"on the server: {p['keys_not_on_server'][:5]} ...")
    if p["slashy_names"]:
        raise ApplyError(
            "collection name(s) contain '/', which collides with the path "
            f"separator and would misroute items: {p['slashy_names'][:5]}. "
            "Rename them in Zotero first.")

    # 1. create missing collections, parents before children
    path_key = dict(p["existing_collections"])
    created = {}
    for path in sorted(p["collections_to_create"], key=lambda s: s.count("/")):
        parent = path.rsplit("/", 1)[0] if "/" in path else None
        body = [{"name": path.rsplit("/", 1)[-1]}]
        if parent:
            body[0]["parentCollection"] = path_key[parent]
        resp = client.post_collections(body)
        if resp.get("failed"):
            raise ApplyError(f"creating collection {path!r} failed: {resp['failed']}")
        path_key[path] = resp["success"]["0"]
        created[path] = path_key[path]

    # 2. journal pre-state BEFORE any item write (rollback baseline)
    keys = [pr["key"] for pr in doc["proposals"]]
    pre = _fetch_items(client, keys)
    vanished = [k for k in keys if k not in pre]
    if vanished:
        raise ApplyError(f"{len(vanished)} items vanished between planning and write "
                         f"(deleted on another device?): {vanished[:5]} - "
                         "nothing written; re-run `steward propose`")
    jpath = _write_journal("apply", profile, pre, created)

    # 3. write: replace each item's collections with its targets
    intended = {pr["key"]: [path_key[t] for t in pr["targets"]] for pr in doc["proposals"]}
    updates = [{"key": k, "version": pre[k]["version"], "collections": intended[k]}
               for k in keys]
    result = client.post_items(updates)

    # 4. resolve failures WITHOUT clobbering concurrent edits
    if result["failed"]:
        failed_keys = [updates[int(idx)]["key"] for idx in result["failed"]]
        intended_full = {k: {"collections": intended[k]} for k in failed_keys}
        retry, conflicts, gone = resolve_conflicts(
            client, failed_keys, intended_full, pre, ("collections",))
        if retry:
            second = client.post_items(retry)
            for idx in second["failed"]:
                conflicts.append(retry[int(idx)]["key"])
        if conflicts or gone:
            msg = []
            if conflicts:
                msg.append(f"{len(conflicts)} items were edited concurrently and were "
                           f"left untouched: {conflicts[:5]}")
            if gone:
                msg.append(f"{len(gone)} items vanished mid-run: {gone[:5]}")
            raise ApplyError("; ".join(msg) + f". Already-applied items are journaled "
                             f"at {jpath} (use `steward rollback` to revert them).")

    print(f"applied {len(updates)} items "
          f"({len(created)} collections created)")
    print(f"journal: {jpath}")
    print(f"undo: steward rollback \"{jpath}\"")
    return jpath


# -- rollback ----------------------------------------------------------------

def list_journals() -> list[Path]:
    jdir = journal_dir()
    return sorted(jdir.glob("*.json")) if jdir.is_dir() else []


def rollback(journal_path: Path, client: ZoteroClient, profile: Profile,
             run: bool = False) -> None:
    doc = json.loads(journal_path.read_text(encoding="utf-8"))
    jlib = doc.get("library", {})
    if (jlib.get("type"), str(jlib.get("id"))) != (profile.library_type, str(profile.library_id)):
        raise ApplyError(
            f"journal was recorded for library {jlib.get('type')}/{jlib.get('id')}, "
            f"but the active profile is {profile.library_type}/{profile.library_id} - "
            "refusing to cross-apply")
    pre = doc["pre_state"]
    # restore exactly the fields the journal captured (collections, or tags+extra)
    sample = next(iter(pre.values()), {})
    fields = tuple(f for f in sample if f != "version") or ("collections",)
    fresh = _fetch_items(client, list(pre), fields=fields)
    gone = [k for k in pre if k not in fresh]
    restorable = [k for k in pre if k in fresh]
    if not restorable:
        raise ApplyError("nothing to roll back (all journaled items are gone)")
    print(f"rollback plan: restore {len(restorable)} items ({', '.join(fields)})"
          + (f"; {len(gone)} items no longer exist (skipped)" if gone else ""))
    if not run:
        print("DRY RUN - nothing written. Re-run with --run to execute.")
        return

    # journal the CURRENT state first, so a rollback is itself reversible
    cur = {k: fresh[k] for k in restorable}
    _write_journal("rollback", profile, cur, {})

    updates = []
    for k in restorable:
        u = {"key": k, "version": fresh[k]["version"]}
        for f in fields:
            u[f] = pre[k][f]
        updates.append(u)
    result = client.post_items(updates)
    if result["failed"]:
        raise ZoteroError(f"rollback failed for {len(result['failed'])} items - "
                          "rerun, or restore the full backup")
    print(f"rolled back {len(updates)} items to their journaled collections")
    print("note: collections created by apply are left in place (now possibly "
          "empty); delete them in Zotero if unwanted")
