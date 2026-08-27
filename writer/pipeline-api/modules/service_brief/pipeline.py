"""Service Page Brief Generator — top-level orchestration.

Flow: research cache → (research pipeline) → synthesis → assembly.

The cache stores the **research_bundle** (client-agnostic), so a repeat run
within the TTL skips the SERP fetch + competitor scrape (PRD §8.6) while
synthesis still runs per-client and produces a differentiated brief.
"""

from __future__ import annotations

import logging

from models.service_brief import SCHEMA_VERSION, ResearchBundle, ServiceBriefRequest, ServiceBriefResponse

from . import cache, cost
from .assembly import assemble
from .errors import ServiceBriefError
from .research import _anchor_query, run_research
from .serp import competitor_avg_words, serp_word_target
from .synthesis import synthesize

logger = logging.getLogger(__name__)


def _apply_serp_length_target(bundle: ResearchBundle) -> None:
    """Set the SERP-anchored length target (competitor avg + 20%) on the bundle's
    SERP profile from its competitor word counts.

    Called for both fresh and cached bundles so a research bundle cached BEFORE the
    length change (which carries the old fixed-band target) is still sized to the
    SERP average — the cache lookup keys on keyword + TTL only, not schema_version,
    so an old bundle would otherwise be reused verbatim for up to the TTL window.
    Idempotent for fresh bundles (research computed the same value). No-op — leaving
    the band fallback in place — when too few competitors scraped to yield a
    reliable average. Deterministic, no LLM."""
    counts = [sk.word_count for sk in bundle.competitor_skeletons if sk.word_count > 0]
    avg = competitor_avg_words(counts)
    target = serp_word_target(avg)
    if target:
        bundle.serp_profile.target_word_count = target
        bundle.serp_profile.serp_avg_word_count = int(round(avg))


async def run_service_brief(request: ServiceBriefRequest) -> ServiceBriefResponse:
    """Generate a service-page brief for a single (service, primary_query)."""
    cost.start_accounting()
    cache_hit = False
    bundle: ResearchBundle | None = None

    # The cache is keyed on the SERP anchor query (for a location page that's the
    # first service in the target location, not the bare primary_query) so two
    # location hubs for the same location but different lead services don't
    # collide. `_anchor_query` is the same resolver run_research uses internally.
    cache_key = _anchor_query(
        page_type=request.page_type,
        primary_query=request.primary_query,
        services=request.services,
        location=request.location,
    )

    # ---- Research cache (client-agnostic) ----
    if not request.force_refresh:
        cached_payload = await cache.get_cached(
            cache_key, request.location_code, request.page_type
        )
        if cached_payload:
            try:
                bundle = ResearchBundle(**cached_payload)
                cache_hit = True
            except Exception as exc:
                logger.warning(
                    "service_brief.cache.payload_invalid",
                    extra={"error": str(exc)},
                )
                bundle = None

    # ---- Fresh research (own pipeline) ----
    if bundle is None:
        bundle = await run_research(
            service=request.service,
            primary_query=request.primary_query,
            location=request.location,
            location_code=request.location_code,
            page_type=request.page_type,
            services=request.services,
        )
        await cache.write_cache(
            keyword=cache_key,
            location_code=request.location_code,
            schema_version=SCHEMA_VERSION,
            output_payload=bundle.model_dump(),
            page_type=request.page_type,
        )

    # SERP-anchored length target — applied after the bundle is ready (cache or
    # fresh) so a bundle cached under the old fixed-band target is upgraded to the
    # SERP average + 20% before synthesis reads it. Idempotent for fresh bundles.
    _apply_serp_length_target(bundle)

    # ---- Synthesis (per-client) ----
    try:
        synthesis = await synthesize(
            service=request.service,
            primary_query=request.primary_query,
            bundle=bundle,
            client_context=request.client_context,
            page_type=request.page_type,
            services=request.services,
            location=request.location,
        )
    except Exception as exc:
        raise ServiceBriefError(
            "synthesis_failed", f"Synthesis failed: {exc}"
        ) from exc

    response = assemble(request, bundle, synthesis, cache_hit=cache_hit, cost_usd=cost.total_cost())
    logger.info(
        "service_brief.complete",
        extra={
            "run_id": request.run_id,
            "primary_query": request.primary_query,
            "mode": response.metadata.mode,
            "sections": response.metadata.section_count,
            "objections": response.metadata.objection_count,
            "cache_hit": cache_hit,
        },
    )
    return response
