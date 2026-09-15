"""Google Trends Discovery — the demand-discovery front door (shared core + Phase 1).

Pulls RISING related queries from Google Trends (via DataForSEO), qualifies each
with the volume/CPC data the suite already buys (``dataforseo_labs.fetch_keyword_overview``),
scores them (velocity × the EXISTING opportunity model — no second intent model),
and persists a run so the view is a cheap re-read.

This is an INPUT source, not a new pipeline: everything downstream of a qualified
rising query (cluster / draft / "Write this post") reuses existing modules. Phase 1
is ecommerce, **keyword-anchored** — a scan expands one or more seed keywords into
their rising related queries, optionally filtered to a Google Trends category. Ships
dark behind ``settings.google_trends_enabled`` (code default False).

DataForSEO shape notes — verified LIVE from Railway PLATFORM 2026-09-15
(queries_list=True with 13 rising / 25 top, categories=1427 rows, graph=53 points):
  * endpoint  POST /v3/keywords_data/google_trends/explore/live
  * request   [{keywords: [≤5], location_name|location_code, date_from, category_code,
    type, item_types}]
  * ``item_types`` IS accepted and REQUIRED to get the queries list — the DEFAULT
    response carries only ``google_trends_graph`` (interest_over_time) and no
    queries list, so every rising-query scan MUST send
    ``item_types: ["google_trends_queries_list"]``. The seasonal scan omits it and
    parses the default graph.
  * ONE keyword per explore for rising queries. Google Trends "related/rising
    queries" is a SINGLE-TERM concept: a multi-keyword explore is a comparison
    view that carries NO ``google_trends_queries_list`` item, so it returns zero
    rising queries (verified live 2026-09-15 — a 2-keyword explore returns 0
    rising even when each seed alone returns many). Rising-query scans therefore
    send exactly one keyword per call (``_QUERIES_EXPLORE_KEYWORDS``); the seasonal
    graph scan already explores one keyword per call for per-keyword attribution.
  * response  tasks[0].result[0].items[] — the item with type="google_trends_queries_list"
    carries data.top[] / data.rising[] (each {query, value}; a rising value is a
    percent int or the string "Breakout"). The graph item's points are
    {date_from, date_to, timestamp, missing_data, values:[int]}; a missing_data
    point is skipped. Parsed defensively.
  * categories GET /v3/keywords_data/google_trends/categories (free) → a flat
    {category_code, category_name, category_code_parent} list (a POST 404s).
  * cost ≈ $0.002 per explore task.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import secrets
from datetime import date
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_labs, keyword_research

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_EXPLORE_PATH = "/v3/keywords_data/google_trends/explore/live"
_CATEGORIES_PATH = "/v3/keywords_data/google_trends/categories"

_EXPLORE_MAX_KEYWORDS = 5   # DataForSEO Google Trends explore per-task keyword cap
# Rising-query scans send ONE keyword per explore: Google Trends related/rising
# queries only exist for a single search term, so a multi-keyword explore (a
# comparison view) carries no queries list and yields zero rising queries. See the
# module docstring's "ONE keyword per explore" note (verified live 2026-09-15).
_QUERIES_EXPLORE_KEYWORDS = 1
_BREAKOUT_PCT = 5000.0      # "Breakout" (>5000%) folded to this sentinel percentage
_TIMEOUT = 60.0
_DFS_MAX_RETRIES = 3
_DFS_RETRY_BASE_SECONDS = 2.0

# In-memory categories cache (the tree is static; the endpoint is free but a
# per-process cache avoids a call per dropdown render).
_CATEGORIES_CACHE: Optional[list[dict]] = None


class BudgetExceeded(Exception):
    """Raised when today's Google Trends paid-call budget is exhausted."""


# ---------------------------------------------------------------------------
# DataForSEO transport (clones dataforseo_labs._auth_header / _post — the plan
# keeps this wrapper self-contained rather than importing private helpers).
# ---------------------------------------------------------------------------
def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


async def _request(method: str, path: str, payload: Optional[list[dict]] = None) -> dict:
    """One DataForSEO call (POST with a task array, or GET). Retries on 429/5xx
    with jittered backoff. The explore endpoint is a POST; the categories endpoint
    is a **GET** (a POST 404s — verified live 2026-09-15)."""
    attempt = 0
    while True:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if method == "GET":
                resp = await client.get(f"{_BASE_URL}{path}", headers=_auth_header())
            else:
                resp = await client.post(f"{_BASE_URL}{path}", headers=_auth_header(), json=payload or [])
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
            logger.warning("google_trends_dfs_retry", extra={"path": path, "status": resp.status_code,
                                                             "attempt": attempt + 1, "delay_s": round(delay, 1)})
            await asyncio.sleep(delay)
            attempt += 1
            continue
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, payload: list[dict]) -> dict:
    return await _request("POST", path, payload)


async def _get(path: str) -> dict:
    return await _request("GET", path)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def parse_rising_value(value) -> tuple[float, bool]:
    """A Google Trends rising value → (percent, is_breakout). Pure.

    Rising values come as a percent int/float (250 = +250%) or the string
    "Breakout" (>5000%). Anything unparseable → (0.0, False)."""
    if isinstance(value, str):
        if "break" in value.lower():
            return _BREAKOUT_PCT, True
        cleaned = value.replace("%", "").replace(",", "").replace("+", "").strip()
        try:
            return max(0.0, float(cleaned)), False
        except ValueError:
            return 0.0, False
    if isinstance(value, (int, float)):
        return max(0.0, float(value)), False
    return 0.0, False


def parse_rising_queries(body: dict, *, include_top: bool = False) -> list[dict]:
    """Extract rising (and optionally top) related queries from a DataForSEO
    google_trends/explore response. Pure. Defensive against shape drift.

    Returns [{query, bucket, rising_value, is_breakout}] deduped by normalized
    query (first/strongest wins). ``bucket`` is 'rising' or 'top'."""
    tasks = body.get("tasks") if isinstance(body, dict) else None
    if not isinstance(tasks, list):
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "google_trends_queries_list":
                    continue
                data = item.get("data")
                if not isinstance(data, dict):
                    continue
                buckets = ["rising", "top"] if include_top else ["rising"]
                for bucket in buckets:
                    for entry in data.get(bucket) or []:
                        if not isinstance(entry, dict):
                            continue
                        query = entry.get("query") or entry.get("keyword")
                        if not isinstance(query, str) or not query.strip():
                            continue
                        norm = keyword_research.normalize_keyword(query)
                        if norm in seen:
                            continue
                        seen.add(norm)
                        pct, breakout = parse_rising_value(entry.get("value"))
                        out.append({
                            "query": query.strip(),
                            "bucket": bucket,
                            "rising_value": pct,
                            "is_breakout": breakout,
                        })
    return out


def velocity_factor(rising_pct: float) -> float:
    """A bounded, monotonic multiplier from a rising percentage. Pure.

    1.0 at no growth, ~1.3 at +100%, ~2.7 at Breakout (5000%). Log-shaped so a
    breakout doesn't swamp the qualified-demand signal it multiplies."""
    return 1.0 + math.log10(1.0 + max(0.0, rising_pct) / 100.0)


def trend_score(
    rising_pct: float,
    volume: Optional[int],
    cpc: Optional[float],
    keyword_difficulty: Optional[float],
    search_intent: Optional[str],
) -> float:
    """velocity × the EXISTING opportunity model. Pure, monotonic, sortable.

    Reuses ``keyword_research.opportunity_score`` wholesale (value × ease × intent
    weight) rather than inventing a second intent model — so a rising query with
    no commercial demand scores low even when its velocity is high."""
    opp = keyword_research.opportunity_score(volume, cpc, keyword_difficulty, search_intent)
    return round(velocity_factor(rising_pct) * opp, 2)


def build_trend_rows(rising: list[dict], overview: dict[str, dict]) -> list[dict]:
    """Merge rising queries with their DataForSEO overview metrics into stored
    rows. Pure. ``overview`` is {keyword: {volume, cpc_usd, competition_index,
    keyword_difficulty, search_intent}} (the fetch_keyword_overview shape).

    A query with demand (volume present) is ``qualified``; one without is kept for
    inspection but flagged. Sorted by trend_score desc, then volume desc."""
    rows: list[dict] = []
    for r in rising:
        query = r["query"]
        m = overview.get(query) or overview.get(keyword_research.normalize_keyword(query)) or {}
        volume = m.get("volume")
        cpc = m.get("cpc_usd")
        kd = m.get("keyword_difficulty")
        intent = m.get("search_intent")
        rows.append({
            "query": query,
            "seed": r.get("seed"),
            "bucket": r.get("bucket", "rising"),
            "rising_value": r.get("rising_value"),
            "is_breakout": bool(r.get("is_breakout")),
            "volume": volume,
            "cpc_usd": cpc,
            "competition_index": m.get("competition_index"),
            "keyword_difficulty": kd,
            "search_intent": intent,
            "is_question": keyword_research.is_question(query),
            "qualified": bool(volume),
            "trend_score": trend_score(r.get("rising_value") or 0.0, volume, cpc, kd, intent),
        })
    rows.sort(key=lambda x: (x["trend_score"] or 0.0, x["volume"] or 0), reverse=True)
    return rows


def parse_categories(body: dict) -> list[dict]:
    """Flatten a DataForSEO google_trends/categories response into
    [{category_code, category_name, parent_code}]. Pure. Defensive."""
    out: list[dict] = []
    tasks = body.get("tasks") if isinstance(body, dict) else None
    if not isinstance(tasks, list):
        return out

    def _walk(items):
        for item in items or []:
            if not isinstance(item, dict):
                continue
            code = item.get("category_code")
            name = item.get("category_name") or item.get("name")
            if code is not None and isinstance(name, str):
                out.append({
                    "category_code": code,
                    "category_name": name,
                    "parent_code": item.get("category_code_parent"),
                })
            # Some shapes nest children under 'items' / 'categories'.
            _walk(item.get("items") or item.get("categories"))

    for task in tasks:
        if not isinstance(task, dict):
            continue
        result = task.get("result")
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict) and isinstance(r.get("items"), list):
                    _walk(r["items"])
                elif isinstance(r, dict) and r.get("category_code") is not None:
                    _walk([r])
    return out


# ---------------------------------------------------------------------------
# Phase 4 (local seasonal) pure helpers — the interest_over_time slice of the
# explore response (a DIFFERENT item type from the queries list) → a calendar
# seasonality profile in the exact shape trend_watch.demand_outlook consumes.
#
# ⚠️ The interest_over_time shape is DOCUMENTED, not live-verified (the same
# egress block as the rising-queries shape) — the graph item is `type=
# "google_trends_graph"` with data[] points each carrying a timestamp + values[].
# scripts/verify_google_trends.py --keyword ... --interest prints the live shape;
# reconcile this parser + its tests together if it differs.
# ---------------------------------------------------------------------------
def _point_month(entry: dict) -> Optional[int]:
    """The calendar month (1-12) of an interest_over_time point. Defensive.

    Handles an explicit ``date_from``/``date`` ISO string, a unix ``timestamp``
    (seconds), or a nested ``{year, month}``. None when unparseable."""
    for key in ("date_from", "date", "datetime"):
        val = entry.get(key)
        if isinstance(val, str) and len(val) >= 7 and val[4] == "-":
            try:
                return int(val[5:7])
            except ValueError:
                pass
    ts = entry.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            from datetime import datetime, timezone
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).month
        except (ValueError, OSError, OverflowError):
            pass
    month = entry.get("month")
    if isinstance(month, int) and 1 <= month <= 12:
        return month
    return None


def _point_value(entry: dict) -> Optional[float]:
    """The interest value of a point. Defensive across shapes: a scalar ``value``,
    or a ``values``/``data`` list (single-keyword explore → first element)."""
    val = entry.get("value")
    if isinstance(val, (int, float)):
        return float(val)
    for key in ("values", "data"):
        seq = entry.get(key)
        if isinstance(seq, list) and seq:
            first = seq[0]
            if isinstance(first, (int, float)):
                return float(first)
            if isinstance(first, dict) and isinstance(first.get("value"), (int, float)):
                return float(first["value"])
    return None


def parse_interest_over_time(body: dict) -> list[dict]:
    """Extract the interest_over_time series from a DataForSEO explore response.
    Pure. Defensive. Returns [{month, value}] points (month 1-12, value float).

    Live graph point shape (verified 2026-09-15): {date_from, date_to, timestamp,
    missing_data, values:[int]} — ``values[0]`` for a single-keyword explore. A
    point flagged ``missing_data: true`` carries no real reading and is skipped."""
    tasks = body.get("tasks") if isinstance(body, dict) else None
    if not isinstance(tasks, list):
        return []
    out: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if not isinstance(item, dict) or item.get("type") != "google_trends_graph":
                    continue
                data = item.get("data")
                points = data if isinstance(data, list) else (
                    (data or {}).get("data") if isinstance(data, dict) else None)
                for entry in points or []:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("missing_data") is True:
                        continue
                    month = _point_month(entry)
                    value = _point_value(entry)
                    if month is not None and value is not None:
                        out.append({"month": month, "value": value})
    return out


def seasonality_profile_from_series(series: list[dict]) -> Optional[dict]:
    """A calendar seasonality profile from an interest_over_time series, in the
    EXACT shape trend_watch.demand_outlook consumes: {"index": {1..12: float},
    "peak_months": [...], "low_months": [...]} where 1.0 = the year's mean. Pure.

    Averages each point's value into its calendar month, then normalizes each
    month to the mean of the months that HAVE data. None when <6 months covered
    or the mean is zero (mirrors trend_watch.seasonality_profile's guards)."""
    by_month: dict[int, list[float]] = {}
    for p in series or []:
        m = p.get("month")
        v = p.get("value")
        if isinstance(m, int) and 1 <= m <= 12 and isinstance(v, (int, float)):
            by_month.setdefault(m, []).append(float(v))
    if len(by_month) < 6:
        return None
    month_avg = {m: (sum(vs) / len(vs)) for m, vs in by_month.items()}
    overall = sum(month_avg.values()) / len(month_avg)
    if overall <= 0:
        return None
    index = {m: round(month_avg[m] / overall, 3) for m in month_avg}
    peak = sorted(index, key=lambda m: index[m], reverse=True)[:3]
    low = sorted(index, key=lambda m: index[m])[:3]
    return {"index": index, "peak_months": sorted(peak), "low_months": sorted(low)}


# ---------------------------------------------------------------------------
# DataForSEO calls (I/O).
# ---------------------------------------------------------------------------
async def explore_live(
    keywords: list[str],
    *,
    category_code: Optional[int] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    trends_type: str = "web",
    date_from: Optional[str] = None,
    item_types: Optional[list[str]] = None,
) -> tuple[dict, float]:
    """One Google Trends explore call (≤5 keywords). Returns (body, cost).

    ``item_types`` selects which item types the response carries. To get the
    rising/top queries list you MUST pass ``["google_trends_queries_list"]`` — the
    DEFAULT response carries only ``google_trends_graph`` (interest_over_time) and
    no queries list (verified live 2026-09-15). The seasonal scan omits it so the
    default graph is what comes back."""
    task: dict = {"keywords": keywords[:_EXPLORE_MAX_KEYWORDS], "type": trends_type or "web"}
    if category_code is not None:
        task["category_code"] = int(category_code)
    if location_code is not None:
        task["location_code"] = int(location_code)
    if language_code:
        task["language_code"] = language_code
    if date_from:
        task["date_from"] = date_from
    if item_types:
        task["item_types"] = list(item_types)
    body = await _post(_EXPLORE_PATH, [task])
    cost = dataforseo_labs.cost_of(body) or 0.0
    return body, cost


async def fetch_categories(force: bool = False) -> list[dict]:
    """The Google Trends category tree (free endpoint), cached per process.
    Best-effort — an empty list on failure (the UI degrades to a free-text code).
    This endpoint is a **GET** — a POST 404s (verified live 2026-09-15)."""
    global _CATEGORIES_CACHE
    if _CATEGORIES_CACHE is not None and not force:
        return _CATEGORIES_CACHE
    try:
        body = await _get(_CATEGORIES_PATH)
        _CATEGORIES_CACHE = parse_categories(body)
    except Exception as exc:  # noqa: BLE001 — best-effort; the dropdown is optional
        logger.warning("google_trends.categories_failed", extra={"error": str(exc)})
        return []
    return _CATEGORIES_CACHE


# ---------------------------------------------------------------------------
# Budget meter (mirrors keyword_research; the reservation is FAIL-CLOSED — a
# paid scan never runs without a confirmed reservation).
# ---------------------------------------------------------------------------
def _today() -> str:
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid Google Trends calls left in today's budget (large when disabled)."""
    cap = settings.google_trends_daily_call_budget
    if cap <= 0:
        return 10 ** 9
    try:
        rows = (
            get_supabase().table("google_trends_usage").select("calls")
            .eq("day", _today()).limit(1).execute()
        ).data
    except Exception:
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def reserve_budget(n: int) -> None:
    """Reserve ``n`` paid calls against today's budget, or raise BudgetExceeded.
    Atomic via the reserve_google_trends_calls RPC. FAIL-CLOSED: a cap hit OR an
    accounting error both refuse (a paid scan must never run unmetered)."""
    cap = settings.google_trends_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_google_trends_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:
        logger.warning("google_trends_budget_accounting_failed", extra={"error": str(exc)})
        raise BudgetExceeded("google_trends_budget_unavailable") from exc
    if fit is False:
        raise BudgetExceeded(f"google_trends_budget_exceeded: cap {cap} reached today")


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
def _client_location(client_id: str) -> Optional[int]:
    """The client's rank-tracking location code (for geo-scoped Trends). Best-effort."""
    try:
        rows = (
            get_supabase().table("clients").select("rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception:
        return None
    if rows:
        return rows[0].get("rank_tracking_location_code")
    return None


async def _explore_and_qualify(
    seeds: list[str],
    *,
    category_code: Optional[int],
    location_code: Optional[int],
    language_code: str,
    trends_type: str,
    log_ctx: Optional[dict] = None,
) -> tuple[list[dict], float]:
    """Shared core: explore seeds → rising related queries → qualify with the
    volume/CPC gate → build stored rows. Returns (rows, total_cost). Reserves the
    paid-call budget (fail-closed) for the explore chunks + the overview batch.

    Used by every scan mode (keyword / category / portfolio). Explores ONE seed
    per call — Google Trends rising queries only exist for a single term (a
    multi-keyword explore is a comparison view with no queries list), so each seed
    is a chunk of one and every rising query attributes to its exact seed."""
    log_ctx = log_ctx or {}
    chunks = dataforseo_labs.chunk(seeds, _QUERIES_EXPLORE_KEYWORDS)
    reserve_budget(len(chunks))  # one explore call per seed (each billed)

    rising: list[dict] = []
    total_cost = 0.0
    for group in chunks:
        try:
            body, cost = await explore_live(
                group, category_code=category_code, location_code=location_code,
                language_code=language_code, trends_type=trends_type,
                item_types=["google_trends_queries_list"],
            )
        except Exception as exc:  # noqa: BLE001 — one dead chunk shouldn't kill the scan
            logger.warning("google_trends.explore_chunk_failed", extra={**log_ctx, "error": str(exc)})
            continue
        total_cost += cost
        for r in parse_rising_queries(body):
            r["seed"] = group[0]  # one seed per chunk → exact attribution
            rising.append(r)

    # Dedupe rising queries across chunks by normalized query.
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in rising:
        norm = keyword_research.normalize_keyword(r["query"])
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(r)

    # Qualify — the NON-NEGOTIABLE gate. Volume/CPC via the same call keyword
    # research uses (country-coerced location; Trends geo can be finer).
    overview: dict[str, dict] = {}
    if deduped:
        try:
            overview, ov_cost = await dataforseo_labs.fetch_keyword_overview(
                [r["query"] for r in deduped],
                location_code=dataforseo_labs.labs_location_code(location_code),
                language_code=language_code,
            )
            total_cost += ov_cost
            reserve_budget(1)  # meter the overview batch (best-effort accounting)
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 — unqualified rows still persist, flagged
            logger.warning("google_trends.qualify_failed", extra={**log_ctx, "error": str(exc)})

    return build_trend_rows(deduped, overview), round(total_cost, 4)


async def run_google_trends_scan(
    client_id: str,
    seeds: list[str],
    *,
    category_code: Optional[int] = None,
    category_name: Optional[str] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    trends_type: str = "web",
) -> dict:
    """Phase 1 scan: expand seeds → rising related queries → qualify → score →
    persist a run. Returns a summary dict. Raises BudgetExceeded when metered out.

    Keyword-anchored (seeds required), so it needs no relevance-anchor step — the
    seed IS the anchor. category_code is an optional Trends filter."""
    seeds = keyword_research.parse_seeds(seeds)
    if not seeds:
        raise ValueError("no_seeds")

    if location_code is None:
        location_code = _client_location(client_id)
    language_code = language_code or "en"
    trends_type = trends_type or "web"

    rows, total_cost = await _explore_and_qualify(
        seeds, category_code=category_code, location_code=location_code,
        language_code=language_code, trends_type=trends_type,
        log_ctx={"client_id": client_id},
    )
    qualified = sum(1 for r in rows if r["qualified"])

    run = _persist_run(
        client_id, seeds, rows, mode="keyword",
        category_code=category_code, category_name=category_name,
        location_code=location_code, language_code=language_code,
        trends_type=trends_type, cost_usd=total_cost, qualified=qualified,
    )
    return {
        "run_id": run,
        "rising_count": len(rows),
        "qualified_count": qualified,
        "cost_usd": total_cost,
    }


# ---------------------------------------------------------------------------
# Phase 2 — informational sites: a SEEDLESS category scan anchored on the
# client's own site topics + ICP, gated by the same relevance + audience filters
# keyword research uses, whose survivors route into Topic Research.
# ---------------------------------------------------------------------------
def derive_category_seeds(topic_research: dict, cap: int) -> list[str]:
    """The explore seeds for a seedless category scan: the client's own site
    topics, then intent-fanout expansion seeds, then the ICP-grounded intents
    (deduped, capped, in that priority). Pure.

    Trends explore needs keywords; a category scan has none, so we anchor on what
    the client is actually about. Site-topic slugs make the cleanest explore seeds,
    so they lead; the ICP-grounded ``intents`` are the fallback that lets a client
    with an ICP but no discoverable website still anchor a scan (honouring the
    'site topics/ICP' anchor decision). Empty only when the client has neither."""
    if not isinstance(topic_research, dict):
        return []
    site = topic_research.get("site")
    topics = (site or {}).get("topics") or []
    expansion = topic_research.get("expansion_seeds") or []
    intents = topic_research.get("intents") or []
    out: list[str] = []
    seen: set[str] = set()
    for phrase in list(topics) + list(expansion) + list(intents):
        if not isinstance(phrase, str) or not phrase.strip():
            continue
        norm = keyword_research.normalize_keyword(phrase)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(phrase.strip())
        if len(out) >= max(1, cap):
            break
    return out


_HEAD_TERM_MAX_TOKENS = 3  # longest head noun-phrase kept from a derived category seed


def head_term_seeds(
    seeds: list[str], cap: int, *, max_tokens: int = _HEAD_TERM_MAX_TOKENS
) -> list[str]:
    """Reduce derived category-scan seeds to the broader HEAD terms Google Trends
    can actually carry rising related queries for. Pure.

    Google Trends explore only returns related/rising queries for reasonably-popular
    HEAD terms — a long-tail derived phrase ("does semax need to be refrigerated",
    "ajp endocrinology and metabolism impact factor") returns ZERO even with the
    single-keyword-per-explore fix, which is why seedless category scans usually came
    back empty. Each seed is shortened to its first ``max_tokens`` significant tokens
    (``keyword_research.tokenize`` already drops interrogatives + stopwords + tiny
    words), then the set is deduped (normalized) and capped, preserving priority order.

    Best-effort: a seed that tokenizes to nothing (all stopwords/punctuation) falls
    through UNCHANGED so a scan never loses an anchor it can't shorten. NEVER applied
    to user-entered Phase-1 seeds — those stay verbatim."""
    out: list[str] = []
    seen: set[str] = set()
    for phrase in seeds or []:
        if not isinstance(phrase, str) or not phrase.strip():
            continue
        tokens = keyword_research.tokenize(phrase)
        head = " ".join(tokens[: max(1, max_tokens)]) if tokens else phrase.strip()
        norm = keyword_research.normalize_keyword(head)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(head)
        if len(out) >= max(1, cap):
            break
    return out


async def run_google_trends_category_scan(
    client_id: str,
    *,
    category_code: Optional[int] = None,
    category_name: Optional[str] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    trends_type: str = "web",
) -> dict:
    """Phase 2 scan (informational): derive anchor seeds from the client's site
    topics/ICP → explore (category-filtered) → qualify → the SAME relevance +
    audience gates keyword research uses → persist a run (mode='category'). The
    survivors are routed to Topic Research via the router (a deliberate human
    step, so the expensive strategist run is an explicit click, not auto-spend).

    Best-effort throughout: a missing site/LLM/embedding key degrades a gate to a
    no-op rather than aborting. Raises ValueError('no_anchor') only when the client
    has no site/ICP signal at all (nothing to anchor a seedless scan on)."""
    from services import keyword_research_topics

    if location_code is None:
        location_code = _client_location(client_id)
    language_code = language_code or "en"
    trends_type = trends_type or "web"

    ctx = keyword_research._client_context(client_id)
    try:
        topic_research = await keyword_research_topics.research_topics(ctx, [], location_code)
    except Exception as exc:  # noqa: BLE001 — degrade to no anchors rather than abort
        logger.warning("google_trends.topics_failed", extra={"client_id": client_id, "error": str(exc)})
        topic_research = {}

    seeds = derive_category_seeds(topic_research, settings.google_trends_category_seed_cap)
    if not seeds:
        # research_topics can be fully gated off (keyword_research_topical=False) or
        # return nothing; fall back to a DIRECT site-topic discovery (gated only on
        # keyword_research_site_topics) so a category scan still anchors on the
        # client's own site when it has one — decoupling Phase 2 from the topical flag.
        try:
            site_topics, _ = await keyword_research_topics.discover_site_topics(ctx, location_code)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("google_trends.site_topics_failed",
                           extra={"client_id": client_id, "error": str(exc)})
            site_topics = []
        seeds = derive_category_seeds(
            {"site": {"topics": site_topics}}, settings.google_trends_category_seed_cap)
    if not seeds:
        raise ValueError("no_anchor")
    # Relevance anchors keep the FULL derived phrases (the richer signal for the
    # gate); only the explore seeds are reduced to head terms below.
    anchors = topic_research.get("anchors") or list(seeds)
    # Google Trends explore only carries rising related queries for reasonably-popular
    # HEAD terms — a long-tail derived phrase returns zero even with the single-keyword
    # fix — so reduce each derived seed to its broader head term before exploring.
    seeds = head_term_seeds(seeds, settings.google_trends_category_seed_cap)

    rows, total_cost = await _explore_and_qualify(
        seeds, category_code=category_code, location_code=location_code,
        language_code=language_code, trends_type=trends_type,
        log_ctx={"client_id": client_id, "mode": "category"},
    )

    # Relevance + audience gates — reuse keyword research's, so a category's
    # national noise doesn't flood the client's list. Each needs a `keyword` field.
    for r in rows:
        r["keyword"] = r["query"]
    if rows and settings.keyword_research_semantic_relevance:
        try:
            from services import keyword_research_relevance
            rows, _ = await keyword_research_relevance.score_relevance(
                rows, anchors, seeds, settings.keyword_research_relevance_floor)
        except Exception as exc:  # noqa: BLE001 — best-effort; keep the token-gated set
            logger.warning("google_trends.relevance_failed",
                           extra={"client_id": client_id, "error": str(exc)})
    if rows and settings.keyword_research_audience_filter:
        try:
            from services import keyword_research_audience
            # Sync call on the async path — deliberately matching keyword_research's
            # own call site (the job worker runs one job per lane; offloading to a
            # thread would diverge from that pattern and put the shared Supabase
            # client on a worker thread for no meaningful gain).
            rows, _ = keyword_research_audience.filter_by_audience(rows, ctx, seeds)
        except Exception as exc:  # noqa: BLE001 — best-effort; keep the relevance-gated set
            logger.warning("google_trends.audience_failed",
                           extra={"client_id": client_id, "error": str(exc)})

    qualified = sum(1 for r in rows if r.get("qualified"))
    run = _persist_run(
        client_id, seeds, rows, mode="category",
        category_code=category_code, category_name=category_name,
        location_code=location_code, language_code=language_code,
        trends_type=trends_type, cost_usd=total_cost, qualified=qualified,
    )
    return {
        "run_id": run,
        "rising_count": len(rows),
        "qualified_count": qualified,
        "seeds": seeds,
        "cost_usd": total_cost,
    }


def _persist_run(
    client_id: Optional[str], seeds: list[str], rows: list[dict], *,
    mode: str = "keyword",
    category_code=None, category_name=None, location_code=None, language_code=None,
    trends_type="web", cost_usd=None, qualified=0, rising_count: Optional[int] = None,
) -> str:
    """Persist a run + its child rows. ``rising_count`` defaults to ``len(rows)``;
    pass it explicitly when ``rows`` is a capped subset of a larger set (the
    portfolio sweep stores a bounded slice but reports the true totals)."""
    supabase = get_supabase()
    run = (
        supabase.table("google_trends_runs").insert({
            "client_id": client_id,
            "mode": mode,
            "seeds": seeds,
            "category_code": category_code,
            "category_name": category_name,
            "location_code": location_code,
            "language_code": language_code,
            "trends_type": trends_type,
            "rising_count": rising_count if rising_count is not None else len(rows),
            "qualified_count": qualified,
            "status": "complete",
            "cost_usd": cost_usd,
        }).execute()
    ).data[0]
    run_id = run["id"]
    if rows:
        supabase.table("google_trends_keywords").insert(
            [{"run_id": run_id, **{k: r.get(k) for k in (
                "query", "seed", "bucket", "rising_value", "is_breakout", "volume",
                "cpc_usd", "competition_index", "keyword_difficulty", "search_intent",
                "is_question", "qualified", "trend_score", "relevance_score",
                "audience_fit", "source_client_name",
            )}} for r in rows]
        ).execute()
    return run_id


# ---------------------------------------------------------------------------
# Async job plumbing.
# ---------------------------------------------------------------------------
def enqueue_google_trends_scan(
    client_id: str,
    seeds: list[str],
    *,
    mode: str = "keyword",
    category_code: Optional[int] = None,
    category_name: Optional[str] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    trends_type: str = "web",
    user_id: Optional[str] = None,
) -> str:
    """Enqueue a google_trends_scan async job. Returns the job id. ``mode`` is
    'keyword' (Phase 1, seeds required) or 'category' (Phase 2, seeds derived)."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "google_trends_scan",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "seeds": seeds, "mode": mode,
                "category_code": category_code, "category_name": category_name,
                "location_code": location_code, "language_code": language_code,
                "trends_type": trends_type, "user_id": user_id,
            },
        }).execute()
    ).data[0]
    return row["id"]


def enqueue_portfolio_sweep(*, user_id: Optional[str] = None) -> str:
    """Enqueue a portfolio (agency-wide) Google Trends sweep. Returns the job id.
    client-less (entity_id null); the digest goes to the strategy channel."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "google_trends_scan",
            "payload": {"mode": "portfolio", "user_id": user_id},
        }).execute()
    ).data[0]
    return row["id"]


def enqueue_due_portfolio_trends_sweep() -> int:
    """Weekly (shared scheduler): enqueue ONE portfolio sweep. Self-gated on
    google_trends_enabled; deduped against an in-flight portfolio job so a
    same-day re-tick can't double-run. Returns 1 if enqueued, else 0."""
    if not settings.google_trends_enabled:
        return 0
    try:
        pending = (
            get_supabase().table("async_jobs").select("id, payload")
            .eq("job_type", "google_trends_scan").in_("status", ["pending", "running"])
            .limit(50).execute()
        ).data or []
    except Exception:  # noqa: BLE001 — on a read failure, err toward enqueuing
        pending = []
    if any((p.get("payload") or {}).get("mode") == "portfolio" for p in pending):
        return 0
    enqueue_portfolio_sweep()
    logger.info("gsc_scheduler.trends_sweep_enqueued")
    return 1


async def run_google_trends_scan_job(job: dict) -> None:
    """async_jobs handler for google_trends_scan (keyword / category / portfolio)."""
    payload = job.get("payload") or {}
    mode = payload.get("mode") or "keyword"
    supabase = get_supabase()
    try:
        if mode == "portfolio":
            result = await run_portfolio_trends_sweep()
        elif mode == "local_seasonal":
            result = await run_local_seasonal_scan(
                payload.get("client_id") or job.get("entity_id"),
                payload.get("seeds") or payload.get("keywords") or [],
                location_code=payload.get("location_code"),
                language_code=payload.get("language_code"),
                source_job_id=job.get("id"),
            )
        elif mode == "category":
            result = await run_google_trends_category_scan(
                payload.get("client_id") or job.get("entity_id"),
                category_code=payload.get("category_code"),
                category_name=payload.get("category_name"),
                location_code=payload.get("location_code"),
                language_code=payload.get("language_code"),
                trends_type=payload.get("trends_type") or "web",
            )
        else:
            result = await run_google_trends_scan(
                payload.get("client_id") or job.get("entity_id"),
                payload.get("seeds") or [],
                category_code=payload.get("category_code"),
                category_name=payload.get("category_name"),
                location_code=payload.get("location_code"),
                language_code=payload.get("language_code"),
                trends_type=payload.get("trends_type") or "web",
            )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except ValueError as exc:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:200], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("google_trends.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


# ---------------------------------------------------------------------------
# Phase 3 — portfolio-wide "what's rising this week": an agency sweep over the
# union of clients' tracked keywords (no client scope, no relevance/audience gate),
# digested to the SerMaStr strategy channel. Reuses the core with no anchor.
# ---------------------------------------------------------------------------
_PORTFOLIO_STORE_CAP = 500  # max qualified rows persisted per portfolio run


def _portfolio_seed_groups() -> list[dict]:
    """Per-client tracked-keyword seed groups for the sweep: [{client_id,
    client_name, seeds}]. Grouped by client so each rising query is attributable
    (explore aggregates within a chunk). Capped by config (clients × seeds)."""
    supabase = get_supabase()
    try:
        kw_rows = (
            supabase.table("tracked_keywords").select("client_id, keyword")
            .eq("active", True).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("google_trends.portfolio_seeds_failed", extra={"error": str(exc)})
        return []
    per_client_cap = max(1, settings.google_trends_portfolio_seeds_per_client)
    by_client: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for r in kw_rows:
        cid = r.get("client_id")
        kw = r.get("keyword")
        if not cid or not isinstance(kw, str) or not kw.strip():
            continue
        norm = keyword_research.normalize_keyword(kw)
        s = seen.setdefault(cid, set())
        if norm in s:
            continue
        bucket = by_client.setdefault(cid, [])
        if len(bucket) >= per_client_cap:
            continue
        s.add(norm)
        bucket.append(kw.strip())
    if not by_client:
        return []
    # Cap the number of clients DETERMINISTICALLY — most tracked keywords first
    # (biggest SEO footprint), client_id as a stable tiebreak — so a capped sweep
    # is reproducible and prioritises the most-invested clients rather than
    # whatever order the DB returned.
    client_ids = sorted(
        by_client, key=lambda c: (-len(by_client[c]), c)
    )[: max(1, settings.google_trends_portfolio_max_clients)]
    names: dict[str, str] = {}
    try:
        rows = (
            supabase.table("clients").select("id, name").in_("id", client_ids).execute()
        ).data or []
        names = {r["id"]: r.get("name") for r in rows}
    except Exception:  # noqa: BLE001 — names are cosmetic
        pass
    return [{"client_id": cid, "client_name": names.get(cid), "seeds": by_client[cid]}
            for cid in client_ids]


async def run_portfolio_trends_sweep() -> dict:
    """Phase 3 sweep: explore each client's tracked keywords → qualify → aggregate
    the top rising+qualified queries across the agency → persist a portfolio run
    (client_id null, mode='portfolio') → emit a weekly trends_digest to the
    strategy channel. Best-effort per client; raises BudgetExceeded when metered
    out (whatever was gathered before the cap is still digested)."""
    groups = _portfolio_seed_groups()
    if not groups:
        return {"rising_count": 0, "qualified_count": 0, "clients": 0, "note": "no_seeds"}

    all_rows: list[dict] = []
    total_cost = 0.0
    metered_out = False
    for g in groups:
        try:
            rows, cost = await _explore_and_qualify(
                g["seeds"], category_code=None, location_code=None,
                language_code="en", trends_type=settings.google_trends_default_type,
                log_ctx={"mode": "portfolio", "client_id": g["client_id"]},
            )
        except BudgetExceeded:
            metered_out = True
            break
        except Exception as exc:  # noqa: BLE001 — one client shouldn't kill the sweep
            logger.warning("google_trends.portfolio_client_failed",
                           extra={"client_id": g["client_id"], "error": str(exc)})
            continue
        total_cost += cost
        for r in rows:
            r["source_client_name"] = g.get("client_name")
        all_rows.extend(rows)

    # Aggregate: dedupe across clients by normalized query (strongest trend_score
    # wins), keep the qualified ones, rank, cap to the digest size.
    best: dict[str, dict] = {}
    for r in all_rows:
        norm = keyword_research.normalize_keyword(r["query"])
        if not norm:
            continue
        cur = best.get(norm)
        if cur is None or (r.get("trend_score") or 0) > (cur.get("trend_score") or 0):
            best[norm] = r
    ranked = sorted(best.values(), key=lambda x: (x.get("trend_score") or 0.0, x.get("volume") or 0), reverse=True)
    qualified_rows = [r for r in ranked if r.get("qualified")]
    digest_rows = qualified_rows[: max(1, settings.google_trends_portfolio_digest_size)]

    # Store the top qualified rows (bounded) — an agency sweep can dedupe to
    # thousands of rising queries across clients, and the no-demand ones aren't
    # actionable at the portfolio level. Report the TRUE totals via rising_count.
    stored_rows = qualified_rows[:_PORTFOLIO_STORE_CAP]
    run_id = _persist_run(
        None, [], stored_rows, mode="portfolio",
        location_code=None, language_code="en",
        trends_type=settings.google_trends_default_type,
        cost_usd=round(total_cost, 4), qualified=len(qualified_rows),
        rising_count=len(ranked),
    )
    # Emit the digest UNLESS we were budget-blocked before gathering anything — a
    # "nothing rising" post when the sweep never actually ran would be misleading.
    if digest_rows or not metered_out:
        _emit_portfolio_digest(run_id, digest_rows, len(qualified_rows))
    return {
        "run_id": run_id,
        "rising_count": len(ranked),
        "qualified_count": len(qualified_rows),
        "clients": len(groups),
        "cost_usd": round(total_cost, 4),
        "metered_out": metered_out,
    }


def build_digest_summary(rows: list[dict], total_qualified: int) -> str:
    """The weekly trends_digest body: top rising+qualified queries, each with its
    velocity, demand, and the client it surfaced for. Pure, deterministic."""
    if not rows:
        return "No qualified rising searches across the portfolio this week."
    lines = [f"*{len(rows)}* of {total_qualified} qualified rising searches across the portfolio this week:"]
    for r in rows:
        vel = "Breakout" if r.get("is_breakout") else (
            f"+{round(r['rising_value'])}%" if r.get("rising_value") else "rising")
        vol = f"{int(r['volume']):,}/mo" if r.get("volume") else "—"
        who = f" · {r['source_client_name']}" if r.get("source_client_name") else ""
        lines.append(f"• *{r['query']}* — {vel} · {vol}{who}")
    return "\n".join(lines)


def _emit_portfolio_digest(run_id: str, rows: list[dict], total_qualified: int) -> None:
    """Emit the weekly portfolio digest to the SerMaStr strategy channel.

    kind='trends_digest' is in NEITHER the PACE nor DIRECTOR routing set, so it
    falls through to settings.slack_default_channel (the strategy channel) — the
    same routing strategy reviews use. client_id=None (agency-level). Best-effort."""
    from datetime import date as _date
    try:
        from services import notifications
        iso = _date.today().isocalendar()
        notifications.emit(
            None, "trends_digest",
            "Google Trends — what's rising this week",
            summary=build_digest_summary(rows, total_qualified),
            payload={"run_id": run_id, "items": [
                {"query": r["query"], "trend_score": r.get("trend_score"),
                 "volume": r.get("volume"), "is_breakout": r.get("is_breakout"),
                 "client": r.get("source_client_name")} for r in rows]},
            dedupe_key=f"trends_digest:{iso[0]}-W{iso[1]:02d}",
        )
    except Exception as exc:  # noqa: BLE001 — the run persists even if delivery fails
        logger.warning("google_trends.digest_emit_failed", extra={"error": str(exc)})


# ---------------------------------------------------------------------------
# Phase 4 — local seasonal (metro-geo only): build a calendar seasonality
# profile from Trends interest_over_time and feed trend_watch.demand_outlook.
# A DIFFERENT slice of the explore response from Phases 1-3 (the graph, not the
# rising queries) — a distinct, smaller build. Result rides the job row (no new
# table), like backlink_lookup. Metro-only: sub-metro Ads volume returns null
# (the LeadOff ZIP probe proved it), so the qualify volume needs metro grain.
# ---------------------------------------------------------------------------
_SEASONAL_MAX_KEYWORDS = 10


def _seasonal_date_from(months: int) -> str:
    """ISO date ``months`` before today (the interest_over_time history window)."""
    from datetime import date as _date
    today = _date.today()
    total = today.year * 12 + (today.month - 1) - max(1, months)
    y, m = divmod(total, 12)
    return f"{y:04d}-{m + 1:02d}-01"


def _store_seasonality(
    client_id: str,
    location_code: int,
    profiles: list[dict],
    *,
    source_job_id: Optional[str] = None,
) -> int:
    """Persist each per-keyword Trends seasonality profile into
    google_trends_seasonality (keyed client × keyword × location), so
    trend_watch.build_demand_outlook can PREFER it over the Ads-volume-history
    profile on the Forecast card. Upsert on the unique key. Returns rows written.

    Best-effort: a write failure NEVER fails the scan (the profiles still ride the
    job row). A profile of None (thin history) writes nothing for that keyword —
    keyword_market's Ads history stays the fallback for it."""
    rows: list[dict] = []
    for p in profiles:
        prof = p.get("profile")
        if not isinstance(prof, dict) or not prof.get("index"):
            continue
        rows.append({
            "client_id": client_id,
            "keyword": p["keyword"],
            "location_code": location_code,
            # jsonb keys are strings; demand_outlook coerces them back to int months.
            "month_index": {str(m): v for m, v in prof["index"].items()},
            "peak_months": prof.get("peak_months") or [],
            "low_months": prof.get("low_months") or [],
            "source_run_id": source_job_id,
            "updated_at": "now()",
        })
    if not rows:
        return 0
    try:
        get_supabase().table("google_trends_seasonality").upsert(
            rows, on_conflict="client_id,keyword,location_code"
        ).execute()
    except Exception as exc:  # noqa: BLE001 — best-effort; the scan result still returns
        logger.warning("google_trends.seasonality_store_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        return 0
    return len(rows)


async def run_local_seasonal_scan(
    client_id: str,
    keywords: list[str],
    *,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    source_job_id: Optional[str] = None,
) -> dict:
    """Phase 4: per keyword, pull the Trends interest_over_time series (metro geo)
    → a calendar seasonality profile → persist it (google_trends_seasonality, so it
    reaches the Forecast card) + feed trend_watch.demand_outlook. Returns
    {outlook, profiles, location_code, cost_usd}. The result rides the job row.

    Metro-gated: raises ValueError('location_required') without a location_code
    (sub-metro Ads volume is null, so the qualify volume needs metro grain)."""
    keywords = keyword_research.parse_seeds(keywords)
    if not keywords:
        raise ValueError("no_keywords")
    if location_code is None:
        location_code = _client_location(client_id)
    if location_code is None:
        raise ValueError("location_required")
    language_code = language_code or "en"
    keywords = keywords[:_SEASONAL_MAX_KEYWORDS]
    date_from = _seasonal_date_from(settings.google_trends_seasonal_months)

    # One explore per keyword (a single keyword per call so the graph is that
    # keyword's — a multi-keyword explore returns one graph per keyword with no
    # attribution in parse_interest_over_time), plus one overview batch.
    reserve_budget(len(keywords) + 1)

    profiles: list[dict] = []
    total_cost = 0.0
    for kw in keywords:
        try:
            body, cost = await explore_live(
                [kw], location_code=location_code, language_code=language_code,
                trends_type="web", date_from=date_from,
            )
        except Exception as exc:  # noqa: BLE001 — one dead keyword shouldn't kill the scan
            logger.warning("google_trends.seasonal_explore_failed",
                           extra={"client_id": client_id, "keyword": kw, "error": str(exc)})
            continue
        total_cost += cost
        profile = seasonality_profile_from_series(parse_interest_over_time(body))
        profiles.append({"keyword": kw, "profile": profile})

    # Persist the profiles so trend_watch.build_demand_outlook prefers them on the
    # Forecast card (best-effort — never fails the scan; does NOT touch keyword_market).
    _store_seasonality(client_id, location_code, profiles, source_job_id=source_job_id)

    # Qualify for avg volume (metro grain) so demand_outlook can weight keywords.
    overview: dict[str, dict] = {}
    try:
        overview, ov_cost = await dataforseo_labs.fetch_keyword_overview(
            keywords, location_code=dataforseo_labs.labs_location_code(location_code),
            language_code=language_code,
        )
        total_cost += ov_cost
    except Exception as exc:  # noqa: BLE001 — profiles still usable without volume weighting
        logger.warning("google_trends.seasonal_qualify_failed",
                       extra={"client_id": client_id, "error": str(exc)})

    from datetime import date as _date
    from services import trend_watch
    tuples = [
        (p["keyword"],
         (overview.get(p["keyword"]) or {}).get("volume"),
         p["profile"])
        for p in profiles
    ]
    outlook = trend_watch.demand_outlook(tuples, _date.today())

    return {
        "location_code": location_code,
        "profiles": [
            {"keyword": p["keyword"],
             "index": (p["profile"] or {}).get("index"),
             "peak_months": (p["profile"] or {}).get("peak_months"),
             "volume": (overview.get(p["keyword"]) or {}).get("volume")}
            for p in profiles
        ],
        "outlook": outlook,
        "cost_usd": round(total_cost, 4),
    }


def enqueue_local_seasonal_scan(
    client_id: str, keywords: list[str], *,
    location_code: Optional[int] = None, language_code: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Enqueue a Phase 4 local-seasonal scan (mode='local_seasonal'). Job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "google_trends_scan",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "keywords": keywords, "mode": "local_seasonal",
                "location_code": location_code, "language_code": language_code,
                "user_id": user_id,
            },
        }).execute()
    ).data[0]
    return row["id"]


# ---------------------------------------------------------------------------
# Reads (for the router).
# ---------------------------------------------------------------------------
_RUN_SUMMARY_COLS = (
    "id, mode, seeds, category_code, category_name, location_code, "
    "language_code, trends_type, rising_count, qualified_count, "
    "cost_usd, status, created_at"
)


def list_runs(client_id: str, limit: int = 25) -> list[dict]:
    """Scan-run summary rows for a client (no child keywords), newest first.
    Covers both keyword (Phase 1) and category (Phase 2) runs — both client-scoped."""
    return (
        get_supabase().table("google_trends_runs")
        .select(_RUN_SUMMARY_COLS)
        .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def list_portfolio_runs(limit: int = 25) -> list[dict]:
    """Portfolio (agency-wide) sweep summary rows, newest first. client_id is null."""
    return (
        get_supabase().table("google_trends_runs")
        .select(_RUN_SUMMARY_COLS)
        .is_("client_id", "null").eq("mode", "portfolio")
        .order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_run(client_id: Optional[str], run_id: str) -> Optional[dict]:
    """A single run + its rising-query rows (trend_score desc). None if not the
    client's run. client_id=None fetches a portfolio run (client_id null)."""
    supabase = get_supabase()
    q = supabase.table("google_trends_runs").select("*").eq("id", run_id)
    q = q.is_("client_id", "null") if client_id is None else q.eq("client_id", client_id)
    runs = q.limit(1).execute().data
    if not runs:
        return None
    keywords = (
        supabase.table("google_trends_keywords").select("*")
        .eq("run_id", run_id).order("trend_score", desc=True).execute()
    ).data or []
    return {"run": runs[0], "keywords": keywords}


def clear_runs(client_id: str) -> int:
    """Delete ALL scans for a client (children cascade). Returns rows removed."""
    rows = (
        get_supabase().table("google_trends_runs").delete()
        .eq("client_id", client_id).execute()
    ).data or []
    return len(rows)
