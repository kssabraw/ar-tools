"""Unit tests for services.strategy_digest — the SerMaStr digest assembler's
pure logic: the standard signal envelope (deterministic status — the LLM never
does trend arithmetic), staleness flags, the keyword passport grouping, the
active-signal gate, and the render budget. No DB / no network (the providers'
reads are covered by integration testing, per repo convention)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import strategy_digest as sd

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# compute_status — deterministic trend arithmetic
# ---------------------------------------------------------------------------
def test_status_lower_is_better_improving():
    # position 4 vs baseline 8 → moved down the axis → better
    assert sd.compute_status(4, 8, sd.LOWER_IS_BETTER, 1.0) == "improving"


def test_status_lower_is_better_declining():
    assert sd.compute_status(12, 8, sd.LOWER_IS_BETTER, 1.0) == "declining"


def test_status_higher_is_better_flips_the_direction():
    # visibility 40% vs 60% baseline → declining even though the number fell
    # (this is exactly the position-vs-visibility mix-up the envelope kills)
    assert sd.compute_status(40, 60, sd.HIGHER_IS_BETTER, 5.0) == "declining"
    assert sd.compute_status(60, 40, sd.HIGHER_IS_BETTER, 5.0) == "improving"


def test_status_noise_floor_is_stable():
    assert sd.compute_status(8.4, 8.0, sd.LOWER_IS_BETTER, 1.0) == "stable"


def test_status_missing_either_side_is_insufficient():
    assert sd.compute_status(None, 8, sd.LOWER_IS_BETTER, 1.0) == "insufficient_data"
    assert sd.compute_status(8, None, sd.LOWER_IS_BETTER, 1.0) == "insufficient_data"


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------
def test_stale_when_age_exceeds_cadence_grace():
    # the spec's example: a 19-day-old grid scan on a weekly cadence is stale
    measured = (NOW - timedelta(days=19)).isoformat()
    stale, age = sd.staleness(measured, 7, NOW)
    assert stale is True and age == 19


def test_fresh_within_grace():
    measured = (NOW - timedelta(days=10)).isoformat()
    stale, age = sd.staleness(measured, 7, NOW)  # 10 < 7*2
    assert stale is False and age == 10


def test_unknown_timestamp_is_stale():
    stale, age = sd.staleness(None, 7, NOW)
    assert stale is True and age is None


def test_no_cadence_never_stale():
    measured = (NOW - timedelta(days=400)).isoformat()
    stale, _ = sd.staleness(measured, None, NOW)
    assert stale is False


# ---------------------------------------------------------------------------
# make_envelope
# ---------------------------------------------------------------------------
def test_envelope_computes_delta_and_status():
    e = sd.make_envelope(
        module="organic_rank", keyword="emergency plumber", metric="position",
        value=12.0, baseline=6.0, direction=sd.LOWER_IS_BETTER,
        measured_at=(NOW - timedelta(days=2)).isoformat(), cadence_days=7,
        min_delta=1.0, now=NOW,
    )
    assert e["delta"] == 6.0
    assert e["status"] == "declining"
    assert e["stale"] is False
    assert e["direction"] == sd.LOWER_IS_BETTER


def test_envelope_precomputed_status_wins():
    e = sd.make_envelope(
        module="organic_rank", keyword="k", metric="position",
        value=5, baseline=5, direction=sd.LOWER_IS_BETTER, now=NOW,
        status="improving",  # the module's own deterministic trend read
    )
    assert e["status"] == "improving"


def test_envelope_non_numeric_value_is_insufficient():
    e = sd.make_envelope(
        module="m", keyword="k", metric="x", value=None, baseline=3,
        direction=sd.LOWER_IS_BETTER, now=NOW,
    )
    assert e["status"] == "insufficient_data"
    assert e["delta"] is None


def test_staleness_flags_message():
    stale_env = sd.make_envelope(
        module="maps_geogrid", keyword="plumber", metric="local_pack_presence_pct",
        value=50, baseline=50, direction=sd.HIGHER_IS_BETTER,
        measured_at=(NOW - timedelta(days=19)).isoformat(), cadence_days=7,
        min_delta=5.0, now=NOW,
    )
    flags = sd.staleness_flags([stale_env])
    assert len(flags) == 1
    assert "19 days ago" in flags[0] and "STALE" in flags[0]


# ---------------------------------------------------------------------------
# keyword passports
# ---------------------------------------------------------------------------
def _env(module, keyword, status="stable"):
    return sd.make_envelope(
        module=module, keyword=keyword, metric="m", value=1, baseline=1,
        direction=sd.LOWER_IS_BETTER, now=NOW, status=status,
    )


def test_passports_group_by_keyword_across_modules():
    envs = [
        _env("organic_rank", "Emergency Plumber"),
        _env("maps_geogrid", "emergency plumber"),  # different case — same passport
        _env("organic_rank", "drain cleaning"),
    ]
    passports = sd.build_keyword_passports(envs, [], [])
    by_kw = {p["keyword"].lower(): p for p in passports}
    assert len(passports) == 2
    assert len(by_kw["emergency plumber"]["signals"]) == 2


def test_passports_alerted_keywords_sort_first():
    envs = [_env("organic_rank", "quiet keyword"), _env("organic_rank", "hot keyword", "declining")]
    alerts = [{"keyword": "hot keyword", "alert_type": "weekly_drop"}]
    episodes = [{"keyword": "hot keyword", "channel": "organic", "status": "open"}]
    passports = sd.build_keyword_passports(envs, episodes, alerts)
    assert passports[0]["keyword"] == "hot keyword"
    assert passports[0]["alerts"] and passports[0]["episodes"]


def test_passports_capped():
    envs = [_env("organic_rank", f"kw {i}") for i in range(60)]
    assert len(sd.build_keyword_passports(envs, [], [], max_keywords=40)) == 40


# ---------------------------------------------------------------------------
# active domains + weekly gate
# ---------------------------------------------------------------------------
def test_active_domains_from_alerts_and_flags():
    digest = {
        "open_alerts": {"rank": [{"keyword": "k"}], "offpage": [{"alert_type": "rd_loss"}]},
        "episodes": [{"channel": "maps", "keyword": "k"}],
        "task_plan": {"flags": ["under_funded"], "retainer_monthly": 2000},
        "ai_visibility": {"invisible_keywords": ["k"], "envelopes": []},
        "action_plan": {"items": [{"kind": "quick_win"}]},
    }
    domains = sd.active_signal_domains(digest)
    assert domains == {"organic_drop", "maps", "offpage", "ai_visibility", "content", "budget"}


def test_quiet_client_has_no_active_signals():
    digest = {"open_alerts": {}, "episodes": [], "task_plan": {}}
    assert sd.has_active_signals(digest) is False
    assert sd.active_signal_domains(digest) == set()


def test_leadoff_seeded_client_pulls_leadoff_domain():
    # the create-from-market handoff writes a "LeadOff targets — …" goal
    digest = {
        "open_alerts": {}, "episodes": [], "task_plan": {},
        "campaign_goals": {"goals": [
            {"label": "LeadOff targets — Locksmith in Vancouver, WA",
             "goal_type": "custom"}]},
    }
    assert sd.active_signal_domains(digest) == {"leadoff"}
    # ...but a LeadOff goal alone does NOT make the client "active" for the
    # weekly scheduler gate (it's context, not a problem signal)
    assert sd.has_active_signals(digest) is False


def test_open_alert_makes_client_active():
    assert sd.has_active_signals({"open_alerts": {"maps": [{"keyword": "k"}]}}) is True
    assert sd.has_active_signals({"episodes": [{"keyword": "k"}]}) is True
    assert sd.has_active_signals({"task_plan": {"flags": ["escalate_margin_below_50"]}}) is True


# ---------------------------------------------------------------------------
# render budget
# ---------------------------------------------------------------------------
def test_render_within_budget_is_unchanged():
    digest = {"a": 1}
    out = sd.render_digest(digest, 1000)
    assert out == '{"a": 1}'


def test_render_trims_passports_to_fit():
    digest = {
        "keyword_passports": [
            {"keyword": f"kw {i}", "signals": [{"padding": "x" * 200}]} for i in range(40)
        ],
        "action_plan": {"items": [{"diagnosis": "y" * 200} for _ in range(15)]},
    }
    out = sd.render_digest(digest, 5000)
    assert len(out) <= 5000 + 50
    assert "trimmed_to_fit_budget" in out or "TRUNCATED_TO_BUDGET" in out


def test_budget_domain_from_client_retainer():
    # retainer lives on the client section (not the task plan) — a retainer
    # client with an unflagged plan still activates the budget domain.
    digest = {"client": {"retainer_monthly": 2000}, "task_plan": {"flags": []}}
    assert "budget" in sd.active_signal_domains(digest)


# ---------------------------------------------------------------------------
# review_snippets — customer-voice raw material for the strategist
# ---------------------------------------------------------------------------
def test_review_snippets_clips_caps_and_skips_empty():
    gbp = {"reviews": [
        {"reviewer": "A", "rating": 5, "date": "2026-06-01", "text": "Free parking was great! " * 30},
        {"reviewer": "B", "rating": 4, "date": "", "text": "  "},          # empty → skipped
        {"reviewer": "C", "rating": 5, "text": "They have free parking."},  # no date → None
        "junk",                                                             # non-dict → skipped
    ]}
    out = sd.review_snippets(gbp, limit=10, clip=50)
    assert len(out) == 2
    assert len(out[0]["text"]) == 50 and out[0]["rating"] == 5
    assert out[1] == {"rating": 5, "date": None, "text": "They have free parking."}
    # reviewer names are deliberately NOT carried into the prompt
    assert all("reviewer" not in r for r in out)


def test_review_snippets_limit_and_empty_shapes():
    gbp = {"reviews": [{"text": f"review {i}"} for i in range(20)]}
    assert len(sd.review_snippets(gbp, limit=10)) == 10
    assert sd.review_snippets(None) == []
    assert sd.review_snippets({}) == []
    assert sd.review_snippets({"reviews": "oops"}) == []


# ---------------------------------------------------------------------------
# competitor_review_sets — competitor customer-voice from raw capture rows
# ---------------------------------------------------------------------------
def test_competitor_review_sets_dedups_sorts_and_caps():
    rows = [
        # newest capture first per place — the stale p1 capture below must lose
        {"place_id": "p1", "name": "Acme Roofing", "top3_pins": 2, "found_pins": 5,
         "profile": {"reviews": [{"text": "fresh capture"}]}},
        {"place_id": "p2", "name": "Best Roofs", "top3_pins": 9, "found_pins": 12,
         "profile": {"reviews": [{"text": f"r{i}"} for i in range(9)]}},
        {"place_id": "p1", "name": "Acme Roofing", "top3_pins": 2, "found_pins": 5,
         "profile": {"reviews": [{"text": "STALE capture"}]}},
        {"place_id": "p3", "name": "No Reviews Inc", "top3_pins": 99, "found_pins": 99,
         "profile": {"reviews": []}},  # no text → skipped even though top pack presence
    ]
    out = sd.competitor_review_sets(rows, max_competitors=4, per_competitor=5)
    # p3 skipped (no reviews); p2 first (more pack presence than p1)
    assert [c["competitor"] for c in out] == ["Best Roofs", "Acme Roofing"]
    assert len(out[0]["reviews"]) == 5  # per-competitor cap
    assert out[1]["reviews"][0]["text"] == "fresh capture"  # latest capture won


def test_competitor_review_sets_max_competitors_and_empty():
    rows = [
        {"place_id": f"p{i}", "name": f"C{i}", "top3_pins": i,
         "profile": {"reviews": [{"text": "hi"}]}}
        for i in range(6)
    ]
    assert len(sd.competitor_review_sets(rows, max_competitors=3)) == 3
    assert sd.competitor_review_sets([]) == []
    assert sd.competitor_review_sets(None) == []
