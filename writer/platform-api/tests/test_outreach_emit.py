"""Pure-logic tests for the Phase 3 emit + touch builders.

No network, no database. What matters here: `selection_reason` is validated (recorded on 100% of
contacts, with the pre-Phase-4 'manual' value), the touch rollup recomputes rather than drifts, the
outcome stub does not claim a contact, and the emit payload is an audit-ready QUEUE that carries the
call hook as its pitch and NO generated asset.
"""
import pytest

from services import outreach_emit as oe


# --- selection_reason ---------------------------------------------------------------------------


def test_resolve_selection_reason_defaults_when_unset():
    assert oe.resolve_selection_reason(None, default="manual") == "manual"
    assert oe.resolve_selection_reason("", default="manual") == "manual"
    assert oe.resolve_selection_reason("   ", default="random_control") == "random_control"


def test_resolve_selection_reason_accepts_the_allowlist():
    for r in ("thompson", "random_control", "manual"):
        assert oe.resolve_selection_reason(r, default="manual") == r
    assert oe.resolve_selection_reason("  thompson ", default="manual") == "thompson"


def test_resolve_selection_reason_rejects_unknown():
    with pytest.raises(ValueError):
        oe.resolve_selection_reason("guessed", default="manual")


def test_resolve_selection_reason_rejects_a_bad_default():
    # A misconfigured default must fail loudly rather than write an unmodellable value.
    with pytest.raises(ValueError):
        oe.resolve_selection_reason(None, default="whatever")


# --- channel ------------------------------------------------------------------------------------


def test_validate_channel():
    assert oe.validate_channel("phone") == "phone"
    assert oe.validate_channel(" email ") == "email"
    with pytest.raises(ValueError):
        oe.validate_channel("fax")
    with pytest.raises(ValueError):
        oe.validate_channel(None)


# --- outcome / touch rows -----------------------------------------------------------------------


def test_build_outcome_row_stub_does_not_claim_a_contact():
    row = oe.build_outcome_row(
        prospect_id="p1", selection_reason="manual", sequence_version="phone_v1",
        touches_per_sequence=5,
    )
    assert row == {
        "prospect_id": "p1",
        "lead_source": "outbound_scan",
        "selection_reason": "manual",
        "sequence_version": "phone_v1",
        "touches_per_sequence_at_send": 5,
        "touch_count": 0,
    }
    # emit enqueues; a touch contacts — so no first_contacted_at is written at emit.
    assert "first_contacted_at" not in row


def test_build_touch_row_omits_empty_optionals():
    row = oe.build_touch_row(lead_id="l1", channel="phone")
    assert row == {"lead_id": "l1", "channel": "phone"}


def test_build_touch_row_includes_supplied_fields():
    row = oe.build_touch_row(
        lead_id="l1", channel="phone", sequence_version="phone_v1", touch_number=2,
        disposition="voicemail", note="  left a message  ", actor_id="a1",
    )
    assert row == {
        "lead_id": "l1", "channel": "phone", "sequence_version": "phone_v1",
        "touch_number": 2, "disposition": "voicemail", "note": "left a message", "actor_id": "a1",
    }


def test_build_touch_row_validates_channel():
    with pytest.raises(ValueError):
        oe.build_touch_row(lead_id="l1", channel="carrier-pigeon")


# --- touch rollup -------------------------------------------------------------------------------


def test_aggregate_touches_empty():
    assert oe.aggregate_touches([]) == {"touch_count": 0, "first_contacted_at": None}


def test_aggregate_touches_counts_and_takes_earliest():
    rows = [
        {"touched_at": "2026-08-09T12:00:00Z"},
        {"touched_at": "2026-08-08T09:00:00Z"},   # earliest
        {"touched_at": "2026-08-09T18:00:00Z"},
    ]
    agg = oe.aggregate_touches(rows)
    assert agg["touch_count"] == 3
    assert agg["first_contacted_at"] == "2026-08-08T09:00:00Z"


def test_aggregate_touches_ignores_missing_times_for_first_contact_but_still_counts():
    rows = [{"touched_at": None}, {"touched_at": "2026-08-09T12:00:00Z"}]
    agg = oe.aggregate_touches(rows)
    assert agg["touch_count"] == 2
    assert agg["first_contacted_at"] == "2026-08-09T12:00:00Z"


# --- score block --------------------------------------------------------------------------------


def test_build_score_block_absent():
    assert oe.build_score_block(None) == {"model": "placeholder", "available": False}


def test_build_score_block_labels_placeholder_and_never_a_fitted_score():
    block = oe.build_score_block(
        {"coverage_pct": 25.0, "coverage_deficit": 75.0, "best_rank": 4,
         "centroid_dist_at_loss": 2.5, "keywords_measured": 1, "keywords_present": 1}
    )
    assert block["model"] == "placeholder"
    assert block["available"] is True
    assert block["coverage_deficit"] == 75.0
    # No predicted_prob / decile / fitted fields ever leak from a placeholder.
    assert "predicted_prob" not in block and "decile" not in block


# --- emit payload -------------------------------------------------------------------------------


def _justification():
    return {
        "measured": True,
        "hook": "I searched plumber near Van Nuys — you're not in the top 3 anywhere past 2 miles.",
        "hook_element": "coverage",
        "available_elements": ["coverage", "reviews"],
        "talking_points": [{"element": "coverage", "text": "invisible past 2 miles", "facts": {}}],
        "caveats": ["single scan — no trend yet"],
        "provenance": {
            "snapshot_id": "snap1", "submarket": "Van Nuys", "keyword": "plumber",
            "scanned_at": "2026-08-08T00:00:00Z", "geometry_version": "v1", "live_points": 79,
        },
    }


def test_build_emit_payload_is_an_audit_queue_row_not_an_asset():
    payload = oe.build_emit_payload(
        prospect={"id": "p1", "name": "Acme Plumbing", "place_id": "PID", "category": "plumber"},
        channel="phone",
        contacts={"phone": "555", "email": None, "website": "acme.example"},
        justification=_justification(),
        placeholder={"coverage_pct": 20.0, "coverage_deficit": 80.0, "best_rank": 5,
                     "centroid_dist_at_loss": 2.0, "keywords_measured": 1, "keywords_present": 1},
        selection_reason="manual",
    )
    # Identity, channel, contacts, selection_reason.
    assert payload["prospect"] == {
        "id": "p1", "name": "Acme Plumbing", "place_id": "PID", "category": "plumber",
        "submarket": "Van Nuys",
    }
    assert payload["channel"] == "phone"
    assert payload["selection_reason"] == "manual"
    assert payload["contacts"] == {"phone": "555", "email": None, "website": "acme.example"}
    # The pitch is the call hook, reused verbatim (queue and on-screen hook can't disagree).
    assert payload["primary_pitch"]["hook"] == _justification()["hook"]
    assert payload["primary_pitch"]["element"] == "coverage"
    # Score is the labelled placeholder; score_factors empty until Phase 4.
    assert payload["score"]["model"] == "placeholder"
    assert payload["score_factors"] == []
    # No fabricated case study, no delta on a single scan.
    assert payload["matched_case_study"] is None
    assert payload["deltas"] == []
    # Evidence references come from provenance.
    assert payload["evidence"]["snapshot_id"] == "snap1"
    assert payload["evidence"]["keyword"] == "plumber"
    # An audit QUEUE row: no rendered asset, no PDF/signed-url trigger anywhere in it.
    flat = str(payload).lower()
    assert "signed_url" not in flat and "pdf" not in flat and "html" not in flat


def test_build_emit_payload_handles_absent_placeholder():
    payload = oe.build_emit_payload(
        prospect={"id": "p1", "name": "Acme", "place_id": "PID", "category": "plumber"},
        channel="phone", contacts={"phone": None, "email": None, "website": None},
        justification=_justification(), placeholder=None, selection_reason="random_control",
    )
    assert payload["score"] == {"model": "placeholder", "available": False}
    assert payload["selection_reason"] == "random_control"


# --- webhook headers ----------------------------------------------------------------------------


def test_build_webhook_headers():
    assert oe.build_webhook_headers(None) == {"Content-Type": "application/json"}
    assert oe.build_webhook_headers("  ") == {"Content-Type": "application/json"}
    assert oe.build_webhook_headers("tok") == {
        "Content-Type": "application/json", "Authorization": "Bearer tok",
    }
