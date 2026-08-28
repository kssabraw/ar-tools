"""Unit tests for services.interventions — the pure intervention-outcome logic
(verdict classification, +2w/+6w cadence, per-tactic rollup, target parsing).

No network / no DB: classify_verdict / evaluate_intervention /
summarize_effectiveness / resolve_direction / proposal_target are pure; the
registration hooks + daily sweep's I/O are covered by integration testing, per
repo convention.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import interventions as iv

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _intervention(applied_days_ago: int, baseline_value=8.0, direction="lower_is_better",
                  **extra) -> dict:
    row = {
        "id": "iv-1",
        "client_id": "c-1",
        "tactic_type": "reoptimization",
        "applied_at": (NOW - timedelta(days=applied_days_ago)).isoformat(),
        "baseline": {"value": baseline_value, "metric": "keyword_position", "direction": direction},
        "target": {"keyword": "emergency plumber", "goal_type": "keyword_position"},
        "checks": [],
    }
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# resolve_direction
# ---------------------------------------------------------------------------
def test_resolve_direction():
    # keyword_position is the only lower-is-better metric; None defaults to it.
    assert iv.resolve_direction("keyword_position") == "lower_is_better"
    assert iv.resolve_direction(None) == "lower_is_better"
    for gt in ("organic_clicks", "ai_visibility", "maps_pack_presence", "custom"):
        assert iv.resolve_direction(gt) == "higher_is_better"


# ---------------------------------------------------------------------------
# classify_verdict — lower-is-better (rank positions)
# ---------------------------------------------------------------------------
def test_classify_lower_is_better_bands():
    d = "lower_is_better"
    assert iv.classify_verdict(10.0, 6.0, d) == "worked"        # gained 4 ≥ 3
    assert iv.classify_verdict(10.0, 8.5, d) == "partial"       # gained 1.5
    assert iv.classify_verdict(10.0, 9.5, d) == "no_effect"     # gained 0.5
    assert iv.classify_verdict(10.0, 12.0, d) == "no_effect"    # got worse
    # a met explicit target is always worked, even on a small move
    assert iv.classify_verdict(4.0, 3.0, d, target_value=3.0) == "worked"


def test_classify_missing_values_none():
    assert iv.classify_verdict(None, 5.0, "lower_is_better") is None
    assert iv.classify_verdict(5.0, None, "higher_is_better") is None


# ---------------------------------------------------------------------------
# classify_verdict — higher-is-better (clicks / visibility / pack presence)
# ---------------------------------------------------------------------------
def test_classify_higher_is_better_relative():
    d = "higher_is_better"
    assert iv.classify_verdict(100.0, 120.0, d) == "worked"     # +20% ≥ 15%
    assert iv.classify_verdict(100.0, 105.0, d) == "partial"    # +5%
    assert iv.classify_verdict(100.0, 100.5, d) == "no_effect"  # +0.5% < 2%
    assert iv.classify_verdict(100.0, 90.0, d) == "no_effect"   # fell
    # zero baseline: any positive value is a real gain
    assert iv.classify_verdict(0.0, 5.0, d) == "worked"
    assert iv.classify_verdict(0.0, 0.0, d) == "no_effect"


# ---------------------------------------------------------------------------
# evaluate_intervention — cadence (+2w interim, +6w final)
# ---------------------------------------------------------------------------
def test_evaluate_not_due_before_two_weeks():
    r = iv.evaluate_intervention(_intervention(5), current_value=4.0, now=NOW)
    assert r["due"] is False and r["is_final"] is False


def test_evaluate_interim_check_at_two_weeks():
    r = iv.evaluate_intervention(_intervention(15, baseline_value=10.0), current_value=6.0, now=NOW)
    assert r["due"] is True and r["is_final"] is False
    assert r["verdict"] == "worked"


def test_evaluate_final_verdict_at_six_weeks():
    r = iv.evaluate_intervention(_intervention(43, baseline_value=10.0), current_value=9.5, now=NOW)
    assert r["due"] is True and r["is_final"] is True
    assert r["verdict"] == "no_effect"


def test_evaluate_unmeasurable_final_is_none_not_no_effect():
    # A target we could never measure (no baseline value) must NOT be fabricated
    # into 'no_effect' at the 6-week mark — evaluate returns verdict None, and
    # _apply_check closes the row without a verdict (stays 'pending' in the rollup).
    row = _intervention(43, baseline_value=None)
    r = iv.evaluate_intervention(row, current_value=None, now=NOW)
    assert r["is_final"] is True and r["due"] is True
    assert r["verdict"] is None


def test_evaluate_uses_baseline_direction_and_target():
    row = _intervention(
        43, baseline_value=100.0, direction="higher_is_better",
        target={"keyword": "kw", "goal_type": "organic_clicks", "target_value": 130.0},
    )
    # current met the explicit target → worked (even if the % move were modest)
    r = iv.evaluate_intervention(row, current_value=130.0, now=NOW)
    assert r["verdict"] == "worked" and r["is_final"] is True


# ---------------------------------------------------------------------------
# summarize_effectiveness — per-tactic rollup
# ---------------------------------------------------------------------------
def test_summarize_effectiveness_buckets_by_tactic():
    rows = [
        {"tactic_type": "reoptimization", "verdict": "worked"},
        {"tactic_type": "reoptimization", "verdict": "no_effect"},
        {"tactic_type": "reoptimization", "verdict": None},        # pending
        {"tactic_type": "link_building", "verdict": "partial"},
        {"tactic_type": "link_building", "verdict": "worked"},
    ]
    out = iv.summarize_effectiveness(rows)
    reo = out["by_tactic"]["reoptimization"]
    assert (reo["worked"], reo["no_effect"], reo["pending"], reo["total"]) == (1, 1, 1, 3)
    link = out["by_tactic"]["link_building"]
    assert (link["worked"], link["partial"], link["total"]) == (1, 1, 2)
    assert out["overall"]["total"] == 5 and out["overall"]["worked"] == 2


def test_summarize_effectiveness_empty():
    out = iv.summarize_effectiveness([])
    assert out["by_tactic"] == {} and out["overall"]["total"] == 0


# ---------------------------------------------------------------------------
# proposal_target — in-scope parsing
# ---------------------------------------------------------------------------
def test_proposal_target_valid():
    p = {"target": {"tactic_type": "link_building", "keyword": "roof repair", "page_url": ""}}
    assert iv.proposal_target(p) == {
        "tactic_type": "link_building", "keyword": "roof repair", "page_url": None
    }


def test_proposal_target_rejects():
    assert iv.proposal_target({}) is None
    assert iv.proposal_target({"target": {"tactic_type": "gbp_post", "keyword": "x"}}) is None
    assert iv.proposal_target({"target": {"tactic_type": "reoptimization"}}) is None  # no anchor
    assert iv.proposal_target({"target": "not a dict"}) is None


# ---------------------------------------------------------------------------
# drift guard — strategist mirrors TACTIC_TYPES to keep sanitize_review DB-free
# ---------------------------------------------------------------------------
def test_tactic_types_in_sync_with_strategist():
    from services import strategist

    assert strategist._INTERVENTION_TACTICS == iv.TACTIC_TYPES
