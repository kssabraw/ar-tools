"""Unit tests for the WordPress publish helper.

httpx is mocked — no network. Covers config validation, the success path, and
auth/error mapping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from services import wordpress_publish  # noqa: E402
from services.wordpress_publish import (  # noqa: E402
    WordPressPublishError,
    client_is_configured,
    publish_to_wordpress,
)

_CLIENT = {
    "wordpress_site_url": "https://acmehvac.com",
    "wordpress_username": "editor",
    "wordpress_app_password": "abcd efgh ijkl mnop",
}


class _FakeResponse:
    def __init__(self, status_code=201, json_data=None, text="", headers=None,
                 is_redirect=False, url="https://acmehvac.com/wp-json/wp/v2/posts"):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.headers = headers or {"content-type": "application/json"}
        self.is_redirect = is_redirect
        self.url = url

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


class _FakeClient:
    def __init__(self, response, capture):
        self._response = response
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._capture["url"] = url
        self._capture["json"] = json
        self._capture["headers"] = headers
        return self._response


def _patch(monkeypatch, response, capture):
    monkeypatch.setattr(
        wordpress_publish.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeClient(response, capture),
    )


def test_client_is_configured():
    assert client_is_configured(_CLIENT) is True
    assert client_is_configured({"wordpress_site_url": "https://x.com"}) is False
    assert client_is_configured({}) is False


@pytest.mark.asyncio
async def test_publish_success_blog_post_hits_posts_endpoint(monkeypatch):
    capture = {}
    resp = _FakeResponse(
        201,
        {"id": 42, "link": "https://acmehvac.com/?p=42", "status": "draft"},
    )
    _patch(monkeypatch, resp, capture)

    result = await publish_to_wordpress(
        client=_CLIENT, title="T", html="<p>hi</p>", status="draft", content_type="blog_post"
    )
    assert result["post_id"] == 42
    assert result["link"] == "https://acmehvac.com/?p=42"
    assert result["edit_link"] == "https://acmehvac.com/wp-admin/post.php?post=42&action=edit"
    assert capture["url"] == "https://acmehvac.com/wp-json/wp/v2/posts"
    assert capture["json"] == {"title": "T", "content": "<p>hi</p>", "status": "draft"}
    assert capture["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_slug_pins_post_url(monkeypatch):
    """An explicit slug is sent to WP so the published URL matches links computed
    against it (the fanout writer's internal links); omitted, WP derives its own."""
    capture = {}
    resp = _FakeResponse(201, {"id": 43, "link": "u", "status": "draft"})
    _patch(monkeypatch, resp, capture)
    await publish_to_wordpress(
        client=_CLIENT, title="T", html="<p>hi</p>", slug="retatrutide-dosage-guide"
    )
    assert capture["json"]["slug"] == "retatrutide-dosage-guide"


@pytest.mark.asyncio
async def test_no_slug_omits_field(monkeypatch):
    capture = {}
    resp = _FakeResponse(201, {"id": 44, "link": "u", "status": "draft"})
    _patch(monkeypatch, resp, capture)
    await publish_to_wordpress(client=_CLIENT, title="T", html="<p>hi</p>")
    assert "slug" not in capture["json"]


@pytest.mark.asyncio
async def test_service_page_hits_pages_endpoint(monkeypatch):
    capture = {}
    resp = _FakeResponse(201, {"id": 7, "link": "u", "status": "publish"})
    _patch(monkeypatch, resp, capture)
    await publish_to_wordpress(
        client=_CLIENT, title="T", html="<p>x</p>", status="publish", content_type="service_page"
    )
    assert capture["url"].endswith("/wp-json/wp/v2/pages")


@pytest.mark.asyncio
async def test_missing_config_raises():
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client={}, title="T", html="<p>x</p>")
    assert str(exc.value) == "wordpress_not_configured"


@pytest.mark.asyncio
async def test_non_https_site_rejected():
    bad = dict(_CLIENT, wordpress_site_url="http://acmehvac.com")
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=bad, title="T", html="<p>x</p>")
    assert str(exc.value) == "wordpress_site_url_must_be_https"


@pytest.mark.asyncio
async def test_invalid_status_rejected():
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>", status="trash")
    assert str(exc.value) == "invalid_status"


@pytest.mark.asyncio
async def test_empty_content_rejected():
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=_CLIENT, title="T", html="   ")
    assert str(exc.value) == "content_is_empty"


@pytest.mark.asyncio
async def test_auth_failure_maps_to_auth_error(monkeypatch):
    capture = {}
    _patch(monkeypatch, _FakeResponse(401, {}, text="bad creds"), capture)
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>")
    assert str(exc.value) == "wordpress_auth_failed"


# ── SEOPress meta title + on-page H1 routing ─────────────────────────────────

@pytest.mark.asyncio
async def test_seo_title_routed_to_seopress_meta(monkeypatch):
    """A distinct SEO title lands in SEOPress's meta-title field, separate from
    the WordPress post title (which is the on-page H1)."""
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(
        client=_CLIENT,
        title="Retatrutide Dosage: mg Breakdown (2026)",
        seo_title="Retatrutide Dosage 2026: Starting mg, Escalation, Max 12mg",
        html="<p>x</p>",
    )
    assert capture["json"]["title"] == "Retatrutide Dosage: mg Breakdown (2026)"
    assert capture["json"]["meta"] == {
        "_seopress_titles_title": "Retatrutide Dosage 2026: Starting mg, Escalation, Max 12mg"
    }


@pytest.mark.asyncio
async def test_seo_title_equal_to_title_omits_meta(monkeypatch):
    """No SEOPress meta when the SEO title isn't distinct from the post title."""
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(client=_CLIENT, title="Same Title", seo_title="same title", html="<p>x</p>")
    assert "meta" not in capture["json"]


@pytest.mark.asyncio
async def test_no_seo_title_omits_meta(monkeypatch):
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>")
    assert "meta" not in capture["json"]


@pytest.mark.asyncio
async def test_strip_leading_h1_removes_duplicate_body_h1(monkeypatch):
    """With strip_leading_h1, the body's own leading H1 is dropped (the post title
    supplies the page's H1 under most themes)."""
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(
        client=_CLIENT, title="The Heading", html="<h1>The Heading</h1>\n<h2>Body</h2>",
        strip_leading_h1=True,
    )
    assert "<h1>" not in capture["json"]["content"]
    assert capture["json"]["content"].lstrip().startswith("<h2>")


@pytest.mark.asyncio
async def test_leading_h1_kept_by_default(monkeypatch):
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(client=_CLIENT, title="T", html="<h1>Keep</h1><h2>Body</h2>")
    assert "<h1>Keep</h1>" in capture["json"]["content"]


# ── ?rest_route= fallback for Plain permalinks ───────────────────────────────

class _TwoResponseClient:
    """Returns the first response on the primary URL and the second on the fallback."""

    def __init__(self, responses, capture):
        self._responses = list(responses)
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._capture.setdefault("urls", []).append(url)
        self._capture["json"] = json
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_html_response_triggers_rest_route_fallback(monkeypatch):
    """A 2xx that returns HTML (Plain permalinks serving the theme) retries the
    ?rest_route= form, which succeeds."""
    capture = {}
    html_resp = _FakeResponse(200, {}, text="<!doctype html><html>...", headers={"content-type": "text/html"})
    ok_resp = _FakeResponse(201, {"id": 9, "link": "u", "status": "draft"})
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient",
        lambda *a, **k: _TwoResponseClient([html_resp, ok_resp], capture),
    )
    result = await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>")
    assert result["post_id"] == 9
    assert capture["urls"] == [
        "https://acmehvac.com/wp-json/wp/v2/posts",
        "https://acmehvac.com/?rest_route=/wp/v2/posts",
    ]


@pytest.mark.asyncio
async def test_html_response_on_both_routes_raises_not_json(monkeypatch):
    capture = {}
    html_resp = lambda: _FakeResponse(200, {}, text="<html>x", headers={"content-type": "text/html"})
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient",
        lambda *a, **k: _TwoResponseClient([html_resp(), html_resp()], capture),
    )
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>")
    assert str(exc.value) == "wordpress_rest_not_json"


@pytest.mark.asyncio
async def test_redirect_response_raises_rest_redirect(monkeypatch):
    capture = {}
    redir = lambda: _FakeResponse(301, {}, headers={"location": "https://acmehvac.com/login"}, is_redirect=True)
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient",
        lambda *a, **k: _TwoResponseClient([redir(), redir()], capture),
    )
    with pytest.raises(WordPressPublishError) as exc:
        await publish_to_wordpress(client=_CLIENT, title="T", html="<p>x</p>")
    assert str(exc.value) == "wordpress_rest_redirect"


# ── media sideload ───────────────────────────────────────────────────────────

class _ImgResponse:
    def __init__(self, content=b"\xff\xd8\xff", headers=None, status_code=200):
        self.content = content
        self.headers = headers or {"content-type": "image/jpeg"}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


class _SideloadClient:
    """Fake client routing GET→image bytes, POST /media→attachment, POST→post."""

    def __init__(self, capture):
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, follow_redirects=False):
        self._capture.setdefault("fetched", []).append(url)
        return _ImgResponse()

    async def post(self, url, json=None, content=None, headers=None):
        if url.endswith("/media"):
            self._capture.setdefault("media_posts", []).append(headers)
            return _FakeResponse(
                201, {"id": 99, "source_url": "https://acmehvac.com/wp-content/x.jpg"}
            )
        self._capture["json"] = json
        return _FakeResponse(201, {"id": 5, "link": "u", "status": "draft", "featured_media": 99})


@pytest.mark.asyncio
async def test_external_image_is_sideloaded_and_rewritten(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient", lambda *a, **k: _SideloadClient(capture)
    )
    html = '<p>hi</p><img src="https://cdn.example.com/hero.jpg" alt="h" />'
    result = await publish_to_wordpress(client=_CLIENT, title="T", html=html)

    # The image was fetched + uploaded, the src rewritten to the WP URL, and the
    # first upload became the featured image.
    assert capture["fetched"] == ["https://cdn.example.com/hero.jpg"]
    assert "https://acmehvac.com/wp-content/x.jpg" in capture["json"]["content"]
    assert "cdn.example.com" not in capture["json"]["content"]
    assert capture["json"]["featured_media"] == 99
    assert result["featured_media"] == 99


@pytest.mark.asyncio
async def test_image_already_on_wp_host_is_not_sideloaded(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient", lambda *a, **k: _SideloadClient(capture)
    )
    html = '<img src="https://acmehvac.com/wp-content/already.jpg" alt="x" />'
    await publish_to_wordpress(client=_CLIENT, title="T", html=html)
    assert "fetched" not in capture  # no fetch/upload for same-host images
    assert "featured_media" not in capture["json"]


@pytest.mark.asyncio
async def test_sideload_disabled_skips_media(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient", lambda *a, **k: _SideloadClient(capture)
    )
    html = '<img src="https://cdn.example.com/hero.jpg" alt="h" />'
    await publish_to_wordpress(client=_CLIENT, title="T", html=html, sideload_images=False)
    assert "fetched" not in capture
    assert "cdn.example.com" in capture["json"]["content"]


@pytest.mark.asyncio
async def test_explicit_featured_image_is_uploaded_and_set(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        wordpress_publish.httpx, "AsyncClient", lambda *a, **k: _SideloadClient(capture)
    )
    # Body has no images; the explicit featured image is fetched + set.
    await publish_to_wordpress(
        client=_CLIENT,
        title="T",
        html="<p>no imgs</p>",
        featured_image_url="https://cdn.example.com/hero.jpg",
    )
    assert capture["fetched"] == ["https://cdn.example.com/hero.jpg"]
    assert capture["json"]["featured_media"] == 99
