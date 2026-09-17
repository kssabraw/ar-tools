"""Unit tests for Client Reporting Phase 5 pure helpers
(services/client_report_schedule): recipient parsing + delivery email format.
The cadence clock is brand_schedule.compute_next_run_at (tested with that
module); scheduler/delivery I/O paths are exercised on the deployed worker."""

from datetime import date

from services.client_report import PERIOD_CHOICES, period_start_for
from services.client_report_schedule import (
    _default_settings,
    format_report_email,
    parse_recipients,
)


def test_parse_recipients_string_and_list():
    assert parse_recipients("am@agency.com, ops@agency.com") == ["am@agency.com", "ops@agency.com"]
    assert parse_recipients(["am@agency.com", "  ops@agency.com "]) == ["am@agency.com", "ops@agency.com"]


def test_parse_recipients_dedupes_and_drops_junk():
    assert parse_recipients("am@agency.com, AM@agency.com, , not-an-email, x@y.z") == [
        "am@agency.com", "x@y.z",
    ]
    assert parse_recipients(None) == []
    assert parse_recipients(42) == []


def test_format_report_email():
    subject, body = format_report_email("Acme Roofing", "Acme Roofing — SEO Report (2026-07-06)", "https://signed/url")
    assert subject == "[Acme Roofing] SEO report ready"
    assert "Acme Roofing — SEO Report (2026-07-06)" in body
    assert "https://signed/url" in body
    assert body.endswith("— AR Tools")


def test_format_report_email_no_client_no_link():
    subject, body = format_report_email(None, "Report", None)
    assert subject == "SEO report ready"
    assert "http" not in body


def test_period_start_for_day_tokens():
    today = date(2026, 7, 6)
    assert period_start_for("30d", None, today) == date(2026, 6, 6)
    assert period_start_for("60d", None, today) == date(2026, 5, 7)
    assert period_start_for("90d", None, today) == date(2026, 4, 7)
    assert period_start_for("120d", None, today) == date(2026, 3, 8)
    assert period_start_for("1y", None, today) == date(2025, 7, 6)
    # No/unknown token → None (builder default window).
    assert period_start_for(None, None, today) is None
    assert period_start_for("bogus", None, today) is None


def test_default_settings_extra_reports_off():
    # AI Visibility + Local Rank (Maps) scheduling are opt-in — a fresh client's
    # schedule never emits either standalone report until its toggle is turned on.
    defaults = _default_settings("client-1")
    assert defaults["ai_visibility_enabled"] is False
    assert defaults["maps_enabled"] is False


def test_period_start_for_campaign_start():
    today = date(2026, 7, 6)
    # 'all' anchors on the campaign start...
    assert period_start_for("all", date(2025, 2, 14), today) == date(2025, 2, 14)
    # ...and falls back to the default window when created_at is unknown.
    assert period_start_for("all", None, today) == date(2026, 6, 6)
    # every advertised choice resolves without raising
    for token in PERIOD_CHOICES:
        period_start_for(token, date(2025, 1, 1), today)


# ---------------------------------------------------------------------------
# Freshness guard: a scheduled client-facing report is HELD when rank data is
# stale, and the team is warned instead of shipping stale numbers.
# ---------------------------------------------------------------------------
def test_stale_client_report_is_held_and_warned(monkeypatch):
    import services.client_report_schedule as crs

    class _Builder:
        def __init__(self, table):
            self.table = table
            self._is_due_query = False

        def select(self, *_a, **_k):
            return self

        def neq(self, *_a, **_k):
            return self

        def lte(self, *_a, **_k):
            self._is_due_query = True
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def update(self, *_a, **_k):
            return self

        def execute(self):
            if self.table == "client_report_settings" and self._is_due_query:
                return type("R", (), {"data": [{
                    "client_id": "c1", "cadence": "monthly", "day_of_week": None,
                    "day_of_month": 1, "hour_utc": 8, "period": "auto",
                    "ai_visibility_enabled": True, "maps_enabled": True,
                    "last_run_at": None, "next_run_at": "2000-01-01T00:00:00+00:00",
                }]})()
            if self.table == "rank_freshness_status":
                return type("R", (), {"data": [{"status": "stale"}]})()
            return type("R", (), {"data": []})()

    class _Fake:
        def table(self, name):
            return _Builder(name)

    monkeypatch.setattr(crs, "get_supabase", lambda: _Fake())

    enqueue_calls: list = []
    monkeypatch.setattr(
        "services.client_report.enqueue_client_report",
        lambda *a, **k: enqueue_calls.append((a, k)),
    )
    emitted: list = []
    monkeypatch.setattr(
        "services.notifications.emit",
        lambda **k: emitted.append(k),
    )

    crs.enqueue_due_report_schedules()

    # Nothing was enqueued for the stale client…
    assert enqueue_calls == []
    # …and the team was warned exactly once, with the hold kind.
    assert len(emitted) == 1
    assert emitted[0]["kind"] == "report_held_stale_data"
    assert emitted[0]["severity"] == "warning"


def test_stale_rank_holds_combined_but_not_standalone_ai_report(monkeypatch):
    # #4: a rank-data stall holds only the COMBINED report; the standalone AI
    # Visibility report (separate data source) still ships when the client tracks it.
    import services.client_report_schedule as crs

    class _B:
        def __init__(self, table):
            self.table = table
            self._due = False

        def select(self, *_a, **_k):
            return self

        def neq(self, *_a, **_k):
            return self

        def lte(self, *_a, **_k):
            self._due = True
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def update(self, *_a, **_k):
            return self

        def execute(self):
            D = lambda d: type("R", (), {"data": d})()
            if self.table == "client_report_settings" and self._due:
                return D([{
                    "client_id": "c1", "cadence": "monthly", "day_of_week": None,
                    "day_of_month": 1, "hour_utc": 8, "period": "auto",
                    "ai_visibility_enabled": True, "maps_enabled": False,
                    "last_run_at": None, "next_run_at": "2000-01-01T00:00:00+00:00",
                }])
            if self.table == "rank_freshness_status":
                return D([{"status": "stale"}])
            if self.table == "brand_tracked_keywords":   # client tracks AI visibility
                return D([{"id": "b1"}])
            return D([])  # client_reports pending check → empty, maps_keywords → empty

    class _Fake:
        def table(self, name):
            return _B(name)

    monkeypatch.setattr(crs, "get_supabase", lambda: _Fake())
    calls: list = []
    monkeypatch.setattr("services.client_report.enqueue_client_report",
                        lambda *a, **k: calls.append((a, k)))
    emitted: list = []
    monkeypatch.setattr("services.notifications.emit", lambda **k: emitted.append(k))

    crs.enqueue_due_report_schedules()

    report_types = [a[1] for (a, _k) in calls]
    assert "ai_visibility" in report_types          # standalone AI report NOT held
    assert "monthly" not in report_types and "weekly" not in report_types  # combined held
    assert any(e["kind"] == "report_held_stale_data" for e in emitted)
