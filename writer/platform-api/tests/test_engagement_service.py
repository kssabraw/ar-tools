"""Unit tests for services.engagement_service.can_transition — pure state machine."""

from __future__ import annotations

from services import engagement_service as es


def test_forward_lifecycle_edges_allowed():
    for frm, to in zip(es.LIFECYCLE, es.LIFECYCLE[1:]):
        assert es.can_transition(frm, to), f"{frm} -> {to} should be allowed"


def test_skipping_a_stage_is_rejected():
    assert not es.can_transition("onboarding", "auditing")
    assert not es.can_transition("intake", "strategizing")
    assert not es.can_transition("auditing", "plan_review")


def test_plan_review_can_approve_or_replan():
    assert es.can_transition("plan_review", "provisioning")   # approve
    assert es.can_transition("plan_review", "strategizing")   # send back


def test_steady_state_can_amend_or_run_more():
    assert es.can_transition("steady_state", "plan_review")
    assert es.can_transition("steady_state", "executing")


def test_any_live_state_can_pause_and_close():
    for s in es.LIFECYCLE:
        assert es.can_transition(s, "paused")
        assert es.can_transition(s, "closed")


def test_paused_resumes_then_closes():
    assert es.can_transition("paused", "executing")
    assert es.can_transition("paused", "steady_state")
    assert es.can_transition("paused", "closed")
    assert not es.can_transition("paused", "paused")
    assert not es.can_transition("paused", "onboarding")  # not a resume point


def test_closed_is_terminal():
    assert not es.can_transition("closed", "onboarding")
    assert not es.can_transition("closed", "paused")
    assert not es.can_transition("closed", "closed")


def test_self_and_unknown_states_rejected():
    assert not es.can_transition("executing", "executing")
    assert not es.can_transition("executing", "bogus")
    assert not es.can_transition("bogus", "executing")


# ── onboarding approval gate (pure helpers) ──────────────────────────────────
def test_voice_approved_requires_content_and_acceptance():
    assert es._is_voice_approved({"raw_text": "We sound friendly."})           # user-authored
    assert es._is_voice_approved({"recommended_voice": "x", "recommended_accepted": True})
    assert not es._is_voice_approved({"recommended_voice": "x"})               # drafted, not accepted
    assert not es._is_voice_approved({})
    assert not es._is_voice_approved(None)


def test_icp_ready_from_icp_or_differentiators():
    assert es._is_icp_ready({"raw_text": "Busy homeowners"}, None)
    assert es._is_icp_ready({"segments": [{"name": "x"}]}, None)
    assert es._is_icp_ready(None, ["24/7 service"])                            # differentiators alone
    assert not es._is_icp_ready({}, None)
    assert not es._is_icp_ready(None, [])
