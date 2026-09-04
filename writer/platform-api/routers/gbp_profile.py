"""Google Business Profile **Profile Editor** module router.

Read + edit a client's GBP description / services / hours via the v1 Business
Information API. Every edit is drafted (manual / AI) then applied on an EXPLICIT
operator click — nothing is auto-applied (ADR 0004). Applying is content output,
so it's Freeze-gated (assert_not_frozen); reads + drafts are not.

The whole surface returns 503 (gbp_profile_not_enabled) until both
``gbp_api_enabled`` and ``gbp_profile_enabled`` are set. Long-running actions
(read live / draft / apply) that call Google run as async jobs or awaited reads;
the UI polls .../jobs/status.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from middleware.auth import require_auth, require_staff
from models.gbp_profile import (
    GbpMonitorStatus,
    GbpProfileEdit,
    GbpProfileJob,
    GbpProfileJobsStatusRequest,
    GbpProfileJobStatus,
    GbpProfileResponse,
    ProfileDraftRequest,
    ProfileEditCreateRequest,
    ProfileEditPatchRequest,
    ProfileLintResponse,
    ServiceTypesResponse,
)
from models.gbp_posts import GbpLocationOption
from services import gbp_monitor
from services import gbp_profile_api as api
from services import gbp_profile_service as svc
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gbp-profile"])


# ── locations picker ─────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/profile-locations", response_model=list[GbpLocationOption])
async def list_profile_locations(client_id: UUID, auth: dict = Depends(require_auth)):
    """Registered GBP locations for this client (only 'ok' ones can be edited)."""
    svc._assert_enabled()
    return svc.list_ok_locations(str(client_id))


# ── read current live values ─────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/profile", response_model=GbpProfileResponse)
async def read_profile(
    client_id: UUID, location_row_id: UUID = Query(...), auth: dict = Depends(require_auth)
):
    """The three fields' LIVE current values for one location (always read fresh
    from Google — no cached 'current') plus the location's recent edit rows."""
    return await svc.read_current(str(client_id), str(location_row_id))


@router.get("/clients/{client_id}/gbp/profile/service-types", response_model=ServiceTypesResponse)
async def list_service_types(
    client_id: UUID, location_row_id: UUID = Query(...), auth: dict = Depends(require_auth)
):
    """The Google-defined service types the operator can pick for this listing,
    grouped by its categories (the services editor's only add path — VAs pick
    from Google's approved list, not free text)."""
    return await svc.list_service_types(str(client_id), str(location_row_id))


@router.post("/clients/{client_id}/gbp/profile/lint", response_model=ProfileLintResponse)
async def lint_description(client_id: UUID, body: dict, auth: dict = Depends(require_auth)):
    """Advisory description content-policy warnings (never a gate)."""
    svc._assert_enabled()
    return ProfileLintResponse(warnings=api.lint_description(body.get("description") or ""))


# ── edits (history + CRUD) ────────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/profile/edits", response_model=list[GbpProfileEdit])
async def list_edits(
    client_id: UUID, location_row_id: UUID | None = Query(None),
    field: str | None = Query(None), auth: dict = Depends(require_auth),
):
    return svc.list_edits(
        str(client_id),
        location_row_id=str(location_row_id) if location_row_id else None,
        field=field,
    )


@router.post("/clients/{client_id}/gbp/profile/edits", response_model=GbpProfileEdit)
async def create_edit(
    client_id: UUID, body: ProfileEditCreateRequest, auth: dict = Depends(require_staff)
):
    """Create a manual draft edit for one field (snapshots the live baseline)."""
    return await svc.create_edit(str(client_id), body.model_dump(mode="json"), auth["user_id"])


@router.post("/clients/{client_id}/gbp/profile/draft", response_model=GbpProfileJob)
async def draft_field(
    client_id: UUID, body: ProfileDraftRequest, auth: dict = Depends(require_staff)
):
    """AI-draft a field (description or services) — lands as a draft for review.
    Hours is manual-only. Never auto-applies."""
    job_id = svc.enqueue_draft(str(client_id), str(body.location_row_id), body.field, auth["user_id"])
    return GbpProfileJob(job_id=job_id)


@router.patch("/clients/{client_id}/gbp/profile/edits/{edit_id}", response_model=GbpProfileEdit)
async def update_edit(
    client_id: UUID, edit_id: UUID, body: ProfileEditPatchRequest,
    auth: dict = Depends(require_staff),
):
    """Edit a draft's proposed value before applying (re-validates)."""
    return await svc.update_edit(str(edit_id), body.model_dump(mode="json", exclude_unset=True))


@router.post("/clients/{client_id}/gbp/profile/edits/{edit_id}/apply", response_model=GbpProfileJob)
async def apply_edit(client_id: UUID, edit_id: UUID, auth: dict = Depends(require_staff)):
    """Apply a draft edit to Google (async, freeze-gated). Re-reads + diffs the
    live field first (aborts into live_changed if it drifted)."""
    assert_not_frozen(str(client_id))  # Freeze Protocol: content output paused
    job_id = svc.enqueue_apply(str(edit_id), str(client_id))
    return GbpProfileJob(job_id=job_id)


@router.post("/clients/{client_id}/gbp/profile/edits/{edit_id}/discard")
async def discard_edit(client_id: UUID, edit_id: UUID, auth: dict = Depends(require_staff)):
    """Discard a draft / re-review edit (never a live one)."""
    svc.discard_edit(str(edit_id))
    return {"ok": True}


@router.post("/clients/{client_id}/gbp/profile/edits/{edit_id}/refresh", response_model=GbpProfileJob)
async def refresh_edit(client_id: UUID, edit_id: UUID, auth: dict = Depends(require_staff)):
    """Manually kick the reconciler for a pending_review edit (Refresh status)."""
    job_id = svc.enqueue_sync(str(edit_id), str(client_id))
    return GbpProfileJob(job_id=job_id)


# ── profile monitor (suspension / out-of-band change watch) ───────────────────
@router.get("/clients/{client_id}/gbp/profile/monitor", response_model=GbpMonitorStatus)
async def monitor_status(
    client_id: UUID, location_row_id: UUID = Query(...), auth: dict = Depends(require_auth)
):
    """The monitor state for one location: access (ok / suspended / no_access),
    when it was last checked, and the last out-of-band change detected."""
    return gbp_monitor.get_monitor_status(str(client_id), str(location_row_id))


@router.post("/clients/{client_id}/gbp/profile/monitor/check", response_model=GbpProfileJob)
async def monitor_check(
    client_id: UUID, location_row_id: UUID = Query(...), auth: dict = Depends(require_staff)
):
    """Run a monitor check now (reads the live listing + diffs the baseline)."""
    job_id = gbp_monitor.enqueue_check(str(client_id), str(location_row_id))
    return GbpProfileJob(job_id=job_id)


# ── job status poll ──────────────────────────────────────────────────────────
@router.post("/clients/{client_id}/gbp/profile/jobs/status", response_model=list[GbpProfileJobStatus])
async def jobs_status(
    client_id: UUID, body: GbpProfileJobsStatusRequest, auth: dict = Depends(require_auth)
):
    svc._assert_enabled()
    return svc.get_jobs_status(str(client_id), [str(j) for j in body.job_ids])
