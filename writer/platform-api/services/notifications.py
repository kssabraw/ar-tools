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
    return bool(
        settings.notifications_enabled
        and settings.slack_bot_token
        and settings.slack_default_channel
    )


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


def format_slack(title: str, summary: Optional[str], client_name: Optional[str],
                 link: Optional[str], severity: str) -> str:
    """Slack message text (mrkdwn). Pure."""
    icon = {"critical": "🔴", "warning": "🟠"}.get(severity, "🔵")
    head = f"{icon} *{title}*"
    if client_name:
        head += f"  ·  _{client_name}_"
    parts = [head]
    if summary:
        parts.append(summary)
    if link:
        parts.append(f"<{link}|Open in AR Tools>")
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Emit (sync — safe to call from producer code) + dispatch (async job).
# ----------------------------------------------------------------------------
def emit(
    client_id: Optional[str],
    kind: str,
    title: str,
    summary: Optional[str] = None,
    severity: str = "info",
    payload: Optional[dict] = None,
) -> Optional[str]:
    """Record an in-app notification and enqueue its email/Slack dispatch.

    Best-effort: never raises into the caller (a notification failure must not
    break the producer's own work). Returns the notification id, or None.
    """
    if not settings.notifications_enabled:
        return None
    try:
        supabase = get_supabase()
        row = (
            supabase.table("notifications")
            .insert(
                {
                    "client_id": client_id,
                    "kind": kind,
                    "severity": severity,
                    "title": title,
                    "summary": summary,
                    "payload": payload,
                }
            )
            .execute()
        )
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


async def _send_slack(text: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _SLACK_POST_URL,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
            json={"channel": settings.slack_default_channel, "text": text, "mrkdwn": True},
        )
        resp.raise_for_status()
        body = resp.json()
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
    if n.get("client_id"):
        c = (
            supabase.table("clients").select("name").eq("id", n["client_id"]).limit(1).execute()
        )
        client_name = c.data[0]["name"] if c.data else None
    link = _deep_link(n.get("payload"))

    channels: dict[str, str] = {}
    if email_configured():
        subject, body = format_email(n["title"], n.get("summary"), client_name, link)
        try:
            await asyncio.to_thread(_send_email_sync, subject, body)
            channels["email"] = "ok"
        except Exception as exc:
            channels["email"] = "failed"
            logger.warning("notification_email_failed", extra={"id": notification_id, "error": str(exc)})
    else:
        channels["email"] = "skipped"

    if slack_configured():
        try:
            await _send_slack(format_slack(n["title"], n.get("summary"), client_name, link, n["severity"]))
            channels["slack"] = "ok"
        except Exception as exc:
            channels["slack"] = "failed"
            logger.warning("notification_slack_failed", extra={"id": notification_id, "error": str(exc)})
    else:
        channels["slack"] = "skipped"

    supabase.table("notifications").update({"channels_sent": channels}).eq("id", notification_id).execute()
    supabase.table("async_jobs").update(
        {"status": "complete", "result": channels, "completed_at": "now()"}
    ).eq("id", job_id).execute()
