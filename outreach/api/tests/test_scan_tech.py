"""scan-tech orchestration — the per-prospect site scan, with the fetch mocked.

No network: `scan_prospect_tech` and `run_tech_scan` take a `fetch` callable, so the whole producer
is testable off hand-built responses. What matters here: a failed fetch stores a STATUS (unknown),
never an all-False "no ad tech" (absent); the GTM follow only fires when configured and needed; and
one bad site never ends the batch.
"""
import asyncio

import pytest

from api.config import Settings
from api.services import scan_tech
from api.services.scan_tech import FetchResult, STATUS_OK, STATUS_UNREACHABLE


def _settings(**over):
    return Settings(supabase_url="x", supabase_service_role_key="x", **over)


def _run(coro):
    return asyncio.run(coro)


def test_scan_prospect_no_website_returns_none():
    p = {"id": "p1", "name": "X", "website": None}
    async def fetch(url):  # never called
        raise AssertionError
    assert _run(scan_tech.scan_prospect_tech(p, _settings(), fetch=fetch)) is None


def test_failed_fetch_stores_unknown_not_absent():
    p = {"id": "p1", "name": "X", "website": "drips.com"}
    async def fetch(url):
        return FetchResult(STATUS_UNREACHABLE, url, "")
    row = _run(scan_tech.scan_prospect_tech(p, _settings(), fetch=fetch))
    assert row["fetch_status"] == STATUS_UNREACHABLE
    assert row["meta_pixel"] is False           # all-False, but the status says it's UNKNOWN
    assert row["prospect_id"] == "p1"


def test_ok_fetch_detects_tech():
    p = {"id": "p1", "name": "X", "website": "drips.com"}
    async def fetch(url):
        return FetchResult(STATUS_OK, url, "fbq('init','333333'); cdn.callrail.com")
    row = _run(scan_tech.scan_prospect_tech(p, _settings(), fetch=fetch))
    assert row["fetch_status"] == STATUS_OK
    assert row["meta_pixel"] is True and row["vendor_tags"] == ["callrail"]


def test_gtm_follow_recovers_injected_pixel_only_when_enabled():
    p = {"id": "p1", "name": "X", "website": "drips.com"}
    page = "<script src='https://www.googletagmanager.com/gtm.js?id=GTM-XYZ123'></script>"
    container = "fbq('init','444444'); connect.facebook.net/fbevents.js"

    async def fetch(url):
        return FetchResult(STATUS_OK, url, container if "gtm.js" in url else page)

    # Follow OFF -> the injected pixel is missed (the §16a.1 false negative).
    off = _run(scan_tech.scan_prospect_tech(p, _settings(tech_follow_gtm=False), fetch=fetch))
    assert off["meta_pixel"] is False and off["gtm_followed"] is False
    # Follow ON -> recovered.
    on = _run(scan_tech.scan_prospect_tech(p, _settings(tech_follow_gtm=True), fetch=fetch))
    assert on["meta_pixel"] is True and on["gtm_followed"] is True


class _Exec:
    def __init__(self, data): self.data = data


class _FakeTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._lo = self._hi = None
    def select(self, *_a): return self
    def eq(self, *_a): return self
    @property
    def not_(self): return self          # supabase-py exposes `.not_.is_(...)`
    def is_(self, *_a): return self
    def range(self, lo, hi):
        self._lo, self._hi = lo, hi; return self
    def insert(self, rows):
        self.store.setdefault("inserted", []).extend(rows); return self
    def execute(self):
        if self.name == "prospect" and self._lo is not None:
            return _Exec(self.store["prospects"][self._lo:self._hi + 1])
        return _Exec([])


class _FakeDB:
    def __init__(self, store): self.store = store
    def table(self, name):
        return _FakeTable(self.store, name)


def test_run_tech_scan_one_bad_site_never_ends_the_batch():
    store = {"prospects": [
        {"id": "p1", "name": "A", "website": "a.com"},
        {"id": "p2", "name": "B", "website": "b.com"},
        {"id": "p3", "name": "C", "website": "c.com"},
    ]}
    db = _FakeDB(store)

    async def fetch(url):
        if "b.com" in url:
            raise RuntimeError("boom")            # p2 blows up mid-scan
        return FetchResult(STATUS_OK, url, "fbq('init','999999')")

    report = _run(scan_tech.run_tech_scan(db, _settings(), market_id="m1", fetch=fetch))
    assert report.considered == 3
    # p1 + p3 fetched + stored; p2's exception is captured, not raised.
    assert report.stored == 2
    assert report.with_pixel == 2
    # The exception counts as a FAILURE, so the numbers add up: considered == ok + failed.
    assert report.failed == 1
    assert report.considered == report.fetched_ok + report.failed
    assert any("p2" in prob for prob in report.problems)


def test_page_body_is_capped_so_one_huge_page_cannot_blow_memory():
    p = {"id": "p1", "name": "X", "website": "drips.com"}
    huge = "x" * 5_000_000 + "fbq('init','777777')"      # the pixel sits past the cap

    async def fetch(url):
        return FetchResult(STATUS_OK, url, huge[:_settings(tech_max_page_bytes=1000).tech_max_page_bytes])

    row = _run(scan_tech.scan_prospect_tech(p, _settings(tech_max_page_bytes=1000), fetch=fetch))
    # Truncation is the point: we bound the work rather than scanning 5 MB of one page.
    assert row["fetch_status"] == STATUS_OK and row["meta_pixel"] is False


# --- Auto tech-scan backlog (the `tick` drain) -------------------------------------------------

def test_pick_backlog_skips_signaled_and_websiteless():
    candidates = [
        {"id": "p1", "name": "A", "website": "a.com"},      # due
        {"id": "p2", "name": "B", "website": "b.com"},      # already signaled -> skip
        {"id": "p3", "name": "C", "website": None},         # no website -> skip
        {"id": "p4", "name": "D", "website": "mailto:x@y"},  # not a fetchable URL -> skip
        {"id": "p5", "name": "E", "website": "e.com"},      # due
    ]
    picked = scan_tech.pick_backlog(candidates, signaled={"p2"}, limit=None)
    assert [p["id"] for p in picked] == ["p1", "p5"]


def test_pick_backlog_caps_at_limit_preserving_order():
    candidates = [{"id": f"p{i}", "website": f"{i}.com"} for i in range(5)]
    picked = scan_tech.pick_backlog(candidates, signaled=set(), limit=2)
    assert [p["id"] for p in picked] == ["p0", "p1"]


class _BacklogTable:
    """A supabase-py-ish builder over an in-memory store for the two backlog reads + the store."""

    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._lo = self._hi = None
        self._gte = None

    def select(self, *_a): return self
    def eq(self, *_a): return self
    def order(self, *_a, **_k): return self

    @property
    def not_(self): return self
    def is_(self, *_a): return self

    def gte(self, _col, value):
        self._gte = value
        return self

    def range(self, lo, hi):
        self._lo, self._hi = lo, hi
        return self

    def insert(self, rows):
        self.store.setdefault("inserted", []).extend(rows)
        return self

    def execute(self):
        if self.name == "prospect":
            rows = self.store["prospects"]
        elif self.name == "prospect_tech_signal":
            rows = [
                s for s in self.store.get("signals", [])
                if self._gte is None or s.get("fetched_at", "") >= self._gte
            ]
        else:
            rows = []
        if self._lo is not None:
            rows = rows[self._lo : self._hi + 1]
        return _Exec(rows)


class _BacklogDB:
    def __init__(self, store): self.store = store
    def table(self, name): return _BacklogTable(self.store, name)


def test_run_tech_backlog_fetches_only_unsignaled():
    store = {
        "prospects": [
            {"id": "p1", "name": "A", "website": "a.com"},
            {"id": "p2", "name": "B", "website": "b.com"},   # already has a signal -> skipped
            {"id": "p3", "name": "C", "website": "c.com"},
        ],
        "signals": [{"prospect_id": "p2", "fetched_at": "2999-01-01T00:00:00+00:00"}],
    }
    db = _BacklogDB(store)
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(url)
        return FetchResult(STATUS_OK, url, "fbq('init','111111')")

    # refresh_days=0 -> ANY existing signal counts, so p2 is skipped regardless of its age.
    report = _run(scan_tech.run_tech_backlog(db, _settings(), refresh_days=0, fetch=fetch))
    assert report.considered == 2
    assert report.stored == 2
    assert sorted(r["prospect_id"] for r in store["inserted"]) == ["p1", "p3"]
    assert "b.com" not in " ".join(fetched)


def test_run_tech_backlog_refresh_days_refetches_a_stale_signal():
    store = {
        "prospects": [{"id": "p1", "name": "A", "website": "a.com"}],
        # An ancient signal — older than any positive refresh window.
        "signals": [{"prospect_id": "p1", "fetched_at": "2000-01-01T00:00:00+00:00"}],
    }
    db = _BacklogDB(store)

    async def fetch(url):
        return FetchResult(STATUS_OK, url, "fbq('init','111111')")

    # Fetch-once (0) treats the ancient signal as current -> nothing due.
    once = _run(scan_tech.run_tech_backlog(db, _settings(), refresh_days=0, fetch=fetch))
    assert once.considered == 0 and once.stored == 0
    # A positive window makes the ancient signal stale -> re-fetched.
    stale = _run(scan_tech.run_tech_backlog(db, _settings(), refresh_days=45, fetch=fetch))
    assert stale.considered == 1 and stale.stored == 1


def test_run_tech_backlog_disabled_when_per_tick_zero():
    store = {"prospects": [{"id": "p1", "website": "a.com"}], "signals": []}
    db = _BacklogDB(store)

    async def fetch(url):  # must never be called
        raise AssertionError("backlog ran while disabled")

    report = _run(scan_tech.run_tech_backlog(db, _settings(tech_scan_per_tick=0), fetch=fetch))
    assert report.considered == 0 and report.stored == 0
    assert "inserted" not in store
