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

DataForSEO shape notes — verified against docs.dataforseo.com 2026-09-14, but NOT
from a live call (the build sandbox is egress-blocked from api.dataforseo.com; a
403 CONNECT tunnel). Run ``scripts/verify_google_trends.py`` from the Railway
PLATFORM service (which holds the creds and has egress) to confirm the response
shape before flipping the flag on. Known facts:
  * endpoint  POST /v3/keywords_data/google_trends/explore/live
  * request   [{keywords: [≤5], location_name|location_code, date_from, category_code, type}]
  * DO NOT send ``item_types`` — the DOCUMENTED param is REJECTED live with task
    error 40501 "Invalid Field: 'item_types'" ($0 charged). ``google_trends_queries_list``
    is returned in the DEFAULT response, so we parse it from there.
  * response  tasks[0].result[0].items[] — the item with type="google_trends_queries_list"
    carries data.top[] / data.rising[] (each {query, value}; a rising value is a
    percent int or the string "Breakout"). Parsed defensively.
  * categories POST /v3/keywords_data/google_trends/categories (free) → a category tree.
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
            logger.warning("google_trends_dfs_retry", extra={"path": path, "status": resp.status_code,
                                                             "attempt": attempt + 1, "delay_s": round(delay, 1)})
            await asyncio.sleep(delay)
            attempt += 1
            continue
        resp.raise_for_status()
        return resp.json()


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
) -> tuple[dict, float]:
    """One Google Trends explore call (≤5 keywords). Returns (body, cost).

    NOTE: no ``item_types`` — it is rejected live (40501); the queries list is in
    the default response."""
    task: dict = {"keywords": keywords[:_EXPLORE_MAX_KEYWORDS], "type": trends_type or "web"}
    if category_code is not None:
        task["category_code"] = int(category_code)
    if location_code is not None:
        task["location_code"] = int(location_code)
    if language_code:
        task["language_code"] = language_code
    if date_from:
        task["date_from"] = date_from
    body = await _post(_EXPLORE_PATH, [task])
    cost = dataforseo_labs.cost_of(body) or 0.0
    return body, cost


async def fetch_categories(force: bool = False) -> list[dict]:
    """The Google Trends category tree (free endpoint), cached per process.
    Best-effort — an empty list on failure (the UI degrades to a free-text code)."""
    global _CATEGORIES_CACHE
    if _CATEGORIES_CACHE is not None and not force:
        return _CATEGORIES_CACHE
    try:
        body = await _post(_CATEGORIES_PATH, [{}])
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

    # One explore call per ≤5-seed chunk (each billed).
    chunks = dataforseo_labs.chunk(seeds, _EXPLORE_MAX_KEYWORDS)
    reserve_budget(len(chunks))

    rising: list[dict] = []
    total_cost = 0.0
    for group in chunks:
        try:
            body, cost = await explore_live(
                group, category_code=category_code, location_code=location_code,
                language_code=language_code, trends_type=trends_type,
            )
        except Exception as exc:  # noqa: BLE001 — one dead chunk shouldn't kill the scan
            logger.warning("google_trends.explore_chunk_failed",
                           extra={"client_id": client_id, "error": str(exc)})
            continue
        total_cost += cost
        for r in parse_rising_queries(body):
            # Attribute to the first seed in the chunk (explore aggregates across
            # the ≤5 keywords; per-query origin isn't returned).
            r["seed"] = group[0] if len(group) == 1 else None
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
            logger.warning("google_trends.qualify_failed",
                           extra={"client_id": client_id, "error": str(exc)})

    rows = build_trend_rows(deduped, overview)
    qualified = sum(1 for r in rows if r["qualified"])

    run = _persist_run(
        client_id, seeds, rows,
        category_code=category_code, category_name=category_name,
        location_code=location_code, language_code=language_code,
        trends_type=trends_type, cost_usd=round(total_cost, 4),
        qualified=qualified,
    )
    return {
        "run_id": run,
        "rising_count": len(rows),
        "qualified_count": qualified,
        "cost_usd": round(total_cost, 4),
    }


def _persist_run(
    client_id: str, seeds: list[str], rows: list[dict], *,
    category_code, category_name, location_code, language_code, trends_type,
    cost_usd, qualified,
) -> str:
    supabase = get_supabase()
    run = (
        supabase.table("google_trends_runs").insert({
            "client_id": client_id,
            "seeds": seeds,
            "category_code": category_code,
            "category_name": category_name,
            "location_code": location_code,
            "language_code": language_code,
            "trends_type": trends_type,
            "rising_count": len(rows),
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
                "is_question", "qualified", "trend_score",
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
    category_code: Optional[int] = None,
    category_name: Optional[str] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    trends_type: str = "web",
    user_id: Optional[str] = None,
) -> str:
    """Enqueue a google_trends_scan async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "google_trends_scan",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "seeds": seeds,
                "category_code": category_code, "category_name": category_name,
                "location_code": location_code, "language_code": language_code,
                "trends_type": trends_type, "user_id": user_id,
            },
        }).execute()
    ).data[0]
    return row["id"]


async def run_google_trends_scan_job(job: dict) -> None:
    """async_jobs handler for google_trends_scan."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
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
# Reads (for the router).
# ---------------------------------------------------------------------------
def list_runs(client_id: str, limit: int = 25) -> list[dict]:
    """Scan-run summary rows for a client (no child keywords), newest first."""
    return (
        get_supabase().table("google_trends_runs")
        .select("id, seeds, category_code, category_name, location_code, "
                "language_code, trends_type, rising_count, qualified_count, "
                "cost_usd, status, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_run(client_id: str, run_id: str) -> Optional[dict]:
    """A single run + its rising-query rows (trend_score desc). None if not the
    client's run."""
    supabase = get_supabase()
    runs = (
        supabase.table("google_trends_runs").select("*")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
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
