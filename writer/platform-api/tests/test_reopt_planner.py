"""Unit tests for the reoptimization planner pure helpers (no network)."""

from __future__ import annotations

from services import reopt_planner


CLIENT = "11111111-1111-1111-1111-111111111111"


def _rankability_item(**over):
    base = {
        "keyword": "emergency plumber",
        "has_snapshot": True,
        "score": 70,
        "band": "Easy",
        "priority": 5000.0,
        "client_rank": 12,
        "est_value": 1200,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# build_actions
# ---------------------------------------------------------------------------
def test_drop_outranks_everything_and_deindex_is_critical():
    drops = [
        {"keyword": "blocked drain", "alert_type": "drop", "message": "Fell 8 spots."},
        {"keyword": "burst pipe", "alert_type": "deindexed", "message": "Page deindexed."},
    ]
    actions = reopt_planner.build_actions(CLIENT, drops, [], {})
    assert len(actions) == 2
    # deindex sorts above an ordinary drop, and is critical with the indexing CTA.
    first = actions[0]
    assert first["keyword"] == "burst pipe"
    assert first["kind"] == "rank_drop"
    assert first["severity"] == "critical"
    assert "URL Inspection" in first["recommendation"]
    assert actions[1]["severity"] == "warning"
    assert all(a["cta_path"] == f"clients/{CLIENT}/rankings" for a in actions)


def test_quick_win_striking_distance_reoptimizes_else_creates():
    items = [
        _rankability_item(keyword="hot water repair", client_rank=8, priority=9000.0),
        _rankability_item(keyword="gas fitting", client_rank=None, priority=8000.0),
    ]
    actions = reopt_planner.build_actions(CLIENT, [], items, {})
    by_kw = {a["keyword"]: a for a in actions}
    assert by_kw["hot water repair"]["cta_label"] == "Reoptimize"
    assert "#8" in by_kw["hot water repair"]["recommendation"]
    assert by_kw["gas fitting"]["cta_label"] == "Create page"
    assert all(a["cta_path"] == f"clients/{CLIENT}/local-seo" for a in actions)


def test_quick_win_excludes_low_score_wrong_band_and_no_snapshot():
    items = [
        _rankability_item(keyword="a", band="Hard"),                 # wrong band
        _rankability_item(keyword="b", score=40),                    # below min score
        _rankability_item(keyword="c", has_snapshot=False, score=None, band=None),  # no snapshot
        _rankability_item(keyword="d", score=80, band="Moderate"),   # kept
    ]
    actions = reopt_planner.build_actions(CLIENT, [], items, {})
    kws = {a["keyword"] for a in actions}
    assert kws == {"d"}


def test_drop_supersedes_quick_win_for_same_keyword():
    drops = [{"keyword": "Emergency Plumber", "alert_type": "drop", "message": "Dropped."}]
    items = [_rankability_item(keyword="emergency plumber")]
    actions = reopt_planner.build_actions(CLIENT, drops, items, {})
    kinds = {a["keyword"].lower(): a["kind"] for a in actions}
    assert kinds == {"emergency plumber": "rank_drop"}  # case-insensitive dedup


def test_gsc_cannibalization_and_hidden_wins_mapped():
    gsc = {
        "cannibalization": [{"query": "drain cleaning", "page_count": 3, "total_impressions": 4200}],
        "hidden_wins": [{"keyword": "leak detection", "position": 14.0, "impressions": 300}],
    }
    actions = reopt_planner.build_actions(CLIENT, [], [], gsc)
    by_kind = {a["kind"]: a for a in actions}
    assert by_kind["cannibalization"]["keyword"] == "drain cleaning"
    assert "3 pages" in by_kind["cannibalization"]["diagnosis"]
    assert by_kind["cannibalization"]["cta_path"] == f"clients/{CLIENT}/gsc-research"
    assert by_kind["opportunity"]["keyword"] == "leak detection"
    assert "page 2" in by_kind["opportunity"]["diagnosis"]


def test_hidden_win_skipped_when_already_a_drop():
    drops = [{"keyword": "leak detection", "alert_type": "drop", "message": "Dropped."}]
    gsc = {"hidden_wins": [{"keyword": "leak detection", "position": 14.0, "impressions": 300}]}
    actions = reopt_planner.build_actions(CLIENT, drops, [], gsc)
    assert [a["kind"] for a in actions] == ["rank_drop"]


def test_total_capped():
    drops = [
        {"keyword": f"kw{i}", "alert_type": "drop", "message": "d"} for i in range(40)
    ]
    actions = reopt_planner.build_actions(CLIENT, drops, [], {})
    assert len(actions) == reopt_planner.TOTAL_MAX


def test_ordering_drops_then_cannibal_then_quick_then_hidden():
    drops = [{"keyword": "d1", "alert_type": "drop", "message": "x"}]
    items = [_rankability_item(keyword="q1", priority=10.0)]
    gsc = {
        "cannibalization": [{"query": "c1", "page_count": 2, "total_impressions": 10}],
        "hidden_wins": [{"keyword": "h1", "position": 15.0, "impressions": 5}],
    }
    actions = reopt_planner.build_actions(CLIENT, drops, items, gsc)
    order = [a["keyword"] for a in actions]
    assert order[0] == "d1"          # drop (1000) first
    assert order.index("c1") < order.index("q1")  # cannibal (800) before low-priority quick win
    assert order[-1] == "h1"         # hidden win (impressions=5) last


def test_high_value_quick_win_never_leapfrogs_a_drop():
    # A huge-priority quick win must still sort below an ordinary drop (strict tiers).
    drops = [{"keyword": "d1", "alert_type": "drop", "message": "x"}]
    items = [_rankability_item(keyword="q1", priority=999_999.0, est_value=999_999)]
    actions = reopt_planner.build_actions(CLIENT, drops, items, {})
    assert actions[0]["keyword"] == "d1"
    assert actions[0]["sort"] > actions[1]["sort"]


def test_cannibalization_rows_rank_by_impressions():
    gsc = {
        "cannibalization": [
            {"query": "low", "page_count": 2, "total_impressions": 100},
            {"query": "high", "page_count": 2, "total_impressions": 9000},
        ],
    }
    actions = reopt_planner.build_actions(CLIENT, [], [], gsc)
    assert [a["keyword"] for a in actions] == ["high", "low"]


# ---------------------------------------------------------------------------
# summarize_plan
# ---------------------------------------------------------------------------
def test_summarize_empty():
    out = reopt_planner.summarize_plan([])
    assert out["severity"] == "info"
    assert "healthy" in out["summary"]


def test_summarize_counts_and_severity():
    actions = [
        {"kind": "rank_drop", "severity": "critical"},
        {"kind": "rank_drop", "severity": "warning"},
        {"kind": "quick_win", "severity": "info"},
        {"kind": "cannibalization", "severity": "warning"},
        {"kind": "opportunity", "severity": "info"},
    ]
    out = reopt_planner.summarize_plan(actions)
    assert out["severity"] == "critical"
    assert "2 drops to fix" in out["summary"]
    assert "1 quick win" in out["summary"]
    assert "2 other opportunities" in out["summary"]


# ---------------------------------------------------------------------------
# _should_store (empty-plan dedup)
# ---------------------------------------------------------------------------
def test_should_store_nonempty_always():
    assert reopt_planner._should_store(3, None) is True
    assert reopt_planner._should_store(3, 0) is True
    assert reopt_planner._should_store(3, 5) is True


def test_should_store_first_empty_when_no_prior():
    assert reopt_planner._should_store(0, None) is True   # record the first empty


def test_should_store_records_transition_to_empty():
    assert reopt_planner._should_store(0, 2) is True       # actions cleared → store


def test_should_skip_steady_state_empty():
    assert reopt_planner._should_store(0, 0) is False      # empty after empty → skip


def test_summarize_singular_plurals():
    out = reopt_planner.summarize_plan([
        {"kind": "rank_drop", "severity": "warning"},
        {"kind": "quick_win", "severity": "info"},
        {"kind": "opportunity", "severity": "info"},
    ])
    assert "1 drop to fix" in out["summary"]
    assert "1 quick win" in out["summary"]
    assert "1 other opportunity" in out["summary"]
    assert out["severity"] == "warning"


def test_summarize_counts_maps_issues():
    out = reopt_planner.summarize_plan([
        {"kind": "maps_decline", "severity": "critical"},
        {"kind": "maps_competitor", "severity": "warning"},
        {"kind": "maps_weak_area", "severity": "info"},
    ])
    assert "3 local-pack issues" in out["summary"]
    assert out["severity"] == "critical"


# ---------------------------------------------------------------------------
# build_maps_actions
# ---------------------------------------------------------------------------
def test_maps_lost_pack_is_critical_and_top_of_band():
    alerts = [
        {"keyword": "plumber", "alert_type": "coverage_drop", "message": "Coverage fell."},
        {"keyword": "plumber", "alert_type": "lost_pack", "message": "Fell out of the pack."},
    ]
    actions = reopt_planner.build_maps_actions(CLIENT, alerts, [])
    first = actions[0]
    assert first["kind"] == "maps_decline"
    assert first["severity"] == "critical"
    assert "out of the local pack" in first["recommendation"]
    assert all(a["source"] == "maps" for a in actions)
    assert first["sort"] > actions[1]["sort"]


def test_maps_competitor_surge_kind_and_cta():
    alerts = [{"keyword": "roofing", "alert_type": "competitor_surge", "message": "Comp surged."}]
    actions = reopt_planner.build_maps_actions(CLIENT, alerts, [])
    assert actions[0]["kind"] == "maps_competitor"
    assert actions[0]["cta_path"] == f"clients/{CLIENT}/maps"
    assert "GBP" in actions[0]["recommendation"]


def test_maps_area_decline_labels_sector():
    alerts = [{"keyword": "roofing", "alert_type": "area_decline", "sector": "NE", "message": "Weak NE."}]
    actions = reopt_planner.build_maps_actions(CLIENT, alerts, [])
    assert "(northeast)" in actions[0]["keyword"]


def test_maps_weak_area_creates_location_page():
    weak = [{"city": "Inner West", "admin_area": "NSW", "pins": 6}]
    actions = reopt_planner.build_maps_actions(CLIENT, [], weak)
    a = actions[0]
    assert a["kind"] == "maps_weak_area"
    assert a["cta_path"] == f"clients/{CLIENT}/local-seo"
    assert "Inner West" in a["recommendation"]
    assert "6 grid pins" in a["diagnosis"]


def test_maps_weak_area_capped():
    weak = [{"city": f"City{i}", "pins": i} for i in range(20)]
    actions = reopt_planner.build_maps_actions(CLIENT, [], weak)
    assert len(actions) == reopt_planner.MAPS_WEAK_AREA_MAX


def test_maps_solv_drop_emits_action_at_top_of_band():
    solv = {"from_pct": 40.0, "to_pct": 22.0, "delta_pct": 18.0, "top_gainer": "Ace Plumbing"}
    alerts = [{"keyword": "plumber", "alert_type": "lost_pack", "message": "Out of the pack."}]
    actions = reopt_planner.build_maps_actions(CLIENT, alerts, [], solv_drop=solv)
    solv_action = next(a for a in actions if a["kind"] == "maps_solv_drop")
    assert "40.0% to 22.0%" in solv_action["diagnosis"]
    assert "Ace Plumbing" in solv_action["diagnosis"]
    assert solv_action["cta_path"] == f"clients/{CLIENT}/maps"
    # lost_pack (critical) still sorts above the SoLV drop within the Maps band.
    lost = next(a for a in actions if a["kind"] == "maps_decline")
    assert lost["sort"] > solv_action["sort"]


def test_maps_solv_drop_absent_when_no_signal():
    actions = reopt_planner.build_maps_actions(CLIENT, [], [], solv_drop=None)
    assert not any(a["kind"] == "maps_solv_drop" for a in actions)


# ---------------------------------------------------------------------------
# build_brand_action
# ---------------------------------------------------------------------------
def test_review_action_on_velocity_gap_and_negatives():
    gap = {"velocity": 1.0, "competitor_velocity": 4.0, "behind": 3.0, "recent_negatives": 2}
    actions = reopt_planner.build_review_action(CLIENT, gap)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "review_gap" and a["source"] == "maps"
    assert a["severity"] == "warning"          # recent negatives → warning
    assert "trails competitors" in a["diagnosis"]
    assert a["cta_path"] == f"clients/{CLIENT}/maps"


def test_review_action_empty_when_no_gap():
    assert reopt_planner.build_review_action(CLIENT, None) == []


def test_relevance_action_lists_gaps():
    gap = {"keyword": "plumber", "gaps": [
        "your GBP category isn't the service (2 competitors' are)",
        "your GBP links to a page that isn't about the service",
    ]}
    actions = reopt_planner.build_relevance_action(CLIENT, gap)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "local_relevance" and a["source"] == "maps"
    assert "category isn't the service" in a["diagnosis"]
    assert "plumber" in a["keyword"]
    assert a["cta_path"] == f"clients/{CLIENT}/maps"


def test_relevance_action_empty_when_no_gaps():
    assert reopt_planner.build_relevance_action(CLIENT, None) == []
    assert reopt_planner.build_relevance_action(CLIENT, {"keyword": "x", "gaps": []}) == []


def test_content_action_on_depth_and_topic_gap():
    gap = {"depth_behind": 600, "topic_gaps": ["pricing", "faq", "warranty"], "keyword": "emergency plumber"}
    actions = reopt_planner.build_content_action(CLIENT, gap)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "content_gap" and a["source"] == "maps"
    assert "600 words thinner" in a["diagnosis"]
    assert "pricing" in a["diagnosis"]
    assert "emergency plumber" in a["keyword"]
    assert a["cta_path"] == f"clients/{CLIENT}/local-seo"


def test_content_action_empty_when_no_gap():
    assert reopt_planner.build_content_action(CLIENT, None) == []
    assert reopt_planner.build_content_action(CLIENT, {"depth_behind": None, "topic_gaps": []}) == []


def test_backlink_action_on_authority_gap():
    gap = {"dr_behind": 25, "referring_domains_behind": 100,
           "competitor_median_dr": 55, "competitor_median_referring_domains": 150}
    actions = reopt_planner.build_backlink_action(CLIENT, gap)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "backlink_gap" and a["source"] == "organic"
    assert "Domain Rating 25 behind" in a["diagnosis"]
    assert "100 fewer referring domains" in a["diagnosis"]
    assert a["cta_path"] == f"clients/{CLIENT}/rankings"


def test_backlink_action_empty_when_no_gap():
    assert reopt_planner.build_backlink_action(CLIENT, None) == []
    assert reopt_planner.build_backlink_action(CLIENT, {"dr_behind": None, "referring_domains_behind": None}) == []


def test_brand_action_emitted_on_decline():
    decline = {"from_impressions": 400, "to_impressions": 200, "delta_pct": 50.0, "weeks": 4}
    actions = reopt_planner.build_brand_action(CLIENT, decline)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "brand_search_decline"
    assert a["source"] == "organic"
    assert "50.0%" in a["diagnosis"]
    assert a["cta_path"] == f"clients/{CLIENT}/rankings"


def test_brand_action_empty_when_no_decline():
    assert reopt_planner.build_brand_action(CLIENT, None) == []


def test_gbp_action_consolidates_gaps():
    audit = {
        "score": 57,
        "competitor_count": 5,
        "gaps": ["Opening hours", "Business description"],
        "category_gaps": ["emergency plumber"],
        "review_gap": {"client": 20, "competitor_median": 120, "deficit": 100},
    }
    actions = reopt_planner.build_gbp_action(CLIENT, audit)
    assert len(actions) == 1
    a = actions[0]
    assert a["kind"] == "gbp_gap" and a["source"] == "maps"
    assert "57/100" in a["diagnosis"]
    assert "emergency plumber" in a["recommendation"]
    assert "100-review gap" in a["recommendation"]
    assert a["cta_path"] == f"clients/{CLIENT}/maps"


def test_gbp_action_empty_when_no_gaps():
    audit = {"score": 100, "competitor_count": 3, "gaps": [], "category_gaps": [], "review_gap": None}
    assert reopt_planner.build_gbp_action(CLIENT, audit) == []
    assert reopt_planner.build_gbp_action(CLIENT, None) == []


def test_brand_action_sorts_in_hidden_band():
    decline = {"from_impressions": 400, "to_impressions": 200, "delta_pct": 50.0, "weeks": 4}
    brand = reopt_planner.build_brand_action(CLIENT, decline)[0]
    # Below a quick win (tier 2) but it's the top of the hidden band (tier 1).
    items = [_rankability_item(keyword="q1", priority=1.0)]
    quick = reopt_planner.build_actions(CLIENT, [], items, {}, cap=None)[0]
    assert quick["sort"] > brand["sort"]


def test_maps_tier_below_cannibal_above_quick():
    # An organic drop and cannibalization outrank a maps decline; a maps decline
    # outranks a quick win and a hidden win (strict tiers).
    drops = [{"keyword": "d1", "alert_type": "drop", "message": "x"}]
    items = [_rankability_item(keyword="q1", priority=10.0)]
    gsc = {"cannibalization": [{"query": "c1", "page_count": 2, "total_impressions": 10}]}
    organic = reopt_planner.build_actions(CLIENT, drops, items, gsc, cap=None)
    maps = reopt_planner.build_maps_actions(
        CLIENT, [{"keyword": "m1", "alert_type": "coverage_drop", "message": "m"}], []
    )
    combined = sorted(organic + maps, key=lambda a: a["sort"], reverse=True)
    order = [a["keyword"] for a in combined]
    assert order.index("d1") < order.index("c1") < order.index("m1") < order.index("q1")


# ---------------------------------------------------------------------------
# _aggregate_weak_areas
# ---------------------------------------------------------------------------
def test_aggregate_weak_areas_dedups_by_place_keeps_most_pins():
    results = [
        {"report_weak_locations": {"weak_areas": [{"city": "Newtown", "admin_area": "NSW", "pins": 2}]}},
        {"report_weak_locations": {"weak_areas": [{"city": "Newtown", "admin_area": "NSW", "pins": 5}]}},
        {"report_weak_locations": {"weak_areas": [{"city": "Glebe", "pins": 3}]}},
    ]
    out = reopt_planner._aggregate_weak_areas(results)
    assert [a["city"] for a in out] == ["Newtown", "Glebe"]  # worst-first by pins
    assert out[0]["pins"] == 5  # kept the higher-pin Newtown entry


def test_aggregate_weak_areas_skips_blank_city_and_handles_empty():
    results = [
        {"report_weak_locations": {"weak_areas": [{"city": "", "pins": 9}]}},
        {"report_weak_locations": None},
        {},
    ]
    assert reopt_planner._aggregate_weak_areas(results) == []


# ---------------------------------------------------------------------------
# enqueue_reopt_plan — in-flight dedup + restart/burst debounce
# ---------------------------------------------------------------------------
class _FakeQuery:
    """Records the filter chain for one async_jobs query and returns a canned
    result decided by the recording _FakeSupabase."""

    def __init__(self, supa, op):
        self._supa = supa
        self._op = op  # "select" or "insert"
        self.filters: dict = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.filters[col] = list(vals)
        return self

    def gte(self, col, val):
        self.filters[f"{col}__gte"] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._op == "insert":
            self._supa.inserts.append(self._payload)
            return _Result([{"id": "new"}])
        # A select: decide which guard query this is by its filters.
        statuses = self.filters.get("status")
        if isinstance(statuses, list):  # in_(...) → in-flight check
            return _Result([{"id": "inflight"}] if self._supa.in_flight else [])
        if self.filters.get("status") == "complete":  # recency debounce
            return _Result([{"id": "recent"}] if self._supa.has_recent else [])
        return _Result([])

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeSupabase:
    def __init__(self, in_flight=False, has_recent=False):
        self.in_flight = in_flight
        self.has_recent = has_recent
        self.inserts: list = []

    def table(self, _name):
        return _FakeQuery(self, "select")


def _run_enqueue(
    monkeypatch, trigger, *, in_flight=False, has_recent=False, window=6, event_refresh=True
):
    fake = _FakeSupabase(in_flight=in_flight, has_recent=has_recent)
    monkeypatch.setattr(reopt_planner, "get_supabase", lambda: fake)
    # enqueue_reopt_plan resolves settings via a local `from config import settings`.
    import config

    monkeypatch.setattr(config.settings, "reopt_plan_min_interval_hours", window)
    monkeypatch.setattr(config.settings, "reopt_plan_event_refresh_enabled", event_refresh)
    reopt_planner.enqueue_reopt_plan(CLIENT, trigger=trigger)
    return fake


def test_enqueue_manual_always_inserts_even_with_recent_plan(monkeypatch):
    # manual bypasses both the event-refresh gate and the recency debounce.
    fake = _run_enqueue(monkeypatch, "manual", has_recent=True, event_refresh=False)
    assert len(fake.inserts) == 1
    assert fake.inserts[0]["payload"]["trigger"] == "manual"


def test_enqueue_skips_when_job_in_flight(monkeypatch):
    fake = _run_enqueue(monkeypatch, "scheduled", in_flight=True)
    assert fake.inserts == []


def test_enqueue_scheduled_debounced_when_plan_built_today(monkeypatch):
    fake = _run_enqueue(monkeypatch, "scheduled", has_recent=True)
    assert fake.inserts == []


def test_enqueue_scheduled_inserts_when_no_recent_plan(monkeypatch):
    # scheduled runs even with event refresh disabled (the weekly cadence).
    fake = _run_enqueue(monkeypatch, "scheduled", has_recent=False, event_refresh=False)
    assert len(fake.inserts) == 1


def test_enqueue_event_trigger_suppressed_when_refresh_disabled(monkeypatch):
    # Default owner policy: drop/maps_drop/offpage never rebuild the plan.
    fake = _run_enqueue(monkeypatch, "drop", has_recent=False, event_refresh=False)
    assert fake.inserts == []


def test_enqueue_event_trigger_debounced_within_window(monkeypatch):
    # With event refresh re-enabled, the recency debounce still applies.
    fake = _run_enqueue(monkeypatch, "drop", has_recent=True, window=6, event_refresh=True)
    assert fake.inserts == []


def test_enqueue_event_trigger_window_zero_disables_debounce(monkeypatch):
    # event refresh on + window=0 → no recency query; the event rebuild is allowed.
    fake = _run_enqueue(monkeypatch, "maps_drop", has_recent=True, window=0, event_refresh=True)
    assert len(fake.inserts) == 1
