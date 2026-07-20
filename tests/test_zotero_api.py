"""Transport-layer tests for ZoteroClient (zotero_api).

urlopen is stubbed entirely (no network); time.sleep is patched to a no-op so
retry/backoff paths run instantly. Covers: 429 / 5xx retry honoring Retry-After,
the Backoff response header, URLError local-vs-web retry policy, get_all
pagination stop, post_items 50-item batching + index rekeying, and the local
read-only write-guard.
"""
import json
import urllib.error

import pytest

from steward import zotero_api as za
from steward.config import Profile
from steward.zotero_api import ZoteroClient, ZoteroError


class FakeResp:
    """Context-manager stand-in for the object urlopen returns."""

    def __init__(self, status=200, headers=None, body=None):
        self.status = status
        self.headers = headers or {}
        self._raw = (json.dumps(body) if body is not None else "").encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def make_client(local=False):
    return ZoteroClient(Profile(library_id="42", api_key="k", local=local),
                        local=local)


@pytest.fixture
def no_sleep(monkeypatch):
    """Make every retry/backoff sleep instant and record the durations."""
    slept = []
    monkeypatch.setattr(za.time, "sleep", lambda s: slept.append(s))
    return slept


def patch_urlopen(monkeypatch, responses):
    """Stub urlopen to yield each item of `responses` in turn.

    An item may be a FakeResp (returned) or an Exception (raised). Records the
    Request objects it was called with so the test can inspect URLs/bodies.
    """
    seq = iter(responses)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        item = next(seq)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(za.urllib.request, "urlopen", fake_urlopen)
    return calls


# -- 429 / 5xx retry honoring Retry-After -----------------------------------

def test_retry_on_429_honors_retry_after(monkeypatch, no_sleep):
    client = make_client()
    err = urllib.error.HTTPError("u", 429, "slow down",
                                 {"Retry-After": "7"}, None)
    calls = patch_urlopen(monkeypatch, [err, FakeResp(200, body={"ok": 1})])
    status, _, data = client.request("GET", "/items")
    assert status == 200 and data == {"ok": 1}
    assert len(calls) == 2            # one failure + one success
    assert no_sleep == [7]            # slept exactly the Retry-After value


def test_retry_on_500_then_succeeds(monkeypatch, no_sleep):
    client = make_client()
    # 500 has no Retry-After -> default 5s; then a clean 200
    err = urllib.error.HTTPError("u", 503, "down", {}, None)
    patch_urlopen(monkeypatch, [err, FakeResp(200, body=[])])
    status, _, data = client.request("GET", "/items")
    assert status == 200 and data == []
    assert no_sleep == [5]            # default backoff for 5xx without Retry-After


def test_4xx_other_than_429_raises_immediately(monkeypatch, no_sleep):
    client = make_client()
    body = b"not found"

    class HTTPErr404(urllib.error.HTTPError):
        def read(self_inner):
            return body

    err = HTTPErr404("u", 404, "missing", {}, None)
    calls = patch_urlopen(monkeypatch, [err])
    with pytest.raises(ZoteroError, match="HTTP 404"):
        client.request("GET", "/items/ZZZZ")
    assert len(calls) == 1           # no retry on a 404
    assert no_sleep == []


def test_retries_exhausted_on_persistent_5xx(monkeypatch, no_sleep):
    client = make_client()
    err = urllib.error.HTTPError("u", 500, "boom", {}, None)
    # 4 attempts (retries default) all 5xx -> "retries exhausted"
    calls = patch_urlopen(monkeypatch, [err, err, err, err])
    with pytest.raises(ZoteroError, match="retries exhausted"):
        client.request("GET", "/items")
    assert len(calls) == 4


# -- Backoff response header -------------------------------------------------

def test_backoff_header_is_respected_and_capped(monkeypatch, no_sleep):
    client = make_client()
    # Backoff well above the 30s cap -> sleep is clamped to 30
    patch_urlopen(monkeypatch, [FakeResp(200, headers={"Backoff": "99"}, body={})])
    client.request("GET", "/items")
    assert no_sleep == [30]


# -- URLError: local vs web --------------------------------------------------

def test_urlerror_local_raises_immediately(monkeypatch, no_sleep):
    client = make_client(local=True)
    calls = patch_urlopen(monkeypatch, [urllib.error.URLError("refused")])
    with pytest.raises(ZoteroError, match="local API unreachable"):
        client.request("GET", "/items")
    assert len(calls) == 1           # local never retries
    assert no_sleep == []


def test_urlerror_web_retries_then_succeeds(monkeypatch, no_sleep):
    client = make_client(local=False)
    patch_urlopen(monkeypatch,
                  [urllib.error.URLError("flaky"), FakeResp(200, body={"ok": 1})])
    status, _, data = client.request("GET", "/items")
    assert status == 200 and data == {"ok": 1}
    assert no_sleep == [3]           # fixed 3s web retry pause


def test_urlerror_web_retries_exhausted(monkeypatch, no_sleep):
    client = make_client(local=False)
    e = urllib.error.URLError("down")
    calls = patch_urlopen(monkeypatch, [e, e, e, e])
    with pytest.raises(ZoteroError, match="failed:"):
        client.request("GET", "/items")
    assert len(calls) == 4           # all 4 attempts used
    assert no_sleep == [3, 3, 3]     # slept between the first three failures only


# -- get_all pagination ------------------------------------------------------

def test_get_all_stops_on_short_page(monkeypatch, no_sleep):
    client = make_client()
    full = [{"i": i} for i in range(100)]   # exactly one full page
    tail = [{"i": 100}, {"i": 101}]         # short page -> stop
    calls = patch_urlopen(monkeypatch,
                          [FakeResp(200, body=full), FakeResp(200, body=tail)])
    out = client.get_all("/collections")
    assert len(out) == 102
    assert len(calls) == 2
    # start= advanced by the page size between calls
    assert "start=0" in calls[0].full_url
    assert "start=100" in calls[1].full_url
    # path already had no '?', so the first separator is '?'
    assert "/collections?limit=100" in calls[0].full_url


def test_get_all_single_short_page(monkeypatch, no_sleep):
    client = make_client()
    patch_urlopen(monkeypatch, [FakeResp(200, body=[{"i": 1}])])
    out = client.get_all("/items?format=json")   # path already has '?'
    assert out == [{"i": 1}]


# -- post_items batching, rekeying, write-guard ------------------------------

def test_post_items_batches_and_rekeys_indices(monkeypatch, no_sleep):
    client = make_client()
    # 120 objects -> 3 batches (50 + 50 + 20). Each batch reports its own
    # 0-based indices; the client must rekey them to global indices.
    objects = [{"key": f"K{i:05d}", "version": 1, "collections": []}
               for i in range(120)]

    bodies = []

    def fake_urlopen(req, timeout=None):
        sent = json.loads(req.data.decode("utf-8"))
        bodies.append(sent)
        # mark the first object of each batch as success, the rest unchanged,
        # and the LAST object of each batch as failed (local idx len-1)
        n = len(sent)
        resp = {"success": {"0": sent[0]["key"]},
                "unchanged": {str(j): sent[j]["key"] for j in range(1, n - 1)},
                "failed": {str(n - 1): {"code": 412}}}
        return FakeResp(200, body=resp)

    monkeypatch.setattr(za.urllib.request, "urlopen", fake_urlopen)
    merged = client.post_items(objects)

    assert [len(b) for b in bodies] == [50, 50, 20]      # 50-item cap
    # success indices rekeyed to global 0, 50, 100
    assert set(merged["success"]) == {"0", "50", "100"}
    # failed indices rekeyed to the last of each batch: 49, 99, 119
    assert set(merged["failed"]) == {"49", "99", "119"}
    assert merged["success"]["50"] == "K00050"           # value follows the key
    # one inter-batch pause per batch (0.4s)
    assert no_sleep == [0.4, 0.4, 0.4]


def test_post_items_local_is_write_guarded(no_sleep):
    client = make_client(local=True)
    with pytest.raises(ZoteroError, match="read-only"):
        client.post_items([{"key": "K1", "version": 1, "collections": []}])


def test_post_collections_local_is_write_guarded(no_sleep):
    client = make_client(local=True)
    with pytest.raises(ZoteroError, match="read-only"):
        client.post_collections([{"name": "X"}])


def test_post_items_empty_is_noop(monkeypatch, no_sleep):
    client = make_client()
    # no objects -> no HTTP call, empty merged buckets
    patch_urlopen(monkeypatch, [])
    merged = client.post_items([])
    assert merged == {"success": {}, "unchanged": {}, "failed": {}}
    assert no_sleep == []
