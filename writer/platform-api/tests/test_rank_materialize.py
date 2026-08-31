"""Unit tests for materialize helpers.

No network: a tiny fake Supabase query builder records the query it receives
so we can assert the DataForSEO-rank fetch bypasses PostgREST's default
1000-row cap (the bug that stranded later keywords at status='no_data' on
large / GSC-less clients like Consultare).
"""

from __future__ import annotations

from datetime import date

from services import rank_materialize


def test_resolve_status_maps_no_data_to_unranked_after_a_fetch():
    # Checked by the DataForSEO fallback but ranks nowhere → 'unranked'.
    assert rank_materialize.resolve_status("no_data", True) == "unranked"
    # Never fetched yet → stays 'no_data'.
    assert rank_materialize.resolve_status("no_data", False) == "no_data"


def test_resolve_status_leaves_ranked_statuses_untouched():
    for s in ("climbing", "stable", "volatile", "dropping", "deindex_risk"):
        assert rank_materialize.resolve_status(s, True) == s
        assert rank_materialize.resolve_status(s, False) == s


# --------------------------------------------------------------------------
# GSC fetch: scope-to-tracked-keywords + paginate past the row cap.
#
# Regression for the live incident where gsc_position froze at the GSC set-up
# date for every connected client: a single unpaginated read was silently capped
# (PostgREST db-max-rows) to the earliest ~1000 rows — the initial back-fill
# batch — so every later daily-appended date was never seen and its gsc_position
# stayed NULL. The fake below ENFORCES a hard per-page cap (stricter than the real
# DB) so a non-paginating fetch would fail the test.
# --------------------------------------------------------------------------
class _CappedQuery:
    """Chainable double that filters, orders, and enforces a hard row cap."""

    def __init__(self, rows, calls, cap):
        self._rows = rows
        self.calls = calls
        self._cap = cap
        self._eq: dict = {}
        self._in: dict = {}
        self._gte: dict = {}
        self._lte: dict = {}
        self._orders: list = []
        self._range = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def in_(self, col, vals):
        self._in[col] = list(vals)
        self.calls.setdefault("in_cols", []).append(col)
        return self

    def gte(self, col, val):
        self._gte[col] = val
        return self

    def lte(self, col, val):
        self._lte[col] = val
        return self

    def is_(self, col, val):
        self.calls["is_"] = (col, val)
        return self

    @property
    def not_(self):
        self.calls["not_"] = True
        return self

    def order(self, col, *a, **k):
        self._orders.append(col)
        return self

    def limit(self, n):
        self.calls["limit"] = n
        return self

    def range(self, lo, hi):
        self._range = (lo, hi)
        self.calls.setdefault("ranges", []).append((lo, hi))
        return self

    def _match(self, r):
        return (
            all(r.get(c) == v for c, v in self._eq.items())
            and all(r.get(c) in vals for c, vals in self._in.items())
            and all(str(r.get(c)) >= str(v) for c, v in self._gte.items())
            and all(str(r.get(c)) <= str(v) for c, v in self._lte.items())
        )

    def execute(self):
        rows = [r for r in self._rows if self._match(r)]
        for col in reversed(self._orders):
            rows = sorted(rows, key=lambda r: str(r.get(col)))
        if self._range is not None:
            lo, hi = self._range
            hi = min(hi, lo + self._cap - 1)  # server never returns more than cap
            rows = rows[lo : hi + 1]
        else:
            rows = rows[: self._cap]
        return type("Res", (), {"data": rows})()


class _CappedSupabase:
    def __init__(self, rows, calls, cap):
        self._rows = rows
        self._calls = calls
        self._cap = cap

    def table(self, name):
        self._calls["table"] = name
        return _CappedQuery(self._rows, self._calls, self._cap)


def test_fetch_gsc_query_rows_paginates_and_scopes(monkeypatch):
    # Page size 3 but the server caps responses at 2 rows — i.e. cap < _READ_PAGE.
    # This is the case that a break-on-short-page loop gets wrong: it would stop
    # after the first (short) page and drop the rest. The cursor must advance by
    # rows actually returned and stop only on an empty page.
    monkeypatch.setattr(rank_materialize, "_READ_PAGE", 3)
    P = "prop-1"
    tracked = [
        {"property_id": P, "query": "medical coding services", "date": "2026-07-03", "position": 5},
        {"property_id": P, "query": "medical coding services", "date": "2026-07-04", "position": 6},
        {"property_id": P, "query": "medical coding services", "date": "2026-08-26", "position": 38},
        {"property_id": P, "query": "medical coding services", "date": "2026-08-30", "position": 33},
    ]
    # A query for another (untracked) term — must be excluded by scoping.
    noise = [{"property_id": P, "query": "unrelated term", "date": "2026-08-28", "position": 1}]
    calls: dict = {}
    supabase = _CappedSupabase(tracked + noise, calls, cap=2)

    rows = rank_materialize.fetch_gsc_query_rows(
        supabase, "prop-1", ["Medical Coding Services"], date(2026, 5, 3), date(2026, 8, 31)
    )

    # Scoped to the tracked query only.
    assert calls["table"] == "gsc_query_daily"
    assert "query" in calls.get("in_cols", [])
    assert {r["query"] for r in rows} == {"medical coding services"}
    # Paginated past a cap BELOW the page size: every date survives, none dropped.
    got = {r["date"] for r in rows}
    assert got == {"2026-07-03", "2026-07-04", "2026-08-26", "2026-08-30"}
    # The cursor advanced by rows returned (2), not the requested page size (3):
    # first two windows start at 0 then 2, and the final empty page ends it.
    ranges = calls.get("ranges", [])
    assert [lo for lo, _ in ranges] == [0, 2, 4]


def test_fetch_gsc_query_rows_empty_keywords_short_circuits():
    calls: dict = {}
    supabase = _CappedSupabase([], calls, cap=2)
    assert (
        rank_materialize.fetch_gsc_query_rows(
            supabase, "prop-1", [], date(2026, 5, 3), date(2026, 8, 31)
        )
        == []
    )
    assert calls == {}  # no query issued when there are no keywords


def test_fetch_gsc_query_page_rows_scopes_and_paginates(monkeypatch):
    # cap (2) below page size (3): the canonical read must page, not truncate.
    monkeypatch.setattr(rank_materialize, "_READ_PAGE", 3)
    P = "prop-1"
    tracked = [
        {"property_id": P, "query": "medical coding services", "date": "2026-08-01", "page": "/a", "clicks": 3, "impressions": 9},
        {"property_id": P, "query": "medical coding services", "date": "2026-08-02", "page": "/a", "clicks": 1, "impressions": 4},
        {"property_id": P, "query": "medical coding services", "date": "2026-08-03", "page": "/b", "clicks": 5, "impressions": 6},
    ]
    noise = [{"property_id": P, "query": "unrelated", "date": "2026-08-02", "page": "/x", "clicks": 9, "impressions": 9}]
    calls: dict = {}
    supabase = _CappedSupabase(tracked + noise, calls, cap=2)

    rows = rank_materialize.fetch_gsc_query_page_rows(
        supabase, "prop-1", ["Medical Coding Services"]
    )

    assert calls["table"] == "gsc_query_page_daily"
    assert "query" in calls.get("in_cols", [])
    # Scoped to the tracked query; all three of its rows survive the sub-page cap.
    assert {r["query"] for r in rows} == {"medical coding services"}
    assert {(r["page"], r["date"]) for r in rows} == {
        ("/a", "2026-08-01"),
        ("/a", "2026-08-02"),
        ("/b", "2026-08-03"),
    }
    # And the consumer resolves the higher-click page (/b: 5 vs /a: 3+1=4).
    assert rank_materialize.resolve_canonical_pages(rows) == {"medical coding services": "/b"}


def test_load_tracked_ranks_paginates_and_maps_rows(monkeypatch):
    # cap (2) below page size (3): load_tracked_ranks must page past the cap
    # (it used to rely on .limit(100000), which the cap silently overrode).
    monkeypatch.setattr(rank_materialize, "_READ_PAGE", 3)
    rows = [
        {"keyword_id": "a", "date": "2026-07-07", "tracked_rank": 1},
        {"keyword_id": "a", "date": "2026-07-10", "tracked_rank": 4},
        {"keyword_id": "b", "date": "2026-07-10", "tracked_rank": 12},
        # A stray null must be ignored even if it slips through.
        {"keyword_id": "c", "date": "2026-07-10", "tracked_rank": None},
    ]
    calls: dict = {}
    supabase = _CappedSupabase(rows, calls, cap=2)

    df_by_kw = rank_materialize.load_tracked_ranks(supabase, ["a", "b", "c"], date(2026, 4, 1))

    # Still filters to non-null tracked_rank, and now pages instead of one capped read.
    assert calls["table"] == "rank_keyword_metrics"
    assert calls.get("not_") is True
    assert calls.get("is_") == ("tracked_rank", "null")
    assert [lo for lo, _ in calls.get("ranges", [])] == [0, 2, 4]
    # Mapping: keyword_id -> {date_iso: rank}, nulls dropped.
    assert df_by_kw == {
        "a": {"2026-07-07": 1, "2026-07-10": 4},
        "b": {"2026-07-10": 12},
    }


def test_load_tracked_ranks_empty_keyword_ids_short_circuits():
    calls: dict = {}
    supabase = _CappedSupabase([], calls, cap=2)
    assert rank_materialize.load_tracked_ranks(supabase, [], date(2026, 4, 1)) == {}
    assert calls == {}  # no query issued when there are no keywords
