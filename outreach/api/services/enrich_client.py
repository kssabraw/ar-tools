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

**Async is mandatory (confirmed live 2026-08-26, I-109).** Enrichments run asynchronously on
Outscraper; a synchronous (`async=false`) call returns the base Maps record BEFORE the enrichers
finish, so it carries no emails/contacts/people — only the business name in `name_for_emails`. Two
`probe-enrich` runs proved it: our production enricher set (`domains_service` + validators) against
a business with known LinkedIn/Apollo contacts still returned a bare Maps record. So `_enrich_one`
now submits `async=true` and polls the archive (`fetch_result`) to completion, the same pair the
mass ingest uses — the only path that actually yields the enrichers' output. `enrichments` is still
passed through verbatim from config; the response is read defensively by `enrichment.parse_contacts`
and `probe-enrich` still logs one full record so a new enricher's shape can be confirmed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..config import Settings
from .outscraper_client import (
    ENDPOINT_MAPS_SEARCH,
    OutscraperClient,
    OutscraperError,
    extract_places,
)

logger = logging.getLogger(__name__)

# The key each returned record is tagged with, so the drain maps a record back to the prospect it
# enriched without trusting response ordering. Underscore-prefixed so it can never collide with a
# provider field the parser reads.
PLACE_TAG = "_place_id"


def _enrichment_param(enrichments: list[str], endpoint: str) -> Any:
    """The `enrichment` value for the wire, shaped for the endpoint.

    GET /maps/search-v3 gets a single comma-joined query value (unambiguous to serialize — no reliance
    on httpx's list-repeat behaviour, and the shape pixel_probe's single-enricher call already uses);
    POST /google-maps-search gets a JSON list. Which form Outscraper actually wants for a MULTI-valued
    set is unconfirmed against this account (measure-don't-infer, ISSUES I-109) — `probe-enrich`
    settles it, and this is the one line to change if it disagrees."""
    if endpoint == ENDPOINT_MAPS_SEARCH:
        return list(enrichments)
    return ",".join(enrichments)


async def _enrich_one(
    oc: OutscraperClient, settings: Settings, place_id: str, enrichments: list[str]
) -> list[dict[str, Any]]:
    """Enrich one place_id ASYNC (submit → poll the archive) and return its record(s), tagged.

    Enrichments run asynchronously on Outscraper: a synchronous (async=false) call returns the base
    Maps record BEFORE the enrichers finish — i.e. with no emails, no scraped contacts, no person
    fields at all, only `name_for_emails` (the business name). That was the real cause of "enrich
    just restates the business name" — confirmed live 2026-08-26 by two `probe-enrich` runs, one
    with `domains_service` against a business KNOWN to have contact data, which still came back with
    zero enrichment fields (ISSUES I-109). So we submit async and poll to completion, exactly like
    the mass-ingest `submit_maps_search`/`fetch_result` pair — the only path that actually returns
    the enrichers' output. Per-place poll ceiling is `enrich_poll_timeout_seconds` so a single
    stuck place fails on its own rather than hanging the tick.
    """
    endpoint = settings.outscraper_search_endpoint
    enrichment = _enrichment_param(enrichments, endpoint)
    if endpoint == ENDPOINT_MAPS_SEARCH:
        payload: dict[str, Any] = {
            "query": [place_id],
            "organizationsPerQueryLimit": 1,
            "language": settings.outscraper_language,
            "region": settings.outscraper_region,
            "async": True,
            "enrichment": enrichment,
        }
        submit = await oc._request("POST", endpoint, json=payload)  # noqa: SLF001 — enrichment path
    else:
        params = {
            "query": place_id,
            "organizationsPerQueryLimit": 1,
            "language": settings.outscraper_language,
            "region": settings.outscraper_region,
            # Booleans go over the wire as lowercase strings on GET, as the base search does.
            "async": "true",
            # `enrichment` is a single comma-joined value on GET (see `_enrichment_param`).
            "enrichment": enrichment,
        }
        submit = await oc._request("GET", endpoint, params=params)  # noqa: SLF001 — enrichment path

    request_id = submit.get("id")
    if not request_id:
        # No request id: either a body-level error the client would have raised, or a response that
        # already carried its data inline. Use inline data if present; otherwise it is a real fault.
        inline = extract_places(submit)
        if not inline:
            raise OutscraperError(
                f"enrichment submission for {place_id} returned no request id and no data: {submit!r}"
            )
        records = inline
    else:
        archive = await oc.fetch_result(
            str(request_id), poll_timeout=settings.enrich_poll_timeout_seconds
        )
        records = extract_places(archive)

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
