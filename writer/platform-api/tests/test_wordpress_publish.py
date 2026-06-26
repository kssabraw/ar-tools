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
