"""DataForSEO **Labs** client — the competitive-intelligence data layer for the
Domain Intelligence module (the "SEMrush clone").

The suite already has six ad-hoc DataForSEO wrappers (backlinks_api, serp_snapshot,
keyword_market, dataforseo_rank, the fanout client, the pipeline brief client).
Per the owner refactoring policy this module adds ONE new consolidated client for
the Labs *competitive* endpoints none of them call, rather than a seventh ad-hoc
wrapper or a refactor of the six. See docs/modules/domain-intelligence-module-prd-v1_0.md §4.

Endpoints wrapped (all `dataforseo_labs/google/.../live`):
  * ranked_keywords        → every keyword a domain ranks for (the core primitive)
  * domain_rank_overview   → organic traffic / keyword-count / authority rollup
  * bulk_traffic_estimation→ estimated organic traffic for a batch of domains
  * competitors_domain     → domains that share the most SERP real estate
  * keyword_overview       → per-keyword volume / CPC / KD / intent (batched ≤700)

Auth mirrors backlinks_api (Basic auth from settings). Parse helpers are pure
(no I/O) and independently unit-tested; fetch helpers do the HTTP with 429/5xx
retry + jittered backoff, same as backlinks_api._post.

DR/UR convention: the suite renders authority as rank ÷ 10 (0–100). Labs
`rank_absolute` is a SERP position (1..N), NOT the 0–1000 authority rank — do
not divide it. Authority rank (`domain_rank`/`rank`) IS 0–1000 and is scaled.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_RANKED_KEYWORDS_PATH = "/v3/dataforseo_labs/google/ranked_keywords/live"
_DOMAIN_RANK_OVERVIEW_PATH = "/v3/dataforseo_labs/google/domain_rank_overview/live"
_BULK_TRAFFIC_PATH = "/v3/dataforseo_labs/google/bulk_traffic_estimation/live"
_COMPETITORS_DOMAIN_PATH = "/v3/dataforseo_labs/google/competitors_domain/live"
_KEYWORD_OVERVIEW_PATH = "/v3/dataforseo_labs/google/keyword_overview/live"

_DEFAULT_LOCATION_CODE = 2840  # US
_DEFAULT_LANGUAGE_CODE = "en"
_KEYWORD_OVERVIEW_MAX = 700    # Labs per-task keyword cap
_TIMEOUT = 60.0
_DFS_MAX_RETRIES = 3
_DFS_RETRY_BASE_SECONDS = 2.0


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _coerce_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _coerce_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN → None


def rank_to_rating(rank) -> Optional[float]:
    """Authority rank (0–1000) → the suite's DR/UR proxy (0–100)."""
    f = _coerce_float(rank)
    return round(f / 10.0, 1) if f is not None else None


def domain_of(url_or_domain: Optional[str]) -> Optional[str]:
    """Bare registrable host: no scheme, no www, no path, casefolded. Pure."""
    raw = (url_or_domain or "").strip().lower()
    if not raw:
        return None
    if "//" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _first_result(body: dict, error_prefix: str) -> dict:
    """The single result object from a Labs response, or raise on a task error."""
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        msg = tasks[0].get("status_message") if tasks else "no tasks"
        raise RuntimeError(f"{error_prefix}: {msg}")
    return (tasks[0].get("result") or [{}])[0] or {}


def cost_of(body: dict) -> Optional[float]:
    """The real per-call USD cost DataForSEO returns on the task, or None."""
    tasks = body.get("tasks") or []
    return _coerce_float(tasks[0].get("cost")) if tasks else None


def parse_ranked_keywords(body: dict) -> list[dict]:
    """Rows for every keyword the target ranks for. One row per item:
    {keyword, position, url, volume, cpc_usd, keyword_difficulty, search_intent}.

    Labs nests keyword metrics under ``keyword_data`` and the SERP placement
    under ``ranked_serp_element.serp_item``. Missing sub-objects degrade the row
    (fields → None) rather than dropping it."""
    result = _first_result(body, "labs_ranked_keywords_error")
    out: list[dict] = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        kd = item.get("keyword_data") or {}
        ki = kd.get("keyword_info") or {}
        kp = kd.get("keyword_properties") or {}
        si = kd.get("search_intent_info") or {}
        serp = ((item.get("ranked_serp_element") or {}).get("serp_item")) or {}
        kw = kd.get("keyword")
        if not kw:
            continue
        out.append({
            "keyword": kw,
            "position": _coerce_int(serp.get("rank_absolute")),
            "url": serp.get("url"),
            "volume": _coerce_int(ki.get("search_volume")),
            "cpc_usd": _coerce_float(ki.get("cpc")),
            "keyword_difficulty": _coerce_float(kp.get("keyword_difficulty")),
            "search_intent": si.get("main_intent") if isinstance(si, dict) else None,
        })
    return out


def parse_domain_rank_overview(body: dict) -> dict:
    """Rollup metrics for a domain: {organic_traffic_est, ranked_keyword_count,
    organic_pos_1, traffic_value_est}. Labs returns these under metrics.organic."""
    result = _first_result(body, "labs_domain_rank_overview_error")
    items = result.get("items") or []
    metrics = (items[0].get("metrics") if items and isinstance(items[0], dict) else {}) or {}
    organic = metrics.get("organic") or {}
    return {
        "organic_traffic_est": _coerce_float(organic.get("etv")),
        "ranked_keyword_count": _coerce_int(organic.get("count")),
        "organic_pos_1": _coerce_int(organic.get("pos_1")),  # #1 positions only
        "traffic_value_est": _coerce_float(organic.get("estimated_paid_traffic_cost")),
    }


def parse_bulk_traffic(body: dict) -> dict[str, Optional[float]]:
    """{target_domain: estimated_organic_traffic} for a bulk estimation call."""
    result = _first_result(body, "labs_bulk_traffic_error")
    out: dict[str, Optional[float]] = {}
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        target = domain_of(item.get("target"))
        if not target:
            continue
        organic = ((item.get("metrics") or {}).get("organic")) or {}
        out[target] = _coerce_float(organic.get("etv"))
    return out


def parse_competitors_domain(body: dict) -> list[dict]:
    """Competitor domains by SERP overlap: {domain, avg_position, intersections,
    organic_keywords, organic_etv}. Sorted by intersections desc by the API."""
    result = _first_result(body, "labs_competitors_domain_error")
    out: list[dict] = []
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        dom = domain_of(item.get("domain"))
        if not dom:
            continue
        organic = ((item.get("metrics") or {}).get("organic")) or {}
        out.append({
            "domain": dom,
            "avg_position": _coerce_float(item.get("avg_position")),
            "intersections": _coerce_int(item.get("intersections")),
            "organic_keywords": _coerce_int(organic.get("count")),
            "organic_etv": _coerce_float(organic.get("etv")),
        })
    return out


def parse_keyword_overview(body: dict) -> dict[str, dict]:
    """{keyword: {volume, cpc_usd, competition_index, keyword_difficulty,
    search_intent}} for a batch. Missing keywords are simply absent."""
    result = _first_result(body, "labs_keyword_overview_error")
    out: dict[str, dict] = {}
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        kw = item.get("keyword")
        if not isinstance(kw, str):
            continue
        ki = item.get("keyword_info") or {}
        kp = item.get("keyword_properties") or {}
        si = item.get("search_intent_info") or {}
        out[kw] = {
            "volume": _coerce_int(ki.get("search_volume")),
            "cpc_usd": _coerce_float(ki.get("cpc")),
            "competition_index": _coerce_float(ki.get("competition_index")),
            "keyword_difficulty": _coerce_float(
                kp.get("keyword_difficulty") if isinstance(kp, dict) else None
            ),
            "search_intent": si.get("main_intent") if isinstance(si, dict) else None,
        }
    return out


def chunk(items: list, size: int) -> list[list]:
    """Split a list into chunks of at most ``size``. Pure."""
    return [items[i : i + size] for i in range(0, len(items), size)]


# ----------------------------------------------------------------------------
# Fetch (I/O) — 429/5xx retry with jittered backoff (mirrors backlinks_api._post).
# ----------------------------------------------------------------------------
async def _post(path: str, payload: list[dict]) -> dict:
    attempt = 0
    while True:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{_BASE_URL}{path}", headers=_auth_header(), json=payload)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= _DFS_MAX_RETRIES:
                resp.raise_for_status()
            try:
                retry_after = float(resp.headers.get("Retry-After") or 0)
            except ValueError:
                retry_after = 0.0
            delay = max(
                retry_after,
                _DFS_RETRY_BASE_SECONDS * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0),
            )
            logger.warning("labs_dfs_retry", extra={"path": path, "status": resp.status_code,
                                                     "attempt": attempt + 1, "delay_s": round(delay, 1)})
            await asyncio.sleep(delay)
            attempt += 1
            continue
        resp.raise_for_status()
        return resp.json()


def labs_location_code(location_code: Optional[int]) -> int:
    """Country-level location code for a Labs call. Pure.

    Labs endpoints accept COUNTRY codes only (2000 + ISO-3166 numeric, e.g.
    2840 = United States). Clients carry the rank tracker's CITY-level codes
    (7-digit) in rank_tracking_location_code — passing one to Labs fails the
    whole call with "Invalid Field: 'location_code'" (took out 60% of
    keyword_gap runs the week of 2026-07-06). Anything outside the country
    range is coerced to the default country; Labs data is country-grain anyway.
    """
    try:
        code = int(location_code) if location_code is not None else 0
    except (TypeError, ValueError):
        code = 0
    if 2000 <= code <= 2999:
        return code
    if code:
        logger.info(
            "labs_location_coerced",
            extra={"from_code": code, "to_code": _DEFAULT_LOCATION_CODE},
        )
    return _DEFAULT_LOCATION_CODE


def _loc(location_code: Optional[int], language_code: Optional[str]) -> dict:
    return {
        "location_code": labs_location_code(location_code),
        "language_code": language_code or _DEFAULT_LANGUAGE_CODE,
    }


async def fetch_ranked_keywords(
    target_domain: str,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    limit: int = 500,
    max_position: int = 100,
) -> tuple[list[dict], Optional[float]]:
    """Keywords ``target_domain`` ranks for in organic positions 1..max_position.
    Returns (rows, cost_usd). One billed call."""
    payload = [{
        "target": target_domain, **_loc(location_code, language_code),
        "limit": limit,
        # Pin to organic explicitly — relying on the API default risks paid /
        # featured-snippet placements polluting the organic-position data.
        "item_types": ["organic"],
        "order_by": ["ranked_serp_element.serp_item.rank_absolute,asc"],
        "filters": [["ranked_serp_element.serp_item.rank_absolute", "<=", max_position]],
    }]
    body = await _post(_RANKED_KEYWORDS_PATH, payload)
    return parse_ranked_keywords(body), cost_of(body)


async def fetch_domain_rank_overview(
    target_domain: str,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> tuple[dict, Optional[float]]:
    """Traffic / keyword-count / value rollup for a domain. Returns (rollup, cost)."""
    payload = [{"target": target_domain, **_loc(location_code, language_code)}]
    body = await _post(_DOMAIN_RANK_OVERVIEW_PATH, payload)
    return parse_domain_rank_overview(body), cost_of(body)


async def fetch_bulk_traffic(
    targets: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> tuple[dict[str, Optional[float]], Optional[float]]:
    """Estimated organic traffic for up to 1000 domains in one billed call."""
    if not targets:
        return {}, None
    payload = [{"targets": targets[:1000], **_loc(location_code, language_code)}]
    body = await _post(_BULK_TRAFFIC_PATH, payload)
    return parse_bulk_traffic(body), cost_of(body)


async def fetch_competitors_domain(
    target_domain: str,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    limit: int = 20,
) -> tuple[list[dict], Optional[float]]:
    """Domains that share the most SERP real estate with the target. One call."""
    payload = [{"target": target_domain, **_loc(location_code, language_code), "limit": limit}]
    body = await _post(_COMPETITORS_DOMAIN_PATH, payload)
    return parse_competitors_domain(body), cost_of(body)


async def fetch_keyword_overview(
    keywords: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> tuple[dict[str, dict], float]:
    """Per-keyword metrics for a batch, chunked at the 700-keyword cap. Returns
    (map, total_cost). One billed call per chunk."""
    merged: dict[str, dict] = {}
    total_cost = 0.0
    for group in chunk([k for k in keywords if k], _KEYWORD_OVERVIEW_MAX):
        payload = [{"keywords": group, **_loc(location_code, language_code)}]
        body = await _post(_KEYWORD_OVERVIEW_PATH, payload)
        merged.update(parse_keyword_overview(body))
        total_cost += cost_of(body) or 0.0
    return merged, round(total_cost, 4)
