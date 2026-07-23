"""Unit tests for services.gbp_timezone pure helpers."""

from __future__ import annotations

from services import gbp_timezone as tz


def test_parse_timezone_id_ok():
    assert (
        tz.parse_timezone_id({"status": "OK", "timeZoneId": "America/Los_Angeles"})
        == "America/Los_Angeles"
    )


def test_parse_timezone_id_non_ok_status():
    assert tz.parse_timezone_id({"status": "ZERO_RESULTS", "timeZoneId": "X"}) is None


def test_parse_timezone_id_missing_id():
    assert tz.parse_timezone_id({"status": "OK"}) is None
    assert tz.parse_timezone_id({"status": "OK", "timeZoneId": ""}) is None


def test_parse_timezone_id_malformed():
    assert tz.parse_timezone_id(None) is None
    assert tz.parse_timezone_id("nope") is None


def test_resolve_timezone_no_coords_is_none():
    # No key/coords → no network call, just None.
    assert tz.resolve_timezone(None, None, api_key="k") is None


def test_ensure_client_timezone_returns_stored_without_derivation():
    # A stored timezone short-circuits before any derivation or DB write.
    assert (
        tz.ensure_client_timezone(
            {"id": "c1", "timezone": "America/New_York", "gbp": {}}
        )
        == "America/New_York"
    )
