"""Which geo-grid scans count as reporting, and how an on-demand scan is scoped
to a subset of keywords.

Two features that meet in the same place: reporting reads the SCHEDULED series
only, and a manual run may cover only some keywords. They depend on each other —
a partial keyword set is safe precisely because a partial scan is always a
one-off, so it can never land in a series that assumes full coverage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import maps_reporting  # noqa: E402
from services.local_dominator import resolve_scan_keywords  # noqa: E402


# ---------------------------------------------------------------------------
# is_reporting_scan / filter_reporting
# ---------------------------------------------------------------------------
def test_scheduled_scans_are_reporting_and_one_offs_are_not():
    assert maps_reporting.is_reporting_scan({"trigger": "scheduled"}) is True
    assert maps_reporting.is_reporting_scan({"trigger": "manual"}) is False


def test_parallel_test_scans_stay_out_of_reporting():
    # The §7 provider-comparison quarantine was already excluded from the
    # completion hooks; it must not sneak back in through a reporting read.
    assert maps_reporting.is_reporting_scan({"trigger": "parallel_test"}) is False


def test_accepts_a_bare_trigger_string():
    # enqueue_completion_hooks only has the trigger, not the row.
    assert maps_reporting.is_reporting_scan("scheduled") is True
    assert maps_reporting.is_reporting_scan("manual") is False


def test_a_scan_with_no_trigger_is_treated_as_reporting():
    # The column is NOT NULL in practice. If one ever arrives without it,
    # dropping a real scan out of every chart is the worse failure.
    assert maps_reporting.is_reporting_scan({}) is True
    assert maps_reporting.is_reporting_scan(None) is True


def test_an_unrecognised_trigger_is_excluded_by_default():
    # REPORTING_TRIGGERS is an allowlist: a new trigger stays out of client-facing
    # reporting until someone opts it in deliberately.
    assert maps_reporting.is_reporting_scan({"trigger": "backfill"}) is False


def test_filter_reporting_keeps_order_and_drops_one_offs():
    scans = [
        {"id": "a", "trigger": "scheduled"},
        {"id": "b", "trigger": "manual"},
        {"id": "c", "trigger": "scheduled"},
    ]
    assert [s["id"] for s in maps_reporting.filter_reporting(scans)] == ["a", "c"]


class _FakeQuery:
    """Records the filters applied, like the Supabase query builder chain."""

    def __init__(self):
        self.calls = []

    def in_(self, column, values):
        self.calls.append(("in_", column, values))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self


def test_only_reporting_filters_the_query_by_trigger():
    q = _FakeQuery()
    out = maps_reporting.only_reporting(q)
    assert out is q  # composes into the existing chain
    assert q.calls == [("in_", "trigger", ["scheduled"])]


def test_only_reporting_composes_with_the_call_sites_own_filters():
    q = _FakeQuery()
    maps_reporting.only_reporting(q).eq("client_id", "c1").eq("status", "complete")
    assert q.calls[0] == ("in_", "trigger", ["scheduled"])
    assert ("eq", "status", "complete") in q.calls


# ---------------------------------------------------------------------------
# resolve_scan_keywords
# ---------------------------------------------------------------------------
ACTIVE = ["historical preservation architects nyc", "local law 97 architects", "adaptive reuse nyc"]


def test_no_requested_keywords_scans_the_whole_active_set():
    to_scan, unknown = resolve_scan_keywords(ACTIVE, None)
    assert to_scan == ACTIVE
    assert unknown == []


def test_an_empty_request_also_means_all_keywords():
    # The router sends None for "no selection"; defend against [] too, since an
    # empty selection must never start a zero-keyword scan.
    assert resolve_scan_keywords(ACTIVE, [])[0] == ACTIVE


def test_a_subset_scans_only_those_keywords():
    to_scan, unknown = resolve_scan_keywords(ACTIVE, ["local law 97 architects"])
    assert to_scan == ["local law 97 architects"]
    assert unknown == []


def test_matching_is_case_and_whitespace_insensitive():
    to_scan, unknown = resolve_scan_keywords(ACTIVE, ["  LOCAL LAW 97 Architects "])
    assert to_scan == ["local law 97 architects"]
    assert unknown == []


def test_result_follows_the_clients_keyword_order_not_the_request_order():
    # So the same subset requested two different ways produces identically
    # ordered scans (and identically ordered heatmap cards).
    to_scan, _ = resolve_scan_keywords(ACTIVE, ["adaptive reuse nyc", "historical preservation architects nyc"])
    assert to_scan == ["historical preservation architects nyc", "adaptive reuse nyc"]


def test_duplicate_requests_are_collapsed():
    to_scan, _ = resolve_scan_keywords(ACTIVE, ["adaptive reuse nyc", "Adaptive Reuse NYC"])
    assert to_scan == ["adaptive reuse nyc"]


def test_unknown_keywords_are_reported_rather_than_silently_dropped():
    # Quietly ignoring one would start a narrower scan than the user asked for.
    to_scan, unknown = resolve_scan_keywords(ACTIVE, ["adaptive reuse nyc", "roof repair"])
    assert to_scan == ["adaptive reuse nyc"]
    assert unknown == ["roof repair"]


def test_a_deactivated_keyword_reads_as_unknown():
    # start_client_scan re-resolves against the CURRENT active set, so a keyword
    # deactivated between enqueue and run drops out instead of being scanned.
    to_scan, unknown = resolve_scan_keywords(["plumber"], ["plumber", "emergency plumber"])
    assert to_scan == ["plumber"]
    assert unknown == ["emergency plumber"]


def test_blank_entries_are_ignored_entirely():
    to_scan, unknown = resolve_scan_keywords(ACTIVE, ["", "   ", "adaptive reuse nyc"])
    assert to_scan == ["adaptive reuse nyc"]
    assert unknown == []


def test_a_request_that_matches_nothing_yields_no_scan():
    # The caller turns this into a 400 / 'no_keywords' rather than scanning all.
    to_scan, unknown = resolve_scan_keywords(ACTIVE, ["roof repair"])
    assert to_scan == []
    assert unknown == ["roof repair"]


# ---------------------------------------------------------------------------
# Wiring: the rule has to actually reach the two paths that spend money and
# raise client-facing alerts, not just exist as a helper.
# ---------------------------------------------------------------------------
def _capture_hooks(monkeypatch):
    """Record which completion hooks fire, without touching the DB."""
    from services import maps_analyzer, maps_report

    fired = []
    monkeypatch.setattr(maps_report, "enqueue_maps_report", lambda scan_id: fired.append(("report", scan_id)))
    monkeypatch.setattr(maps_analyzer, "enqueue_maps_analyze", lambda scan_id: fired.append(("analyze", scan_id)))
    return fired


def test_a_scheduled_scan_gets_the_report_and_analyzer_hooks(monkeypatch):
    from services import local_dominator

    fired = _capture_hooks(monkeypatch)
    local_dominator.enqueue_completion_hooks("scan-1", "scheduled")
    assert [f[0] for f in fired] == ["report", "analyze"]


def test_a_one_off_scan_gets_neither_hook(monkeypatch):
    # No LLM report spend and no Drive doc for a scan outside the client's
    # record, and no alerts off a possibly-partial keyword set.
    from services import local_dominator

    fired = _capture_hooks(monkeypatch)
    local_dominator.enqueue_completion_hooks("scan-1", "manual")
    assert fired == []


def test_parallel_test_scans_still_get_neither_hook(monkeypatch):
    # Pre-existing §7 behaviour, now enforced by the shared rule.
    from services import local_dominator

    fired = _capture_hooks(monkeypatch)
    local_dominator.enqueue_completion_hooks("scan-1", "parallel_test")
    assert fired == []


class _ScanRowSupabase:
    """Returns one maps_scans row for the analyzer's opening lookup."""

    def __init__(self, row):
        self.row = row
        self.results_read = False

    def table(self, name):
        if name == "maps_scan_results":
            self.results_read = True
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": [self.row] if self.row else []})


def test_analyze_scan_refuses_a_one_off(monkeypatch):
    # analyze_scan is callable directly (not only via the hook), so it defends
    # itself — and bails BEFORE reading results, i.e. before any work.
    from services import maps_analyzer

    supa = _ScanRowSupabase(
        {"id": "s1", "client_id": "c1", "status": "complete",
         "completed_at": "2026-08-01T00:00:00Z", "trigger": "manual"}
    )
    monkeypatch.setattr(maps_analyzer, "get_supabase", lambda: supa)
    out = maps_analyzer.analyze_scan("s1")
    assert out == {"skipped": "scan_not_in_reporting", "opened": 0}
    assert supa.results_read is False


# ---------------------------------------------------------------------------
# Scoped "Clear all" — the two lists are cleared from different screens, so
# neither may take the other's history with it.
# ---------------------------------------------------------------------------
class _ClearSupabase:
    """Enough of the query builder for clear_scans: a filtered select of scan
    rows, then a delete keyed on explicit ids."""

    def __init__(self, rows):
        self.rows = rows
        self.deleted_ids = None
        self._mode = None

    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, column, values):
        if self._mode == "delete":
            assert column == "id", "delete must be keyed on resolved ids"
            self.deleted_ids = list(values)
        return self

    def execute(self):
        data = [] if self._mode == "delete" else self.rows
        return type("R", (), {"data": data})


_MIXED = [
    {"id": "s1", "trigger": "scheduled"},
    {"id": "m1", "trigger": "manual"},
    {"id": "s2", "trigger": "scheduled"},
    {"id": "m2", "trigger": "manual"},
]


def _clear(monkeypatch, scope, rows=_MIXED):
    import asyncio
    from uuid import uuid4

    from routers import maps as maps_router

    supa = _ClearSupabase(rows)
    monkeypatch.setattr(maps_router, "get_supabase", lambda: supa)
    out = asyncio.run(maps_router.clear_scans(uuid4(), scope=scope, auth={}))
    return out, supa


def test_clearing_scheduled_scans_leaves_one_offs_alone(monkeypatch):
    out, supa = _clear(monkeypatch, "scheduled")
    assert supa.deleted_ids == ["s1", "s2"]
    assert out == {"deleted": 2}


def test_clearing_one_offs_leaves_the_reporting_history_alone(monkeypatch):
    out, supa = _clear(monkeypatch, "manual")
    assert supa.deleted_ids == ["m1", "m2"]
    assert out == {"deleted": 2}


def test_scope_all_clears_both(monkeypatch):
    out, supa = _clear(monkeypatch, "all")
    assert supa.deleted_ids == ["s1", "m1", "s2", "m2"]
    assert out == {"deleted": 4}


def test_nothing_matching_issues_no_delete_at_all(monkeypatch):
    # Guard against a no-op clear falling through to an unfiltered delete.
    out, supa = _clear(monkeypatch, "manual", rows=[{"id": "s1", "trigger": "scheduled"}])
    assert supa.deleted_ids is None
    assert out == {"deleted": 0}


def test_an_unknown_scope_is_rejected(monkeypatch):
    import asyncio
    from uuid import uuid4

    from fastapi import HTTPException

    from routers import maps as maps_router

    supa = _ClearSupabase(_MIXED)
    monkeypatch.setattr(maps_router, "get_supabase", lambda: supa)
    try:
        asyncio.run(maps_router.clear_scans(uuid4(), scope="everything", auth={}))
    except HTTPException as exc:
        assert exc.status_code == 400 and exc.detail == "invalid_scope"
    else:
        raise AssertionError("expected a 400")
    assert supa.deleted_ids is None
