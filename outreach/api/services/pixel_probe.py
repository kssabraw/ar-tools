"""§16a.1 verification spike — is a Meta pixel in the Outscraper ENRICHMENT pull? (ISSUES I-003).

**The assumption under test** (PRD §16a.1): that Meta-pixel presence arrives in the same enrichment
pull as listings and contacts, making it a market-wide, near-free money signal. If it does, the Meta
half of Slice B1 is cheaper than a per-prospect site fetch; if GTM-injected pixels are largely
missed, the §B3 site fetch (built) stays the primary source and the money-signal cost model holds.

**This is a SPIKE, isolated from the ingest path on purpose.** `outscraper_client.submit_maps_search`
carries a hard invariant — "Base tier only … do not populate `enrichment`, and do not add a config
flag that would let someone else" — which protects the MASS ingest (thousands of places) from
silently turning on billed enrichment. A one-off enriched sample of ~5–10 places is a different,
deliberate, gated act, so it lives here in its own request builder and never touches that method.

**Measure-don't-infer** (the `dataforseo_client.py` discipline): the exact enrichment field name for
a pixel is UNKNOWN against this account, so the parser does not assert one. `scan_place_for_pixel`
scans a place record for pixel INDICATORS by key and value, and `fetch_enriched_sample` logs one full
record so the real envelope is recoverable from the log. The command BILLS (enrichment is billed), so
it is gated in `PAID_COMMANDS`.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

# Key names an enrichment might use for a pixel/tech field — matched loosely because the exact name
# is unmeasured. A KEY hit is weaker evidence than a VALUE hit (a key named "pixel_id" with a null
# value proves the field exists but not that this business has one), so the two are reported apart.
_PIXEL_KEY_HINTS = re.compile(r"pixel|facebook|(?:^|_)fb(?:_|$)|meta_tag|tracking|analytics|gtm", re.I)

# Value signatures — the same fingerprints the site-fetch detector uses, so a "found" here means the
# same thing as a B1 detection.
_PIXEL_VALUE_MARKERS = (
    re.compile(r"connect\.facebook\.net", re.I),
    re.compile(r"\bfbq\b", re.I),
    re.compile(r"facebook\.com/tr", re.I),
    re.compile(r"\bGTM-[A-Z0-9]{4,}\b"),
    re.compile(r"\bAW-\d{6,}\b"),
)


def _walk(value: Any, path: str = "") -> list[tuple[str, Any]]:
    """Flatten a nested record into (dotted-key, scalar-value) pairs. Pure."""
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.extend(_walk(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.extend(_walk(v, f"{path}[{i}]"))
    else:
        out.append((path, value))
    return out


def scan_place_for_pixel(place: dict[str, Any]) -> dict[str, Any]:
    """Scan one enriched place record for Meta-pixel (and adjacent tag) indicators. Pure.

    Returns `key_hints` (fields whose NAME suggests a pixel/tech field — the field EXISTS), and
    `value_hits` (fields whose VALUE matches a pixel signature — this business HAS one). `found` is a
    value hit, the strong signal; a key hint without a value hit means the enrichment carries the
    field but this record didn't populate it (which is itself the §16a.1 answer for coverage)."""
    pairs = _walk(place)
    key_hints: list[str] = []
    value_hits: list[dict[str, Any]] = []
    for key, value in pairs:
        leaf = key.split(".")[-1].split("[")[0]
        if _PIXEL_KEY_HINTS.search(leaf):
            key_hints.append(key)
        if isinstance(value, str) and value and any(m.search(value) for m in _PIXEL_VALUE_MARKERS):
            value_hits.append({"key": key, "value": value[:200]})
    return {
        "found": bool(value_hits),
        "key_hints": sorted(set(key_hints)),
        "value_hits": value_hits,
    }


def summarize_pixel_probe(
    records: list[dict[str, Any]], errors: list[str] | None = None
) -> dict[str, Any]:
    """Aggregate the spike over its sample — the answer §16a.1 wants. Pure.

    `found_rate` is the share of records with a value hit; `carries_field` is the share with any key
    hint (the field being PRESENT in the envelope even when unpopulated). A high carries_field with a
    low found_rate is the "field exists but is sparse" outcome that argues the site fetch stays
    primary.

    `errors` are the queries that failed. They are reported ALONGSIDE the results rather than
    replacing them: this spike BILLS per query, so a failure on query 4 must not discard what
    queries 1–3 were charged for (the rates are then computed over what actually came back, and the
    error list says how much of the sample is missing).
    """
    n = len(records)
    scans = [scan_place_for_pixel(r) for r in records]
    found = sum(1 for s in scans if s["found"])
    carries = sum(1 for s in scans if s["key_hints"])
    all_hint_keys = sorted({k for s in scans for k in s["key_hints"]})
    return {
        "sample": n,
        "found": found,
        "found_rate": round(found / n, 3) if n else 0.0,
        "carries_field": carries,
        "carries_field_rate": round(carries / n, 3) if n else 0.0,
        "field_names_seen": all_hint_keys,
        "errors": list(errors or []),
        "per_record": scans,
    }


async def fetch_enriched_sample(
    settings: Settings,
    queries: list[str],
    *,
    enrichment: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch a SMALL enriched sample — the spike's one billed act. Isolated from the ingest path.

    Builds its own request rather than calling `submit_maps_search` (whose base-tier invariant must
    not be bent). Logs one full record so the enrichment envelope is measured, not inferred.

    Returns `(records, errors)`. **Each query is isolated**, because every query is BILLED: a
    ReadTimeout on query 4 (a synchronous enriched pull is exactly the shape that hits the 60s
    timeout, and `httpx.ReadTimeout` is deliberately NOT in `FAILOVER_ERRORS`, so it propagates)
    used to abort the loop and discard the records queries 1–3 had already been charged for. The
    failure is REPORTED, never swallowed into "no pixel anywhere" — an outage must not answer the
    question the spike is asking.
    """
    # Imported once, not per iteration.
    from .outscraper_client import OutscraperClient, extract_places

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    logged_sample = False
    async with OutscraperClient(settings, client=client) as oc:
        # A synchronous enriched pull for a handful of queries — the SDK's search endpoint with an
        # explicit enrichment param. Deliberately not the async tile lifecycle: this is ~N places,
        # not a market.
        endpoint = settings.outscraper_search_endpoint
        for query in queries:
            params = {
                "query": query,
                "organizationsPerQueryLimit": 1,
                "language": settings.outscraper_language,
                "region": settings.outscraper_region,
                "async": "false",
                "enrichment": enrichment,
            }
            try:
                body = await oc._request("GET", endpoint, params=params)  # noqa: SLF001 — spike
            except Exception as exc:  # noqa: BLE001 — a billed query already spent; keep the rest
                errors.append(f"{query}: {str(exc)[:200]}")
                logger.warning("pixel probe query failed", extra={"query": query, "error": str(exc)[:300]})
                continue
            if not logged_sample:
                # Once per RUN (not "while records is empty") — a first query returning no places
                # would otherwise log the sample again on every following query.
                logged_sample = True
                logger.info("pixel probe sample record", extra={"raw": str(body)[:4000]})
            records.extend(extract_places(body))
    return records, errors
