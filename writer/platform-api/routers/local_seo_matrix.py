"""Local SEO — service × location matrix routes
(docs/modules/local-seo-matrix-plan-v1_0.md §6).

All under /clients/{client_id}/local-seo/matrices. Every write is
`require_auth` + Freeze-Protocol gated; every job is scoped to the client.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from config import settings
from middleware.auth import require_auth
from models.local_seo_matrix import (
    MatrixCreateRequest,
    MatrixDetail,
    MatrixEstimate,
    MatrixGenerateRequest,
    MatrixGenerateResult,
    MatrixRecheckResult,
    MatrixSuggestJob,
    MatrixSuggestRequest,
    MatrixSuggestResult,
    MatrixSummary,
    MatrixUpdateRequest,
)
from services import local_seo_matrix_store as store
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["local_seo_matrix"])

_BASE = "/clients/{client_id}/local-seo/matrices"


def _enabled() -> None:
    if not settings.local_seo_matrix_enabled:
        raise HTTPException(status_code=503, detail="local_seo_matrix_not_enabled")


def _dump_axes(body) -> dict:
    """Pydantic → plain dict, with `MatrixLocationIn | str` rows kept as-is (the
    store's normalizer accepts both)."""
    data = body.model_dump(exclude_unset=True)
    if "locations" in data and data["locations"] is not None:
        data["locations"] = [
            loc if isinstance(loc, (str, dict)) else loc.model_dump() for loc in data["locations"]
        ]
    return data


@router.get(_BASE, response_model=list[MatrixSummary])
async def list_matrices(client_id: UUID, auth: dict = Depends(require_auth)) -> list[MatrixSummary]:
    _enabled()
    return [MatrixSummary(**m) for m in store.list_matrices(str(client_id))]


@router.post(_BASE, response_model=MatrixDetail)
async def create_matrix(
    client_id: UUID, body: MatrixCreateRequest, auth: dict = Depends(require_auth),
) -> MatrixDetail:
    """Create a matrix + its cells and mark coverage. Creates no content — the
    freeze gate is on generate/publish, not here."""
    _enabled()
    matrix = await store.create_matrix(str(client_id), _dump_axes(body), auth["user_id"])
    return MatrixDetail(**matrix)


@router.get(_BASE + "/{matrix_id}", response_model=MatrixDetail)
async def get_matrix(client_id: UUID, matrix_id: UUID, auth: dict = Depends(require_auth)) -> MatrixDetail:
    _enabled()
    return MatrixDetail(**store.get_matrix(str(matrix_id), str(client_id)))


@router.put(_BASE + "/{matrix_id}", response_model=MatrixDetail)
async def update_matrix(
    client_id: UUID, matrix_id: UUID, body: MatrixUpdateRequest, auth: dict = Depends(require_auth),
) -> MatrixDetail:
    _enabled()
    matrix = await store.update_matrix(str(matrix_id), str(client_id), _dump_axes(body))
    return MatrixDetail(**matrix)


@router.delete(_BASE + "/{matrix_id}")
async def delete_matrix(client_id: UUID, matrix_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Delete the matrix (cells cascade). Pages are untouched."""
    _enabled()
    return store.delete_matrix(str(matrix_id), str(client_id))


@router.post(_BASE + "/{matrix_id}/recheck", response_model=MatrixRecheckResult)
async def recheck_matrix(client_id: UUID, matrix_id: UUID, auth: dict = Depends(require_auth)) -> MatrixRecheckResult:
    """Re-run the existing-page marking (live site + in-tool pages)."""
    _enabled()
    return MatrixRecheckResult(**(await store.recheck(str(matrix_id), str(client_id))))


@router.get(_BASE + "/{matrix_id}/estimate", response_model=MatrixEstimate)
async def estimate_matrix_run(
    client_id: UUID,
    matrix_id: UUID,
    cell_ids: Optional[list[UUID]] = Query(None),
    include_covered: bool = False,
    signoff_acknowledged: bool = False,
    auth: dict = Depends(require_auth),
) -> MatrixEstimate:
    """Count / est. cost / est. time + gates for a run (default: every runnable cell)."""
    _enabled()
    return MatrixEstimate(
        **store.estimate_run(
            str(matrix_id), str(client_id),
            [str(c) for c in cell_ids] if cell_ids else None,
            include_covered, signoff_acknowledged,
        )
    )


@router.post(_BASE + "/{matrix_id}/generate", response_model=MatrixGenerateResult)
async def generate_matrix_cells(
    client_id: UUID, matrix_id: UUID, body: MatrixGenerateRequest, auth: dict = Depends(require_auth),
) -> MatrixGenerateResult:
    """Immediate run: one staggered background generate job per selected cell."""
    _enabled()
    assert_not_frozen(str(client_id))  # Freeze Protocol: content creation paused
    result = store.start_generate(
        str(matrix_id), str(client_id), auth["user_id"],
        cell_ids=[str(c) for c in body.cell_ids] if body.cell_ids else None,
        include_covered=body.include_covered,
        signoff_acknowledged=body.signoff_acknowledged,
        force_refresh=body.force_refresh,
    )
    return MatrixGenerateResult(**result)


@router.post(_BASE + "/{matrix_id}/suggest", response_model=MatrixSuggestJob)
async def suggest_axis(
    client_id: UUID, matrix_id: UUID, body: MatrixSuggestRequest, auth: dict = Depends(require_auth),
) -> MatrixSuggestJob:
    """Suggest services (silo planner) or locations (target cities + suburbs) — async."""
    _enabled()
    job_id = store.start_suggest(str(matrix_id), str(client_id), body.axis, auth["user_id"], body.seed_service)
    return MatrixSuggestJob(job_id=job_id, status="pending")


@router.get(_BASE + "/{matrix_id}/suggest/{job_id}", response_model=MatrixSuggestResult)
async def get_suggest(
    client_id: UUID, matrix_id: UUID, job_id: UUID, auth: dict = Depends(require_auth),
) -> MatrixSuggestResult:
    _enabled()
    return MatrixSuggestResult(**store.get_suggest(str(job_id), str(client_id)))
