"""Service Page Brief Generator — top-level orchestration.

Flow: research cache → (research pipeline) → synthesis → assembly.

The cache stores the **research_bundle** (client-agnostic), so a repeat run
within the TTL skips the SERP fetch + competitor scrape (PRD §8.6) while
synthesis still runs per-client and produces a differentiated brief.
"""

from __future__ import annotations

import logging

from models.service_brief import SCHEMA_VERSION, ResearchBundle, ServiceBriefRequest, ServiceBriefResponse

from . import cache
from .assembly import assemble
from .errors import ServiceBriefError
from .research import run_research
from .synthesis import synthesize

logger = logging.getLogger(__name__)


async def run_service_brief(request: ServiceBriefRequest) -> ServiceBriefResponse:
    """Generate a service-page brief for a single (service, primary_query)."""
    cache_hit = False
    bundle: ResearchBundle | None = None

    # ---- Research cache (client-agnostic) ----
    if not request.force_refresh:
        cached_payload = await cache.get_cached(request.primary_query, request.location_code)
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
        )
        await cache.write_cache(
            keyword=request.primary_query,
            location_code=request.location_code,
            schema_version=SCHEMA_VERSION,
            output_payload=bundle.model_dump(),
        )

    # ---- Synthesis (per-client) ----
    try:
        synthesis = await synthesize(
            service=request.service,
            primary_query=request.primary_query,
            bundle=bundle,
            client_context=request.client_context,
        )
    except Exception as exc:
        raise ServiceBriefError(
            "synthesis_failed", f"Synthesis failed: {exc}"
        ) from exc

    response = assemble(request, bundle, synthesis, cache_hit=cache_hit)
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
