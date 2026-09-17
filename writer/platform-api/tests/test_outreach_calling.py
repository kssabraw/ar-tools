"""Pure-logic tests for the cold-caller CRM calling layer (Tier 1.2 / 1.3 / 1.4).

No network, no database. What matters here: dispositions are validated against the right channel's
vocabulary, the catalog carries the next-action hints the UI drives off, the wall-clock → instant
conversion is DST-correct and syncs the local due date, the business-hours indicator is honest
about weekends and unknown zones, and `resolve_callback_fields` folds a wall-time into the stored
columns without letting `next_action_local` reach the database.
"""
from datetime import datetime, timezone

import pytest

from services import outreach_calling as oc
from services import outreach as svc


# --- disposition vocabulary (T1.2) --------------------------------------------------------------


def test_validate_disposition_accepts_channel_values_and_blank():
    assert oc.validate_disposition("phone", "voicemail") == "voicemail"
    assert oc.validate_disposition("phone", "  callback_requested ") == "callback_requested"
    assert oc.validate_disposition("email", "bounced") == "bounced"
    # Blank / None is a bare log — allowed.
    assert oc.validate_disposition("phone", None) is None
    assert oc.validate_disposition("phone", "   ") is None


def test_validate_disposition_rejects_wrong_channel_value():
    # A phone-only value on an email touch, and vice versa.
    with pytest.raises(ValueError):
        oc.validate_disposition("email", "voicemail")
    with pytest.raises(ValueError):
        oc.validate_disposition("phone", "bounced")
    with pytest.raises(ValueError):
        oc.validate_disposition("phone", "invented")


def test_disposition_catalog_carries_hints_the_ui_needs():
    cat = oc.disposition_catalog()
    assert [r["value"] for r in cat["phone"]] == list(oc.PHONE_DISPOSITIONS)
    assert [r["value"] for r in cat["email"]] == list(oc.EMAIL_DISPOSITIONS)
    by_value = {r["value"]: r for r in cat["phone"]}
    # callback_requested reveals the callback picker; do_not_call offers a suppression + Lost reason.
    assert by_value["callback_requested"]["reveal_callback"] is True
    assert by_value["do_not_call"]["suggest_suppress"] is True
    assert by_value["do_not_call"]["suppress_scope"] == "all"
    assert by_value["not_interested"]["suggest_lost_reason"] == "not_interested"
    # a plain disposition has a label and no coercive hint
    assert by_value["no_answer"]["label"] == "No answer"
    assert "suggest_lost_reason" not in by_value["no_answer"]


# --- timezone derivation (T1.4) -----------------------------------------------------------------


def test_guess_timezone_bands():
    assert oc.guess_timezone(-118.2) == "America/Los_Angeles"   # LA
    assert oc.guess_timezone(-94.6) == "America/Chicago"        # Kansas City
    assert oc.guess_timezone(-73.9) == "America/New_York"       # NYC
    assert oc.guess_timezone(-105.0) == "America/Denver"        # Denver
    assert oc.guess_timezone(-157.8) == "Pacific/Honolulu"      # Honolulu
    assert oc.guess_timezone(-66.9) == "America/New_York"       # Maine (continental US east edge)
    assert oc.guess_timezone(None) is None


def test_guess_timezone_rejects_non_us_longitudes():
    # East of ~-60 is the Atlantic / Eastern hemisphere — unknowable, never a wrong US zone.
    assert oc.guess_timezone(10.0) is None      # Europe
    assert oc.guess_timezone(-50.0) is None     # mid-Atlantic
    assert oc.guess_timezone(139.7) is None     # Tokyo


def test_resolve_timezone_prefers_stored_then_guess_then_default():
    assert oc.resolve_timezone("America/New_York", -118.0, "America/Los_Angeles") == "America/New_York"
    assert oc.resolve_timezone(None, -118.0, "America/Denver") == "America/Los_Angeles"
    assert oc.resolve_timezone(None, None, "America/Denver") == "America/Denver"
    # a garbage stored zone falls through to the guess
    assert oc.resolve_timezone("Not/AZone", -94.6, "America/Denver") == "America/Chicago"


# --- business hours (T1.4) ----------------------------------------------------------------------


def test_business_hours_true_inside_weekday_window():
    # Wed 2026-09-16 20:00Z == 13:00 in LA (PDT), a weekday inside 8–18.
    now = datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc)
    s = oc.business_hours_status("America/Los_Angeles", now)
    assert s["in_business_hours"] is True
    assert s["local_hour"] == 13


def test_business_hours_false_at_night_and_weekend():
    # Wed 2026-09-16 06:00Z == 23:00 previous day in LA → out of hours.
    night = oc.business_hours_status("America/Los_Angeles", datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc))
    assert night["in_business_hours"] is False
    # Sunday 2026-09-20 19:00Z == 12:00 LA, but weekend → out of hours.
    weekend = oc.business_hours_status("America/Los_Angeles", datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc))
    assert weekend["in_business_hours"] is False


def test_business_hours_unknown_zone_is_none_not_false():
    s = oc.business_hours_status(None, datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc))
    assert s["in_business_hours"] is None and s["tz"] is None
    s2 = oc.business_hours_status("Not/AZone", datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc))
    assert s2["in_business_hours"] is None
    # Same key set as the valid branch, so a consumer sees one stable shape either way.
    valid = oc.business_hours_status("America/Los_Angeles", datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc))
    assert set(s.keys()) == set(valid.keys())
    assert "weekday" in s and s["weekday"] is None


def test_business_hours_accepts_naive_now_as_utc():
    s = oc.business_hours_status("America/Los_Angeles", datetime(2026, 9, 16, 20, 0))
    assert s["local_hour"] == 13


# --- callback resolution (T1.3 / T1.4) ----------------------------------------------------------


def test_resolve_callback_converts_wall_time_to_instant_and_local_date():
    r = oc.resolve_callback("2026-09-22T14:00", "America/Los_Angeles")
    # 14:00 PDT == 21:00 UTC
    assert r["next_action_at"] == "2026-09-22T21:00:00+00:00"
    assert r["next_action_due"] == "2026-09-22"
    assert r["next_action_tz"] == "America/Los_Angeles"


def test_resolve_callback_local_date_can_differ_from_utc_date():
    # 22:00 in LA on the 22nd is 05:00 UTC on the 23rd — the LOCAL date is what the caller means.
    r = oc.resolve_callback("2026-09-22T22:00", "America/Los_Angeles")
    assert r["next_action_at"] == "2026-09-23T05:00:00+00:00"
    assert r["next_action_due"] == "2026-09-22"


def test_resolve_callback_bare_date_defaults_to_morning():
    r = oc.resolve_callback("2026-09-22", "America/New_York")
    assert r["next_action_due"] == "2026-09-22"
    assert r["next_action_at"].endswith("+00:00")


def test_resolve_callback_rejects_bad_zone_and_time():
    with pytest.raises(ValueError):
        oc.resolve_callback("2026-09-22T14:00", "Not/AZone")
    with pytest.raises(ValueError):
        oc.resolve_callback("not-a-time", "America/Los_Angeles")
    with pytest.raises(ValueError):
        oc.resolve_callback("", "America/Los_Angeles")


# --- resolve_callback_fields (service transform, pure but for the default zone) ------------------


def test_resolve_callback_fields_folds_local_into_columns():
    out = svc.resolve_callback_fields(
        {"next_action": "Callback", "next_action_local": "2026-09-22T14:00", "next_action_tz": "America/Los_Angeles"},
        default_tz="America/Denver",
    )
    assert "next_action_local" not in out           # never reaches the database
    assert out["next_action"] == "Callback"
    assert out["next_action_at"] == "2026-09-22T21:00:00+00:00"
    assert out["next_action_due"] == "2026-09-22"
    assert out["next_action_tz"] == "America/Los_Angeles"


def test_resolve_callback_fields_uses_default_zone_when_unset():
    out = svc.resolve_callback_fields(
        {"next_action_local": "2026-09-22T09:00"}, default_tz="America/New_York"
    )
    assert out["next_action_tz"] == "America/New_York"
    assert out["next_action_due"] == "2026-09-22"


def test_resolve_callback_fields_null_local_clears_the_instant():
    out = svc.resolve_callback_fields({"next_action_local": None}, default_tz="America/Denver")
    assert out["next_action_at"] is None
    assert "next_action_local" not in out
    # A bare clear does not inject the default zone (it would overwrite the lead's stored zone).
    assert "next_action_tz" not in out


def test_resolve_callback_fields_clear_keeps_a_co_sent_zone():
    out = svc.resolve_callback_fields(
        {"next_action_local": None, "next_action_tz": "America/New_York"}, default_tz="America/Denver"
    )
    assert out["next_action_at"] is None
    assert out["next_action_tz"] == "America/New_York"
    assert "next_action_local" not in out


def test_resolve_callback_fields_passthrough_when_no_local():
    payload = {"next_action_due": "2026-09-22", "next_action": "Follow up"}
    assert svc.resolve_callback_fields(payload, default_tz="America/Denver") == payload


def test_resolve_callback_fields_bad_input_raises_named_error():
    with pytest.raises(svc.OutreachError) as e:
        svc.resolve_callback_fields(
            {"next_action_local": "2026-09-22T14:00", "next_action_tz": "Not/AZone"},
            default_tz="America/Denver",
        )
    assert e.value.code == "invalid_callback"
