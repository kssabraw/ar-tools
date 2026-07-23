"""Unit tests for the GBP Posts module pure helpers (no DB / no Google)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import gbp_posts_api as api
from services import gbp_posts_service as svc


# ── v4_parent ────────────────────────────────────────────────────────────────
def test_v4_parent_from_full_forms():
    assert api.v4_parent("accounts/123", "locations/456") == "accounts/123/locations/456"


def test_v4_parent_from_bare_ids():
    assert api.v4_parent("123", "456") == "accounts/123/locations/456"


def test_v4_parent_requires_both():
    with pytest.raises(ValueError):
        api.v4_parent("", "locations/456")


# ── append_utm ───────────────────────────────────────────────────────────────
def test_append_utm_adds_params():
    out = api.append_utm("https://acme.com/roofing", "First Class Roofing")
    assert "utm_source=gbp" in out and "utm_medium=post" in out
    assert "utm_campaign=first-class-roofing" in out


def test_append_utm_preserves_existing():
    out = api.append_utm("https://acme.com/x?utm_source=news&a=1", "camp")
    assert "utm_source=news" in out  # not overwritten
    assert "a=1" in out and "utm_medium=post" in out


def test_append_utm_ignores_non_http_and_empty():
    assert api.append_utm(None, "c") is None
    assert api.append_utm("tel:+15551234", "c") == "tel:+15551234"


# ── call-to-action ───────────────────────────────────────────────────────────
def test_cta_call_needs_no_url():
    assert api.build_call_to_action("call", None) == {"actionType": "CALL"}


def test_cta_learn_more_needs_url():
    assert api.build_call_to_action("learn_more", "https://x.com") == {
        "actionType": "LEARN_MORE", "url": "https://x.com"
    }
    with pytest.raises(ValueError):
        api.build_call_to_action("learn_more", "")


def test_cta_invalid_type():
    with pytest.raises(ValueError):
        api.build_call_to_action("frobnicate", "https://x.com")


def test_cta_none_is_none():
    assert api.build_call_to_action(None, None) is None


# ── build_local_post_body ────────────────────────────────────────────────────
def test_build_standard_body():
    body = api.build_local_post_body(summary="Fresh roof, happy home.", topic_type="standard")
    assert body["topicType"] == "STANDARD"
    assert body["summary"] == "Fresh roof, happy home."
    assert body["languageCode"] == "en-US"


def test_build_body_with_cta_and_media():
    body = api.build_local_post_body(
        summary="Book now", topic_type="standard", cta_type="book",
        cta_url="https://acme.com/book", media=[{"sourceUrl": "https://cdn/x.jpg"}],
    )
    assert body["callToAction"] == {"actionType": "BOOK", "url": "https://acme.com/book"}
    assert body["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://cdn/x.jpg"}]


def test_build_body_rejects_empty_summary():
    with pytest.raises(ValueError):
        api.build_local_post_body(summary="   ", topic_type="standard")


def test_build_body_rejects_overlong_summary():
    with pytest.raises(ValueError):
        api.build_local_post_body(summary="x" * 1600, topic_type="standard")


def test_build_body_event_requires_title_and_schedule():
    with pytest.raises(ValueError):
        api.build_local_post_body(summary="Sale!", topic_type="event", event={"title": ""})
    body = api.build_local_post_body(
        summary="Grand opening", topic_type="event",
        event={"title": "Opening", "schedule": {"startDate": {"year": 2026, "month": 8, "day": 1}}},
    )
    assert body["topicType"] == "EVENT"
    assert body["event"]["title"] == "Opening"


def test_build_product_body_maps_to_standard_no_event_required():
    # 'product' is our type — Google has no PRODUCT topicType, so it publishes as
    # a STANDARD post and must NOT require an event block.
    body = api.build_local_post_body(
        summary="Our new winter roof coating keeps homes warmer.",
        topic_type="product", cta_type="shop", cta_url="https://acme.com/coating",
    )
    assert body["topicType"] == "STANDARD"
    assert body["callToAction"]["actionType"] == "SHOP"
    assert "event" not in body


def test_product_is_a_known_topic_type():
    assert "product" in api.TOPIC_TYPES


def test_build_body_offer_includes_offer_block():
    body = api.build_local_post_body(
        summary="10% off", topic_type="offer",
        event={"title": "Fall promo", "schedule": {"startDate": {"year": 2026, "month": 9, "day": 1}}},
        offer={"couponCode": "FALL10"},
    )
    assert body["offer"] == {"couponCode": "FALL10"}


# ── state + parse ────────────────────────────────────────────────────────────
def test_state_to_status():
    assert api.state_to_status("LIVE") == "live"
    assert api.state_to_status("REJECTED") == "rejected"
    assert api.state_to_status("PROCESSING") == "publishing"
    assert api.state_to_status(None) == "publishing"


def test_parse_local_post():
    parsed = api.parse_local_post({
        "name": "accounts/1/locations/2/localPosts/3", "state": "LIVE",
        "searchUrl": "https://g.co/p", "summary": "Hi", "topicType": "STANDARD",
        "createTime": "2026-07-23T00:00:00Z",
    })
    assert parsed["google_name"].endswith("/localPosts/3")
    assert parsed["status"] == "live"
    assert parsed["search_url"] == "https://g.co/p"
    assert parsed["topic_type"] == "standard"


# ── sync reconcile predicate (search_url backfill) ───────────────────────────
def test_needs_update_on_status_change():
    assert svc.post_needs_update({"status": "publishing"}, {"status": "live"}) is True


def test_needs_update_when_search_url_arrives_after_live():
    # Google fills searchUrl a bit after the post is already LIVE — must still save.
    row = {"status": "live", "search_url": None}
    live = {"status": "live", "search_url": "https://g.co/p/1"}
    assert svc.post_needs_update(row, live) is True


def test_needs_update_on_google_state_change():
    row = {"status": "live", "search_url": "u", "google_state": "PROCESSING"}
    live = {"status": "live", "search_url": "u", "google_state": "LIVE"}
    assert svc.post_needs_update(row, live) is True


def test_no_update_when_identical():
    row = {"status": "live", "search_url": "u", "google_state": "LIVE"}
    live = {"status": "live", "search_url": "u", "google_state": "LIVE"}
    assert svc.post_needs_update(row, live) is False


def test_no_update_when_live_url_empty():
    # Never clobber a stored URL with an empty one from a partial read.
    row = {"status": "live", "search_url": "https://g.co/p/1"}
    live = {"status": "live", "search_url": None}
    assert svc.post_needs_update(row, live) is False


# ── error classification ─────────────────────────────────────────────────────
def test_classify_api_not_enabled():
    assert api.classify_post_error(403, "My Business API has not been used in project") == "gbp_api_not_enabled"


def test_classify_quota():
    assert api.classify_post_error(429, "RESOURCE_EXHAUSTED") == "gbp_quota_not_granted"


def test_classify_not_manager():
    assert api.classify_post_error(403, "The caller does not have permission") == "service_account_not_a_manager_or_forbidden"


def test_classify_invalid_and_notfound():
    assert api.classify_post_error(400, "bad content") == "invalid_post_content"
    assert api.classify_post_error(404, "not found") == "post_or_location_not_found"


# ── schedule cadence math ────────────────────────────────────────────────────
def _now():
    # A fixed Thursday 2026-07-23 12:00 UTC (weekday 3).
    return datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def test_disabled_has_no_next_run():
    assert svc.compute_next_run_at(_now(), "disabled", None, None, 9) is None


def test_weekly_next_run_is_future_with_correct_dow_and_hour():
    nxt = svc.compute_next_run_at(_now(), "weekly", 0, None, 9)  # Monday 09:00
    assert nxt > _now()
    assert nxt.weekday() == 0 and nxt.hour == 9


def test_monthly_next_run_advances_when_past():
    # day_of_month 1 has already passed on the 23rd → next month.
    nxt = svc.compute_next_run_at(_now(), "monthly", None, 1, 9)
    assert nxt > _now() and nxt.day == 1


def test_biweekly_steps_14_days_from_prev():
    prev = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)  # already past _now()
    nxt = svc.compute_next_run_at(_now(), "biweekly", 0, None, 9, prev=prev)
    # prev + 14 days = 2026-08-03, still future of now.
    assert nxt == datetime(2026, 8, 3, 9, 0, tzinfo=timezone.utc)


def test_biweekly_without_prev_seeds_like_weekly():
    nxt = svc.compute_next_run_at(_now(), "biweekly", 0, None, 9)
    assert nxt > _now() and nxt.weekday() == 0


# ── scheduled-publish time validation ────────────────────────────────────────
def test_ensure_future_utc_accepts_future_and_normalizes():
    now = _now()
    future = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
    assert svc.ensure_future_utc(future, now) == future.isoformat()


def test_ensure_future_utc_treats_naive_as_utc():
    now = _now()
    naive = datetime(2026, 7, 24, 9, 0)  # no tzinfo → assume UTC
    out = svc.ensure_future_utc(naive, now)
    assert out == "2026-07-24T09:00:00+00:00"


def test_ensure_future_utc_rejects_past():
    from fastapi import HTTPException
    now = _now()
    with pytest.raises(HTTPException):
        svc.ensure_future_utc(datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc), now)


def test_ensure_future_utc_rejects_equal_now():
    from fastapi import HTTPException
    now = _now()
    with pytest.raises(HTTPException):
        svc.ensure_future_utc(now, now)


# ── timezone-aware scheduling: the hour is client-LOCAL, stored as UTC ────────
def test_weekly_hour_is_client_local_winter():
    from zoneinfo import ZoneInfo
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)  # Monday, winter (PST = UTC-8)
    nxt = svc.compute_next_run_at(now, "weekly", 0, None, 9, tz="America/Los_Angeles")
    assert nxt.utcoffset().total_seconds() == 0            # returned in UTC
    assert nxt.astimezone(la).hour == 9                    # 9am *client-local*
    assert nxt.hour == 17                                  # 09:00 PST == 17:00 UTC


def test_weekly_hour_is_client_local_dst_summer():
    from zoneinfo import ZoneInfo
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)  # summer (PDT = UTC-7)
    nxt = svc.compute_next_run_at(now, "weekly", 0, None, 9, tz="America/Los_Angeles")
    assert nxt.astimezone(la).hour == 9                    # still 9am local across DST…
    assert nxt.hour == 16                                  # …but 16:00 UTC now, not 17:00


def test_monthly_hour_is_client_local():
    from zoneinfo import ZoneInfo
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    nxt = svc.compute_next_run_at(now, "monthly", None, 1, 9, tz="America/Los_Angeles")
    assert nxt.astimezone(la).day == 1 and nxt.astimezone(la).hour == 9
    assert nxt > now


def test_unknown_tz_falls_back_to_utc():
    now = _now()
    nxt = svc.compute_next_run_at(now, "weekly", 0, None, 9, tz="Not/AZone")
    assert nxt.hour == 9  # bad tz name → UTC hour, same as tz=None


def test_none_tz_matches_legacy_utc_behavior():
    now = _now()
    assert svc.compute_next_run_at(now, "weekly", 0, None, 9, tz=None) == svc.compute_next_run_at(
        now, "weekly", 0, None, 9
    )


def test_ensure_future_utc_localizes_naive_to_client_tz():
    now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 7, 6, 9, 0)  # 9am wall-clock, meant as client-local
    out = svc.ensure_future_utc(naive, now, tz="America/Los_Angeles")
    assert out == "2026-07-06T16:00:00+00:00"  # 09:00 PDT == 16:00 UTC


# ── image validation (Google's local-post floor) ─────────────────────────────
def test_image_ok():
    assert svc.image_rejection_reason("image/jpeg", 400, 300, 50_000) is None
    assert svc.image_rejection_reason("image/png", 250, 250, 10_240) is None


def test_image_rejects_type():
    assert svc.image_rejection_reason("image/webp", 400, 400, 50_000) == "unsupported_image_type"
    assert svc.image_rejection_reason("image/gif", 400, 400, 50_000) == "unsupported_image_type"


def test_image_rejects_too_small_bytes():
    assert svc.image_rejection_reason("image/jpeg", 400, 400, 5_000) == "image_too_small_bytes"


def test_image_rejects_too_large_bytes():
    assert svc.image_rejection_reason("image/jpeg", 400, 400, 30 * 1024 * 1024) == "image_too_large"


def test_image_rejects_small_dimensions():
    assert svc.image_rejection_reason("image/jpeg", 249, 400, 50_000) == "image_dimensions_too_small"
    assert svc.image_rejection_reason("image/png", 400, 100, 50_000) == "image_dimensions_too_small"


# ── empty-trash live-post guard ──────────────────────────────────────────────
def test_is_live_on_google_true_only_when_live_and_named():
    assert svc.is_live_on_google({"status": "live", "google_name": "accounts/1/.../3"}) is True


def test_is_live_on_google_false_cases():
    assert svc.is_live_on_google({"status": "live", "google_name": None}) is False   # live but never got a name
    assert svc.is_live_on_google({"status": "draft", "google_name": None}) is False
    assert svc.is_live_on_google({"status": "rejected", "google_name": "n"}) is False
    assert svc.is_live_on_google({"status": "failed", "google_name": None}) is False


# ── auth mode selection (OAuth vs service account) ───────────────────────────
def test_auth_mode_service_account_by_default(monkeypatch):
    from config import settings
    from services import gbp_auth
    monkeypatch.setattr(settings, "google_oauth_client_id", "")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    monkeypatch.setattr(settings, "gbp_oauth_refresh_token", "")
    assert gbp_auth.oauth_configured() is False
    assert gbp_auth.auth_mode() == "service_account"


def test_auth_mode_oauth_when_fully_configured(monkeypatch):
    from config import settings
    from services import gbp_auth
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "secret")
    monkeypatch.setattr(settings, "gbp_oauth_refresh_token", "refresh")
    assert gbp_auth.oauth_configured() is True
    assert gbp_auth.auth_mode() == "oauth"


def test_auth_mode_partial_oauth_is_not_configured(monkeypatch):
    from config import settings
    from services import gbp_auth
    monkeypatch.setattr(settings, "google_oauth_client_id", "cid")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")  # missing
    monkeypatch.setattr(settings, "gbp_oauth_refresh_token", "refresh")
    assert gbp_auth.oauth_configured() is False


# ── OAuth Connect flow — signed state (pure) ─────────────────────────────────
def test_oauth_state_roundtrip():
    from services import gbp_oauth
    s = gbp_oauth.sign_state("https://app/x", "nonce", 1000)
    assert gbp_oauth.parse_state(s, 1100) == {"r": "https://app/x", "n": "nonce", "t": 1000}


def test_oauth_state_rejects_tamper():
    from services import gbp_oauth
    s = gbp_oauth.sign_state("https://app/x", "n", 1000)
    payload, sig = s.split(".", 1)
    tampered = payload + "." + ("0" * len(sig))
    assert gbp_oauth.parse_state(tampered, 1100) is None


def test_oauth_state_rejects_expired():
    from services import gbp_oauth
    s = gbp_oauth.sign_state("https://app/x", "n", 1000)
    assert gbp_oauth.parse_state(s, 1000 + 601) is None  # past the 600s window


def test_oauth_safe_return_to_blocks_open_redirect(monkeypatch):
    from config import settings
    from services import gbp_oauth
    monkeypatch.setattr(settings, "app_base_url", "https://app.example")
    assert gbp_oauth.safe_return_to("https://app.example/clients/1/gbp-posts") == "https://app.example/clients/1/gbp-posts"
    assert gbp_oauth.safe_return_to("https://evil.com/x") == "https://app.example"  # off-origin rejected
    assert gbp_oauth.safe_return_to(None) == "https://app.example"


# ── manager-invitation parsing ───────────────────────────────────────────────
def test_parse_invitation_location_name():
    from services import gbp_invitations
    inv = gbp_invitations.parse_invitation({
        "name": "accounts/1/invitations/9", "role": "MANAGER",
        "targetLocation": {"locationName": "Acme Roofing", "address": "123 St"},
    })
    assert inv == {"name": "accounts/1/invitations/9", "role": "MANAGER", "business": "Acme Roofing"}


def test_parse_invitation_account_fallback():
    from services import gbp_invitations
    inv = gbp_invitations.parse_invitation({
        "name": "accounts/1/invitations/9", "role": "MANAGER",
        "targetAccount": {"accountName": "Acme Group"},
    })
    assert inv["business"] == "Acme Group"


def test_parse_invitation_unknown_business():
    from services import gbp_invitations
    assert gbp_invitations.parse_invitation({"name": "n", "role": "MANAGER"})["business"] == "a business"


# ── client context builder ───────────────────────────────────────────────────
def test_build_client_context_includes_key_fields():
    ctx = svc.build_client_context({
        "name": "Acme Roofing", "website_url": "https://acme.com",
        "business_location": "Kansas City, MO",
        "brand_voice": {"raw_text": "Friendly and local."},
        "detected_icp": "homeowners 35-60",
    })
    assert "Acme Roofing" in ctx and "acme.com" in ctx
    assert "Kansas City" in ctx and "Friendly and local" in ctx
    assert "homeowners" in ctx
