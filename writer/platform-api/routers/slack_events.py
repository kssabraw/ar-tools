"""Slack Events API endpoint — inbound side of the SerMastr assistant.

Slack POSTs here when the bot is @mentioned (event subscription `app_mention`).
We verify the request signature (fail-closed), answer the URL-verification
handshake, and for a real mention ack within Slack's 3-second window while the
answer is produced in a background task (Claude calls take longer than 3s).

Public endpoint — the signature check (HMAC over the signing secret) is the only
thing standing between this and the open internet, so it runs before anything.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Request, Response

from config import settings
from services import slack_assistant

router = APIRouter(tags=["slack"])
logger = logging.getLogger(__name__)


@router.post("/slack/events")
async def slack_events(request: Request, background: BackgroundTasks) -> Response:
    raw = await request.body()
    body_text = raw.decode("utf-8", errors="replace")

    # Disabled / unconfigured → ack so Slack doesn't retry, but do nothing.
    if not (settings.slack_assistant_enabled and settings.slack_signing_secret):
        return Response(status_code=200)

    # Verify the Slack signature before trusting anything in the body.
    if not slack_assistant.verify_slack_signature(
        settings.slack_signing_secret,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        body_text,
        request.headers.get("X-Slack-Signature", ""),
        int(time.time()),
    ):
        logger.warning("slack_events.bad_signature")
        return Response(status_code=403)

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return Response(status_code=400)

    # URL verification handshake (sent once when you set the Request URL).
    if payload.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": payload.get("challenge")}),
            media_type="application/json",
        )

    # Slack retries on non-2xx; we always ack fast. Skip retried deliveries so a
    # slow first answer can't trigger a duplicate reply.
    if request.headers.get("X-Slack-Retry-Num"):
        return Response(status_code=200)

    if payload.get("type") == "event_callback":
        event = payload.get("event") or {}
        # Channel mode: answer every plain human message in channels SerMastr is in
        # (it's used in a dedicated channel). Ignore the bot's own posts (rank-drop
        # alerts etc.) + other bots + edits/joins/deletes (subtypes) to avoid loops.
        # `message` events also cover @mentions (the mention text is just stripped),
        # so we don't separately handle `app_mention` — that would double-reply.
        if (
            event.get("type") == "message"
            and event.get("subtype") in (None, "thread_broadcast")
            and not event.get("bot_id")
        ):
            background.add_task(slack_assistant.handle_message, event)

    return Response(status_code=200)
