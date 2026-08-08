"""Keyword Research — problem-first Topic Research.

The keyword-expansion pipeline (services/keyword_research.py) researches the SEED
and its variations. For a service seed like "third party claims administrator"
that returns variations of the SERVICE NAME (TPA companies, claims software) — not
the topics a buyer actually searches, because the buyer searches their PROBLEM in
words that never contain the service name ("reducing claims leakage", "catastrophe
surge staffing", "nuclear verdicts").

This module flips the approach to do genuine TOPIC research, from three sources
(owner-chosen):

  1. PROBLEM-FIRST — an LLM derives the buyer's problems / jobs-to-be-done from the
     client's ICP + differentiators + the themes already on their own site, and
     turns each into a blog-worthy topic angle. (Not seed variations.)
  2. REAL DEMAND — each theme is validated with a live SERP: People Also Ask
     questions + phrase-containment suggestions on the theme (volume-enriched), so
     a topic is grounded in what people actually search, not just an LLM guess.
  3. COMPETITOR MINING — the informational keywords the top competitors in those
     SERPs actually rank for (audience-filtered), surfacing proven topics + a
     content gap.

Output is a ranked set of TOPIC CARDS (theme + buyer problem + a suggested title +
supporting keywords/volume + real questions + competitor coverage), stored on a
keyword_topic_research_runs row. Pure assembly/scoring is unit-tested; the SERP /
Labs / LLM calls are the I/O and are all best-effort.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import (
    dataforseo_labs,
    keyword_research,
    keyword_research_audience,
    keyword_research_seeds,
    keyword_research_topics,
)

logger = logging.getLogger(__name__)

_SERP_CALL_COST = 0.002
_RANKED_CALL_COST = 0.02


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def aggregate_competitor_domains(
    per_theme_organic: list[list[dict]],
    client_domain: Optional[str],
    *,
    top_n: int,
) -> list[str]:
    """The domains appearing most across the theme SERPs, excluding the client and
    obvious non-competitors (directories/aggregators are kept — they still signal
    demand, but the caller can ignore them). Ordered by appearances desc. Pure."""
    counts: dict[str, int] = {}
    cd = (client_domain or "").lower().lstrip("www.")
    for organic in per_theme_organic:
        seen: set[str] = set()
        for r in organic or []:
            dom = (r.get("domain") or "").lower().lstrip("www.")
            if not dom or dom == cd or dom in seen:
                continue
            seen.add(dom)
            counts[dom] = counts.get(dom, 0) + 1
    return [d for d, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)][:top_n]


def topic_priority(volume_total: int, question_count: int, competitor_count: int) -> float:
    """A 0..1-ish priority for a topic: real search demand + questions asked +
    competitor validation. Monotonic in each. Pure."""
    import math
    demand = math.log1p(max(0, volume_total)) / math.log1p(50000)   # 0..~1
    questions = min(1.0, question_count / 8.0)
    competition = min(1.0, competitor_count / 3.0)
    return round(0.6 * demand + 0.25 * questions + 0.15 * competition, 3)


def build_topic_card(
    theme: dict,
    suggestions: list[dict],
    questions: list[str],
    competitor_examples: list[str],
    *,
    keyword_cap: int = 12,
    question_cap: int = 8,
) -> dict:
    """Assemble one topic card from a theme + its mined demand. Drops job-seeker
    keywords from the supporting set, keeps the highest-volume buyer keywords, and
    scores priority. Pure."""
    buyer_kw = [
        s for s in suggestions
        if s.get("keyword") and not keyword_research_audience.is_job_seeker(s.get("keyword"))
    ]
    buyer_kw.sort(key=lambda s: (s.get("volume") or 0), reverse=True)
    top_kw = [{"keyword": s["keyword"], "volume": s.get("volume")} for s in buyer_kw[:keyword_cap]]
    volume_total = sum((s.get("volume") or 0) for s in buyer_kw)
    q = [x for x in questions if x][:question_cap]
    return {
        "theme": theme.get("theme"),
        "problem": theme.get("problem"),
        "title": theme.get("title") or theme.get("theme"),
        "supporting_keywords": top_kw,
        "questions": q,
        "competitor_examples": competitor_examples[:6],
        "volume_total": volume_total,
        "priority": topic_priority(volume_total, len(q), len(competitor_examples)),
    }


def rank_topics(cards: list[dict]) -> list[dict]:
    """Topic cards sorted by priority desc, dropping empties (no keywords AND no
    questions — nothing to write from). Pure."""
    live = [c for c in cards if (c.get("supporting_keywords") or c.get("questions"))]
    return sorted(live, key=lambda c: c.get("priority") or 0, reverse=True)


# ---------------------------------------------------------------------------
# Problem-theme generation (LLM).
# ---------------------------------------------------------------------------
_THEME_SYSTEM = (
    "You are a B2B content strategist. Given a business's ideal customer (ICP), "
    "its differentiators, and the topics already on its site, identify the buyer's "
    "core PROBLEMS and jobs-to-be-done, and turn each into a blog-worthy topic the "
    "business should own. Think about what the BUYER searches when they have the "
    "problem — which is usually NOT the business's service name."
)
_THEME_TOOL = {
    "name": "emit_themes",
    "description": "Return the buyer's problem-driven blog topic themes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string", "description": "Short topic label (2-5 words)."},
                        "problem": {"type": "string", "description": "The buyer problem it addresses, one line."},
                        "title": {"type": "string", "description": "A compelling blog post title."},
                        "search_query": {"type": "string", "description": "A 2-4 word phrase the buyer would SEARCH for this problem (NOT the business name) — used to find real demand."},
                    },
                    "required": ["theme", "problem", "search_query"],
                },
            }
        },
        "required": ["themes"],
    },
}


def _theme_prompt(context: str, site_topics: list[str], seeds: list[str], count: int) -> str:
    site_block = ("\n\nTopics already on the client's site (mine these for the buyer's "
                  "real angles):\n" + "\n".join(f"- {t}" for t in site_topics[:30])) if site_topics else ""
    seed_block = ("\n\nSeed terms the team is interested in:\n" + "\n".join(f"- {s}" for s in seeds)) if seeds else ""
    return (
        f"{context}{seed_block}{site_block}\n\n"
        f"Identify up to {count} problem-driven blog topics this business should own. "
        "For each: the topic, the buyer PROBLEM it solves, a compelling title, and a "
        "2-4 word phrase the buyer would actually SEARCH for that problem (not the "
        "business's service name).\n\n"
        "Rules:\n"
        "- Write for the BUYER (the ICP), not job-seekers, students, or DIY consumers.\n"
        "- The search_query must be a real query someone types — a problem/topic, not "
        "a brand or a bare service name.\n"
        "- Favor topics that demonstrate expertise and pull the buyer toward the service.\n"
        "- Return via the emit_themes tool."
    )


def generate_problem_themes(
    client: dict, seeds: list[str], site_topics: list[str]
) -> list[dict]:
    """LLM → problem-driven topic themes grounded on ICP + differentiators + site
    topics. Best-effort: [] when no LLM key / call fails."""
    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return []
    context = keyword_research_seeds.build_seed_context(client) or ""
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.keyword_topic_model,
            max_tokens=settings.keyword_topic_max_tokens,
            system=_THEME_SYSTEM,
            user=_theme_prompt(context, site_topics, seeds, settings.keyword_topic_max_themes),
            tool_name=_THEME_TOOL["name"],
            tool_description=_THEME_TOOL["description"],
            input_schema=_THEME_TOOL["input_schema"],
            log_tag="keyword_topic_research_themes",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("keyword_topic_research.themes_failed", extra={"error": str(exc)})
        return []
    themes: list[dict] = []
    seen: set[str] = set()
    for t in (result.get("themes") or []):
        if not isinstance(t, dict):
            continue
        label = str(t.get("theme") or "").strip()
        query = str(t.get("search_query") or "").strip()
        if not label or not query or label.lower() in seen:
            continue
        seen.add(label.lower())
        themes.append({
            "theme": label, "problem": str(t.get("problem") or "").strip(),
            "title": str(t.get("title") or "").strip(), "search_query": query,
        })
    return themes[: settings.keyword_topic_max_themes]


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
async def _mine_theme(theme: dict, location_code: int, language_code: str) -> dict:
    """One theme → its real demand: a SERP (PAA + top organic domains) + suggestions
    (volume-enriched keywords). Best-effort; returns a partial dict on any failure."""
    from services import serp_snapshot

    query = theme.get("search_query") or theme.get("theme")
    out = {"theme": theme, "organic": [], "questions": [], "suggestions": [], "cost": 0.0}
    # SERP → PAA + competitor domains.
    try:
        items = await serp_snapshot.fetch_serp(
            query, location_code, language_code, settings.keyword_topic_serp_depth)
        out["organic"] = serp_snapshot.extract_organic_results(items, settings.keyword_topic_serp_top)
        out["questions"] = serp_snapshot.extract_serp_features(items).get("people_also_ask") or []
        out["cost"] += _SERP_CALL_COST
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_research.serp_failed", extra={"query": query, "error": str(exc)})
    # Suggestions → keywords + volume.
    try:
        rows, cost = await dataforseo_labs.fetch_keyword_suggestions(
            query, location_code, language_code, limit=settings.keyword_topic_suggestion_limit)
        out["suggestions"] = rows
        out["cost"] += cost or 0.0
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_research.suggestions_failed", extra={"query": query, "error": str(exc)})
    return out


async def _mine_competitors(
    domains: list[str], location_code: int, language_code: str
) -> tuple[list[dict], float]:
    """Top competitor domains → their buyer-fit INFORMATIONAL ranked keywords (proven
    topics). Returns (competitor_blobs, cost). Best-effort per domain."""
    cost = 0.0
    out: list[dict] = []
    for dom in domains:
        try:
            rows, c = await dataforseo_labs.fetch_ranked_keywords(
                dom, location_code, language_code,
                limit=settings.keyword_topic_competitor_kw_limit, max_position=20)
            cost += c or 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyword_topic_research.ranked_failed", extra={"domain": dom, "error": str(exc)})
            continue
        info = [
            r for r in rows
            if (r.get("search_intent") or "").lower() == "informational"
            and r.get("keyword")
            and not keyword_research_audience.is_job_seeker(r.get("keyword"))
        ]
        info.sort(key=lambda r: (r.get("volume") or 0), reverse=True)
        out.append({
            "domain": dom,
            "informational_keywords": len(info),
            "sample": [{"keyword": r["keyword"], "volume": r.get("volume")}
                       for r in info[: settings.keyword_topic_competitor_sample]],
        })
    return out, cost


def _match_competitor_examples(theme: dict, competitors: list[dict]) -> list[str]:
    """Competitor keywords that share a token with the theme — 'competitors also
    cover this'. Pure over the competitor blobs."""
    theme_toks = keyword_research.token_set(theme.get("theme")) | keyword_research.token_set(theme.get("search_query"))
    if not theme_toks:
        return []
    out: list[str] = []
    for c in competitors:
        for s in c.get("sample") or []:
            kw = s.get("keyword")
            if kw and (keyword_research.token_set(kw) & theme_toks):
                out.append(f"{c['domain']}: {kw}")
    return out


async def run_topic_research(
    client_id: str,
    seeds: list[str],
    location_code: Optional[int] = None,
    language_code: Optional[str] = None,
) -> dict:
    """Problem-first topic research: themes → real demand (PAA + suggestions) →
    competitor mining → ranked topic cards, persisted to a run. Returns a summary."""
    supabase = get_supabase()
    ctx = keyword_research._client_context(client_id)
    if location_code is None:
        location_code = ctx.get("rank_tracking_location_code")
    loc = dataforseo_labs.labs_location_code(location_code)
    lang = language_code or settings.dataforseo_default_language_code

    # Client's own site themes (best-effort) ground the problem-first generation.
    site_topics, _ = await keyword_research_topics.discover_site_topics(ctx, location_code)
    themes = generate_problem_themes(ctx, seeds, site_topics)
    if not themes:
        # No LLM / no context → nothing to research problem-first.
        run = supabase.table("keyword_topic_research_runs").insert({
            "client_id": client_id, "seeds": seeds, "location_code": location_code,
            "language_code": lang, "status": "complete", "topic_count": 0,
            "topics": None, "competitors": None, "cost_usd": 0,
        }).execute().data[0]
        return {"run_id": run["id"], "topic_count": 0, "cost_usd": 0.0}

    # Budget: 1 SERP + 1 suggestions per theme + competitor ranked calls.
    n_themes = len(themes)
    keyword_research.reserve_budget(
        n_themes * 2 + settings.keyword_topic_max_competitors)

    mined = await asyncio.gather(*[_mine_theme(t, loc, lang) for t in themes])
    cost = sum(m.get("cost") or 0.0 for m in mined)

    client_domain = None
    website = ctx.get("website_url")
    if website:
        from services.dataforseo_rank import extract_domain
        client_domain = extract_domain(website) or None

    comp_domains = aggregate_competitor_domains(
        [m.get("organic") or [] for m in mined], client_domain,
        top_n=settings.keyword_topic_max_competitors)
    competitors, comp_cost = await _mine_competitors(comp_domains, loc, lang)
    cost += comp_cost

    cards = [
        build_topic_card(
            m["theme"], m.get("suggestions") or [], m.get("questions") or [],
            _match_competitor_examples(m["theme"], competitors),
        )
        for m in mined
    ]
    topics = rank_topics(cards)

    run = supabase.table("keyword_topic_research_runs").insert({
        "client_id": client_id, "seeds": seeds, "location_code": location_code,
        "language_code": lang, "status": "complete", "topic_count": len(topics),
        "topics": topics or None, "competitors": competitors or None,
        "cost_usd": round(cost, 4),
    }).execute().data[0]
    _prune_runs(client_id)
    return {"run_id": run["id"], "topic_count": len(topics), "cost_usd": round(cost, 4)}


_RUNS_KEEP = 25


def _prune_runs(client_id: str) -> None:
    try:
        supabase = get_supabase()
        old = (supabase.table("keyword_topic_research_runs").select("id")
               .eq("client_id", client_id).order("created_at", desc=True).execute()).data or []
        stale = [r["id"] for r in old[_RUNS_KEEP:]]
        if stale:
            supabase.table("keyword_topic_research_runs").delete().in_("id", stale).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_research.prune_failed", extra={"error": str(exc)})


def enqueue_topic_research(
    client_id: str, seeds: list[str],
    location_code: Optional[int] = None, language_code: Optional[str] = None,
) -> str:
    row = get_supabase().table("async_jobs").insert({
        "job_type": "keyword_topic_research", "entity_id": client_id,
        "payload": {"client_id": client_id, "seeds": seeds,
                    "location_code": location_code, "language_code": language_code},
    }).execute().data[0]
    return row["id"]


async def run_topic_research_job(job: dict) -> None:
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await run_topic_research(
            payload.get("client_id") or job.get("entity_id"),
            payload.get("seeds") or [],
            location_code=payload.get("location_code"),
            language_code=payload.get("language_code"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except keyword_research.BudgetExceeded:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_research.job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def list_runs(client_id: str, limit: int = 25) -> list[dict]:
    return (get_supabase().table("keyword_topic_research_runs")
            .select("id, seeds, topic_count, cost_usd, status, created_at")
            .eq("client_id", client_id).order("created_at", desc=True).limit(limit).execute()).data or []


def get_run(client_id: str, run_id: str) -> Optional[dict]:
    rows = (get_supabase().table("keyword_topic_research_runs").select("*")
            .eq("id", run_id).eq("client_id", client_id).limit(1).execute()).data
    return rows[0] if rows else None


def latest_run(client_id: str) -> Optional[dict]:
    rows = (get_supabase().table("keyword_topic_research_runs").select("*")
            .eq("client_id", client_id).order("created_at", desc=True).limit(1).execute()).data
    return rows[0] if rows else None
