"""Unit tests for services.director.audit_health — the pure audit-log
process-health assessors (owner ask 2026-09-01). No DB, no mocks: each assessor
is a pure function over hand-built learning-signal dicts."""

from __future__ import annotations

from services.director import audit_health as AH


def _sk(**kw):
    """A SerMaStr learning_signals by_kind bucket with sensible zero defaults."""
    base = {"approved": 0, "dismissed": 0, "pending": 0, "worked": 0, "partial": 0,
            "no_effect": 0, "total": 0, "decided": 0, "graded": 0,
            "dismiss_rate": 0.0, "ineffective_rate": 0.0}
    base.update(kw)
    return base


def _pa(**kw):
    """A PACE learning_signals by_action bucket with sensible zero defaults."""
    base = {"approved": 0, "denied": 0, "modified": 0, "reverted": 0,
            "executed": 0, "total": 0, "reject_rate": 0.0}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# high_dismiss (SerMaStr)
# ---------------------------------------------------------------------------
def test_sermastr_dismiss_fires_at_threshold_and_min_samples():
    by_kind = {"link_building": _sk(dismissed=5, approved=2, decided=7, dismiss_rate=0.714)}
    findings = AH.assess_sermastr_dismiss(by_kind, min_samples=4, threshold=0.6)
    assert len(findings) == 1
    f = findings[0]
    assert f["agent"] == "sermastr" and f["kind"] == "high_dismiss"
    assert f["ident"] == "sermastr:high_dismiss:link_building"
    assert "71%" in f["label"] and f["detail"]["decided"] == 7


def test_sermastr_dismiss_silent_below_min_samples():
    by_kind = {"link_building": _sk(dismissed=2, approved=0, decided=2, dismiss_rate=1.0)}
    assert AH.assess_sermastr_dismiss(by_kind, min_samples=4, threshold=0.6) == []


def test_sermastr_dismiss_silent_below_threshold():
    by_kind = {"reoptimization": _sk(dismissed=2, approved=6, decided=8, dismiss_rate=0.25)}
    assert AH.assess_sermastr_dismiss(by_kind, min_samples=4, threshold=0.6) == []


# ---------------------------------------------------------------------------
# low_effectiveness (SerMaStr)
# ---------------------------------------------------------------------------
def test_sermastr_ineffective_fires_on_no_effect_rate():
    by_kind = {"reoptimization": _sk(no_effect=4, worked=1, partial=0, graded=5, ineffective_rate=0.8)}
    findings = AH.assess_sermastr_ineffective(by_kind, min_samples=4, threshold=0.5)
    assert len(findings) == 1
    assert findings[0]["kind"] == "low_effectiveness"
    assert findings[0]["detail"]["graded"] == 5


def test_sermastr_ineffective_silent_when_thin():
    by_kind = {"reoptimization": _sk(no_effect=1, worked=0, graded=1, ineffective_rate=1.0)}
    assert AH.assess_sermastr_ineffective(by_kind, min_samples=4, threshold=0.5) == []


# ---------------------------------------------------------------------------
# high_dismiss (PACE reject/revert)
# ---------------------------------------------------------------------------
def test_pace_reject_fires_and_counts_declined_plus_reverted():
    by_action = {"reassign_task": _pa(denied=3, reverted=2, total=8, reject_rate=0.625)}
    findings = AH.assess_pace_reject(by_action, min_samples=4, threshold=0.6)
    assert len(findings) == 1
    f = findings[0]
    assert f["agent"] == "pace" and f["ident"] == "pace:high_dismiss:reassign_task"
    assert f["detail"]["declined"] == 5 and f["detail"]["total"] == 8


def test_pace_reject_silent_below_threshold():
    by_action = {"set_task_due": _pa(denied=1, reverted=0, total=10, reject_rate=0.1)}
    assert AH.assess_pace_reject(by_action, min_samples=4, threshold=0.6) == []


# ---------------------------------------------------------------------------
# stale_pending
# ---------------------------------------------------------------------------
def test_stale_pending_fires_at_min_count():
    findings = AH.assess_stale_pending(6, pending_days=5, min_count=5)
    assert len(findings) == 1
    assert findings[0]["ident"] == "sermastr:stale_pending"
    assert findings[0]["detail"]["stale_count"] == 6


def test_stale_pending_silent_below_min():
    assert AH.assess_stale_pending(3, pending_days=5, min_count=5) == []


# ---------------------------------------------------------------------------
# coverage_gap
# ---------------------------------------------------------------------------
def test_coverage_flags_zero_activity_only_for_active_agents():
    findings = AH.assess_coverage(sermastr_total=0, pace_total=0,
                                  sermastr_active=True, pace_active=True)
    idents = {f["ident"] for f in findings}
    assert "sermastr:coverage_gap:no_activity" in idents
    assert "pace:coverage_gap:no_activity" in idents


def test_coverage_no_activity_suppressed_for_dark_agent():
    findings = AH.assess_coverage(sermastr_total=0, pace_total=0,
                                  sermastr_active=False, pace_active=False)
    assert findings == []


def test_coverage_behind_goals_lists_uncovered_clients():
    findings = AH.assess_coverage(sermastr_total=5, pace_total=5,
                                  sermastr_active=True, pace_active=True,
                                  behind_uncovered=["c1", "c2"], min_uncovered=1)
    behind = [f for f in findings if f["ident"] == "sermastr:coverage_gap:behind_goals"]
    assert len(behind) == 1
    assert behind[0]["detail"]["count"] == 2 and behind[0]["detail"]["client_ids"] == ["c1", "c2"]


# ---------------------------------------------------------------------------
# build_findings — composition + client scoping
# ---------------------------------------------------------------------------
_THRESHOLDS = {"min_samples": 4, "dismiss_threshold": 0.6, "ineffective_threshold": 0.5,
               "stale_pending_min": 5, "pending_days": 5, "min_uncovered": 1}


def test_build_findings_composes_all_signals():
    sermastr_signals = {"by_kind": {
        "link_building": _sk(dismissed=5, approved=2, decided=7, dismiss_rate=0.714),
        "reoptimization": _sk(no_effect=4, worked=1, graded=5, ineffective_rate=0.8),
    }}
    pace_signals = {"by_action": {"reassign_task": _pa(denied=4, reverted=1, total=7, reject_rate=0.714)}}
    findings = AH.build_findings(
        sermastr_signals=sermastr_signals, pace_signals=pace_signals,
        sermastr_total=20, pace_total=15, stale_count=6, behind_uncovered=["c9"],
        thresholds=_THRESHOLDS, sermastr_active=True, pace_active=True, client_id=None)
    kinds = sorted(f["kind"] for f in findings)
    # high_dismiss (sermastr) + low_effectiveness + high_dismiss (pace) + stale + behind coverage
    assert kinds.count("high_dismiss") == 2
    assert "low_effectiveness" in kinds
    assert "stale_pending" in kinds
    assert "coverage_gap" in kinds


def test_build_findings_scopes_rates_to_client_and_skips_agency_signals():
    """A per-client read: rate findings carry the client_id; stale/coverage
    (agency-level) are passed empty by the caller and produce nothing."""
    sermastr_signals = {"by_kind": {"link_building": _sk(dismissed=5, approved=1, decided=6, dismiss_rate=0.833)}}
    findings = AH.build_findings(
        sermastr_signals=sermastr_signals, pace_signals={"by_action": {}},
        sermastr_total=6, pace_total=0, stale_count=0, behind_uncovered=None,
        thresholds=_THRESHOLDS, sermastr_active=False, pace_active=False, client_id="c1")
    assert len(findings) == 1
    assert findings[0]["client_id"] == "c1"
    assert findings[0]["kind"] == "high_dismiss"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def test_finding_dedupe_key_is_per_iso_week():
    assert AH.finding_dedupe_key("sermastr:high_dismiss:link_building", 2026, 35) == \
        "ops_seam:audit:sermastr:high_dismiss:link_building:2026-W35"


def test_format_health_section_empty_when_no_findings():
    assert AH.format_health_section([]) == []


def test_format_health_section_bullets_each_finding():
    findings = [{"label": "SerMaStr `link_building` proposals are dismissed 71% of the time"}]
    lines = AH.format_health_section(findings)
    assert lines[0] == "*Agent process health:*"
    assert lines[1].startswith("• SerMaStr")


def test_summary_line_counts_per_agent():
    findings = [
        {"agent": "sermastr", "kind": "high_dismiss"},
        {"agent": "sermastr", "kind": "stale_pending"},
        {"agent": "pace", "kind": "high_dismiss"},
    ]
    line = AH.summary_line(findings)
    assert "3 issues" in line and "2 SerMaStr" in line and "1 PACE" in line


def test_summary_line_empty_when_all_clear():
    assert AH.summary_line([]) == ""


def test_notification_title_names_agent_and_kind():
    f = {"agent": "pace", "kind": "high_dismiss"}
    assert AH.notification_title(f) == "PACE process health — Work getting rejected"
