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


# ---------------------------------------------------------------------------
# resolve_slack_channel — PM/PACE kinds route to the dedicated PACE channel
# ---------------------------------------------------------------------------
def test_pace_kinds_route_to_pace_channel():
    # PACE's own producers and the native task_* notifications all go to PACE.
    for kind in (
        "pace_digest", "pace_chase_plan", "pace_escalation", "pace_report",
        "task_assigned", "task_mention", "task_comment", "task_month_generated",
        "task_overload", "task_due", "task_nudge",
    ):
        assert notifications.resolve_slack_channel(kind, None, "C_PACE") == "C_PACE", kind


def test_non_pm_kinds_stay_on_default_channel():
    # Strategy + SEO alerts return None → the sender uses slack_default_channel,
    # so the PACE channel never captures strategy chatter.
    for kind in ("strategy_review", "rank_drop", "maps_drop", "brand_visibility", "run_failed"):
        assert notifications.resolve_slack_channel(kind, None, "C_PACE") is None, kind


def test_pace_kind_with_no_pace_channel_falls_through():
    # Backward-compatible: no PACE channel configured → default channel (None).
    assert notifications.resolve_slack_channel("task_due", None, "") is None
    assert notifications.resolve_slack_channel("task_due", None, None) is None


def test_explicit_payload_channel_always_wins():
    # An explicit override beats both PACE routing and the default, for any kind.
    assert notifications.resolve_slack_channel("task_due", {"slack_channel": "C_X"}, "C_PACE") == "C_X"
    assert notifications.resolve_slack_channel("rank_drop", {"slack_channel": "C_X"}, "C_PACE") == "C_X"


# ---------------------------------------------------------------------------
# resolve_slack_token / pace_bot_token — PACE posts under its own app's token
# ---------------------------------------------------------------------------
def test_resolve_slack_token_pace_channel_gets_pace_token():
    # A message bound for the PACE channel goes out under the PACE app's token.
    assert notifications.resolve_slack_token("C_PACE", "C_PACE", "xoxb-pace", "xoxb-def") == "xoxb-pace"


def test_resolve_slack_token_other_channels_get_default():
    assert notifications.resolve_slack_token(None, "C_PACE", "xoxb-pace", "xoxb-def") == "xoxb-def"
    assert notifications.resolve_slack_token("C_OTHER", "C_PACE", "xoxb-pace", "xoxb-def") == "xoxb-def"


def test_resolve_slack_token_no_pace_token_falls_back():
    # Separate-bot mode not configured → even the PACE channel posts under default,
    # so the change is inert until a PACE app token is set.
    assert notifications.resolve_slack_token("C_PACE", "C_PACE", "", "xoxb-def") == "xoxb-def"


def test_pace_bot_token_prefers_pace_then_default(monkeypatch):
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-def")
    monkeypatch.setattr(settings, "pace_slack_bot_token", "xoxb-pace")
    assert notifications.pace_bot_token() == "xoxb-pace"
    monkeypatch.setattr(settings, "pace_slack_bot_token", "")
    assert notifications.pace_bot_token() == "xoxb-def"


# ---------------------------------------------------------------------------
# emit — the recipient (personal-bell target) is written to the row
# ---------------------------------------------------------------------------
def test_emit_writes_recipient_profile_id(monkeypatch):
    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "slack_bot_token", "")
    monkeypatch.setattr(settings, "slack_default_channel", "")
    captured: dict = {}

    class _Q:
        def __init__(self, tbl):
            self.tbl = tbl

        def insert(self, row):
            if self.tbl == "notifications":
                captured.update(row)
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "n1"}]})()

    monkeypatch.setattr(notifications, "get_supabase", lambda: type("SB", (), {"table": lambda self, n: _Q(n)})())
    nid = notifications.emit(
        client_id="c1", kind="task_nudge", title="Nudge", recipient_profile_id="p_ivy",
    )
    assert nid == "n1"
    assert captured["recipient_profile_id"] == "p_ivy"     # targeted at the person's bell
    assert captured["client_id"] == "c1"


def test_emit_recipient_defaults_none(monkeypatch):
    """A broadcast (agency/client-wide) notification carries a null recipient —
    unchanged behaviour for every existing producer."""
    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "slack_bot_token", "")
    monkeypatch.setattr(settings, "slack_default_channel", "")
    captured: dict = {}

    class _Q:
        def __init__(self, tbl):
            self.tbl = tbl

        def insert(self, row):
            if self.tbl == "notifications":
                captured.update(row)
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "n2"}]})()

    monkeypatch.setattr(notifications, "get_supabase", lambda: type("SB", (), {"table": lambda self, n: _Q(n)})())
    notifications.emit(client_id="c1", kind="rank_drop", title="Drop")
    assert captured["recipient_profile_id"] is None
