"""Outscraper enrichment BY place_id — contact names / phones / emails.

Generalizes `pixel_probe.fetch_enriched_sample` (the proven, deliberately-off-the-ingest-path model
for a billed enrichment call) into a reusable `enrich_places(place_ids, enrichments)`. Like that
function it builds its OWN request rather than calling `outscraper_client.submit_maps_search` —
whose base-tier invariant ("do not populate `enrichment`, and do not add a config flag that would
let someone else") protects the mass ingest and must not be bent. This module is that separate,
explicitly-billed act.

Called BY place_id: Outscraper resolves a place_id passed as the query to exactly that place, so a
selection enriches exactly the chosen leads and nothing else. Each place is a separate request run
CONCURRENTLY (bounded) — billing is per record either way, so this buys robustness (one place
failing loses one place, not the batch) over the marginal request-overhead saving of a multi-query
call. That per-place isolation is the pixel_probe lesson: every query is billed, so a failure on one
must never discard the records the others were charged for.

**Measure-don't-infer:** the exact enrichment param VALUE(S) and response field names are
unconfirmed against this account (no enriched pull has run). `enrichments` is passed through
verbatim from config and this module asserts nothing about the response — `enrichment.parse_contacts`
reads it defensively, and `probe-enrich` logs one full record so the shape is confirmed before
production is trusted.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..config import Settings
from .outscraper_client import ENDPOINT_MAPS_SEARCH, OutscraperClient, extract_places

logger = logging.getLogger(__name__)

# The key each returned record is tagged with, so the drain maps a record back to the prospect it
# enriched without trusting response ordering. Underscore-prefixed so it can never collide with a
# provider field the parser reads.
PLACE_TAG = "_place_id"


def _enrichment_param(enrichments: list[str]) -> Any:
    """The `enrichment` value for the wire. GET /maps/search-v3 takes a comma-joined string (how
    platform-api sends multi-valued params); POST /google-maps-search takes a JSON list. Returning
    the right shape here keeps the request builder below simple."""
    return list(enrichments)


async def _enrich_one(
    oc: OutscraperClient, settings: Settings, place_id: str, enrichments: list[str]
) -> list[dict[str, Any]]:
    """Enrich one place_id synchronously and return its record(s), each tagged with the place_id.

    Synchronous (async=false) like the pixel_probe spike: one place returns fast, and the sync path
    avoids the submit/poll dance for what is a single lookup. A slow enriched pull is exactly the
    shape that hits the timeout, which is why enrichment gets its own generous
    `enrich_request_timeout_seconds`, clear of the 60s base.
    """
    endpoint = settings.outscraper_search_endpoint
    enrichment = _enrichment_param(enrichments)
    if endpoint == ENDPOINT_MAPS_SEARCH:
        payload: dict[str, Any] = {
            "query": [place_id],
            "organizationsPerQueryLimit": 1,
            "language": settings.outscraper_language,
            "region": settings.outscraper_region,
            "async": False,
            "enrichment": enrichment,
        }
        body = await oc._request("POST", endpoint, json=payload)  # noqa: SLF001 — enrichment path
    else:
        params = {
            "query": place_id,
            "organizationsPerQueryLimit": 1,
            "language": settings.outscraper_language,
            "region": settings.outscraper_region,
            "async": "false",
            # GET carries repeated params for a list; httpx serializes a list value as repeats.
            "enrichment": enrichment,
        }
        body = await oc._request("GET", endpoint, params=params)  # noqa: SLF001 — enrichment path

    records = extract_places(body)
    for record in records:
        if isinstance(record, dict):
            record[PLACE_TAG] = place_id
    return records


async def enrich_places(
    settings: Settings,
    place_ids: list[str],
    *,
    enrichments: list[str],
    client: httpx.AsyncClient | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Enrich a set of place_ids. Returns `(records, errors)`.

    Each record carries its place_id under `PLACE_TAG`. Requests run concurrently, bounded by
    `enrich_chunk_size`, on ONE shared client. A per-place failure is REPORTED (never swallowed into
    "no contacts anywhere") and does not abort the rest — every place is billed independently.

    The enricher timeout is applied by building the shared client here; a caller passing its own
    client owns its timeout.
    """
    ids = [p for p in dict.fromkeys(place_ids) if p]  # de-dupe, preserve order, drop blanks
    if not ids:
        return [], []

    owns = client is None
    http = client or httpx.AsyncClient(timeout=settings.enrich_request_timeout_seconds)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    sample_logged = False
    sem = asyncio.Semaphore(max(1, settings.enrich_chunk_size))

    async def _guarded(place_id: str) -> None:
        nonlocal sample_logged
        async with sem:
            try:
                async with OutscraperClient(settings, client=http) as oc:
                    got = await _enrich_one(oc, settings, place_id, enrichments)
            except Exception as exc:  # noqa: BLE001 — a billed place already spent; keep the rest
                errors.append(f"{place_id}: {str(exc)[:200]}")
                logger.warning(
                    "enrich place failed", extra={"place_id": place_id, "error": str(exc)[:300]}
                )
                return
            if got and not sample_logged:
                sample_logged = True
                logger.info("enrich sample record", extra={"raw": str(got[0])[:4000]})
            records.extend(got)

    try:
        await asyncio.gather(*(_guarded(pid) for pid in ids))
    finally:
        if owns:
            await http.aclose()
    return records, errors
