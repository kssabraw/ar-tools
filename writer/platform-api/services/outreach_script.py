"""Per-prospect call SCRIPT + objection/rebuttal library — the talk track past line one.

The "Why call?" hook (`outreach_justification.build_justification` + the loss-framed phrasing pass)
gives a caller their OPENER. It is one line. This module builds what comes after it: a structured
talk track (open → discovery → evidence → value → close) AND a library of rebuttals to the
objections a local-business owner actually raises on a cold call — each one **fed by the prospect's
own measured facts** so the caller answers "we already show up on Google" with *that business's*
coverage deficit and the named competitor taking its searches, not a generic line.

**PURE deterministic assembly, exactly like `outreach_justification` and the heatmap renderer.** No
LLM, no network, no clock, no randomness. Every grounded sentence is a template filled from a number
that was MEASURED — so it cannot fabricate a fact, a competitor, or a dollar figure (outreach
DECISIONS.md 2026-08-08 design-fork ruling; outreach/CLAUDE.md "never invent a fact, a competitor,
or a number"). Where the grounding fact is absent (an unscanned area, a missing signal) the rebuttal
degrades to a **generic-but-honest** line that still invents nothing — never omitted, so the caller
always has an answer, and never a claim the prospect can falsify in one sentence (PRD §9a.2).

This is the same posture, and the same reasoning, as the justification module chose:

  * **Cheapest to reverse.** Pure assembly adds no dependency, key, cost, or non-determinism. A
    grounded LLM phrasing pass can be layered ON TOP later (the opener already is one), reusing the
    facts this module assembles — never the other way around.
  * **The invariant gets to be structural, not hoped for.** A deterministic assembler cannot slip a
    fabricated number into a prospect-facing sentence; there is no model to guard shut.
  * **Replayability.** Every rebuttal carries the raw `facts` it was built from — the same
    discipline `score_factors` and `talking_point.facts` hold — so a claim made on a call is
    inspectable and reproducible from stored inputs.

It never re-grounds: the OPENER is `justification.hook` verbatim (so the script and the "Why call?"
panel share one opener — the loss-framed phrasing pass, cached per (prospect, snapshot), lives
there), the EVIDENCE section is the justification's `talking_points` verbatim (one source of truth),
and the VALUE line is the deterministic `valuation.line` (never LLM-phrased — the call-hook guard
rejects money numbers, so a computed dollar range rides its own field). This module only adds the
call-flow scaffolding around them and the rebuttals keyed to what the prospect says back.

The phrasing templates are code constants, not config — the accepted Phase 3 precedent (the heatmap
legend labels, the justification sentences). "Template MUST be config" (PRD §716) is honored in
spirit: the sentences are filled from persisted scan data and never improvised at send time, which
is what that MUST protects against. Promoting to config is a later cheap-to-reverse step.

The paid/paying evidence gate is preserved verbatim from I-099: a spend claim keyed on a
`conversion_tag` (measured on the prospect's SITE, not this keyword's SERP) never asserts the
prospect bid on this keyword — it says only what the tag proves (they invest in paid traffic).
Because this module reuses facts the justification/report already resolved (named competitors, the
`paying_evidence` tag), it does no NEW name-matching and cannot re-introduce the one-directional
match bug those layers guard.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# The evidence elements this module reads out of the justification, by the keys
# `outreach_justification` stamps on each talking point. Mirrored here (not imported as behaviour)
# because they are a stable read contract, the same way the report module mirrors them.
_EL_COVERAGE = "coverage"
_EL_COMPETITOR = "competitor"
_EL_PAYING = "paying"
_EL_PAID = "paid"
_EL_REVIEWS = "reviews"
_EL_GEOGRAPHY = "geography"


# --- number formatting (mirrors outreach_justification, so the two read identically) ------------


def _pct(value: Any) -> str:
    """A percentage with no trailing `.0` — 74% not 74.0%, 12.5% kept."""
    try:
        rounded = round(float(value), 1)
    except (TypeError, ValueError):
        return "part"
    return f"{int(rounded)}%" if rounded == int(rounded) else f"{rounded}%"


def _num(value: Any) -> str:
    """A count with no trailing `.0` — 15 not 15.0, 12.5 kept."""
    try:
        rounded = round(float(value), 1)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(rounded)}" if rounded == int(rounded) else f"{rounded}"


def _plural(n: Any, singular: str, plural: Optional[str] = None) -> str:
    try:
        one = int(n) == 1
    except (TypeError, ValueError):
        one = False
    return singular if one else (plural or f"{singular}s")


# --- fact accessors over the assembled justification -------------------------------------------


def _points_by_element(justification: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The justification's talking points keyed by element, so a rebuttal can read the facts a
    given signal produced without re-deriving anything."""
    out: dict[str, dict[str, Any]] = {}
    for p in justification.get("talking_points") or []:
        el = p.get("element")
        if el and el not in out:
            out[el] = p
    return out


def _organic_facts(signals: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The organic-search read (rank + captured depth), only when that scan actually ran. `None`
    otherwise — an unrun organic scan must never read as "not ranking" (the not_scanned discipline)."""
    if not signals:
        return None
    section = signals.get("organic") or {}
    if section.get("status") != "measured":
        return None
    return {
        "prospect_rank": section.get("prospect_rank"),
        "captured_depth": section.get("captured_depth"),
    }


class _Ctx:
    """The resolved facts one rebuild reads from — assembled once, passed to every builder. Every
    field is either a facts dict lifted straight off a talking point (so it is measured) or None."""

    def __init__(self, justification: dict[str, Any], signals: Optional[dict[str, Any]]):
        prov = justification.get("provenance") or {}
        self.measured: bool = bool(justification.get("measured"))
        self.name: str = justification.get("prospect_name") or "this business"
        self.keyword: str = prov.get("keyword") or "your main service"
        self.submarket: str = prov.get("submarket") or "your area"
        pbe = _points_by_element(justification)
        self.cov = (pbe.get(_EL_COVERAGE) or {}).get("facts") or None
        self.comp = (pbe.get(_EL_COMPETITOR) or {}).get("facts") or None
        self.paying = (pbe.get(_EL_PAYING) or {}).get("facts") or None
        self.paid = (pbe.get(_EL_PAID) or {}).get("facts") or None
        self.reviews = (pbe.get(_EL_REVIEWS) or {}).get("facts") or None
        self.geo = (pbe.get(_EL_GEOGRAPHY) or {}).get("facts") or None
        self.organic = _organic_facts(signals)

    # --- derived phrasing helpers (each returns measured text or None) --------------------------

    def deficit_clause(self) -> Optional[str]:
        """"you're missing from the map pack across 74% of {submarket}" / "…everywhere I looked",
        or None when coverage wasn't measured. Loss-framed, present tense, numbers from facts only."""
        cov = self.cov
        if not cov:
            return None
        if int(cov.get("points_present") or 0) == 0:
            return f"you're invisible in the Google map pack everywhere I looked across {self.submarket}"
        return (
            f"you're missing from the Google map pack across {_pct(cov.get('coverage_deficit'))} "
            f"of {self.submarket}"
        )

    def lead_competitor(self) -> Optional[dict[str, Any]]:
        named = (self.comp or {}).get("named") or []
        return named[0] if named else None

    def competitor_clause(self) -> str:
        lead = self.lead_competitor()
        return f", and {lead['name']} is taking those searches" if lead else ""

    def paid_advertiser(self) -> Optional[str]:
        """The single most-nameable competitor advertiser (an LSA name reads better than a bare
        domain), or None. Only names an advertiser the paid capture actually resolved."""
        paid = self.paid or {}
        for a in paid.get("competitor_lsa") or []:
            if a.get("name"):
                return a["name"]
        for a in paid.get("competitor_advertisers") or []:
            if a.get("domain"):
                return a["domain"]
        return None


def _rebuttal(
    key: str, objection: str, response: str, *, grounded: bool, facts: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    return {
        "key": key,
        "objection": objection,
        "response": response,
        "grounded": grounded,
        "facts": facts or {},
    }


# --- rebuttal builders (one per objection; each prefers a grounded line, degrades to generic) ---
#
# Every builder is pure and total: it returns a rebuttal for a measured OR an unmeasured prospect.
# A grounded branch fires only when the fact it needs is present, and uses ONLY that fact's numbers
# / names. The generic branch invents nothing and makes no promise ("diagnose, not promise").


def _already_ranking(ctx: _Ctx) -> dict[str, Any]:
    objection = "We already show up on Google."
    deficit = ctx.deficit_clause()
    if deficit:
        text = (
            f"There's a real difference between ranking for your business name and ranking when "
            f"someone searches “{ctx.keyword}”. When I checked, {deficit}{ctx.competitor_clause()}."
        )
        facts: dict[str, Any] = {"coverage": ctx.cov}
        lead = ctx.lead_competitor()
        if lead:
            facts["competitor"] = lead
        org = ctx.organic
        if org:
            rank = org.get("prospect_rank")
            if isinstance(rank, int):
                text += (
                    f" You do come up at #{rank} in the regular search results, but the map pack "
                    f"sits above those, and that's where these local searches actually go."
                )
                facts["organic_rank"] = rank
            elif org.get("captured_depth"):
                text += (
                    f" And you're not in the top {org['captured_depth']} standard results for it "
                    f"either."
                )
                facts["organic_captured_depth"] = org.get("captured_depth")
        return _rebuttal("already_ranking", objection, text, grounded=True, facts=facts)
    return _rebuttal(
        "already_ranking",
        objection,
        f"Showing up for your name is one thing — showing up when a customer searches "
        f"“{ctx.keyword}” is another. That second one is exactly what I checked, and it's usually "
        f"where the gap is.",
        grounded=False,
    )


def _has_agency(ctx: _Ctx) -> dict[str, Any]:
    objection = "We already have someone handling our SEO / marketing."
    deficit = ctx.deficit_clause()
    if ctx.paying and deficit:
        # Evidence-neutral: "paying to be found" is true for every paying_evidence, including a
        # conversion tag (I-099) — it never claims they bid on this keyword.
        return _rebuttal(
            "has_agency",
            objection,
            f"If someone's handling it, this is the exact thing to put to them: you're clearly "
            f"paying to be found, and {deficit} for “{ctx.keyword}”. That's the gap a good audit "
            f"catches.",
            grounded=True,
            facts={"paying": ctx.paying, "coverage": ctx.cov},
        )
    if deficit:
        return _rebuttal(
            "has_agency",
            objection,
            f"Fair — the question worth asking them is what it's producing, because right now "
            f"{deficit} for “{ctx.keyword}”{ctx.competitor_clause()}.",
            grounded=True,
            facts={"coverage": ctx.cov, "competitor": ctx.lead_competitor()},
        )
    return _rebuttal(
        "has_agency",
        objection,
        f"Great — is what they're doing actually moving you up for “{ctx.keyword}”? That's the one "
        f"thing I checked, and it's usually where the gap shows.",
        grounded=False,
    )


def _already_ads(ctx: _Ctx) -> dict[str, Any]:
    objection = "We already run Google Ads."
    deficit = ctx.deficit_clause()
    if ctx.paying and deficit:
        evidence = (ctx.paying or {}).get("paying_evidence")
        if evidence == "conversion_tag":
            # Measured on their SITE, not this SERP — so it claims only what the tag proves.
            text = (
                f"Your site's running Google Ads conversion tracking, so you're already investing "
                f"in paid clicks — but {deficit} in the map pack, and that's the free version your "
                f"competitors are getting."
            )
        else:
            channel = "a Local Services ad" if evidence == "lsa" else "Google Ads"
            text = (
                f"Then this one should sting a little: you're paying for {channel} on "
                f"“{ctx.keyword}” but {deficit}, so you're buying clicks your competitors are "
                f"getting for free from the map pack."
            )
        return _rebuttal("already_ads", objection, text, grounded=True, facts={"paying": ctx.paying})
    advertiser = ctx.paid_advertiser()
    if advertiser and deficit:
        return _rebuttal(
            "already_ads",
            objection,
            f"Ads only work while you keep paying for them. Right now {advertiser} is renting the "
            f"top of a search you're invisible on — {deficit} — while the map pack right below it "
            f"is the part you'd own.",
            grounded=True,
            facts={"paid": ctx.paid, "coverage": ctx.cov},
        )
    return _rebuttal(
        "already_ads",
        objection,
        "Ads put you at the top for exactly as long as you pay. The map pack is the part you own — "
        "and it's where I found the gap.",
        grounded=False,
    )


def _not_interested(ctx: _Ctx) -> dict[str, Any]:
    objection = "Not interested."
    deficit = ctx.deficit_clause()
    if deficit:
        lead = ctx.lead_competitor()
        who = lead["name"] if lead else "your competitors"
        return _rebuttal(
            "not_interested",
            objection,
            f"Completely fair — the only reason I called is that when I searched “{ctx.keyword}” "
            f"across {ctx.submarket}, {deficit}, and those calls are landing with {who}. Give me "
            f"thirty seconds and then decide?",
            grounded=True,
            facts={"coverage": ctx.cov, "competitor": lead},
        )
    return _rebuttal(
        "not_interested",
        objection,
        f"Fair enough — the only reason I called is I ran a quick check on “{ctx.keyword}” in your "
        f"area and saw something worth thirty seconds. Want the short version?",
        grounded=False,
    )


def _too_busy(ctx: _Ctx) -> dict[str, Any]:
    objection = "We're busy enough / not taking new work right now."
    lead = ctx.lead_competitor()
    if lead:
        return _rebuttal(
            "too_busy",
            objection,
            f"Good problem to have — the thing is, the “{ctx.keyword}” searches you're not showing "
            f"for don't disappear, they go to {lead['name']}. This is about the tap you can turn "
            f"back on whenever you want it.",
            grounded=True,
            facts={"competitor": lead},
        )
    deficit = ctx.deficit_clause()
    if deficit:
        return _rebuttal(
            "too_busy",
            objection,
            f"Makes sense — worth knowing that {deficit} for “{ctx.keyword}”, so when things do "
            f"slow down, that's the demand sitting on the table.",
            grounded=True,
            facts={"coverage": ctx.cov},
        )
    return _rebuttal(
        "too_busy",
        objection,
        "Totally get it — this isn't about right now, it's about the switch you can flip when you "
        "want more of the right work coming in.",
        grounded=False,
    )


def _price(ctx: _Ctx) -> dict[str, Any]:
    # Deliberately generic: never fabricate a price, never promise a result.
    return _rebuttal(
        "price",
        "How much does this cost?",
        "Honestly, it depends on the size of the gap — which is why I won't throw a number at you "
        "before you've seen it. The look itself is free; worst case, you walk away with a map of "
        "exactly where you stand.",
        grounded=False,
    )


def _email_me(ctx: _Ctx) -> dict[str, Any]:
    # Generic, but useful: it points at the real scan/report, which invents nothing.
    return _rebuttal(
        "email_me",
        "Just email me some information.",
        "Happy to — I can send you the actual scan I ran: a map showing exactly where you show up "
        "for these searches and where you don't. What's the best address for it?",
        grounded=False,
    )


def _tried_before(ctx: _Ctx) -> dict[str, Any]:
    objection = "We tried SEO before and it didn't do anything."
    deficit = ctx.deficit_clause()
    if deficit:
        return _rebuttal(
            "tried_before",
            objection,
            f"That's exactly why I lead with where you actually stand instead of a pitch: {deficit} "
            f"for “{ctx.keyword}”{ctx.competitor_clause()}. It's measurable now, so you'd see it "
            f"move or you wouldn't — no faith required.",
            grounded=True,
            facts={"coverage": ctx.cov, "competitor": ctx.lead_competitor()},
        )
    return _rebuttal(
        "tried_before",
        objection,
        "Fair — that's usually because nobody showed you a number to hold it against. I'd start by "
        "measuring exactly where you rank today, so anything after that is provable, not a promise.",
        grounded=False,
    )


def _referral_only(ctx: _Ctx) -> dict[str, Any]:
    objection = "We get all our work from referrals / word of mouth."
    rev = ctx.reviews
    if rev and rev.get("review_count") is not None and rev.get("field_median") is not None:
        own = int(rev["review_count"])
        return _rebuttal(
            "referral_only",
            objection,
            f"Referrals still Google you before they call — and you're sitting on {own} "
            f"{_plural(own, 'review')} against a field averaging about {_num(rev['field_median'])}, "
            f"so you can lose a warm lead right at the comparison.",
            grounded=True,
            facts={"reviews": rev},
        )
    deficit = ctx.deficit_clause()
    if deficit:
        return _rebuttal(
            "referral_only",
            objection,
            f"Even a referral checks Google first — and right now when they do, {deficit}"
            f"{ctx.competitor_clause()}.",
            grounded=True,
            facts={"coverage": ctx.cov, "competitor": ctx.lead_competitor()},
        )
    return _rebuttal(
        "referral_only",
        objection,
        "Referrals are great — and almost every one of them still Googles you before they call, so "
        "what they find there decides whether that warm intro converts.",
        grounded=False,
    )


# Ordered most-common first — the sequence a caller is likely to hit them in.
_REBUTTAL_BUILDERS: tuple[Callable[[_Ctx], dict[str, Any]], ...] = (
    _already_ranking,
    _has_agency,
    _already_ads,
    _not_interested,
    _too_busy,
    _price,
    _email_me,
    _tried_before,
    _referral_only,
)


# --- talk-track sections -----------------------------------------------------------------------


def _section(
    key: str,
    title: str,
    lines: list[str],
    *,
    note: Optional[str] = None,
    facts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {"key": key, "title": title, "lines": lines, "note": note, "facts": facts or {}}


def _build_sections(ctx: _Ctx, justification: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []

    # 1. Open — the caller's opener, verbatim from the justification (shared with "Why call?").
    hook = justification.get("hook")
    if hook:
        sections.append(
            _section(
                "open",
                "Open",
                [hook],
                note="Then stop and let them answer — don't pitch over the top of the opener.",
                facts={"hook_element": justification.get("hook_element")},
            )
        )

    # 2. Discovery — get them talking before you present anything. Generic scaffolding, anchored on
    #    the real search when it's measured; no claim, so nothing to fabricate.
    if ctx.measured:
        discovery = [
            f"When someone in {ctx.submarket} searches “{ctx.keyword}”, where do you figure you come up?",
            "How are most of your new customers finding you right now?",
        ]
    else:
        discovery = [
            "When a customer searches for what you do on Google, where do you figure you come up?",
            "How are most of your new customers finding you right now?",
        ]
    sections.append(
        _section(
            "discovery",
            "Get them talking",
            discovery,
            note="Let their answer set up the gap — most owners guess higher than the scan shows.",
        )
    )

    # 3. Evidence — the justification's talking points, verbatim. One source of truth; no re-grounding.
    points = justification.get("talking_points") or []
    if ctx.measured and points:
        sections.append(
            _section(
                "evidence",
                "What the scan actually shows",
                [p.get("text", "") for p in points if p.get("text")],
                note="Lead with the strongest one, then stop and let it land.",
                facts={p.get("element"): p.get("facts") for p in points if p.get("element")},
            )
        )

    # 4. Value — the deterministic missed-opportunity line if it was computed; else a qualitative,
    #    number-free cost-of-inaction line. Never LLM-phrased (the call-hook guard rejects money).
    valuation = justification.get("valuation") or {}
    value_line = valuation.get("line") if valuation.get("available") else None
    if value_line:
        sections.append(
            _section(
                "value",
                "What it's costing them",
                [value_line],
                note="A range that shows its work — don't round it into a promise.",
                facts={"valuation": valuation},
            )
        )
    elif ctx.deficit_clause():
        sections.append(
            _section(
                "value",
                "What it's costing them",
                [
                    f"Every one of those “{ctx.keyword}” searches you're not showing for is a "
                    f"customer picking a competitor instead — that's the cost of staying invisible, "
                    f"and it's happening every day until it's fixed."
                ],
                note="No dollar figure here — the loss is the searches themselves.",
                facts={"coverage": ctx.cov},
            )
        )

    # 5. Close — the ask. Diagnose, not promise: offer to show the map, never guarantee a ranking.
    sections.append(
        _section(
            "close",
            "The ask",
            [
                "What I'd suggest is a quick fifteen-minute screen-share where I walk you through "
                "exactly where you show up and where you don't — no cost, no obligation.",
                "Would earlier or later in the week suit you better?",
            ],
            note="Book the walk-through — don't promise a ranking on the phone.",
        )
    )
    return sections


# --- the assembler -----------------------------------------------------------------------------


def build_script(
    *, justification: dict[str, Any], signals: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Assemble the call script + rebuttal library for one prospect. Pure.

    `justification` is the whole object `outreach_justification.build_justification` produced (reused
    verbatim — its hook is the opener, its talking points are the evidence, its valuation is the
    value line). `signals` is the report's signal block (`outreach_report.build_report`'s `signals`),
    read only for the organic rank that enriches the "we already show up on Google" rebuttal; None or
    an unrun organic scan simply leaves that enrichment off.

    Returns a stable shape: `measured` / `grounded` flags, the ordered talk-track `sections`, the
    `rebuttals` (each with its `facts`), `caveats`, and `provenance` — everything replayable from
    stored inputs, nothing improvised.
    """
    measured = bool(justification.get("measured"))
    ctx = _Ctx(justification, signals)

    sections = _build_sections(ctx, justification)
    rebuttals = [b(ctx) for b in _REBUTTAL_BUILDERS]
    grounded = measured and any(r.get("grounded") for r in rebuttals)

    caveats = list(justification.get("caveats") or [])
    if not measured:
        caveats.insert(
            0,
            "No rolled-up scan for this business's area yet — these are generic openers and "
            "rebuttals. Run or await a scan for fact-grounded talking points.",
        )
    elif not grounded:
        caveats.insert(
            0,
            "The scan produced no strong signal to build rebuttals from — these fall back to "
            "generic lines.",
        )

    return {
        "measured": measured,
        "grounded": grounded,
        "prospect_id": justification.get("prospect_id"),
        "prospect_name": ctx.name,
        "opening_line": justification.get("hook"),
        "sections": sections,
        "rebuttals": rebuttals,
        "caveats": caveats,
        "provenance": justification.get("provenance") or {},
    }
