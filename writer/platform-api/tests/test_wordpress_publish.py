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
    def _factory(*a, **k):
        # The client-level kwargs matter: the default headers set there (notably
        # User-Agent) ride every request the helper makes.
        capture["client_kwargs"] = k
        return _FakeClient(response, capture)

    monkeypatch.setattr(wordpress_publish.httpx, "AsyncClient", _factory)


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
async def test_requests_carry_a_browser_user_agent(monkeypatch):
    """Managed WP hosts' bot filters (SiteGround's Anti-Bot AI among them) answer
    httpx's default `python-httpx/x.y` UA with a captcha page instead of the API
    response — an authenticated, otherwise-valid publish then fails as a 400. The
    UA is set on the client so every request in the module carries it."""
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "https://acmehvac.com/?p=1"}), capture)

    await publish_to_wordpress(
        client=_CLIENT, title="T", html="<p>hi</p>", status="draft", content_type="blog_post"
    )
    ua = capture["client_kwargs"]["headers"]["User-Agent"]
    assert "httpx" not in ua.lower()
    assert ua.startswith("Mozilla/")
    assert capture["headers"]["Accept"] == "application/json"


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
async def test_seo_title_routed_to_seo_plugin_meta(monkeypatch):
    """A distinct SEO title lands in each supported SEO plugin's meta-title field
    (SEOPress, Rank Math, Yoast), separate from the WordPress post title (the
    H1). The site keeps whichever key its installed plugin registered."""
    capture = {}
    _patch(monkeypatch, _FakeResponse(201, {"id": 1, "link": "u", "status": "draft"}), capture)
    await publish_to_wordpress(
        client=_CLIENT,
        title="Retatrutide Dosage: mg Breakdown (2026)",
        seo_title="Retatrutide Dosage 2026: Starting mg, Escalation, Max 12mg",
        html="<p>x</p>",
    )
    assert capture["json"]["title"] == "Retatrutide Dosage: mg Breakdown (2026)"
    seo = "Retatrutide Dosage 2026: Starting mg, Escalation, Max 12mg"
    assert capture["json"]["meta"] == {
        "_seopress_titles_title": seo,
        "rank_math_title": seo,
        "_yoast_wpseo_title": seo,
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


def test_header_summary_redacts_cookie_values_and_keeps_names():
    """Response headers go into the diagnostic log line, but a challenge's
    Set-Cookie value is an opaque token — the cookie's presence is the signal we
    need, so the name survives and the value does not."""
    resp = httpx.Response(
        400,
        headers=[
            ("content-type", "text/html"),
            ("server", "nginx"),
            ("set-cookie", "sgcaptcha_token=abc123secret; Path=/"),
            ("set-cookie", "wordpress_test=deadbeef; Path=/"),
        ],
    )
    summary = wordpress_publish._header_summary(resp)
    assert "content-type: text/html" in summary
    assert "server: nginx" in summary
    # Both cookies are named, neither value leaks.
    assert "sgcaptcha_token=<redacted>" in summary
    assert "wordpress_test=<redacted>" in summary
    assert "abc123secret" not in summary
    assert "deadbeef" not in summary


def test_header_summary_is_bounded():
    """A chatty edge can't flood the log line."""
    resp = httpx.Response(400, headers=[(f"x-h{i}", "v" * 50) for i in range(50)])
    assert len(wordpress_publish._header_summary(resp)) <= wordpress_publish._LOGGED_HEADER_MAX


def test_header_summary_never_raises_on_a_plain_mapping():
    """The helper runs inside the failure paths. If it could raise it would
    replace a specific error code with a generic one, so a headers object it
    doesn't understand degrades to a placeholder instead of blowing up."""
    class _Odd:
        headers = {"content-type": "text/html", "set-cookie": "t=secret"}

    summary = wordpress_publish._header_summary(_Odd())
    assert "content-type: text/html" in summary
    assert "t=<redacted>" in summary
    assert "secret" not in summary

    class _Hostile:
        @property
        def headers(self):
            raise RuntimeError("boom")

    assert wordpress_publish._header_summary(_Hostile()) == "<unavailable>"


class _HeaderCaptureClient:
    """Fake client recording BOTH the client-level headers and the per-request
    headers, so a test can tell the difference between the two."""

    def __init__(self, capture, client_kwargs):
        self._capture = capture
        self._capture["client_headers"] = client_kwargs.get("headers") or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, follow_redirects=False):
        self._capture.setdefault("fetched", []).append(url)
        return _ImgResponse()

    async def post(self, url, json=None, content=None, headers=None):
        if url.endswith("/media"):
            self._capture["media_headers"] = headers
            return _FakeResponse(
                201, {"id": 99, "source_url": "https://acmehvac.com/wp-content/x.jpg"}
            )
        self._capture["create_headers"] = headers
        return _FakeResponse(201, {"id": 5, "link": "u", "status": "draft"})


def _patch_client(monkeypatch, capture):
    monkeypatch.setattr(
        wordpress_publish.httpx,
        "AsyncClient",
        lambda *a, **k: _HeaderCaptureClient(capture, k),
    )


@pytest.mark.asyncio
async def test_publisher_header_sent_on_wp_requests_when_configured(monkeypatch):
    monkeypatch.setattr(
        wordpress_publish.settings, "wordpress_publisher_header_value", "s3cret-token"
    )
    monkeypatch.setattr(
        wordpress_publish.settings, "wordpress_publisher_header_name", "X-Publisher-Tool"
    )
    capture = {}
    _patch_client(monkeypatch, capture)
    await publish_to_wordpress(
        client=_CLIENT,
        title="T",
        html='<p>hi</p><img src="https://cdn.example.com/hero.jpg" />',
    )
    # Both the post create and the media upload carry it.
    assert capture["create_headers"]["X-Publisher-Tool"] == "s3cret-token"
    assert capture["media_headers"]["X-Publisher-Tool"] == "s3cret-token"


@pytest.mark.asyncio
async def test_publisher_header_omitted_entirely_when_unconfigured(monkeypatch):
    monkeypatch.setattr(wordpress_publish.settings, "wordpress_publisher_header_value", "")
    capture = {}
    _patch_client(monkeypatch, capture)
    await publish_to_wordpress(client=_CLIENT, title="T", html="<p>hi</p>")
    assert not any(
        k.lower() == "x-publisher-tool" for k in capture["create_headers"]
    ), "no header should be sent at all when no value is configured"


@pytest.mark.asyncio
async def test_publisher_header_never_leaks_to_third_party_image_hosts(monkeypatch):
    """The publish client also GETs source images from arbitrary CDNs. The token
    is a shared secret, so it must be per-request on WP-bound calls only — never
    a client-level default that rides along to every host we fetch from."""
    monkeypatch.setattr(
        wordpress_publish.settings, "wordpress_publisher_header_value", "s3cret-token"
    )
    capture = {}
    _patch_client(monkeypatch, capture)
    await publish_to_wordpress(
        client=_CLIENT,
        title="T",
        html='<p>hi</p><img src="https://cdn.example.com/hero.jpg" />',
    )
    # The external image really was fetched on this client...
    assert capture["fetched"] == ["https://cdn.example.com/hero.jpg"]
    # ...and the client-level headers, which that GET inherits, must not carry it.
    client_headers = {str(k).lower(): v for k, v in dict(capture["client_headers"]).items()}
    assert "x-publisher-tool" not in client_headers
    assert "s3cret-token" not in str(client_headers)


# --- SSH publish transport -------------------------------------------------

def _ssh_settings(monkeypatch, **over):
    vals = {
        "wordpress_ssh_client_ids": "client-1",
        "wordpress_ssh_host": "ssh.example.com",
        "wordpress_ssh_port": 18765,
        "wordpress_ssh_username": "u16-abc",
        "wordpress_ssh_private_key": "-----BEGIN KEY-----\nx\n-----END KEY-----",
        "wordpress_ssh_wp_path": "/home/u16-abc/www/example.com/public_html",
        "wordpress_ssh_known_host": "",
    }
    vals.update(over)
    for k, v in vals.items():
        monkeypatch.setattr(wordpress_publish.settings, k, v)


def test_ssh_disabled_by_default(monkeypatch):
    monkeypatch.setattr(wordpress_publish.settings, "wordpress_ssh_client_ids", "")
    assert wordpress_publish._ssh_enabled_for({"id": "client-1"}) is False


def test_ssh_only_for_listed_clients(monkeypatch):
    _ssh_settings(monkeypatch)
    assert wordpress_publish._ssh_enabled_for({"id": "client-1"}) is True
    # An interim workaround must never leak to other clients.
    assert wordpress_publish._ssh_enabled_for({"id": "client-2"}) is False


def test_ssh_refuses_when_listed_but_unconfigured(monkeypatch):
    _ssh_settings(monkeypatch, wordpress_ssh_private_key="")
    assert wordpress_publish._ssh_enabled_for({"id": "client-1"}) is False


class _FakeSSHResult:
    def __init__(self, stdout, exit_status=0, stderr=""):
        self.stdout, self.exit_status, self.stderr = stdout, exit_status, stderr


class _FakeSSHConn:
    def __init__(self, capture, result):
        self._capture, self._result = capture, result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, command, input=None, check=False):
        self._capture["command"] = command
        self._capture["stdin"] = input
        return self._result


def _fake_asyncssh(monkeypatch, capture, result):
    import types
    mod = types.ModuleType("asyncssh")
    mod.import_private_key = lambda pem: f"key({len(pem)})"

    def connect(host, **kw):
        capture["host"] = host
        capture["connect_kwargs"] = kw
        return _FakeSSHConn(capture, result)

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "asyncssh", mod)
    return capture


@pytest.mark.asyncio
async def test_ssh_publish_returns_rest_shaped_result(monkeypatch):
    _ssh_settings(monkeypatch)
    capture = _fake_asyncssh(
        monkeypatch, {}, _FakeSSHResult("4321\nhttps://example.com/hello\n")
    )
    client = dict(_CLIENT, id="client-1")
    result = await publish_to_wordpress(
        client=client, title="Hello", html="<p>body</p>", status="publish"
    )
    assert result["post_id"] == 4321
    assert result["link"] == "https://example.com/hello"
    assert result["status"] == "publish"
    assert result["featured_media"] is None
    # Body goes over stdin, never inside the command.
    assert capture["stdin"] == "<p>body</p>"
    assert "<p>body</p>" not in capture["command"]
    assert "wp post create -" in capture["command"]


@pytest.mark.asyncio
async def test_ssh_publish_shell_quotes_hostile_title(monkeypatch):
    """A title is attacker-influenced content in the sense that matters here: it
    is interpolated into a remote shell command."""
    _ssh_settings(monkeypatch)
    capture = _fake_asyncssh(monkeypatch, {}, _FakeSSHResult("7\nhttps://x/y\n"))
    nasty = "Title'; rm -rf / #"
    await publish_to_wordpress(
        client=dict(_CLIENT, id="client-1"), title=nasty, html="<p>b</p>", status="draft"
    )
    import shlex
    # Parse the command the way a shell would rather than string-matching: the
    # title must survive as ONE argument, and must not introduce a command.
    tokens = shlex.split(capture["command"])
    assert f"--post_title={nasty}" in tokens, "title must be a single intact argument"
    assert "rm" not in tokens, "title must not be able to introduce a command"


@pytest.mark.asyncio
async def test_ssh_publish_refuses_images_rather_than_dropping_them(monkeypatch):
    _ssh_settings(monkeypatch)
    _fake_asyncssh(monkeypatch, {}, _FakeSSHResult("1\nl\n"))
    with pytest.raises(wordpress_publish.WordPressPublishError) as exc:
        await publish_to_wordpress(
            client=dict(_CLIENT, id="client-1"),
            title="T",
            html='<p>x</p><img src="https://cdn.example.com/a.jpg" />',
        )
    assert str(exc.value) == "wordpress_ssh_images_unsupported"


@pytest.mark.asyncio
async def test_ssh_publish_surfaces_wpcli_failure(monkeypatch):
    _ssh_settings(monkeypatch)
    _fake_asyncssh(monkeypatch, {}, _FakeSSHResult("", exit_status=1, stderr="boom"))
    with pytest.raises(wordpress_publish.WordPressPublishError) as exc:
        await publish_to_wordpress(
            client=dict(_CLIENT, id="client-1"), title="T", html="<p>x</p>"
        )
    assert str(exc.value) == "wordpress_ssh_wpcli_error_1"


@pytest.mark.asyncio
async def test_rest_path_untouched_for_other_clients(monkeypatch):
    """The client not on the SSH list still goes over REST."""
    _ssh_settings(monkeypatch)
    capture = {}
    _patch_client(monkeypatch, capture)
    await publish_to_wordpress(
        client=dict(_CLIENT, id="client-2"), title="T", html="<p>x</p>"
    )
    assert "create_headers" in capture  # the REST client was used
