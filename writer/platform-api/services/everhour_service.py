"""Everhour time-tracking integration — REST client + pure helpers.

Backs docs/modules/everhour-time-tracking-integration-plan-v1_0.md.

Everhour is a satellite TIME LAYER, never a task manager — the native
``tasks`` table stays the source of truth. Two things ride this one API key:

  A. Task mirror (write, metadata-only) — create a thin Everhour task shadow
     (name + optional assignee) for each native task, purely to establish a
     stable join key time reads back against. Phase 2.
  B. Time pull (read) — a daily sync of team time records over a date range,
     rolled up into ``actual_hours`` per task / client / member. Phase 3.

This file holds the async Everhour REST client (thin httpx wrapper, no
business logic) and the **pure helpers** (no I/O) the sync job composes. The
pure helpers are independently unit-tested; the I/O methods are mocked in
tests, never hit live — model on ``services/asana_service.py``.

Endpoint shapes below are verified against Everhour's published OpenAPI spec
(https://developers.everhour.com/openapi.json, fetched 2026-08-28), not
guessed — see docs/modules/everhour-time-tracking-integration-plan-v1_0.md §11
for the resolution of the earlier egress-blocker.

Graceful degradation: ``is_configured()`` gates every entry point. Absent the
API key the integration is skipped with a note, never an error — the same
provisioning pattern as GSC / Slack / Asana.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.everhour.com"
_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Configuration gating
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """True when the Everhour API key is provisioned."""
    return bool(settings.everhour_api_key)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — normalize API responses / build request payloads
# ---------------------------------------------------------------------------
def seconds_to_hours(seconds: Optional[float]) -> Optional[float]:
    """Seconds -> hours, rounded to 2dp. None-safe (a record with no time)."""
    if seconds is None:
        return None
    return round(float(seconds) / 3600.0, 2)


def build_task_payload(
    name: str,
    *,
    assignee_user_id: Optional[int] = None,
    description: Optional[str] = None,
) -> dict:
    """Build the ``POST /projects/{project_id}/tasks`` body for the
    metadata-only mirror (locked decision #6 — name, plus assignee when
    cheaply available; deliberately never status/due-date/section/labels,
    which would turn Everhour into a second place task state lives). Pure —
    unit-tested."""
    payload: dict[str, Any] = {"name": name or ""}
    if assignee_user_id is not None:
        payload["assignees"] = [{"userId": assignee_user_id}]
    if description:
        payload["description"] = description
    return payload


def parse_user(user: dict) -> dict:
    """Normalize a ``User`` response into the roster-link shape
    ``{everhour_user_id, name, role, status, capacity_seconds}``. Pure."""
    uid = user.get("id")
    return {
        "everhour_user_id": str(uid) if uid is not None else None,
        "name": user.get("name"),
        "role": user.get("role"),
        "status": user.get("status"),
        "capacity_seconds": user.get("capacity"),
    }


def parse_project(project: dict) -> dict:
    """Normalize a ``Project`` response into ``{everhour_project_id, name}``.
    Pure. (Project ids come back as strings like ``"as:1234567890"`` /
    ``"ev:1234567890"`` — not numeric, unlike user ids.)"""
    return {
        "everhour_project_id": project.get("id"),
        "name": project.get("name"),
    }


def parse_time_record(record: dict) -> dict:
    """Normalize one ``GET /team/time`` item (``TimeRecordExtended`` or
    ``TaskTimeBillable`` — the endpoint's response is a ``oneOf`` of the two,
    both sharing id/time/user/date/task/comment) into the shape
    ``time_entries`` rows are built from: ``{everhour_record_id,
    everhour_task_id, everhour_user_id, entry_date, seconds, billable,
    comment}``.

    ``billable`` is only present when the request carried
    ``opts_include_billing=1`` (``TaskTimeBillable.billing.billable``) —
    absent otherwise, so this returns ``None`` (unknown), never ``False``
    (confirmed non-billable), when the caller didn't ask for billing data.
    Pure — unit-tested."""
    task = record.get("task") or {}
    billing = record.get("billing") or {}
    rid = record.get("id")
    uid = record.get("user")
    return {
        "everhour_record_id": str(rid) if rid is not None else None,
        "everhour_task_id": task.get("id"),
        "everhour_user_id": str(uid) if uid is not None else None,
        "entry_date": record.get("date"),
        "seconds": record.get("time"),
        "billable": billing.get("billable"),
        "comment": record.get("comment"),
    }


def is_valid_time_record(parsed: dict) -> bool:
    """A parsed time record carries everything ``time_entries``' NOT NULL
    columns + the idempotency key need. Pure — filters malformed API rows
    out before they hit the upsert, rather than letting one bad row reject
    the whole batch."""
    return bool(
        parsed.get("everhour_record_id")
        and parsed.get("entry_date")
        and parsed.get("seconds") is not None
    )


def next_page(current_page: int, returned_count: int, limit: Optional[int]) -> Optional[int]:
    """The next page number to fetch from a bare-array, no-total-count
    endpoint (``GET /team/time`` and friends — see the pagination docs), or
    ``None`` when this page was the last one. Pure — unit-tested.

    ``limit`` is defensively guarded: an unset/non-positive limit can never
    signal "last page" via ``returned_count < limit`` (a limit of 0 makes
    that comparison false forever, so a caller that mis-threads its limit
    would paginate without end) — treated as "stop" rather than loop
    forever or crash on ``None < int``."""
    if not limit or limit <= 0:
        return None
    if returned_count < limit:
        return None
    return current_page + 1


# ---------------------------------------------------------------------------
# Async REST client (thin httpx wrapper — mocked in tests, never hit live)
# ---------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    return {
        "X-Api-Key": settings.everhour_api_key,
        "Accept": "application/json",
    }


async def _get(path: str, params: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{path}", headers=_headers(), json=data)
        resp.raise_for_status()
        return resp.json()


async def get_current_user() -> dict:
    """``GET /users/me`` — the authenticated user + account info. The
    cheapest call that proves an API key is valid (403 on a bad/missing
    key, per https://developers.everhour.com/errors)."""
    return await _get("/users/me")


async def verify_api_key() -> bool:
    """True when the configured key is accepted by Everhour. Never raises —
    a network error, a 4xx, or a malformed (non-JSON) response body all
    mean "not usable right now", which is a provisioning-status read, not
    an application error. ``ValueError`` catches ``json.JSONDecodeError``
    (a 200 with an unparseable body — e.g. an intermediary proxy's error
    page — which ``httpx.HTTPError`` alone does not cover, since
    ``resp.json()`` raises it independently of the status code)."""
    if not is_configured():
        return False
    try:
        await get_current_user()
        return True
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("everhour_service.verify_api_key_failed", extra={"error": str(exc)})
        return False


async def list_team_users() -> list[dict]:
    """All team members — ``GET /team/users``. Populates the roster's
    Everhour-user-link picker (Phase 1)."""
    return await _get("/team/users") or []


async def list_projects(query: Optional[str] = None) -> list[dict]:
    """Projects the key's account can see — ``GET /projects``. The docs note
    this endpoint returns the full collection with no pagination support."""
    params = {"query": query} if query else None
    return await _get("/projects", params) or []


async def get_project(project_id: str) -> dict:
    """One project's basics — ``GET /projects/{project_id}``. Used to
    validate a pasted/selected Everhour project id at client-mapping save
    time (Phase 1), the same role ``asana_service.get_project`` plays
    (including its ``or {}`` fallback — a 200 with a literal JSON ``null``
    body must degrade to an empty dict, not ``None``, since this is typed
    ``-> dict`` and a Phase 1 caller will index into the result)."""
    return await _get(f"/projects/{project_id}") or {}


async def create_project(name: str, *, project_type: str = "board") -> dict:
    """Create an Everhour project — ``POST /projects``. Only exercised if a
    client's project ends up provisioned via the API rather than created by
    hand in the Everhour UI — see plan doc §11.3 (open question)."""
    return await _post("/projects", {"name": name, "type": project_type})


async def create_task(project_id: str, payload: dict) -> dict:
    """Create a task in a project — ``POST /projects/{project_id}/tasks``.
    ``payload`` is a ``build_task_payload()`` body (the metadata-only
    mirror, Phase 2)."""
    return await _post(f"/projects/{project_id}/tasks", payload)


async def list_team_time(
    date_from: str,
    date_to: str,
    *,
    page: int = 1,
    limit: Optional[int] = None,
) -> list[dict]:
    """One page of team time records over ``[date_from, date_to]`` —
    ``GET /team/time``. Bare-array response with no total-count field; the
    caller pages using ``next_page()`` (``len(result) < limit`` = last page,
    per the pagination docs). Phase 3's daily sync source."""
    params = {
        "from": date_from,
        "to": date_to,
        "page": page,
        "limit": limit or settings.everhour_sync_page_limit,
    }
    return await _get("/team/time", params) or []
