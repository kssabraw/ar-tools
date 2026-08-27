"""Enigma GraphQL client + pure parsers — the path that returns card windows + owner contact.

`POST {enigma_graphql_url}` with `{query, variables}` and the `x-api-key` header. One synchronous
`search` query per business matches it (BRAND) and returns, in a single call:
  - `cardTransactions` filtered to `card_revenue_amount` over the 1m / 3m / 12m windows, and
  - `operatingLocations → roles → legalEntities → persons` (owner name) + job title / management
    level / job function / phone / email.
See `outreach/docs/enigma-graphql-api-reference.md` for the contract (the REST match/ID path in
`enigma_client.py` is the superseded first probe — it returned no card data on the eval key).

The client logs the FULL raw envelope of every call (the measure-don't-infer discipline) so the real
response shape is captured on the first live Railway run. The parsers here are pure and tolerant of
the Relay `edges/node` nesting: a shape they don't recognise yields None/empty, never raises.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import Settings
from .enigma_client import EnigmaCall  # reuse the captured-round-trip record

logger = logging.getLogger(__name__)

# The probe query: match a BRAND by name+address, then pull the two payloads we care about. Mirrors
# the entity path behind the owner's console-batch output columns (operatingLocations→roles→persons)
# and requests all three card-revenue windows (the batch export only carried 12m).
SEARCH_QUERY = """
query Probe($si: SearchInput!) {
  search(searchInput: $si) {
    ... on Brand {
      enigmaId
      names(first: 1) { edges { node { name } } }
      cardTransactions(conditions: { filter: { AND: [
        { EQ: ["quantityType", "card_revenue_amount"] },
        { IN: ["period", ["1m", "3m", "12m"]] }
      ] } }) {
        edges { node { period projectedQuantity rawQuantity periodStartDate periodEndDate } }
      }
      operatingLocations(first: 1) {
        edges { node { roles(first: 3) { edges { node {
          jobTitle jobFunction managementLevel
          legalEntities(first: 1) { edges { node { persons(first: 1) { edges { node {
            fullName firstName lastName
          } } } } } }
          phoneNumbers(first: 1) { edges { node { phoneNumber } } }
          emailAddresses(first: 1) { edges { node { emailAddress } } }
        } } } } }
      }
    }
  }
}
""".strip()


def build_variables(biz: dict[str, Any], match_threshold: float) -> dict[str, Any]:
    """The `searchInput` for one prospect, from its identifiers. Only non-empty address parts are
    sent. Matches at BRAND level (the console batch's entity path)."""
    si: dict[str, Any] = {"entityType": "BRAND", "matchThreshold": match_threshold}
    if biz.get("name"):
        si["name"] = str(biz["name"]).strip()
    addr = {
        k: str(biz[src]).strip()
        for k, src in (("street1", "street"), ("city", "city"),
                       ("state", "state"), ("postalCode", "postal_code"))
        if biz.get(src)
    }
    if addr:
        si["address"] = addr
    if biz.get("website"):
        si["website"] = str(biz["website"]).strip()
    return {"si": si}


def _headers(settings: Settings) -> dict[str, str]:
    return {"x-api-key": settings.enigma_api_key, "content-type": "application/json",
            "Accept": "application/json"}


async def search_business(client: httpx.AsyncClient, settings: Settings,
                          biz: dict[str, Any]) -> EnigmaCall:
    """POST one GraphQL search. Never raises — a transport/HTTP failure is recorded on the returned
    EnigmaCall so one bad lookup can't abort the sample."""
    url = settings.enigma_graphql_url
    call = EnigmaCall(method="POST", url=url)
    body = {"query": SEARCH_QUERY, "variables": build_variables(biz, settings.enigma_graphql_match_threshold)}
    try:
        resp = await client.post(url, headers=_headers(settings), json=body)
        call.status = resp.status_code
        call.body_text = resp.text[:8000]
        try:
            call.raw = resp.json()
        except Exception:  # noqa: BLE001 — a non-JSON body (error page) is still captured as text
            call.raw = None
    except Exception as exc:  # noqa: BLE001 — transport error; record, don't raise
        call.error = repr(exc)[:300]
    return call


# --- pure parsers over the GraphQL response --------------------------------------------------------


def _nodes(conn: Any) -> list[Any]:
    """The node objects of a Relay connection, tolerant of missing/odd shapes."""
    if not isinstance(conn, dict):
        return []
    out = []
    for edge in conn.get("edges") or []:
        if isinstance(edge, dict) and isinstance(edge.get("node"), dict):
            out.append(edge["node"])
    return out


def _first_node(conn: Any) -> dict[str, Any] | None:
    ns = _nodes(conn)
    return ns[0] if ns else None


def first_brand(raw: Any) -> dict[str, Any] | None:
    """The top matched Brand object from a GraphQL response, or None. `search` returns a list ranked
    best-first; we take the first dict that carries our fields."""
    if not isinstance(raw, dict):
        return None
    results = ((raw.get("data") or {}).get("search")) if isinstance(raw.get("data"), dict) else None
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and (item.get("enigmaId") or item.get("names") or item.get("cardTransactions")):
            return item
    return None


def extract_enigma_id(brand: Any) -> str | None:
    if isinstance(brand, dict):
        v = brand.get("enigmaId")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def extract_card_windows(brand: Any) -> dict[str, Any] | None:
    """`{period: projected_amount}` for `card_revenue_amount` over 1m/3m/12m, or None. Prefers the
    projected (panel-scaled) figure — the console export's `Card_revenue_amount_12M` value — and
    falls back to the raw quantity when projected is null (compliance floor)."""
    if not isinstance(brand, dict):
        return None
    out: dict[str, Any] = {}
    for node in _nodes(brand.get("cardTransactions")):
        period = node.get("period")
        if period in ("1m", "3m", "12m") and period not in out:
            amt = node.get("projectedQuantity")
            if amt is None:
                amt = node.get("rawQuantity")
            if amt is not None:
                out[period] = amt
    return out or None


def _person_name(role: dict[str, Any]) -> str | None:
    for le in _nodes(role.get("legalEntities")):
        for person in _nodes(le.get("persons")):
            full = person.get("fullName")
            if isinstance(full, str) and full.strip():
                return full.strip()
            first = str(person.get("firstName") or "").strip()
            last = str(person.get("lastName") or "").strip()
            name = f"{first} {last}".strip()
            if name:
                return name
    return None


def extract_owner(brand: Any) -> dict[str, Any] | None:
    """The best decision-maker record from `operatingLocations → roles`, or None. Prefers a role that
    resolves to a named person; falls back to the first role carrying a title. Returns
    `{full_name, job_title, management_level, job_function, phone, email}` (any may be None)."""
    if not isinstance(brand, dict):
        return None
    ol = _first_node(brand.get("operatingLocations"))
    if not ol:
        return None
    roles = _nodes(ol.get("roles"))
    if not roles:
        return None

    def _record(role: dict[str, Any], name: str | None) -> dict[str, Any]:
        phone = _first_node(role.get("phoneNumbers"))
        email = _first_node(role.get("emailAddresses"))
        return {
            "full_name": name,
            "job_title": (role.get("jobTitle") or None),
            "management_level": (role.get("managementLevel") or None),
            "job_function": (role.get("jobFunction") or None),
            "phone": (phone.get("phoneNumber") if phone else None),
            "email": (email.get("emailAddress") if email else None),
        }

    for role in roles:
        name = _person_name(role)
        if name:
            return _record(role, name)
    # No named person on any role — return the first role's title/contact (still useful signal).
    first = roles[0]
    rec = _record(first, None)
    return rec if any(rec.get(k) for k in ("job_title", "phone", "email")) else None


# --- lookup orchestration + probe metrics ----------------------------------------------------------


@dataclass
class GraphqlLookup:
    prospect_id: str = ""
    biz: dict[str, Any] = field(default_factory=dict)
    call: EnigmaCall | None = None
    brand: dict[str, Any] | None = None
    enigma_id: str = ""


async def lookup_one(client: httpx.AsyncClient, settings: Settings,
                     prospect: dict[str, Any]) -> GraphqlLookup:
    result = GraphqlLookup(prospect_id=str(prospect.get("id") or ""), biz=prospect)
    result.call = await search_business(client, settings, prospect)
    if result.call.ok:
        result.brand = first_brand(result.call.raw)
        result.enigma_id = extract_enigma_id(result.brand) or ""
    logger.info(
        "enigma graphql lookup",
        extra={
            "prospect_id": result.prospect_id,
            "status": getattr(result.call, "status", None),
            "enigma_id": result.enigma_id,
            "owner": extract_owner(result.brand),
            "card": extract_card_windows(result.brand),
            "raw": result.call.body_text if result.call else None,
        },
    )
    return result


async def lookup_many(settings: Settings, prospects: list[dict[str, Any]],
                      *, concurrency: int = 5) -> list[GraphqlLookup]:
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(timeout=settings.enigma_request_timeout_seconds) as client:
        async def _run(p: dict[str, Any]) -> GraphqlLookup:
            async with sem:
                try:
                    return await lookup_one(client, settings, p)
                except Exception as exc:  # noqa: BLE001 — never let one prospect break the gather
                    logger.warning("enigma graphql lookup crashed", extra={"error": repr(exc)[:200]})
                    return GraphqlLookup(prospect_id=str(p.get("id") or ""), biz=p)

        return await asyncio.gather(*[_run(p) for p in prospects])


def probe_metrics(results: list[Any], unnamed_prospect_ids: set[str]) -> dict[str, Any]:
    """The scoping §3 decision metrics over GraphqlLookup results.

    - match_rate: share that matched a Brand with an enigma id.
    - owner_name_hit_on_unnamed: of the prospects the existing ladder could NOT name, share Enigma
      gave a principal NAME (the headline contacts number).
    - card_fill_of_matched: of the matched, share with any 1m/3m/12m card-revenue window.
    """
    total = len(results)
    matched = [r for r in results if getattr(r, "enigma_id", "")]
    unnamed = [r for r in results if getattr(r, "prospect_id", "") in unnamed_prospect_ids]

    def _owner_name(r: Any) -> str | None:
        owner = extract_owner(getattr(r, "brand", None))
        return owner.get("full_name") if owner else None

    unnamed_named = [r for r in unnamed if _owner_name(r)]
    card_filled = [r for r in matched if extract_card_windows(getattr(r, "brand", None))]

    def _rate(n: int, d: int) -> float:
        return round(n / d, 3) if d else 0.0

    return {
        "total": total,
        "matched": len(matched),
        "match_rate": _rate(len(matched), total),
        "unnamed_sampled": len(unnamed),
        "owner_name_hits_on_unnamed": len(unnamed_named),
        "owner_name_hit_on_unnamed": _rate(len(unnamed_named), len(unnamed)),
        "card_windows_present": len(card_filled),
        "card_fill_of_matched": _rate(len(card_filled), len(matched)),
    }
