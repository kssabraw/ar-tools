"""Keyword Research — blog-topic idea generator.

Keyword research surfaces *keywords*; a content team needs *topics*. This turns a
run's buyer-fit keywords + the client's ICP into a short list of blog post ideas
— each a title + the angle + the keyword(s) it targets — ready to hand a writer.

It runs AFTER the audience filter, so it only ever builds on keywords the client's
actual buyer would search (no "how to become an adjuster" posts for a B2B TPA).
One LLM call per request via the shared report_llm transport; the selection and
prompt building are pure and unit-tested. On-demand (like the PDF report), cached
on the run so re-opening is free.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import keyword_research_seeds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def select_topic_keywords(rows: list[dict], *, cap: int = 60) -> list[dict]:
    """Pick the keywords worth building blog topics from: buyer-fit (never
    job_seeker/off_audience), preferring informational/question intent (blog
    material) then the rest, ordered by opportunity then volume. Pure."""
    def _buyer(r: dict) -> bool:
        return (r.get("audience_fit") or "buyer") == "buyer"

    buyer = [r for r in rows if _buyer(r)]

    def _rank(r: dict) -> tuple:
        intent = (r.get("search_intent") or "").lower()
        blog_intent = 1 if (r.get("is_question") or intent == "informational") else 0
        return (blog_intent, r.get("opportunity_score") or 0, r.get("volume") or 0)

    return sorted(buyer, key=_rank, reverse=True)[:cap]


def build_topic_prompt(context: str, keywords: list[dict], count: int) -> str:
    """The blog-topic prompt from the client's business context + the selected
    buyer-fit keywords. Pure."""
    kw_lines = "\n".join(
        f"- {r.get('keyword')}"
        + (f" (vol {r.get('volume')})" if r.get("volume") else "")
        for r in keywords
    )
    ctx_block = f"{context}\n\n" if context else ""
    return (
        f"{ctx_block}These are real search keywords the business's target customers "
        f"use (already filtered to the right audience):\n{kw_lines}\n\n"
        f"Propose {count} blog post ideas this business should write to attract and "
        "win its ideal customer. Each idea:\n"
        "- a specific, compelling title (not a bare keyword)\n"
        "- a one-line angle: what the post covers and why it matters to the buyer\n"
        "- the keyword(s) from the list above it targets\n\n"
        "Rules:\n"
        "- Write for the BUYER, not job-seekers, students, or DIY consumers.\n"
        "- Favor topics that show expertise and pull the buyer toward the service.\n"
        "- Group related keywords into one strong post rather than one post per "
        "keyword.\n"
        "- Return via the emit_topics tool."
    )


_TOPIC_SYSTEM = (
    "You are a B2B content strategist. Turn keyword research into a focused set of "
    "blog post ideas that attract the business's IDEAL CUSTOMER and demonstrate "
    "expertise — never generic, never aimed at the wrong audience."
)
_TOPIC_TOOL = {
    "name": "emit_topics",
    "description": "Return the proposed blog post ideas.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "angle": {"type": "string"},
                        "target_keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "angle"],
                },
                "description": "The blog post ideas.",
            }
        },
        "required": ["topics"],
    },
}


def _clean_topics(raw: list, cap: int) -> list[dict]:
    """Normalize LLM topic objects into stored rows. Pure."""
    out: list[dict] = []
    seen: set[str] = set()
    for t in raw or []:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append({
            "title": title,
            "angle": str(t.get("angle") or "").strip(),
            "target_keywords": [str(k).strip() for k in (t.get("target_keywords") or []) if str(k).strip()],
        })
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
def _client_for_context(client_id: str) -> dict:
    try:
        rows = (
            get_supabase().table("clients")
            .select("name, website_url, business_location, gbp, detected_icp, "
                    "differentiators, icp_text")
            .eq("id", client_id).limit(1).execute()
        ).data
    except Exception:
        return {}
    return (rows or [{}])[0] or {}


def generate_blog_topics(client_id: str, run_id: str) -> dict:
    """Generate blog post ideas for a run's buyer-fit keywords, cache them on the
    run, and return {topics, generated}. Best-effort — returns an empty topic list
    (never raises) when no keywords, no LLM key, or the call fails."""
    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs").select("id")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        raise ValueError("run_not_found")

    kws = (
        supabase.table("keyword_research_keywords")
        .select("keyword, volume, opportunity_score, search_intent, is_question, audience_fit")
        .eq("run_id", run_id).execute()
    ).data or []
    selected = select_topic_keywords(kws, cap=settings.keyword_research_topic_keyword_cap)
    if not selected:
        return {"topics": [], "generated": False, "reason": "no_keywords"}

    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return {"topics": [], "generated": False, "reason": "no_llm_key"}

    client = _client_for_context(client_id)
    context = keyword_research_seeds.build_seed_context(client)
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.keyword_research_topic_model,
            max_tokens=settings.keyword_research_topic_max_tokens,
            system=_TOPIC_SYSTEM,
            user=build_topic_prompt(context, selected, settings.keyword_research_topic_count),
            tool_name=_TOPIC_TOOL["name"],
            tool_description=_TOPIC_TOOL["description"],
            input_schema=_TOPIC_TOOL["input_schema"],
            log_tag="keyword_research_blog_topics",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("keyword_research_content.generate_failed",
                       extra={"client_id": client_id, "run_id": run_id, "error": str(exc)})
        return {"topics": [], "generated": False, "reason": "llm_error"}

    topics = _clean_topics(result.get("topics"), settings.keyword_research_topic_count)
    try:
        supabase.table("keyword_research_runs").update(
            {"blog_topics": topics or None}).eq("id", run_id).execute()
    except Exception as exc:  # noqa: BLE001 — cache write is best-effort
        logger.warning("keyword_research_content.cache_failed", extra={"error": str(exc)})
    return {"topics": topics, "generated": bool(topics)}
