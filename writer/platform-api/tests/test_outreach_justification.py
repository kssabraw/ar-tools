"""Pure-logic tests for the per-prospect call-hook justification.

No network, no database — the whole point of the module is that the assembly is deterministic and
fact-grounded, so it is testable from hand-built inputs exactly like the outreach heatmap renderer.
What is worth pinning here: the byte decode's several shapes, the inferred-zero review convention,
the competitor summarizer's "who beats you where you're invisible" arithmetic and its refusal to
name a place_id it can't resolve, and the assembler's guards — invisible-everywhere phrasing,
geography only when there IS a drop-out radius, the review comparison withheld on a thin sample,
and the hook/available-element attribution.
"""
from services import outreach_justification as oj


# --- decode_rank_vector -------------------------------------------------------------------------


def test_decode_rank_vector_accepts_hex_memoryview_and_bytes():
    raw = bytes([0, 1, 3, 255])
    assert oj.decode_rank_vector(raw) == [0, 1, 3, 255]
    assert oj.decode_rank_vector(bytearray(raw)) == [0, 1, 3, 255]
    assert oj.decode_rank_vector(memoryview(raw)) == [0, 1, 3, 255]
    # PostgREST hands bytea back as a \x-prefixed hex string — the silent-failure shape.
    assert oj.decode_rank_vector("\\x000103ff") == [0, 1, 3, 255]
    assert oj.decode_rank_vector("000103ff") == [0, 1, 3, 255]
    assert oj.decode_rank_vector(None) == []


def test_absent_point_seqs():
    # 0 = absent, 255 = dead (never measured, never absence), other = a rank.
    assert oj.absent_point_seqs([0, 2, 0, 255, 5]) == {0, 2}
    # None means "no coverage row" -> absent everywhere, which the competitor summarizer reads.
    assert oj.absent_point_seqs(None) is None


# --- reviews ------------------------------------------------------------------------------------


def test_resolve_review_count_honours_inferred_zero():
    assert oj.resolve_review_count({"review_count": 12}) == 12
    # NULL count WITH the inferred-zero flag reads as 0 (the provider encodes zero as null).
    assert oj.resolve_review_count({"review_count": None, "review_count_inferred_zero": True}) == 0
    # NULL count WITHOUT the flag is genuinely unknown — never guessed at as zero.
    assert oj.resolve_review_count({"review_count": None, "review_count_inferred_zero": False}) is None
    assert oj.resolve_review_count({"review_count": None}) is None


def test_field_review_stats_median_and_sample():
    rows = [
        {"review_count": 10},
        {"review_count": 20},
        {"review_count": 30},
        {"review_count": None, "review_count_inferred_zero": True},  # counts as 0
        {"review_count": None},  # unknown, dropped
    ]
    stats = oj.field_review_stats(rows)
    assert stats["sample"] == 4  # 10, 20, 30, 0
    assert stats["median"] == 15.0  # median of [0,10,20,30]


def test_field_review_stats_empty():
    assert oj.field_review_stats([]) == {"median": None, "sample": 0}
    assert oj.field_review_stats([{"review_count": None}]) == {"median": None, "sample": 0}


# --- summarize_competitors ----------------------------------------------------------------------


def _pack(seq, place, rank):
    return {"point_seq": seq, "place_id": place, "rank": rank}


def test_summarize_competitors_counts_only_invisible_points_and_names_the_known():
    # Prospect is absent at seqs {3,4,5,6,7}. Pack rows across those + a couple where it isn't.
    pack = [
        _pack(3, "A", 1), _pack(4, "A", 2), _pack(5, "A", 1), _pack(6, "A", 3),
        _pack(3, "B", 2), _pack(4, "B", 3),
        _pack(7, "UNKNOWN", 1),          # holds a pack at an invisible point but has no name
        _pack(0, "A", 1),                # a point the prospect is NOT absent at — excluded
        _pack(3, "SELF", 1),             # the prospect's own listing — never a competitor
    ]
    result = oj.summarize_competitors(
        prospect_place_id="SELF",
        absent_seqs={3, 4, 5, 6, 7},
        pack_rows=pack,
        name_by_place_id={"A": "Ace Plumbing", "B": "Bolt Rooter"},
        max_named=3,
    )
    # Denominator = invisible points that have a pack: {3,4,5,6,7} = 5.
    assert result["invisible_points"] == 5
    # A at {3,4,5,6}=4, B at {3,4}=2, UNKNOWN at {7}=1 -> total 3 distinct competitors.
    assert result["total"] == 3
    # Named, most-dominant first; the unnamed place is counted in total but never named.
    assert [c["name"] for c in result["named"]] == ["Ace Plumbing", "Bolt Rooter"]
    assert result["named"][0]["points"] == 4
    assert result["named"][1]["points"] == 2


def test_summarize_competitors_absent_everywhere_when_no_vector():
    pack = [_pack(0, "A", 1), _pack(1, "A", 2), _pack(2, "B", 1)]
    result = oj.summarize_competitors(
        prospect_place_id="SELF",
        absent_seqs=None,  # no coverage row -> absent at every measured point
        pack_rows=pack,
        name_by_place_id={"A": "Ace", "B": "Bolt"},
        max_named=3,
    )
    assert result["invisible_points"] == 3  # every competitive point counts
    assert result["named"][0] == {"place_id": "A", "name": "Ace", "points": 2}


def test_summarize_competitors_max_named_caps_the_list_not_the_total():
    pack = [_pack(i, chr(65 + i), 1) for i in range(5)]  # A..E, one point each
    names = {chr(65 + i): f"biz-{i}" for i in range(5)}
    result = oj.summarize_competitors(
        prospect_place_id="SELF", absent_seqs={0, 1, 2, 3, 4},
        pack_rows=pack, name_by_place_id=names, max_named=2,
    )
    assert len(result["named"]) == 2
    assert result["total"] == 5


# --- build_justification ------------------------------------------------------------------------


def _prospect(**over):
    base = {
        "id": "p1", "name": "Drips Plumbing", "place_id": "SELF", "phone": "+1 555",
        "website": "https://drips.example", "category": "plumber", "rating": 4.1,
        "review_count": 4, "review_count_inferred_zero": False, "business_status": "OPERATIONAL",
    }
    base.update(over)
    return base


_SNAP = {"id": "snap1", "scanned_at": "2026-08-08T10:00:00Z", "geometry_version": "v1"}
_NO_COMP = {"available": True, "named": [], "total": 0, "invisible_points": 0}


def test_hook_leads_with_the_distinctive_fact_so_neighbours_diverge():
    """Two businesses in the SAME submarket+keyword with the SAME coverage no longer open with the
    same line: the one with a review deficit leads with reviews, the one with none leads with
    coverage. This is the fix for the 'generic and identical' complaint — the hook leads with the
    per-prospect-distinctive loss, not the shared coverage line."""
    coverage = {
        "coverage_pct": 30.0, "points_present": 3, "live_points": 10,
        "best_rank": 2, "worst_rank": 8, "avg_rank": 4.67, "centroid_dist_at_loss": None,
    }
    common = dict(
        keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP, field_min_sample=5, pack_size=3,
    )
    # Prospect A: 4 reviews against a field median of 40 -> reviews lead.
    a = oj.build_justification(prospect=_prospect(review_count=4),
                              field_reviews={"median": 40.0, "sample": 8}, **common)
    # Prospect B: 90 reviews, above field -> no review deficit, coverage leads.
    b = oj.build_justification(prospect=_prospect(review_count=90),
                              field_reviews={"median": 40.0, "sample": 8}, **common)
    assert a["hook_element"] == oj.ELEM_REVIEWS
    assert b["hook_element"] == oj.ELEM_COVERAGE
    assert a["hook"] != b["hook"]
    # A's opener is built from ITS distinctive fact (the review count), not the shared coverage %.
    assert "4 " in a["hook"] and "review" in a["hook"]


def test_hook_is_loss_framed_present_tense():
    """The opener frames an active, ongoing loss — customers going to a competitor now — not a
    neutral 'you could improve' read."""
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=12, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    assert "going to a competitor" in result["hook"]


def test_build_partial_coverage_produces_coverage_and_geography():
    coverage = {
        "coverage_pct": 30.0, "points_present": 3, "live_points": 10,
        "best_rank": 2, "worst_rank": 8, "avg_rank": 4.67, "centroid_dist_at_loss": 2.5,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    assert result["measured"] is True
    elements = result["available_elements"]
    assert oj.ELEM_COVERAGE in elements
    assert oj.ELEM_GEOGRAPHY in elements
    # Coverage leads the hook (strongest state pitch), and the deficit is stated.
    assert result["hook_element"] == oj.ELEM_COVERAGE
    cov = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_COVERAGE)
    assert cov["facts"]["coverage_deficit"] == 70.0
    assert "70%" in cov["text"]
    assert "2.5" in next(p for p in result["talking_points"]
                         if p["element"] == oj.ELEM_GEOGRAPHY)["text"]


def test_build_invisible_everywhere_has_no_geography_point():
    # points_present 0 -> invisible across the whole area; there is no drop-out radius to describe.
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=12, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    assert oj.ELEM_GEOGRAPHY not in result["available_elements"]
    cov = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_COVERAGE)
    assert cov["facts"]["invisible_points"] == 12
    # Loss-framed: the searches are being handed to a competitor, not a neutral "invisible" read.
    assert "handed to a competitor" in cov["text"]
    assert "anywhere I looked" in result["hook"]


def test_build_competitor_point_and_hook_mention():
    competitors = {
        "available": True,
        "named": [{"place_id": "A", "name": "Ace Plumbing", "points": 6},
                  {"place_id": "B", "name": "Bolt Rooter", "points": 3}],
        "total": 5, "invisible_points": 8,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage={"coverage_pct": 20.0, "points_present": 2, "live_points": 10,
                  "best_rank": 3, "worst_rank": 9, "avg_rank": 6.0, "centroid_dist_at_loss": None},
        live_points=10, competitors=competitors,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    comp = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_COMPETITOR)
    assert "Ace Plumbing" in comp["text"] and "Bolt Rooter" in comp["text"]
    assert "5 competitors" in comp["text"]  # total exceeds the named list
    # The hook names the top competitor (PRD §716 shape).
    assert "Ace Plumbing" in result["hook"]
    # centroid_dist_at_loss is None here -> no geography point even though some points are held.
    assert oj.ELEM_GEOGRAPHY not in result["available_elements"]


def test_build_reviews_point_only_below_field_and_with_sample():
    coverage = {"coverage_pct": 50.0, "points_present": 5, "live_points": 10,
                "best_rank": 1, "worst_rank": 4, "avg_rank": 2.0, "centroid_dist_at_loss": 3.0}
    # 4 reviews vs field median 20, sample 8 -> a real deficit, emitted.
    below = oj.build_justification(
        prospect=_prospect(review_count=4), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": 20.0, "sample": 8}, field_min_sample=5, pack_size=3,
    )
    assert oj.ELEM_REVIEWS in below["available_elements"]

    # Thin sample -> the comparison is withheld rather than made on 3 businesses.
    thin = oj.build_justification(
        prospect=_prospect(review_count=4), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": 20.0, "sample": 3}, field_min_sample=5, pack_size=3,
    )
    assert oj.ELEM_REVIEWS not in thin["available_elements"]

    # At/above the field median -> not a weakness to point out, so omitted.
    above = oj.build_justification(
        prospect=_prospect(review_count=40), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": 20.0, "sample": 8}, field_min_sample=5, pack_size=3,
    )
    assert oj.ELEM_REVIEWS not in above["available_elements"]


def test_build_listing_gaps():
    coverage = {"coverage_pct": 50.0, "points_present": 5, "live_points": 10,
                "best_rank": 1, "worst_rank": 4, "avg_rank": 2.0, "centroid_dist_at_loss": None}
    result = oj.build_justification(
        prospect=_prospect(website=None, phone="", business_status="CLOSED_TEMPORARILY"),
        keyword="plumber", submarket="Van Nuys", snapshot=_SNAP, coverage=coverage,
        live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    els = result["available_elements"]
    assert oj.ELEM_NO_WEBSITE in els and oj.ELEM_NO_PHONE in els and oj.ELEM_LISTING_STATUS in els
    status = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_LISTING_STATUS)
    assert "closed temporarily" in status["text"]


def test_build_paid_talking_point_fires_on_the_competitor_gap():
    # Rivals paying for the search the prospect is invisible on — the scoring-spec §Buying-intent pitch.
    paid = {
        "ads_present": True, "lsa_present": True, "prospect_running_ads": False,
        "prospect_running_lsa": False, "prospect_running_any": False,
        "competitor_advertisers": [{"domain": "ace.com", "rank": 1, "title": "Ace"}],
        "competitor_lsa": [{"name": "Reliable Rooter", "rank": 1}],
        "advertiser_count": 1, "lsa_count": 1, "competitors_advertising_gap": True,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    assert oj.ELEM_PAID in result["available_elements"]
    point = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_PAID)
    # LSA names lead over bare ad domains; the "2 in all" count is stated.
    assert "Reliable Rooter" in point["text"]
    assert "2 competitors" in point["text"]
    assert point["facts"]["advertiser_count"] == 1


def test_build_no_paid_point_when_prospect_is_the_advertiser():
    # A prospect who IS advertising has no "rivals only" gap — the scorer owns that signal, not the hook.
    paid = {
        "ads_present": True, "lsa_present": False, "prospect_running_ads": True,
        "prospect_running_lsa": False, "prospect_running_any": True,
        "competitor_advertisers": [], "competitor_lsa": [],
        "advertiser_count": 0, "lsa_count": 0, "competitors_advertising_gap": False,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    assert oj.ELEM_PAID not in result["available_elements"]


def test_build_paying_and_losing_is_the_lead_hook():
    # Prospect IS paying (AW tag / SERP paid / LSA) AND invisible -> the strongest opener.
    paid = {
        "ads_present": True, "lsa_present": False, "prospect_running_ads": True,
        "prospect_running_lsa": False, "prospect_running_any": True, "prospect_is_paying": True,
        "prospect_paying_this_keyword": True, "paying_evidence": "serp_ad",
        "prospect_ad_conversion_tag": True, "competitor_advertisers": [], "competitor_lsa": [],
        "advertiser_count": 0, "lsa_count": 0, "competitors_advertising_gap": False,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=12, competitors=_NO_COMP,     # coverage None -> invisible everywhere
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    assert oj.ELEM_PAYING in result["available_elements"]
    # It outranks coverage as the hook, and the spoken hook agrees (leads with the paying pitch).
    assert result["hook_element"] == oj.ELEM_PAYING
    assert "paying for Google Ads" in result["hook"]
    assert "getting for free" in result["hook"]
    point = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_PAYING)
    assert point["facts"]["invisible_everywhere"] is True


def test_build_paying_but_not_losing_does_not_fire():
    # Paying AND good coverage (present, low deficit) -> no "losing" pitch.
    paid = {"prospect_is_paying": True, "prospect_running_lsa": False}
    coverage = {"coverage_pct": 90.0, "points_present": 9, "live_points": 10,
                "best_rank": 1, "worst_rank": 3, "avg_rank": 1.5, "centroid_dist_at_loss": None}
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    assert oj.ELEM_PAYING not in result["available_elements"]
    assert "paying for" not in result["hook"]


def test_build_no_paid_point_when_signal_absent():
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=None,
    )
    assert oj.ELEM_PAID not in result["available_elements"]


def test_build_is_deterministic():
    coverage = {"coverage_pct": 30.0, "points_present": 3, "live_points": 10,
                "best_rank": 2, "worst_rank": 8, "avg_rank": 4.67, "centroid_dist_at_loss": 2.5}
    kwargs = dict(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=coverage, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    assert oj.build_justification(**kwargs) == oj.build_justification(**kwargs)


def test_build_always_carries_single_scan_caveat_and_provenance():
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=10,
        competitors={"available": False, "named": [], "total": 0, "invisible_points": 0},
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3,
    )
    assert any("single scan" in c for c in result["caveats"])
    # Competitor data unavailable -> its own caveat, and provenance records it.
    assert any("aged out" in c for c in result["caveats"])
    assert result["provenance"]["competitors_available"] is False
    assert result["provenance"]["snapshot_id"] == "snap1"
    assert result["provenance"]["geometry_version"] == "v1"


def test_not_measured():
    result = oj.not_measured("p1", "Drips Plumbing")
    assert result["measured"] is False
    assert result["talking_points"] == []
    assert "Not measured" in result["message"]


def test_a_site_tag_alone_never_claims_keyword_spend_regression():
    """REGRESSION: an `AW-` tag on the prospect's SITE produced the spoken line "you're paying for
    Google Ads" about a keyword whose SERP showed no ad from them. The tag proves tracking is
    installed, not that they bid on this term — and tags routinely outlive the campaigns that placed
    them, so the claim is falsifiable in one sentence on the call."""
    paid = {
        "ads_present": False, "lsa_present": False, "prospect_running_ads": False,
        "prospect_running_lsa": False, "prospect_running_any": False,
        "prospect_is_paying": True, "prospect_paying_this_keyword": False,
        "paying_evidence": "conversion_tag", "prospect_ad_conversion_tag": True,
        "competitor_advertisers": [], "competitor_lsa": [],
        "advertiser_count": 0, "lsa_count": 0, "competitors_advertising_gap": False,
    }
    result = oj.build_justification(
        prospect=_prospect(), keyword="emergency plumber", submarket="Los Angeles", snapshot=_SNAP,
        coverage=None, live_points=81, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    # It still fires (proven budget somewhere + measured invisibility) …
    assert result["hook_element"] == oj.ELEM_PAYING
    # … but it ASKS about spend rather than asserting it on this keyword.
    assert "you're paying for Google Ads" not in result["hook"]
    assert "conversion tracking" in result["hook"] and result["hook"].rstrip().endswith("?")
    point = next(p for p in result["talking_points"] if p["element"] == oj.ELEM_PAYING)
    assert "Running Google Ads conversion tracking" in point["text"]
    assert point["facts"]["paying_evidence"] == "conversion_tag"


def test_lsa_evidence_names_the_lsa_channel():
    paid = {"prospect_is_paying": True, "prospect_paying_this_keyword": True,
            "paying_evidence": "lsa", "prospect_running_lsa": True, "prospect_running_ads": False}
    result = oj.build_justification(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
        coverage=None, live_points=10, competitors=_NO_COMP,
        field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid,
    )
    assert "a Local Services ad" in result["hook"]


def test_losing_deficit_threshold_is_configurable():
    paid = {"prospect_is_paying": True, "paying_evidence": "serp_ad",
            "prospect_paying_this_keyword": True, "prospect_running_lsa": False}
    coverage = {"coverage_pct": 70.0, "points_present": 7, "live_points": 10,
                "best_rank": 1, "worst_rank": 5, "avg_rank": 2.0, "centroid_dist_at_loss": None}
    kw = dict(prospect=_prospect(), keyword="plumber", submarket="Van Nuys", snapshot=_SNAP,
              coverage=coverage, live_points=10, competitors=_NO_COMP,
              field_reviews={"median": None, "sample": 0}, field_min_sample=5, pack_size=3, paid=paid)
    # 30% deficit: below the default 50 bar -> not "losing".
    assert oj.ELEM_PAYING not in oj.build_justification(**kw)["available_elements"]
    # A stricter bar makes the same scan qualify.
    assert oj.ELEM_PAYING in oj.build_justification(**kw, losing_deficit_pct=25.0)["available_elements"]
