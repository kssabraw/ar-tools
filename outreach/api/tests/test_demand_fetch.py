"""Demand fetch — the valuation's search-volume + CPC producer.

Pure pieces (token resolution, request build, response parse, competition coercion, cache freshness)
plus the fetch flow around a stubbed DataForSEO call: it resolves + stores a location token, honours
a fresh cache without billing, upserts even an all-null (asked, no measurable volume) result, and
REFUSES — never bills, never fabricates — when it can't resolve a location or the keyword is invalid.
"""

import asyncio
import time

from api.services import demand_fetch
from api.services.demand_fetch import DemandFetchError


# The Google-Ads locations list resolve_location matches against. Seeded into the module cache so no
# network runs — fetch_locations returns the cached list. code values are arbitrary fixtures.
_US_LOCATIONS = [
    {"location_name": "Los Angeles,California,United States", "location_code": 1013962, "location_type": "City"},
    {"location_name": "Inglewood,California,United States", "location_code": 1013965, "location_type": "City"},
]


def _seed_locations(entries=_US_LOCATIONS, iso="US"):
    """Pre-seed the in-process locations cache so resolve_location matches without a network call."""
    demand_fetch._LOCATIONS_CACHE.clear()
    demand_fetch._LOCATIONS_CACHE[iso] = (time.monotonic(), [dict(e) for e in entries])


# --- fakes ------------------------------------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name, op="select", payload=None, on_conflict=None):
        self.db, self.name, self.op, self.payload, self.on_conflict = db, name, op, payload, on_conflict
        self.filters = []
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        return _Query(self.db, self.name, "insert", payload)

    def update(self, payload):
        return _Query(self.db, self.name, "update", payload)

    def upsert(self, payload, on_conflict=None):
        return _Query(self.db, self.name, "upsert", payload, on_conflict=on_conflict)

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row):
        return all(str(row.get(c)) == str(v) for c, v in self.filters)

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = [dict(r) for r in payload]
            for i, row in enumerate(written):
                row.setdefault("id", f"{self.name}-{len(rows) + i}")
            rows.extend(written)
            return _Result(written)
        if self.op == "upsert":
            keys = [k.strip() for k in (self.on_conflict or "").split(",") if k.strip()]
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = []
            for rec in payload:
                match = None
                if keys:
                    match = next(
                        (r for r in rows if all(str(r.get(k)) == str(rec.get(k)) for k in keys)),
                        None,
                    )
                if match is not None:
                    match.update(rec)
                    written.append(dict(match))
                else:
                    row = dict(rec)
                    row.setdefault("id", f"{self.name}-{len(rows)}")
                    rows.append(row)
                    written.append(dict(row))
            return _Result(written)
        if self.op == "update":
            hit = [r for r in rows if self._matches(r)]
            for row in hit:
                row.update(self.payload)
            return _Result([dict(r) for r in hit])
        found = [r for r in rows if self._matches(r)]
        if self._limit is not None:
            found = found[: self._limit]
        return _Result([dict(r) for r in found])


class _FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self, name)


class _Settings:
    dataforseo_login = "test-login"
    dataforseo_password = "test-pass"
    dataforseo_request_timeout_seconds = 180.0
    dataforseo_default_language_code = "en"
    dataforseo_cost_per_request_cents = 1
    demand_refresh_days = 30
    demand_default_country_iso = "US"
    demand_locations_cache_ttl_seconds = 24 * 60 * 60


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeHTTP:
    """A stub httpx.AsyncClient — records POSTs and returns a fixed body. A `body` of None makes any
    POST fail the test (proving the fetch never billed)."""

    def __init__(self, body=None):
        self._body = body
        self.calls = []

    async def post(self, url, headers=None, json=None):
        self.calls.append((url, json))
        assert self._body is not None, "fetch_demand billed a request it should have skipped"
        return _Resp(self._body)


def _volume_body(keyword="plumber", volume=1200, cpc=6.5, competition="HIGH"):
    return {"tasks": [{"status_code": 20000, "result": [
        {"keyword": keyword, "search_volume": volume, "cpc": cpc, "competition": competition},
    ]}]}


def _seed(db, *, submarket=None, keyword_demand=()):
    db.tables["scan_snapshot"] = [{"id": "snap-1", "submarket_id": "sub-1", "keyword_id": "kw-1"}]
    db.tables["submarket"] = [submarket or {"id": "sub-1", "name": "Los Angeles", "market_id": "m-1"}]
    db.tables["market"] = [{"id": "m-1", "name": "Los Angeles Plumbing"}]
    db.tables["keyword_demand"] = [dict(r) for r in keyword_demand]


# --- pure: location resolution (I-122) --------------------------------------------------------


def test_city_query_prefers_submarket_first_segment_then_market():
    assert demand_fetch.city_query({"name": "Los Angeles, CA, USA"}, {"name": "X"}) == "Los Angeles"
    assert demand_fetch.city_query({"name": "Van Nuys"}, {"name": "X"}) == "Van Nuys"
    assert demand_fetch.city_query({"name": ""}, {"name": "Inglewood, CA, USA"}) == "Inglewood"
    assert demand_fetch.city_query({"name": " "}, None) is None
    assert demand_fetch.city_query({}, {}) is None


def test_infer_country_iso_reads_trailing_token_else_default():
    assert demand_fetch.infer_country_iso({"name": "Los Angeles, CA, USA"}, None) == "US"
    assert demand_fetch.infer_country_iso({"name": "Sydney, NSW, Australia"}, None) == "AU"
    # bare "CA" is NOT Canada (California, mid-name) — falls through to the default
    assert demand_fetch.infer_country_iso({"name": "Van Nuys"}, None, default="US") == "US"
    assert demand_fetch.infer_country_iso({"name": ""}, {"name": "Whittier"}, default="US") == "US"


def test_match_location_ranks_exact_city_and_type():
    locs = [
        {"location_name": "Los Angeles,California,United States", "location_code": 1013962, "location_type": "City"},
        {"location_name": "Los Angeles County,California,United States", "location_code": 9990, "location_type": "County"},
        {"location_name": "East Los Angeles,California,United States", "location_code": 8880, "location_type": "City"},
    ]
    # exact city segment wins over a county / a substring match
    assert demand_fetch.match_location(locs, "Los Angeles") == ("Los Angeles,California,United States", 1013962)
    # no match → None (the caller then refuses)
    assert demand_fetch.match_location(locs, "Nowheresville") is None
    assert demand_fetch.match_location([], "Los Angeles") is None


# --- pure: keyword guard ----------------------------------------------------------------------


def test_keyword_ok_enforces_caps():
    assert demand_fetch._keyword_ok("emergency plumber") is None
    assert demand_fetch._keyword_ok("") is not None
    assert demand_fetch._keyword_ok("x" * 81) is not None
    assert demand_fetch._keyword_ok(" ".join(["w"] * 11)) is not None


def test_build_search_volume_task_shape():
    # a numeric-code token (the resolved, endpoint-accepted form) → location_code
    code_task = demand_fetch.build_search_volume_task("plumber", "1013962", language_code="en")
    assert code_task == {"keywords": ["plumber"], "location_code": 1013962, "language_code": "en"}
    # a non-digit token → location_name (back-compat)
    name_task = demand_fetch.build_search_volume_task("plumber", "Los Angeles", language_code="en")
    assert name_task == {"keywords": ["plumber"], "location_name": "Los Angeles", "language_code": "en"}


# --- pure: competition coercion ---------------------------------------------------------------


def test_coerce_competition():
    assert demand_fetch._coerce_competition({"competition_index": 50}) == 0.5
    assert demand_fetch._coerce_competition({"competition_index": 200}) == 1.0   # clamped
    assert demand_fetch._coerce_competition({"competition": 0.3}) == 0.3
    assert demand_fetch._coerce_competition({"competition": "HIGH"}) == 0.9
    assert demand_fetch._coerce_competition({"competition": "unknown"}) is None
    assert demand_fetch._coerce_competition({}) is None


# --- pure: parse ------------------------------------------------------------------------------


def test_parse_search_volume_happy():
    m = demand_fetch.parse_search_volume(_volume_body(), "plumber")
    assert m.search_volume == 1200 and m.cpc == 6.5 and m.competition == 0.9


def test_parse_search_volume_case_insensitive_match():
    body = _volume_body(keyword="Plumber")
    m = demand_fetch.parse_search_volume(body, "plumber")
    assert m.search_volume == 1200


def test_parse_search_volume_task_error_raises():
    body = {"tasks": [{"status_code": 40501, "status_message": "invalid location"}]}
    try:
        demand_fetch.parse_search_volume(body, "plumber")
        assert False, "expected DemandFetchError"
    except DemandFetchError as exc:
        assert "40501" in str(exc)


def test_parse_search_volume_no_matching_item_is_all_none():
    body = {"tasks": [{"status_code": 20000, "result": [{"keyword": "roofer", "search_volume": 9}]}]}
    m = demand_fetch.parse_search_volume(body, "plumber")
    assert m.search_volume is None and m.cpc is None and m.competition is None


def test_parse_search_volume_null_volume_is_a_finding_not_an_error():
    body = {"tasks": [{"status_code": 20000, "result": [
        {"keyword": "plumber", "search_volume": None, "cpc": None},
    ]}]}
    m = demand_fetch.parse_search_volume(body, "plumber")
    assert m.search_volume is None and m.cpc is None


# --- pure: cache freshness --------------------------------------------------------------------


def test_is_cache_fresh():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    fresh = (now - timedelta(days=5)).isoformat()
    stale = (now - timedelta(days=40)).isoformat()
    assert demand_fetch.is_cache_fresh(fresh, 30, now) is True
    assert demand_fetch.is_cache_fresh(stale, 30, now) is False
    assert demand_fetch.is_cache_fresh(stale, 0, now) is True     # 0 = never refresh → always fresh
    assert demand_fetch.is_cache_fresh(None, 30, now) is False


# --- flow: fetch_demand -----------------------------------------------------------------------


def test_fetch_demand_happy_path_bills_stores_and_caches_token():
    db = _FakeDB()
    _seed(db)
    _seed_locations()
    http = _FakeHTTP(_volume_body())
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.stored is True and report.already_cached is False
    assert report.search_volume == 1200 and report.cpc == 6.5
    assert len(http.calls) == 1  # one billed request
    # the resolved token is the numeric location_code (I-122), stored on the submarket for reuse
    assert db.tables["submarket"][0]["location_token"] == "1013962"
    # the search_volume request geo-targets by location_code, not a bare name
    assert http.calls[0][1] == [{"keywords": ["plumber"], "location_code": 1013962, "language_code": "en"}]
    # the cache row is keyed (normalised keyword, resolved code token)
    row = db.tables["keyword_demand"][0]
    assert row["keyword"] == "plumber" and row["location_token"] == "1013962"
    assert row["search_volume"] == 1200 and row["competition"] == 0.9
    # a cost_ledger row was written
    assert db.tables["cost_ledger"][0]["stage"] == "b_demand"


def test_fetch_demand_fresh_cache_is_a_free_no_op():
    db = _FakeDB()
    from datetime import datetime, timezone
    fresh = datetime(2026, 9, 5, tzinfo=timezone.utc).isoformat()
    _seed(
        db,
        # a code token is already stored (digit) → no re-resolution; the fresh cache row is keyed by it
        submarket={"id": "sub-1", "name": "Los Angeles", "market_id": "m-1", "location_token": "1013962"},
        keyword_demand=[{"keyword": "plumber", "location_token": "1013962",
                         "search_volume": 800, "cpc": 5.0, "fetched_at": fresh}],
    )
    http = _FakeHTTP(body=None)  # any POST fails the test
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.already_cached is True and report.stored is False
    assert report.search_volume == 800
    assert http.calls == []


def test_fetch_demand_reresolves_a_stale_name_token_to_a_code():
    """A pre-I-122 non-digit token is stale — the fetch re-resolves it to a numeric code (self-heal)."""
    db = _FakeDB()
    _seed(db, submarket={"id": "sub-1", "name": "Los Angeles", "market_id": "m-1",
                         "location_token": "Los Angeles, CA, USA"})
    _seed_locations()
    http = _FakeHTTP(_volume_body())
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.stored is True
    assert db.tables["submarket"][0]["location_token"] == "1013962"  # re-resolved to the code
    assert http.calls[0][1][0]["location_code"] == 1013962


def test_fetch_demand_refuses_when_no_location_resolvable():
    db = _FakeDB()
    _seed(db, submarket={"id": "sub-1", "name": "", "market_id": "m-1"})
    db.tables["market"] = [{"id": "m-1", "name": ""}]
    http = _FakeHTTP(body=None)
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.stored is False and report.already_cached is False
    assert any("could not resolve a DataForSEO location_code" in p for p in report.problems)
    assert http.calls == []  # never billed
    assert db.tables.get("keyword_demand", []) == []  # nothing cached


def test_fetch_demand_refuses_when_city_not_in_locations_list():
    """A city that matches nothing in the Google-Ads locations list REFUSES — never bills, never
    sends a bad location (the 40501 the fix exists to prevent)."""
    db = _FakeDB()
    _seed(db, submarket={"id": "sub-1", "name": "Nowheresville", "market_id": "m-1"})
    db.tables["market"] = [{"id": "m-1", "name": "Nowheresville"}]
    _seed_locations()  # list has Los Angeles / Inglewood, not Nowheresville
    http = _FakeHTTP(body=None)
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.stored is False
    assert any("could not resolve a DataForSEO location_code" in p for p in report.problems)
    assert http.calls == []
    assert db.tables.get("keyword_demand", []) == []


def test_fetch_demand_skips_an_oversized_keyword():
    db = _FakeDB()
    _seed(db)
    http = _FakeHTTP(body=None)
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "x" * 90,
                                  market_id="m-1", client=http)
    )
    assert report.stored is False and http.calls == []


def test_fetch_demand_caches_a_null_result():
    """An all-null response is a finding worth caching so we don't re-bill it every scan."""
    db = _FakeDB()
    _seed(db)
    _seed_locations()
    body = {"tasks": [{"status_code": 20000, "result": [{"keyword": "plumber", "search_volume": None}]}]}
    http = _FakeHTTP(body)
    report = asyncio.run(
        demand_fetch.fetch_demand(db, _Settings(), db.tables["scan_snapshot"][0], "plumber",
                                  market_id="m-1", client=http)
    )
    assert report.stored is True and report.search_volume is None
    assert db.tables["keyword_demand"][0]["search_volume"] is None
