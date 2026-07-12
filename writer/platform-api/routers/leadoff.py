"""LeadOff — market intelligence (suite-level, pre-client market selection).

The precomputed board + per-market briefs, plus the Create-Client-from-market
handoff (PRD §5 item 2). Paid actions (tryout an off-list city, scouting-report
enrichment) are deliberately not exposed yet — see docs/modules/leadoff-prd-v1_0.md
§Build order.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from services import campaign_goals
from services import leadoff as leadoff_service
from services.leadoff import BOARD_SORTS, DEFAULT_CAPTURE, DEFAULT_TIER, LEAD_TIERS
from config import settings

router = APIRouter(tags=["leadoff"])
logger = logging.getLogger(__name__)


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


class CreateClientFromMarketRequest(BaseModel):
    city_id: int
    category_id: str
    name: str = Field(..., min_length=1, max_length=200)
    # LeadOff is a research tool first — a market pick may predate any site.
    website_url: str = ""


@router.post("/leadoff/create-client", status_code=201)
async def create_client_from_market(
    body: CreateClientFromMarketRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    """The handoff (PRD §5 item 2): create a client card pre-loaded with the
    chosen market's intel — location from the market's city, the top-5 seeded
    into the competitor registry, and the effort targets (reviews to beat #3,
    RD link budget) recorded as a custom campaign goal. Creation goes through
    the normal clients path so the usual auto-scans/dup checks apply; the
    seeding steps are best-effort and never fail a created client."""
    brief = leadoff_service.get_market_brief(body.city_id, body.category_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="not_found")

    from models.clients import ClientCreateRequest
    from routers.clients import create_client

    client = await create_client(
        ClientCreateRequest(
            name=body.name.strip(),
            website_url=body.website_url.strip(),
            brand_guide_source_type="text",
            icp_source_type="text",
            business_location=f"{brief['city_name']}, {brief['state_code']}",
            client_type="local",
        ),
        auth,
    )  # raises 409 client_name_taken / 500 like the Clients page

    client_id = str(client.id)
    supabase = get_supabase()
    competitors_seeded = 0
    for comp in leadoff_service.handoff_competitors(brief.get("competitors") or []):
        try:
            supabase.table("client_competitors").insert(
                {**comp, "client_id": client_id}
            ).execute()
            competitors_seeded += 1
        except Exception as exc:
            logger.warning("leadoff_competitor_seed_failed", extra={
                "client_id": client_id, "competitor": comp.get("name"),
                "error": str(exc)})

    goal_created = False
    try:
        campaign_goals.create_goal(
            client_id,
            leadoff_service.handoff_goal(brief, brief.get("enrichment")),
            created_by=auth["user_id"],
        )
        goal_created = True
    except Exception as exc:
        logger.warning("leadoff_goal_seed_failed", extra={
            "client_id": client_id, "error": str(exc)})

    logger.info("leadoff_client_created", extra={
        "client_id": client_id, "city_id": body.city_id,
        "category_id": body.category_id,
        "competitors_seeded": competitors_seeded, "goal_created": goal_created})
    return {
        "client_id": client_id,
        "competitors_seeded": competitors_seeded,
        "goal_created": goal_created,
    }
