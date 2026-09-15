"""PAA → SEO Neo v1 API — the content half.

A per-client content-creation surface (PRD §8.1 — a card in the workspace
"Content Creation" section, its own route), NOT a Keyword Research tab. Pull
People-Also-Ask questions for a service-in-geo → select ~4 → save the set →
create the posts (one Blog Writer run per PAA + best-effort GBP post +
syndication refresh), with a cannibalization guard in front of the create.

Ships as a plain content surface (no feature flag): it is an organizer over an
existing paid SERP call that kicks off existing writers. Guardrail (PRD §9):
nothing here touches the SEO Neo authority layer.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from middleware.auth import require_auth
from models.paa import PaaCreatePostsRequest, PaaPullRequest, PaaSetCreateRequest
from services import paa_sets_service
from services.freeze import assert_not_frozen
from services.orchestrator import orchestrate_run

router = APIRouter(tags=["paa"])
logger = logging.getLogger(__name__)


@router.get("/clients/{client_id}/paa-sets")
async def list_sets(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """PAA sets for the client (newest first, with chosen/post counts)."""
    try:
        return {"sets": paa_sets_service.list_sets(str(client_id))}
    except Exception as exc:
        logger.error("paa_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/paa-sets/pull")
async def pull(
    client_id: UUID, body: PaaPullRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Pull PAA questions for a service-in-geo + market enrichment + a suggested
    'link high' service page. Reuses one billed SERP call. Does not persist."""
    return await paa_sets_service.pull_paa(
        str(client_id),
        service_keyword=body.service_keyword,
        geo_mode=body.geo_mode,
        location_override=body.location,
    )


@router.post("/clients/{client_id}/paa-sets", status_code=201)
async def create_set(
    client_id: UUID, body: PaaSetCreateRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Persist a PAA set + its chosen items (resolves the service-page URL)."""
    return paa_sets_service.create_set(
        str(client_id),
        service_keyword=body.service_keyword,
        items=[i.model_dump() for i in body.items],
        geo_mode=body.geo_mode,
        location=body.location,
        location_code=body.location_code,
        service_page_url=body.service_page_url,
        auto_service_page_url=body.auto_service_page_url,
        created_by=auth["user_id"],
    )


@router.get("/paa-sets/{set_id}")
async def get_set(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    return paa_sets_service.get_set(str(set_id))


@router.delete("/paa-sets/{set_id}")
async def delete_set(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    paa_sets_service.delete_set(str(set_id))
    return {"ok": True}


@router.get("/paa-sets/{set_id}/preflight")
async def preflight(
    set_id: UUID, acknowledge: bool = False, auth: dict = Depends(require_auth)
) -> dict:
    """The cannibalization guard for the set's chosen items (reused site-page
    matching + scale gates). Read-only — surfaces the gates before create."""
    return await paa_sets_service.preflight(str(set_id), acknowledge=acknowledge)


@router.post("/paa-sets/{set_id}/create-posts", status_code=202)
async def create_posts(
    set_id: UUID,
    body: PaaCreatePostsRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> dict:
    """Create the PAA posts: one Blog Writer run per chosen PAA + best-effort GBP
    post + syndication refresh. Blocked (200 with gates) unless a cannibalization
    sign-off is acknowledged. Content creation stops under a freeze."""
    set_row = paa_sets_service.get_set(str(set_id))
    assert_not_frozen(str(set_row["client_id"]))

    result = await paa_sets_service.create_posts(
        str(set_id), user_id=auth["user_id"], acknowledge=body.acknowledge
    )
    # Dispatch each blog run (sequential background tasks, like /runs/bulk).
    for run_id in result.get("run_ids", []):
        background_tasks.add_task(orchestrate_run, run_id)
    return result


@router.post("/paa-sets/{set_id}/verify")
async def verify(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Run the deterministic writer-constraint checks (exact-match + service-page
    link) on each chosen item whose blog run has finished; persist the verdict."""
    return paa_sets_service.verify_posts(str(set_id))
