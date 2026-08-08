"""Topic Research — the strategist-grade reasoning layer.

The deterministic engine (keyword_topic_research) gathers evidence: buyer
problem-themes, each theme's real search demand (PAA + suggestions), and
competitor informational keywords. This layer makes that evidence think like an
SEO strategist, reusing SerMastr's two assets:

  * SOP GROUNDING — the agency's own content playbooks (Seed Keyword / On-Page
    Coverage / AEO / Site Architecture) are injected so the plan follows the house
    methodology and builds a topical-authority structure (pillars → clusters), not
    a flat list.
  * CLIENT-DATA GROUNDING — the client's real position (what they already rank
    for + striking distance, GSC opportunities, competitor keyword gaps, existing
    content coverage, seasonal trends) from the shared context providers, so the
    plan targets what will actually move THIS client's rankings.

It runs as a bounded tool-use loop (mirroring services/strategist.py): the model
can investigate (read a SOP section, pull fresh demand for a candidate, mine a
competitor's topics) before committing, then emits a topical-authority plan via a
forced tool. Best-effort — any failure falls back to the deterministic cards.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from config import settings
from services import (
    dataforseo_labs,
    keyword_research,
    keyword_research_audience,
)

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 120.0
# The agency content SOPs that make topic research follow the house methodology.
_CONTENT_SOPS = (
    "Seed_Keyword_SOP.md",
    "On_Page_Criteria_and_Coverage.md",
    "AIO_AEO_SOP.md",
    "Site_Architecture_and_Internal_Linking_SOP.md",
)


# ---------------------------------------------------------------------------
# Grounding blocks.
# ---------------------------------------------------------------------------
def content_sop_block(budget_chars: int) -> str:
    """The agency content SOPs, each capped to a share of the budget. '' if the
    corpus can't be loaded. Best-effort."""
    try:
        from services import sop_library
        docs = sop_library.load_sop_docs()
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_strategist.sop_load_failed", extra={"error": str(exc)})
        return ""
    if not docs:
        return ""
    per = max(1500, budget_chars // max(1, len(_CONTENT_SOPS)))
    parts: list[str] = []
    for name in _CONTENT_SOPS:
        text = docs.get(name)
        if text:
            parts.append(f"### SOP: {name}\n{text.strip()[:per]}")
    return "\n\n".join(parts)


def build_client_context(client_id: str) -> str:
    """The client's real cross-module position (rankings + striking distance, GSC
    opportunities, competitor gaps, content coverage, trends, ICP) as compact JSON.
    Reuses the shared context providers. Best-effort — '{}' on failure."""
    try:
        from services.slack_assistant import context as sa_context
        ctx = sa_context.build_context(client_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyword_topic_strategist.context_failed", extra={"error": str(exc)})
        return "{}"
    try:
        return json.dumps(ctx, default=str)[: settings.keyword_topic_context_char_budget]
    except Exception:
        return "{}"


def render_evidence(evidence: dict) -> str:
    """The gathered evidence (themes + per-theme demand/questions + competitors) as
    a compact prompt block. Pure."""
    lines: list[str] = []
    site = evidence.get("site_topics") or []
    if site:
        lines.append("CLIENT SITE TOPICS: " + ", ".join(site[:30]))
    lines.append("\nCANDIDATE THEMES + REAL DEMAND:")
    for m in evidence.get("mined") or []:
        t = m.get("theme") or {}
        sugg = sorted(
            (s for s in (m.get("suggestions") or []) if s.get("keyword")),
            key=lambda s: (s.get("volume") or 0), reverse=True)
        kw = ", ".join(f"{s['keyword']} ({s.get('volume') or 0})" for s in sugg[:10])
        q = "; ".join((m.get("questions") or [])[:6])
        lines.append(f"- THEME: {t.get('theme')} | problem: {t.get('problem')}")
        lines.append(f"    query: {t.get('search_query')} | keywords: {kw or '—'}")
        if q:
            lines.append(f"    questions: {q}")
    comps = evidence.get("competitors") or []
    if comps:
        lines.append("\nCOMPETITOR TOPICS (informational keywords they rank for):")
        for c in comps:
            sample = ", ".join(s.get("keyword") for s in (c.get("sample") or [])[:10] if s.get("keyword"))
            lines.append(f"- {c.get('domain')} ({c.get('informational_keywords')} informational): {sample}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Investigation tools (read-only; used inside the loop).
# ---------------------------------------------------------------------------
_TOOL_DEFS = [
    {
        "name": "read_sop",
        "description": "Read a section of an agency SOP to ground a decision in the house methodology. docs: Seed_Keyword_SOP, On_Page_Criteria_and_Coverage, AIO_AEO_SOP, Site_Architecture_and_Internal_Linking_SOP (and others).",
        "input_schema": {"type": "object", "properties": {
            "doc": {"type": "string"}, "section": {"type": "string", "description": "Optional section heading."}},
            "required": ["doc"]},
        "paid": False,
    },
    {
        "name": "keyword_demand",
        "description": "PAID: real search demand for a candidate topic phrase — phrase-containment suggestions (with volume) + People Also Ask questions. Use to validate/size a topic before committing.",
        "input_schema": {"type": "object", "properties": {
            "phrase": {"type": "string", "description": "A 2-5 word topic phrase the buyer would search."}},
            "required": ["phrase"]},
        "paid": True,
    },
    {
        "name": "competitor_topics",
        "description": "PAID: the buyer-fit INFORMATIONAL keywords a competitor domain ranks for (proven topics + content gap). Use to find topics competitors win that the client doesn't.",
        "input_schema": {"type": "object", "properties": {
            "domain": {"type": "string", "description": "A competitor domain (e.g. sedgwick.com)."}},
            "required": ["domain"]},
        "paid": False,
    },
]


async def _dispatch_tool(name: str, args: dict, client_id: str, loc: int, lang: str) -> str:
    if name == "read_sop":
        from services import strategist_tools
        return await strategist_tools._run_read_sop(client_id, args)
    if name == "keyword_demand":
        phrase = (args.get("phrase") or "").strip()
        if not phrase:
            return "no phrase"
        keyword_research.reserve_budget(2)
        from services import serp_snapshot
        rows, _ = await dataforseo_labs.fetch_keyword_suggestions(phrase, loc, lang, limit=100)
        buyer = [r for r in rows if r.get("keyword") and not keyword_research_audience.is_job_seeker(r.get("keyword"))]
        buyer.sort(key=lambda r: (r.get("volume") or 0), reverse=True)
        top = [f"{r['keyword']} ({r.get('volume') or 0})" for r in buyer[:15]]
        questions: list[str] = []
        try:
            items = await serp_snapshot.fetch_serp(phrase, loc, lang, settings.keyword_topic_serp_depth)
            questions = (serp_snapshot.extract_serp_features(items).get("people_also_ask") or [])[:8]
        except Exception:  # noqa: BLE001
            pass
        return json.dumps({"keywords": top, "questions": questions})
    if name == "competitor_topics":
        domain = (args.get("domain") or "").strip()
        if not domain:
            return "no domain"
        keyword_research.reserve_budget(1)
        rows, _ = await dataforseo_labs.fetch_ranked_keywords(
            domain, loc, lang, limit=settings.keyword_topic_competitor_kw_limit, max_position=20)
        info = [r for r in rows
                if (r.get("search_intent") or "").lower() == "informational"
                and r.get("keyword") and not keyword_research_audience.is_job_seeker(r.get("keyword"))]
        info.sort(key=lambda r: (r.get("volume") or 0), reverse=True)
        return json.dumps([f"{r['keyword']} ({r.get('volume') or 0})" for r in info[:20]])
    return f"unknown tool {name}"


# ---------------------------------------------------------------------------
# Emit schema + system prompt.
# ---------------------------------------------------------------------------
_EMIT_TOOL = {
    "name": "emit_topic_plan",
    "description": "Emit the final topical-authority content plan. Call exactly once when done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "assessment": {"type": "string", "description": "A 2-4 sentence strategic read of the client's topical position and where the biggest content opportunity is, grounded in the data."},
            "pillars": {
                "type": "array",
                "description": "The topical-authority pillars (3-6), each a hub the client should own.",
                "items": {
                    "type": "object",
                    "properties": {
                        "pillar": {"type": "string", "description": "Pillar topic label."},
                        "rationale": {"type": "string", "description": "Why this pillar for THIS client — cite the data/SOP."},
                        "clusters": {
                            "type": "array",
                            "description": "Supporting blog posts under the pillar.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "buyer_problem": {"type": "string"},
                                    "search_intent": {"type": "string", "description": "informational | commercial | transactional | navigational"},
                                    "funnel_stage": {"type": "string", "description": "TOFU | MOFU | BOFU"},
                                    "target_keywords": {"type": "array", "items": {"type": "string"}},
                                    "questions": {"type": "array", "items": {"type": "string"}},
                                    "priority": {"type": "string", "description": "high | medium | low — by business impact given the client's authority + demand."},
                                    "rationale": {"type": "string", "description": "Why write this now — cite demand / the client's position / an SOP."},
                                },
                                "required": ["title", "buyer_problem", "target_keywords", "priority"],
                            },
                        },
                    },
                    "required": ["pillar", "clusters"],
                },
            },
        },
        "required": ["assessment", "pillars"],
    },
}

_SYSTEM = (
    "You are a senior SEO content strategist for an agency. You plan a client's "
    "blog/content topics the way the agency's SOPs prescribe — building TOPICAL "
    "AUTHORITY (pillar hubs + supporting clusters), mapping each topic to search "
    "intent and funnel stage, and considering AI-answer (AEO) retrieval.\n\n"
    "You are given: the agency's content SOPs, the client's REAL position (what it "
    "already ranks for + striking-distance, GSC opportunities, competitor keyword "
    "gaps, existing content coverage, seasonal trends, ICP), and gathered evidence "
    "(candidate buyer problem-themes with real search demand + competitor topics).\n\n"
    "Think like an expert:\n"
    "- Write for the client's BUYER (the ICP), never job-seekers/students/DIY "
    "consumers.\n"
    "- Build on the client's existing authority — prefer topics adjacent to what "
    "they already rank for and striking-distance wins; fill coverage GAPS vs "
    "competitors; don't duplicate content they already have.\n"
    "- Prioritize by BUSINESS IMPACT (buyer stage × winnability given the client's "
    "authority × real demand), not raw volume.\n"
    "- Ground every recommendation in the data or an SOP. Use the tools to verify "
    "demand or read an SOP section before committing when useful, but stay within "
    "the drill-down budget.\n"
    "- Never invent metrics; if you lack data, say so in the rationale.\n\n"
    "When done, call emit_topic_plan exactly once."
)


def _prompt(sop_block: str, client_ctx: str, evidence_text: str, max_dd: int) -> str:
    return (
        f"AGENCY CONTENT SOPs:\n{sop_block or '(none available)'}\n\n"
        f"CLIENT REAL POSITION (JSON):\n{client_ctx}\n\n"
        f"GATHERED EVIDENCE:\n{evidence_text}\n\n"
        f"DRILL-DOWN BUDGET: at most {max_dd} tool calls this run. Produce a "
        "topical-authority content plan (pillars → clusters) for this client, then "
        "call emit_topic_plan."
    )


# ---------------------------------------------------------------------------
# The bounded reasoning loop.
# ---------------------------------------------------------------------------
async def run_topic_strategy(client_id: str, ctx: dict, evidence: dict) -> Optional[dict]:
    """Run the SOP- + data-grounded reasoning loop over the gathered evidence and
    return the emitted topical-authority plan (or None). Best-effort."""
    if not settings.anthropic_api_key:
        return None
    import anthropic

    from services.report_llm import retry_transient

    loc = dataforseo_labs.labs_location_code(ctx.get("rank_tracking_location_code"))
    lang = settings.dataforseo_default_language_code

    sop_block = content_sop_block(settings.keyword_topic_sop_char_budget)
    client_ctx = build_client_context(client_id)
    evidence_text = render_evidence(evidence)
    max_dd = settings.keyword_topic_max_drilldowns

    tools = list(_TOOL_DEFS) + [_EMIT_TOOL]
    api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=_LLM_TIMEOUT)
    messages: list[dict] = [{"role": "user", "content": _prompt(sop_block, client_ctx, evidence_text, max_dd)}]
    drilldowns = 0
    emitted: Optional[dict] = None

    for round_no in range(max_dd + 3):
        force_emit = round_no >= max_dd + 1 or drilldowns >= max_dd
        resp = await retry_transient(
            lambda: api.messages.create(
                model=settings.keyword_topic_model,
                max_tokens=settings.keyword_topic_strategist_max_tokens,
                system=_SYSTEM,
                tools=[{"name": t["name"], "description": t["description"],
                        "input_schema": t["input_schema"]} for t in tools],
                tool_choice={"type": "tool", "name": "emit_topic_plan"} if force_emit else {"type": "auto"},
                messages=messages,
            ),
            log_tag="keyword_topic_strategist",
        )
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        emit_block = next((b for b in tool_uses if b.name == "emit_topic_plan"), None)
        if emit_block is not None:
            emitted = emit_block.input or {}
            break
        if not tool_uses:
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Call emit_topic_plan now."})
            continue
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in tool_uses:
            if drilldowns >= max_dd:
                out = "Drill-down cap reached — call emit_topic_plan with what you have."
            else:
                try:
                    out = await _dispatch_tool(block.name, block.input or {}, client_id, loc, lang)
                except Exception as exc:  # noqa: BLE001 — a tool failure never kills the run
                    out = f"{block.name} failed: {exc}"
                drilldowns += 1
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
        messages.append({"role": "user", "content": results})

    return sanitize_plan(emitted) if emitted else None


# ---------------------------------------------------------------------------
# Pure post-processing.
# ---------------------------------------------------------------------------
_PRIORITY_NUM = {"high": 0.9, "medium": 0.6, "med": 0.6, "low": 0.3}


def sanitize_plan(raw: dict) -> dict:
    """Normalize the emitted plan: coerce lists, keep known fields. Pure."""
    pillars = []
    for p in (raw.get("pillars") or []):
        if not isinstance(p, dict) or not p.get("pillar"):
            continue
        clusters = []
        for c in (p.get("clusters") or []):
            if not isinstance(c, dict) or not c.get("title"):
                continue
            clusters.append({
                "title": str(c.get("title") or "").strip(),
                "buyer_problem": str(c.get("buyer_problem") or "").strip(),
                "search_intent": str(c.get("search_intent") or "").strip().lower() or None,
                "funnel_stage": str(c.get("funnel_stage") or "").strip().upper() or None,
                "target_keywords": [str(k).strip() for k in (c.get("target_keywords") or []) if str(k).strip()],
                "questions": [str(q).strip() for q in (c.get("questions") or []) if str(q).strip()],
                "priority": str(c.get("priority") or "medium").strip().lower(),
                "rationale": str(c.get("rationale") or "").strip(),
            })
        if clusters:
            pillars.append({
                "pillar": str(p.get("pillar")).strip(),
                "rationale": str(p.get("rationale") or "").strip(),
                "clusters": clusters,
            })
    return {"assessment": str(raw.get("assessment") or "").strip(), "pillars": pillars}


def _volume_lookup(evidence: dict) -> dict:
    """{normalized keyword: volume} from all gathered suggestions. Pure."""
    vol: dict = {}
    for m in evidence.get("mined") or []:
        for s in m.get("suggestions") or []:
            kw = keyword_research.normalize_keyword(s.get("keyword"))
            if kw and s.get("volume") is not None:
                vol[kw] = max(vol.get(kw, 0), s.get("volume") or 0)
    return vol


def flatten_plan_to_cards(plan: dict, evidence: dict) -> list[dict]:
    """Flatten the pillar/cluster plan into the flat topic cards the existing UI
    renders, enriching keyword volumes from the gathered evidence and carrying the
    pillar / intent / funnel-stage / rationale. Ordered by priority. Pure."""
    vol = _volume_lookup(evidence)
    cards: list[dict] = []
    for p in plan.get("pillars") or []:
        for c in p.get("clusters") or []:
            kws = c.get("target_keywords") or []
            supporting = [{"keyword": k, "volume": vol.get(keyword_research.normalize_keyword(k))} for k in kws]
            cards.append({
                "theme": p.get("pillar"),
                "pillar": p.get("pillar"),
                "problem": c.get("buyer_problem"),
                "title": c.get("title"),
                "search_intent": c.get("search_intent"),
                "funnel_stage": c.get("funnel_stage"),
                "supporting_keywords": supporting,
                "questions": c.get("questions") or [],
                "competitor_examples": [],
                "volume_total": sum((s.get("volume") or 0) for s in supporting),
                "priority": _PRIORITY_NUM.get(c.get("priority"), 0.5),
                "priority_label": c.get("priority"),
                "rationale": c.get("rationale"),
            })
    cards.sort(key=lambda c: c.get("priority") or 0, reverse=True)
    return cards
