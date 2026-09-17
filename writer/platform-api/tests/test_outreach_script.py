"""Pure-logic tests for the per-prospect call script + rebuttal library.

No network, no database — the whole point of the module is deterministic, fact-grounded assembly
(outreach DECISIONS.md 2026-08-08 design-fork ruling), so it is testable from hand-built inputs
exactly like `outreach_justification` and the heatmap renderer. What is worth pinning: the opener is
the justification's hook verbatim, the evidence section is its talking points verbatim, the value
line is its deterministic valuation line, every grounded rebuttal uses ONLY numbers/names present in
the facts it was handed, the paid `conversion_tag` claim is evidence-gated (I-099), and an unmeasured
prospect still gets a usable generic script that fabricates nothing.
"""
from services import outreach_script as osc


# --- fixtures -----------------------------------------------------------------------------------


def _cov_point(deficit=74.0, present=21, live=81):
    return {
        "element": "coverage",
        "text": "Acme is losing “emergency plumber” searches across 74% of South Bay.",
        "facts": {
            "coverage_pct": round(100 - deficit, 1),
            "coverage_deficit": deficit,
            "points_present": present,
            "live_points": live,
            "invisible_points": live - present,
            "keyword": "emergency plumber",
            "submarket": "South Bay",
        },
    }


def _comp_point():
    return {
        "element": "competitor",
        "text": "Bob’s Plumbing is taking 40 of the 60 points where Acme never appears.",
        "facts": {
            "named": [{"place_id": "b1", "name": "Bob’s Plumbing", "points": 40}],
            "total": 5,
            "invisible_points": 60,
            "pack_size": 3,
        },
    }


def _reviews_point(own=8, median=45.0):
    return {
        "element": "reviews",
        "text": f"Only {own} reviews against a field around {median}.",
        "facts": {"review_count": own, "field_median": median, "field_sample": 12},
    }


def _paying_point(evidence="serp_ad"):
    return {
        "element": "paying",
        "text": "Paying for Google Ads but missing from the map pack.",
        "facts": {
            "paying_evidence": evidence,
            "prospect_running_ads": evidence == "serp_ad",
            "prospect_running_lsa": evidence == "lsa",
            "prospect_ad_conversion_tag": evidence == "conversion_tag",
            "coverage_deficit": 74.0,
            "invisible_everywhere": False,
        },
    }


def _paid_point():
    return {
        "element": "paid",
        "text": "Rival is buying this search.",
        "facts": {
            "competitor_advertisers": [{"domain": "rival-plumbing.com", "rank": 1}],
            "competitor_lsa": [{"name": "FastFlow LSA", "rank": 1}],
            "advertiser_count": 1,
            "lsa_count": 1,
            "prospect_running_ads": False,
            "prospect_running_lsa": False,
        },
    }


def _justification(points, *, hook="I searched “emergency plumber” across South Bay — you're missing…",
                   valuation=None, measured=True, name="Acme Plumbing"):
    return {
        "measured": measured,
        "prospect_id": "p1",
        "prospect_name": name,
        "hook": hook if measured else None,
        "hook_element": "coverage",
        "talking_points": points,
        "valuation": valuation,
        "caveats": ["These figures are from a single scan."],
        "provenance": {
            "snapshot_id": "s1",
            "submarket": "South Bay",
            "keyword": "emergency plumber",
        },
    }


def _rebuttal(script, key):
    return next(r for r in script["rebuttals"] if r["key"] == key)


# --- sections -----------------------------------------------------------------------------------


def test_opener_is_the_justification_hook_verbatim():
    j = _justification([_cov_point()], hook="OPENER LINE")
    script = osc.build_script(justification=j)
    assert script["opening_line"] == "OPENER LINE"
    opener = next(s for s in script["sections"] if s["key"] == "open")
    assert opener["lines"] == ["OPENER LINE"]


def test_evidence_section_is_talking_points_verbatim():
    points = [_cov_point(), _comp_point()]
    script = osc.build_script(justification=_justification(points))
    evidence = next(s for s in script["sections"] if s["key"] == "evidence")
    assert evidence["lines"] == [points[0]["text"], points[1]["text"]]
    # facts carried per element for replayability
    assert evidence["facts"]["coverage"] == points[0]["facts"]
    assert evidence["facts"]["competitor"] == points[1]["facts"]


def test_value_section_uses_the_deterministic_valuation_line_when_present():
    j = _justification([_cov_point()], valuation={"available": True, "line": "About $1,200–$1,800/mo."})
    script = osc.build_script(justification=j)
    value = next(s for s in script["sections"] if s["key"] == "value")
    assert value["lines"] == ["About $1,200–$1,800/mo."]


def test_value_section_falls_back_to_a_number_free_line_without_a_valuation():
    script = osc.build_script(justification=_justification([_cov_point()], valuation=None))
    value = next(s for s in script["sections"] if s["key"] == "value")
    # No fabricated dollar figure when the valuation wasn't computed.
    assert "$" not in value["lines"][0]
    assert "emergency plumber" in value["lines"][0]


def test_close_never_promises_a_ranking():
    script = osc.build_script(justification=_justification([_cov_point()]))
    close = next(s for s in script["sections"] if s["key"] == "close")
    blob = " ".join(close["lines"]).lower()
    assert "walk you through" in blob
    for promise in ("get you ranked", "guarantee", "we'll rank", "number one", "#1"):
        assert promise not in blob


# --- rebuttal library -------------------------------------------------------------------------


def test_rebuttals_are_the_fixed_ordered_set():
    script = osc.build_script(justification=_justification([_cov_point()]))
    keys = [r["key"] for r in script["rebuttals"]]
    assert keys == [
        "already_ranking", "has_agency", "already_ads", "not_interested",
        "too_busy", "price", "email_me", "tried_before", "referral_only",
    ]


def test_already_ranking_grounds_on_deficit_and_named_competitor():
    script = osc.build_script(justification=_justification([_cov_point(), _comp_point()]))
    r = _rebuttal(script, "already_ranking")
    assert r["grounded"] is True
    assert "74%" in r["response"]
    assert "Bob’s Plumbing" in r["response"]
    assert r["facts"]["competitor"]["name"] == "Bob’s Plumbing"


def test_already_ranking_enriched_by_organic_rank_only_when_organic_measured():
    j = _justification([_cov_point()])
    signals = {"organic": {"status": "measured", "prospect_rank": 7, "captured_depth": 20}}
    r = _rebuttal(osc.build_script(justification=j, signals=signals), "already_ranking")
    assert "#7" in r["response"]
    assert r["facts"]["organic_rank"] == 7
    # No organic signal → no organic sentence, and no invented rank.
    r2 = _rebuttal(osc.build_script(justification=j, signals=None), "already_ranking")
    assert "#" not in r2["response"]
    # not_scanned organic is treated as absent (never "not ranking").
    r3 = _rebuttal(
        osc.build_script(justification=j, signals={"organic": {"status": "not_scanned"}}),
        "already_ranking",
    )
    assert "#" not in r3["response"]


def test_already_ads_conversion_tag_never_claims_a_keyword_bid():
    # A conversion tag is measured on the SITE, not this keyword's SERP (I-099) — the rebuttal may
    # say they invest in paid traffic, but must NOT assert they bid on this keyword.
    j = _justification([_cov_point(), _paying_point(evidence="conversion_tag")])
    r = _rebuttal(osc.build_script(justification=j), "already_ads")
    assert r["grounded"] is True
    assert "conversion tracking" in r["response"]
    assert "paying for Google Ads on" not in r["response"]
    assert "paying for a Local Services ad on" not in r["response"]


def test_already_ads_serp_ad_may_name_the_channel_and_keyword():
    j = _justification([_cov_point(), _paying_point(evidence="lsa")])
    r = _rebuttal(osc.build_script(justification=j), "already_ads")
    assert "Local Services ad" in r["response"]
    assert "emergency plumber" in r["response"]


def test_already_ads_competitor_gap_names_only_a_resolved_advertiser():
    j = _justification([_cov_point(), _paid_point()])
    r = _rebuttal(osc.build_script(justification=j), "already_ads")
    assert r["grounded"] is True
    assert "FastFlow LSA" in r["response"]  # LSA name preferred over a bare domain


def test_referral_only_grounds_on_review_delta():
    j = _justification([_cov_point(), _reviews_point(own=8, median=45.0)])
    r = _rebuttal(osc.build_script(justification=j), "referral_only")
    assert r["grounded"] is True
    assert "8 reviews" in r["response"]
    assert "45" in r["response"]


def test_price_and_email_are_generic_and_fabricate_nothing():
    script = osc.build_script(justification=_justification([_cov_point()]))
    price = _rebuttal(script, "price")
    email = _rebuttal(script, "email_me")
    assert price["grounded"] is False and email["grounded"] is False
    assert "$" not in price["response"]  # never a fabricated price


# --- unmeasured (generic) path ----------------------------------------------------------------


def test_unmeasured_prospect_gets_a_generic_but_honest_script():
    j = _justification([], measured=False)
    script = osc.build_script(justification=j)
    assert script["measured"] is False
    assert script["grounded"] is False
    assert script["opening_line"] is None
    # Every rebuttal still present, all generic (nothing to ground on), none fabricated.
    assert len(script["rebuttals"]) == 9
    assert all(r["grounded"] is False for r in script["rebuttals"])
    # An explicit caveat, not a silent empty panel.
    assert any("no rolled-up scan" in c.lower() for c in script["caveats"])
    # No evidence section (nothing measured), but discovery + close still there.
    keys = {s["key"] for s in script["sections"]}
    assert "evidence" not in keys
    assert {"discovery", "close"} <= keys


def test_measured_but_signal_free_prospect_marks_itself_generic():
    # Coverage present but zero deficit-worthy signal is unusual; simulate a measured prospect whose
    # only talking point is a listing gap the rebuttals can't ground on.
    listing = {"element": "no_website", "text": "No website linked.", "facts": {"website": None}}
    script = osc.build_script(justification=_justification([listing]))
    assert script["measured"] is True
    assert script["grounded"] is False
    assert any("generic" in c.lower() for c in script["caveats"])


# --- determinism / replayability --------------------------------------------------------------


def test_build_script_is_deterministic():
    j = _justification([_cov_point(), _comp_point()], valuation={"available": True, "line": "$1k."})
    signals = {"organic": {"status": "measured", "prospect_rank": 4, "captured_depth": 20}}
    assert osc.build_script(justification=j, signals=signals) == osc.build_script(
        justification=j, signals=signals
    )


def test_every_grounded_rebuttal_carries_its_facts():
    j = _justification([_cov_point(), _comp_point(), _reviews_point()])
    for r in osc.build_script(justification=j)["rebuttals"]:
        if r["grounded"]:
            assert r["facts"], f"grounded rebuttal {r['key']} must carry its facts"
