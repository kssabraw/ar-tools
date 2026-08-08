"""Outreach pipeline — the suite's surface over the Outreacher project.

The outreach pipeline is an AR Tools module, not a standalone tool (outreach/HANDOFF.md §2). Its
database lives in its own Supabase project because the storage projection would eat this one's
headroom; its API lives here, so staff authenticate against the suite once and never need an
Outreacher account. Retool is dropped.

Thin by design: auth and shape here, everything else in `services/outreach`.

**Nothing in this router can spend money.** Ingestion and scanning are the Railway job's, driven
by `OUTREACH_COMMAND`, and every paid path stays there deliberately — a route that fires a paid
Outscraper pull is one accidental click from a duplicate market ingest, which has already happened
once (ISSUES I-035 correction). Read the pipeline here; run it there.

The one qualification (outreach DECISIONS.md 2026-08-06): the scan-order routes AUTHORIZE spend
without performing it. `POST /outreach/scan-requests` writes a signed order the outreach job's
`tick` command executes on its own schedule — the row is the confirmation, this process never
touches a provider, and the paid path stays exactly where it was. Admin-gated, because the click
is the authorization.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import settings
from middleware.auth import require_admin, require_auth, require_staff
from services import outreach as outreach_service
from services.outreach import OutreachError
from services.outreach_db import outreach_configured

router = APIRouter(tags=["outreach"])
logger = logging.getLogger(__name__)


async def require_outreach(auth: dict = Depends(require_auth)) -> dict:
    """Gate every route on the module being both enabled and credentialed.

    Two conditions, one 503 each, because they fail for different reasons and a reader needs to
    know which: the flag is a deployment choice, the credentials are a provisioning gap.
    """
    if not settings.outreach_enabled:
        raise HTTPException(status_code=503, detail="outreach_not_enabled")
    if not outreach_configured():
        raise HTTPException(status_code=503, detail="outreach_not_configured")
    return auth


def _handle(fn, *args, **kwargs):
    """Run a service call, mapping its error vocabulary onto HTTP.

    `*_not_found` becomes 404 and everything else 422 — the service raises named codes precisely
    so this mapping is one rule rather than a per-route try/except that drifts.
    """
    try:
        return fn(*args, **kwargs)
    except OutreachError as e:
        status = 404 if e.code.endswith("_not_found") else 422
        raise HTTPException(status_code=status, detail=e.code) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error("outreach_call_failed", extra={"error": str(e), "fn": getattr(fn, "__name__", "?")})
        raise HTTPException(status_code=500, detail="internal_error") from e


# --- Status ------------------------------------------------------------------------------------


@router.get("/outreach/status")
async def outreach_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the module is reachable, so the SPA can hide the nav entry rather than 503 into it.

    Deliberately outside `require_outreach` — a gate that 503s cannot answer "are you enabled?".
    """
    return {
        "enabled": bool(settings.outreach_enabled),
        "configured": outreach_configured(),
    }


# --- Pipeline (read-only) ----------------------------------------------------------------------


@router.get("/outreach/markets")
async def list_markets(auth: dict = Depends(require_outreach)) -> dict:
    return {"markets": _handle(outreach_service.list_markets)}


@router.get("/outreach/markets/{market_id}/summary")
async def market_summary(market_id: str, auth: dict = Depends(require_outreach)) -> dict:
    """The funnel for one market: ingested, evaluated, survived, excluded, flagged, per-rule, spend.

    Per-rule counts report `not_evaluated` separately from `passed`. `review_recency` is deferred
    to Phase 5 and writes `passed = true, observed_value = 'not_evaluated'` for every prospect
    (ISSUES I-016), so a UI that adds the two together would tell an operator that every business
    in the market has a recent review when not one has been checked.
    """
    return _handle(outreach_service.market_summary, market_id)


@router.get("/outreach/markets/{market_id}/submarkets")
async def list_submarkets(market_id: str, auth: dict = Depends(require_outreach)) -> dict:
    return {"submarkets": _handle(outreach_service.list_submarkets, market_id)}


@router.get("/outreach/prospects")
async def list_prospects(
    market_id: Optional[str] = None,
    submarket_id: Optional[str] = None,
    status: str = "all",
    search: Optional[str] = None,
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    """A page of prospects with their filter verdict.

    `status` is one of all / survived / excluded / flagged / unevaluated. Note `survived` means
    evaluated AND not excluded, so a prospect the filter never reached is never counted as one.
    """
    return _handle(
        outreach_service.list_prospects,
        market_id=market_id,
        submarket_id=submarket_id,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/outreach/prospects/{prospect_id}")
async def get_prospect(prospect_id: str, auth: dict = Depends(require_outreach)) -> dict:
    """One prospect, with every rule evaluated against it — passing rules included."""
    return _handle(outreach_service.get_prospect, prospect_id)


# --- Lead CRM ----------------------------------------------------------------------------------


class LeadCreateRequest(BaseModel):
    source: str
    prospect_id: Optional[str] = None
    stage: Optional[str] = None
    owner_id: Optional[str] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    notes_intake: Optional[str] = None
    next_action: Optional[str] = None
    next_action_due: Optional[str] = None


class LeadUpdateRequest(BaseModel):
    """Partial update. Serialized with `exclude_unset` so an omitted field is left alone and an
    explicit null clears it — without that distinction, unassigning an owner is impossible."""

    stage: Optional[str] = None
    owner_id: Optional[str] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    notes_intake: Optional[str] = None
    lost_reason: Optional[str] = None
    lost_to: Optional[str] = None
    next_action: Optional[str] = None
    next_action_due: Optional[str] = None


class ActivityCreateRequest(BaseModel):
    kind: str = "note"
    body: str
    touch_id: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SuppressionCreateRequest(BaseModel):
    scope: str
    value: str
    reason: Optional[str] = None


@router.get("/outreach/lead-stages")
async def list_lead_stages(auth: dict = Depends(require_outreach)) -> dict:
    """Board columns, in order. Also carries `is_terminal`, which is why this is a lookup table
    rather than an enum."""
    return {"stages": _handle(outreach_service.list_lead_stages)}


@router.get("/outreach/leads")
async def list_leads(
    stage: Optional[str] = None,
    source: Optional[str] = None,
    owner_id: Optional[str] = None,
    overdue: bool = False,
    search: Optional[str] = None,
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    """A page of live leads. `overdue=true` is crm-layer-spec §10's forcing function — a due date
    in the past on a lead that is neither won nor lost."""
    return _handle(
        outreach_service.list_leads,
        stage=stage,
        source=source,
        owner_id=owner_id,
        overdue=overdue,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/outreach/leads/{lead_id}")
async def get_lead(lead_id: str, auth: dict = Depends(require_outreach)) -> dict:
    return _handle(outreach_service.get_lead, lead_id)


@router.post("/outreach/leads")
async def create_lead(
    payload: LeadCreateRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Create a lead.

    Staff-gated, matching the rest of the estate's pre-client surfaces (LeadOff's create-client
    handoff sits behind the same bar): a lead is a commitment to contact a real business.
    """
    _require_outreach_ready()
    return _handle(
        outreach_service.create_lead,
        payload.model_dump(exclude_unset=True),
        auth["user_id"],
    )


@router.patch("/outreach/leads/{lead_id}")
async def update_lead(
    lead_id: str, payload: LeadUpdateRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Patch a lead.

    The stage-change and reassignment rows in the activity timeline are written by the database's
    `lead_log_changes` trigger, attributed to this caller through `updated_by`. Nothing here
    writes them, so one event can never produce two rows in an append-only table.
    """
    _require_outreach_ready()
    return _handle(
        outreach_service.update_lead,
        lead_id,
        payload.model_dump(exclude_unset=True),
        auth["user_id"],
    )


@router.post("/outreach/leads/{lead_id}/activities")
async def add_activity(
    lead_id: str, payload: ActivityCreateRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Append to a lead's timeline. Append-only: corrections are new rows, never edits, so there
    is deliberately no update or delete counterpart."""
    _require_outreach_ready()
    return _handle(
        outreach_service.add_activity,
        lead_id,
        kind=payload.kind,
        body=payload.body,
        actor_id=auth["user_id"],
        touch_id=payload.touch_id,
        metadata=payload.metadata,
    )


@router.post("/outreach/prospects/{prospect_id}/promote")
async def promote_prospect(
    prospect_id: str, auth: dict = Depends(require_staff)
) -> dict:
    """Send a scanned prospect to the CRM board — a lead prefilled from the prospect row.

    Owner ruling 2026-08-06: a hand-picked lead IS `outbound_scan` (outreach DECISIONS.md).
    Idempotent: a second click, or Phase 3's future emit for the same prospect, gets the existing
    lead back with `already_existed: true` rather than an error. Staff-gated like create_lead —
    picking a target spends nothing; it is a commitment to contact a real business.
    """
    _require_outreach_ready()
    return {"lead": _handle(outreach_service.promote_prospect, prospect_id, auth["user_id"])}


@router.get("/outreach/suppressions")
async def list_suppressions(
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    return _handle(outreach_service.list_suppressions, limit, offset)


@router.post("/outreach/suppressions")
async def add_suppression(
    payload: SuppressionCreateRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Record a do-not-contact.

    There is no DELETE route and there must not be one — crm-layer-spec §4: a suppression must not
    be deleted, ever. Re-adding an existing value is a successful no-op, so a caller never has to
    check first.
    """
    _require_outreach_ready()
    return _handle(
        outreach_service.add_suppression,
        scope=payload.scope,
        value=payload.value,
        reason=payload.reason,
        actor_id=auth["user_id"],
    )


# --- Scan orders (the UI trigger — outreach DECISIONS.md 2026-08-06) ---------------------------


class ScanRequestCreate(BaseModel):
    submarket_id: str
    keyword_id: str
    note: Optional[str] = None


class OnboardCity(BaseModel):
    name: str
    region: Optional[str] = None
    lat: float
    lng: float


class OnboardSubarea(BaseModel):
    name: str
    lat: float
    lng: float
    place_id: Optional[str] = None


class OnboardRequestCreate(BaseModel):
    """The "City + Business type" order. `city` + `subarea` come straight from
    `GET /outreach/geo/subareas`; `business_type` is the typed category (== the scan keyword)."""

    city: OnboardCity
    subarea: OnboardSubarea
    business_type: str
    note: Optional[str] = None


@router.get("/outreach/markets/{market_id}/keywords")
async def list_keywords(market_id: str, auth: dict = Depends(require_outreach)) -> dict:
    return {"keywords": _handle(outreach_service.list_keywords, market_id)}


# --- Any-city geo (read-only: resolve a typed city + list its verified sub-areas) --------------
#
# These power the "City + Business type" scan form (owner request 2026-08-08). They only READ —
# Google geocoding + Overpass — so they never touch the ~$0.81 scan spend the scan-order routes
# guard; a wrong enumeration shows a wrong list, never a bill. Staff-gated (not open to every
# authed user) because geocoding a metro's sub-areas is a small metered cost, and staff is the bar
# the rest of the module's cost-bearing surface already uses.


@router.get("/outreach/geo/resolve-city")
async def resolve_city(
    q: str = Query(..., min_length=1), auth: dict = Depends(require_staff)
) -> dict:
    """Resolve a typed city string to a Google place (name, region, centre, place_id)."""
    _require_outreach_ready()
    from db.supabase_client import get_supabase
    from services import outreach_geo

    try:
        return {"city": await outreach_geo.resolve_city(q, supabase=get_supabase())}
    except OutreachError as e:
        status = 404 if e.code.endswith("_not_found") else 422
        raise HTTPException(status_code=status, detail=e.code) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("outreach_resolve_city_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="internal_error") from e


@router.get("/outreach/geo/subareas")
async def list_subareas(
    q: str = Query(..., min_length=1), auth: dict = Depends(require_staff)
) -> dict:
    """A typed city's Google-verified sub-areas, as scan targets. Returns
    ``{city, subareas: [{name, lat, lng, place_id}], note}``; a degraded source yields an empty
    list with a note, never a 500. An unresolvable city is a 404 so the form can say so."""
    _require_outreach_ready()
    from db.supabase_client import get_supabase
    from services import outreach_geo

    try:
        return await outreach_geo.enumerate_subareas(q, supabase=get_supabase())
    except OutreachError as e:
        status = 404 if e.code.endswith("_not_found") else 422
        raise HTTPException(status_code=status, detail=e.code) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("outreach_list_subareas_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="internal_error") from e


@router.post("/outreach/scan-requests")
async def create_scan_request(
    payload: ScanRequestCreate, auth: dict = Depends(require_admin)
) -> dict:
    """Place a signed scan order — the UI-path spend authorization.

    ADMIN-gated, above the staff bar the CRM writes use: this row causes the outreach job to
    post ~81 paid tasks (one per grid point) on its next tick. The click IS the confirmation,
    so the role that can click is the role trusted with spend. Nothing is contacted here; the
    money moves in the outreach service's `tick`, which refuses everything but the oldest
    pending order per heartbeat.
    """
    _require_outreach_ready()
    return {
        "scan_request": _handle(
            outreach_service.create_scan_request,
            submarket_id=payload.submarket_id,
            keyword_id=payload.keyword_id,
            note=payload.note,
            actor_id=auth["user_id"],
        )
    }


@router.post("/outreach/scan-requests/{request_id}/cancel")
async def cancel_scan_request(
    request_id: str, auth: dict = Depends(require_admin)
) -> dict:
    """Withdraw a PENDING order. One the tick has claimed is already executing — it resolves on
    its own and the outcome is the record; cancelling it would only orphan the spend."""
    _require_outreach_ready()
    return {"scan_request": _handle(outreach_service.cancel_scan_request, request_id, auth["user_id"])}


@router.get("/outreach/scan-requests")
async def list_scan_requests(
    status: Optional[str] = None,
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    return _handle(outreach_service.list_scan_requests, status=status, limit=limit, offset=offset)


@router.get("/outreach/scan-requests/{request_id}")
async def scan_request_detail(request_id: str, auth: dict = Depends(require_outreach)) -> dict:
    """The status screen's read: order + snapshot + per-status task counts + rollup marker."""
    return _handle(outreach_service.scan_request_detail, request_id)


@router.get("/outreach/submarkets/{submarket_id}/placeholder-scores")
async def placeholder_scores(
    submarket_id: str,
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    """Coverage-deficit scores for one submarket, worst first.

    Empty means NOT MEASURED (no rollup marker → the view returns no rows), and the payload says
    so explicitly — I-076's other half. Rendering an empty list as "no data" would read a
    failed scan as total invisibility, which is the strongest pitch in the market, manufactured.
    """
    result = _handle(outreach_service.placeholder_scores, submarket_id, limit, offset)
    result["measured"] = result["total"] > 0
    return result


# --- Onboard orders (the "City + Business type" full-pipeline order) ---------------------------
#
# An onboard order authorizes discover → filter → scan for a TYPED city (DECISIONS.md 2026-08-08,
# ISSUES I-092). Admin-gated like scan orders — it authorizes a paid discovery pull PLUS a scan —
# and executed the same way: platform-api writes the signed row, the outreach `tick` runs it.


@router.post("/outreach/onboard-requests")
async def create_onboard_request(
    payload: OnboardRequestCreate, auth: dict = Depends(require_admin)
) -> dict:
    """Place a signed onboard order for a typed city + business type.

    ADMIN-gated: this row causes the outreach job to run a paid Outscraper discovery pull AND post
    a geogrid scan on its next tick. The click IS the confirmation; nothing is contacted here.
    """
    _require_outreach_ready()
    return {
        "onboard_request": _handle(
            outreach_service.create_onboard_from_place,
            city=payload.city.model_dump(),
            subarea=payload.subarea.model_dump(),
            business_type=payload.business_type,
            note=payload.note,
            actor_id=auth["user_id"],
        )
    }


@router.get("/outreach/onboard-requests")
async def list_onboard_requests(
    status: Optional[str] = None,
    limit: int = Query(default=outreach_service.DEFAULT_PAGE_SIZE, ge=1),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_outreach),
) -> dict:
    return _handle(outreach_service.list_onboard_requests, status=status, limit=limit, offset=offset)


@router.get("/outreach/onboard-requests/{request_id}")
async def onboard_request_detail(request_id: str, auth: dict = Depends(require_outreach)) -> dict:
    """The status screen's read: order + stage + ingested/survived counts + snapshot."""
    return _handle(outreach_service.onboard_request_detail, request_id)


@router.post("/outreach/onboard-requests/{request_id}/cancel")
async def cancel_onboard_request(
    request_id: str, auth: dict = Depends(require_admin)
) -> dict:
    """Withdraw a PENDING onboard. One the tick has claimed is mid-discovery (real money) and
    resolves on its own."""
    _require_outreach_ready()
    return _handle(outreach_service.cancel_onboard_request, request_id, auth["user_id"])


def _require_outreach_ready() -> None:
    """The write routes gate on `require_staff` for the role, so they cannot also depend on
    `require_outreach` for the module. This applies the same two checks."""
    if not settings.outreach_enabled:
        raise HTTPException(status_code=503, detail="outreach_not_enabled")
    if not outreach_configured():
        raise HTTPException(status_code=503, detail="outreach_not_configured")
