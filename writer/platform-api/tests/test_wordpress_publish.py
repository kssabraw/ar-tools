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
    def __init__(self, status_code=201, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

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
