"""Unit tests for the Drive folder resolver + the Apps Script webhook retry."""

import asyncio

import httpx
import pytest

import services.google_docs as gd
from config import settings
from services.google_docs import GoogleDocError, resolve_drive_folder


def test_type_specific_folder_wins():
    client = {
        "drive_folders": {"blog_post": "folder-blog", "service_page": "folder-svc"},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-blog"
    assert resolve_drive_folder(client, "service_page") == "folder-svc"


def test_falls_back_to_default_when_type_unset():
    client = {
        "drive_folders": {"blog_post": "folder-blog"},
        "google_drive_folder_id": "folder-default",
    }
    # location_page has no entry → default
    assert resolve_drive_folder(client, "location_page") == "folder-default"


def test_falls_back_when_no_map_at_all():
    client = {"google_drive_folder_id": "folder-default"}
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_empty_string_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": ""},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_whitespace_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": "   "},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_non_string_entry_falls_through_to_default():
    client = {
        "drive_folders": {"blog_post": 12345},
        "google_drive_folder_id": "folder-default",
    }
    assert resolve_drive_folder(client, "blog_post") == "folder-default"


def test_values_are_stripped():
    client = {"drive_folders": {"blog_post": "  folder-blog  "}, "google_drive_folder_id": "d"}
    assert resolve_drive_folder(client, "blog_post") == "folder-blog"
    assert resolve_drive_folder({"google_drive_folder_id": "  d  "}, "blog_post") == "d"


def test_returns_none_when_nothing_configured():
    assert resolve_drive_folder({"drive_folders": {}}, "use_case") is None
    assert resolve_drive_folder({}, "blog_post") is None
    # whitespace-only default → None (not a bogus "   " folder id)
    assert resolve_drive_folder({"google_drive_folder_id": "   "}, "blog_post") is None
    # non-dict drive_folders → ignored, falls to default
    assert resolve_drive_folder({"drive_folders": "oops", "google_drive_folder_id": "d"}, "blog_post") == "d"


def test_none_content_type_uses_default():
    client = {"drive_folders": {"blog_post": "x"}, "google_drive_folder_id": "d"}
    assert resolve_drive_folder(client, None) == "d"


# ── Apps Script webhook retry (publish-leg resilience) ────────────────────────
def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x")
    return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))


class _FlakyOnce:
    def __init__(self, fails: int, exc_factory):
        self.fails = fails
        self.exc_factory = exc_factory
        self.calls = 0

    async def __call__(self, body):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc_factory()
        return {"success": True, "doc_id": "d1"}


async def _no_sleep(_d):
    return None


def _prep(monkeypatch, once):
    monkeypatch.setattr(settings, "google_apps_script_url", "https://script", raising=False)
    monkeypatch.setattr(settings, "google_docs_max_retries", 2, raising=False)
    monkeypatch.setattr(gd, "_apps_script_request_once", once)
    monkeypatch.setattr(gd.asyncio, "sleep", _no_sleep)


def test_webhook_retries_5xx_then_succeeds(monkeypatch):
    once = _FlakyOnce(2, lambda: _http_status_error(503))
    _prep(monkeypatch, once)
    out = asyncio.run(gd._call_apps_script({"x": 1}))
    assert out["success"] is True
    assert once.calls == 3  # failed twice, succeeded third


def test_webhook_retries_timeout(monkeypatch):
    once = _FlakyOnce(1, lambda: httpx.ReadTimeout("t"))
    _prep(monkeypatch, once)
    out = asyncio.run(gd._call_apps_script({"x": 1}))
    assert out["success"] is True
    assert once.calls == 2


def test_webhook_4xx_not_retried(monkeypatch):
    once = _FlakyOnce(9, lambda: _http_status_error(400))
    _prep(monkeypatch, once)
    with pytest.raises(GoogleDocError):
        asyncio.run(gd._call_apps_script({"x": 1}))
    assert once.calls == 1  # fail fast


def test_webhook_app_error_not_retried(monkeypatch):
    # success=false (e.g. a bad folder id) won't self-heal — no retry.
    once = _FlakyOnce(9, lambda: GoogleDocError("apps_script_returned_error: bad_folder"))
    _prep(monkeypatch, once)
    with pytest.raises(GoogleDocError):
        asyncio.run(gd._call_apps_script({"x": 1}))
    assert once.calls == 1


def test_webhook_gives_up_after_budget(monkeypatch):
    once = _FlakyOnce(9, lambda: _http_status_error(500))
    _prep(monkeypatch, once)
    with pytest.raises(GoogleDocError):
        asyncio.run(gd._call_apps_script({"x": 1}))
    assert once.calls == 3  # initial + 2 retries


def test_webhook_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings, "google_apps_script_url", "", raising=False)
    with pytest.raises(GoogleDocError):
        asyncio.run(gd._call_apps_script({"x": 1}))
