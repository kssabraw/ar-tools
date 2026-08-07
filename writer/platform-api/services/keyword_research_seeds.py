"""Keyword Research — seed/topic suggestions.

Gives the team a starting point: a handful of suggested SEED keywords/topics to
research, grounded in the client's business context (GBP category, business
location, ICP + differentiators, website). These are *seeds* — broad
service/topic terms the DataForSEO Labs expansion works best on — NOT branded
queries and NOT "near me" (research on the bare business name drifts, which the
module already warns about, and AI/search resolves "near me" itself).

Design mirrors services/keyword_research.py: the context-building / parsing /
cleaning helpers here are PURE (no I/O) and independently unit-tested; the one
LLM call goes through the shared report_llm transport (Anthropic → OpenAI →
Gemini fallback) and degrades to a deterministic fallback when no key is set, so
the button is never empty-handed.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import icp_service, keyword_research

logger = logging.getLogger(__name__)

# Seeds must never carry "near me" (same owner rule as the AI-visibility
# suggester): search/AI resolves it to the asker's location, so it's noise — the
# actual city belongs in the seed instead. Matches "near me"/"near-me"/"nearme".
_NEAR_ME_RE = re.compile(r"\bnear[\s\-]*me\b", re.I)

_SUGGEST_COUNT = 8  # target number of seed suggestions


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def is_local(client: dict) -> bool:
    """A client with a GBP competes on a geographic footprint (local SEO); a
    website-only client does not. Drives whether seeds lean service+city or
    category/need. Pure."""
    return bool(client.get("gbp"))


def build_seed_context(client: dict) -> str:
    """A compact business descriptor for grounding seed suggestions: business
    name + GBP category + location + website host + ICP/differentiators. Pure."""
    gbp = client.get("gbp") or {}
    lines: list[str] = []
    name = (client.get("name") or "").strip()
    if name:
        lines.append(f"Business name: {name}")
    category = gbp.get("gbp_category")
    categories = gbp.get("gbp_categories") or ([category] if category else [])
    cats = [c for c in categories if c]
    if cats:
        lines.append(f"Business type(s): {', '.join(cats)}")
    loc = (
        gbp.get("address") or gbp.get("formatted_address")
        or client.get("business_location")
    )
    if loc:
        lines.append(f"Location: {loc}")
    service_areas = gbp.get("service_area_places") or []
    if service_areas:
        lines.append(f"Also serves: {', '.join(str(p) for p in service_areas[:8])}")
    website = (client.get("website_url") or "").strip()
    if website:
        host = re.sub(r"^www\.", "", (re.sub(r"^https?://", "", website).split("/")[0]))
        if host:
            lines.append(f"Website: {host}")
    icp = icp_service.resolve_icp_text(client)
    if icp:
        lines.append(f"Ideal customer / positioning:\n{icp}")
    return "\n".join(lines).strip()


def clean_seeds(
    items: list[str],
    client_name: Optional[str],
    existing: Optional[set[str]] = None,
    *,
    cap: int = _SUGGEST_COUNT,
    brand_ratio: float = 0.6,
) -> list[str]:
    """Normalize, dedupe, and filter raw suggested seeds: drop blanks, "near me",
    pure-brand-name seeds (research on those drifts — see the module's brand-seed
    guard), and any already researched (``existing`` normalized-keyword set).
    Preserves order, caps the count. Pure."""
    existing = existing or set()
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        s = re.sub(r"\s+", " ", str(raw or "").strip())
        if not s:
            continue
        key = keyword_research.normalize_keyword(s)
        if key in seen or key in existing:
            continue
        if _NEAR_ME_RE.search(s):
            continue
        if keyword_research.looks_like_brand_seed(s, client_name, brand_ratio):
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= cap:
            break
    return out


def fallback_seeds(client: dict, *, cap: int = _SUGGEST_COUNT) -> list[str]:
    """Deterministic seed suggestions from GBP category + location, for when no
    LLM key is configured (or the call fails). Never brand-only. Pure."""
    gbp = client.get("gbp") or {}
    category = gbp.get("gbp_category")
    categories = [c for c in (gbp.get("gbp_categories") or ([category] if category else [])) if c]
    city = _city_of(
        gbp.get("address") or gbp.get("formatted_address") or client.get("business_location")
    )
    seeds: list[str] = []
    for cat in categories:
        c = cat.strip()
        if not c:
            continue
        seeds.append(c)
        if city:
            seeds.append(f"{c} {city}")
    return clean_seeds(seeds, client.get("name"), cap=cap)


def _city_of(location: Optional[str]) -> str:
    """Best-effort city token from a stored address/location string. Takes the
    first comma-separated part, dropping a leading street line if present. Pure."""
    if not location:
        return ""
    parts = [p.strip() for p in str(location).split(",") if p.strip()]
    if not parts:
        return ""
    # A single token or a "City, ST" style → first part is the city. A full
    # street address ("123 Main St, Austin, TX") → the city is the 2nd part.
    if len(parts) >= 3 and re.search(r"\d", parts[0]):
        return parts[1]
    return parts[0]


# ---------------------------------------------------------------------------
# Prompt + LLM (I/O via the shared report_llm transport).
# ---------------------------------------------------------------------------
_SEED_SYSTEM = (
    "You are an SEO strategist choosing SEED keywords for keyword research. A seed "
    "is a short, broad service or topic term (2-4 words) that a keyword-research "
    "tool expands into a wider universe of related keywords — NOT a full question "
    "and NOT a long-tail phrase. Good seeds name the core services, products, or "
    "topics the business wants to rank for."
)
_SEED_TOOL = {
    "name": "emit_seeds",
    "description": "Return the suggested seed keywords/topics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "seeds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The suggested seed keywords/topics.",
            }
        },
        "required": ["seeds"],
    },
}


def _seed_prompt(context: str, local: bool, count: int) -> str:
    locality = (
        "This is a LOCAL business. Favor seeds that pair the service with its city "
        "or a served area where natural (e.g. \"emergency plumber Sydney\"), but do "
        "NOT use the phrase \"near me\". Include a few bare service seeds too."
        if local
        else "This is NOT a local business. Ground seeds on the product/service "
        "category and customer need — do NOT append a city or use \"near me\"."
    )
    return (
        f"Suggest {count} SEED keywords/topics to research for this business.\n\n"
        f"{context}\n\n"
        f"{locality}\n\n"
        "Requirements:\n"
        "- Each seed is a short service/product/topic term (2-4 words), the kind a "
        "keyword tool expands — not a full question, not a long descriptive phrase.\n"
        "- Cover the business's distinct services/topics, not one repeated.\n"
        "- Do NOT use the bare business name as a seed (research on a brand name "
        "drifts).\n"
        "- Commercial/transactional intent preferred over generic informational.\n"
        f"- Return {count} seeds via the emit_seeds tool."
    )


def suggest_seeds(client_id: str) -> dict:
    """Suggest seed keywords/topics for a client to research. Grounds an LLM call
    on the client's business context, cleans/dedupes the result (and excludes
    seeds already researched), and falls back to a deterministic GBP-derived set
    when no LLM key is configured or the call fails. Returns
    {seeds, grounded, source}. Never raises for a best-effort suggestion."""
    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("name, website_url, business_location, gbp, detected_icp, "
                "differentiators, icp_text")
        .eq("id", client_id).limit(1).execute()
    ).data
    client = (rows or [{}])[0] or {}

    existing = _researched_seed_keys(client_id)
    context = build_seed_context(client)
    grounded = bool(context)

    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if have_key and context:
        try:
            from services import report_llm

            result = report_llm.run_forced_tool_sync(
                provider="anthropic",
                model=settings.keyword_research_seed_model,
                max_tokens=settings.keyword_research_seed_max_tokens,
                system=_SEED_SYSTEM,
                user=_seed_prompt(context, is_local(client), _SUGGEST_COUNT + 4),
                tool_name=_SEED_TOOL["name"],
                tool_description=_SEED_TOOL["description"],
                input_schema=_SEED_TOOL["input_schema"],
                log_tag="keyword_research_seed_suggest",
            )
            raw = (result or {}).get("seeds") or []
            seeds = clean_seeds(raw, client.get("name"), existing)
            if seeds:
                return {"seeds": seeds, "grounded": grounded, "source": "llm"}
        except Exception as exc:  # noqa: BLE001 — suggestions are best-effort
            logger.warning("keyword_research_seeds.suggest_failed",
                           extra={"client_id": client_id, "error": str(exc)})

    seeds = clean_seeds(fallback_seeds(client), client.get("name"), existing)
    return {"seeds": seeds, "grounded": grounded, "source": "fallback"}


def _researched_seed_keys(client_id: str) -> set[str]:
    """Normalized seed keywords already researched for this client, so a new
    suggestion set is fresh. Best-effort — empty on failure."""
    try:
        rows = (
            get_supabase().table("keyword_research_runs").select("seeds")
            .eq("client_id", client_id).limit(keyword_research._RUNS_KEEP).execute()
        ).data or []
    except Exception:
        return set()
    keys: set[str] = set()
    for r in rows:
        for s in r.get("seeds") or []:
            keys.add(keyword_research.normalize_keyword(s))
    return keys
