"""Unit tests for materialize helpers.

No network: a tiny fake Supabase query builder records the query it receives
so we can assert the DataForSEO-rank fetch bypasses PostgREST's default
1000-row cap (the bug that stranded later keywords at status='no_data' on
large / GSC-less clients like Consultare).
"""

from __future__ import annotations

from datetime import date

from services import rank_materialize


class _FakeQuery:
    """Chainable query double that records calls and returns a fixed dataset."""

    def __init__(self, rows, calls):
        self._rows = rows
        self.calls = calls  # shared dict recording what the caller applied

    # supabase-py chain methods — record and return self for chaining.
    def select(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def is_(self, col, val):
        self.calls["is_"] = (col, val)
        return self

    @property
    def not_(self):
        self.calls["not_"] = True
        return self

    def limit(self, n):
        self.calls["limit"] = n
        return self

    def execute(self):
        return type("Res", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def table(self, name):
        self._calls["table"] = name
        return _FakeQuery(self._rows, self._calls)


def test_load_tracked_ranks_bypasses_row_cap_and_maps_rows():
    rows = [
        {"keyword_id": "a", "date": "2026-07-07", "tracked_rank": 1},
        {"keyword_id": "a", "date": "2026-07-10", "tracked_rank": 4},
        {"keyword_id": "b", "date": "2026-07-10", "tracked_rank": 12},
        # A stray null must be ignored even if it slips through.
        {"keyword_id": "c", "date": "2026-07-10", "tracked_rank": None},
    ]
    calls: dict = {}
    supabase = _FakeSupabase(rows, calls)

    df_by_kw = rank_materialize.load_tracked_ranks(supabase, ["a", "b", "c"], date(2026, 4, 1))

    # Regression guards: the query must filter to non-null tracked_rank AND set
    # an explicit high limit so the default 1000-row cap can't truncate it.
    assert calls["table"] == "rank_keyword_metrics"
    assert calls.get("not_") is True
    assert calls.get("is_") == ("tracked_rank", "null")
    assert calls.get("limit") == rank_materialize._MAX_METRIC_ROWS
    assert rank_materialize._MAX_METRIC_ROWS >= 100000

    # Mapping: keyword_id -> {date_iso: rank}, nulls dropped.
    assert df_by_kw == {
        "a": {"2026-07-07": 1, "2026-07-10": 4},
        "b": {"2026-07-10": 12},
    }


def test_load_tracked_ranks_empty_keyword_ids_short_circuits():
    calls: dict = {}
    supabase = _FakeSupabase([], calls)
    assert rank_materialize.load_tracked_ranks(supabase, [], date(2026, 4, 1)) == {}
    # No query issued when there are no keywords.
    assert calls == {}
