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

**The location — MEASURED, then resolved to a location_code (I-122).** The first live run measured
the contract the dataforseo_client.py way: a best-effort `location_name` STRING ("Los Angeles, CA,
USA") is rejected by google_ads/search_volume/live with `40501 Invalid Field: 'location_name'`. The
endpoint geo-targets by a numeric `location_code` (the suite's keyword_market feeds it one in
production), so `resolve_location` now matches the submarket's city against DataForSEO's own
Google-Ads locations list (`fetch_locations`, the free reference endpoint, cached) and returns that
city's numeric `location_code`. It REFUSES when nothing matches — records a failed order, never a
fabricated/national code (national volume ÷ a 5-mile footprint is nonsense). The resolved
(city, code, canonical name) is logged. City-level volume is deliberate: the valuation localizes it
to the 5-mile footprint by Census population share downstream (I-123), so a hyper-local coordinate
would defeat that design. The stored `location_token` is the stringified code; a stale non-digit
token (e.g. a pre-fix name) is re-resolved automatically.

**The response envelope — MEASURED.** `parse_search_volume` is tolerant and RAISES on a task-level
error (an outage must never read as "no demand", which would manufacture the strongest-sounding
valuation — zero — exactly the coverage-layer trap).
"""
from __future__ import annotations

import logging
import time
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

# The Google-Ads locations REFERENCE list, scoped by country ISO. Country-scoped (`/{iso}`) to keep
# the response small. FREE reference data — a GET, not a per-task billed call — so resolving a code
# costs nothing. Using the google_ads family's OWN locations guarantees the codes it returns are the
# codes search_volume/live accepts (same geo-target space), which is the whole point of the I-122 fix.
GOOGLE_ADS_LOCATIONS_PATH = "/v3/keywords_data/google_ads/locations"

# location_type → sort priority for a city match (lower wins), mirroring the suite's locations_service:
# a City/Municipality/Town beats a Region/State, which beats a County. Anything else sorts last.
_TYPE_PRIORITY = {"City": 0, "Municipality": 0, "Town": 0, "Region": 1, "State": 1, "Province": 1,
                  "County": 2}

# Last-comma-segment country token → ISO, for scoping the locations lookup. Bare "CA" is deliberately
# absent (California vs Canada is ambiguous, and outreach markets carry it as a middle segment before
# "USA"); an unrecognised token falls back to the configured default (US). Extend as markets expand.
_COUNTRY_TOKENS = {
    "USA": "US", "US": "US", "UNITED STATES": "US",
    "AU": "AU", "AUS": "AU", "AUSTRALIA": "AU",
    "UK": "GB", "GB": "GB", "UNITED KINGDOM": "GB",
    "CANADA": "CA", "NZ": "NZ", "NEW ZEALAND": "NZ",
}

# country_iso → (fetched_at_monotonic, slim_locations). In-process, like locations_service — the list
# is near-static, so a long TTL avoids re-GETting the free reference list on every fetch.
_LOCATIONS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}

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


def city_query(submarket: dict[str, Any], market: dict[str, Any] | None) -> str | None:
    """The city string to match against DataForSEO's locations list. Pure.

    The first comma-segment of the submarket name (the city — "Los Angeles, CA, USA" → "Los Angeles",
    "Van Nuys" → "Van Nuys"), else the market name's first segment, else None. None → the fetch
    REFUSES (there is nothing to resolve a location from)."""
    for src in (submarket, market):
        name = str((src or {}).get("name") or "").strip()
        if name:
            seg = name.split(",")[0].strip()
            if seg:
                return seg
    return None


def infer_country_iso(
    submarket: dict[str, Any], market: dict[str, Any] | None, default: str = "US"
) -> str:
    """The country ISO to scope the locations lookup, from the name's last comma-segment. Pure.

    Reads the trailing country token ("…, USA" → US) off the submarket, else the market, else the
    configured default. Bare "CA" is intentionally NOT treated as Canada (it is California in the
    outreach markets and would sit mid-name before "USA")."""
    for src in (submarket, market):
        segs = [s.strip().upper() for s in str((src or {}).get("name") or "").split(",") if s.strip()]
        if segs and segs[-1] in _COUNTRY_TOKENS:
            return _COUNTRY_TOKENS[segs[-1]]
    return (default or "US").upper()


def match_location(
    locations: list[dict[str, Any]], query: str
) -> tuple[str, int] | None:
    """Best (canonical_name, location_code) for `query` in a locations list, or None. Pure.

    Mirrors locations_service._rank_key: match the query against each location's CITY segment (the
    part before the first comma), preferring an exact city match, then a prefix, then a substring;
    ties broken by location_type (City/Town beat Region beat County) then the shorter name. Returns
    None when nothing matches — the caller then REFUSES rather than sending a bad location."""
    q = query.strip().lower()
    if not q:
        return None
    best: tuple[tuple[int, int, int], str, int] | None = None
    for loc in locations:
        name = str(loc.get("location_name") or "")
        code = loc.get("location_code")
        if not name or code is None or isinstance(code, bool):
            continue
        first_seg = name.split(",")[0].strip().lower()
        if first_seg == q:
            match_rank = 0
        elif first_seg.startswith(q):
            match_rank = 1
        elif q in first_seg:
            match_rank = 2
        else:
            continue
        key = (match_rank, _TYPE_PRIORITY.get(str(loc.get("location_type") or ""), 3), len(name))
        if best is None or key < best[0]:
            best = (key, name, int(code))
    return (best[1], best[2]) if best else None


async def fetch_locations(
    settings: Settings, country_iso: str, *, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """The DataForSEO Google-Ads location list for a country, cached in-process. Impure.

    FREE reference data (a GET, not a per-task billed call). Returns [] on any failure so the caller
    degrades to a clean refusal rather than an exception. Uses its OWN client (the locations GET is
    independent of the search_volume POST), so tests pre-seed `_LOCATIONS_CACHE` and no network runs."""
    iso = (country_iso or "US").upper()
    ttl = getattr(settings, "demand_locations_cache_ttl_seconds", 24 * 60 * 60)
    cached = _LOCATIONS_CACHE.get(iso)
    if cached and (time.monotonic() - cached[0]) < ttl:
        return cached[1]

    url = f"{BASE_URL}{GOOGLE_ADS_LOCATIONS_PATH}/{iso}"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    try:
        resp = await client.get(url, headers=_auth_header(settings))
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — a dead reference lookup must degrade to a refusal
        logger.warning("demand locations fetch failed",
                       extra={"country": iso, "error": str(exc)[:200]})
        return []
    finally:
        if owns:
            await client.aclose()

    slim: list[dict[str, Any]] = []
    for task in (body.get("tasks") or []):
        for loc in (task.get("result") or []):
            name = loc.get("location_name")
            code = loc.get("location_code")
            if not name or code is None:
                continue
            slim.append({
                "location_name": name,
                "location_code": code,
                "location_type": loc.get("location_type") or "",
            })
    if slim:
        _LOCATIONS_CACHE[iso] = (time.monotonic(), slim)
    else:
        logger.warning("demand locations empty",
                       extra={"country": iso, "tasks": len(body.get("tasks") or [])})
    return slim


async def resolve_location(
    settings: Settings,
    submarket: dict[str, Any],
    market: dict[str, Any] | None,
    *,
    locations_client: httpx.AsyncClient | None = None,
) -> tuple[str, int] | None:
    """Resolve the submarket to a (canonical_name, location_code), or None (→ the fetch REFUSES).

    Matches the submarket's city against DataForSEO's own Google-Ads locations list, so the code it
    returns is one search_volume/live accepts. City-level by design — the volume is localized to the
    footprint by Census population share downstream (I-123), not by a hyper-local coordinate."""
    q = city_query(submarket, market)
    if not q:
        return None
    iso = infer_country_iso(submarket, market, getattr(settings, "demand_default_country_iso", "US"))
    locations = await fetch_locations(settings, iso, client=locations_client)
    if not locations:
        return None
    return match_location(locations, q)


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
    Pure. Branches on the token: an all-digits token is a numeric `location_code` (the resolved,
    endpoint-accepted form — see resolve_location); anything else is sent as a `location_name` string
    for back-compat. The endpoint rejects an unrecognised `location_name` (40501), which is why the
    resolver produces a code — the digit branch is the live path (I-122)."""
    loc = str(location_token).strip()
    if loc.isdigit():
        return {
            "keywords": [keyword],
            "location_code": int(loc),
            "language_code": language_code,
        }
    return {
        "keywords": [keyword],
        "location_name": loc,
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

    # Resolve (or reuse) the location token. Stored on the submarket so the resolution runs once. A
    # non-digit token is stale (a pre-I-122 location_name string) and is re-resolved to a numeric
    # location_code, so the fix self-heals an old row without a manual edit.
    token = str(submarket.get("location_token") or "").strip()
    if not token or not token.isdigit():
        market = None
        if submarket.get("market_id"):
            m_rows = (
                db.table("market").select("id, name")
                .eq("id", submarket["market_id"]).limit(1).execute().data or []
            )
            market = m_rows[0] if m_rows else None
        resolved = await resolve_location(settings, submarket, market)
        if not resolved:
            report.problems.append(
                "could not resolve a DataForSEO location_code for the demand fetch "
                "(no submarket/market city matched the Google-Ads locations list)"
            )
            return report
        canonical_name, code = resolved
        token = str(code)
        db.table("submarket").update({"location_token": token}).eq("id", submarket_id).execute()
        logger.info(
            "resolved demand location",
            extra={
                "submarket_id": submarket_id,
                "query": city_query(submarket, market),
                "location_code": code,
                "location_name": canonical_name,
            },
        )
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
