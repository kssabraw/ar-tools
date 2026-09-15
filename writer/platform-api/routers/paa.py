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

import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from config import settings
from middleware.auth import require_auth
from models.paa import (
    PaaCampaignStartRequest,
    PaaCreatePostsRequest,
    PaaDrillConfirmRequest,
    PaaManifestAssetCreate,
    PaaManifestAssetUpdate,
    PaaPullRequest,
    PaaSetCreateRequest,
)
from services import paa_campaign_service, paa_manifest_service, paa_sets_service
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


# ── Phase 2 — the prep-sheet manifest (track / cost / QA / hand-off) ──────────
# The manifest auto-collects the URLs of assets the suite already produced,
# tracks the human/authority work as rows, costs it (reused Recipe Engine), QAs
# the content (reused QA Agent), and exports it. Guardrail (PRD §9): the suite
# tracks / costs / QAs / hands off — it NEVER executes the authority layer.


@router.get("/paa-sets/{set_id}/manifest")
async def get_manifest(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The prep-sheet manifest for a set (``{exists: false}`` if not built yet)."""
    return paa_manifest_service.get_manifest(set_id=str(set_id))


@router.post("/paa-sets/{set_id}/manifest/build")
async def build_manifest(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Build or refresh the manifest: auto-collect the suite-produced asset URLs,
    seed the authority bundle + media checklist (first build only), recompute the
    cost + QA roll-ups. Preserves operator edits on a rebuild."""
    return paa_manifest_service.build_manifest(str(set_id), user_id=auth["user_id"])


@router.get("/paa-manifests/{manifest_id}")
async def get_manifest_by_id(manifest_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    return paa_manifest_service.get_manifest(manifest_id=str(manifest_id))


@router.post("/paa-manifests/{manifest_id}/qa", status_code=202)
async def manifest_qa(manifest_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Enqueue the QA pass: review each content asset's live URL via the QA Agent
    (gated on qa_enabled; deterministic v1 checks as the free fallback)."""
    job_id = paa_manifest_service.enqueue_qa(str(manifest_id))
    return {"job_id": job_id}


@router.post("/paa-manifests/{manifest_id}/assets", status_code=201)
async def add_manifest_asset(
    manifest_id: UUID, body: PaaManifestAssetCreate, auth: dict = Depends(require_auth)
) -> dict:
    """Add a manual asset row (a hand-captured content / authority / media item)."""
    return paa_manifest_service.add_asset(str(manifest_id), body.model_dump())


@router.patch("/paa-manifest-assets/{asset_id}")
async def update_manifest_asset(
    asset_id: UUID, body: PaaManifestAssetUpdate, auth: dict = Depends(require_auth)
) -> dict:
    """Operator edit to a manifest asset (status / url / note / cost)."""
    return paa_manifest_service.update_asset(
        str(asset_id), body.model_dump(exclude_none=True)
    )


@router.delete("/paa-manifest-assets/{asset_id}")
async def delete_manifest_asset(asset_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    return paa_manifest_service.delete_asset(str(asset_id))


@router.get("/paa-manifests/{manifest_id}/export")
async def export_manifest(
    manifest_id: UUID, format: str = "json", auth: dict = Depends(require_auth)
):
    """Export the prep sheet as JSON (default) or CSV — the deterministic
    download half of the hand-off (the client-identity header + every asset row
    with its confidence tag)."""
    export = paa_manifest_service.build_export(str(manifest_id))
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in export["rows"]:
            writer.writerow(row)
        filename = "paa-prep-sheet.csv"
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return export["payload"]


@router.post("/paa-manifests/{manifest_id}/export/sheet")
async def export_manifest_sheet(manifest_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Export the prep sheet to a Google Sheet in the client's Drive folder (the
    hand-off artifact; reuses the Apps Script webhook)."""
    return await paa_manifest_service.export_to_sheet(str(manifest_id))


# ── Phase 3 — the Service PAA Campaign + the automated single-variable gate ────
# A campaign wraps a PAA set in a state machine that runs the methodology's
# content→settle→scan→gate loop and hands off the (Phase-2) manifest. Autonomy is
# hybrid propose-confirm: the two paid/content steps (scan, drill) are human-
# confirmed here. Ships dark behind paa_campaign_enabled. Guardrail (PRD §9): the
# campaign orchestrates + tracks + hands off — it NEVER executes the authority layer.


def _require_campaigns_enabled() -> None:
    if not settings.paa_campaign_enabled:
        raise HTTPException(status_code=503, detail="paa_campaign_not_enabled")


@router.get("/paa-sets/{set_id}/campaign")
async def get_campaign_for_set(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The campaign for a set (``{exists: false}`` if none / feature off)."""
    if not settings.paa_campaign_enabled:
        return {"exists": False, "enabled": False, "set_id": str(set_id)}
    return paa_campaign_service.get_campaign(set_id=str(set_id))


@router.post("/paa-sets/{set_id}/campaign", status_code=201)
async def create_campaign(set_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Wrap a saved PAA set in a campaign (auto-adds the service keyword to the
    Maps tracker, captures the baseline rank)."""
    _require_campaigns_enabled()
    return paa_campaign_service.create_campaign(str(set_id), user_id=auth["user_id"])


@router.get("/paa-campaigns/{campaign_id}")
async def get_campaign(campaign_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    _require_campaigns_enabled()
    return paa_campaign_service.get_campaign(campaign_id=str(campaign_id))


@router.post("/paa-campaigns/{campaign_id}/start", status_code=202)
async def start_campaign(
    campaign_id: UUID,
    body: PaaCampaignStartRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> dict:
    """Confirm the start step: create the PAA posts (one blog run per PAA), enter
    the content state. Blocked (200 with gates) unless a cannibalization sign-off is
    acknowledged. Content creation stops under a freeze."""
    _require_campaigns_enabled()
    campaign = paa_campaign_service.get_campaign(campaign_id=str(campaign_id))
    if not campaign.get("exists"):
        raise HTTPException(status_code=404, detail="paa_campaign_not_found")
    assert_not_frozen(str(campaign["campaign"]["client_id"]))
    result = await paa_campaign_service.start_campaign(
        str(campaign_id), user_id=auth["user_id"], acknowledge=body.acknowledge
    )
    for run_id in result.get("run_ids", []):
        background_tasks.add_task(orchestrate_run, run_id)
    return result


@router.post("/paa-campaigns/{campaign_id}/confirm-scan", status_code=202)
async def confirm_scan(campaign_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Confirm the (paid) single-variable Maps geo-grid scan for the service
    keyword; enter the scanning state (the sweep reads the gate when it completes)."""
    _require_campaigns_enabled()
    return paa_campaign_service.confirm_scan(str(campaign_id))


@router.get("/paa-campaigns/{campaign_id}/drill-preview")
async def drill_preview(campaign_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Preview the drill round: pull sub-PAAs seeded from the current level's
    questions (read-only, does not persist)."""
    _require_campaigns_enabled()
    return await paa_campaign_service.propose_drill(str(campaign_id))


@router.post("/paa-campaigns/{campaign_id}/drill", status_code=202)
async def confirm_drill(
    campaign_id: UUID,
    body: PaaDrillConfirmRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> dict:
    """Confirm a drill round: add the selected sub-PAAs at drill_level+1 + create
    their posts, re-enter the content state. Content creation stops under a freeze."""
    _require_campaigns_enabled()
    campaign = paa_campaign_service.get_campaign(campaign_id=str(campaign_id))
    if not campaign.get("exists"):
        raise HTTPException(status_code=404, detail="paa_campaign_not_found")
    assert_not_frozen(str(campaign["campaign"]["client_id"]))
    result = await paa_campaign_service.confirm_drill(
        str(campaign_id), items=[i.model_dump() for i in body.items],
        user_id=auth["user_id"], acknowledge=body.acknowledge,
    )
    for run_id in result.get("run_ids", []):
        background_tasks.add_task(orchestrate_run, run_id)
    return result


@router.post("/paa-campaigns/{campaign_id}/reset")
async def reset_campaign(campaign_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Reset a halted campaign after an on-page/entity re-check → re-scan."""
    _require_campaigns_enabled()
    return paa_campaign_service.reset_halted(str(campaign_id))
