"""Demand fetch — monthly search volume + CPC for a snapshot's (keyword, location).

The FIRST link of the missed-opportunity valuation chain (docs/missed-opportunity-valuation-prd-
v0_1.md): the ONE paid call the feature needs. Everything downstream (the gap from the rank_vector,
the pack-CTR curve, the per-category close/job-value assumptions) is config + data already on disk,
read at report-assembly time in platform-api. This module only fills the `keyword_demand` cache.

Search volume + CPC are a property of the (keyword, location), NOT the business — every prospect in
a submarket scanning the same keyword shares one number — so this fetches ONCE per (keyword,
location_token) and caches it, reused across every prospect and every re-scan. One cheap DataForSEO
Google-Ads `search_volume/live` call, the suite's `keyword_market` request shape rebuilt in the
outreach worker (the two-database invariant: platform-api only READS this cache).

Two things are MEASURED on the first live run, not asserted (the dataforseo_client.py discipline):

  1. **The location token.** There is NO lat/lng → numeric location_code resolver in the codebase,
     and the market/submarket rows carry no region/country column, so `resolve_location_token`
     builds a best-effort DataForSEO `location_name` string from the names it has and REFUSES when it
     can't (records a failed order, never a fabricated/national code — national volume ÷ a 5-mile
     footprint is nonsense). Whether that token resolves to city-granular volume is the PRD §12
     spike; the first run logs the resolved token + the raw response so it is measured, not guessed.
  2. **The response envelope.** `parse_search_volume` is tolerant and RAISES on a task-level error
     (an outage must never read as "no demand", which would manufacture the strongest-sounding
     valuation — zero — exactly the coverage-layer trap).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import Settings
from .scan_runner import BASE_URL, _auth_header

logger = logging.getLogger(__name__)

# The standard DataForSEO Google-Ads search-volume endpoint (the suite's keyword_market uses the
# same path). Added to dataforseo_client.CANDIDATE_REVIEW_PATHS so `probe-dataforseo` can confirm it
# FREE before the first paid call, per the measure-don't-infer discipline.
SEARCH_VOLUME_PATH = "/v3/keywords_data/google_ads/search_volume/live"

# DataForSEO's caps on the search_volume request (from keyword_market): a keyword over these is
# rejected, so a scan keyword that violates them is skipped with a recorded problem rather than
# failing the order.
_MAX_KEYWORD_CHARS = 80
_MAX_KEYWORD_WORDS = 10

_TASK_STATUS_OK = 20000

# LOW/MEDIUM/HIGH → a 0..1 competition index, so the cached value is uniform whether DataForSEO
# returns the string label or the numeric `competition_index`. Unknown/None stays None (unknown ≡
# absent — never a fabricated 0).
_COMPETITION_INDEX = {"LOW": 0.1, "MEDIUM": 0.5, "HIGH": 0.9}


class DemandFetchError(RuntimeError):
    """A failure fetching or parsing the search-volume response, incl. a task-level error in a 200."""


@dataclass(frozen=True)
class DemandMetrics:
    """The volume/CPC/competition for one (keyword, location), all NULLABLE — a null is a finding
    ("asked, no measurable volume"), never coerced to 0."""

    search_volume: int | None
    cpc: float | None
    competition: float | None


@dataclass
class DemandFetchReport:
    keyword: str = ""
    location_token: str = ""
    stored: bool = False
    already_cached: bool = False
    search_volume: int | None = None
    cpc: float | None = None
    problems: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- pure: token resolution + request + parse -------------------------------------------------


def resolve_location_token(submarket: dict[str, Any], market: dict[str, Any] | None) -> str | None:
    """Best-effort DataForSEO `location_name` for a submarket. Pure.

    SPIKE-GATED (PRD §12 spike 1). There is no lat/lng → location_code resolver and no region/country
    column, so this builds the most specific plausible name it can from what exists — the submarket
    name, else the market name — and returns None when it has nothing usable. None → the fetch
    REFUSES (no national fallback: national volume localized to a 5-mile footprint is meaningless).
    The resolved token is stored on the submarket and logged on first run so its quality is measured,
    not assumed; if the first live run shows the name is too ambiguous, the fix is a richer resolver
    (reverse-geocode + a locations-list match), and the stored-token schema survives that change.
    """
    for candidate in (submarket.get("name"), (market or {}).get("name")):
        token = str(candidate or "").strip()
        if token:
            return token
    return None


def _keyword_ok(keyword: str) -> str | None:
    """Why this keyword can't be sent to search_volume, or None. Enforces DataForSEO's caps so an
    oversized term is skipped with a reason rather than failing the whole order."""
    kw = keyword.strip()
    if not kw:
        return "empty keyword"
    if len(kw) > _MAX_KEYWORD_CHARS:
        return f"keyword exceeds {_MAX_KEYWORD_CHARS} chars"
    if len(kw.split()) > _MAX_KEYWORD_WORDS:
        return f"keyword exceeds {_MAX_KEYWORD_WORDS} words"
    return None


def build_search_volume_task(
    keyword: str, location_token: str, *, language_code: str
) -> dict[str, Any]:
    """The DataForSEO google_ads/search_volume/live request body for one keyword at one location.
    Pure. Uses `location_name` (a string) rather than `location_code` (an int) because no lat/lng →
    code resolver exists — see resolve_location_token."""
    return {
        "keywords": [keyword],
        "location_name": location_token,
        "language_code": language_code,
    }


def _coerce_competition(item: dict[str, Any]) -> float | None:
    """A 0..1 competition index from either the numeric field or the LOW/MED/HIGH label. Pure."""
    idx = item.get("competition_index")
    if isinstance(idx, (int, float)) and not isinstance(idx, bool):
        # DataForSEO's competition_index is 0..100; normalise to 0..1.
        return round(min(1.0, max(0.0, float(idx) / 100.0)), 4)
    label = item.get("competition")
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return round(min(1.0, max(0.0, float(label))), 4)
    if isinstance(label, str):
        return _COMPETITION_INDEX.get(label.strip().upper())
    return None


def parse_search_volume(body: dict[str, Any], keyword: str) -> DemandMetrics:
    """Read one search_volume/live response into volume/CPC/competition for `keyword`. Pure.

    RAISES DemandFetchError on a task-level error (status_code != 20000) — an outage must not be
    collapsed into "no demand". Matches the requested keyword case-insensitively; a response that
    carried no matching item returns all-None (asked, nothing measurable), which is a finding, not an
    error."""
    tasks = body.get("tasks") or []
    if not tasks:
        raise DemandFetchError("response carried no tasks")
    task = tasks[0] or {}
    status = task.get("status_code")
    if status is not None and status != _TASK_STATUS_OK:
        raise DemandFetchError(
            f"task failed: status_code={status} message={task.get('status_message')!r}"
        )
    result = task.get("result") or []
    target = keyword.strip().lower()
    for item in result:
        if not isinstance(item, dict):
            continue
        if str(item.get("keyword") or "").strip().lower() != target:
            continue
        vol = item.get("search_volume")
        cpc = item.get("cpc")
        return DemandMetrics(
            search_volume=int(vol) if isinstance(vol, (int, float)) and not isinstance(vol, bool) else None,
            cpc=float(cpc) if isinstance(cpc, (int, float)) and not isinstance(cpc, bool) else None,
            competition=_coerce_competition(item),
        )
    return DemandMetrics(search_volume=None, cpc=None, competition=None)


def normalize_keyword(keyword: str) -> str:
    """The keyword_demand cache key normalisation — lower/trim, so the same term from two submarkets
    shares one row. The reader (platform-api) must normalise identically. Pure."""
    return keyword.strip().lower()


def is_cache_fresh(fetched_at: Any, refresh_days: int, now: datetime) -> bool:
    """Is a cached keyword_demand row still fresh (no re-fetch)? Pure. refresh_days <= 0 means a row
    is always fresh (fetch once, never auto-refresh)."""
    if refresh_days <= 0:
        return True
    if not fetched_at:
        return False
    ts = fetched_at
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).days < refresh_days


# --- I/O: the fetch ---------------------------------------------------------------------------


async def fetch_demand(
    db: Any,
    settings: Settings,
    snapshot: dict[str, Any],
    keyword_term: str,
    *,
    market_id: str | None,
    client: httpx.AsyncClient | None = None,
) -> DemandFetchReport:
    """Fetch + cache search volume/CPC for a snapshot's (keyword, resolved location). BILLS one
    request, unless the (keyword, location_token) is already cached fresh (a free no-op).

    Resolves the location token from the snapshot's submarket (storing it on the submarket for
    reuse), checks the keyword_demand cache, and only calls DataForSEO on a miss/stale. A cost_ledger
    row is written best-effort (a ledger failure never costs the fetch, §7.1)."""
    report = DemandFetchReport(keyword=keyword_term)

    kw_problem = _keyword_ok(keyword_term)
    if kw_problem:
        report.problems.append(kw_problem)
        return report

    submarket_id = snapshot.get("submarket_id")
    if not submarket_id:
        report.problems.append("snapshot has no submarket — cannot resolve a location")
        return report
    sub_rows = (
        db.table("submarket").select("id, name, market_id, location_token")
        .eq("id", submarket_id).limit(1).execute().data or []
    )
    if not sub_rows:
        report.problems.append("submarket no longer exists")
        return report
    submarket = sub_rows[0]

    # Resolve (or reuse) the location token. Stored on the submarket so the resolution runs once.
    token = str(submarket.get("location_token") or "").strip()
    if not token:
        market = None
        if submarket.get("market_id"):
            m_rows = (
                db.table("market").select("id, name")
                .eq("id", submarket["market_id"]).limit(1).execute().data or []
            )
            market = m_rows[0] if m_rows else None
        resolved = resolve_location_token(submarket, market)
        if not resolved:
            report.problems.append(
                "could not resolve a location for the demand fetch (no submarket/market name)"
            )
            return report
        token = resolved
        db.table("submarket").update({"location_token": token}).eq("id", submarket_id).execute()
    report.location_token = token

    kw_key = normalize_keyword(keyword_term)

    # Cache check: a fresh row for this (keyword, location_token) is a free hit.
    cached = (
        db.table("keyword_demand").select("search_volume, cpc, fetched_at")
        .eq("keyword", kw_key).eq("location_token", token).limit(1).execute().data or []
    )
    if cached and is_cache_fresh(cached[0].get("fetched_at"), settings.demand_refresh_days, _now()):
        report.already_cached = True
        report.search_volume = cached[0].get("search_volume")
        report.cpc = cached[0].get("cpc")
        return report

    task = build_search_volume_task(
        keyword_term, token, language_code=settings.dataforseo_default_language_code
    )
    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    try:
        response = await client.post(
            f"{BASE_URL}{SEARCH_VOLUME_PATH}", headers=_auth_header(settings), json=[task]
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if owns:
            await client.aclose()

    # One full sample + the resolved token, once, so an unexpected envelope OR a bad location match
    # is diagnosable from the log rather than a second paid run (the dataforseo_client.py discipline).
    logger.info(
        "search_volume sample",
        extra={"keyword": kw_key, "location_token": token, "raw": str(body)[:4000]},
    )

    metrics = parse_search_volume(body, keyword_term)

    # Upsert the cache row (idempotent on the (keyword, location_token) unique key). A row is written
    # even when every metric is None — "asked, no measurable volume" is a fact worth caching so we
    # don't re-bill it every scan.
    db.table("keyword_demand").upsert(
        {
            "keyword": kw_key,
            "location_token": token,
            "search_volume": metrics.search_volume,
            "cpc": metrics.cpc,
            "competition": metrics.competition,
            "source": "dataforseo_google_ads",
            "fetched_at": _now().isoformat(),
        },
        on_conflict="keyword,location_token",
    ).execute()
    report.stored = True
    report.search_volume = metrics.search_volume
    report.cpc = metrics.cpc

    try:
        from .cost import build_ledger_row

        db.table("cost_ledger").insert(
            build_ledger_row(
                market_id=market_id,
                cycle_number=None,
                stage="b_demand",
                provider="dataforseo",
                units=1,
                cost_cents=settings.dataforseo_cost_per_request_cents,
            )
        ).execute()
    except Exception as exc:  # noqa: BLE001 — a ledger failure must never cost the fetch
        logger.error("could not write cost_ledger row (demand)", extra={"error": str(exc)[:500]})

    logger.info(
        "search_volume captured",
        extra={"keyword": kw_key, "location_token": token,
               "search_volume": metrics.search_volume, "cpc": metrics.cpc},
    )
    return report
