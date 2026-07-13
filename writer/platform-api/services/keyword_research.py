"""Keyword Research — the seed-keyword explorer.

Enter seed keyword(s) for a client → the DataForSEO Labs ``keyword_ideas``
endpoint returns the related keyword universe, each idea already enriched with
search volume / CPC / competition / keyword difficulty / search intent (one
billed call — no follow-up keyword_overview batch). The ideas are then
auto-clustered into topic groups and persisted as a research run so the view is
a cheap re-read and the CSV export is deterministic.

This is a research tool, NOT a content generator — it replaces the old
"Keyword Research" workspace card that pointed at the Topic Fanout (a
mass-content pipeline). The Fanout stays behind the "Create Mass Posts" card.

Design mirrors services/domain_intel.py: the clustering / scoring math here is
PURE (no I/O) and independently unit-tested; the heavy read is a paid Labs call
guarded by a daily budget meter (keyword_research_usage) + persisted to a run so
re-opening a run never re-bills.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_labs

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a paid Labs call would exceed the module's daily budget."""


_RUNS_KEEP = 25  # research runs retained per client (child rows cascade-delete)

# Common English function words + generic connectors dropped before clustering,
# so topic groups form around meaningful head terms, not "for"/"the"/"near".
_STOPWORDS = frozenset({
    "a", "an", "and", "or", "the", "of", "for", "to", "in", "on", "at", "by",
    "with", "from", "near", "vs", "is", "are", "my", "your", "you", "me", "i",
    "it", "its", "this", "that", "best", "top", "get", "do", "does",
})
# Leading tokens that mark a question keyword (used for the is_question tag and
# to keep question phrasing out of the cluster head where a noun is better).
_QUESTION_LEADS = frozenset({
    "how", "what", "why", "when", "where", "which", "who", "whom", "whose",
    "can", "could", "should", "will", "would", "is", "are", "do", "does",
})
_INTENT_WEIGHT = {
    "transactional": 1.0,
    "commercial": 0.9,
    "informational": 0.6,
    "navigational": 0.5,
}


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def normalize_keyword(keyword: Optional[str]) -> str:
    """Lower-cased, whitespace-collapsed keyword. Pure."""
    return re.sub(r"\s+", " ", (keyword or "").strip().lower())


def tokenize(keyword: str) -> list[str]:
    """Significant tokens of a keyword: lower-cased alphanumeric words, minus
    stopwords, length ≥ 2. Preserves order. Pure."""
    words = re.findall(r"[a-z0-9]+", normalize_keyword(keyword))
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def is_question(keyword: str) -> bool:
    """Whether a keyword reads as a question (leads with an interrogative or
    ends with '?'). Pure — used to tag question keywords for the view/export."""
    kw = normalize_keyword(keyword)
    if not kw:
        return False
    if kw.endswith("?"):
        return True
    first = re.findall(r"[a-z0-9]+", kw)
    return bool(first) and first[0] in _QUESTION_LEADS


def opportunity_score(
    volume: Optional[int],
    cpc: Optional[float],
    keyword_difficulty: Optional[float],
    search_intent: Optional[str],
) -> float:
    """A ranked-opportunity score for a research keyword. Higher = pursue first.

    value (volume × CPC) × ease (low KD) × intent weight (commercial/transactional
    worth more than informational). Deterministic and monotonic in each input so
    the view/export can sort on it. Pure."""
    value = (volume or 0) * (cpc or 0.0)
    kd = keyword_difficulty if keyword_difficulty is not None else 50.0
    ease = max(0.0, min(100.0, 100.0 - kd)) / 100.0
    weight = _INTENT_WEIGHT.get((search_intent or "").lower(), 0.7)
    return round(value * ease * weight, 2)


def build_research_rows(idea_rows: list[dict]) -> list[dict]:
    """Dedupe + enrich raw Labs idea rows into stored research rows.

    Keeps the highest-volume instance per normalized keyword, and attaches the
    is_question tag + opportunity_score. Sorted by opportunity_score desc. Pure."""
    best: dict[str, dict] = {}
    for r in idea_rows:
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        key = normalize_keyword(kw)
        cur = best.get(key)
        if cur is not None and (r.get("volume") or 0) <= (cur.get("volume") or 0):
            continue
        best[key] = {
            "keyword": kw,
            "volume": r.get("volume"),
            "cpc_usd": r.get("cpc_usd"),
            "competition_index": r.get("competition_index"),
            "keyword_difficulty": r.get("keyword_difficulty"),
            "search_intent": r.get("search_intent"),
            "is_question": is_question(kw),
            "opportunity_score": opportunity_score(
                r.get("volume"), r.get("cpc_usd"),
                r.get("keyword_difficulty"), r.get("search_intent"),
            ),
        }
    rows = list(best.values())
    rows.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return rows


def cluster_keywords(rows: list[dict]) -> list[dict]:
    """Group research rows into topic clusters by their dominant shared token.

    Deterministic, no-LLM lexical clustering: the "head" of a keyword is its
    most globally-frequent significant token (ties → the earliest token in the
    keyword, i.e. its head noun), which is the topic hub the keyword belongs
    under. Preferring the earliest token on a tie keeps a shared city/qualifier
    from hijacking the cluster of "<service> <city>" queries — the service wins.
    Keywords sharing a head land in one cluster labelled by that token. Keywords
    with no significant token (e.g. a bare brand acronym) fall into "other".

    Returns clusters sorted by total search volume desc; within a cluster,
    keywords by opportunity_score desc. Each cluster:
    {label, keyword_count, total_volume, keywords: [keyword, ...]}. Pure."""
    # Global document frequency of each significant token.
    freq: dict[str, int] = {}
    token_cache: dict[int, list[str]] = {}
    for i, r in enumerate(rows):
        toks = tokenize(r.get("keyword") or "")
        token_cache[i] = toks
        for t in set(toks):
            freq[t] = freq.get(t, 0) + 1

    def head_of(toks: list[str]) -> str:
        if not toks:
            return "other"
        # Most globally-frequent token; on a tie the earliest (head) token wins,
        # so a shared city can't outrank the service. Fully deterministic.
        best, best_freq = toks[0], freq.get(toks[0], 0)
        for t in toks[1:]:
            f = freq.get(t, 0)
            if f > best_freq:
                best, best_freq = t, f
        return best

    grouped: dict[str, list[dict]] = {}
    for i, r in enumerate(rows):
        label = head_of(token_cache[i])
        grouped.setdefault(label, []).append(r)

    clusters: list[dict] = []
    for label, members in grouped.items():
        members_sorted = sorted(
            members, key=lambda x: x.get("opportunity_score") or 0, reverse=True
        )
        clusters.append({
            "label": label,
            "keyword_count": len(members_sorted),
            "total_volume": sum((m.get("volume") or 0) for m in members_sorted),
            "keywords": [m["keyword"] for m in members_sorted],
        })
    clusters.sort(key=lambda c: (c["total_volume"], c["keyword_count"]), reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Budget guard (I/O) — mirrors domain_intel's daily meter.
# ---------------------------------------------------------------------------
def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid Labs calls left in today's budget (a large number when disabled)."""
    cap = settings.keyword_research_daily_call_budget
    if cap <= 0:
        return 10 ** 9
    try:
        rows = (
            get_supabase().table("keyword_research_usage").select("calls")
            .eq("day", _today()).limit(1).execute()
        ).data
    except Exception:
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def reserve_budget(n: int) -> None:
    """Reserve ``n`` paid Labs calls against today's budget, or raise
    BudgetExceeded. Atomic via the reserve_keyword_research_calls RPC. An RPC
    failure is fail-open (accounting never blocks work)."""
    cap = settings.keyword_research_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_keyword_research_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:
        logger.warning("keyword_research_budget_accounting_failed", extra={"error": str(exc)})
        return
    if fit is False:
        raise BudgetExceeded(f"keyword_research_budget_exceeded: cap {cap} reached today")


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
def parse_seeds(raw) -> list[str]:
    """Normalize a seed payload (a string or list) into a deduped seed list.
    Splits a string on newlines/commas. Pure."""
    if isinstance(raw, str):
        parts = re.split(r"[\n,]+", raw)
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            parts.extend(re.split(r"[\n,]+", str(item)))
    else:
        return []
    seen: list[str] = []
    lowered: set[str] = set()
    for p in parts:
        s = p.strip()
        if s and s.lower() not in lowered:
            lowered.add(s.lower())
            seen.append(s)
    return seen[: settings.keyword_research_max_seeds]


def _client_location_code(client_id: str) -> Optional[int]:
    try:
        rows = (
            get_supabase().table("clients").select("rank_tracking_location_code")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception:
        return None
    return (rows or [{}])[0].get("rank_tracking_location_code")


async def run_keyword_research(
    client_id: str,
    seeds: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> dict:
    """Fetch + persist a keyword research run for a seed set.

    Reserves budget, calls Labs keyword_ideas, dedupes/enriches/clusters (pure),
    and persists a run row with its child keyword rows. Returns a summary."""
    seed_list = seeds[: settings.keyword_research_max_seeds]
    if not seed_list:
        raise ValueError("no_seeds")
    supabase = get_supabase()
    if location_code is None:
        location_code = _client_location_code(client_id)

    reserve_budget(1)
    idea_rows, cost = await dataforseo_labs.fetch_keyword_ideas(
        seed_list, location_code, language_code,
        limit=settings.keyword_research_idea_limit,
    )
    rows = build_research_rows(idea_rows)
    clusters = cluster_keywords(rows)
    label_for = {kw: c["label"] for c in clusters for kw in c["keywords"]}

    run = (
        supabase.table("keyword_research_runs").insert({
            "client_id": client_id,
            "seeds": seed_list,
            "location_code": location_code,
            "language_code": language_code or "en",
            "keyword_count": len(rows),
            "cluster_count": len(clusters),
            "status": "complete",
            "cost_usd": round(cost or 0.0, 4),
        }).execute()
    ).data[0]

    child = [{
        "run_id": run["id"],
        "keyword": r["keyword"],
        "cluster_label": label_for.get(r["keyword"]),
        "volume": r.get("volume"),
        "cpc_usd": r.get("cpc_usd"),
        "competition_index": r.get("competition_index"),
        "keyword_difficulty": r.get("keyword_difficulty"),
        "search_intent": r.get("search_intent"),
        "is_question": r.get("is_question"),
        "opportunity_score": r.get("opportunity_score"),
    } for r in rows]
    for group in dataforseo_labs.chunk(child, 500):
        if group:
            supabase.table("keyword_research_keywords").insert(group).execute()

    _prune_runs(client_id)
    return {
        "run_id": run["id"], "keyword_count": len(rows),
        "cluster_count": len(clusters), "cost_usd": round(cost or 0.0, 4),
    }


def _prune_runs(client_id: str) -> None:
    """Keep the newest _RUNS_KEEP runs per client (child rows cascade). Best-effort."""
    try:
        supabase = get_supabase()
        old = (
            supabase.table("keyword_research_runs").select("id")
            .eq("client_id", client_id).order("created_at", desc=True).execute()
        ).data or []
        stale = [r["id"] for r in old[_RUNS_KEEP:]]
        if stale:
            supabase.table("keyword_research_runs").delete().in_("id", stale).execute()
    except Exception as exc:
        logger.warning("keyword_research.prune_failed", extra={"client_id": client_id, "error": str(exc)})


def enqueue_keyword_research(
    client_id: str,
    seeds: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> str:
    """Enqueue a keyword_research async job. Returns the job id."""
    row = (
        get_supabase().table("async_jobs").insert({
            "job_type": "keyword_research",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id, "seeds": seeds,
                "location_code": location_code, "language_code": language_code,
            },
        }).execute()
    ).data[0]
    return row["id"]


async def run_keyword_research_job(job: dict) -> None:
    """async_jobs handler for keyword_research."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_keyword_research(
            payload.get("client_id") or job.get("entity_id"),
            payload.get("seeds") or [],
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
        logger.warning("keyword_research.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


# ---------------------------------------------------------------------------
# Reads (for the router).
# ---------------------------------------------------------------------------
def list_runs(client_id: str, limit: int = 25) -> list[dict]:
    """Research-run summary rows for a client (no child keywords), newest first."""
    return (
        get_supabase().table("keyword_research_runs")
        .select("id, seeds, location_code, language_code, keyword_count, "
                "cluster_count, cost_usd, status, created_at")
        .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []


def get_run(client_id: str, run_id: str) -> Optional[dict]:
    """A run + its keywords + rebuilt clusters, or None. Scoped to the client."""
    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs").select("*")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        return None
    kws = (
        supabase.table("keyword_research_keywords").select("*")
        .eq("run_id", run_id)
        .order("opportunity_score", desc=True)
        .limit(settings.keyword_research_idea_limit).execute()
    ).data or []
    clusters = _clusters_from_rows(kws)
    return {"run": runs[0], "keywords": kws, "clusters": clusters}


def _clusters_from_rows(kws: list[dict]) -> list[dict]:
    """Rebuild the cluster summary from stored keyword rows (they carry
    cluster_label), sorted by total volume desc. Pure over the DB read."""
    grouped: dict[str, list[dict]] = {}
    for k in kws:
        grouped.setdefault(k.get("cluster_label") or "other", []).append(k)
    clusters = [{
        "label": label,
        "keyword_count": len(members),
        "total_volume": sum((m.get("volume") or 0) for m in members),
    } for label, members in grouped.items()]
    clusters.sort(key=lambda c: (c["total_volume"], c["keyword_count"]), reverse=True)
    return clusters
