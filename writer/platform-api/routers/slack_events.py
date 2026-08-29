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


def _extract_message_event(payload: dict):
    """The plain human `message` event to act on, or None (bot posts, edits,
    joins, retries are filtered by the caller). Shared by both endpoints."""
    if payload.get("type") != "event_callback":
        return None
    event = payload.get("event") or {}
    if (
        event.get("type") == "message"
        and event.get("subtype") in (None, "thread_broadcast")
        and not event.get("bot_id")
    ):
        return event
    return None


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


@router.post("/slack/pace/events")
async def slack_pace_events(request: Request, background: BackgroundTasks) -> Response:
    """Inbound side of the dedicated PACE Slack app (owner ruling 2026-08-28).

    A separate Slack app gives PACE its own bot identity, so it needs its own
    signing secret and its own Request URL. This app lives only in the PACE
    channel; every plain human message it delivers is PACE's to consider, but
    (owner ruling 2026-08-29) it only ANSWERS a new question when @-mentioned
    — a reply continuing an already-staged confirmation is the exception
    (``pace_agent.maybe_handle_slack``). The Events API envelope's
    ``authorizations`` field carries PACE's own bot user id, threaded through
    so the mention check knows which user id is "PACE".

    Inert unless PACE is enabled AND a PACE signing secret is configured — until
    then the shared SerMaStr app keeps handling the PACE channel (via the
    force path in handle_message)."""
    raw = await request.body()
    body_text = raw.decode("utf-8", errors="replace")

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return Response(status_code=400)

    # URL-verification handshake — answer it BEFORE the enabled/secret gate so the
    # Request URL can be verified during setup, before the signing secret is
    # deployed (the challenge echoes no secret; it only proves URL ownership).
    if payload.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": payload.get("challenge")}),
            media_type="application/json",
        )

    # Inbound diagnostics — record every real delivery + the gate state, so a
    # silent non-reply is debuggable (is Slack reaching us, and do we drop it?).
    _ev = payload.get("event") or {}
    logger.info(
        "slack_pace_events.hit type=%s event=%s subtype=%s bot=%s channel=%s retry=%s pace_enabled=%s has_secret=%s",
        payload.get("type"), _ev.get("type"), _ev.get("subtype"),
        bool(_ev.get("bot_id")), _ev.get("channel"),
        request.headers.get("X-Slack-Retry-Num"),
        settings.pace_enabled, bool(settings.pace_slack_signing_secret),
    )

    # Real events require PACE enabled + a configured signing secret (fail-closed).
    if not (settings.pace_enabled and settings.pace_slack_signing_secret):
        return Response(status_code=200)

    if not slack_assistant.verify_slack_signature(
        settings.pace_slack_signing_secret,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        body_text,
        request.headers.get("X-Slack-Signature", ""),
        int(time.time()),
    ):
        logger.warning("slack_pace_events.bad_signature")
        return Response(status_code=403)

    # Slack retries on non-2xx; always ack fast and skip retried deliveries.
    if request.headers.get("X-Slack-Retry-Num"):
        return Response(status_code=200)

    event = _extract_message_event(payload)
    if event is not None:
        from services import pace_agent

        background.add_task(pace_agent.handle_pace_message, event, _bot_user_id(payload))

    return Response(status_code=200)


def _bot_user_id(payload: dict) -> "str | None":
    """The receiving app's own Slack user id, from the Events API envelope's
    ``authorizations[0].user_id`` (present on every event_callback for a
    non-org-wide app — used to tell "someone @-mentioned PACE" apart from
    "someone @-mentioned a teammate"). ``None`` when Slack omits it; callers
    degrade permissively rather than going silent."""
    auths = payload.get("authorizations") or []
    return (auths[0] or {}).get("user_id") if auths else None


@router.post("/slack/director/events")
async def slack_director_events(request: Request, background: BackgroundTasks) -> Response:
    """Inbound side of the dedicated DORA (Director of Operations) Slack app
    (owner ruling 2026-08-29).

    A separate Slack app gives DORA its own bot identity, so it needs its own
    signing secret and its own Request URL. This app lives only in the #dora
    channel, so every plain human message it delivers is DORA's to answer
    (read-only — DORA just reports cross-agent flow).

    Inert unless DORA is enabled AND a DORA signing secret is configured. Setup:
    create the DORA Slack app, add it to #dora, point its Event Request URL here,
    and — per the PACE gotcha — keep Socket Mode OFF, or Slack ships events over a
    WebSocket and this endpoint never sees them (yet URL verification still
    passes)."""
    raw = await request.body()
    body_text = raw.decode("utf-8", errors="replace")

    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return Response(status_code=400)

    # URL-verification handshake — answer it BEFORE the enabled/secret gate so the
    # Request URL can be verified during setup, before the signing secret is
    # deployed (the challenge echoes no secret; it only proves URL ownership).
    if payload.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": payload.get("challenge")}),
            media_type="application/json",
        )

    _ev = payload.get("event") or {}
    logger.info(
        "slack_director_events.hit type=%s event=%s subtype=%s bot=%s channel=%s retry=%s director_enabled=%s has_secret=%s",
        payload.get("type"), _ev.get("type"), _ev.get("subtype"),
        bool(_ev.get("bot_id")), _ev.get("channel"),
        request.headers.get("X-Slack-Retry-Num"),
        settings.director_enabled, bool(settings.director_slack_signing_secret),
    )

    # Real events require DORA enabled + a configured signing secret (fail-closed).
    if not (settings.director_enabled and settings.director_slack_signing_secret):
        return Response(status_code=200)

    if not slack_assistant.verify_slack_signature(
        settings.director_slack_signing_secret,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        body_text,
        request.headers.get("X-Slack-Signature", ""),
        int(time.time()),
    ):
        logger.warning("slack_director_events.bad_signature")
        return Response(status_code=403)

    # Slack retries on non-2xx; always ack fast and skip retried deliveries.
    if request.headers.get("X-Slack-Retry-Num"):
        return Response(status_code=200)

    event = _extract_message_event(payload)
    if event is not None:
        from services import director_agent

        background.add_task(director_agent.handle_director_message, event)

    return Response(status_code=200)
