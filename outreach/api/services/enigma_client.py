"""Enigma GraphQL client — match a prospect to its Enigma business + people, BY prospect.

POSTs to Enigma's GraphQL endpoint (`enigma_api_url`) with the key in the `x-api-key` header, per
Enigma's docs. One request per prospect, run CONCURRENTLY (bounded) — Enigma bills per resolved
business, so per-prospect isolation buys robustness (one failing lookup loses one prospect, not the
batch) exactly like `enrich_client.enrich_places`.

**THE QUERY IS THE ONE CORRECTION POINT (ISSUES I-Enigma).** No live Enigma call has run, so the
selection-set field names below (`cardRevenueAmount`, `people`, `title`, …) are a best-effort against
Enigma's published shape (Relay `edges/node`; entities Brand / LegalEntity / Person; auth via
`x-api-key`; the `search(searchInput:{name,entityType,address})` form from Enigma's own example) and
are UNCONFIRMED. GraphQL validates the whole query against its schema, so a wrong field name fails
the entire request with an `errors` block — which this client surfaces as a retryable failure (never
a silent `no_match`), so the first live run reports exactly which fields to correct here. Fix
`_SELECTION` / `_build_query`; nothing else needs to change (the parse is already shape-tolerant).

Gated inert: callers check `settings.enigma_api_key` before invoking this module; with no key the
integration does nothing and spends nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class EnigmaError(Exception):
    """A transport or provider error from an Enigma call (retryable)."""


class EnigmaQueryError(EnigmaError):
    """The response carried a GraphQL `errors` block — almost always a wrong field name in
    `_SELECTION` while the shape is being confirmed. Retryable, and the message names the bad
    fields."""


# The selection set — the correction point. Requests the brand id + name, its firmographics
# (revenue / growth / location count), and its legal entities' people (the owners/officers) with
# their titles and any contact coordinates. Field names are provisional (see the module docstring).
_SELECTION = """
    ... on Brand {
      id
      names { edges { node { name } } }
      cardRevenueAmount
      cardRevenueGrowth
      locationCount
      website
      operatingLocations { edges { node {
        addresses(first: 1) { edges { node { fullAddress } } }
      } } }
      legalEntities { edges { node {
        id
        names { edges { node { name } } }
        people { edges { node {
          fullName
          title
          email
          phone
        } } }
      } } }
    }
"""


def _parse_city_state(address: Any) -> tuple[str | None, str | None]:
    """Best-effort (city, state) from a US full-address string. Returns (None, None) when it cannot
    tell — in which case the query searches by name alone and our own match gate carries the weight.
    """
    if not address:
        return None, None
    parts = [p.strip() for p in str(address).split(",")]
    for i in range(len(parts) - 1, -1, -1):
        m = re.match(r"^([A-Za-z]{2})\s+\d{5}", parts[i])  # "CA 92801"
        if m:
            city = parts[i - 1] if i - 1 >= 0 else None
            return (city or None), m.group(1).upper()
    return None, None


def _build_query(prospect: dict[str, Any]) -> str:
    """The GraphQL query string for one prospect. Values are JSON-escaped (GraphQL string literals
    accept JSON escaping), so a name with a quote cannot break the query."""
    name = prospect.get("name") or ""
    city, state = _parse_city_state(prospect.get("address"))
    if city and state:
        addr = f",address:{{city:{json.dumps(city)},state:{json.dumps(state)}}}"
    elif state:
        addr = f",address:{{state:{json.dumps(state)}}}"
    else:
        addr = ""
    search_input = f"{{name:{json.dumps(name)},entityType:BRAND{addr}}}"
    return "query { search(searchInput: " + search_input + ") {" + _SELECTION + "} }"


async def match_prospect(
    settings: Settings, prospect: dict[str, Any], *, client: httpx.AsyncClient
) -> dict[str, Any]:
    """One Enigma lookup. Returns the raw JSON response (the caller keeps it in `raw`).

    Raises `EnigmaQueryError` when the response carries GraphQL `errors` and no usable data, and
    `EnigmaError` on a non-2xx transport status — both retryable, so a wrong query or a provider
    blip never lands as a terminal `no_match`."""
    query = _build_query(prospect)
    resp = await client.post(
        settings.enigma_api_url,
        headers={"x-api-key": settings.enigma_api_key, "content-type": "application/json"},
        json={"query": query},
    )
    if resp.status_code >= 400:
        raise EnigmaError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise EnigmaError(f"non-JSON response: {resp.text[:300]}") from exc

    errors = body.get("errors") if isinstance(body, dict) else None
    has_data = isinstance(body, dict) and body.get("data") not in (None, {}, [])
    if errors and not has_data:
        raise EnigmaQueryError(str(errors)[:500])
    return body


async def match_prospects(
    settings: Settings,
    prospects: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Match a batch of prospects concurrently (bounded by `enigma_chunk_size`), on one shared
    client. Returns `(results, errors)` where each result is `(prospect_id, raw_response)`. A
    per-prospect failure is REPORTED (`"<prospect_id>: <msg>"`) and never aborts the rest — every
    resolved business is billed independently."""
    if not prospects:
        return [], []

    owns = client is None
    http = client or httpx.AsyncClient(timeout=settings.enigma_request_timeout_seconds)
    results: list[tuple[str, dict[str, Any]]] = []
    errors: list[str] = []
    sample_logged = False
    sem = asyncio.Semaphore(max(1, settings.enigma_chunk_size))

    async def _guarded(prospect: dict[str, Any]) -> None:
        nonlocal sample_logged
        pid = prospect["id"]
        async with sem:
            try:
                body = await match_prospect(settings, prospect, client=http)
            except Exception as exc:  # noqa: BLE001 — a billed lookup already spent; keep the rest
                errors.append(f"{pid}: {str(exc)[:200]}")
                logger.warning("enigma match failed", extra={"prospect_id": pid,
                                                             "error": str(exc)[:300]})
                return
            if not sample_logged:
                sample_logged = True
                logger.info("enigma sample response", extra={"raw": str(body)[:4000]})
            results.append((pid, body))

    try:
        await asyncio.gather(*(_guarded(p) for p in prospects))
    finally:
        if owns:
            await http.aclose()
    return results, errors
