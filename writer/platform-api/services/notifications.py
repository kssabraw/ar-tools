"""Notifications service — the suite's shared delivery pipe.

Producers (rank-drop alerting, the reoptimization planner, …) call ``emit`` with
a client-scoped event. ``emit`` writes one ``notifications`` row (the in-app feed
that drives the client-card badge) and enqueues a ``notification_dispatch`` async
job that delivers the email + Slack copies. Delivery is decoupled from producers
so a blocking SMTP/Slack send can never stall a job; each channel is best-effort
and only fires when its creds are configured (in-app always works).

Channels: in-app (DB row), email (SMTP — Gmail/Workspace), Slack (bot token →
chat.postMessage). Recipients/channel are agency-level for v1.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT = 20.0

# Per-channel outcomes that count as delivered — a requeued dispatch job skips
# re-sending these (idempotency) while still retrying "failed"/"skipped".
_DELIVERED = frozenset({"ok", "ok_master_fallback"})


# ----------------------------------------------------------------------------
# Pure config/format helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def email_configured() -> bool:
    return bool(
        settings.notifications_enabled
        and settings.smtp_host
        and settings.smtp_user
        and settings.smtp_password
        and email_recipients()
    )


def slack_configured() -> bool:
    """Whether any Slack delivery path is set up. True for the normal SerMaStr
    config (bot token + a default channel) OR a PACE-only setup (the PACE app's
    bot token + a PACE channel) — so a deployment that wires only PACE's Slack
    app still delivers PACE kinds. When only PACE is configured, a non-PACE kind
    resolves to no channel and is skipped at dispatch (``has_slack_target``)."""
    if not settings.notifications_enabled:
        return False
    if settings.slack_bot_token and settings.slack_default_channel:
        return True
    if settings.pace_slack_bot_token and settings.pace_slack_channel:
        return True
    return False


def email_recipients() -> list[str]:
    return [r.strip() for r in (settings.notify_email_to or "").split(",") if r.strip()]


def _deep_link(payload: Optional[dict]) -> Optional[str]:
    """Absolute URL for the notification's in-app target, if both a base URL and a
    relative link are available."""
    base = (settings.app_base_url or "").rstrip("/")
    path = (payload or {}).get("link")
    if not (base and path):
        return None
    return f"{base}/{str(path).lstrip('/')}"


def format_email(title: str, summary: Optional[str], client_name: Optional[str],
                 link: Optional[str]) -> tuple[str, str]:
    """(subject, plain-text body) for the email copy. Pure."""
    subject = f"[{client_name}] {title}" if client_name else title
    lines = [title, ""]
    if summary:
        lines += [summary, ""]
    if link:
        lines += [f"Open: {link}", ""]
    lines.append("— AR Tools")
    return subject, "\n".join(lines)


# Slack broadcast tokens. The raw <!here>/<!channel> forms fire the ping under
# mrkdwn (no link_names needed); a plain "@here" string would render inert.
_MENTION_TOKENS = {"here": "<!here>", "channel": "<!channel>", "everyone": "<!everyone>"}


def slack_mention(severity: str) -> str:
    """The Slack broadcast prefix (``<!here>``/``<!channel>``) to lead a message
    with for this severity, or ``""``. Gated by ``slack_mention_token`` (set it to
    ``""`` to disable all broadcasts) and the ``slack_mention_severities``
    allowlist, so info-level notifications never ping the channel. Pure."""
    token = _MENTION_TOKENS.get((settings.slack_mention_token or "").strip().lower())
    if not token:
        return ""
    allowed = {
        s.strip().lower()
        for s in (settings.slack_mention_severities or "").split(",")
        if s.strip()
    }
    return token if severity in allowed else ""


def format_slack(title: str, summary: Optional[str], client_name: Optional[str],
                 link: Optional[str], severity: str) -> str:
    """Slack message text (mrkdwn). Pure."""
    icon = {"critical": "🔴", "warning": "🟠"}.get(severity, "🔵")
    head = f"{icon} *{title}*"
    if client_name:
        head += f"  ·  _{client_name}_"
    mention = slack_mention(severity)
    if mention:
        head = f"{mention} {head}"
    parts = [head]
    if summary:
        parts.append(summary)
    if link:
        parts.append(f"<{link}|Open in AR Tools>")
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Emit (sync — safe to call from producer code) + dispatch (async job).
# ----------------------------------------------------------------------------
# PM / PACE notification kinds are delivered to the dedicated PACE Slack channel
# (``settings.pace_slack_channel``) when one is configured, so project-management
# chatter (task assignments, comments, nudges, the due/overload sweeps, and the
# daily digest / chase plan / escalations) stays out of the strategy channel.
# A client-scoped PACE kind (``CLIENT_SCOPED_PACE_KINDS``) is delivered to that
# client's OWN channel (``clients.slack_channel_id``) when one is set, falling
# back to the master PACE channel otherwise — so PACE can talk in each client's
# channel instead of only one master channel. Every other kind (strategy reviews,
# SEO alerts, run/publish events) keeps using ``slack_default_channel``. A
# producer can still force any channel explicitly via ``payload.slack_channel`` —
# that always wins.
PACE_CHANNEL_KINDS = frozenset({
    "pace_digest", "pace_chase_plan", "pace_escalation", "pace_report", "pace_briefs",
    "task_assigned", "task_mention", "task_comment", "task_month_generated",
    "task_overload", "task_due", "task_nudge",
})

# The client-scoped subset of the PACE kinds: each carries a real ``client_id``
# and concerns exactly one client, so when that client has a dedicated Slack
# channel (``clients.slack_channel_id``) PACE posts these there instead of the
# master PACE channel. The portfolio PACE kinds (the daily digest, Chase Plan,
# workload report, escalations — all emitted with ``client_id=None``) and the
# suite-wide ``task_overload``/``task_due`` digests are deliberately excluded, so
# they stay in the single master channel as agency-wide rollups.
CLIENT_SCOPED_PACE_KINDS = frozenset({
    "task_assigned", "task_mention", "task_comment", "task_month_generated",
    "task_nudge",
})


def resolve_slack_channel(
    kind: Optional[str], payload: Optional[dict], pace_channel: Optional[str],
    client_channel: Optional[str] = None,
) -> Optional[str]:
    """Pick the Slack channel for one notification. Precedence:
    1. an explicit ``payload.slack_channel`` (a producer targeting a channel),
    2. the client's own channel for a client-scoped PACE ``kind`` when that client
       has ``client_channel`` configured (per-client PACE delivery),
    3. the master PACE channel for any PM/PACE ``kind`` when ``pace_channel`` is set,
    4. otherwise ``None`` → the sender falls back to ``slack_default_channel``.
    Pure — unit-tested."""
    override = (payload or {}).get("slack_channel")
    if override:
        return override
    if client_channel and kind in CLIENT_SCOPED_PACE_KINDS:
        return client_channel
    if pace_channel and kind in PACE_CHANNEL_KINDS:
        return pace_channel
    return None


def pace_bot_token() -> str:
    """The bot token PACE posts under: the dedicated PACE Slack app's token when
    configured, else the shared (SerMaStr) token. PACE-side senders use this so
    their posts carry the PACE identity once a separate app exists."""
    return settings.pace_slack_bot_token or settings.slack_bot_token


def resolve_slack_token(
    channel: Optional[str], pace_channel: str, pace_token: str, default_token: str,
    kind: Optional[str] = None,
) -> str:
    """The bot token to deliver one notification under. The PACE app owns delivery
    of every PM/PACE kind — in the master PACE channel *and* in each client's own
    channel — so when ``pace_token`` is configured any PACE ``kind`` posts under it
    (the PACE bot must be a member of the target channel). Otherwise the default
    (SerMaStr) token is used, with a back-compat check that also uses the PACE
    token for a message explicitly bound for the master PACE channel. Pure —
    unit-tested."""
    if pace_token and (kind in PACE_CHANNEL_KINDS or (pace_channel and channel == pace_channel)):
        return pace_token
    return default_token


def resolve_client_channel(raw: Optional[str]) -> Optional[str]:
    """Normalize a client's stored ``slack_channel_id`` for routing: trim it and
    treat blank/whitespace as unset (``None``). The clients router already trims
    on write, but an out-of-band DB value must never route a message to a
    whitespace channel. Pure — unit-tested."""
    return (raw or "").strip() or None


def master_fallback_channel(
    resolved_channel: Optional[str], client_channel: Optional[str],
    pace_channel: Optional[str], default_channel: Optional[str],
) -> Optional[str]:
    """The channel to retry on when a send to a client's OWN channel fails (bot
    not invited, bad/renamed id, archived channel) — so a misconfigured per-client
    channel degrades to the master channel instead of dropping the message. Only
    returns a target when the message was actually routed to the client channel;
    for any other channel there is nothing to fall back to (``None``). Prefers the
    master PACE channel, then the default channel. Pure — unit-tested."""
    if client_channel and resolved_channel == client_channel:
        return pace_channel or default_channel or None
    return None


def has_slack_target(channel: Optional[str], default_channel: Optional[str]) -> bool:
    """Whether a resolved notification has somewhere to post: an explicit channel
    or a default the sender falls back to. In a PACE-only deployment (no default
    channel) a non-PACE kind resolves to neither → skip rather than post to "".
    Pure — unit-tested."""
    return bool(channel or default_channel)


def emit(
    client_id: Optional[str],
    kind: str,
    title: str,
    summary: Optional[str] = None,
    severity: str = "info",
    payload: Optional[dict] = None,
    dedupe_key: Optional[str] = None,
    recipient_profile_id: Optional[str] = None,
) -> Optional[str]:
    """Record an in-app notification and enqueue its email/Slack dispatch.

    Best-effort: never raises into the caller (a notification failure must not
    break the producer's own work). Returns the notification id, or None.

    ``recipient_profile_id`` (optional) targets the notification at ONE suite
    user — it surfaces in their personal header bell (``GET /notifications/mine``)
    in addition to the per-client feed. None = agency/client-wide (unchanged).

    ``dedupe_key`` (optional) gives **atomic** idempotency via the unique
    ``notifications.dedupe_key`` index: if a row with this key already exists
    (e.g. a rolling-deploy re-run of a daily digest), the insert conflicts and
    this is a clean no-op returning None — no duplicate notification. The DB
    constraint is the arbiter (no query-guard TOCTOU race).
    """
    if not settings.notifications_enabled:
        return None
    try:
        supabase = get_supabase()
        insert_row = {
            "client_id": client_id,
            "kind": kind,
            "severity": severity,
            "title": title,
            "summary": summary,
            "payload": payload,
            "dedupe_key": dedupe_key,
            "recipient_profile_id": recipient_profile_id,
        }
        try:
            row = supabase.table("notifications").insert(insert_row).execute()
        except Exception as insert_exc:
            # A dedupe_key conflict means someone already emitted this — a clean
            # no-op. Disambiguate a genuine conflict from any other insert error
            # by re-checking for the key's existence (the constraint is atomic).
            if dedupe_key:
                existing = (
                    supabase.table("notifications")
                    .select("id")
                    .eq("dedupe_key", dedupe_key)
                    .limit(1)
                    .execute()
                )
                if existing.data:
                    return None
            raise insert_exc
        notification_id = row.data[0]["id"]
        # Only enqueue an external-delivery job when a channel is actually set up.
        if email_configured() or slack_configured():
            supabase.table("async_jobs").insert(
                {
                    "job_type": "notification_dispatch",
                    "entity_id": client_id,
                    "payload": {"notification_id": notification_id},
                }
            ).execute()
        return notification_id
    except Exception as exc:  # never break the producer
        logger.warning("notification_emit_failed", extra={"kind": kind, "error": str(exc)})
        return None


def _send_email_sync(subject: str, body: str) -> None:
    """Blocking SMTP send to all recipients (run via asyncio.to_thread)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(email_recipients())
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_TIMEOUT) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


# Slack rate-limits chat.postMessage at ~1 msg/sec/channel and answers 429 with
# a Retry-After header. Sweep producers (rank drops, offpage alerts, …) can
# enqueue a burst of dispatch jobs, and a dropped 429 silently lost the message
# — honor Retry-After (bounded) and retry a couple of times instead.
_SLACK_MAX_RETRIES = 2
_SLACK_RETRY_AFTER_CAP_SECONDS = 30.0


async def _send_slack(text: str, channel: Optional[str] = None, token: Optional[str] = None) -> None:
    import asyncio

    target = channel or settings.slack_default_channel
    bot_token = token or settings.slack_bot_token
    body: dict = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(_SLACK_MAX_RETRIES + 1):
            resp = await client.post(
                _SLACK_POST_URL,
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": target, "text": text, "mrkdwn": True},
            )
            if resp.status_code == 429 and attempt < _SLACK_MAX_RETRIES:
                try:
                    retry_after = float(resp.headers.get("Retry-After") or 1)
                except ValueError:
                    retry_after = 1.0
                delay = min(max(retry_after, 1.0), _SLACK_RETRY_AFTER_CAP_SECONDS)
                logger.warning("slack_rate_limited", extra={"retry_in_s": delay, "attempt": attempt + 1})
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            body = resp.json()
            break
    if not body.get("ok"):
        raise RuntimeError(f"slack_error: {body.get('error')}")


async def run_notification_dispatch_job(job: dict) -> None:
    """async_jobs handler for job_type='notification_dispatch' — send the email +
    Slack copies of one notification, best-effort per channel."""
    import asyncio

    payload = job.get("payload") or {}
    notification_id = payload.get("notification_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not notification_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing notification_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    found = (
        supabase.table("notifications").select("*").eq("id", notification_id).limit(1).execute()
    )
    if not found.data:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "notification_not_found", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    n = found.data[0]

    client_name = None
    client_channel = None
    if n.get("client_id"):
        c = (
            supabase.table("clients")
            .select("name, slack_channel_id")
            .eq("id", n["client_id"])
            .limit(1)
            .execute()
        )
        if c.data:
            client_name = c.data[0].get("name")
            client_channel = resolve_client_channel(c.data[0].get("slack_channel_id"))
    link = _deep_link(n.get("payload"))

    # Per-channel idempotency: a reaper requeue re-runs this job, so start from the
    # already-recorded outcomes and re-attempt only the channels not yet delivered
    # (a prior "failed"/"skipped" is retried; a prior success is left alone) — so a
    # requeue can never double-post an already-delivered Slack/email copy.
    channels: dict[str, str] = dict(n.get("channels_sent") or {})

    if channels.get("email") in _DELIVERED:
        pass
    elif email_configured():
        subject, body = format_email(n["title"], n.get("summary"), client_name, link)
        try:
            await asyncio.to_thread(_send_email_sync, subject, body)
            channels["email"] = "ok"
        except Exception as exc:
            channels["email"] = "failed"
            logger.warning("notification_email_failed", extra={"id": notification_id, "error": str(exc)})
    else:
        channels["email"] = "skipped"

    skip = set((n.get("payload") or {}).get("skip_channels") or [])
    if channels.get("slack") in _DELIVERED:
        pass  # already delivered on an earlier attempt
    elif "slack" in skip:
        # The producer delivers its own Slack copy (e.g. the Chase Plan posts
        # directly so its ts can key the batch confirm) — don't double-post.
        channels["slack"] = "skipped"
    elif slack_configured():
        # Route a client-scoped PACE kind to that client's own channel when one is
        # set; else route PM/PACE kinds to the master PACE channel; an explicit
        # payload.slack_channel still wins; else the default channel. Post under the
        # PACE app's bot token for any PACE kind (so a separate PACE bot owns
        # delivery in both the master and per-client channels).
        channel = resolve_slack_channel(
            n.get("kind"), n.get("payload"), settings.pace_slack_channel,
            client_channel=client_channel,
        )
        if not has_slack_target(channel, settings.slack_default_channel):
            # PACE-only deployment (no default channel) + a non-PACE kind → there
            # is nowhere to post it; skip rather than posting to an empty channel.
            channels["slack"] = "skipped"
        else:
            text = format_slack(n["title"], n.get("summary"), client_name, link, n["severity"])
            token = resolve_slack_token(
                channel, settings.pace_slack_channel,
                settings.pace_slack_bot_token, settings.slack_bot_token,
                kind=n.get("kind"),
            )
            # If we routed to a client's OWN channel and that send fails (bot not
            # invited / bad or renamed id / archived), retry on the master channel
            # so the message still reaches the team instead of being dropped.
            fallback = master_fallback_channel(
                channel, client_channel, settings.pace_slack_channel,
                settings.slack_default_channel,
            )
            try:
                await _send_slack(text, channel=channel, token=token)
                channels["slack"] = "ok"
            except Exception as exc:
                if fallback and fallback != channel:
                    try:
                        fb_token = resolve_slack_token(
                            fallback, settings.pace_slack_channel,
                            settings.pace_slack_bot_token, settings.slack_bot_token,
                            kind=n.get("kind"),
                        )
                        await _send_slack(text, channel=fallback, token=fb_token)
                        channels["slack"] = "ok_master_fallback"
                        logger.warning(
                            "notification_slack_client_channel_fallback",
                            extra={"id": notification_id, "client_channel": client_channel,
                                   "error": str(exc)},
                        )
                    except Exception as exc2:
                        channels["slack"] = "failed"
                        logger.warning("notification_slack_failed",
                                       extra={"id": notification_id, "error": str(exc2)})
                else:
                    channels["slack"] = "failed"
                    logger.warning("notification_slack_failed",
                                   extra={"id": notification_id, "error": str(exc)})
    else:
        channels["slack"] = "skipped"

    supabase.table("notifications").update({"channels_sent": channels}).eq("id", notification_id).execute()
    supabase.table("async_jobs").update(
        {"status": "complete", "result": channels, "completed_at": "now()"}
    ).eq("id", job_id).execute()
