"""In-app Guides portal router.

Reads are auth-gated (any signed-in user); writes require the staff tier. The DB table is
the source of truth (seeded with defaults at startup). The editor lists all guides
(incl. disabled) via ?include_disabled=true.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from middleware.auth import require_auth, require_staff
from models.guides import Guide, GuideCreateRequest, GuideUpdateRequest
from services import guide_store, guide_sync

router = APIRouter(tags=["guides"])
logger = logging.getLogger(__name__)


@router.get("/guides", response_model=list[Guide])
async def list_guides(include_disabled: bool = False, auth: dict = Depends(require_auth)) -> list[Guide]:
    """All guides for display (enabled-only by default). The editor passes
    include_disabled=true to also see disabled drafts."""
    return [Guide(**r) for r in guide_store.list_guides(include_disabled=include_disabled)]


# ── DORA guide-sync runs (services/guide_sync.py) — static paths first so
# ``/guides/sync-runs/...`` never falls into ``/guides/{slug}``.
@router.get("/guides/sync-runs/{run_id}")
async def get_guide_sync_run(run_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """One run in full (incl. the prior/proposed bodies, for previewing a
    proposal or what a revert would restore)."""
    row = await run_in_threadpool(guide_sync.get_run, str(run_id))
    if not row:
        raise HTTPException(status_code=404, detail="guide_sync_run_not_found")
    return row


@router.post("/guides/sync-runs/{run_id}/apply")
async def apply_guide_sync_run(run_id: UUID, auth: dict = Depends(require_staff)) -> dict:
    """Apply a ``proposed`` DORA rewrite to the guide (staff)."""
    return await run_in_threadpool(guide_sync.apply_run, str(run_id), auth.get("user_id"))


@router.post("/guides/sync-runs/{run_id}/revert")
async def revert_guide_sync_run(run_id: UUID, auth: dict = Depends(require_staff)) -> dict:
    """Restore the guide body DORA replaced in an ``applied`` run (staff)."""
    return await run_in_threadpool(guide_sync.revert_run, str(run_id), auth.get("user_id"))


@router.post("/guides/sync-runs/{run_id}/dismiss")
async def dismiss_guide_sync_run(run_id: UUID, auth: dict = Depends(require_staff)) -> dict:
    """Decline a ``proposed`` rewrite (or acknowledge a rejected/failed one) (staff)."""
    return await run_in_threadpool(guide_sync.dismiss_run, str(run_id), auth.get("user_id"))


@router.get("/guides/{slug}/sync-runs")
async def list_guide_sync_runs(slug: str, limit: int = 20, auth: dict = Depends(require_auth)) -> list[dict]:
    """A guide's DORA sync history, newest first (bodies omitted — fetch a run
    by id to preview one)."""
    return await run_in_threadpool(guide_sync.list_runs, slug, max(1, min(limit, 100)))


@router.get("/guides/{slug}", response_model=Guide)
async def get_guide(slug: str, auth: dict = Depends(require_auth)) -> Guide:
    row = guide_store.get_guide(slug)
    if not row:
        raise HTTPException(status_code=404, detail="guide_not_found")
    return Guide(**row)


@router.post("/guides", response_model=Guide, status_code=201)
async def create_guide(body: GuideCreateRequest, auth: dict = Depends(require_staff)) -> Guide:
    row = guide_store.create_guide(
        slug=body.slug, title=body.title, body=body.body, summary=body.summary,
        category=body.category, icon=body.icon, sort_order=body.sort_order,
    )
    return Guide(**row)


@router.patch("/guides/{guide_id}", response_model=Guide)
async def update_guide(guide_id: UUID, body: GuideUpdateRequest, auth: dict = Depends(require_staff)) -> Guide:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="no_fields")
    return Guide(**guide_store.update_guide(str(guide_id), updates))


@router.delete("/guides/{guide_id}", status_code=204, response_class=Response)
async def delete_guide(guide_id: UUID, auth: dict = Depends(require_staff)) -> Response:
    guide_store.delete_guide(str(guide_id))
    return Response(status_code=204)
