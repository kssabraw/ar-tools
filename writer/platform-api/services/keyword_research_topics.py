"""Keyword Research — client-grounded topical research.

Goes deeper than expanding the literal seed string: it works out what the client
actually is and what the seeds are really *about*, then uses that both to broaden
the expansion in relevant directions and to anchor the semantic relevance gate.

Two grounding sources, each best-effort (a missing one degrades, never aborts):

  * SITE TOPICS — the client's own pages, discovered via site_page_index
    (sitemap → DataForSEO ``site:`` fallback, the same discovery the rest of the
    suite uses), reduced to topic phrases from the URL slugs. This is the client's
    real coverage, not a guess.
  * INTENT FAN-OUT — one cheap LLM call (via the shared report_llm transport) that
    turns the seeds + the client's business context + its site topics into the
    distinct sub-intents/angles behind the seeds, plus a few extra on-topic
    expansion seeds ("third party claims administrator" → self-insured employers,
    workers-comp TPA, claims-administration software, choosing a TPA …).

The output feeds two consumers in keyword_research.run_keyword_research:
  * ``anchors`` — the positive set the Gemini relevance gate scores against, and
  * ``expansion_seeds`` — extra phrase-containment seeds to research (bounded), so
    the keyword universe follows the client's real topics, not just the seed text.

Pure helpers (slug→topic, anchor assembly, prompt) are unit-tested; the site
discovery + the LLM call are the only I/O.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from services import keyword_research, keyword_research_seeds

logger = logging.getLogger(__name__)

# URL path segments that are structure, not topic — dropped before deriving
# topic phrases from a slug.
_GENERIC_SLUGS = frozenset({
    "blog", "blogs", "post", "posts", "article", "articles", "news",
    "category", "categories", "cat", "tag", "tags", "page", "pages", "p",
    "product", "products", "shop", "store", "collection", "collections",
    "service", "services", "index", "home", "about", "about-us", "contact",
    "contact-us", "privacy", "privacy-policy", "terms", "tos", "sitemap",
    "faq", "faqs", "en", "us", "www", "amp", "author", "wp", "wp-content",
})
_TOPIC_MIN_WORDS = 1
_TOPIC_MAX_WORDS = 6


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def _slug_to_phrase(slug: str) -> str:
    """A hyphen/underscore slug → a space-separated phrase, digits/junk trimmed."""
    words = re.split(r"[-_]+", (slug or "").strip().lower())
    words = [w for w in words if w and not w.isdigit() and len(w) <= 30]
    return " ".join(words).strip()


def topics_from_urls(urls: list[str], *, cap: int = 40) -> list[str]:
    """Derive candidate topic phrases from a list of site URLs' path slugs.

    Takes the last (most specific) meaningful path segment of each URL, drops
    structural segments (blog/category/product/…), de-hyphenates it into a phrase,
    keeps only 1–6-word phrases with at least one alphabetic word, dedupes
    (case-insensitive, order-preserving) and caps. Pure — no network."""
    from services.site_page_index import url_path_slugs

    seen: set[str] = set()
    out: list[str] = []
    for url in urls or []:
        slugs = [s for s in url_path_slugs(url) if s.lower() not in _GENERIC_SLUGS]
        if not slugs:
            continue
        phrase = _slug_to_phrase(slugs[-1])
        words = phrase.split()
        if not (_TOPIC_MIN_WORDS <= len(words) <= _TOPIC_MAX_WORDS):
            continue
        if not any(re.search(r"[a-z]", w) for w in words):
            continue
        low = phrase.lower()
        if low and low not in seen:
            seen.add(low)
            out.append(phrase)
        if len(out) >= cap:
            break
    return out


def build_anchors(
    seeds: list[str],
    intents: list[str],
    site_topics: list[str],
    client_descriptor: Optional[str] = None,
) -> list[str]:
    """Assemble the relevance anchor set from the seeds, the fanned-out intents,
    the client's site topics, and (optionally) a short business descriptor.
    Order-preserving dedupe. Pure — the cap is applied by the relevance scorer."""
    anchors: list[str] = []
    seen: set[str] = set()
    for group in (seeds, intents, site_topics, [client_descriptor] if client_descriptor else []):
        for t in group or []:
            s = (t or "").strip()
            low = s.lower()
            if s and low not in seen:
                seen.add(low)
                anchors.append(s)
    return anchors


def clean_expansion_seeds(
    items: list[str], seeds: list[str], client_name: Optional[str], *, cap: int
) -> list[str]:
    """Normalize/dedupe LLM expansion seeds, drop any equal to an existing seed,
    "near me", or a pure brand-name seed. Reuses the seed-suggestion cleaner so the
    rules stay in one place. Pure."""
    existing = {keyword_research.normalize_keyword(s) for s in (seeds or [])}
    return keyword_research_seeds.clean_seeds(
        items, client_name, existing, cap=cap,
        brand_ratio=settings.keyword_research_brand_seed_ratio,
    )


# ---------------------------------------------------------------------------
# Intent fan-out prompt (I/O via the shared report_llm transport).
# ---------------------------------------------------------------------------
_INTENT_SYSTEM = (
    "You are an SEO topical strategist. Given the seed keywords a team wants to "
    "research and a description of the business, identify the distinct SEARCH "
    "INTENTS and sub-topics behind those seeds — the real reasons someone searches "
    "in this space and the angles a site should cover. Stay strictly within the "
    "business's actual domain; do not drift into unrelated senses of a word."
)
_INTENT_TOOL = {
    "name": "emit_topics",
    "description": "Return the sub-intents behind the seeds and a few extra on-topic seeds.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Distinct sub-intents / sub-topics behind the seeds "
                               "(short noun phrases, 2-6 words each). The angles a "
                               "site in this space should cover.",
            },
            "expansion_seeds": {
                "type": "array",
                "items": {"type": "string"},
                "description": "A few extra SHORT seed terms (2-4 words) to research "
                               "that stay on the business's topic — the kind a "
                               "keyword tool expands. Not questions, not brand names.",
            },
        },
        "required": ["intents", "expansion_seeds"],
    },
}


def _intent_prompt(seeds: list[str], context: str, site_topics: list[str], count: int) -> str:
    seed_lines = "\n".join(f"- {s}" for s in seeds)
    site_block = (
        "\n\nThe client's site already covers these topics (use them to stay on "
        "the business's real domain):\n" + "\n".join(f"- {t}" for t in site_topics[:25])
        if site_topics else ""
    )
    ctx_block = f"\n\nBusiness context:\n{context}" if context else ""
    return (
        f"Seed keywords to research:\n{seed_lines}{ctx_block}{site_block}\n\n"
        f"Identify up to {count} distinct sub-intents / sub-topics behind these "
        "seeds — the different reasons people search here and the angles the site "
        "should cover. Then give a few extra short on-topic seed terms to research.\n\n"
        "Rules:\n"
        "- Stay strictly inside this business's domain. If a seed word has an "
        "unrelated common meaning (e.g. \"party\" as in a celebration when the "
        "topic is \"third party\"), ignore that meaning entirely.\n"
        "- Intents are short noun phrases (2-6 words), not questions.\n"
        "- Expansion seeds are short (2-4 words), commercial/topic terms, never the "
        "bare business name and never \"near me\".\n"
        "- Return via the emit_topics tool."
    )


def fanout_intents(
    seeds: list[str], client: dict, site_topics: list[str]
) -> tuple[list[str], list[str]]:
    """One LLM call → (intents, expansion_seeds), grounded on the seeds + client
    business context + site topics. Best-effort: returns ([], []) when no LLM key
    is configured or the call fails, so the run degrades to the token gates + site
    topics as anchors."""
    have_key = bool(
        settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key
    )
    if not have_key:
        return [], []
    context = keyword_research_seeds.build_seed_context(client)
    try:
        from services import report_llm

        result = report_llm.run_forced_tool_sync(
            provider="anthropic",
            model=settings.keyword_research_intent_model,
            max_tokens=settings.keyword_research_intent_max_tokens,
            system=_INTENT_SYSTEM,
            user=_intent_prompt(seeds, context, site_topics,
                                settings.keyword_research_intent_max),
            tool_name=_INTENT_TOOL["name"],
            tool_description=_INTENT_TOOL["description"],
            input_schema=_INTENT_TOOL["input_schema"],
            log_tag="keyword_research_intent_fanout",
        ) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("keyword_research_topics.fanout_failed", extra={"error": str(exc)})
        return [], []

    intents = [str(x).strip() for x in (result.get("intents") or []) if str(x).strip()]
    raw_expansion = [str(x).strip() for x in (result.get("expansion_seeds") or []) if str(x).strip()]
    expansion = clean_expansion_seeds(
        raw_expansion, seeds, client.get("name"),
        cap=settings.keyword_research_intent_expansion_cap,
    )
    return intents[: settings.keyword_research_intent_max], expansion


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
async def discover_site_topics(client: dict, location_code: Optional[int]) -> tuple[list[str], str]:
    """Discover the client's site topics. Returns (topics, source). Best-effort —
    a client with no website or no readable pages yields ([], 'none')."""
    website = (client.get("website_url") or "").strip()
    if not website or not settings.keyword_research_site_topics:
        return [], "none"
    try:
        from services.site_page_index import discover_site_urls

        loc = int(location_code) if location_code else settings.dataforseo_default_location_code
        urls, source = await discover_site_urls(website, loc)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("keyword_research_topics.site_discovery_failed", extra={"error": str(exc)})
        return [], "none"
    topics = topics_from_urls(urls, cap=settings.keyword_research_site_topic_cap)
    return topics, source


async def research_topics(
    client: dict, seeds: list[str], location_code: Optional[int]
) -> dict:
    """Build the client-grounded topical research for a run: site topics + intent
    fan-out → anchors + expansion seeds. Returns the topic_research blob (also the
    source of the run's stored ``topic_research``). Best-effort throughout."""
    if not settings.keyword_research_topical:
        return {"enabled": False, "site": {"source": "none", "topics": []},
                "intents": [], "expansion_seeds": [], "anchors": list(seeds)}

    site_topics, site_source = await discover_site_topics(client, location_code)

    intents: list[str] = []
    expansion: list[str] = []
    if settings.keyword_research_intent_fanout:
        intents, expansion = fanout_intents(seeds, client, site_topics)

    descriptor = keyword_research_seeds.build_seed_context(client) or None
    # The descriptor can be long; anchor on just its first line (name + type).
    descriptor_head = descriptor.splitlines()[0] if descriptor else None
    anchors = build_anchors(seeds, intents, site_topics, descriptor_head)

    return {
        "enabled": True,
        "site": {"source": site_source, "topics": site_topics},
        "intents": intents,
        "expansion_seeds": expansion,
        "anchors": anchors,
    }
