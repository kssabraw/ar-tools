"""Domain Intelligence — the competitive-intelligence engine (the "SEMrush clone").

Phase 0 (foundations): the pure computational core + the paid-call budget/cache
guards. The async job runners, routers, and frontend land in Phases 1–2. See
docs/modules/domain-intelligence-module-prd-v1_0.md.

Design: every heavy read is a DataForSEO Labs call (services/dataforseo_labs.py),
persisted to a snapshot so views are cheap re-reads. The gap/scoring math here is
PURE (no I/O) and unit-tested — the LLM/agents consume its output, they never
recompute it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import backlinks_api, dataforseo_labs
from services.keyword_market import estimate_monthly_value

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a paid Labs call would exceed the module's daily budget."""


normalize_domain = dataforseo_labs.domain_of  # single source of truth


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def enrich_est_value(rows: list[dict]) -> list[dict]:
    """Attach an ``est_value`` (volume × CTR-at-position × CPC) to ranked-keyword
    rows, in place-safe fashion (returns new dicts). Pure."""
    out: list[dict] = []
    for r in rows:
        out.append({
            **r,
            "est_value": estimate_monthly_value(
                r.get("volume"), r.get("position"), r.get("cpc_usd")
            ),
        })
    return out


def opportunity_score(
    volume: Optional[int],
    cpc: Optional[float],
    keyword_difficulty: Optional[float],
    competitor_position: Optional[int],
    gap_type: Optional[str],
) -> float:
    """A ranked-opportunity score for a gap keyword. Higher = pursue first.

    value (volume × CPC) × ease (low KD) × proven (competitor already ranks high)
    × a per-gap-type weight. Deterministic and monotonic in each input, so the
    Action Plan / strategist can sort on it. Pure."""
    value = (volume or 0) * (cpc or 0.0)
    kd = keyword_difficulty if keyword_difficulty is not None else 50.0
    ease = max(0.0, min(100.0, 100.0 - kd)) / 100.0
    proven = 1.0 if (competitor_position or 999) <= 3 else 0.6
    weight = {"weak": 1.0, "missing": 0.8, "untapped": 0.7}.get(gap_type, 0.8)
    return round(value * ease * proven * weight, 2)


def classify_gap(
    client_position: Optional[int],
    competitor_position: Optional[int],
    *,
    competitor_max_position: int,
    client_min_position: int,
) -> Optional[str]:
    """Whether a (client, competitor) keyword pair is a gap, and which kind.

    A gap requires the competitor ranking at/above ``competitor_max_position``
    AND the client either absent or ranking worse than ``client_min_position``.
      * ``missing`` — client does not rank at all.
      * ``weak``    — client ranks, but below the threshold.
    Returns None when it isn't a gap. Pure."""
    if competitor_position is None or competitor_position > competitor_max_position:
        return None
    if client_position is None:
        return "missing"
    if client_position > client_min_position:
        return "weak"
    return None


def compute_keyword_gap(
    competitor_rows: list[dict],
    client_rows: list[dict],
    competitor_domain: Optional[str],
    *,
    competitor_max_position: Optional[int] = None,
    client_min_position: Optional[int] = None,
    min_volume: Optional[int] = None,
) -> list[dict]:
    """Gap keywords the ``competitor`` ranks for but the client doesn't (or ranks
    poorly for). ``*_rows`` are parse_ranked_keywords outputs. Sorted by
    opportunity_score desc. Pure (thresholds default to config)."""
    cmax = settings.domain_intel_gap_competitor_max_position if competitor_max_position is None else competitor_max_position
    cmin = settings.domain_intel_gap_client_min_position if client_min_position is None else client_min_position
    vmin = settings.domain_intel_gap_min_volume if min_volume is None else min_volume

    client_pos = {}
    for r in client_rows:
        kw = (r.get("keyword") or "").lower()
        pos = r.get("position")
        if kw and pos is not None and (kw not in client_pos or pos < client_pos[kw]):
            client_pos[kw] = pos

    gaps: list[dict] = []
    for r in competitor_rows:
        kw = r.get("keyword")
        if not kw:
            continue
        if (r.get("volume") or 0) < vmin:
            continue
        comp_pos = r.get("position")
        cli_pos = client_pos.get(kw.lower())
        gap_type = classify_gap(
            cli_pos, comp_pos,
            competitor_max_position=cmax, client_min_position=cmin,
        )
        if gap_type is None:
            continue
        gaps.append({
            "keyword": kw,
            "competitor_domain": competitor_domain,
            "competitor_position": comp_pos,
            "client_position": cli_pos,
            "volume": r.get("volume"),
            "cpc_usd": r.get("cpc_usd"),
            "keyword_difficulty": r.get("keyword_difficulty"),
            "gap_type": gap_type,
            "opportunity_score": opportunity_score(
                r.get("volume"), r.get("cpc_usd"), r.get("keyword_difficulty"),
                comp_pos, gap_type,
            ),
        })
    gaps.sort(key=lambda g: g["opportunity_score"], reverse=True)
    return gaps


def merge_keyword_gaps(gap_lists: list[list[dict]]) -> list[dict]:
    """Merge per-competitor gap lists into one, keeping the highest-scoring row
    per keyword and collecting which competitors rank for it. Sorted by score.
    Pure."""
    best: dict[str, dict] = {}
    for gaps in gap_lists:
        for g in gaps:
            key = (g.get("keyword") or "").lower()
            if not key:
                continue
            cur = best.get(key)
            if cur is None or g["opportunity_score"] > cur["opportunity_score"]:
                best[key] = dict(g)
    merged = list(best.values())
    merged.sort(key=lambda g: g["opportunity_score"], reverse=True)
    return merged


def compute_link_gap(
    competitor_referring: dict[str, list[dict]],
    client_referring_domains,
) -> list[dict]:
    """Referring domains linking to ≥1 competitor but NOT the client.

    ``competitor_referring`` maps a competitor domain → its referring-domain rows
    ({domain, rank, backlinks}). ``client_referring_domains`` is an iterable of the
    domains already linking to the client. Returns rows sorted by rank desc. Pure."""
    client_set = {normalize_domain(d) for d in (client_referring_domains or []) if d}
    acc: dict[str, dict] = {}
    for competitor, rows in (competitor_referring or {}).items():
        for row in rows or []:
            rd = normalize_domain(row.get("domain"))
            if not rd or rd in client_set:
                continue
            entry = acc.setdefault(rd, {
                "referring_domain": rd,
                "linking_to": set(),
                "referring_domain_rank": row.get("rank"),
                "backlink_count": row.get("backlinks"),
            })
            entry["linking_to"].add(competitor)
            # keep the strongest observed rank / highest backlink count
            if (row.get("rank") or 0) > (entry["referring_domain_rank"] or 0):
                entry["referring_domain_rank"] = row.get("rank")
            if (row.get("backlinks") or 0) > (entry["backlink_count"] or 0):
                entry["backlink_count"] = row.get("backlinks")
    out = []
    for entry in acc.values():
        out.append({**entry, "linking_to": sorted(entry["linking_to"])})
    out.sort(key=lambda e: (len(e["linking_to"]), e["referring_domain_rank"] or 0), reverse=True)
    return out


def build_overview(
    rank_overview: Optional[dict],
    bulk_traffic: Optional[float],
    backlink_summary: Optional[dict],
) -> dict:
    """Merge the Labs domain overview, a bulk-traffic estimate, and the backlink
    summary (DR/RD) into one rollup. Each source degrades independently. Pure."""
    ro = rank_overview or {}
    bl = backlink_summary or {}
    traffic = ro.get("organic_traffic_est")
    if traffic is None:
        traffic = bulk_traffic
    return {
        "organic_traffic_est": traffic,
        "ranked_keyword_count": ro.get("ranked_keyword_count"),
        "traffic_value_est": ro.get("traffic_value_est"),
        "dr": bl.get("rank") if bl.get("rank") is not None else bl.get("dr"),
        "rd": bl.get("referring_domains") if bl.get("referring_domains") is not None else bl.get("rd"),
    }


def is_snapshot_fresh(captured_at, now: Optional[datetime] = None) -> bool:
    """Whether a stored snapshot is within the module's cache window. Pure given
    ``now``. A fresh snapshot is re-served instead of re-billing DataForSEO."""
    hours = settings.domain_intel_cache_hours
    if hours <= 0 or not captured_at:
        return False
    try:
        cap = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if cap.tzinfo is None:
        cap = cap.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - cap) <= timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Budget guard (I/O) — mirrors backlink_explorer's daily meter.
# ---------------------------------------------------------------------------
def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid Labs calls left in today's budget (a large number when disabled)."""
    cap = settings.domain_intel_daily_call_budget
    if cap <= 0:
        return 10 ** 9
    try:
        rows = get_supabase().table("domain_intel_usage").select("calls").eq("day", _today()).limit(1).execute().data
    except Exception:
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def reserve_budget(n: int) -> None:
    """Reserve ``n`` paid Labs calls against today's budget, or raise
    BudgetExceeded. Atomic via the reserve_domain_intel_calls RPC (single
    check-and-increment). An RPC failure is fail-open (accounting never blocks
    work) — mirrors backlink_explorer._reserve_budget."""
    cap = settings.domain_intel_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_domain_intel_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:
        logger.warning("domain_intel_budget_accounting_failed", extra={"error": str(exc)})
        return
    if fit is False:
        raise BudgetExceeded(f"domain_intel_budget_exceeded: cap {cap} reached today")


# ---------------------------------------------------------------------------
# Orchestration (I/O) — Phase 1: Domain Overview + Ranked Keywords.
# ---------------------------------------------------------------------------
def _client_location_code(client_id: str) -> Optional[int]:
    """The client's rank-tracking location (§10 open question #1 default), or None."""
    try:
        rows = (
            get_supabase().table("clients").select("rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception:
        return None
    return (rows or [{}])[0].get("rank_tracking_location_code")


async def run_domain_overview(
    client_id: str,
    target_domain: str,
    role: str = "competitor",
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    *,
    force: bool = False,
) -> dict:
    """Fetch + persist a Domain Overview snapshot (rollups + ranked keywords).

    A fresh snapshot within the cache window is re-served (no paid call) unless
    ``force``. Otherwise reserves budget, calls the Labs overview + ranked
    keywords + the backlink summary (DR/RD), and persists a snapshot with its
    ranked-keyword child rows."""
    domain = normalize_domain(target_domain)
    if not domain:
        raise ValueError("invalid_domain")
    supabase = get_supabase()
    if location_code is None:
        location_code = _client_location_code(client_id)

    if not force:
        existing = (
            supabase.table("domain_intel_snapshots").select("id, captured_at")
            .eq("client_id", client_id).eq("target_domain", domain)
            .order("captured_at", desc=True).limit(1).execute()
        ).data
        if existing and is_snapshot_fresh(existing[0]["captured_at"]):
            return {"snapshot_id": existing[0]["id"], "target_domain": domain, "cached": True}

    # Budget: overview + ranked_keywords + backlink summary (+ optional bulk).
    reserve_budget(3)

    overview_raw, c_overview = await dataforseo_labs.fetch_domain_rank_overview(
        domain, location_code, language_code
    )
    ranked_raw, c_ranked = await dataforseo_labs.fetch_ranked_keywords(
        domain, location_code, language_code,
        limit=settings.domain_intel_ranked_keyword_cap, max_position=100,
    )
    try:
        summary = await backlinks_api.fetch_summary(domain, "domain")
    except Exception as exc:
        logger.warning("domain_intel.backlink_summary_failed", extra={"domain": domain, "error": str(exc)})
        summary = {}

    bulk_traffic = None
    if overview_raw.get("organic_traffic_est") is None:
        try:
            reserve_budget(1)
            bulk_map, _c = await dataforseo_labs.fetch_bulk_traffic([domain], location_code, language_code)
            bulk_traffic = bulk_map.get(domain)
        except BudgetExceeded:
            pass  # traffic estimate is best-effort; the snapshot still stands

    overview = build_overview(
        overview_raw, bulk_traffic,
        {"dr": summary.get("domain_rating"), "rd": summary.get("referring_domains")},
    )
    ranked = enrich_est_value(ranked_raw)
    cost = round((c_overview or 0.0) + (c_ranked or 0.0), 4)

    snap = (
        supabase.table("domain_intel_snapshots").insert({
            "client_id": client_id, "target_domain": domain, "role": role,
            "location_code": location_code, "language_code": language_code or "en",
            "organic_traffic_est": overview["organic_traffic_est"],
            "ranked_keyword_count": overview["ranked_keyword_count"] or len(ranked),
            "dr": overview["dr"], "rd": overview["rd"],
            "traffic_value_est": overview["traffic_value_est"],
            "status": "complete", "cost_usd": cost,
        }).execute()
    ).data[0]

    rows = [{
        "snapshot_id": snap["id"], "keyword": r["keyword"], "position": r.get("position"),
        "url": r.get("url"), "volume": r.get("volume"), "cpc_usd": r.get("cpc_usd"),
        "keyword_difficulty": r.get("keyword_difficulty"), "search_intent": r.get("search_intent"),
        "est_value": r.get("est_value"),
    } for r in ranked]
    for group in dataforseo_labs.chunk(rows, 500):
        if group:
            supabase.table("domain_ranked_keywords").insert(group).execute()

    return {
        "snapshot_id": snap["id"], "target_domain": domain, "cached": False,
        "ranked_keyword_count": len(rows), "cost_usd": cost,
    }


def enqueue_domain_overview(
    client_id: str,
    target_domain: str,
    role: str = "competitor",
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
    force: bool = False,
) -> str:
    """Enqueue a domain_overview async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "domain_overview",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "target_domain": target_domain, "role": role,
                "location_code": location_code, "language_code": language_code, "force": force,
            },
        }).execute()
    ).data[0]
    return row["id"]


async def run_domain_overview_job(job: dict) -> None:
    """async_jobs handler for domain_overview."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_domain_overview(
            payload.get("client_id") or job.get("entity_id"),
            payload.get("target_domain"),
            role=payload.get("role") or "competitor",
            location_code=payload.get("location_code"),
            language_code=payload.get("language_code"),
            force=bool(payload.get("force")),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning("domain_overview.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


# ---------------------------------------------------------------------------
# Reads (for the router).
# ---------------------------------------------------------------------------
def get_latest_overview(client_id: str, target_domain: str) -> Optional[dict]:
    """The most recent snapshot for (client, domain) + its ranked keywords, or None."""
    domain = normalize_domain(target_domain)
    if not domain:
        return None
    supabase = get_supabase()
    snap = (
        supabase.table("domain_intel_snapshots").select("*")
        .eq("client_id", client_id).eq("target_domain", domain)
        .order("captured_at", desc=True).limit(1).execute()
    ).data
    if not snap:
        return None
    kws = (
        supabase.table("domain_ranked_keywords").select("*")
        .eq("snapshot_id", snap[0]["id"])
        .order("est_value", desc=True).limit(settings.domain_intel_ranked_keyword_cap).execute()
    ).data or []
    return {"snapshot": snap[0], "ranked_keywords": kws}


def list_snapshots(client_id: str, limit: int = 50) -> list[dict]:
    """Snapshot summary rows for a client (no child keywords), newest first."""
    return (
        get_supabase().table("domain_intel_snapshots")
        .select("id, target_domain, role, organic_traffic_est, ranked_keyword_count, "
                "dr, rd, traffic_value_est, cost_usd, captured_at")
        .eq("client_id", client_id).order("captured_at", desc=True).limit(limit).execute()
    ).data or []


# ---------------------------------------------------------------------------
# Orchestration (I/O) — Phase 2: Keyword Gap.
# ---------------------------------------------------------------------------
def _client_domain(client_id: str) -> Optional[str]:
    try:
        rows = (
            get_supabase().table("clients").select("website_url")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception:
        return None
    return normalize_domain((rows or [{}])[0].get("website_url"))


def resolve_competitor_domains(client_id: str, explicit: Optional[list[str]] = None) -> list[str]:
    """The competitor domain set for a gap run: an explicit list if given, else
    the client's registered competitors (active, with a domain), capped."""
    if explicit:
        seen: list[str] = []
        for d in explicit:
            nd = normalize_domain(d)
            if nd and nd not in seen:
                seen.append(nd)
        return seen[: settings.domain_intel_gap_max_competitors]
    try:
        rows = (
            get_supabase().table("client_competitors").select("domain, active")
            .eq("client_id", client_id).eq("active", True).execute()
        ).data or []
    except Exception:
        rows = []
    out: list[str] = []
    for r in rows:
        nd = normalize_domain(r.get("domain"))
        if nd and nd not in out:
            out.append(nd)
    return out[: settings.domain_intel_gap_max_competitors]


async def run_keyword_gap(
    client_id: str,
    competitor_domains: Optional[list[str]] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> dict:
    """Compute + persist the client's keyword gaps vs a competitor set.

    Fetches the client's ranked keywords once + each competitor's, computes the
    per-competitor gaps (pure), merges to one best-per-keyword list, and replaces
    the client's stored gap rows with it. Returns a summary."""
    client_domain = _client_domain(client_id)
    if not client_domain:
        raise ValueError("client_domain_unknown")
    competitors = resolve_competitor_domains(client_id, competitor_domains)
    if not competitors:
        return {"gap_count": 0, "competitors": [], "client_domain": client_domain, "note": "no_competitors"}
    if location_code is None:
        location_code = _client_location_code(client_id)

    reserve_budget(1 + len(competitors))
    supabase = get_supabase()

    client_rows, _c = await dataforseo_labs.fetch_ranked_keywords(
        client_domain, location_code, language_code,
        limit=settings.domain_intel_ranked_keyword_cap, max_position=100,
    )
    gap_lists: list[list[dict]] = []
    used: list[str] = []
    for comp in competitors:
        try:
            comp_rows, _cc = await dataforseo_labs.fetch_ranked_keywords(
                comp, location_code, language_code,
                limit=settings.domain_intel_ranked_keyword_cap, max_position=100,
            )
        except Exception as exc:
            logger.warning("keyword_gap.competitor_fetch_failed", extra={"domain": comp, "error": str(exc)})
            continue
        gap_lists.append(compute_keyword_gap(comp_rows, client_rows, comp))
        used.append(comp)

    merged = merge_keyword_gaps(gap_lists)[: settings.domain_intel_ranked_keyword_cap]

    # Replace the client's stored gap set with this run's.
    try:
        supabase.table("domain_keyword_gaps").delete().eq("client_id", client_id).execute()
    except Exception as exc:
        logger.warning("keyword_gap.clear_failed", extra={"client_id": client_id, "error": str(exc)})
    rows = [{
        "client_id": client_id, "keyword": g["keyword"],
        "competitor_domain": g.get("competitor_domain"),
        "competitor_position": g.get("competitor_position"),
        "client_position": g.get("client_position"),
        "volume": g.get("volume"), "cpc_usd": g.get("cpc_usd"),
        "keyword_difficulty": g.get("keyword_difficulty"),
        "gap_type": g.get("gap_type"), "opportunity_score": g.get("opportunity_score"),
    } for g in merged]
    for group in dataforseo_labs.chunk(rows, 500):
        if group:
            supabase.table("domain_keyword_gaps").insert(group).execute()

    return {"gap_count": len(rows), "competitors": used, "client_domain": client_domain}


def enqueue_keyword_gap(
    client_id: str,
    competitor_domains: Optional[list[str]] = None,
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> str:
    """Enqueue a keyword_gap async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "keyword_gap",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "competitor_domains": competitor_domains,
                "location_code": location_code, "language_code": language_code,
            },
        }).execute()
    ).data[0]
    return row["id"]


async def run_keyword_gap_job(job: dict) -> None:
    """async_jobs handler for keyword_gap."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_keyword_gap(
            payload.get("client_id") or job.get("entity_id"),
            competitor_domains=payload.get("competitor_domains"),
            location_code=payload.get("location_code"),
            language_code=payload.get("language_code"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning("keyword_gap.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def get_keyword_gaps(client_id: str, limit: Optional[int] = None) -> dict:
    """The client's current keyword-gap set (latest run), ordered by opportunity."""
    cap = limit or settings.domain_intel_ranked_keyword_cap
    rows = (
        get_supabase().table("domain_keyword_gaps").select("*")
        .eq("client_id", client_id)
        .order("opportunity_score", desc=True).limit(cap).execute()
    ).data or []
    captured_at = max((r.get("captured_at") for r in rows if r.get("captured_at")), default=None)
    return {"gaps": rows, "captured_at": captured_at, "count": len(rows)}


# ---------------------------------------------------------------------------
# Orchestration (I/O) — Phase 3: Backlink Gap + competitor discovery.
# ---------------------------------------------------------------------------
def _rd_rows_for_gap(referring_rows: list[dict]) -> list[dict]:
    """Map backlinks_api.parse_referring_domains rows to compute_link_gap's shape
    ({domain, rank, backlinks}). The suite's DR proxy is `domain_rating` (0–100)."""
    return [
        {"domain": r.get("domain"), "rank": r.get("domain_rating"), "backlinks": r.get("backlinks")}
        for r in referring_rows if r.get("domain")
    ]


async def run_link_gap(
    client_id: str,
    competitor_domains: Optional[list[str]] = None,
) -> dict:
    """Compute + persist referring domains linking to the client's competitors but
    not the client. Fetches each domain's referring-domain list (backlinks_api),
    runs the pure compute_link_gap, and replaces the client's stored link-gap set."""
    client_domain = _client_domain(client_id)
    if not client_domain:
        raise ValueError("client_domain_unknown")
    competitors = resolve_competitor_domains(client_id, competitor_domains)
    if not competitors:
        return {"gap_count": 0, "competitors": [], "client_domain": client_domain, "note": "no_competitors"}

    reserve_budget(1 + len(competitors))
    supabase = get_supabase()
    limit = settings.backlink_referring_domains_limit

    client_rd = await backlinks_api.fetch_referring_domains(client_domain, "domain", limit=limit)
    client_domains = [r.get("domain") for r in client_rd if r.get("domain")]

    competitor_referring: dict[str, list[dict]] = {}
    used: list[str] = []
    for comp in competitors:
        try:
            rd = await backlinks_api.fetch_referring_domains(comp, "domain", limit=limit)
        except Exception as exc:
            logger.warning("link_gap.competitor_fetch_failed", extra={"domain": comp, "error": str(exc)})
            continue
        competitor_referring[comp] = _rd_rows_for_gap(rd)
        used.append(comp)

    gaps = compute_link_gap(competitor_referring, client_domains)[: settings.domain_intel_ranked_keyword_cap]

    try:
        supabase.table("domain_link_gaps").delete().eq("client_id", client_id).execute()
    except Exception as exc:
        logger.warning("link_gap.clear_failed", extra={"client_id": client_id, "error": str(exc)})
    rows = [{
        "client_id": client_id, "referring_domain": g["referring_domain"],
        "linking_to": g.get("linking_to") or [],
        "referring_domain_rank": g.get("referring_domain_rank"),
        "backlink_count": g.get("backlink_count"),
    } for g in gaps]
    for group in dataforseo_labs.chunk(rows, 500):
        if group:
            supabase.table("domain_link_gaps").insert(group).execute()

    return {"gap_count": len(rows), "competitors": used, "client_domain": client_domain}


def enqueue_link_gap(client_id: str, competitor_domains: Optional[list[str]] = None) -> str:
    """Enqueue a link_gap async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "link_gap",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "competitor_domains": competitor_domains},
        }).execute()
    ).data[0]
    return row["id"]


async def run_link_gap_job(job: dict) -> None:
    """async_jobs handler for link_gap."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_link_gap(
            payload.get("client_id") or job.get("entity_id"),
            competitor_domains=payload.get("competitor_domains"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning("link_gap.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def get_link_gaps(client_id: str, limit: Optional[int] = None) -> dict:
    """The client's current backlink-gap set (latest run), strongest first."""
    cap = limit or settings.domain_intel_ranked_keyword_cap
    rows = (
        get_supabase().table("domain_link_gaps").select("*")
        .eq("client_id", client_id)
        .order("referring_domain_rank", desc=True).limit(cap).execute()
    ).data or []
    captured_at = max((r.get("captured_at") for r in rows if r.get("captured_at")), default=None)
    return {"gaps": rows, "captured_at": captured_at, "count": len(rows)}


async def discover_competitors(
    client_id: str, location_code: Optional[int] = None, language_code: Optional[str] = None
) -> dict:
    """SERP-overlap competitor suggestions for the client's own domain (Labs
    competitors_domain). Marks which are already in the registry. One paid call."""
    client_domain = _client_domain(client_id)
    if not client_domain:
        return {"client_domain": None, "suggestions": [], "note": "client_domain_unknown"}
    if location_code is None:
        location_code = _client_location_code(client_id)
    reserve_budget(1)
    rows, _cost = await dataforseo_labs.fetch_competitors_domain(client_domain, location_code, language_code)

    try:
        existing = {
            normalize_domain(r.get("domain"))
            for r in (
                get_supabase().table("client_competitors").select("domain")
                .eq("client_id", client_id).execute()
            ).data or []
        }
    except Exception:
        existing = set()

    suggestions = []
    for r in rows:
        dom = r.get("domain")
        if not dom or dom == client_domain:
            continue
        suggestions.append({**r, "registered": dom in existing})
    return {"client_domain": client_domain, "suggestions": suggestions}
