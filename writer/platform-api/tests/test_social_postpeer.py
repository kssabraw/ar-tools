"""Unit tests for the PostPeer adapter's pure helpers (no network)."""

from services.social.postpeer_adapter import (
    build_connect_params,
    build_post_payload,
    classify_error,
    parse_integration,
    parse_integrations_page,
    parse_post_response,
    x_credit_cost,
)
from services.social.adapter import Integration, PostResult


def test_x_credit_cost():
    assert x_credit_cost("twitter", "hello world") == 5
    assert x_credit_cost("x", "no link here") == 5
    assert x_credit_cost("twitter", "see https://example.com") == 50
    assert x_credit_cost("twitter", "http://a.co") == 50
    assert x_credit_cost("facebook", "see https://example.com") == 1
    assert x_credit_cost("instagram", "") == 1


def test_build_connect_params():
    assert build_connect_params("p1") == {"profileId": "p1"}
    assert build_connect_params("p1", "https://cb", "app9") == {
        "profileId": "p1",
        "redirectUri": "https://cb",
        "appId": "app9",
    }
    # empty redirect/app are omitted, not sent blank
    assert build_connect_params("p1", None, None) == {"profileId": "p1"}


def test_parse_integration_reconnect_flag():
    raw = {
        "id": "abc123",
        "platform": "facebook",
        "profileId": "p1",
        "platformUserId": "9",
        "tokenStatus": {"reconnectRequired": True},
    }
    i = parse_integration(raw)
    assert isinstance(i, Integration)
    assert i.account_id == "abc123"
    assert i.platform == "facebook"
    assert i.profile_id == "p1"
    assert i.reconnect_required is True
    # no tokenStatus => healthy
    assert parse_integration({"id": "z", "platform": "x"}).reconnect_required is False


def test_parse_integrations_page():
    body = {"integrations": [{"id": "1", "platform": "twitter"}, {"id": "2", "platform": "facebook"}], "total": 5}
    items, total = parse_integrations_page(body)
    assert [i.account_id for i in items] == ["1", "2"]
    assert total == 5
    # missing total => None; empty => []
    items2, total2 = parse_integrations_page({"integrations": []})
    assert items2 == [] and total2 is None


def test_build_post_payload_one_platform():
    p = build_post_payload("facebook", "acc1", "hi", media_urls=["https://img/1.jpg"])
    assert p["content"] == "hi"
    assert p["platforms"] == [{"platform": "facebook", "accountId": "acc1"}]
    assert p["mediaItems"] == [{"type": "image", "url": "https://img/1.jpg"}]
    assert p["publishNow"] is True
    # platform_specific rides through; no media key when none
    p2 = build_post_payload("instagram", "a", "x", platform_specific={"contentType": "story"})
    assert p2["platforms"][0]["platformSpecificData"] == {"contentType": "story"}
    assert "mediaItems" not in p2


def test_parse_post_response_success_and_failure():
    ok = parse_post_response(
        {"success": True, "status": "published", "postId": "post_9",
         "platforms": [{"platform": "facebook", "success": True, "platformPostUrl": "https://fb/p/9"}]},
        "facebook",
    )
    assert isinstance(ok, PostResult)
    assert ok.ok and ok.provider_post_id == "post_9" and ok.post_url == "https://fb/p/9"

    bad = parse_post_response(
        {"status": "failed", "platforms": [{"platform": "twitter", "success": False, "error": "duplicate"}]},
        "twitter",
    )
    assert bad.ok is False and bad.detail == "duplicate"


def test_classify_error():
    assert classify_error(401, {}) == "postpeer_auth_failed"
    assert classify_error(402, {}) == "postpeer_out_of_credits"
    assert classify_error(200, {"message": "insufficient credits"}) == "postpeer_out_of_credits"
    assert classify_error(429, {}) == "postpeer_rate_limited"
    assert classify_error(403, {}) == "postpeer_forbidden"
    assert classify_error(404, {}) == "postpeer_not_found"
    assert classify_error(500, "boom") == "postpeer_server_error"
    assert classify_error(418, {}) == "postpeer_error_418"
