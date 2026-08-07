"""Unit tests for the Local Dominator geo-grid pure helpers (no I/O)."""

from __future__ import annotations

from services import local_dominator


# ---------------------------------------------------------------------------
# summarize_grid
# ---------------------------------------------------------------------------
def test_summarize_grid_counts_and_average():
    # Raw ranks are 0-INDEXED (0 = 1st place). Not-ranked pins are negative (-1)
    # or null. All metrics are reported 1-based (display = raw + 1).
    content = [
        [0, 1, 2],
        [3, None, 10],
        [-1, -1, 4],
    ]
    s = local_dominator.summarize_grid(content)
    assert s["total_pins"] == 9
    assert s["found_pins"] == 6          # raw 0,1,2,3,10,4 → display 1,2,3,4,11,5
    assert s["top3_pins"] == 3           # display 1,2,3 (raw 0,1,2)
    assert s["top10_pins"] == 5          # display 1,2,3,4,5 (raw 10→11 excluded)
    assert s["computed_average"] == round((1 + 2 + 3 + 4 + 11 + 5) / 6, 2)


def test_to_display_grid_is_one_based_with_nulls():
    content = [[0, 1, -1], [None, 9, 2]]
    assert local_dominator.to_display_grid(content) == [[1, 2, None], [None, 10, 3]]


def test_summarize_grid_empty_and_all_unranked():
    assert local_dominator.summarize_grid([]) == {
        "total_pins": 0, "found_pins": 0, "top3_pins": 0, "top10_pins": 0, "computed_average": None,
    }
    s = local_dominator.summarize_grid([[-1, None], [-1, -1]])
    assert s["total_pins"] == 4 and s["found_pins"] == 0 and s["computed_average"] is None


# ---------------------------------------------------------------------------
# build_scan_request
# ---------------------------------------------------------------------------
def test_build_scan_request_maps_radius_to_grid_params():
    config = {
        "center_lat": 26.0481, "center_lng": -80.1819, "radius_miles": 5,
        "shape": "circle", "google_place_id": "ChIJabc", "resource_category": "googleMaps",
        "serp_device": "desktop",
    }
    body = local_dominator.build_scan_request(config, ["plumber", "emergency plumber"])
    assert body["grid_size"] == 11          # 5 mi @ 1-mile spacing
    assert body["distance"] == 1609         # 1 mile in metres
    assert body["latitude"] == 26.0481 and body["longitude"] == -80.1819
    assert body["shape"] == "square"  # square lattice, masked to a circle in the UI
    assert body["google_place_id"] == "ChIJabc"
    assert body["search_terms"] == ["plumber", "emergency plumber"]
    assert body["resource_category"] == "googleMaps" and body["serp_device"] == "desktop"


def test_build_scan_request_defaults_shape_and_surface():
    config = {
        "center_lat": 1.0, "center_lng": 2.0, "radius_miles": 3,
        "google_place_id": "p", "shape": None, "resource_category": None, "serp_device": None,
    }
    body = local_dominator.build_scan_request(config, ["x"])
    assert body["grid_size"] == 7           # 3 mi
    assert body["shape"] == "square"  # square lattice, masked to a circle in the UI
    assert body["resource_category"] == "googleMaps"
    assert body["serp_device"] == "desktop"



# ---------------------------------------------------------------------------
# resolve_weekday / scan_due — per-client scan scheduling (pure)
# ---------------------------------------------------------------------------
from datetime import date, datetime, timezone  # noqa: E402

from config import settings  # noqa: E402

MON, TUE, THU = 0, 1, 3
UTC = timezone.utc


def test_resolve_weekday_uses_the_config_value():
    assert local_dominator.resolve_weekday(THU) == THU
    assert local_dominator.resolve_weekday(0) == 0
    assert local_dominator.resolve_weekday(6) == 6


def test_resolve_weekday_falls_back_on_unset_or_nonsense():
    default = settings.maps_scan_weekday
    assert local_dominator.resolve_weekday(None) == default
    assert local_dominator.resolve_weekday(7) == default      # out of range
    assert local_dominator.resolve_weekday(-1) == default
    assert local_dominator.resolve_weekday("tue") == default
    # bool is an int subclass — must not be read as weekday 1
    assert local_dominator.resolve_weekday(True) == default


def test_scan_due_on_the_clients_own_weekday():
    # Last scan is recent enough that the overdue catch-up CANNOT fire, so this
    # isolates the weekday rule itself.
    thu, recent = date(2026, 8, 6), date(2026, 8, 2)
    assert thu.weekday() == THU
    assert (thu - recent).days < 7
    assert local_dominator.scan_due(thu, THU, recent, recent) is True
    # ...and NOT on the old global Tuesday, which is the whole point of the fix.
    assert local_dominator.scan_due(date(2026, 8, 4), THU, recent, recent) is False


def test_scan_due_blocks_a_second_scan_the_same_day():
    """The guard that makes a DAILY sweep safe: enqueue_maps_scan only dedupes
    pending/running jobs, so a completed scan would otherwise be re-enqueued on
    the very next tick — 7x the paid scans."""
    tue = date(2026, 8, 4)
    assert local_dominator.scan_due(tue, TUE, tue, tue) is False


def test_scan_due_a_failed_attempt_today_still_blocks():
    """A FAILED attempt is an attempt: without this, a failing provider would be
    retried every 5-minute tick for the rest of the day — one paid attempt per
    tick instead of one per day."""
    tue, prev = date(2026, 8, 4), date(2026, 7, 28)
    # attempted (and failed) today; last good scan a week ago
    assert local_dominator.scan_due(tue, TUE, tue, prev) is False


def test_scan_due_failed_attempt_retries_next_day_not_next_week():
    """A failed Tuesday must not cost the whole week: on Wednesday the last GOOD
    scan is 8 days old, so the catch-up fires a retry — bounded to one/day by
    the attempt guard above."""
    wed = date(2026, 8, 5)
    failed_tue, prev_good = date(2026, 8, 4), date(2026, 7, 28)
    assert local_dominator.scan_due(wed, TUE, failed_tue, prev_good) is True


def test_scan_due_is_quiet_between_weekdays():
    # Wednesday, scanned yesterday on its Tuesday — not due, not yet overdue.
    d, last = date(2026, 8, 5), date(2026, 8, 4)
    assert local_dominator.scan_due(d, TUE, last, last) is False


def test_scan_due_catches_up_when_a_window_was_missed():
    """Per-client catch-up: the Tuesday window was missed entirely (no attempt at
    all), so by Wednesday the last good scan is over a week old and the scan
    must fire rather than silently wait another seven days."""
    last = date(2026, 7, 28)
    assert local_dominator.scan_due(date(2026, 8, 5), TUE, last, last) is True


def test_scan_due_exactly_seven_days_is_on_cadence_not_overdue():
    """The catch-up is STRICTLY more than 7 days. At exactly 7 the client is on
    cadence (the weekday rule handles it); >= would double-fire in the week
    after a weekday change — catch-up on the old day at day 7, then the
    own-weekday rule again the day after."""
    last_tue = date(2026, 8, 4)
    # Client moved Tue -> Wed. The following Tuesday (gap exactly 7): NOT due.
    assert local_dominator.scan_due(date(2026, 8, 11), 2, last_tue, last_tue) is False
    # Wednesday (gap 8): due, and the cadence settles on Wednesday.
    assert local_dominator.scan_due(date(2026, 8, 12), 2, last_tue, last_tue) is True


def test_scan_due_weekday_suppressed_right_after_a_good_scan():
    """A weekday change must not double-scan. Moving Tue -> Thu: the Wednesday
    catch-up fires at day 8, and without suppression the new Thursday weekday
    would fire again the very next day. A good scan within the last 2 days
    holds the weekday rule off; the cadence settles on Thursday a week on."""
    caught_up_wed = date(2026, 8, 12)
    # Thursday, one day after the catch-up scan: suppressed.
    assert local_dominator.scan_due(date(2026, 8, 13), THU, caught_up_wed, caught_up_wed) is False
    # The following Thursday (gap 8 -> catch-up + weekday): due.
    assert local_dominator.scan_due(date(2026, 8, 20), THU, caught_up_wed, caught_up_wed) is True


def test_scan_due_cancelled_scan_is_respected_not_retried():
    """A user-cancelled scheduled scan counts as this week's scan (it is in the
    non-failed map), so it must NOT trigger a next-day catch-up retry."""
    wed = date(2026, 8, 5)
    cancelled_tue = date(2026, 8, 4)
    assert local_dominator.scan_due(wed, TUE, cancelled_tue, cancelled_tue) is False


def test_scan_due_never_scanned_waits_for_its_weekday():
    assert local_dominator.scan_due(date(2026, 8, 5), TUE, None, None) is False   # Wed
    assert local_dominator.scan_due(date(2026, 8, 4), TUE, None, None) is True    # Tue


def test_scan_history_splits_attempts_from_good_scans():
    """'failed' rows count as attempts only; anything else (complete, polling,
    cancelled) is also a good scan. The newest UTC timestamp wins per client
    (timestamps, not dates, so the caller can convert to each client's local
    date)."""
    rows = [
        {"client_id": "c1", "created_at": "2026-08-04 08:00:00+00", "status": "failed"},
        {"client_id": "c1", "created_at": "2026-07-28 08:00:00+00", "status": "complete"},
        {"client_id": "c2", "created_at": "2026-08-04 08:00:00+00", "status": "cancelled"},
    ]
    fake = _FakeSupabase(configs=[], scans=rows, keywords_by_client={})
    attempts, good = local_dominator._scan_history(fake, datetime(2026, 8, 5, tzinfo=UTC))
    assert attempts == {"c1": datetime(2026, 8, 4, 8, tzinfo=UTC), "c2": datetime(2026, 8, 4, 8, tzinfo=UTC)}
    assert good == {"c1": datetime(2026, 7, 28, 8, tzinfo=UTC), "c2": datetime(2026, 8, 4, 8, tzinfo=UTC)}


# ---------------------------------------------------------------------------
# enqueue_due_maps_scans — per-client weekday routing + starvation reporting
# ---------------------------------------------------------------------------
class _FakeQuery:
    """Minimal chainable stub of the supabase-py table query builder."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def gte(self, *_a, **_kw):
        return self

    def order(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def execute(self):
        return type("Res", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, configs, scans, keywords_by_client):
        self._configs = configs
        self._scans = scans
        self._keywords = keywords_by_client
        self.keyword_lookups = []

    def table(self, name):
        if name == "maps_scan_configs":
            return _FakeQuery(self._configs)
        if name == "maps_scans":
            return _FakeQuery(self._scans)
        if name == "maps_keywords":
            # Keyword lookups happen in config order, only for due clients.
            client_id = self._due_order.pop(0)
            self.keyword_lookups.append(client_id)
            return _FakeQuery(self._keywords.get(client_id, []))
        raise AssertionError(f"unexpected table {name}")


def _cfg(client_id, weekday, **overrides):
    """A complete weekly config row; overrides let a test blank out fields."""
    row = {
        "client_id": client_id, "weekday": weekday,
        "google_place_id": "p", "center_lat": 1.0, "center_lng": 2.0,
    }
    row.update(overrides)
    return row


def _run_sweep(monkeypatch, configs, scans, keywords, due_order, today, hour=9, tz_map=None):
    fake = _FakeSupabase(configs, scans, keywords)
    fake._due_order = list(due_order)
    monkeypatch.setattr(local_dominator, "get_supabase", lambda: fake)

    # Timezone resolution is stubbed so these sweep tests stay in the UTC frame
    # (None → UTC); tz_map lets a test place a client in a specific zone.
    import services.gbp_timezone as _gbp_tz
    monkeypatch.setattr(
        _gbp_tz, "resolve_client_timezone",
        lambda client_id, *a, **k: (tz_map or {}).get(client_id),
    )

    enqueued = []
    monkeypatch.setattr(
        local_dominator, "enqueue_maps_scan",
        lambda client_id, trigger=None: enqueued.append(client_id) or True,
    )
    starved = []
    monkeypatch.setattr(local_dominator, "_notify_starved_configs", starved.extend)

    class _FixedDatetime(local_dominator.datetime):
        @classmethod
        def now(cls, tz=None):
            return local_dominator.datetime(today.year, today.month, today.day, hour, tzinfo=tz)

    monkeypatch.setattr(local_dominator, "datetime", _FixedDatetime)
    count = local_dominator.enqueue_due_maps_scans()
    return count, enqueued, starved, fake


def test_enqueue_due_maps_scans_routes_each_client_to_its_own_weekday(monkeypatch):
    """The fix: a client set to Thursday must scan on Thursday, and the Tuesday
    client must be left alone that day.

    Both clients' last scans are <7 days old so the overdue catch-up cannot fire
    — this must pass on the weekday routing alone."""
    thursday = date(2026, 8, 6)
    count, enqueued, _starved, fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("tue-client", TUE), _cfg("thu-client", THU)],
        scans=[{"client_id": "tue-client", "created_at": "2026-08-04 08:00:00+00"},
               {"client_id": "thu-client", "created_at": "2026-08-02 08:00:00+00"}],
        keywords={"thu-client": [{"id": "k1"}]},
        due_order=["thu-client"],
        today=thursday,
    )
    assert count == 1
    assert enqueued == ["thu-client"]
    assert fake.keyword_lookups == ["thu-client"]  # the Tuesday client isn't touched


def test_enqueue_due_maps_scans_does_not_rescan_the_same_day(monkeypatch):
    """A daily sweep must not re-enqueue a client that already scanned today."""
    tuesday = date(2026, 8, 4)
    count, enqueued, _starved, _fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("c1", TUE)],
        scans=[{"client_id": "c1", "created_at": "2026-08-04 08:00:00+00"}],
        keywords={"c1": [{"id": "k1"}]},
        due_order=[],
        today=tuesday,
    )
    assert count == 0
    assert enqueued == []


def test_enqueue_due_maps_scans_reports_starvation_on_the_clients_weekday(monkeypatch):
    """A client with an active config but no keywords is skipped AND surfaced --
    it used to stop scanning silently."""
    tuesday = date(2026, 8, 4)
    count, enqueued, starved, _fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("no-kw", TUE)],
        scans=[{"client_id": "no-kw", "created_at": "2026-07-28 08:00:00+00"}],
        keywords={},
        due_order=["no-kw"],
        today=tuesday,
    )
    assert count == 0
    assert enqueued == []
    assert starved == ["no-kw"]


def test_enqueue_due_maps_scans_does_not_renotify_starvation_on_catch_up_days(monkeypatch):
    """A starved client is permanently overdue, so it comes up due every day.
    It must only be REPORTED on its own weekday, not logged daily forever."""
    wednesday = date(2026, 8, 5)
    count, enqueued, starved, _fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("no-kw", TUE)],
        scans=[{"client_id": "no-kw", "created_at": "2026-06-23 08:00:00+00"}],
        keywords={},
        due_order=["no-kw"],
        today=wednesday,
    )
    assert count == 0
    assert enqueued == []
    assert starved == []   # due (overdue) but NOT re-reported off its weekday


def test_enqueue_due_maps_scans_unset_weekday_uses_the_global_default(monkeypatch):
    """A config with no weekday must still scan, on settings.maps_scan_weekday.

    Last scan is 3 days old so the catch-up cannot fire — this must pass on the
    global-default weekday alone."""
    from datetime import timedelta

    default = settings.maps_scan_weekday
    # Pick a real date whose weekday matches the configured global default.
    today = next(
        d for d in (date(2026, 8, 3) + timedelta(days=i) for i in range(7))
        if d.weekday() == default
    )
    last = (today - timedelta(days=3)).isoformat()
    count, enqueued, _starved, _fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("c1", None)],
        scans=[{"client_id": "c1", "created_at": f"{last} 08:00:00+00"}],
        keywords={"c1": [{"id": "k1"}]},
        due_order=["c1"],
        today=today,
    )
    assert count == 1
    assert enqueued == ["c1"]


def test_enqueue_due_maps_scans_skips_incomplete_config_without_enqueue(monkeypatch):
    """A config saved before Place ID / center were filled in would make the scan
    job fail BEFORE a maps_scans row exists — nothing records the attempt, so a
    daily sweep would re-enqueue the failing job every tick. It must be skipped
    up front: no enqueue, no keyword lookup."""
    tuesday = date(2026, 8, 4)
    count, enqueued, starved, fake = _run_sweep(
        monkeypatch,
        configs=[_cfg("half-setup", TUE, google_place_id=None)],
        scans=[],
        keywords={"half-setup": [{"id": "k1"}]},
        due_order=[],   # keyword lookup must never happen
        today=tuesday,
    )
    assert count == 0
    assert enqueued == []
    assert starved == []            # incomplete is not the starved (no-keywords) case
    assert fake.keyword_lookups == []


# ---------------------------------------------------------------------------
# resolve_scan_hour / hour_reached — local-time scan scheduling (pure)
# ---------------------------------------------------------------------------
def test_resolve_scan_hour_uses_the_config_value():
    assert local_dominator.resolve_scan_hour(0) == 0
    assert local_dominator.resolve_scan_hour(6) == 6
    assert local_dominator.resolve_scan_hour(23) == 23


def test_resolve_scan_hour_falls_back_on_unset_or_nonsense():
    default = settings.maps_scan_hour
    assert local_dominator.resolve_scan_hour(None) == default
    assert local_dominator.resolve_scan_hour(24) == default     # out of range
    assert local_dominator.resolve_scan_hour(-1) == default
    assert local_dominator.resolve_scan_hour("8") == default
    # bool is an int subclass — must not be read as hour 1
    assert local_dominator.resolve_scan_hour(True) == default


def test_hour_reached():
    assert local_dominator.hour_reached(datetime(2026, 8, 4, 7, tzinfo=UTC), 8) is False
    assert local_dominator.hour_reached(datetime(2026, 8, 4, 8, tzinfo=UTC), 8) is True
    assert local_dominator.hour_reached(datetime(2026, 8, 4, 8, tzinfo=UTC), 6) is True


def test_enqueue_due_maps_scans_holds_until_the_local_hour(monkeypatch):
    """A client is not scanned before its local scan_hour, then is once reached.
    The sweep runs every cycle, so 'too early' must simply wait, not lose the day."""
    tuesday = date(2026, 8, 4)   # weekday TUE
    common = dict(
        configs=[_cfg("c1", TUE, scan_hour=8)],
        scans=[{"client_id": "c1", "created_at": "2026-07-28 08:00:00+00"}],
        keywords={"c1": [{"id": "k1"}]},
        today=tuesday,
    )
    # 07:00 local — before the 8am scan hour: not due (no keyword lookup either).
    count, enqueued, _s, _f = _run_sweep(monkeypatch, due_order=[], hour=7, **common)
    assert count == 0 and enqueued == []
    # 08:00 local — due.
    count, enqueued, _s, _f = _run_sweep(monkeypatch, due_order=["c1"], hour=8, **common)
    assert count == 1 and enqueued == ["c1"]


def test_enqueue_due_maps_scans_honors_client_timezone(monkeypatch):
    """weekday + scan_hour are the CLIENT's local time. A client in
    America/New_York set to Tuesday 8am is due at UTC 13:00 (= 9am EDT) but not
    at UTC 11:00 (= 7am EDT) — the whole point of local-time scheduling."""
    tuesday = date(2026, 8, 4)
    common = dict(
        configs=[_cfg("nyc", TUE, scan_hour=8)],
        scans=[{"client_id": "nyc", "created_at": "2026-07-28 12:00:00+00"}],
        keywords={"nyc": [{"id": "k1"}]},
        today=tuesday,
        tz_map={"nyc": "America/New_York"},
    )
    # UTC 11:00 = 07:00 EDT — before 8am local: not due.
    count, enqueued, _s, _f = _run_sweep(monkeypatch, due_order=[], hour=11, **common)
    assert count == 0 and enqueued == []
    # UTC 13:00 = 09:00 EDT — past 8am local: due.
    count, enqueued, _s, _f = _run_sweep(monkeypatch, due_order=["nyc"], hour=13, **common)
    assert count == 1 and enqueued == ["nyc"]
