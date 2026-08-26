"""Enigma enrichment — pure decision logic + the defensive parse of a GraphQL response.

The HTTP/GraphQL call lives in `enigma_client`; this module never touches the network, so the whole
decision layer — where the fabrication gate and the owner choice live — is unit-testable off
hand-built responses. Two invariants from the paid-signal work (I-099) are enforced here:

  * **Fabrication gate.** An owner/contact is asserted ONLY when the entity match clears
    `min_match_score`. Below it the prospect is `no_match` and NO owner/economics are written — a
    wrong entity match must never manufacture a false owner or phone.
  * **Which source fired.** The chosen owner carries `owner_evidence` (gov_registration |
    contact_data | both), so a surface claims only what that source measured.

**SHAPE IS PROVISIONAL (ISSUES I-Enigma).** No live Enigma call has run, so the exact response
field paths are unconfirmed. `parse_candidate` reads defensively — a tolerant key search that never
asserts a field is present — and the caller keeps the untouched response in `raw`, so a corrected
path needs no re-pull (the measure-don't-infer / raw-recovery discipline, like Outscraper's
`domains_service`). The LOGIC below (role scoring, match gate, owner evidence) is independent of the
wire shape and fully tested; only `parse_candidate`'s key names await the first live response.
"""

from __future__ import annotations

import re
from typing import Any

# --- Role priority — which title is most likely the decision-maker ---------------------------
# The proposal's role→score table. A registered agent (an attorney / filing service) is NOT the
# owner, so it and the other administrative roles score below `DECISION_MAKER_FLOOR` and are never
# chosen as the owner (they are still kept in `officers` for inspection). Scores are on a 0..100
# priority scale, not a probability.
ROLE_SCORES: dict[str, int] = {
    "owner": 100,
    "founder": 100,
    "co-owner": 98,
    "co owner": 98,
    "cofounder": 98,
    "co-founder": 98,
    "co founder": 98,
    "managing member": 95,
    "member": 90,
    "president": 90,
    "partner": 90,
    "principal": 85,
    "ceo": 85,
    "chief executive officer": 85,
    "managing director": 75,
    "vice president": 55,
    "general manager": 60,
    "director": 60,
    "manager": 40,
    "officer": 40,
    "secretary": 30,
    "treasurer": 30,
    "registered agent": 20,
    "agent": 15,
}

# Below this, a person is administrative (registered agent, secretary, treasurer, bare agent) and is
# never asserted as the owner. Manager/officer (40) is the weakest role still treated as a possible
# decision-maker, matching the proposal's table.
DECISION_MAKER_FLOOR = 40

# Generic tokens stripped before name comparison so a legal name's suffix noise ("ABC Plumbing" vs
# "ABC PLUMBING SERVICES LLC") does not depress a real match.
_NAME_STOPWORDS = frozenset(
    {"llc", "inc", "co", "corp", "corporation", "ltd", "limited", "company",
     "services", "service", "the", "and", "of", "group", "enterprises"}
)


def _norm(text: Any) -> str:
    """Lowercase, non-alphanumerics → single spaces, trimmed. Pure."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _digits(text: Any) -> str:
    return re.sub(r"\D", "", str(text or ""))


def _host(url: Any) -> str:
    """Bare host of a URL/domain, lowercased, `www.` and scheme/path stripped. Pure."""
    text = str(url or "").strip().lower()
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0]
    text = re.sub(r"^www\.", "", text)
    return text


# ------------------------------------------------------------------------------------------------
# Role scoring + owner choice (pure, shape-independent)
# ------------------------------------------------------------------------------------------------

def role_score(title: Any) -> int:
    """Priority score (0..100) for a title. 0 when unknown. A compound title takes the MAX over
    every role phrase it contains, so "Managing Member / Owner" scores as owner (100), and word
    boundaries are respected so "member" does not match inside another word."""
    padded = f" {_norm(title)} "
    if padded == "  ":
        return 0
    scores = [score for phrase, score in ROLE_SCORES.items() if f" {phrase} " in padded]
    return max(scores, default=0)


def choose_owner(people: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, int]:
    """The most-likely decision-maker among an entity's people, and its role score.

    First-highest wins (stable on ties), and the winner must clear `DECISION_MAKER_FLOOR` — so an
    entity whose only listed person is a registered agent yields NO owner (None), never a false one.
    """
    best: dict[str, Any] | None = None
    best_score = -1
    for person in people:
        score = role_score(person.get("title"))
        if score > best_score:
            best, best_score = person, score
    if best is not None and best_score >= DECISION_MAKER_FLOOR:
        return best, best_score
    return None, 0


def name_similarity(a: Any, b: Any) -> float:
    """Jaccard overlap of the two names' significant tokens (generic business words stripped). 0..1,
    symmetric — deliberately NOT containment, so a short competitor name inside a longer one does not
    read as a perfect match (the one-directional-match lesson, applied as a symmetric score)."""
    ta = {t for t in _norm(a).split() if t not in _NAME_STOPWORDS}
    tb = {t for t in _norm(b).split() if t not in _NAME_STOPWORDS}
    if not ta or not tb:  # everything was a stopword — fall back to raw tokens
        ta = set(_norm(a).split())
        tb = set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def compute_match_score(prospect: dict[str, Any], cand: dict[str, Any]) -> float:
    """A deterministic 0..1 confidence that `cand` (Enigma) is the same business as `prospect` (GBP),
    used only when Enigma returns no confidence of its own. Name is necessary but not sufficient for
    a local business (many share a name — proposal §22), so a match needs a corroborating phone or
    website to clear a sensible gate: perfect name alone = 0.55; name + phone = 0.85."""
    score = 0.55 * name_similarity(prospect.get("name"), cand.get("name"))
    pp, cp = _digits(prospect.get("phone")), _digits(cand.get("phone"))
    if pp and cp and pp[-10:] == cp[-10:]:
        score += 0.30
    ph, ch = _host(prospect.get("website")), _host(cand.get("website"))
    if ph and ch and ph == ch:
        score += 0.15
    return min(1.0, round(score, 4))


# ------------------------------------------------------------------------------------------------
# Defensive parse of the GraphQL response (shape provisional)
# ------------------------------------------------------------------------------------------------

def _nodes(value: Any) -> list[dict[str, Any]]:
    """Coerce a Relay connection ({edges:[{node:{}}]}), a bare list, or a single dict into a list of
    node dicts. Tolerant of whichever shape the field actually is."""
    if value is None:
        return []
    if isinstance(value, dict):
        if "edges" in value and isinstance(value["edges"], list):
            return [e["node"] for e in value["edges"]
                    if isinstance(e, dict) and isinstance(e.get("node"), dict)]
        if "node" in value and isinstance(value["node"], dict):
            return [value["node"]]
        return [value]
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for item in value:
            out.extend(_nodes(item))
        return out
    return []


def _find_first(obj: Any, keys: tuple[str, ...], *, _depth: int = 0) -> Any:
    """First non-empty value found under any of `keys` (case-insensitive), searched depth-first with
    a bounded depth. Returns None if absent — never raises, never asserts a path exists."""
    if _depth > 8 or obj is None:
        return None
    low = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in low and v not in (None, "", [], {}):
                if isinstance(v, dict) and "edges" in v:
                    ns = _nodes(v)
                    if ns:
                        return ns[0].get("name") if "name" in ns[0] else ns[0]
                    continue
                return v
        for v in obj.values():
            found = _find_first(v, keys, _depth=_depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first(item, keys, _depth=_depth + 1)
            if found is not None:
                return found
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _money_cents(value: Any) -> int | None:
    """A dollar-ish revenue value → integer cents. Accepts a number or a plain string; ignores
    anything unparseable (never raises)."""
    f = _to_float(value)
    return int(round(f * 100)) if f is not None else None


_PEOPLE_KEYS = ("people", "persons", "person", "officers", "relatedPeople", "connectedPeople")


def _collect_under(obj: Any, keys: tuple[str, ...], *, _depth: int = 0) -> list[dict[str, Any]]:
    """Every node reachable under any of `keys`, searched depth-first (bounded). People live nested
    under `legalEntities → node → people`, so a top-level key check would miss them; this walks the
    whole response and `_nodes`-coerces each match."""
    if _depth > 8 or obj is None:
        return []
    low = {k.lower() for k in keys}
    out: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in low:
                out.extend(_nodes(v))
            else:
                out.extend(_collect_under(v, keys, _depth=_depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_collect_under(item, keys, _depth=_depth + 1))
    return out


def _extract_people(cand: dict[str, Any]) -> list[dict[str, Any]]:
    """Every person node reachable from a candidate, normalized to {name, title, email, phone,
    source}. Tolerant: reads people from any of the known connection keys at any depth, and tags
    provenance from what the node carries (a role → gov_registration; contact coords only →
    contact_data; both → both). The provenance heuristic is provisional (ISSUES) — the raw response
    is the recovery path.
    """
    seen_nodes = _collect_under(cand, _PEOPLE_KEYS)
    out: list[dict[str, Any]] = []
    for node in seen_nodes:
        if not isinstance(node, dict):
            continue
        name = _find_first(node, ("fullName", "name", "personName"))
        title = _find_first(node, ("title", "role", "position", "officerTitle", "relationship"))
        email = _find_first(node, ("email", "emailAddress"))
        phone = _find_first(node, ("phone", "phoneNumber", "telephone"))
        if not (name or email or phone):
            continue
        has_role = bool(title)
        has_contact = bool(email or phone)
        if has_role and has_contact:
            source = "both"
        elif has_contact:
            source = "contact_data"
        else:
            source = "gov_registration"
        out.append({
            "name": str(name) if name else None,
            "title": str(title) if title else None,
            "email": str(email) if email else None,
            "phone": str(phone) if phone else None,
            "source": source,
        })
    return out


def parse_candidate(raw: Any) -> dict[str, Any] | None:
    """The best business candidate from an Enigma GraphQL response, or None. Defensive throughout.

    Returns {entity_id, legal_name, provided_score, match_fields, people, economics}. `provided_score`
    is Enigma's own confidence if the response carries one, else None (the caller then computes one).
    """
    root = raw.get("data", raw) if isinstance(raw, dict) else raw
    candidates = _nodes(_find_first(root, ("search", "match", "brands", "results"))
                        if isinstance(root, dict) else None)
    if not candidates and isinstance(root, dict):
        # The query may return the brand directly rather than under `search`.
        candidates = _nodes(root)
    cand = candidates[0] if candidates else None
    if not isinstance(cand, dict):
        return None

    legal_name = _find_first(cand, ("legalName", "name"))
    loc_count = _to_int(_find_first(cand, ("locationCount", "operatingLocationCount")))
    if loc_count is None:
        locs = _nodes(cand.get("operatingLocations"))
        loc_count = len(locs) or None

    return {
        "entity_id": _find_first(cand, ("id", "brandId", "entityId")),
        "legal_name": str(legal_name) if legal_name else None,
        "provided_score": _to_float(_find_first(cand, ("matchScore", "score", "confidence"))),
        "match_fields": {
            "name": str(legal_name) if legal_name else None,
            "phone": _find_first(cand, ("phone", "phoneNumber", "telephone")),
            "website": _find_first(cand, ("website", "url", "domain", "homepageUrl")),
        },
        "people": _extract_people(cand),
        "economics": {
            "card_revenue_cents": _money_cents(
                _find_first(cand, ("cardRevenueAmount", "cardRevenue", "revenue", "estimatedRevenue"))
            ),
            "revenue_growth_pct": _to_float(
                _find_first(cand, ("cardRevenueGrowth", "growthRate", "revenueGrowth", "yoyGrowth"))
            ),
            "location_count": loc_count,
        },
    }


def _officer_view(person: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": person.get("name"),
        "title": person.get("title"),
        "role_score": role_score(person.get("title")),
        "email": person.get("email"),
        "phone": person.get("phone"),
        "source": person.get("source"),
    }


def build_enigma_row(
    prospect: dict[str, Any],
    raw: Any,
    *,
    min_match_score: float,
    place_id: str,
) -> dict[str, Any]:
    """A `prospect_enigma` row from an Enigma response. Pure — the whole resolution decision.

    Statuses: `no_match` (nothing matched, or the best match is below the gate — NOTHING asserted),
    `resolved` (matched above the gate, with an owner and/or contact), `no_contacts` (matched above
    the gate but no owner and no contact coordinates). The gate is the fabrication guard: below it,
    only the entity id + score + raw are kept, never an owner or economics.
    """
    row: dict[str, Any] = {
        "prospect_id": prospect["id"],
        "place_id": place_id,
        "raw": raw,
        "officers": [],
    }

    cand = parse_candidate(raw)
    if not cand:
        row["status"] = "no_match"
        return row

    score = cand["provided_score"]
    if score is None:
        score = compute_match_score(prospect, cand["match_fields"])
    score = round(min(1.0, max(0.0, float(score))), 4)
    row["enigma_entity_id"] = cand.get("entity_id")
    row["match_score"] = score

    if score < min_match_score:
        # Matched a candidate, but not confidently enough to attribute anyone to this prospect.
        row["status"] = "no_match"
        return row

    # Above the gate: safe to attribute the entity, its economics, and its owner to this prospect.
    row["legal_name"] = cand.get("legal_name")
    econ = cand["economics"]
    row["card_revenue_cents"] = econ.get("card_revenue_cents")
    row["revenue_growth_pct"] = econ.get("revenue_growth_pct")
    row["location_count"] = econ.get("location_count")
    row["officers"] = [_officer_view(p) for p in cand["people"]]

    owner, owner_score = choose_owner(cand["people"])
    if owner is not None:
        row["owner_name"] = owner.get("name")
        row["owner_title"] = owner.get("title")
        row["owner_role_score"] = owner_score
        row["owner_email"] = owner.get("email")
        row["owner_phone"] = owner.get("phone")
        row["owner_evidence"] = owner.get("source")

    has_owner = owner is not None
    has_contact = bool(row.get("owner_email") or row.get("owner_phone"))
    row["status"] = "resolved" if (has_owner or has_contact) else "no_contacts"
    return row
