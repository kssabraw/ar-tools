"""Per-prospect "why this is a lead" justification — the caller's phone-call hook.

This is the Phase 3 "call hook generated from the prospect's own data" the outreach docs
anticipate (outreach/HANDOFF.md §12 item 1; PRD §716; reporting-layer-spec §4a "Call hooks are
exempt"). Before a caller dials a scanned prospect they read a short, human-readable set of
talking points — WHY this business is worth calling — so they know exactly what to point out on
the phone.

**This module is PURE deterministic assembly.** No LLM, no network, no clock, no randomness. It
takes facts already captured by the geogrid scan and turns them into sentences, exactly the way
`services/../heatmap.py` turns a `rank_vector` into an SVG. The reasons, spelled out in the
outreach DECISIONS.md entry for this build:

  * The whole reporting family is deterministic by requirement — an artifact rendered in March
    must regenerate identically in June (reporting-layer-spec §2, §6). Talking points assembled
    from the same stored inputs inherit that property for free.
  * The module's governing invariant is "never invent a fact, a competitor, or a number"
    (outreach/CLAUDE.md; PRD §14 "diagnose, not promise"). A deterministic assembler CANNOT
    fabricate — every sentence is a template over numbers that were measured. An LLM phrasing
    pass, however tightly grounded, reopens that door and needs guarding shut again.
  * It is the cheapest option to reverse. Pure assembly adds no dependency, key, cost, or
    non-determinism; an LLM phrasing pass can always be layered ON TOP later, grounded on the
    facts THIS module already assembles (the suite's "numbers-only, never invent" report
    narratives are exactly that shape). Starting deterministic and adding phrasing later is
    strictly cheaper to reverse than starting with an LLM and stripping it out.

The phrasing templates live here as code constants, not config. That mirrors the heatmap
renderer, whose legend labels ("In the map pack (1–3)", …) are also code constants rather than
config — the accepted Phase 3 precedent. "Template MUST be config" (PRD §716) is honored in
spirit: the sentences are filled from persisted scan data and never improvised at send time,
which is what that MUST protects against. Promoting the templates to config is a later,
cheap-to-reverse step if an A/B need arises (outreach DECISIONS.md).

Every talking point carries the raw `facts` it was built from, so the claim is inspectable and
replayable from stored inputs — the same discipline `score_factors` holds for the scoring model
(outreach/CLAUDE.md invariants).
"""
from __future__ import annotations

from typing import Any, Optional

# The two reserved rank_vector bytes, from the coverage rollup (outreach storage spec §4). Mirrored
# here rather than imported because the outreach api is a separate deploy this service cannot
# import from; the values are a wire contract, not logic that can drift. 0 = the business was not
# found at that point; 255 = the point is dead (land-masked / never measured) and is NOT a rank.
BYTE_ABSENT = 0
BYTE_DEAD = 255

# The evidence elements a justification can carry. One key per kind of fact, so the hook attribution
# (PRD §14a "record which element was selected as the hook and which others were available") is a
# stable vocabulary and not a free-text label.
ELEM_COVERAGE = "coverage"
ELEM_PAYING = "paying"
ELEM_COMPETITOR = "competitor"
ELEM_PAID = "paid"
ELEM_GEOGRAPHY = "geography"
ELEM_REVIEWS = "reviews"
ELEM_NO_WEBSITE = "no_website"
ELEM_NO_PHONE = "no_phone"
ELEM_LISTING_STATUS = "listing_status"

# Hook-selection priority. The hook is the single opener a caller leads with; the rest are the
# talking points they work through (PRD §1335 — a hook is one element). Coverage leads because a
# business's own invisibility is the strongest, least-arguable state pitch. A `delta` element
# (before/after change) would sit ABOVE coverage per PRD §716 "preferring a delta over a state" —
# it is deliberately absent until a second scan exists (deltas arrive at cycle 2, ~30 days), the
# same seam the heatmap delta guards leave open (outreach ISSUES I-091). See the caveats.
HOOK_PRIORITY = (
    # The single opener a caller leads with, ordered so the hook LEADS with the most
    # per-prospect-DISTINCTIVE loss rather than the coverage line every business in a submarket
    # shares (that sameness was the complaint this ordering answers). Paying-and-losing stays top
    # (proven budget AND a visible problem — scoring-spec.md §Buying-intent). Then a NAMED
    # competitor taking the exact points this business is missing, then its own review deficit vs
    # the field — both differ business-to-business even inside one submarket. Bare coverage (shared
    # across a submarket) drops BELOW them, so two neighbours no longer open with the same line.
    ELEM_PAYING,
    ELEM_COMPETITOR,
    ELEM_REVIEWS,
    ELEM_COVERAGE,
    ELEM_GEOGRAPHY,
    ELEM_PAID,
    ELEM_NO_WEBSITE,
    ELEM_NO_PHONE,
    ELEM_LISTING_STATUS,
)

# Google's `business_status` values that mean "fine". Anything else (CLOSED_TEMPORARILY,
# CLOSED_PERMANENTLY) is worth flagging to the caller before they pitch.
_OK_STATUSES = frozenset({"", "OPERATIONAL"})


# --- decoding (a byte decode, NOT geometry) ---------------------------------------------------


def decode_rank_vector(raw: Any) -> list[int]:
    """A stored `rank_vector` (bytea) as a list of byte values, one per grid point in point_seq
    order.

    This is a pure byte decode and has NOTHING to do with grid geometry — it never maps a point to
    a coordinate, so it does not touch the pinned geometry registry the module guards so carefully.
    It only needs to survive the several shapes the Postgres driver hands a bytea back as: a
    `\\x`-prefixed hex string over PostgREST, a memoryview, or raw bytes. Getting it wrong is silent
    — a hex STRING has length 2n+2 and would report a grid twice its real size with every byte
    wrong (mirrors the outreach coverage_rollup decoder, which pins this).
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw[2:] if raw.startswith("\\x") else raw
        return list(bytes.fromhex(text))
    if isinstance(raw, memoryview):
        return list(raw.tobytes())
    if isinstance(raw, (bytes, bytearray)):
        return list(bytes(raw))
    raise TypeError(f"cannot decode a rank_vector of type {type(raw).__name__}")


def absent_point_seqs(vector: Optional[list[int]]) -> Optional[set[int]]:
    """The point_seqs where the business was measured but NOT found (byte == 0).

    `None` in means "this prospect has no coverage row" — inside a rolled-up submarket that is
    zero coverage, i.e. absent EVERYWHERE (outreach ISSUES I-076), which the competitor summarizer
    reads as "absent at every measured point". A dead point (255) is not absence — it was never
    measured — so it is never in this set.
    """
    if vector is None:
        return None
    return {i for i, b in enumerate(vector) if b == BYTE_ABSENT}


# --- pure summarizers (fed by the I/O layer, each independently testable) ----------------------


def resolve_review_count(row: dict[str, Any]) -> Optional[int]:
    """One prospect's review count, honoring the inferred-zero convention (outreach ISSUES I-041).

    `review_count` is authoritative when present. When it is NULL, the provider encodes "no
    reviews" as NULL, so a row carrying `review_count_inferred_zero` reads as 0; a NULL WITHOUT the
    flag is genuinely unknown and returns None (it must not be counted as zero — that would invent
    a number).
    """
    count = row.get("review_count")
    if count is not None:
        return int(count)
    if row.get("review_count_inferred_zero"):
        return 0
    return None


def field_review_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The local field's review distribution — the yardstick a prospect's review count is compared
    against.

    Pure. `rows` are the OTHER prospects in the same submarket (the target excluded upstream).
    Unknown counts are dropped, never guessed at (a guessed field median manufactures the very
    comparison the pitch rests on). Returns the median and the sample size it was computed over, so
    the caller can withhold the comparison when the sample is too thin to mean anything.
    """
    values = sorted(v for v in (resolve_review_count(r) for r in rows) if v is not None)
    if not values:
        return {"median": None, "sample": 0}
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
    return {"median": round(float(median), 1), "sample": len(values)}


def summarize_competitors(
    *,
    prospect_place_id: Optional[str],
    absent_seqs: Optional[set[int]],
    pack_rows: list[dict[str, Any]],
    name_by_place_id: dict[str, str],
    max_named: int,
) -> dict[str, Any]:
    """Who holds the Google map pack at the points where THIS prospect is invisible, and how often.

    Pure. `pack_rows` are `grid_result` rows already filtered to `rank <= pack_size` (the map pack)
    for one snapshot — each `{point_seq, place_id, rank}`. `absent_seqs` is where the prospect is
    absent (None = absent everywhere; outreach ISSUES I-076).

    The denominator is the number of pack points where the prospect is invisible — "the places a
    searcher sees a map pack and you are not in it". A competitor's count is how many of THOSE
    points it holds a pack spot at. Only competitors whose `place_id` resolves to a known business
    name are NAMED (never fabricate a competitor — outreach/CLAUDE.md); the rest still count toward
    `total` so "N competitors in all" stays honest without naming a place_id we cannot vouch for.
    The prospect's own place_id is excluded — a business does not compete with itself.
    """
    def is_absent(seq: int) -> bool:
        return absent_seqs is None or seq in absent_seqs

    competitive_points = {int(r["point_seq"]) for r in pack_rows}
    invisible_points = sorted(s for s in competitive_points if is_absent(s))
    invisible_set = set(invisible_points)

    held: dict[str, set[int]] = {}
    for row in pack_rows:
        place_id = row.get("place_id")
        seq = int(row["point_seq"])
        if not place_id or place_id == prospect_place_id:
            continue
        if seq in invisible_set:
            held.setdefault(place_id, set()).add(seq)

    # Most-dominant first, place_id as a deterministic tie-break so the same scan always names the
    # same competitors in the same order (replayability).
    ranked = sorted(held.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    named: list[dict[str, Any]] = []
    for place_id, seqs in ranked:
        name = name_by_place_id.get(place_id)
        if not name:
            continue
        named.append({"place_id": place_id, "name": name, "points": len(seqs)})
        if len(named) >= max_named:
            break

    return {
        "available": True,
        "named": named,
        "total": len(held),
        "invisible_points": len(invisible_points),
    }


# --- phrasing (deterministic templates; the "assembled from persisted data" of §716) ----------


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")


def _pct(value: float) -> str:
    """A percentage with no trailing `.0` — 74% not 74.0%, 12.5% kept."""
    rounded = round(float(value), 1)
    return f"{int(rounded)}%" if rounded == int(rounded) else f"{rounded}%"


def _miles(value: float) -> str:
    rounded = round(float(value), 1)
    return f"{int(rounded)}" if rounded == int(rounded) else f"{rounded}"


def _point(element: str, text: str, facts: dict[str, Any]) -> dict[str, Any]:
    return {"element": element, "text": text, "facts": facts}


# --- the assembler ----------------------------------------------------------------------------


def build_justification(
    *,
    prospect: dict[str, Any],
    keyword: str,
    submarket: str,
    snapshot: dict[str, Any],
    coverage: Optional[dict[str, Any]],
    live_points: Optional[int],
    competitors: dict[str, Any],
    field_reviews: dict[str, Any],
    field_min_sample: int,
    pack_size: int,
    paid: Optional[dict[str, Any]] = None,
    losing_deficit_pct: float = 50.0,
    valuation: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the whole justification for one prospect. Pure — every input is already resolved.

    `coverage` is the prospect's `prospect_coverage` row, or None when the prospect appeared at no
    grid point inside a rolled-up submarket (zero coverage, not unknown — outreach ISSUES I-076).
    `live_points` is the snapshot's measured-point denominator (shared across the snapshot), passed
    separately so the zero-coverage case still knows how many points "invisible everywhere" spans.
    `competitors` / `field_reviews` come from the summarizers above. `paid` is the derived
    paid-placement signal (`outreach_report.derive_paid_signal`, or None when the organic/paid scan
    hasn't run) — a talking point fires only when rivals are paying for this search and the prospect
    is not (the scoring-spec.md §Buying-intent pitch).

    Returns a dict with a stable shape: a headline, the single spoken `hook` (+ `hook_element` and
    the `available_elements` it was chosen from — PRD §14a), the ordered `talking_points` each
    carrying its `facts`, `caveats`, and `provenance` so the whole thing is replayable.
    """
    name = prospect.get("name") or "This business"
    present = int(coverage["points_present"]) if coverage else 0
    cov_pct = float(coverage["coverage_pct"]) if coverage else 0.0
    deficit = round(100.0 - cov_pct, 1)
    total_points = int(live_points) if live_points is not None else None
    invisible = max(total_points - present, 0) if total_points is not None else None
    invisible_everywhere = present == 0

    points: list[dict[str, Any]] = []

    # --- coverage: the core invisibility fact -------------------------------------------------
    cov_facts = {
        "coverage_pct": round(cov_pct, 1),
        "coverage_deficit": deficit,
        "points_present": present,
        "live_points": total_points,
        "invisible_points": invisible,
        "keyword": keyword,
        "submarket": submarket,
    }
    if invisible_everywhere:
        denom = f"all {total_points} points we checked" if total_points else "every point we checked"
        cov_text = (
            f"Every customer searching “{keyword}” across {submarket} is being handed to a "
            f"competitor — {name} doesn't appear in Google's map results at {denom}, so none of "
            f"that demand is reaching them."
        )
    else:
        span = f"{invisible} of the {total_points} points" if total_points is not None else "much of the area"
        cov_text = (
            f"{name} is losing “{keyword}” searches across {_pct(deficit)} of {submarket} — "
            f"absent from Google's map results at {span} we measured, so those customers are "
            f"reaching a competitor first."
        )
    points.append(_point(ELEM_COVERAGE, cov_text, cov_facts))

    # --- paying and losing: the strongest pitch — proven budget AND a visible problem ----------
    # scoring-spec.md §Proven-spend / §Buying-intent (the vendor-failing SHAPE). Fires when the
    # prospect is paying for visibility (in the SERP paid block, running LSA, or carrying an AW-
    # conversion tag on their site — Slice B1) AND is losing it (invisible everywhere, or missing
    # from the majority of the area). Deterministic: every clause is a measured fact.
    paying_and_losing = bool(
        paid and paid.get("prospect_is_paying") and (invisible_everywhere or deficit >= losing_deficit_pct)
    )
    # WHICH evidence fired decides what may be SAID. `serp_ad`/`lsa` were measured on this keyword's
    # own SERP, so a keyword-specific spend claim is grounded. `conversion_tag` was measured on their
    # SITE: it proves Google Ads conversion tracking is installed, NOT that they bid on this term —
    # and tags routinely outlive the campaigns that placed them. Saying "you're paying for Google Ads
    # on <keyword>" off a tag is a claim the prospect can falsify in one sentence, which PRD §9a.2
    # names as the way a false claim costs the lead.
    paying_evidence = (paid or {}).get("paying_evidence")
    if paying_and_losing:
        where = (
            f"invisible in Google's map results everywhere across {submarket}"
            if invisible_everywhere
            else f"missing from Google's map results across {_pct(deficit)} of {submarket}"
        )
        if paying_evidence == "conversion_tag":
            text = (
                f"Running Google Ads conversion tracking on their site — they're buying traffic "
                f"somewhere — but {where} for “{keyword}”. Worth asking what they spend and what it "
                f"returns, because the organic side is going to the businesses above them."
            )
        else:
            channel = "a Local Services ad" if paying_evidence == "lsa" else "Google Ads"
            text = (
                f"Paying for {channel} on “{keyword}” but {where} — spending to be found and still "
                f"losing the map pack, which is the gap {name} can close fastest."
            )
        points.append(
            _point(
                ELEM_PAYING,
                text,
                {
                    "paying_evidence": paying_evidence,
                    "prospect_running_ads": paid.get("prospect_running_ads"),
                    "prospect_running_lsa": paid.get("prospect_running_lsa"),
                    "prospect_ad_conversion_tag": paid.get("prospect_ad_conversion_tag"),
                    "coverage_deficit": deficit,
                    "invisible_everywhere": invisible_everywhere,
                },
            )
        )

    # --- competitor: who is taking the space where they're invisible --------------------------
    named = competitors.get("named") or []
    invis_pts = int(competitors.get("invisible_points") or 0)
    if competitors.get("available") and named and invis_pts > 0:
        lead = named[0]
        text = (
            f"{lead['name']} is taking {lead['points']} of the {invis_pts} "
            f"{_plural(invis_pts, 'point')} where {name} never appears — sitting in Google's top "
            f"{pack_size} and pulling the customers {name} can't be seen by"
        )
        if len(named) > 1:
            second = named[1]
            text += f", with {second['name']} taking {second['points']} more"
        total = int(competitors.get("total") or 0)
        if total > len(named):
            text += f" ({total} competitors are splitting that space in all)"
        text += "."
        points.append(
            _point(
                ELEM_COMPETITOR,
                text,
                {
                    "named": named,
                    "total": competitors.get("total"),
                    "invisible_points": invis_pts,
                    "pack_size": pack_size,
                },
            )
        )

    # --- paid placement: rivals buying the search this prospect is losing ---------------------
    # The scoring-spec.md §Buying-intent pitch — a competitor paying to appear at the top while the
    # prospect is invisible. Fires only on the gap (rivals advertising, prospect not); a prospect
    # who IS advertising is a different, scorer-owned signal, not a cold-call talking point here.
    if paid and paid.get("competitors_advertising_gap"):
        ad_names = [a.get("domain") for a in (paid.get("competitor_advertisers") or []) if a.get("domain")]
        lsa_names = [a.get("name") for a in (paid.get("competitor_lsa") or []) if a.get("name")]
        display = lsa_names + ad_names  # LSA names read better than bare domains, so lead with them
        count = int(paid.get("advertiser_count") or 0) + int(paid.get("lsa_count") or 0)
        if display:
            lead = display[0]
            channel = "Local Services ad" if lsa_names else "Google Ad"
            text = f"{lead} is paying for a {channel} on “{keyword}” — buying the customers {name} is invisible to at the top of the search"
            if count > 1:
                text += f", and they're not alone ({count} competitors are buying this search)"
            text += "."
            points.append(
                _point(
                    ELEM_PAID,
                    text,
                    {
                        "competitor_advertisers": paid.get("competitor_advertisers"),
                        "competitor_lsa": paid.get("competitor_lsa"),
                        "advertiser_count": paid.get("advertiser_count"),
                        "lsa_count": paid.get("lsa_count"),
                        "prospect_running_ads": paid.get("prospect_running_ads"),
                        "prospect_running_lsa": paid.get("prospect_running_lsa"),
                    },
                )
            )

    # --- geography: the radial pattern of where they drop off ---------------------------------
    # From the stored, geometry-derived scalars only (centroid_dist_at_loss, avg_rank) — no compass
    # decomposition, which would need the pinned geometry generator this service must not re-derive
    # (outreach ISSUES I-093). Only meaningful when they hold SOME points but lose others.
    if coverage and present > 0 and coverage.get("centroid_dist_at_loss") is not None:
        dist = float(coverage["centroid_dist_at_loss"])
        geo_facts = {
            "centroid_dist_at_loss": round(dist, 1),
            "avg_rank": coverage.get("avg_rank"),
            "best_rank": coverage.get("best_rank"),
        }
        text = (
            f"{name} holds the map pack close to home but loses it past about {_miles(dist)} "
            f"{_plural(round(dist), 'mile')} out — every search from the edges of {submarket} is "
            f"going to a competitor"
        )
        avg_rank = coverage.get("avg_rank")
        if avg_rank is not None:
            text += f", and even where they do appear they sit at position {round(float(avg_rank), 1)}"
        text += "."
        points.append(_point(ELEM_GEOGRAPHY, text, geo_facts))

    # --- reviews vs the local field -----------------------------------------------------------
    own_reviews = resolve_review_count(prospect)
    field_median = field_reviews.get("median")
    sample = int(field_reviews.get("sample") or 0)
    if (
        own_reviews is not None
        and field_median is not None
        and sample >= field_min_sample
        and own_reviews < field_median
    ):
        points.append(
            _point(
                ELEM_REVIEWS,
                f"Only {own_reviews} Google {_plural(own_reviews, 'review')} against a field that "
                f"averages about {_miles(field_median)} — at the moment a searcher compares, "
                f"{name} loses the click to a better-reviewed competitor.",
                {
                    "review_count": own_reviews,
                    "field_median": field_median,
                    "field_sample": sample,
                },
            )
        )

    # --- listing gaps -------------------------------------------------------------------------
    if not (prospect.get("website") or "").strip():
        points.append(
            _point(
                ELEM_NO_WEBSITE,
                "No website linked on their Google listing — even searchers who do find them have "
                "nowhere to go, and it caps how far the listing can rank.",
                {"website": prospect.get("website")},
            )
        )
    if not (prospect.get("phone") or "").strip():
        points.append(
            _point(
                ELEM_NO_PHONE,
                "No phone number on the listing — a customer can't call them straight from Search "
                "or Maps.",
                {"phone": prospect.get("phone")},
            )
        )
    status = (prospect.get("business_status") or "").strip()
    if status not in _OK_STATUSES:
        points.append(
            _point(
                ELEM_LISTING_STATUS,
                f"Google currently shows this listing as “{status.replace('_', ' ').lower()}” — "
                f"worth confirming they're still trading before pitching.",
                {"business_status": status},
            )
        )

    available_elements = [p["element"] for p in points]
    hook_element = next((e for e in HOOK_PRIORITY if e in available_elements), None)
    points_by_element = {p["element"]: p for p in points}

    return {
        "measured": True,
        "prospect_id": prospect.get("id"),
        "prospect_name": name,
        "headline": _headline(name, keyword, submarket, deficit, invisible_everywhere),
        "hook": _compose_hook(
            hook_element, points_by_element,
            name=name, keyword=keyword, submarket=submarket, deficit=deficit,
            invisible_everywhere=invisible_everywhere, pack_size=pack_size, named=named,
            paying_evidence=paying_evidence,
        ),
        "hook_element": hook_element,
        "available_elements": available_elements,
        "talking_points": points,
        # The missed-opportunity dollar estimate (docs/missed-opportunity-valuation-prd-v0_1.md), or
        # None when it wasn't computed / isn't available. Carried as its OWN deterministic field, NOT
        # a talking_point: the LLM call-hook phrasing pass rewrites talking_points and its guard
        # rejects any money number (outreach_call_hook.guard_output), so a computed dollar range rides
        # here — rendered once, never LLM-sharpened, the guard untouched. The `valuation` dict already
        # carries its rendered `line` (built by the I/O layer via outreach_valuation.spoken_line).
        "valuation": valuation,
        "caveats": _caveats(snapshot, competitors),
        "provenance": {
            "snapshot_id": snapshot.get("id"),
            "submarket": submarket,
            "keyword": keyword,
            "scanned_at": snapshot.get("scanned_at"),
            "geometry_version": snapshot.get("geometry_version"),
            "pack_size": pack_size,
            "live_points": total_points,
            "competitors_available": bool(competitors.get("available")),
        },
    }


def not_measured(prospect_id: str, prospect_name: Optional[str]) -> dict[str, Any]:
    """The response when the prospect's submarket has no rolled-up scan.

    Distinct from "invisible everywhere": nothing was measured, so there is no pain to point at and
    no honest talking point to make (outreach/CLAUDE.md — an empty result must never read as total
    invisibility, "the strongest pitch in the market, manufactured").
    """
    return {
        "measured": False,
        "prospect_id": prospect_id,
        "prospect_name": prospect_name or "This business",
        "message": "Not measured yet — this business's area has no completed, rolled-up scan.",
        "talking_points": [],
    }


def _headline(
    name: str, keyword: str, submarket: str, deficit: float, invisible_everywhere: bool
) -> str:
    """One-line loss-framed summary — what is walking out the door, not a neutral state read."""
    if invisible_everywhere:
        return (
            f"{name} is invisible on Google Maps for “{keyword}” in {submarket} — every one of "
            f"those searches is going to a competitor."
        )
    return (
        f"{name} is losing “{keyword}” searches across {_pct(deficit)} of {submarket} on Google "
        f"Maps — that demand is reaching competitors instead."
    )


def _compose_hook(
    hook_element: Optional[str],
    points_by_element: dict[str, dict[str, Any]],
    *,
    name: str,
    keyword: str,
    submarket: str,
    deficit: float,
    invisible_everywhere: bool,
    pack_size: int,
    named: list[dict[str, Any]],
    paying_evidence: Optional[str],
) -> str:
    """The single spoken opener — **loss-framed** and **leading with this prospect's most
    distinctive measured loss** (whatever `hook_element` resolved to), so two businesses in the same
    submarket no longer open with the same coverage line.

    Deterministic FALLBACK: `services/outreach_call_hook.py` rewrites this with an LLM when
    available, grounded on the same facts; this is what ships when the model is unavailable, so it
    must stand on its own. Every clause is a MEASURED fact — the loss is framed, never invented: no
    promises, and no money / lead / traffic-volume numbers (the module's governing invariant; a
    claim the prospect can falsify in one sentence costs the call).
    """
    prefix = f"I searched “{keyword}” across {submarket} —"

    if hook_element == ELEM_PAYING:
        # Evidence-gated exactly as before: serp_ad/lsa were measured on this keyword's SERP so the
        # spend claim is grounded; a conversion tag was measured on their SITE, so the opener ASKS
        # rather than asserts (a caller who says "you're paying for Google Ads on X" to someone who
        # paused that campaign has lost the call). This branch's copy is unchanged.
        where = (
            "you don't show up in the Google map results anywhere I looked"
            if invisible_everywhere
            else f"you're missing from the Google map results across {_pct(deficit)} of the area"
        )
        if paying_evidence == "conversion_tag":
            return (
                f"{prefix} {where}. I noticed you're running Google Ads conversion tracking, so are "
                f"you paying for clicks your competitors are getting for free from the map pack?"
            )
        channel = "a Local Services ad" if paying_evidence == "lsa" else "Google Ads"
        return (
            f"{prefix} you're paying for {channel}, but {where}, so you're buying clicks your "
            f"competitors are getting for free."
        )

    if hook_element == ELEM_COMPETITOR and named:
        lead = named[0]
        pts = int(lead.get("points") or 0)
        return (
            f"{prefix} {lead['name']} is sitting in the top {pack_size} at {pts} of the exact "
            f"{_plural(pts, 'spot')} you never appear, taking those “{keyword}” customers right now."
        )

    if hook_element == ELEM_REVIEWS and ELEM_REVIEWS in points_by_element:
        f = points_by_element[ELEM_REVIEWS]["facts"]
        own = int(f.get("review_count") or 0)
        med = f.get("field_median")
        return (
            f"{prefix} you've got {own} Google {_plural(own, 'review')} against a field that "
            f"averages about {_miles(med)}, so the moment a searcher compares, that call goes to a "
            f"better-reviewed competitor instead of you."
        )

    if hook_element == ELEM_GEOGRAPHY and ELEM_GEOGRAPHY in points_by_element:
        f = points_by_element[ELEM_GEOGRAPHY]["facts"]
        dist = f.get("centroid_dist_at_loss")
        return (
            f"{prefix} you hold the map pack near your shop but disappear past about {_miles(dist)} "
            f"{_plural(round(float(dist)), 'mile')} out, so every “{keyword}” search from the edges "
            f"of {submarket} is going to a competitor."
        )

    if hook_element == ELEM_PAID and ELEM_PAID in points_by_element:
        f = points_by_element[ELEM_PAID]["facts"]
        lsa = [a.get("name") for a in (f.get("competitor_lsa") or []) if a.get("name")]
        ads = [a.get("domain") for a in (f.get("competitor_advertisers") or []) if a.get("domain")]
        display = lsa + ads
        advertiser = display[0] if display else "a competitor"
        return (
            f"{prefix} {advertiser} is paying to sit at the top of a search you're invisible on, "
            f"buying the “{keyword}” customers who never see you."
        )

    # Coverage (and any listing-only fallback): the shared line, still loss-framed.
    if invisible_everywhere:
        clause = (
            f"you don't come up in the Google map results for “{keyword}” anywhere I looked, so "
            f"every one of those searches is going to a competitor"
        )
    else:
        clause = (
            f"you're missing from the Google map results for “{keyword}” across {_pct(deficit)} of "
            f"the area, and those customers are calling whoever shows instead"
        )
    hook = f"{prefix} {clause}"
    if named:
        hook += f" — {named[0]['name']} is one of the businesses taking that space"
    return hook + "."


def _caveats(snapshot: dict[str, Any], competitors: dict[str, Any]) -> list[str]:
    caveats = [
        "These figures are from a single scan; before/after movement becomes available after the "
        "next scan of this area."
    ]
    if not competitors.get("available"):
        caveats.append(
            "Competitor detail isn't available for this scan (the raw ranking data has aged out) "
            "— the coverage figures are unaffected."
        )
    return caveats
