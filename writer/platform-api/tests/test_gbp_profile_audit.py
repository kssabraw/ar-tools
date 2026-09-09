"""Unit tests for the GBP Profile Audit — pure health scoring (live-aware,
reusing gbp_audit.audit) + the change-trail merge."""

from __future__ import annotations

from services import gbp_profile_audit as a


def _live(**over):
    base = {
        "description": ("First Class Roofing restores and repairs roofs across the Tampa Bay area for "
                        "homeowners and local businesses — repairs, replacements, storm damage and "
                        "inspections, all backed by a workmanship warranty in Tampa."),
        "categories": [{"id": "gcid:roofing_contractor", "name": "Roofing contractor"},
                       {"id": "gcid:gutter", "name": "Gutter service"}],
        "services": [{"kind": "structured", "label": "Roof repair"}],
        "hours": {"regular": [{"day": 0, "open_24": False, "periods": [{"open": "09:00", "close": "17:00"}]}]},
        "phone": {"primary": "(813) 555-1212", "additional": []},
        "website": "https://fcr.example.com",
        "address_str": "1 Main St, Tampa, FL, 33601, US",
        "open_status": "OPEN",
        "has_voice_of_merchant": True,
    }
    base.update(over)
    return base


_CAPTURED_FULL = {"photo": "http://p/1.jpg", "gbp_review_count": 120}


def test_audit_full_profile_scores_high_no_recs():
    res = a.audit_live(_live(), _CAPTURED_FULL, [{"review_count": 80, "primary_category": "Roofing contractor"}])
    assert res["score"] == 100 and res["band"] == "strong"
    assert res["recommendations"] == []
    assert all(c["ok"] for c in res["checks"])


def test_audit_sparse_profile_recommendations():
    live = _live(description="", categories=[], services=[], hours={"regular": []},
                 phone={"primary": "", "additional": []}, website="", address_str="",
                 open_status="", has_voice_of_merchant=None)
    res = a.audit_live(live, {}, [])
    keys = {r["key"] for r in res["recommendations"]}
    assert {"description", "services", "hours", "primary_category", "website", "phone", "photo"} <= keys
    # open_status unknown ("") and VoM unknown (None) never fail → no rec for them.
    assert "open" not in keys and "voice_of_merchant" not in keys
    # High-severity recs sort ahead of medium/low.
    assert res["recommendations"][0]["severity"] in ("critical", "high")
    # Editable-in-tool recs carry the profile target.
    desc_rec = next(r for r in res["recommendations"] if r["key"] == "description")
    assert desc_rec["severity"] == "high" and desc_rec["target"] == "profile"


def test_audit_suspended_voice_of_merchant_is_critical():
    res = a.audit_live(_live(has_voice_of_merchant=False), _CAPTURED_FULL, [])
    vom = next(c for c in res["checks"] if c["key"] == "voice_of_merchant")
    assert vom["ok"] is False
    top = res["recommendations"][0]
    assert top["key"] == "voice_of_merchant" and top["severity"] == "critical"


def test_audit_closed_listing_flags_open_check():
    res = a.audit_live(_live(open_status="CLOSED_PERMANENTLY"), _CAPTURED_FULL, [])
    open_chk = next(c for c in res["checks"] if c["key"] == "open")
    assert open_chk["ok"] is False
    assert any(r["key"] == "open" for r in res["recommendations"])


def test_audit_review_gap_and_category_gaps():
    competitors = [
        {"review_count": 200, "primary_category": "Roofing contractor", "gbp_categories": ["Solar installer"]},
        {"review_count": 220, "primary_category": "Roofing contractor", "gbp_categories": ["Solar installer"]},
    ]
    res = a.audit_live(_live(), {"photo": "p", "gbp_review_count": 30}, competitors)
    assert res["review_gap"]["deficit"] == 220 - 30  # engine median = upper-middle (220), client 30
    assert any(r["key"] == "reviews" for r in res["recommendations"])
    # "solar installer" is on both competitors, not the client → a category gap.
    assert "solar installer" in res["category_gaps"]
    assert any(r["key"] == "category_gaps" for r in res["recommendations"])


def test_audit_live_overrides_captured_snapshot():
    # A stale captured snapshot says "no website"; the live read has one → the
    # website check passes (live wins).
    res = a.audit_live(_live(), {"website": "", "photo": "p", "gbp_review_count": 100}, [])
    website = next(c for c in res["checks"] if c["key"] == "website")
    assert website["ok"] is True


def test_build_live_fields_and_address():
    parsed = {"description": "d", "categories": [{"id": "c", "name": "C"}],
              "services": [], "hours": {"regular": []}}
    snapshot = {"phone": {"primary": "555", "additional": []}, "website": "w",
                "address": {"lines": ["1 Main St"], "locality": "Tampa", "region": "FL",
                            "postal_code": "33601", "country": "US"},
                "open_status": "OPEN", "has_voice_of_merchant": True}
    live = a.build_live_fields(parsed, snapshot)
    assert live["address_str"] == "1 Main St, Tampa, FL, 33601, US"
    assert live["website"] == "w" and live["open_status"] == "OPEN"


def test_merge_history_merges_and_sorts():
    edits = [{"field": "description", "source": "ai", "status": "applied", "created_by": "u1",
              "current_value": "We are a family owned roofer.",
              "proposed_value": "Family-owned roofing experts serving Fort Lauderdale.",
              "applied_at": "2026-09-04T10:00:00Z", "updated_at": "2026-09-04T10:00:00Z"}]
    changes = [
        {"kind": "outside_change", "detail": {"fields": ["phone", "website"]}, "detected_at": "2026-09-04T12:00:00Z"},
        {"kind": "suspended", "detail": None, "detected_at": "2026-09-03T00:00:00Z"},
    ]
    out = a.merge_history(edits, changes, {"u1": "Ivy"}, 10)
    assert [e["kind"] for e in out] == ["outside_change", "edit", "suspended"]
    assert out[0]["detail"] == "Changed outside the tool: phone number, website"
    # The team edit now names the field and shows the before→after, not just "ai edit".
    assert out[1]["source"] == "team" and out[1]["who"] == "Ivy"
    assert out[1]["detail"] == (
        'ai edit · description: "We are a family owned roofer." '
        '→ "Family-owned roofing experts serving Fo…" — applied'
    )
    assert out[2]["detail"].startswith("Listing appears suspended")


def test_merge_history_respects_limit():
    changes = [{"kind": "outside_change", "detail": {"fields": ["hours"]},
                "detected_at": f"2026-09-0{i}T00:00:00Z"} for i in range(1, 6)]
    assert len(a.merge_history([], changes, {}, 3)) == 3


def test_merge_history_labels_a_revert_and_carries_edit_ids():
    edits = [
        {"id": "e-2", "field": "description", "source": "revert", "status": "applied",
         "proposed_value": "The original description.",
         "reverts_edit_id": "e-1", "applied_at": "2026-09-05T10:00:00Z",
         "updated_at": "2026-09-05T10:00:00Z"},
        {"id": "e-1", "field": "description", "source": "ai", "status": "applied",
         "applied_at": "2026-09-04T10:00:00Z", "updated_at": "2026-09-04T10:00:00Z"},
    ]
    out = a.merge_history(edits, [], {}, 10)
    rev = out[0]
    # The revert names the field and previews the restored value.
    assert rev["detail"] == 'reverted description to "The original description." — applied'
    assert rev["edit_id"] == "e-2" and rev["reverts_edit_id"] == "e-1"
    # An ordinary applied edit carries its id (the Revert target) and no back-link.
    assert out[1]["edit_id"] == "e-1" and out[1]["reverts_edit_id"] is None


def test_describe_change_names_field_and_summarizes_per_type():
    # Website: before → after.
    assert a.describe_change("website", "http://old.com", "https://new.com") == (
        'website: "http://old.com" → "https://new.com"'
    )
    # Services: count change + the new labels.
    svc = a.describe_change(
        "services", [{"label": "Roof Repair"}],
        [{"label": "Roof Repair"}, {"label": "Roof Replacement"}],
    )
    assert svc == "services: 1 → 2 — Roof Repair, Roof Replacement"
    # Hours (structured, no per-item diff): still names the field.
    assert a.describe_change("hours", {"regular": []}, {"regular": [1, 2]}) == "hours updated"
    # open/closed status renders the target status.
    assert a.describe_change("open_info", None, {"status": "CLOSED_TEMPORARILY"}) == (
        "open/closed status → Closed Temporarily"
    )
    # A missing/unparseable value degrades to '<field> updated', never raises.
    assert a.describe_change("labels", None, None) == "labels cleared"


def test_merge_history_new_field_gets_a_label_not_a_raw_key():
    # A Phase 3a field the old label map lacked (labels) must not surface as a raw key.
    edits = [{"field": "labels", "source": "manual", "status": "applied",
              "proposed_value": ["promo", "seasonal"],
              "applied_at": "2026-09-05T10:00:00Z", "updated_at": "2026-09-05T10:00:00Z"}]
    out = a.merge_history(edits, [], {}, 10)
    assert out[0]["detail"] == "manual edit · labels: promo, seasonal — applied"
