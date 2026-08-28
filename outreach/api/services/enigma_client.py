"""Enigma SMB-intelligence client — the last-rung contacts source + card-transaction data.

Enigma (`docs/enigma-integration-scoping-v0_1.md`) is a two-step REST API: **match** a business by
its identifiers (name + address / website / person) to get an Enigma business **id**, then **get
attributes** for that id (firmographics, principals/owner names, and card-transaction activity over
Enigma's native 1m / 3m / 12m windows). Auth is the `x-api-key` header.

**The exact contract is UNCONFIRMED from the sandbox** — `api.enigma.com` is egress-blocked here, so
this module cannot be tested against the real API from the dev environment. It is written to the
DOCUMENTED shape (base `https://api.enigma.com`, `POST {match_path}` with a
`{name, address, website, person}` body → matched profiles with ids; `GET {business_path}/{id}?attrs=`
→ attributes), with EVERYTHING url-shaped in config so a wrong path is an env fix, not a code change.
Its job in `probe-enigma` is to run the calls and hand back the FULL RAW envelope of each so the real
schema is captured on the first live Railway run — the "measured on first run, not asserted"
discipline of `dataforseo_client` / `probe-enrich`. No field name is assumed; parsing the useful
bits out lives in the pure `enigma_probe` helpers, which are tolerant and never raise.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class EnigmaError(Exception):
    """A transport/HTTP failure talking to Enigma. Carries the status + a clipped body for the log."""


@dataclass
class EnigmaCall:
    """One HTTP round-trip to Enigma, captured whole so the probe can log the real envelope.

    `raw` is the parsed JSON when the body parsed, else None; `body_text` is always the raw text
    (clipped) so a non-JSON error page is still recoverable. `ok` is a 2xx with a parsed body."""

    method: str
    url: str
    status: int | None = None
    raw: Any = None
    body_text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and self.raw is not None


def _headers(settings: Settings) -> dict[str, str]:
    """Headers for the POST match (carries a JSON body)."""
    return {"x-api-key": settings.enigma_api_key, "Content-Type": "application/json",
            "Accept": "application/json"}


def _get_headers(settings: Settings) -> dict[str, str]:
    """Headers for the bodyless GET attributes call. Deliberately NO `Content-Type: application/json`
    — a GET sends no body, and declaring a JSON content type made Enigma's gateway try to parse an
    empty body and return `400 {"Code":"BadRequestError","Message":"Error Parsing JSON"}` on the first
    probe. Only `x-api-key` + `Accept` here."""
    return {"x-api-key": settings.enigma_api_key, "Accept": "application/json"}


def _biz_body(biz: dict[str, Any]) -> dict[str, Any]:
    """The match request body, from a prospect's identifiers. Only non-empty keys are sent (Enigma
    matches on whatever is provided). Address is split into the documented sub-fields; `person` is
    included only when a name is known (it is for the 'named' control sample)."""
    body: dict[str, Any] = {}
    if biz.get("name"):
        body["name"] = str(biz["name"]).strip()
    addr = {
        k: str(biz[src]).strip()
        for k, src in (("street_address1", "street"), ("city", "city"),
                       ("state", "state"), ("postal_code", "postal_code"))
        if biz.get(src)
    }
    if addr:
        body["address"] = addr
    if biz.get("website"):
        body["website"] = str(biz["website"]).strip()
    person = {k: str(biz[k]).strip() for k in ("first_name", "last_name") if biz.get(k)}
    if person:
        body["person"] = person
    return body


async def match_business(client: httpx.AsyncClient, settings: Settings, biz: dict[str, Any]) -> EnigmaCall:
    """POST the match request. Never raises — a failure is recorded on the returned EnigmaCall so the
    probe can report it per-prospect (one bad match must not abort the sample)."""
    url = f"{settings.enigma_base_url.rstrip('/')}{settings.enigma_match_path}"
    call = EnigmaCall(method="POST", url=url)
    try:
        resp = await client.post(url, headers=_headers(settings), json=_biz_body(biz))
        call.status = resp.status_code
        call.body_text = resp.text[:4000]
        try:
            call.raw = resp.json()
        except Exception:  # noqa: BLE001 — a non-JSON body (error page) is still captured as text
            call.raw = None
    except Exception as exc:  # noqa: BLE001 — transport error; record, don't raise
        call.error = repr(exc)[:300]
    return call


async def get_attributes(client: httpx.AsyncClient, settings: Settings, enigma_id: str) -> EnigmaCall:
    """GET the attributes for a matched id (`?attrs=` selects datasets when configured). Never raises."""
    base = f"{settings.enigma_base_url.rstrip('/')}{settings.enigma_business_path.rstrip('/')}"
    url = f"{base}/{enigma_id}"
    params: dict[str, str] = {}
    if settings.enigma_attrs.strip():
        params["attrs"] = settings.enigma_attrs.strip()
    # lookback_months only means anything for the time-series (card) attributes; harmless otherwise.
    if str(settings.enigma_lookback_months).strip():
        params["lookback_months"] = str(settings.enigma_lookback_months).strip()
    call = EnigmaCall(method="GET", url=url)
    try:
        resp = await client.get(url, headers=_get_headers(settings), params=params or None)
        call.status = resp.status_code
        call.body_text = resp.text[:6000]
        try:
            call.raw = resp.json()
        except Exception:  # noqa: BLE001
            call.raw = None
    except Exception as exc:  # noqa: BLE001
        call.error = repr(exc)[:300]
    return call


@dataclass
class LookupResult:
    """One prospect's full Enigma round-trip: the identifiers we sent, both raw calls, and the
    best-effort extracted id. Extraction of names/card data is the caller's (pure) job — this keeps
    the raw so nothing is lost to a wrong assumption."""

    prospect_id: str = ""
    biz: dict[str, Any] = field(default_factory=dict)
    match_call: EnigmaCall | None = None
    id_call: EnigmaCall | None = None
    enigma_id: str = ""


async def lookup_one(client: httpx.AsyncClient, settings: Settings, prospect: dict[str, Any],
                     extract_id) -> LookupResult:
    """Match one prospect, then (if an id came back) fetch its attributes. `extract_id` is the pure
    `enigma_probe.match_id_from_response` — injected so this module stays free of parse assumptions."""
    result = LookupResult(prospect_id=str(prospect.get("id") or ""), biz=prospect)
    result.match_call = await match_business(client, settings, prospect)
    if result.match_call.ok:
        result.enigma_id = extract_id(result.match_call.raw) or ""
        if result.enigma_id:
            result.id_call = await get_attributes(client, settings, result.enigma_id)
    # Log the raw envelopes so the real schema is captured on the first live run (the whole point).
    logger.info(
        "enigma lookup",
        extra={
            "prospect_id": result.prospect_id,
            "match_status": getattr(result.match_call, "status", None),
            "match_url": result.match_call.url,
            "enigma_id": result.enigma_id,
            "match_raw": result.match_call.body_text,
            "id_status": getattr(result.id_call, "status", None) if result.id_call else None,
            "id_raw": result.id_call.body_text if result.id_call else None,
        },
    )
    return result


async def lookup_many(settings: Settings, prospects: list[dict[str, Any]], extract_id,
                      *, concurrency: int = 5) -> list[LookupResult]:
    """Look up a sample of prospects with bounded concurrency. Per-prospect isolation (the probe-enrich
    lesson): one prospect's failure is recorded on its result, never aborts the sample."""
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(timeout=settings.enigma_request_timeout_seconds) as client:
        async def _run(p: dict[str, Any]) -> LookupResult:
            async with sem:
                try:
                    return await lookup_one(client, settings, p, extract_id)
                except Exception as exc:  # noqa: BLE001 — never let one prospect break the gather
                    logger.warning("enigma lookup crashed", extra={"error": repr(exc)[:200]})
                    return LookupResult(prospect_id=str(p.get("id") or ""), biz=p)

        return await asyncio.gather(*[_run(p) for p in prospects])
