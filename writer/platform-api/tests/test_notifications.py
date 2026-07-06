"""Unit tests for the notifications service pure helpers (no network)."""

from __future__ import annotations

from config import settings
from services import notifications


# ---------------------------------------------------------------------------
# format_email
# ---------------------------------------------------------------------------
def test_format_email_subject_and_body():
    subject, body = notifications.format_email(
        "2 ranking drops detected", "kw a dropped 7 spots.", "Acme Plumbing",
        "https://app/clients/1/rankings",
    )
    assert subject == "[Acme Plumbing] 2 ranking drops detected"
    assert "2 ranking drops detected" in body
    assert "kw a dropped 7 spots." in body
    assert "https://app/clients/1/rankings" in body


def test_format_email_no_client_no_link():
    subject, body = notifications.format_email("Title", None, None, None)
    assert subject == "Title"
    assert "Open:" not in body


# ---------------------------------------------------------------------------
# format_slack
# ---------------------------------------------------------------------------
def test_format_slack_severity_icon_and_link():
    text = notifications.format_slack("Drop", "summary", "Acme", "https://app/x", "critical")
    # Critical is in the default mention allowlist, so it leads with the broadcast.
    assert text.startswith("<!here>")
    assert "🔴" in text
    assert "*Drop*" in text and "_Acme_" in text
    assert "<https://app/x|Open in AR Tools>" in text


def test_format_slack_pings_warning_but_not_info(monkeypatch):
    monkeypatch.setattr(settings, "slack_mention_token", "here")
    monkeypatch.setattr(settings, "slack_mention_severities", "critical,warning")
    warn = notifications.format_slack("W", None, None, None, "warning")
    info = notifications.format_slack("I", None, None, None, "info")
    assert warn.startswith("<!here>")
    assert "<!here>" not in info and "<!channel>" not in info
    assert info.startswith("🔵")


def test_format_slack_mention_token_channel_and_off(monkeypatch):
    monkeypatch.setattr(settings, "slack_mention_severities", "critical,warning")
    monkeypatch.setattr(settings, "slack_mention_token", "channel")
    assert notifications.format_slack("C", None, None, None, "critical").startswith("<!channel>")
    # Empty token disables all broadcasts, even for critical.
    monkeypatch.setattr(settings, "slack_mention_token", "")
    off = notifications.format_slack("C", None, None, None, "critical")
    assert "<!here>" not in off and "<!channel>" not in off
    assert off.startswith("🔴")


# ---------------------------------------------------------------------------
# email_recipients / _deep_link (settings-driven)
# ---------------------------------------------------------------------------
def test_email_recipients_parses_and_trims(monkeypatch):
    monkeypatch.setattr(settings, "notify_email_to", " a@x.com , b@y.com ,, ")
    assert notifications.email_recipients() == ["a@x.com", "b@y.com"]


def test_deep_link_needs_base_and_path(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://app.example.com/")
    assert notifications._deep_link({"link": "/clients/1/rankings"}) == "https://app.example.com/clients/1/rankings"
    assert notifications._deep_link({}) is None
    monkeypatch.setattr(settings, "app_base_url", "")
    assert notifications._deep_link({"link": "/clients/1"}) is None


def test_channel_gating_off_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "slack_bot_token", "")
    monkeypatch.setattr(settings, "slack_default_channel", "")
    assert notifications.email_configured() is False
    assert notifications.slack_configured() is False
