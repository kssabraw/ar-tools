"""Suite dashboard aggregates that span modules.

`/dashboard/ranking-health` powers the per-client tiles: whether each client's
average organic position, average maps (local-pack geo-grid) rank, and AI
visibility share improved or worsened, latest run vs first. For organic/maps,
lower rank numbers are better, so "improved" means the latest average is a
smaller number than the first; for AI visibility a HIGHER share percentage is
better. In both cases the trend's `direction` is normalized so "up" always
means improved (green in the UI). One call covers every client via the
`client_ranking_health()` SQL function (aggregation in Postgres).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_auth

router = APIRouter()

# Below this absolute change in average rank we treat the trend as flat — rank
# averages wobble run-to-run, so a hair of movement isn't a real direction.
_FLAT_EPSILON = 0.1
# AI visibility is a percentage; sub-point wobble between batches isn't a real
# direction, so treat changes under a full point as flat.
_VIS_FLAT_EPSILON = 1.0


class RankingTrend(BaseModel):
    first_avg: float | None = None
    latest_avg: float | None = None
    # Improvement magnitude (first_avg - latest_avg); positive = moved up (better).
    delta: float | None = None
    # "up" = improved (smaller rank number), "down" = worsened, "flat" = no real
    # change, None = not enough data (need a first and a latest with values).
    direction: str | None = None
    sample_count: int = 0  # tracked keywords (organic) / completed scans (maps)


class VisibilityTrend(BaseModel):
    """AI-visibility share trend (first scan batch vs latest). Higher share is
    better, so `delta` is latest - first and `direction` "up" means the share
    rose (improved) — kept polarity-aligned with RankingTrend so the UI treats
    "up" as green for all three axes."""
    first_pct: float | None = None
    latest_pct: float | None = None
    delta: float | None = None  # latest_pct - first_pct; positive = improved
    direction: str | None = None  # "up" = share rose, "down" = fell, "flat", None
    sample_count: int = 0  # completed scan batches


class ClientRankingHealth(BaseModel):
    client_id: str
    organic: RankingTrend
    maps: RankingTrend
    visibility: VisibilityTrend = VisibilityTrend()


class RankingHealthResponse(BaseModel):
    clients: list[ClientRankingHealth] = []


def _f(v) -> float | None:
    # Postgres `numeric` can arrive as a string over PostgREST; coerce so the
    # arithmetic below never trips on a str.
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trend(first: float | None, latest: float | None, count: int) -> RankingTrend:
    if first is None or latest is None:
        # A single run (first == latest with one data point) still yields a flat
        # trend; only a genuinely missing endpoint is "no direction".
        return RankingTrend(first_avg=first, latest_avg=latest, sample_count=count)
    delta = round(first - latest, 2)  # positive = improved (rank number dropped)
    if abs(delta) < _FLAT_EPSILON:
        direction = "flat"
    elif delta > 0:
        direction = "up"
    else:
        direction = "down"
    return RankingTrend(
        first_avg=round(first, 1),
        latest_avg=round(latest, 1),
        delta=delta,
        direction=direction,
        sample_count=count,
    )


def _vis_trend(first: float | None, latest: float | None, count: int) -> VisibilityTrend:
    if first is None or latest is None:
        return VisibilityTrend(first_pct=first, latest_pct=latest, sample_count=count)
    delta = round(latest - first, 1)  # positive = share rose (improved)
    if abs(delta) < _VIS_FLAT_EPSILON:
        direction = "flat"
    elif delta > 0:
        direction = "up"
    else:
        direction = "down"
    return VisibilityTrend(
        first_pct=round(first, 1),
        latest_pct=round(latest, 1),
        delta=delta,
        direction=direction,
        sample_count=count,
    )


@router.get("/dashboard/ranking-health", response_model=RankingHealthResponse)
async def ranking_health(auth: dict = Depends(require_auth)) -> RankingHealthResponse:
    supabase = get_supabase()
    rows = supabase.rpc("client_ranking_health").execute().data or []
    clients: list[ClientRankingHealth] = []
    for r in rows:
        organic = _trend(
            _f(r.get("organic_first_avg")),
            _f(r.get("organic_latest_avg")),
            r.get("organic_keyword_count") or 0,
        )
        maps = _trend(
            _f(r.get("maps_first_avg")),
            _f(r.get("maps_latest_avg")),
            r.get("maps_scan_count") or 0,
        )
        visibility = _vis_trend(
            _f(r.get("brand_first_pct")),
            _f(r.get("brand_latest_pct")),
            r.get("brand_batch_count") or 0,
        )
        # Skip tiles with nothing to show on any axis.
        if (
            organic.latest_avg is None
            and maps.latest_avg is None
            and visibility.latest_pct is None
        ):
            continue
        clients.append(
            ClientRankingHealth(
                client_id=r["client_id"],
                organic=organic,
                maps=maps,
                visibility=visibility,
            )
        )
    return RankingHealthResponse(clients=clients)
