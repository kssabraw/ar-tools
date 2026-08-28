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

# The probe query pulls the two payloads we care about — card-revenue windows (1m/3m/12m) and the
# owner (roles → legalEntities → Person-typed name + title/mgmt/phone/email). Roles live either under
# a Brand (`operatingLocations → roles`) or directly on an OperatingLocation (the console batch's
# `operatingLocations__0__roles__0…` implies the operating-location level is where they actually sit).
#
# The document is built PER entity type (only the fragment for the queried type), NOT with both inline
# fragments in one document: `BrandName.name` is `String` while `OperatingLocationName.name` is
# `String!`, so selecting `names.edges.node.name` in a `... on Brand` AND a `... on OperatingLocation`
# fragment at the same response position is a GraphQL field-conflict validation error (measured live
# 2026-08-27). One fragment per document sidesteps it entirely. `RoleFields` (Role is the same type in
# both places) DRYs the owner selection.
_ROLE_FRAGMENT = """
fragment RoleFields on Role {
  jobTitle
  jobFunction
  managementLevel
  legalEntities(first: 2) { edges { node {
    names(first: 1) { edges { node { name legalEntityType } } }
  } } }
  phoneNumbers(first: 1) { edges { node { phoneNumber } } }
  emailAddresses(first: 1) { edges { node { emailAddress } } }
}
""".strip()

_CARD_SELECTION = """
cardTransactions(conditions: { filter: { AND: [
  { EQ: ["quantityType", "card_revenue_amount"] },
  { IN: ["period", ["1m", "3m", "12m"]] }
] } }) {
  edges { node { period projectedQuantity periodStartDate periodEndDate } }
}
""".strip()

_BRAND_BODY = f"""
... on Brand {{
  enigmaId
  names(first: 1) {{ edges {{ node {{ name }} }} }}
  {_CARD_SELECTION}
  operatingLocations(first: 1) {{
    edges {{ node {{ roles(first: 3) {{ edges {{ node {{ ...RoleFields }} }} }} }} }}
  }}
}}
""".strip()

_OPERATING_LOCATION_BODY = f"""
... on OperatingLocation {{
  enigmaId
  names(first: 1) {{ edges {{ node {{ name }} }} }}
  {_CARD_SELECTION}
  roles(first: 3) {{ edges {{ node {{ ...RoleFields }} }} }}
}}
""".strip()

_ENTITY_TYPES = {"brand": "BRAND", "operating_location": "OPERATING_LOCATION"}


def build_query(entity_type: str = "BRAND") -> str:
    """The GraphQL document for one entity type. Only the matching inline fragment is included, to
    avoid the Brand/OperatingLocation `names.name` (String vs String!) field-conflict."""
    et = _ENTITY_TYPES.get(str(entity_type).strip().lower(), str(entity_type).strip().upper())
    body = _OPERATING_LOCATION_BODY if et == "OPERATING_LOCATION" else _BRAND_BODY
    return f"{_ROLE_FRAGMENT}\n\nquery Probe($si: SearchInput!) {{\n  search(searchInput: $si) {{\n    {body}\n  }}\n}}"


# Back-compat: the default (BRAND) document.
SEARCH_QUERY = build_query("BRAND")


def build_variables(biz: dict[str, Any], match_threshold: float,
                    entity_type: str = "BRAND") -> dict[str, Any]:
    """The `searchInput` for one prospect, from its identifiers. Only non-empty address parts are
    sent. `entity_type` selects BRAND (the console batch's entity path) or OPERATING_LOCATION (where
    roles/owner records live directly)."""
    et = _ENTITY_TYPES.get(str(entity_type).strip().lower(), str(entity_type).strip().upper())
    si: dict[str, Any] = {"entityType": et, "matchThreshold": match_threshold}
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
                          biz: dict[str, Any], entity_type: str = "BRAND") -> EnigmaCall:
    """POST one GraphQL search. Never raises — a transport/HTTP failure is recorded on the returned
    EnigmaCall so one bad lookup can't abort the sample."""
    url = settings.enigma_graphql_url
    call = EnigmaCall(method="POST", url=url)
    body = {"query": build_query(entity_type),
            "variables": build_variables(biz, settings.enigma_graphql_match_threshold, entity_type)}
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


def first_entity(raw: Any) -> dict[str, Any] | None:
    """The top matched entity (Brand or OperatingLocation) from a GraphQL response, or None. `search`
    returns a list ranked best-first; we take the first dict that carries any of our selected fields.
    Note the live API returns `enigmaId: null` on a real match, so a match is signalled by the
    presence of a result dict with fields (names/cardTransactions/roles/operatingLocations), NOT by a
    non-null id — that is what the earlier match_rate=0 bug keyed on."""
    if not isinstance(raw, dict):
        return None
    results = ((raw.get("data") or {}).get("search")) if isinstance(raw.get("data"), dict) else None
    if not isinstance(results, list):
        return None
    for item in results:
        if isinstance(item, dict) and any(
            item.get(k) is not None
            for k in ("enigmaId", "names", "cardTransactions", "roles", "operatingLocations")
        ):
            return item
    return None


# Back-compat alias — this returns whichever entity type matched, not only a Brand.
first_brand = first_entity


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


def extract_card_as_of(brand: Any) -> str | None:
    """The latest `periodEndDate` across the returned card windows (the "revenue as of" recency the
    scoring model wants — the windows are a rolling series), as an ISO date string, or None. Pure and
    tolerant: a missing/odd shape yields None. Only the date part is kept (Enigma sends `YYYY-MM-DD`,
    but a datetime is truncated defensively)."""
    if not isinstance(brand, dict):
        return None
    latest: str | None = None
    for node in _nodes(brand.get("cardTransactions")):
        end = node.get("periodEndDate")
        if isinstance(end, str) and end.strip():
            day = end.strip()[:10]
            if latest is None or day > latest:
                latest = day
    return latest


def extract_matched_name(brand: Any) -> str | None:
    """The name of the matched entity (`names.edges[0].node.name`), for QA of match quality — a wrong
    match is the silent failure (a plausible card figure on the wrong business). Pure; None if absent."""
    if not isinstance(brand, dict):
        return None
    node = _first_node(brand.get("names"))
    if node:
        nm = node.get("name")
        if isinstance(nm, str) and nm.strip():
            return nm.strip()
    return None


def _person_name(role: dict[str, Any]) -> str | None:
    """The owner's name from a role's legal entities. The deployed `search` schema does NOT expose
    `Person.fullName/firstName/lastName` (a live 400), so the name comes from
    `legalEntities → names → { name legalEntityType }` — and only a `legalEntityType == "Person"`
    entity is treated as a person, so a company legal entity name is never mistaken for an owner."""
    for le in _nodes(role.get("legalEntities")):
        for name_node in _nodes(le.get("names")):
            if str(name_node.get("legalEntityType") or "").strip().lower() == "person":
                nm = name_node.get("name")
                if isinstance(nm, str) and nm.strip():
                    return nm.strip()
    return None


def extract_owner(entity: Any) -> dict[str, Any] | None:
    """The best decision-maker record from a matched entity's roles, or None. Roles live either
    directly on an OperatingLocation (`roles`) or under a Brand (`operatingLocations → roles`) — this
    checks the direct path first, then the nested one. Prefers a role that resolves to a named person;
    falls back to the first role carrying a title/contact. Returns `{full_name, job_title,
    management_level, job_function, phone, email}` (any may be None)."""
    if not isinstance(entity, dict):
        return None
    roles = _nodes(entity.get("roles"))
    if not roles:
        ol = _first_node(entity.get("operatingLocations"))
        roles = _nodes(ol.get("roles")) if ol else []
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
                     prospect: dict[str, Any], entity_type: str = "BRAND") -> GraphqlLookup:
    result = GraphqlLookup(prospect_id=str(prospect.get("id") or ""), biz=prospect)
    result.call = await search_business(client, settings, prospect, entity_type)
    if result.call.ok:
        result.brand = first_entity(result.call.raw)
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
                      *, entity_type: str = "BRAND", concurrency: int = 5) -> list[GraphqlLookup]:
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(timeout=settings.enigma_request_timeout_seconds) as client:
        async def _run(p: dict[str, Any]) -> GraphqlLookup:
            async with sem:
                try:
                    return await lookup_one(client, settings, p, entity_type)
                except Exception as exc:  # noqa: BLE001 — never let one prospect break the gather
                    logger.warning("enigma graphql lookup crashed", extra={"error": repr(exc)[:200]})
                    return GraphqlLookup(prospect_id=str(p.get("id") or ""), biz=p)

        return await asyncio.gather(*[_run(p) for p in prospects])


def is_match(result: Any) -> bool:
    """Whether a lookup matched an Enigma entity. Keys on a returned entity object, NOT on
    `enigma_id` — the live API returns `enigmaId: null` on a real match, so the id is not a match
    signal (the earlier match_rate=0 bug)."""
    return bool(getattr(result, "brand", None))


def probe_metrics(results: list[Any], unnamed_prospect_ids: set[str]) -> dict[str, Any]:
    """The scoping §3 decision metrics over GraphqlLookup results.

    - match_rate: share that matched an Enigma entity (by a returned entity, not the always-null id).
    - owner_name_hit_on_unnamed: of the prospects the existing ladder could NOT name, share Enigma
      gave a principal NAME (the headline contacts number).
    - card_fill_of_matched: of the matched, share with any 1m/3m/12m card-revenue window.
    """
    total = len(results)
    matched = [r for r in results if is_match(r)]
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
