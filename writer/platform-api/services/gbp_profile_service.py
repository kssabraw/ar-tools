"""GBP Profile Editor module — service layer.

Reads a client's live GBP description / services / hours (v1 ``locations.get``),
holds proposed edits (manual / AI / strategist) as ``gbp_profile_edits`` rows,
and applies one field at a time on an EXPLICIT operator click — never
auto-applies (ADR 0004). Apply re-reads the live field and aborts into
``live_changed`` if it drifted since the draft (Q3); Google's async
``pending_review`` verdict is chased by the self-continuing ``gbp_profile_sync``
reconciler (Q4/Q7, bounded backoff).

Freeze Protocol: applying is content *output* and pauses under a freeze
(``gbp_profile_apply`` + ``gbp_profile_sync`` are in ``FREEZE_GATED_JOB_TYPES``;
the apply route asserts too). Reads + drafting keep running — the SOP pauses
output, not observation.

The live get/patch go through the v1 discovery wrapper (``gbp_profile_api``); all
the field-shaping + validation + diffing lives there as pure, unit-tested
helpers. This layer owns lifecycle, jobs, and the DB.

See: docs/modules/gbp-profile-editor-prd-v1_0.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import gbp_profile_api as api

logger = logging.getLogger(__name__)

_EDIT_COLUMNS = (
    "id, client_id, location_row_id, field, source, current_value, proposed_value, "
    "status, google_pending, sync_attempts, next_sync_at, error, applied_at, "
    "created_by, created_at, updated_at"
)
# Statuses an edit can be applied from (a fresh draft, a re-review, or a retry).
_APPLIABLE = {"draft", "live_changed", "failed"}


# ───────────────────────────────────────────────────────────────────────────
# Gate + location resolution
# ───────────────────────────────────────────────────────────────────────────
def _assert_enabled() -> None:
    if not (settings.gbp_api_enabled and settings.gbp_profile_enabled):
        raise HTTPException(status_code=503, detail="gbp_profile_not_enabled")


def is_enabled() -> bool:
    return bool(settings.gbp_api_enabled and settings.gbp_profile_enabled)


def _client(client_id: str) -> dict:
    res = get_supabase().table("clients").select("*").eq("id", client_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data[0]


def list_ok_locations(client_id: str) -> list[dict]:
    """The client's registered GBP locations that can be read/edited."""
    res = (
        get_supabase().table("gbp_locations")
        .select("id, location_id, account_id, title, access_status")
        .eq("client_id", client_id).order("created_at").execute()
    )
    return res.data or []


def _location(location_row_id: str, client_id: str) -> dict:
    res = (
        get_supabase().table("gbp_locations")
        .select("id, client_id, location_id, account_id, title, access_status")
        .eq("id", location_row_id).limit(1).execute()
    )
    if not res.data or res.data[0].get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_location_not_found")
    return res.data[0]


def _location_name(location: dict) -> str:
    """The v1 resource name 'locations/{id}' (get/patch key on this alone)."""
    loc = (location.get("location_id") or "").strip()
    if not loc:
        raise HTTPException(status_code=400, detail="gbp_location_missing_id")
    return loc if loc.startswith("locations/") else f"locations/{loc.split('/')[-1]}"


# ───────────────────────────────────────────────────────────────────────────
# Read current live values (+ open edits) for one location
# ───────────────────────────────────────────────────────────────────────────
async def read_current(client_id: str, location_row_id: str) -> dict:
    """Live current values for the three fields (always read fresh — no cached
    'current', which drifts when someone edits in the Google dashboard) plus the
    location's recent edit rows. Raises a classified error on a read failure."""
    _assert_enabled()
    location = _location(location_row_id, client_id)
    name = _location_name(location)
    loc = await asyncio.to_thread(api.get_location, name)
    parsed = api.parse_location_fields(loc)
    edits = list_edits(client_id, location_row_id=location_row_id)
    return {
        "location_row_id": location["id"],
        "location_id": location["location_id"],
        "title": location.get("title") or parsed.get("title"),
        "description": parsed["description"],
        "hours": parsed["hours"],
        "services": parsed["services"],
        "categories": parsed["categories"],
        "metadata": parsed["metadata"],
        "edits": edits,
    }


async def list_service_types(client_id: str, location_row_id: str) -> dict:
    """The Google-defined service types the operator can pick for this listing —
    grouped by the listing's own categories (v1 categories.batchGet, view=FULL).
    The picker is one of two add paths (Google-approved picks + operator-authored
    custom services). Best-effort per category — a category with no structured
    services simply contributes an empty group."""
    _assert_enabled()
    location = _location(location_row_id, client_id)
    loc = await asyncio.to_thread(api.get_location, _location_name(location))
    categories = api.parse_categories(loc)
    resp = await asyncio.to_thread(
        api.list_service_types,
        [c["id"] for c in categories],
        settings.gbp_profile_service_region_code,
        settings.gbp_profile_service_language_code,
    )
    return {"categories": api.parse_service_types(resp, categories)}


def list_edits(client_id: str, location_row_id: Optional[str] = None, field: Optional[str] = None) -> list[dict]:
    _assert_enabled()
    query = (
        get_supabase().table("gbp_profile_edits").select(_EDIT_COLUMNS)
        .eq("client_id", client_id)
    )
    if location_row_id:
        query = query.eq("location_row_id", location_row_id)
    if field:
        query = query.eq("field", field)
    return query.order("created_at", desc=True).limit(100).execute().data or []


def get_edit(edit_id: str) -> dict:
    res = get_supabase().table("gbp_profile_edits").select("*").eq("id", edit_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="gbp_profile_edit_not_found")
    return res.data[0]


# ───────────────────────────────────────────────────────────────────────────
# Proposed-value extraction + validation (per field, via the pure builders)
# ───────────────────────────────────────────────────────────────────────────
def _proposed_from_request(field: str, body: dict) -> object:
    """Pull the field's proposed value out of a request body and normalize it to
    the internal shape stored in ``proposed_value``. Raises 400 when absent."""
    if field == "description":
        if body.get("description") is None:
            raise HTTPException(status_code=400, detail="description_required")
        return body["description"]
    if field == "hours":
        if body.get("hours") is None:
            raise HTTPException(status_code=400, detail="hours_required")
        return body["hours"]
    if field == "services":
        if body.get("services") is None:
            raise HTTPException(status_code=400, detail="services_required")
        return body["services"]
    raise HTTPException(status_code=400, detail="invalid_field")


def _build_patch(field: str, proposed, allowed_categories: Optional[set[str]] = None) -> tuple[dict, str]:
    """Build the (body, updateMask) for a field's proposed value via the pure
    api builders, translating ValueError into a 400 with the code."""
    try:
        if field == "description":
            return api.build_description_patch(proposed, settings.gbp_profile_description_max_chars)
        if field == "hours":
            value = proposed or {}
            return api.build_hours_patch(value.get("regular") or [], value.get("special"))
        if field == "services":
            return api.build_services_patch(proposed or [], allowed_categories=allowed_categories)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=400, detail="invalid_field")


def _field_value(parsed: dict, field: str) -> object:
    if field == "description":
        return parsed["description"]
    if field == "hours":
        return parsed["hours"]
    return parsed["services"]


# ───────────────────────────────────────────────────────────────────────────
# Create / edit / discard a draft
# ───────────────────────────────────────────────────────────────────────────
async def create_edit(client_id: str, body: dict, user_id: Optional[str], source: str = "manual") -> dict:
    """Create a draft edit for one field, snapshotting the live current value as
    the re-read-and-diff baseline. Validates the proposed value up front."""
    _assert_enabled()
    field = body.get("field")
    location = _location(str(body["location_row_id"]), client_id)
    proposed = _proposed_from_request(field, body)
    # Snapshot the live current value + validate the proposed value (services
    # validated against the listing's live categories).
    loc = await asyncio.to_thread(api.get_location, _location_name(location))
    parsed = api.parse_location_fields(loc)
    allowed = {c["id"] for c in parsed["categories"]} if field == "services" else None
    _build_patch(field, proposed, allowed_categories=allowed)  # raises 400 on invalid
    row = {
        "client_id": client_id,
        "location_row_id": location["id"],
        "field": field,
        "source": source,
        "current_value": _field_value(parsed, field),
        "proposed_value": proposed,
        "status": "draft",
        "created_by": user_id,
    }
    res = get_supabase().table("gbp_profile_edits").insert(row).execute()
    return res.data[0]


async def update_edit(edit_id: str, body: dict) -> dict:
    """Edit a draft's proposed value before applying (re-validates)."""
    _assert_enabled()
    edit = get_edit(edit_id)
    if edit["status"] not in _APPLIABLE:
        raise HTTPException(status_code=409, detail=f"edit_not_editable:{edit['status']}")
    proposed = _proposed_from_request(edit["field"], body)
    location = _location(edit["location_row_id"], edit["client_id"])
    allowed = None
    if edit["field"] == "services":
        loc = await asyncio.to_thread(api.get_location, _location_name(location))
        allowed = {c["id"] for c in api.parse_categories(loc)}
    _build_patch(edit["field"], proposed, allowed_categories=allowed)
    res = (
        get_supabase().table("gbp_profile_edits")
        .update({"proposed_value": proposed, "status": "draft", "error": None, "updated_at": "now()"})
        .eq("id", edit_id).execute()
    )
    return res.data[0]


def discard_edit(edit_id: str) -> None:
    """Delete a draft/re-review edit (never a live/applied one)."""
    _assert_enabled()
    edit = get_edit(edit_id)
    if edit["status"] in ("applying", "pending_review"):
        raise HTTPException(status_code=409, detail=f"edit_in_flight:{edit['status']}")
    get_supabase().table("gbp_profile_edits").delete().eq("id", edit_id).execute()


# ───────────────────────────────────────────────────────────────────────────
# Apply (async job; freeze-gated) — with re-read-and-diff (Q3)
# ───────────────────────────────────────────────────────────────────────────
def enqueue_apply(edit_id: str, client_id: str) -> str:
    """Apply a draft edit NOW: mark it applying + enqueue the gbp_profile_apply
    job. Returns the job id. The route asserts not-frozen first."""
    _assert_enabled()
    edit = get_edit(edit_id)
    if edit.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_profile_edit_not_found")
    if edit["status"] not in _APPLIABLE:
        raise HTTPException(status_code=409, detail=f"edit_not_appliable:{edit['status']}")
    get_supabase().table("gbp_profile_edits").update(
        {"status": "applying", "error": None, "updated_at": "now()"}
    ).eq("id", edit_id).execute()
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_profile_apply", "entity_id": client_id,
                 "payload": {"client_id": client_id, "edit_id": edit_id}})
        .execute()
    )
    return res.data[0]["id"]


def _set_edit(edit_id: str, fields: dict) -> None:
    fields = {**fields, "updated_at": "now()"}
    get_supabase().table("gbp_profile_edits").update(fields).eq("id", edit_id).execute()


async def _refresh_monitor_baseline(location_row_id: str, client_id: str, field: str) -> None:
    """After OUR apply of ``field`` goes live, advance that field in the profile
    monitor's baseline so it doesn't flag the change as out-of-band. Best-effort
    (lazy import to avoid a module cycle) — never affects the apply outcome."""
    try:
        from services import gbp_monitor  # lazy — gbp_monitor imports this module

        await gbp_monitor.refresh_baseline(location_row_id, client_id, field)
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_profile.monitor_refresh_failed", extra={"error": str(exc)[:200]})


def _pending_or_terminal(field: str, proposed, live_field, metadata: dict) -> dict:
    """Decide an applied edit's post-patch state from the read-back. Pure.

    - live == proposed  → applied (the change is live)
    - hasPendingEdits   → pending_review (Google queued it; reconciler chases it)
    - else (settled, live != proposed) → the patch didn't take → rejected
    """
    if not api.diff_field(field, proposed, live_field):
        return {"status": "applied", "google_pending": False}
    if metadata.get("has_pending_edits"):
        return {"status": "pending_review", "google_pending": True}
    return {"status": "rejected", "google_pending": False}


async def run_apply_job(job: dict) -> None:
    """Handler for job_type='gbp_profile_apply'. Re-reads the live field, aborts
    into live_changed if it drifted since the draft, else patches the single
    field and records the outcome (applied / pending_review / rejected)."""
    payload = job.get("payload") or {}
    edit_id = payload.get("edit_id")
    client_id = payload.get("client_id")
    supabase = get_supabase()
    try:
        edit = get_edit(edit_id)
        # Idempotency: a requeue after a resolved apply must not re-patch.
        if edit["status"] in ("applied", "rejected", "live_changed"):
            _settle_job(job["id"], {"edit_id": edit_id, "state": edit["status"], "already": True})
            return
        field = edit["field"]
        location = _location(edit["location_row_id"], client_id)
        name = _location_name(location)

        # Re-read the live field and diff against the draft snapshot (Q3).
        loc = await asyncio.to_thread(api.get_location, name)
        parsed = api.parse_location_fields(loc)
        live_now = _field_value(parsed, field)
        if api.diff_field(field, edit.get("current_value"), live_now):
            _set_edit(edit_id, {"status": "live_changed", "error": None})
            _settle_job(job["id"], {"edit_id": edit_id, "state": "live_changed"})
            logger.info("gbp_profile.live_changed", extra={"edit_id": edit_id, "field": field})
            return

        # Build + apply the single-field patch.
        allowed = {c["id"] for c in parsed["categories"]} if field == "services" else None
        body, mask = _build_patch(field, edit["proposed_value"], allowed_categories=allowed)
        patched = await asyncio.to_thread(api.patch_location, name, body, mask, field)
        pparsed = api.parse_location_fields(patched)
        outcome = _pending_or_terminal(field, edit["proposed_value"], _field_value(pparsed, field), pparsed["metadata"])

        update: dict = {**outcome, "error": None}
        if outcome["status"] == "applied":
            update["applied_at"] = "now()"
            update["next_sync_at"] = None
        elif outcome["status"] == "pending_review":
            update["applied_at"] = "now()"  # submitted to Google
            update["sync_attempts"] = 0
            update["next_sync_at"] = _iso(datetime.now(timezone.utc) + timedelta(seconds=settings.gbp_profile_sync_delay_seconds))
        else:  # rejected
            update["error"] = "google_rejected_or_reverted"
        _set_edit(edit_id, update)
        _settle_job(job["id"], {"edit_id": edit_id, "state": outcome["status"]})
        if outcome["status"] == "applied":
            await _refresh_monitor_baseline(edit["location_row_id"], client_id, field)
        if outcome["status"] == "rejected":
            _notify(client_id, "gbp_profile_rejected", "GBP profile edit rejected",
                    f"Google rejected the {field} edit.", "warning", edit_id, field)
        logger.info("gbp_profile.applied", extra={"edit_id": edit_id, "field": field, "state": outcome["status"]})
    except Exception as exc:  # noqa: BLE001 — record failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        _set_edit(edit_id, {"status": "failed", "error": str(detail)[:500]})
        _settle_job(job["id"], None, error=str(detail)[:500])
        _notify(client_id, "gbp_profile_failed", "GBP profile edit failed",
                str(detail)[:200], "warning", edit_id)
        logger.warning("gbp_profile.apply_failed", extra={"edit_id": edit_id, "error": str(detail)})


# ───────────────────────────────────────────────────────────────────────────
# Reconciler (gbp_profile_sync) — self-continuing bounded backoff (Q4/Q7)
# ───────────────────────────────────────────────────────────────────────────
def _active_sync_job(edit_id: str) -> bool:
    rows = (
        get_supabase().table("async_jobs").select("id, payload")
        .eq("job_type", "gbp_profile_sync").in_("status", ["pending", "running"])
        .execute().data or []
    )
    return any((r.get("payload") or {}).get("edit_id") == edit_id for r in rows)


def enqueue_due_gbp_profile_syncs() -> int:
    """Per-cycle sweep: enqueue a gbp_profile_sync check for each pending_review
    edit whose backoff clock (next_sync_at) has come due. The worker claims by
    scheduled_at with no <=now gate, so the backoff lives on the edit row, not
    the job — this is the leadoff_geocode 'self-continuing' shape. No-op until
    the module is enabled."""
    if not is_enabled():
        return 0
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    due = (
        supabase.table("gbp_profile_edits").select("id, client_id")
        .eq("status", "pending_review").not_.is_("next_sync_at", "null")
        .lte("next_sync_at", now.isoformat()).execute().data or []
    )
    count = 0
    for edit in due:
        if _active_sync_job(edit["id"]):
            continue
        try:
            supabase.table("async_jobs").insert(
                {"job_type": "gbp_profile_sync", "entity_id": edit["client_id"],
                 "payload": {"client_id": edit["client_id"], "edit_id": edit["id"]}}
            ).execute()
            count += 1
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("gbp_profile.sync_enqueue_failed", extra={"edit_id": edit["id"], "error": str(exc)})
    if count:
        logger.info("gbp_profile.syncs_enqueued", extra={"edits": count})
    return count


def enqueue_sync(edit_id: str, client_id: str) -> str:
    """Manual 'Refresh status' — enqueue one immediate reconciler check for a
    pending_review edit (works even after the backoff ladder gave up)."""
    _assert_enabled()
    edit = get_edit(edit_id)
    if edit.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_profile_edit_not_found")
    if edit["status"] != "pending_review":
        raise HTTPException(status_code=409, detail=f"edit_not_pending:{edit['status']}")
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_profile_sync", "entity_id": client_id,
                 "payload": {"client_id": client_id, "edit_id": edit_id}})
        .execute()
    )
    return res.data[0]["id"]


def next_backoff(attempts: int) -> Optional[int]:
    """Seconds to the next reconciler check given how many have run, or None when
    the ladder is exhausted (give up → stays pending_review, manual refresh).
    Pure (unit-tested)."""
    ladder = settings.gbp_profile_sync_backoff or []
    if attempts < 0 or attempts >= len(ladder):
        return None
    return ladder[attempts]


async def run_sync_job(job: dict) -> None:
    """Handler for job_type='gbp_profile_sync'. One reconciler check: re-read the
    live field, settle the edit (applied/rejected) or advance the backoff clock.
    The row's next_sync_at drives the next check via the per-cycle sweep."""
    payload = job.get("payload") or {}
    edit_id = payload.get("edit_id")
    client_id = payload.get("client_id")
    try:
        edit = get_edit(edit_id)
        if edit["status"] != "pending_review":
            _settle_job(job["id"], {"edit_id": edit_id, "state": edit["status"], "settled": True})
            return
        field = edit["field"]
        location = _location(edit["location_row_id"], client_id)
        loc = await asyncio.to_thread(api.get_location, _location_name(location))
        parsed = api.parse_location_fields(loc)
        live_now = _field_value(parsed, field)

        if not api.diff_field(field, edit["proposed_value"], live_now):
            _set_edit(edit_id, {"status": "applied", "google_pending": False,
                                "next_sync_at": None, "error": None})
            _settle_job(job["id"], {"edit_id": edit_id, "state": "applied"})
            await _refresh_monitor_baseline(edit["location_row_id"], client_id, field)
            logger.info("gbp_profile.reconciled_applied", extra={"edit_id": edit_id})
            return
        if not parsed["metadata"].get("has_pending_edits"):
            # Google finished and the value didn't take → rejected/reverted.
            _set_edit(edit_id, {"status": "rejected", "google_pending": False,
                                "next_sync_at": None, "error": "google_rejected_or_reverted"})
            _settle_job(job["id"], {"edit_id": edit_id, "state": "rejected"})
            _notify(client_id, "gbp_profile_rejected", "GBP profile edit rejected",
                    f"Google rejected the {field} edit.", "warning", edit_id, field)
            return
        # Still pending — advance the backoff clock, or give up (stays pending).
        attempts = int(edit.get("sync_attempts") or 0) + 1
        delay = next_backoff(attempts)
        update = {"sync_attempts": attempts, "google_pending": True}
        if delay is None:
            update["next_sync_at"] = None  # give up; manual refresh remains
            logger.info("gbp_profile.sync_gave_up", extra={"edit_id": edit_id, "attempts": attempts})
        else:
            update["next_sync_at"] = _iso(datetime.now(timezone.utc) + timedelta(seconds=delay))
        _set_edit(edit_id, update)
        _settle_job(job["id"], {"edit_id": edit_id, "state": "pending_review", "attempts": attempts})
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        _settle_job(job["id"], None, error=str(detail)[:500])
        logger.warning("gbp_profile.sync_failed", extra={"edit_id": edit_id, "error": str(detail)})


# ───────────────────────────────────────────────────────────────────────────
# AI drafting (async job) — Phase 2. Hours is never AI-drafted.
# ───────────────────────────────────────────────────────────────────────────
def enqueue_draft(
    client_id: str, location_row_id: str, field: str, user_id: Optional[str],
    source: str = "ai",
) -> str:
    """Enqueue a gbp_profile_draft job (drafts a description or services edit as a
    status='draft' row for review). Hours is manual-only. Returns the job id."""
    _assert_enabled()
    if field not in ("description", "services"):
        raise HTTPException(status_code=400, detail="field_not_ai_draftable")
    location = _location(location_row_id, client_id)
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_profile_draft", "entity_id": client_id, "payload": {
            "client_id": client_id, "location_row_id": location["id"],
            "field": field, "user_id": user_id, "source": source,
        }})
        .execute()
    )
    return res.data[0]["id"]


_DESC_SYSTEM = (
    "You write the 'from the business' description for a local business's Google "
    "Business Profile. Rules you MUST follow:\n"
    "- Under 750 characters; aim for 2–4 plain, warm sentences.\n"
    "- Describe what the business does, who it serves, and where — grounded ONLY "
    "in the facts provided. NEVER invent services, awards, years in business, or "
    "guarantees.\n"
    "- NO URLs and NO phone numbers (both get the description rejected).\n"
    "- No promotional superlatives (best / #1 / guaranteed), no ALL-CAPS, no emoji.\n"
    "- No medical, legal, or other regulated claims.\n"
    "- Match the business's brand voice when given.\n"
    "Return ONLY the description text — no preamble, no quotes, no markdown."
)

_SERVICES_SYSTEM = (
    "You choose which of Google's approved service types apply to a local "
    "business's Google Business Profile. You are given the ONLY allowed service "
    "types (Google-defined, per the listing's categories). Return ONLY a JSON "
    "array (no prose) of the serviceTypeId strings that genuinely match the "
    "business's real offering — up to 20, most relevant first. Pick ONLY ids from "
    "the provided list; NEVER invent an id or a service. Choose a service type "
    "only if the business actually offers it."
)


async def _draft_description(client: dict, current: str, card: Optional[dict]) -> str:
    from services import anthropic_failover  # lazy
    from services.gbp_posts_service import build_client_context, render_voice_card_block, voice_forbidden_hits
    from services.report_llm import retry_transient

    ask = [
        "Write the business description for this Google Business Profile.",
        f"Current description (improve on it; empty if none): {current or '(none)'}",
    ]
    user = build_client_context(client) + "\n\n" + "\n".join(ask)
    voice_block = render_voice_card_block(card)
    if voice_block:
        user += "\n\n" + voice_block
    api_client = anthropic_failover.FailoverAsyncAnthropic(timeout=60)

    async def _one_call(content: str) -> str:
        resp = await retry_transient(
            lambda: api_client.messages.create(
                model=settings.gbp_profile_draft_model, max_tokens=settings.gbp_profile_draft_max_tokens,
                system=_DESC_SYSTEM, messages=[{"role": "user", "content": content}],
            ),
            max_retries=2, log_tag="gbp_profile_desc_draft",
        )
        return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

    text = (await _one_call(user))[: settings.gbp_profile_description_max_chars]
    # Enforce the deterministic content rules + the voice never-use list; one
    # corrective rewrite (keep the version with fewer violations).
    hits = voice_forbidden_hits(text, card) + _content_violations(text)
    if hits:
        fix = (
            "Rewrite this Google Business Profile description to REMOVE these problems "
            f"entirely: {', '.join(hits)}. Keep the same meaning and brand voice, under "
            "750 characters, no URLs or phone numbers. Return ONLY the description.\n\n" + text
        )
        try:
            rewritten = (await _one_call(fix))[: settings.gbp_profile_description_max_chars]
            new_hits = voice_forbidden_hits(rewritten, card) + _content_violations(rewritten)
            if rewritten and len(new_hits) < len(hits):
                text = rewritten
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.info("gbp_profile.desc_correction_failed", extra={"error": str(exc)[:200]})
    return text


def _content_violations(text: str) -> list[str]:
    """The deterministic description trip-wires present in the text (for the
    corrective rewrite input). Pure."""
    hits = []
    if api._URL_RE.search(text or ""):
        hits.append("a URL")
    if api._PHONE_RE.search(text or ""):
        hits.append("a phone number")
    return hits


async def _draft_services(
    client: dict, categories: list[dict], existing: list[dict], card: Optional[dict],
    service_types: list[dict],
) -> list[dict]:
    from services import anthropic_failover  # lazy
    from services.gbp_posts_service import build_client_context, render_voice_card_block
    from services.report_llm import retry_transient

    type_lines: list[str] = []
    for cat in service_types:
        if not cat.get("service_types"):
            continue
        type_lines.append(f"Category — {cat['name']}:")
        type_lines.extend(f"  - {st['display_name']} (id: {st['service_type_id']})" for st in cat["service_types"])
    available = "\n".join(type_lines) or "(no structured service types available for these categories)"
    grounding = _services_grounding(client, existing)
    ask = [
        "Choose the Google-approved service types that apply to this Google Business Profile.",
        f"Allowed service types (pick ONLY serviceTypeIds from here):\n{available}",
        f"Known offering / existing services / silo topics:\n{grounding}",
    ]
    user = build_client_context(client) + "\n\n" + "\n".join(ask)
    voice_block = render_voice_card_block(card)
    if voice_block:
        user += "\n\n" + voice_block
    api_client = anthropic_failover.FailoverAsyncAnthropic(timeout=60)
    resp = await retry_transient(
        lambda: api_client.messages.create(
            model=settings.gbp_profile_draft_model, max_tokens=settings.gbp_profile_draft_max_tokens,
            system=_SERVICES_SYSTEM, messages=[{"role": "user", "content": user}],
        ),
        max_retries=2, log_tag="gbp_profile_services_draft",
    )
    raw = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    return map_drafted_service_types(raw, service_types)


def _services_grounding(client: dict, existing: list[dict]) -> str:
    """Best-effort services grounding: existing live free-form labels + client
    silo topics (local_seo_pages keywords) + captured GBP categories."""
    lines: list[str] = []
    live = [s.get("label") for s in (existing or []) if s.get("kind") == "free_form" and s.get("label")]
    if live:
        lines.append("Existing services on the listing: " + ", ".join(live))
    gbp = client.get("gbp") or {}
    if isinstance(gbp, dict):
        cats = gbp.get("categories") or gbp.get("category")
        if cats:
            lines.append(f"Captured GBP categories: {cats if isinstance(cats, str) else ', '.join(map(str, cats))}")
    try:
        rows = (
            get_supabase().table("local_seo_pages").select("keyword")
            .eq("client_id", client["id"]).is_("deleted_at", "null")
            .order("created_at", desc=True).limit(30).execute().data or []
        )
        kws = [r["keyword"] for r in rows if r.get("keyword")]
        if kws:
            lines.append("Service/silo topics from the client's Local SEO pages: " + ", ".join(kws[:30]))
    except Exception as exc:  # noqa: BLE001 — best-effort grounding, never blocks
        logger.info("gbp_profile.services_grounding_failed", extra={"error": str(exc)[:200]})
    return "\n".join(lines) or "(no extra grounding on file)"


def map_drafted_services(raw: str, categories: list[dict]) -> list[dict]:
    """Parse the model's JSON services array and map each service's suggested
    category (a display name) to a listing category id — the AI SUGGESTS, the
    operator confirms (Q11). Falls back to the primary category id when the model
    names one that isn't on the listing. Pure (unit-tested)."""
    by_name = {c["name"].strip().lower(): c["id"] for c in categories}
    default_id = categories[0]["id"] if categories else ""
    try:
        data = json.loads(_json_slice(raw))
    except Exception:  # noqa: BLE001 — a non-JSON reply degrades to empty
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        label = (item.get("label") or "").strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        cat_name = (item.get("category") or "").strip().lower()
        category_id = by_name.get(cat_name) or default_id
        out.append({
            "kind": "free_form", "label": label[:120],
            "description": (item.get("description") or "").strip(),
            "category_id": category_id,
        })
    return out


def merge_drafted_services(existing: list[dict], additions: list[dict]) -> list[dict]:
    """Additive AI draft: keep the listing's existing services and append the
    newly-suggested structured picks not already present (by serviceTypeId), so a
    'Suggest with AI' never DROPS an existing custom or structured service when
    applied (the proposed value replaces the whole serviceItems list). Pure
    (unit-tested)."""
    have = {
        (s.get("service_type_id") or s.get("label") or "").strip()
        for s in existing or [] if (s.get("kind") or "free_form") == "structured"
    }
    merged = list(existing or [])
    for add in additions or []:
        sid = (add.get("service_type_id") or "").strip()
        if sid and sid in have:
            continue
        if sid:
            have.add(sid)
        merged.append(add)
    return merged


def map_drafted_service_types(raw: str, service_types: list[dict]) -> list[dict]:
    """Parse the model's JSON array of serviceTypeIds and map each to a structured
    pick ``{kind:'structured', service_type_id, label, category_id}``. Drops any id
    not in the available list (the model can only SUGGEST from Google's approved
    set — Q11). Accepts bare-string ids or ``{"service_type_id": ...}`` objects.
    Pure (unit-tested)."""
    by_id: dict[str, tuple[str, str]] = {}
    for cat in service_types or []:
        for st in cat.get("service_types") or []:
            sid = st.get("service_type_id")
            if sid and sid not in by_id:
                by_id[sid] = (st.get("display_name") or sid, cat.get("id") or "")
    try:
        data = json.loads(_json_slice(raw))
    except Exception:  # noqa: BLE001 — a non-JSON reply degrades to empty
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            stid = item.strip()
        elif isinstance(item, dict):
            stid = (item.get("service_type_id") or item.get("serviceTypeId") or "").strip()
        else:
            continue
        if not stid or stid in seen or stid not in by_id:
            continue
        seen.add(stid)
        label, category_id = by_id[stid]
        out.append({
            "kind": "structured", "service_type_id": stid,
            "label": label, "category_id": category_id,
        })
    return out


def _json_slice(raw: str) -> str:
    """The first [...] JSON array in a model reply (tolerates prose/fences)."""
    start = raw.find("[")
    end = raw.rfind("]")
    return raw[start:end + 1] if 0 <= start < end else raw


async def run_draft_job(job: dict) -> None:
    """Handler for job_type='gbp_profile_draft'. Reads the live field, drafts a
    proposed value (description or services), and lands it as a status='draft'
    edit for review. Drafting runs during a freeze (observation)."""
    payload = job.get("payload") or {}
    client_id = payload["client_id"]
    field = payload["field"]
    supabase = get_supabase()
    try:
        client = _client(client_id)
        location = _location(payload["location_row_id"], client_id)
        loc = await asyncio.to_thread(api.get_location, _location_name(location))
        parsed = api.parse_location_fields(loc)
        from services import voice_card_service  # lazy (avoids import cycle)

        card = await voice_card_service.get_voice_card(client, user_id=payload.get("user_id"))
        if field == "description":
            proposed = await _draft_description(client, parsed["description"], card)
            current = parsed["description"]
            if not proposed:
                raise HTTPException(status_code=502, detail="empty_draft")
        else:  # services
            resp = await asyncio.to_thread(
                api.list_service_types,
                [c["id"] for c in parsed["categories"]],
                settings.gbp_profile_service_region_code,
                settings.gbp_profile_service_language_code,
            )
            service_types = api.parse_service_types(resp, parsed["categories"])
            ai_picks = await _draft_services(client, parsed["categories"], parsed["services"], card, service_types)
            current = parsed["services"]
            if not ai_picks:
                raise HTTPException(status_code=502, detail="empty_draft")
            # Additive: keep existing services, append the AI's new picks — an AI
            # draft must never drop the operator's existing custom services.
            proposed = merge_drafted_services(current, ai_picks)

        row = {
            "client_id": client_id, "location_row_id": location["id"], "field": field,
            "source": payload.get("source") or "ai", "current_value": current,
            "proposed_value": proposed, "status": "draft", "created_by": payload.get("user_id"),
        }
        edit = supabase.table("gbp_profile_edits").insert(row).execute().data[0]
        _settle_job(job["id"], {"edit_id": edit["id"], "field": field})
        logger.info("gbp_profile.drafted", extra={"edit_id": edit["id"], "field": field})
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        _settle_job(job["id"], None, error=str(detail)[:500])
        logger.warning("gbp_profile.draft_failed", extra={"job_id": job["id"], "error": str(detail)})


# ───────────────────────────────────────────────────────────────────────────
# Strategist loop — stage a draft from a diagnosis (never applies; Q6)
# ───────────────────────────────────────────────────────────────────────────
async def stage_strategist_draft(client_id: str, location_row_id: str, field: str, proposed) -> dict:
    """Stage a proposed edit as a status='draft', source='strategist' row for a
    human to review + apply. Used by the SerMaStr action + the Action-Plan
    producer — it never applies (consistent with no-auto-apply + propose-only)."""
    return await create_edit(
        client_id,
        {"location_row_id": location_row_id, "field": field, field: proposed},
        user_id=None, source="strategist",
    )


def primary_location_row_id(client_id: str) -> Optional[str]:
    """The client's first 'ok' registered GBP location, for a strategist stage
    that isn't location-specific. None when the client has none."""
    for loc in list_ok_locations(client_id):
        if loc.get("access_status") == "ok":
            return loc["id"]
    return None


# ───────────────────────────────────────────────────────────────────────────
# Job status poll + small helpers
# ───────────────────────────────────────────────────────────────────────────
def get_jobs_status(client_id: str, job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error, entity_id")
        .in_("id", job_ids).execute().data or []
    )
    out = []
    for r in rows:
        if r.get("entity_id") != client_id:
            continue
        result = r.get("result") or {}
        out.append({"job_id": r["id"], "status": r["status"],
                    "edit_id": result.get("edit_id"), "error": r.get("error")})
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _settle_job(job_id: str, result: Optional[dict], error: Optional[str] = None) -> None:
    fields = {"status": "failed" if error else "complete", "completed_at": "now()"}
    if error:
        fields["error"] = error
    else:
        fields["result"] = result or {}
    get_supabase().table("async_jobs").update(fields).eq("id", job_id).execute()


def _notify(client_id: str, kind: str, title: str, summary: str, severity: str,
            edit_id: Optional[str] = None, field: Optional[str] = None) -> None:
    try:
        from services import notifications  # lazy

        payload = {"edit_id": edit_id}
        if field:
            payload["field"] = field
        notifications.emit(client_id, kind, title, summary=summary, severity=severity, payload=payload)
    except Exception as exc:  # noqa: BLE001 — notification is best-effort
        logger.info("gbp_profile.notify_failed", extra={"error": str(exc)[:200]})
