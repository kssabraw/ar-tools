"""Unit tests for the PostForMe adapter (services/social/postforme_adapter.py) + the
provider-aware factory (services/social.get_adapter). Pure helpers/parsers have no network;
the live post() flow is exercised against a fake httpx client (no real HTTP)."""

import httpx
import pytest
from fastapi import HTTPException

from services.social import postforme_adapter as pfm


# ── platform mapping ──────────────────────────────────────────────────────────

def test_platform_mapping_twitter_is_x():
    assert pfm.to_pfm_platform("twitter") == "x"
    assert pfm.to_pfm_platform("X") == "x"
    assert pfm.to_pfm_platform("instagram") == "instagram"
    assert pfm.from_pfm_platform("x") == "twitter"
    assert pfm.from_pfm_platform("facebook") == "facebook"


# ── media / payload builders ──────────────────────────────────────────────────

def test_normalize_media_is_url_only():
    out = pfm.normalize_media([
        {"type": "image", "url": "a"},
        {"type": "video", "url": "b"},
        "c",              # bare string → image url
        {"type": "image", "url": ""},   # dropped (no url)
        {"nope": 1},      # dropped
    ])
    assert out == [{"url": "a"}, {"url": "b"}, {"url": "c"}]


def test_build_auth_url_payload():
    p = pfm.build_auth_url_payload("twitter", external_id="client-1", redirect_uri="https://x/cb")
    assert p["platform"] == "x"              # mapped
    assert p["external_id"] == "client-1"
    assert p["permissions"] == ["posts"]     # default
    assert p["redirect_url_override"] == "https://x/cb"
    # no external_id / redirect when absent
    p2 = pfm.build_auth_url_payload("instagram")
    assert p2 == {"platform": "instagram", "permissions": ["posts"]}


def test_build_post_payload_shapes():
    p = pfm.build_post_payload(
        "spc_1", "twitter", "hello",
        media=[{"type": "image", "url": "u"}],
        platform_specific={"title": "T"},
        external_id="ref-1",
    )
    assert p["caption"] == "hello"
    assert p["social_accounts"] == ["spc_1"]
    assert p["media"] == [{"url": "u"}]
    assert p["platform_configurations"] == {"x": {"title": "T"}}   # keyed by mapped platform
    assert p["external_id"] == "ref-1"
    assert "scheduled_at" not in p          # always publish-now (we schedule ourselves)
    # minimal
    assert pfm.build_post_payload("spc_2", "facebook", "hi") == {
        "caption": "hi", "social_accounts": ["spc_2"]
    }


def test_build_post_payload_youtube_title_config():
    # A YouTube post carries its title (+ config) under platform_configurations.youtube
    # — the passthrough already nests it at the adapter edge (no youtube-specific code).
    p = pfm.build_post_payload(
        "spc_yt", "youtube", "video description",
        media=[{"type": "video", "url": "https://v/a.mp4"}],
        platform_specific={"title": "My Video", "privacy_status": "public", "made_for_kids": False},
    )
    assert p["media"] == [{"url": "https://v/a.mp4"}]
    assert p["platform_configurations"] == {
        "youtube": {"title": "My Video", "privacy_status": "public", "made_for_kids": False}
    }


def test_placement_config_reels_stories_ig_fb_only():
    # Instagram + Facebook route reel/story via placement; timeline is the default.
    assert pfm.placement_config("instagram", "reel") == {"placement": "reels"}
    assert pfm.placement_config("instagram", "story") == {"placement": "stories"}
    assert pfm.placement_config("facebook", "reel") == {"placement": "reels"}
    assert pfm.placement_config("facebook", "story") == {"placement": "stories"}
    # feed / carousel / other formats → no placement (default timeline)
    assert pfm.placement_config("instagram", "feed") == {}
    assert pfm.placement_config("instagram", "carousel") == {}
    # platforms without placement support → never set it
    assert pfm.placement_config("twitter", "reel") == {}
    assert pfm.placement_config("pinterest", "story") == {}


def test_build_post_payload_maps_format_to_placement():
    # A reel with no extra platform config → placement-only block.
    p = pfm.build_post_payload("spc_1", "instagram", "cap",
                               media=[{"type": "video", "url": "v"}], fmt="reel")
    assert p["platform_configurations"] == {"instagram": {"placement": "reels"}}
    # A story merges placement INTO any user platform_specific block.
    p2 = pfm.build_post_payload("spc_1", "instagram", "",
                                platform_specific={"collaborators": ["x"]}, fmt="story")
    assert p2["platform_configurations"] == {
        "instagram": {"collaborators": ["x"], "placement": "stories"}
    }
    # A feed post carries no placement (unchanged from before).
    p3 = pfm.build_post_payload("spc_1", "instagram", "cap",
                                media=[{"type": "image", "url": "u"}], fmt="feed")
    assert "platform_configurations" not in p3
    # A reel on a platform without placement support (twitter) → no config block.
    assert "platform_configurations" not in pfm.build_post_payload("spc_1", "twitter", "hi", fmt="reel")


# ── account parsing ───────────────────────────────────────────────────────────

def test_parse_account_maps_fields_and_reconnect():
    i = pfm.parse_account({
        "id": "spc_9", "platform": "x", "username": "brand", "user_id": "u9",
        "external_id": "client-1", "status": "connected",
    })
    assert i.account_id == "spc_9"
    assert i.platform == "twitter"          # x → twitter
    assert i.handle == "brand"
    assert i.platform_user_id == "u9"
    assert i.profile_id == "client-1"
    assert i.reconnect_required is False
    # disconnected ⇒ reconnect_required (no separate flag)
    assert pfm.parse_account({"id": "s", "platform": "facebook", "status": "disconnected"}).reconnect_required is True


def test_parse_accounts_page_reads_data_and_total():
    page, total = pfm.parse_accounts_page({
        "data": [{"id": "a", "platform": "instagram"}, "junk", {"id": "b", "platform": "x"}],
        "meta": {"total": 2},
    })
    assert [i.account_id for i in page] == ["a", "b"]   # non-dict skipped
    assert total == 2
    assert pfm.parse_accounts_page({}) == ([], None)


# ── post-create + result parsing (async result shape) ─────────────────────────

def test_parse_post_create():
    assert pfm.parse_post_create({"id": "post_1", "status": "processing"}) == ("post_1", "processing")
    assert pfm.parse_post_create({}) == (None, "")


def test_result_row_for_account_match_and_fallback():
    rows = [{"social_account_id": "a", "success": True}, {"social_account_id": "b", "success": False}]
    assert pfm._result_row_for_account(rows, "b")["success"] is False
    # single-row fallback when the account key doesn't match
    assert pfm._result_row_for_account([{"success": True}], "zzz") is not None
    # ambiguous (2 rows, no match) → None
    assert pfm._result_row_for_account(rows, "zzz") is None


def test_parse_result_row_success_and_failure():
    ok = pfm.parse_result_row(
        {"success": True, "platform_data": {"id": "pp1", "url": "https://x.com/p/1"}}, "twitter", "post_1")
    assert ok.ok and ok.post_url == "https://x.com/p/1" and ok.provider_post_id == "pp1"
    bad = pfm.parse_result_row({"success": False, "error": "bad media"}, "instagram", "post_2")
    assert not bad.ok and bad.detail == "bad media" and bad.provider_post_id == "post_2"


def test_accepted_result_reflects_acceptance():
    acc = pfm.accepted_result("twitter", "post_1", "processing", {"id": "post_1"})
    assert acc.ok and acc.post_url is None and acc.provider_post_id == "post_1"
    # an explicit non-accepted status is not ok
    assert pfm.accepted_result("twitter", "post_1", "failed", {}).ok is False


# ── error classification ──────────────────────────────────────────────────────

def test_classify_error_codes():
    assert pfm.classify_error(401, {}) == "postforme_auth_failed"
    assert pfm.classify_error(402, {}) == "postforme_out_of_quota"
    assert pfm.classify_error(400, {"message": "quota exceeded"}) == "postforme_out_of_quota"  # message-keyed
    assert pfm.classify_error(400, {}) == "postforme_error_400"  # plain fall-through
    assert pfm.classify_error(429, {}) == "postforme_rate_limited"
    assert pfm.classify_error(403, {}) == "postforme_forbidden"
    assert pfm.classify_error(404, {}) == "postforme_not_found"
    assert pfm.classify_error(422, {}) == "postforme_invalid_request"
    assert pfm.classify_error(500, {}) == "postforme_server_error"
    assert pfm.classify_error(418, "teapot") == "postforme_error_418"


# ── adapter infra ─────────────────────────────────────────────────────────────

def test_headers_require_key():
    with pytest.raises(HTTPException) as ei:
        pfm.PostForMeAdapter(api_key="").check_auth()
    assert ei.value.detail == "social_not_configured"


# ── live post() flow against a fake httpx client ──────────────────────────────

class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(body)

    def json(self):
        return self._body


class _FakeClient:
    """Routes POST /social-posts and GET /social-post-results to queued responses."""

    def __init__(self, *, create, results_pages):
        self._create = create
        self._results_pages = list(results_pages)  # each GET pops the next page
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None, params=None):
        self.calls.append(("POST", url, json))
        return self._create

    def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, params))
        page = self._results_pages.pop(0) if self._results_pages else _Resp(200, {"data": []})
        return page


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(pfm.httpx, "Client", lambda *a, **k: fake)
    monkeypatch.setattr(pfm.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pfm.settings, "social_postforme_result_poll_attempts", 3)
    monkeypatch.setattr(pfm.settings, "social_postforme_result_poll_interval_secs", 0)


def test_post_returns_result_when_it_arrives(monkeypatch):
    fake = _FakeClient(
        create=_Resp(200, {"id": "post_1", "status": "processing"}),
        results_pages=[
            _Resp(200, {"data": []}),  # first poll: not ready
            _Resp(200, {"data": [{"social_account_id": "spc_1", "success": True,
                                  "platform_data": {"id": "pp1", "url": "https://x.com/p/1"}}]}),
        ],
    )
    _patch_client(monkeypatch, fake)
    r = pfm.PostForMeAdapter(api_key="k").post("spc_1", "twitter", "hi")
    assert r.ok and r.post_url == "https://x.com/p/1" and r.provider_post_id == "pp1"


def test_post_returns_accepted_when_no_result_in_window(monkeypatch):
    fake = _FakeClient(
        create=_Resp(200, {"id": "post_2", "status": "processing"}),
        results_pages=[_Resp(200, {"data": []})],  # always empty → poll exhausts
    )
    _patch_client(monkeypatch, fake)
    r = pfm.PostForMeAdapter(api_key="k").post("spc_1", "twitter", "hi")
    assert r.ok and r.post_url is None and r.provider_post_id == "post_2"


def test_post_surfaces_platform_failure(monkeypatch):
    fake = _FakeClient(
        create=_Resp(200, {"id": "post_3", "status": "processing"}),
        results_pages=[_Resp(200, {"data": [{"social_account_id": "spc_1", "success": False,
                                             "error": "rejected by platform"}]})],
    )
    _patch_client(monkeypatch, fake)
    r = pfm.PostForMeAdapter(api_key="k").post("spc_1", "twitter", "hi")
    assert not r.ok and r.detail == "rejected by platform"


def test_post_raises_classified_error_on_create_failure(monkeypatch):
    fake = _FakeClient(create=_Resp(401, {"message": "bad key"}), results_pages=[])
    _patch_client(monkeypatch, fake)
    with pytest.raises(HTTPException) as ei:
        pfm.PostForMeAdapter(api_key="k").post("spc_1", "twitter", "hi")
    assert ei.value.detail == "postforme_auth_failed"


# ── factory ───────────────────────────────────────────────────────────────────

def test_get_adapter_selects_provider(monkeypatch):
    import services.social as social

    monkeypatch.setattr(social.settings, "social_posting_provider", "postforme")
    monkeypatch.setattr("services.social.credentials.get_client_key", lambda cid: "key-123")
    a = social.get_adapter(client_id="c1")
    assert isinstance(a, pfm.PostForMeAdapter) and a._api_key == "key-123"

    monkeypatch.setattr(social.settings, "social_posting_provider", "postpeer")
    from services.social.postpeer_adapter import PostPeerAdapter
    assert isinstance(social.get_adapter(client_id="c1"), PostPeerAdapter)

    monkeypatch.setattr(social.settings, "social_posting_provider", "nope")
    with pytest.raises(HTTPException):
        social.get_adapter()
