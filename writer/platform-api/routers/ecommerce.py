"""Ecommerce Product & Collection Writer + Reoptimizer router.

platform-api owns auth + persistence and proxies generation/scoring to the
private nlp service. Every route is auth-gated; the nlp service is only reachable
server-side. Long-running actions (generate / reoptimize / score) are enqueued as
`async_jobs` and return a job handle; the client polls `.../jobs/status`. Site
discovery + GET/DELETE routes are instant plain JSON.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from middleware.auth import require_auth
from models.ecommerce import (
    EcommerceBulkGenerateJob,
    EcommerceBulkGenerateRequest,
    EcommerceDiscoverResult,
    EcommerceGenerateJob,
    EcommerceGenerateJobResult,
    EcommerceGenerateRequest,
    EcommerceJobStatus,
    EcommerceJobsStatusRequest,
    EcommercePageDetail,
    EcommercePageListItem,
    EcommercePageTemplateRequest,
    EcommerceReoptimizeBulkJob,
    EcommerceReoptimizeBulkRequest,
    EcommerceScoreRequest,
)
from services import ecommerce_service
from services.ecommerce_discovery import discover_pages
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ecommerce"])


# ── generation ───────────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/ecommerce/generate-async", response_model=EcommerceGenerateJob)
async def generate_ecommerce_page_async(
    client_id: UUID,
    body: EcommerceGenerateRequest,
    auth: dict = Depends(require_auth),
) -> EcommerceGenerateJob:
    """Kick off ecommerce page generation as a background job (runs minutes)."""
    assert_not_frozen(str(client_id))  # Freeze Protocol: content creation paused
    job_id = await ecommerce_service.enqueue_generate(
        client_id=str(client_id),
        keyword=body.keyword,
        page_type=body.page_type,
        source_url=body.source_url,
        product_input=body.product_input,
        user_id=auth["user_id"],
        page_template_url=body.page_template_url,
    )
    return EcommerceGenerateJob(job_id=job_id, status="pending")


@router.get("/clients/{client_id}/ecommerce/page-template-default")
async def get_ecommerce_page_template_default(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict:
    """Return the client's saved house PDP template URL (products mirror it)."""
    return ecommerce_service.get_page_template_default(str(client_id))


@router.put("/clients/{client_id}/ecommerce/page-template-default")
async def set_ecommerce_page_template_default(
    client_id: UUID,
    body: EcommercePageTemplateRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Set/clear the client's house PDP template — the reference product page whose
    structure every new PRODUCT description mirrors."""
    return ecommerce_service.set_page_template_default(str(client_id), body.page_template_url)


@router.get(
    "/clients/{client_id}/ecommerce/generate/{job_id}",
    response_model=EcommerceGenerateJobResult,
)
async def get_ecommerce_generate_job(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> EcommerceGenerateJobResult:
    """Poll a background generation job; returns status + (when complete) page id."""
    return EcommerceGenerateJobResult(**ecommerce_service.get_generate_job(str(job_id), str(client_id)))


@router.post("/clients/{client_id}/ecommerce/generate-bulk", response_model=EcommerceBulkGenerateJob)
async def generate_ecommerce_pages_bulk(
    client_id: UUID,
    body: EcommerceBulkGenerateRequest,
    auth: dict = Depends(require_auth),
) -> EcommerceBulkGenerateJob:
    """Enqueue one generation job per keyword (bulk-create)."""
    assert_not_frozen(str(client_id))
    job_ids = await ecommerce_service.enqueue_generate_bulk(
        str(client_id), body.keywords, body.page_type, auth["user_id"],
    )
    return EcommerceBulkGenerateJob(job_ids=job_ids)


# ── reoptimization ───────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/ecommerce/reoptimize-bulk", response_model=EcommerceReoptimizeBulkJob)
async def reoptimize_ecommerce_pages_bulk(
    client_id: UUID,
    body: EcommerceReoptimizeBulkRequest,
    auth: dict = Depends(require_auth),
) -> EcommerceReoptimizeBulkJob:
    """Enqueue one score→reoptimize job per live page URL."""
    assert_not_frozen(str(client_id))
    jobs = await ecommerce_service.enqueue_reoptimize_bulk(
        str(client_id),
        [t.model_dump() for t in body.targets],
        auth["user_id"],
        score_threshold=body.score_threshold,
        publish_to_doc=body.publish_to_doc,
    )
    return EcommerceReoptimizeBulkJob(jobs=jobs)


@router.get("/clients/{client_id}/ecommerce/discover", response_model=EcommerceDiscoverResult)
async def discover_ecommerce_pages(
    client_id: UUID,
    page_type: Optional[Literal["product", "collection"]] = Query(None),
    auth: dict = Depends(require_auth),
) -> EcommerceDiscoverResult:
    """Discover the client's live product/collection URLs from its sitemap (or the
    DataForSEO `site:` index fallback) for the Reoptimizer's bulk flow."""
    return EcommerceDiscoverResult(**await discover_pages(str(client_id), page_type))


# ── scoring (backgrounded action) ────────────────────────────────────────────

@router.post("/clients/{client_id}/ecommerce/score", response_model=EcommerceGenerateJob)
async def score_ecommerce_page(
    client_id: UUID,
    body: EcommerceScoreRequest,
    auth: dict = Depends(require_auth),
) -> EcommerceGenerateJob:
    """Score a page against the 8 ecommerce engines as a background job."""
    job_id = await ecommerce_service.enqueue_action(
        str(client_id), "score",
        {
            "keyword": body.keyword, "page_type": body.page_type,
            "page_url": body.page_url, "page_content": body.page_content,
        },
        auth["user_id"],
    )
    return EcommerceGenerateJob(job_id=job_id, status="pending")


# ── job polling ──────────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/ecommerce/jobs/status", response_model=list[EcommerceJobStatus])
async def ecommerce_jobs_status(
    client_id: UUID,
    body: EcommerceJobsStatusRequest,
    auth: dict = Depends(require_auth),
) -> list[EcommerceJobStatus]:
    """Batch-poll a set of background jobs for this client."""
    rows = ecommerce_service.get_jobs_status(str(client_id), [str(j) for j in body.job_ids])
    return [EcommerceJobStatus(**row) for row in rows]


# ── CRUD / lifecycle ─────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/ecommerce/pages", response_model=list[EcommercePageListItem])
async def list_ecommerce_pages(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> list[EcommercePageListItem]:
    """Active (non-deleted) pages — the Saved Pages tab."""
    return [EcommercePageListItem(**row) for row in ecommerce_service.list_pages(str(client_id))]


@router.get("/clients/{client_id}/ecommerce/drafts", response_model=list[EcommercePageListItem])
async def list_ecommerce_drafts(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> list[EcommercePageListItem]:
    """Soft-deleted pages — the Drafts tab."""
    return [EcommercePageListItem(**row) for row in ecommerce_service.list_pages(str(client_id), deleted=True)]


@router.get("/clients/{client_id}/ecommerce/score-history")
async def list_ecommerce_score_history(
    client_id: UUID,
    page_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    auth: dict = Depends(require_auth),
) -> list[dict]:
    """Per-run score history — each row carries the full 8-engine verdict."""
    return ecommerce_service.list_score_history(
        str(client_id), page_id=str(page_id) if page_id else None, limit=limit,
    )


@router.get("/ecommerce/pages/{page_id}", response_model=EcommercePageDetail)
async def get_ecommerce_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> EcommercePageDetail:
    return EcommercePageDetail(**ecommerce_service.get_page(str(page_id)))


@router.delete("/ecommerce/pages/{page_id}")
async def delete_ecommerce_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Soft-delete: move the page to Drafts (recoverable)."""
    ecommerce_service.delete_page(str(page_id))
    return {"deleted": True}


@router.post("/ecommerce/pages/{page_id}/restore")
async def restore_ecommerce_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Restore a drafted page back to Saved Pages."""
    ecommerce_service.restore_page(str(page_id))
    return {"restored": True}


@router.delete("/ecommerce/pages/{page_id}/permanent")
async def purge_ecommerce_page(
    page_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, bool]:
    """Permanently delete a page (from Drafts). Irreversible."""
    ecommerce_service.purge_page(str(page_id))
    return {"purged": True}


@router.delete("/clients/{client_id}/ecommerce/drafts")
async def purge_ecommerce_drafts(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict[str, int]:
    """Permanently delete ALL of a client's drafts (empty the Drafts bin)."""
    return {"purged": ecommerce_service.purge_drafts(str(client_id))}


class PublishPageRequest(BaseModel):
    destination: Literal["google_docs", "wordpress"] = "google_docs"
    status: Literal["draft", "publish"] = "draft"


@router.post("/ecommerce/pages/{page_id}/publish")
async def publish_ecommerce_page(
    page_id: UUID,
    body: PublishPageRequest = PublishPageRequest(),
    auth: dict = Depends(require_auth),
) -> dict:
    """Publish a saved page to a Google Doc in the client's Drive folder, or
    directly to the client's WordPress site (destination='wordpress')."""
    return await ecommerce_service.publish_page(
        str(page_id), auth["user_id"], destination=body.destination, status=body.status
    )


class FeaturedImageRequest(BaseModel):
    url: Optional[str] = None  # null/empty clears the featured image


@router.put("/ecommerce/pages/{page_id}/featured-image")
async def set_ecommerce_featured_image(
    page_id: UUID,
    body: FeaturedImageRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Attach (or clear) an ecommerce page's featured/hero image."""
    return ecommerce_service.set_featured_image(str(page_id), body.url)
