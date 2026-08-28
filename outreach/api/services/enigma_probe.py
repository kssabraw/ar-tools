"""Pure helpers for the Enigma probe — id/name/card extraction + the scoping §3 decision metrics.

Everything here is pure and TOLERANT: the exact Enigma response schema is unconfirmed (the probe
logs the raw so it can be read on the first live run), so these do a defensive recursive walk for
the likely keys rather than asserting a shape. They never raise; a shape they don't recognise yields
None / empty, and the raw envelope in the probe log is the ground truth for correcting them.

None of this decides anything on its own — `probe_metrics` computes the numbers the scoping doc's
decision rule reads (match rate, owner-name hit rate on the un-named, card-signal fill), and a human
reads them against the doc's bars (≥40% owner-name hit, ≥70% match, cost justified).
"""

from __future__ import annotations

import re
from typing import Any, Iterator

# Enigma business ids look like `B00233ee1f5e` (a letter + hex). Loose: a letter then ≥6 hex chars.
_ENIGMA_ID_RE = re.compile(r"^[A-Za-z][0-9a-fA-F]{6,}$")
# The ID endpoint's path param is the BUSINESS id (`B…`), confirmed by the docs
# (`GET /businesses/B00233ee1f5e?attrs=…`). A match record also carries a record-level `enigma_id`
# (`E…`) — passing THAT is what 400'd the first probe. Prefer `business_enigma_id` when both exist.
_ID_KEYS = ("business_enigma_id", "enigma_id", "business_id", "id")
_MATCH_LIST_KEYS = ("matches", "businesses", "data", "results", "hits")
# "people" catches Enigma's match-response `associated_people`; "registered_agent" catches
# `registered_agents`. Principals ride the MATCH response for these businesses, not the id call.
_PRINCIPAL_KEYS = ("principal", "people", "person", "officer", "owner", "contact", "registered_agent")
_CARD_KEYS = ("card_transaction", "card_transactions", "transactions", "card_revenue", "card_revenues")
# Period aliases → canonical window. Enigma's native windows are 1m / 3m / 12m (NO 6m).
# Period detection, in precedence order so a compound key ("three_month", "twelve_month") is not
# mis-read by the bare "month" fallback. 12m first (its tokens never appear in a 3m/1m key), then 3m,
# then 1m (bare "month"/"1"/"one" ⇒ one-month). Enigma's native windows are 1m / 3m / 12m — no 6m.
_PERIOD_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("12m", ("12", "twelve", "year", "annual")),
    ("3m", ("3m", "3_month", "three", "quarter")),
    ("1m", ("1m", "1_month", "one", "month")),
)
_AMOUNT_KEYS = ("average_monthly_amount", "average_monthly_quantity", "average_monthly_count",
                "amount", "quantity", "count", "value")


def _walk(obj: Any) -> Iterator[tuple[str, Any]]:
    """Yield every (key, value) pair at any depth in a JSON-ish structure. Lists are traversed but
    contribute no keys of their own."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def looks_like_enigma_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ENIGMA_ID_RE.match(value.strip()))


def _first_id_in(item: Any) -> str | None:
    if isinstance(item, dict):
        for key in _ID_KEYS:
            v = item.get(key)
            if looks_like_enigma_id(v):
                return v.strip()
        # A nested id (e.g. {"business": {"id": ...}}) — fall through to a walk.
        for _k, v in _walk(item):
            if looks_like_enigma_id(v):
                return v.strip()
    elif looks_like_enigma_id(item):
        return item.strip()
    return None


def match_id_from_response(raw: Any) -> str | None:
    """The top matched Enigma business id, or None. Tries a list of matches under the common wrapper
    keys, then the payload itself, then any id-shaped value anywhere. Best-effort by construction."""
    if raw is None:
        return None
    if isinstance(raw, list):
        for item in raw:
            got = _first_id_in(item)
            if got:
                return got
    if isinstance(raw, dict):
        for key in _MATCH_LIST_KEYS:
            sub = raw.get(key)
            if isinstance(sub, list):
                for item in sub:
                    got = _first_id_in(item)
                    if got:
                        return got
            elif sub is not None:
                got = _first_id_in(sub)
                if got:
                    return got
        got = _first_id_in(raw)
        if got:
            return got
    # Last resort: any id-shaped value anywhere in the tree.
    for _k, v in _walk(raw):
        if looks_like_enigma_id(v):
            return v.strip()
    return None


def _name_from_person(d: dict[str, Any]) -> str | None:
    for key in ("full_name", "name", "display_name"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    first = str(d.get("first_name") or "").strip()
    last = str(d.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def extract_principal_name(id_raw: Any) -> str | None:
    """A principal / owner NAME from the attributes payload, or None. Looks under any key that reads
    like a principal/person/officer/owner and pulls a name from the object(s) there."""
    if id_raw is None:
        return None
    for k, v in _walk(id_raw):
        if any(tag in k.lower() for tag in _PRINCIPAL_KEYS):
            items = v if isinstance(v, list) else [v]
            for item in items:
                if isinstance(item, dict):
                    name = _name_from_person(item)
                    if name:
                        return name
                elif isinstance(item, str) and item.strip() and " " in item.strip():
                    return item.strip()
    return None


def _period_key(raw_key: str) -> str | None:
    lk = raw_key.lower()
    for canon, tokens in _PERIOD_MATCHERS:
        if any(t in lk for t in tokens):
            return canon
    return None


def _amount_in(obj: Any) -> Any:
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, dict):
        for key in _AMOUNT_KEYS:
            if key in obj and isinstance(obj[key], (int, float)):
                return obj[key]
    return None


def extract_card_transactions(id_raw: Any) -> dict[str, Any] | None:
    """A `{window: amount}` map (windows in 1m/3m/12m) from the card-transaction / card-revenue block,
    or None. Finds the card block by key, then reads each period sub-object. Tolerant of the exact
    field names; returns whatever windows it can resolve."""
    if id_raw is None:
        return None
    out: dict[str, Any] = {}
    for k, v in _walk(id_raw):
        if any(tag in k.lower() for tag in _CARD_KEYS):
            # `v` may be a dict of periods, a list of period objects, or a single period object.
            candidates: list[tuple[str, Any]] = []
            if isinstance(v, dict):
                candidates = list(v.items())
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        candidates.extend(item.items())
            for pk, pv in candidates:
                window = _period_key(str(pk))
                if window and window not in out:
                    amt = _amount_in(pv)
                    if amt is not None:
                        out[window] = amt
    return out or None


def _call_raw(call: Any) -> Any:
    return getattr(call, "raw", None) if call is not None else None


def principal_name_from_result(result: Any) -> str | None:
    """A principal / owner NAME for one lookup, checking BOTH the match response and the id-endpoint
    attributes. Enigma returns `associated_people` / `registered_agents` in the MATCH payload for these
    businesses, so reading only the id call (as the first cut did) misses every name."""
    return (
        extract_principal_name(_call_raw(getattr(result, "id_call", None)))
        or extract_principal_name(_call_raw(getattr(result, "match_call", None)))
    )


def card_transactions_from_result(result: Any) -> dict[str, Any] | None:
    """Card-transaction windows for one lookup, from the id-endpoint attributes (the match response
    lists only which data_sources EXIST, not the amounts)."""
    return extract_card_transactions(_call_raw(getattr(result, "id_call", None)))


def probe_metrics(results: list[Any], unnamed_prospect_ids: set[str]) -> dict[str, Any]:
    """The scoping §3 decision metrics over a list of `enigma_client.LookupResult`.

    - match_rate: share that returned an Enigma id.
    - owner_name_hit_on_unnamed: of the prospects we could NOT name via the existing ladder, share
      Enigma gave a principal NAME (the headline contacts number).
    - card_fill: of the matched, share with any card-transaction window.
    Pure over the results' already-extracted fields + best-effort extraction of names/card here."""
    total = len(results)
    matched = [r for r in results if getattr(r, "enigma_id", "")]
    unnamed = [r for r in results if getattr(r, "prospect_id", "") in unnamed_prospect_ids]

    unnamed_named = [r for r in unnamed if principal_name_from_result(r)]
    card_filled = [r for r in matched if card_transactions_from_result(r)]

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
