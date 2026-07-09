"""Local SEO module (#2) router.

platform-api owns auth + persistence and proxies analysis/generation/scoring
to the private nlp service. Every route is auth-gated; the nlp service is only
reachable server-side.

The long-running actions (generate / reoptimize / score / analyze / related /
social / find-page / precheck) are enqueued as `async_jobs` and return a job
handle; the client polls `.../jobs/status` for the result. Running server-side
means the work completes — and the result is retrievable — even if the user
navigates away and comes back. GET / DELETE routes are instant plain JSON.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from middleware.auth import require_auth
from models.local_seo import (
    LocalSeoAnalyzeRequest,
    LocalSeoBulkGenerateJob,
    LocalSeoBulkGenerateRequest,
    LocalSeoFindPageRequest,
    LocalSeoGenerateJob,
    LocalSeoGenerateJobResult,
    LocalSeoGenerateRequest,
    LocalSeoJobsStatusRequest,
    LocalSeoJobStatus,
    LocalSeoReoptimizeBulkJob,
    LocalSeoReoptimizeBulkRequest,
    LocalSeoPageDetail,
    LocalSeoPageListItem,
    LocalSeoPrecheckRequest,
    LocalSeoRankabilityRequest,
    LocalSeoRankabilityResponse,
    LocalSeoRelatedPagesRequest,
    LocalSeoReoptimizeRequest,
    LocalSeoScoreRequest,
    LocalSeoSiloPlanJob,
    LocalSeoSiloPlanRequest,
    LocalSeoSiloPlanResult,
    LocalSeoSocialPostsRequest,
    LocationSuggestion,
    PageTemplateDefaultRequest,
)
from services import local_seo_service, local_seo_silo
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local_seo"])


@router.post("/clients/{client_id}/local-seo/generate-async", response_model=LocalSeoGenerateJob)
async def generate_local_seo_page_async(
    client_id: UUID,
    body: LocalSeoGenerateRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Kick off page generation as a background job (runs minutes; poll for the
    result). Lets the UI navigate away — even to other clients — while it runs."""
    assert_not_frozen(str(client_id))  # Freeze Protocol: content creation paused
    job_id = await local_seo_service.enqueue_generate(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        user_id=auth["user_id"],
        page_template_url=body.page_template_url,
        force_refresh=body.force_refresh,
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.get(
    "/clients/{client_id}/local-seo/generate/{job_id}",
    response_model=LocalSeoGenerateJobResult,
)
async def get_local_seo_generate_job(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJobResult:
    """Poll a background generation job; returns its status and (when complete) the
    new page id."""
    return LocalSeoGenerateJobResult(**local_seo_service.get_generate_job(str(job_id), str(client_id)))


@router.post("/clients/{client_id}/local-seo/generate-bulk", response_model=LocalSeoBulkGenerateJob)
async def generate_local_seo_pages_bulk(
    client_id: UUID,
    body: LocalSeoBulkGenerateRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoBulkGenerateJob:
    """Enqueue background generation for several keywords (bulk-create). The UI
    polls the returned job ids and can leave while they run."""
    assert_not_frozen(str(client_id))  # Freeze Protocol: content creation paused
    job_ids = await local_seo_service.enqueue_generate_bulk(
        client_id=str(client_id),
        keywords=body.keywords,
        location=body.location,
        location_code=body.location_code,
        user_id=auth["user_id"],
        page_template_url=body.page_template_url,
        force_refresh=body.force_refresh,
    )
    return LocalSeoBulkGenerateJob(job_ids=job_ids)


@router.post("/clients/{client_id}/local-seo/reoptimize-bulk", response_model=LocalSeoReoptimizeBulkJob)
async def reoptimize_local_seo_pages_bulk(
    client_id: UUID,
    body: LocalSeoReoptimizeBulkRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoReoptimizeBulkJob:
    """Enqueue background reoptimization for several page URLs. The UI polls the
    returned jobs (paired with their URLs) and can leave while they run."""
    assert_not_frozen(str(client_id))  # Freeze Protocol: content creation paused
    jobs = await local_seo_service.enqueue_reoptimize_bulk(
        client_id=str(client_id),
        targets=[t.model_dump() for t in body.targets],
        user_id=auth["user_id"],
        score_threshold=body.score_threshold,
        publish_to_doc=body.publish_to_doc,
    )
    return LocalSeoReoptimizeBulkJob(jobs=jobs)


@router.post("/clients/{client_id}/local-seo/jobs/status", response_model=list[LocalSeoJobStatus])
async def local_seo_jobs_status(
    client_id: UUID,
    body: LocalSeoJobsStatusRequest,
    auth: dict = Depends(require_auth),
) -> list[LocalSeoJobStatus]:
    """Batch-poll a set of background jobs (generate / reoptimize) for this client."""
    rows = local_seo_service.get_jobs_status(str(client_id), [str(j) for j in body.job_ids])
    return [LocalSeoJobStatus(**row) for row in rows]


@router.post("/clients/{client_id}/local-seo/precheck", response_model=LocalSeoGenerateJob)
async def precheck_local_seo_page(
    client_id: UUID,
    body: LocalSeoPrecheckRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Detect existing/ranking pages for a keyword before generating a new one.

    Backs the New Page flow's automatic gate: the frontend runs this first and,
    when matches come back, lets the user reoptimize an existing page (or pick one
    of several ranking pages) instead of writing a duplicate. Enqueued as a
    background job (the live-site scan + SERP lookup take tens of seconds) so the
    UI can navigate away and reconnect; poll the result via `.../jobs/status`.
    """
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "precheck",
        {"keyword": body.keyword, "location": body.location, "location_code": body.location_code},
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.put("/clients/{client_id}/local-seo/page-template-default")
async def set_local_seo_page_template_default(
    client_id: UUID,
    body: PageTemplateDefaultRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Save (or clear) the client's default page-template URL (Phase 3)."""
    return local_seo_service.set_page_template_default(str(client_id), body.page_template_url)


@router.post("/clients/{client_id}/local-seo/analyze", response_model=LocalSeoGenerateJob)
async def analyze_local_seo(
    client_id: UUID,
    body: LocalSeoAnalyzeRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Competitor SERP analysis as a background job; poll `.../jobs/status`."""
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "analyze",
        {
            "keyword": body.keyword, "location": body.location,
            "location_code": body.location_code, "force_refresh": body.force_refresh,
        },
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/find-page", response_model=LocalSeoGenerateJob)
async def find_local_seo_page(
    client_id: UUID,
    body: LocalSeoFindPageRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Website page-finder as a background job; poll `.../jobs/status`."""
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "find_page",
        {"keyword": body.keyword, "location": body.location},
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/score", response_model=LocalSeoGenerateJob)
async def score_local_seo_page(
    client_id: UUID,
    body: LocalSeoScoreRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Score a page against the 8 engines as a background job; poll `.../jobs/status`.
    Runs minutes when it has to analyze competitors first, so it's backgrounded to
    survive navigating away."""
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "score",
        {
            "keyword": body.keyword, "location": body.location,
            "location_code": body.location_code, "page_url": body.page_url,
            "page_content": body.page_content, "serp_analysis": body.serp_analysis,
            "force_refresh": body.force_refresh,
        },
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/related-pages", response_model=LocalSeoGenerateJob)
async def related_local_seo_pages(
    client_id: UUID,
    body: LocalSeoRelatedPagesRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Related-page discovery as a background job; poll `.../jobs/status`."""
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "related_pages",
        {"keyword": body.keyword, "location": body.location},
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/silo-plan", response_model=LocalSeoSiloPlanJob)
async def start_local_seo_silo_plan(
    client_id: UUID,
    body: LocalSeoSiloPlanRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoSiloPlanJob:
    """Enqueue a Fanout-powered silo plan (runs minutes; poll for the result)."""
    job_id = await local_seo_silo.start_silo_plan(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        user_id=auth["user_id"],
    )
    return LocalSeoSiloPlanJob(job_id=job_id, status="pending")


@router.get(
    "/clients/{client_id}/local-seo/silo-plan/{job_id}",
    response_model=LocalSeoSiloPlanResult,
)
async def get_local_seo_silo_plan(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> LocalSeoSiloPlanResult:
    """Poll a silo-plan job; returns its status and (when complete) page targets."""
    return LocalSeoSiloPlanResult(**local_seo_silo.get_silo_plan(str(job_id), str(client_id)))


@router.post("/clients/{client_id}/local-seo/reoptimize-async", response_model=LocalSeoGenerateJob)
async def reoptimize_local_seo_page_async(
    client_id: UUID,
    body: LocalSeoReoptimizeRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """Kick off the score→reoptimize rewrite as a background job (the new page id
    comes back via the jobs/status poll). Lets the UI navigate away while it runs;
    the reoptimized page lands in the client's pages when done."""
    job_id = await local_seo_service.enqueue_reoptimize_page(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        existing_page_html=body.existing_page_html,
        existing_page_url=body.existing_page_url,
        deficiencies=body.deficiencies,
        serp_analysis=body.serp_analysis,
        user_id=auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/social-posts", response_model=LocalSeoGenerateJob)
async def social_posts_local_seo(
    client_id: UUID,
    body: LocalSeoSocialPostsRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoGenerateJob:
    """GBP social-post generation as a background job; poll `.../jobs/status`."""
    job_id = await local_seo_service.enqueue_action(
        str(client_id), "social_posts",
        {
            "keyword": body.keyword, "location": body.location,
            "page_content": body.page_content, "serp_analysis": body.serp_analysis,
        },
        auth["user_id"],
    )
    return LocalSeoGenerateJob(job_id=job_id, status="pending")


@router.post("/clients/{client_id}/local-seo/rankability", response_model=LocalSeoRankabilityResponse)
async def check_local_seo_rankability(
    client_id: UUID,
    body: LocalSeoRankabilityRequest,
    auth: dict = Depends(require_auth),
) -> LocalSeoRankabilityResponse:
    """Map-pack rankability report — can this client rank in the Maps pack for
    this keyword? Single point-in-time, deterministic, non-streaming (no LLM)."""
    result = await local_seo_service.check_rankability(
        client_id=str(client_id),
        keyword=body.keyword,
        location=body.location,
        location_code=body.location_code,
        sab_city=body.sab_city,
        user_id=auth["user_id"],
    )
    return LocalSeoRankabilityResponse(**result)


@router.get("/clients/{client_id}/local-seo/locations", response_model=list[LocationSuggestion])
async def search_local_seo_locations(
    client_id: UUID,
    query: str = Query(..., min_length=2),
    country: str | None = Query(None, min_length=2, max_length=2),
    auth: dict = Depends(require_auth),
) -> list[LocationSuggestion]:
    """Area-field typeahead: DataForSEO location suggestions scoped to the
    client's country (overridable via `country`)."""
    rows = await local_seo_service.search_locations(str(client_id), query, country=country)
    return [LocationSuggestion(**row) for row in rows]


@router.get("/clients/{client_id}/local-seo/pages", response_model=list[LocalSeoPageListItem])
async def list_local_seo_pages(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> list[LocalSeoPageListItem]:
    """Active (non-deleted) pages — the Saved Pages tab."""
    return [LocalSeoPageListItem(**row) for row in local_seo_service.list_pages(str(client_id))]


@router.get("/clients/{client_id}/local-seo/drafts", response_model=list[LocalSeoPageListItem])
async def list_local_seo_drafts(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> list[LocalSeoPageListItem]:
    """Soft-deleted pages — the Drafts tab (restore or permanently delete)."""
    return [LocalSeoPageListItem(**row) for row in local_seo_service.list_pages(str(client_id), deleted=True)]


@router.get("/clients/{client_id}/local-seo/score-history")
async def list_local_seo_score_history(
    client_id: UUID,
    page_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_auth),
) -> list[dict]:
    """Per-run score history for a client — each row carries the full 8-engine
    `engine_scores` verdict, composite, deficiencies and token usage. Optionally
    scoped to one page via `page_id`."""
    return local_seo_service.list_score_history(
        str(client_id), page_id=str(page_id) if page_id else None, limit=limit,
    )


@router.get("/local-seo/pages/{page_id}", response_model=LocalSeoPageDetail)
async def get_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> LocalSeoPageDetail:
    return LocalSeoPageDetail(**local_seo_service.get_page(str(page_id)))


@router.delete("/local-seo/pages/{page_id}")
async def delete_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Soft-delete: move the page to Drafts (recoverable)."""
    local_seo_service.delete_page(str(page_id))
    return {"deleted": True}


@router.post("/local-seo/pages/{page_id}/restore")
async def restore_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Restore a drafted page back to Saved Pages."""
    local_seo_service.restore_page(str(page_id))
    return {"restored": True}


@router.delete("/local-seo/pages/{page_id}/permanent")
async def purge_local_seo_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Permanently delete a page (from Drafts). Irreversible."""
    local_seo_service.purge_page(str(page_id))
    return {"purged": True}


@router.delete("/clients/{client_id}/local-seo/drafts")
async def purge_local_seo_drafts(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, int]:
    """Permanently delete ALL of a client's drafts (empty the Drafts bin)."""
    return {"purged": local_seo_service.purge_drafts(str(client_id))}


class PublishPageRequest(BaseModel):
    destination: Literal["google_docs", "wordpress", "github"] = "google_docs"
    status: Literal["draft", "publish"] = "draft"


@router.post("/local-seo/pages/{page_id}/publish")
async def publish_local_seo_page(
    page_id: UUID,
    body: PublishPageRequest = PublishPageRequest(),
    auth: dict = Depends(require_auth),
) -> dict:
    """Publish a saved page to a Google Doc in the client's Drive folder, or
    directly to the client's WordPress site (destination='wordpress')."""
    return await local_seo_service.publish_page(
        str(page_id), auth["user_id"], destination=body.destination, status=body.status
    )


class FeaturedImageRequest(BaseModel):
    url: Optional[str] = None  # null/empty clears the featured image


@router.put("/local-seo/pages/{page_id}/featured-image")
async def set_local_seo_featured_image(
    page_id: UUID,
    body: FeaturedImageRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Attach (or clear) a Local SEO page's featured/hero image."""
    return local_seo_service.set_featured_image(str(page_id), body.url)
