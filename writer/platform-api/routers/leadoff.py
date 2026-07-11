"""LeadOff — market intelligence (suite-level, pre-client market selection).

Read-only v1: the precomputed board + per-market briefs. Paid actions
(tryout an off-list city, scouting-report enrichment) are deliberately not
exposed yet — see docs/modules/leadoff-prd-v1_0.md §Build order.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_auth
from services import leadoff as leadoff_service
from services.leadoff import BOARD_SORTS, DEFAULT_CAPTURE, DEFAULT_TIER, LEAD_TIERS
from config import settings

router = APIRouter(tags=["leadoff"])


@router.get("/leadoff/board")
async def get_board(
    city: str | None = None,
    state: str | None = None,
    category: str | None = None,
    min_demand: int | None = Query(default=None, ge=0),
    sort: str = "build",
    capture: float = Query(default=DEFAULT_CAPTURE, ge=0.01, le=0.5),
    lead_tier: str = DEFAULT_TIER,
    limit: int = Query(default=50, ge=1, le=500),
    auth: dict = Depends(require_auth),
) -> dict:
    if sort not in BOARD_SORTS:
        raise HTTPException(status_code=422, detail="invalid_sort")
    if lead_tier not in LEAD_TIERS:
        raise HTTPException(status_code=422, detail="invalid_lead_tier")
    return leadoff_service.list_board(
        city=city, state=state, category=category, min_demand=min_demand,
        sort=sort, capture=capture, lead_tier=lead_tier, limit=limit,
        prefetch=settings.leadoff_prefetch_rows,
    )


@router.get("/leadoff/market-brief")
async def get_market_brief(
    city_id: int,
    category_id: str,
    auth: dict = Depends(require_auth),
) -> dict:
    brief = leadoff_service.get_market_brief(city_id, category_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="not_found")
    return brief
