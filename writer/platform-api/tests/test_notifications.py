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
        "deliverable_link_missing", "deliverable_note",
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
    # An override also beats a client channel.
    assert notifications.resolve_slack_channel(
        "task_assigned", {"slack_channel": "C_X"}, "C_PACE", client_channel="C_CLIENT"
    ) == "C_X"


# ---------------------------------------------------------------------------
# Per-client PACE routing — a client-scoped kind goes to that client's channel
# ---------------------------------------------------------------------------
def test_client_scoped_kinds_route_to_client_channel():
    # The client-scoped PACE kinds land in the client's own channel when set.
    for kind in ("task_assigned", "task_mention", "task_comment",
                 "task_month_generated", "task_nudge",
                 "deliverable_link_missing", "deliverable_note"):
        assert notifications.resolve_slack_channel(
            kind, None, "C_PACE", client_channel="C_CLIENT"
        ) == "C_CLIENT", kind


def test_portfolio_pace_kinds_ignore_client_channel():
    # Portfolio rollups stay in the master PACE channel even if a client channel
    # is somehow supplied — they concern all clients, not one.
    for kind in ("pace_digest", "pace_chase_plan", "pace_escalation", "pace_report",
                 "task_overload", "task_due"):
        assert notifications.resolve_slack_channel(
            kind, None, "C_PACE", client_channel="C_CLIENT"
        ) == "C_PACE", kind


def test_client_scoped_kind_falls_back_to_master_without_client_channel():
    # No client channel configured → the master PACE channel, exactly as before.
    assert notifications.resolve_slack_channel("task_assigned", None, "C_PACE") == "C_PACE"
    assert notifications.resolve_slack_channel(
        "task_assigned", None, "C_PACE", client_channel=None
    ) == "C_PACE"


def test_non_pace_kind_ignores_client_channel():
    # A non-PACE client-scoped alert (rank drop, strategy review) is unaffected —
    # it still returns None → the default channel, never the client channel.
    assert notifications.resolve_slack_channel(
        "rank_drop", None, "C_PACE", client_channel="C_CLIENT"
    ) is None


# ---------------------------------------------------------------------------
# quiet_task_alerts — the per-event task alerts never reach the master #pace
# channel; they go to the client channel (if set) + the person's DM.
# ---------------------------------------------------------------------------
def test_quiet_task_alert_no_client_channel_resolves_to_none():
    # With quiet on and no client channel, a per-event task alert resolves to None
    # (the DM + in-app bell carry it) rather than falling back to master #pace.
    for kind in ("task_assigned", "task_mention", "task_comment", "task_nudge"):
        assert notifications.resolve_slack_channel(
            kind, None, "C_PACE", quiet_task_alerts=True
        ) is None, kind


def test_quiet_task_alert_still_uses_client_channel_when_set():
    # Quiet keeps the client's own channel — only the master fallback is dropped.
    for kind in ("task_assigned", "task_mention", "task_comment", "task_nudge"):
        assert notifications.resolve_slack_channel(
            kind, None, "C_PACE", client_channel="C_CLIENT", quiet_task_alerts=True
        ) == "C_CLIENT", kind


def test_quiet_task_alert_explicit_override_still_wins():
    # An explicit payload.slack_channel overrides everything, even under quiet.
    assert notifications.resolve_slack_channel(
        "task_assigned", {"slack_channel": "C_X"}, "C_PACE", quiet_task_alerts=True
    ) == "C_X"


def test_quiet_does_not_affect_batched_or_portfolio_kinds():
    # task_month_generated (batched digest) is NOT a CLIENT_ONLY kind — it keeps
    # the master fallback even with quiet on; so do the portfolio rollups.
    assert notifications.resolve_slack_channel(
        "task_month_generated", None, "C_PACE", quiet_task_alerts=True
    ) == "C_PACE"
    for kind in ("pace_digest", "task_overload", "task_due"):
        assert notifications.resolve_slack_channel(
            kind, None, "C_PACE", quiet_task_alerts=True
        ) == "C_PACE", kind


def test_quiet_off_preserves_master_fallback():
    # The default (flag off) is byte-for-byte the old behaviour: master fallback.
    assert notifications.resolve_slack_channel(
        "task_assigned", None, "C_PACE", quiet_task_alerts=False
    ) == "C_PACE"


# ---------------------------------------------------------------------------
# dm_recipient_ids — who gets a direct DM for a per-event task alert
# ---------------------------------------------------------------------------
def test_dm_recipient_ids_uses_recipient_and_payload():
    # Recipient (assignee/mentioned) + payload.dm_profile_ids (comment watchers),
    # de-duplicated in stable order.
    ids = notifications.dm_recipient_ids(
        "task_comment", {"dm_profile_ids": ["p2", "p3", "p2"]}, "p1", True
    )
    assert ids == ["p1", "p2", "p3"]


def test_dm_recipient_ids_assigned_uses_recipient_only():
    assert notifications.dm_recipient_ids("task_assigned", None, "p1", True) == ["p1"]


def test_dm_recipient_ids_empty_when_flag_off():
    assert notifications.dm_recipient_ids("task_assigned", None, "p1", False) == []


def test_dm_recipient_ids_excludes_nudge_and_other_kinds():
    # task_nudge DMs at its own call site (no double DM); non-task kinds never DM.
    assert notifications.dm_recipient_ids("task_nudge", None, "p1", True) == []
    assert notifications.dm_recipient_ids("task_month_generated", None, "p1", True) == []
    assert notifications.dm_recipient_ids("rank_drop", None, "p1", True) == []


def test_dm_recipient_ids_no_targets():
    assert notifications.dm_recipient_ids("task_mention", None, None, True) == []


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


def test_resolve_slack_token_pace_kind_in_client_channel_gets_pace_token():
    # A client-scoped PACE kind delivered to a client's own channel still posts
    # under the PACE app's token (the PACE bot owns delivery of every PACE kind).
    assert notifications.resolve_slack_token(
        "C_CLIENT", "C_PACE", "xoxb-pace", "xoxb-def", kind="task_assigned"
    ) == "xoxb-pace"


def test_resolve_slack_token_non_pace_kind_in_other_channel_gets_default():
    # A non-PACE kind in some other channel keeps using the default token.
    assert notifications.resolve_slack_token(
        "C_OTHER", "C_PACE", "xoxb-pace", "xoxb-def", kind="rank_drop"
    ) == "xoxb-def"


# ---------------------------------------------------------------------------
# resolve_client_channel — normalize a stored client channel for routing
# ---------------------------------------------------------------------------
def test_resolve_client_channel_normalizes():
    assert notifications.resolve_client_channel("C0ABC123") == "C0ABC123"
    assert notifications.resolve_client_channel("  C0ABC123  ") == "C0ABC123"
    assert notifications.resolve_client_channel("   ") is None  # whitespace → unset
    assert notifications.resolve_client_channel("") is None
    assert notifications.resolve_client_channel(None) is None


# ---------------------------------------------------------------------------
# master_fallback_channel — a broken client channel degrades to the master
# ---------------------------------------------------------------------------
def test_master_fallback_only_when_routed_to_client_channel():
    # Routed to the client's own channel → fall back to the PACE channel.
    assert notifications.master_fallback_channel(
        "C_CLIENT", "C_CLIENT", "C_PACE", "C_DEFAULT"
    ) == "C_PACE"
    # No PACE channel → the default channel is the fallback.
    assert notifications.master_fallback_channel(
        "C_CLIENT", "C_CLIENT", "", "C_DEFAULT"
    ) == "C_DEFAULT"
    # Neither configured → nothing to fall back to.
    assert notifications.master_fallback_channel(
        "C_CLIENT", "C_CLIENT", "", ""
    ) is None


def test_master_fallback_none_when_not_client_route():
    # Message went to the master channel (not a per-client route) → no fallback.
    assert notifications.master_fallback_channel(
        "C_PACE", "C_CLIENT", "C_PACE", "C_DEFAULT"
    ) is None
    # No client channel at all → no fallback.
    assert notifications.master_fallback_channel(
        "C_PACE", None, "C_PACE", "C_DEFAULT"
    ) is None


# ---------------------------------------------------------------------------
# has_slack_target — a resolved message must have somewhere to post
# ---------------------------------------------------------------------------
def test_has_slack_target():
    assert notifications.has_slack_target("C_CLIENT", "") is True
    assert notifications.has_slack_target(None, "C_DEFAULT") is True
    assert notifications.has_slack_target(None, "") is False  # PACE-only + non-PACE kind
    assert notifications.has_slack_target("", "") is False


# ---------------------------------------------------------------------------
# slack_configured — SerMaStr config OR a PACE-only Slack setup
# ---------------------------------------------------------------------------
def test_slack_configured_sermastr_or_pace_only(monkeypatch):
    monkeypatch.setattr(settings, "notifications_enabled", True)
    # Normal SerMaStr config.
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-def")
    monkeypatch.setattr(settings, "slack_default_channel", "C_DEFAULT")
    monkeypatch.setattr(settings, "pace_slack_bot_token", "")
    monkeypatch.setattr(settings, "pace_slack_channel", "")
    assert notifications.slack_configured() is True
    # PACE-only: no SerMaStr default channel, but a PACE app + channel.
    monkeypatch.setattr(settings, "slack_bot_token", "")
    monkeypatch.setattr(settings, "slack_default_channel", "")
    monkeypatch.setattr(settings, "pace_slack_bot_token", "xoxb-pace")
    monkeypatch.setattr(settings, "pace_slack_channel", "C_PACE")
    assert notifications.slack_configured() is True
    # Nothing configured.
    monkeypatch.setattr(settings, "pace_slack_bot_token", "")
    monkeypatch.setattr(settings, "pace_slack_channel", "")
    assert notifications.slack_configured() is False
    # Notifications globally disabled → always False.
    monkeypatch.setattr(settings, "notifications_enabled", False)
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-def")
    monkeypatch.setattr(settings, "slack_default_channel", "C_DEFAULT")
    assert notifications.slack_configured() is False


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
