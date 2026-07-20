"""Zotero API client (stdlib only): Web API v3 and local read-only API.

Safety contract baked in:
- every write carries per-object versions (412 conflicts surface, never clobber),
- 429/5xx retries honor Retry-After, Backoff headers are respected,
- batches capped at 50 objects (API limit).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .config import Profile

WEB_BASE = "https://api.zotero.org"
LOCAL_BASE = "http://127.0.0.1:23119/api"
BATCH = 50


class ZoteroError(RuntimeError):
    pass


class ZoteroClient:
    def __init__(self, profile: Profile, local: bool | None = None):
        self.profile = profile
        self.local = profile.local if local is None else local
        if self.local:
            self.base = f"{LOCAL_BASE}/users/0"
        else:
            kind = "groups" if profile.library_type == "group" else "users"
            self.base = f"{WEB_BASE}/{kind}/{profile.library_id}"

    # -- transport ---------------------------------------------------------

    def request(self, method: str, path: str, body=None, retries: int = 4):
        headers = {"Zotero-API-Version": "3"}
        if not self.local and self.profile.api_key:
            headers["Zotero-API-Key"] = self.profile.api_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    backoff = r.headers.get("Backoff")
                    if backoff:
                        time.sleep(min(int(backoff), 30))
                    raw = r.read().decode("utf-8")
                    return r.status, dict(r.headers), (json.loads(raw) if raw else None)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(int(e.headers.get("Retry-After", 5)))
                    continue
                raise ZoteroError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}") from e
            except urllib.error.URLError as e:
                if self.local:
                    raise ZoteroError(
                        "local API unreachable - is Zotero running and "
                        "'Allow other applications on this computer to communicate "
                        "with Zotero' enabled in Settings > Advanced?") from e
                if attempt == retries - 1:
                    raise ZoteroError(f"{method} {path} failed: {e}") from e
                time.sleep(3)
        raise ZoteroError(f"{method} {path}: retries exhausted")

    # -- reads -------------------------------------------------------------

    def get_all(self, path: str, page: int = 100) -> list:
        """Fetch a paginated endpoint completely. `path` must not contain start=."""
        sep = "&" if "?" in path else "?"
        out, start = [], 0
        while True:
            _, _, data = self.request("GET", f"{path}{sep}limit={page}&start={start}")
            out.extend(data)
            if len(data) < page:
                return out
            start += page

    def get_versions(self) -> dict:
        """{itemKey: version} for ALL items (incl. children)."""
        _, _, data = self.request("GET", "/items?format=versions")
        return data

    def library_version(self) -> int:
        # NB: must hit a JSON endpoint (request() json-decodes every body);
        # format=keys returns plain text and would crash on non-empty libraries.
        _, headers, _ = self.request("GET", "/items/top?limit=1")
        return int(headers.get("Last-Modified-Version", 0))

    def collections(self) -> list:
        return self.get_all("/collections")

    def collection_paths(self) -> dict:
        """{path: key} for every collection, '/'-joined from the top."""
        cols = self.collections()
        by_key = {c["key"]: c["data"] for c in cols}

        def path_of(key: str) -> str:
            parts, cur = [], by_key.get(key)
            while cur:
                parts.append(cur["name"])
                parent = cur.get("parentCollection")
                cur = by_key.get(parent) if parent else None
            return "/".join(reversed(parts))

        return {path_of(c["key"]): c["key"] for c in cols}

    # -- writes (Web API only; used by apply/tag, plumbing for M1) ----------

    def post_items(self, objects: list) -> dict:
        """Multi-object write in batches of 50. Each object must carry key+version
        (update) or no key (create). Returns merged {success, unchanged, failed}."""
        if self.local:
            raise ZoteroError("the local API is read-only; writes need web mode "
                              "(an API key with write access)")
        merged = {"success": {}, "unchanged": {}, "failed": {}}
        for i in range(0, len(objects), BATCH):
            status, _, resp = self.request("POST", "/items", objects[i:i + BATCH])
            if status != 200:
                raise ZoteroError(f"batch write failed: HTTP {status}")
            for bucket in merged:
                for idx, val in resp.get(bucket, {}).items():
                    merged[bucket][str(i + int(idx))] = val
            time.sleep(0.4)
        return merged

    def post_collections(self, objects: list) -> dict:
        if self.local:
            raise ZoteroError("the local API is read-only; writes need web mode")
        status, _, resp = self.request("POST", "/collections", objects)
        if status != 200:
            raise ZoteroError(f"collection write failed: HTTP {status}")
        return resp
