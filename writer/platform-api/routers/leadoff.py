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
from services import leadoff_actions
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
    sort: str = "v3",
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


@router.get("/leadoff/proximity")
async def get_proximity(
    city_id: int,
    category_id: str,
    auth: dict = Depends(require_auth),
) -> dict:
    """The Distance-pillar octant read for one market (proximity plan §2/§3):
    octant coverage bars, underserved octants, suggested GBP placement pins.
    Loaded lazily by the brief panel; degrades to {available: false} instead
    of 404 so a pin-less market renders an explanation, not an error."""
    from services.leadoff_proximity import market_proximity

    try:
        return await market_proximity(city_id, category_id)
    except Exception:
        logger.warning("leadoff.proximity_failed", exc_info=True)
        return {"available": False, "reason": "proximity_error"}


@router.post("/leadoff/signals/refresh", status_code=202)
async def refresh_signals(auth: dict = Depends(require_staff)) -> dict:
    """Seed / refresh the board's market-signal cache (proximity + footprint
    precompute) on demand. $0 — pure math on already-captured data. Idempotent;
    a no-op if a refresh is already queued."""
    from services.leadoff_signals import enqueue_due_signal_refresh
    import uuid
    # force an enqueue (the scheduler helper is staleness-gated; here the user
    # asked explicitly) unless one is already active
    active = (get_supabase().table("async_jobs").select("id", count="exact")
              .eq("job_type", "leadoff_signal_refresh")
              .in_("status", ["pending", "running"]).limit(1).execute().count or 0)
    if active:
        return {"enqueued": False, "reason": "already_running"}
    get_supabase().table("async_jobs").insert({
        "job_type": "leadoff_signal_refresh", "entity_id": str(uuid.uuid4()),
        "payload": {}, "max_attempts": 3}).execute()
    return {"enqueued": True}


@router.get("/leadoff/find-cities")
async def find_cities(
    category: str,
    state: str | None = None,
    sort: str = "v3",
    limit: int = Query(default=15, ge=1, le=100),
    auth: dict = Depends(require_auth),
) -> dict:
    """"Which cities for category X?" — the free board-lookup path. Resolves the
    text to a scanned category and returns ranked cities; if the category isn't
    in the scan, returns scanned=false + a paid-finder cost estimate."""
    from services import leadoff_finder as finder

    cats = finder.board_categories()
    matched = finder.resolve_category(category, cats)
    if not matched:
        # not scanned — offer the paid finder
        candidates = finder.shortlist_cities(
            state=state, region=None, min_pop=30000,
            limit=finder.DEFAULT_SHORTLIST)
        return {"scanned": False, "query": category,
                "finder_estimate": {
                    "cities": len(candidates),
                    "est_cost": finder.estimate_finder_cost(len(candidates))},
                "note": ("Not in the scan yet. A paid city-finder scores a "
                         "population-ranked shortlist for this new category.")}
    return {"scanned": True, "matched_category": matched,
            **finder.find_board_cities(matched, state=state, sort=sort, limit=limit)}


class CityFinderRequest(BaseModel):
    category: str = Field(..., min_length=2, max_length=120)
    state: str | None = None
    region: str | None = None
    min_pop: int = Field(default=30000, ge=10000)
    limit: int = Field(default=120, ge=10, le=300)
    lead_value: float | None = None


@router.get("/leadoff/city-finder/estimate")
async def city_finder_estimate(
    state: str | None = None,
    region: str | None = None,
    min_pop: int = Query(default=30000, ge=10000),
    limit: int = Query(default=120, ge=10, le=300),
    auth: dict = Depends(require_auth),
) -> dict:
    from services import leadoff_finder as finder
    cities = finder.shortlist_cities(state=state, region=region,
                                     min_pop=min_pop, limit=limit)
    return {"cities": len(cities),
            "est_cost": finder.estimate_finder_cost(len(cities))}


@router.post("/leadoff/city-finder", status_code=202)
async def start_city_finder(
    body: CityFinderRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    """Paid finder for a new category: score a population-ranked city shortlist.
    Poll GET /leadoff/city-finder/{run_id}."""
    from services import leadoff_actions
    from services import leadoff_finder as finder

    cities = finder.shortlist_cities(state=body.state, region=body.region,
                                     min_pop=body.min_pop, limit=body.limit)
    if not cities:
        raise HTTPException(status_code=422, detail="no_candidate_cities")
    est = finder.estimate_finder_cost(len(cities))
    try:
        leadoff_actions.check_budget(auth["user_id"], est)
    except leadoff_actions.BudgetExceeded as exc:
        raise HTTPException(status_code=422, detail="budget_exceeded") from exc
    out = finder.enqueue_city_finder(
        auth["user_id"], category=body.category, state=body.state,
        region=body.region, min_pop=body.min_pop, limit=body.limit,
        lead_value=body.lead_value, est_cost=est)
    leadoff_actions.record_spend(auth["user_id"], "city_finder", est,
                                 category=body.category, state=body.state)
    return {**out, "cities": len(cities)}


@router.get("/leadoff/city-finder/{run_id}")
async def get_city_finder(run_id: str, auth: dict = Depends(require_auth)) -> dict:
    rows = (get_supabase().table("leadoff_city_finder_runs").select("*")
            .eq("id", run_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return rows[0]


@router.get("/leadoff/neighborhoods")
async def get_neighborhoods(
    metro: str | None = None,
    state: str | None = None,
    service: str | None = None,
    sort: str = "demand",
    limit: int = Query(default=100, ge=1, le=955),
    auth: dict = Depends(require_auth),
) -> dict:
    if sort not in leadoff_service.NEIGHBORHOOD_SORTS:
        raise HTTPException(status_code=422, detail="invalid_sort")
    return leadoff_service.list_neighborhoods(
        metro=metro, state=state, service=service, sort=sort, limit=limit)


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

    # Distance-pillar read for the handoff (placement recommendation) +
    # calibration (proximity_opportunity the geo-grid later verifies).
    from services.leadoff_proximity import market_proximity
    try:
        proximity = await market_proximity(body.city_id, body.category_id)
    except Exception:
        proximity = None

    goal_created = False
    try:
        campaign_goals.create_goal(
            client_id,
            leadoff_service.handoff_goal(brief, brief.get("enrichment"), proximity),
            created_by=auth["user_id"],
        )
        goal_created = True
    except Exception as exc:
        logger.warning("leadoff_goal_seed_failed", extra={
            "client_id": client_id, "error": str(exc)})

    # Calibration Phase 0: freeze the full prediction vector (lossless,
    # immutable — the machine copy of the prose goal above). Best-effort.
    from services import leadoff_calibration
    prediction_id = leadoff_calibration.capture_prediction(
        client_id, brief, DEFAULT_CAPTURE, DEFAULT_TIER, auth.get("user_id"),
        proximity=proximity)

    logger.info("leadoff_client_created", extra={
        "client_id": client_id, "city_id": body.city_id,
        "category_id": body.category_id,
        "competitors_seeded": competitors_seeded, "goal_created": goal_created})
    return {
        "client_id": client_id,
        "competitors_seeded": competitors_seeded,
        "goal_created": goal_created,
        "prediction_id": prediction_id,
    }


# ── Paid actions (PRD §5 item 1) — budget-guarded, cost surfaced up front ─────

class TryoutRequest(BaseModel):
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2)
    capture: float = Field(default=DEFAULT_CAPTURE, ge=0.01, le=0.5)
    lead_tier: str = DEFAULT_TIER


@router.post("/leadoff/tryout", status_code=202)
async def start_tryout(
    body: TryoutRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    """Score ANY off-list city (~$0.20, ~3 min) — the check_city port. Runs as
    an async job; poll GET /leadoff/tryouts/{id}."""
    if body.lead_tier not in LEAD_TIERS:
        raise HTTPException(status_code=422, detail="invalid_lead_tier")
    city_row = leadoff_actions.resolve_city(body.city, body.state)
    if city_row is None:
        # cities covers US places >=10k pop; smaller towns need a geocode step
        raise HTTPException(status_code=404, detail="city_not_found")
    try:
        leadoff_actions.check_budget(auth["user_id"], leadoff_actions.COST_TRYOUT)
    except leadoff_actions.BudgetExceeded as exc:
        raise HTTPException(status_code=422, detail="budget_exceeded") from exc
    out = leadoff_actions.enqueue_tryout(
        auth["user_id"], city_row, body.capture, body.lead_tier)
    leadoff_actions.record_spend(
        auth["user_id"], "tryout", leadoff_actions.COST_TRYOUT,
        city_id=city_row.get("city_id"), city_name=city_row.get("name"),
        state_code=city_row.get("state_code"))
    return {"tryout_id": out["tryout"]["id"], "job_id": out["job_id"],
            "city_name": city_row.get("name"), "state_code": city_row.get("state_code"),
            "est_cost": leadoff_actions.COST_TRYOUT}


@router.get("/leadoff/tryouts")
async def list_tryouts(
    limit: int = Query(default=20, ge=1, le=100),
    auth: dict = Depends(require_auth),
) -> dict:
    rows = (get_supabase().table("leadoff_tryouts").select("*")
            .order("created_at", desc=True).limit(limit).execute().data or [])
    return {"tryouts": rows}


@router.get("/leadoff/tryouts/{tryout_id}")
async def get_tryout(tryout_id: str, auth: dict = Depends(require_auth)) -> dict:
    rows = (get_supabase().table("leadoff_tryouts").select("*")
            .eq("id", tryout_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return rows[0]


class ScoutRequest(BaseModel):
    city_id: int
    category_id: str


@router.get("/leadoff/scout/estimate")
async def scout_estimate(
    city_id: int,
    category_id: str,
    auth: dict = Depends(require_auth),
) -> dict:
    """Free preflight: what a scout of this market would pull vs what's
    already cache-fresh, and the dollar estimate."""
    state = leadoff_actions.scout_market_state(city_id, category_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "est_cost": state["est_cost"],
        "rd_misses": len(state["rd_misses"]),
        "velocity_misses": len(state["vel_misses"]),
        "trend_miss": state["trend_miss"],
        "site_misses": len(state.get("site_misses") or []),
        "mention_misses": len(state.get("mention_misses") or {}),
        "fully_cached": state["est_cost"] == 0,
    }


@router.post("/leadoff/scout", status_code=202)
async def start_scout(
    body: ScoutRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    """Pass-2 scouting report for one market (RD + review velocity + demand
    trend, cache-cheapened) — the enrich_shortlist port. Writes the shared
    market_scanner caches; the market brief picks the enrichment up on its
    next read. Poll GET /leadoff/jobs/{job_id}."""
    state = leadoff_actions.scout_market_state(body.city_id, body.category_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not_found")
    if state["est_cost"] == 0 and not state["rd_misses"] \
            and not state["vel_misses"] and not state["trend_miss"]:
        return {"job_id": None, "est_cost": 0.0, "fully_cached": True}
    try:
        leadoff_actions.check_budget(auth["user_id"], state["est_cost"])
    except leadoff_actions.BudgetExceeded as exc:
        raise HTTPException(status_code=422, detail="budget_exceeded") from exc
    out = leadoff_actions.enqueue_scout(
        auth["user_id"], body.city_id, body.category_id, state["est_cost"])
    leadoff_actions.record_spend(
        auth["user_id"], "scout", state["est_cost"],
        city_id=body.city_id, category_id=body.category_id,
        city_name=state["market"].get("city_name"),
        state_code=state["market"].get("state_code"))
    return {"job_id": out["job_id"], "est_cost": state["est_cost"],
            "fully_cached": False}


@router.get("/leadoff/jobs/{job_id}")
async def get_leadoff_job(job_id: str, auth: dict = Depends(require_auth)) -> dict:
    rows = (get_supabase().table("async_jobs")
            .select("id,job_type,status,error,result,created_at,completed_at")
            .eq("id", job_id).in_("job_type", ["leadoff_tryout", "leadoff_scout"])
            .limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return rows[0]


# ── Calibration surface (Phase 0 — read-only; leadoff-calibration-plan) ───────

@router.get("/leadoff/calibration")
async def get_calibration(auth: dict = Depends(require_auth)) -> dict:
    """The read-only prediction↔outcome error report. Nothing here feeds back
    into scoring (Phase 1 is gated on per-metric N≥15, ≥6-month tenure)."""
    from services import leadoff_calibration
    try:
        return leadoff_calibration.calibration_report()
    except Exception as exc:
        logger.error("leadoff_calibration_report_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/leadoff-prediction")
async def get_client_prediction(client_id: str, auth: dict = Depends(require_auth)) -> dict:
    """The client's frozen LeadOff prediction (drives the Campaign Goals
    page's manual-leads entry card). 404 when the client wasn't created
    through the market handoff."""
    rows = (get_supabase().table("leadoff_predictions").select("*")
            .eq("client_id", client_id).order("created_at", desc=True)
            .limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return rows[0]


class ManualLeadsRequest(BaseModel):
    actual_leads_mo: float = Field(..., ge=0)


@router.post("/leadoff/predictions/{prediction_id}/leads")
async def post_manual_leads(
    prediction_id: str,
    body: ManualLeadsRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    """Operator-entered monthly lead count — the plan §3.3 manual path
    (surfaced on the Campaign Goals page per the owner ruling)."""
    from services import leadoff_calibration
    try:
        return leadoff_calibration.record_manual_leads(
            prediction_id, body.actual_leads_mo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="not_found") from exc
    except Exception as exc:
        logger.error("leadoff_manual_leads_failed", extra={
            "prediction_id": prediction_id, "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
