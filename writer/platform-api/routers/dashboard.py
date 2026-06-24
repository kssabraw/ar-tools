"""Suite dashboard aggregates that span modules.

`/dashboard/ranking-health` powers the per-client tiles: whether each client's
average organic position and average maps (local-pack geo-grid) rank improved or
worsened, latest run vs first. Lower rank numbers are better, so "improved" means
the latest average is a smaller number than the first. One call covers every
client via the `client_ranking_health()` SQL function (aggregation in Postgres).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_auth

router = APIRouter()

# Below this absolute change in average rank we treat the trend as flat — rank
# averages wobble run-to-run, so a hair of movement isn't a real direction.
_FLAT_EPSILON = 0.1


class RankingTrend(BaseModel):
    first_avg: float | None = None
    latest_avg: float | None = None
    # Improvement magnitude (first_avg - latest_avg); positive = moved up (better).
    delta: float | None = None
    # "up" = improved (smaller rank number), "down" = worsened, "flat" = no real
    # change, None = not enough data (need a first and a latest with values).
    direction: str | None = None
    sample_count: int = 0  # tracked keywords (organic) / completed scans (maps)


class ClientRankingHealth(BaseModel):
    client_id: str
    organic: RankingTrend
    maps: RankingTrend


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
        # Skip tiles with nothing to show on either axis.
        if organic.latest_avg is None and maps.latest_avg is None:
            continue
        clients.append(
            ClientRankingHealth(client_id=r["client_id"], organic=organic, maps=maps)
        )
    return RankingHealthResponse(clients=clients)
