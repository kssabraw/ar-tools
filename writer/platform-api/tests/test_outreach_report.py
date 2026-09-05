"""Pure-logic tests for the per-prospect report assembly.

No network, no database — the assembly is deterministic and fact-grounded, so it is testable from
hand-built inputs. What matters here: the maps rankings-vs-competitors table (pack presence + best
rank, prospect excluded from its own competitor list, unresolved place_ids counted but never named),
and that a signal with no scan renders as an explicit not_scanned block rather than an empty table.
"""
from services import outreach_report as orep


def _pack(seq, place, rank):
    return {"point_seq": seq, "place_id": place, "rank": rank}


def test_build_maps_comparison_scores_pack_presence_and_best_rank():
    pack = [
        _pack(0, "SELF", 3), _pack(1, "SELF", 2),        # prospect holds 2 points, best rank 2
        _pack(0, "A", 1), _pack(1, "A", 1), _pack(2, "A", 2),  # Ace: 3 points, best 1
        _pack(2, "B", 1),                                 # Bolt: 1 point, best 1
        _pack(3, "UNKNOWN", 1),                           # unresolved -> counted, never named
    ]
    section = orep.build_maps_comparison(
        prospect_place_id="SELF",
        pack_rows=pack,
        name_by_place_id={"A": "Ace Plumbing", "B": "Bolt Rooter"},
        coverage={"coverage_pct": 25.0, "points_present": 2, "best_rank": 2, "avg_rank": 2.5},
        live_points=8,
        max_competitors=3,
    )
    assert section["status"] == orep.STATUS_MEASURED
    # Named competitors, most pack presence first; the prospect is not in its own competitor list.
    assert [c["name"] for c in section["competitors"]] == ["Ace Plumbing", "Bolt Rooter"]
    assert section["competitors"][0] == {
        "place_id": "A", "name": "Ace Plumbing", "pack_points": 3,
        "pack_share_pct": round(100.0 * 3 / 8, 1), "best_rank": 1,
    }
    # The unresolved place is counted in the total but never named.
    assert section["total_competitors"] == 3  # A, B, UNKNOWN
    assert section["prospect"]["pack_points"] == 2
    assert section["prospect"]["pack_best_rank"] == 2


def test_build_maps_comparison_prospect_absent_from_pack():
    # Prospect holds no pack spot anywhere — pack_points 0, still a valid comparison row.
    pack = [_pack(0, "A", 1), _pack(1, "A", 2)]
    section = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=pack,
        name_by_place_id={"A": "Ace"}, coverage=None, live_points=6, max_competitors=3,
    )
    assert section["prospect"]["pack_points"] == 0
    assert section["prospect"]["coverage_pct"] == 0.0
    assert section["competitors"][0]["name"] == "Ace"


def test_build_maps_comparison_caps_named_competitors():
    pack = [_pack(i, chr(65 + i), 1) for i in range(5)]
    names = {chr(65 + i): f"biz-{i}" for i in range(5)}
    section = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=pack, name_by_place_id=names,
        coverage=None, live_points=10, max_competitors=2,
    )
    assert len(section["competitors"]) == 2
    assert section["total_competitors"] == 5


def test_not_scanned_section():
    s = orep.not_scanned_section(orep.SIGNAL_ORGANIC, "no scan yet")
    assert s == {"status": orep.STATUS_NOT_SCANNED, "signal": "organic", "reason": "no scan yet"}


# --- domain_of + build_organic_section --------------------------------------------------------


def test_domain_of_matches_the_producer_side():
    assert orep.domain_of("https://www.AcePlumbing.com/x") == "aceplumbing.com"
    assert orep.domain_of("boltrooter.com") == "boltrooter.com"
    assert orep.domain_of("") is None and orep.domain_of(None) is None


def _summary(results, ai=False, depth=20):
    return {"engine": "google_organic", "captured_depth": depth,
            "ai_overview_present": ai, "results": results}


def test_build_organic_section_finds_prospect_rank_and_competitors():
    summary = _summary([
        {"rank": 1, "domain": "bigrooter.com", "url": "u1", "title": "Big Rooter"},
        {"rank": 2, "domain": "ace.com", "url": "u2", "title": "Ace"},
        {"rank": 5, "domain": "drips.com", "url": "u3", "title": "Drips"},  # the prospect
    ], ai=True)
    section = orep.build_organic_section(
        summary, prospect_website="https://www.drips.com/services", max_competitors=2
    )
    assert section["status"] == orep.STATUS_MEASURED
    assert section["prospect_domain"] == "drips.com"
    assert section["prospect_rank"] == 5
    assert section["ai_overview_present"] is True
    # Competitors are the top domains, prospect's own excluded, capped.
    assert [c["domain"] for c in section["competitors"]] == ["bigrooter.com", "ace.com"]


def test_build_organic_section_prospect_not_in_results():
    summary = _summary([{"rank": 1, "domain": "ace.com"}, {"rank": 2, "domain": "bolt.com"}])
    section = orep.build_organic_section(
        summary, prospect_website="drips.com", max_competitors=3
    )
    # Not in the captured depth -> None (not ranking in the top N), never a guessed position.
    assert section["prospect_rank"] is None
    assert [c["domain"] for c in section["competitors"]] == ["ace.com", "bolt.com"]


def test_build_organic_section_no_summary_is_not_scanned():
    section = orep.build_organic_section(None, prospect_website="x.com", max_competitors=3)
    assert section["status"] == orep.STATUS_NOT_SCANNED
    assert section["signal"] == orep.SIGNAL_ORGANIC


def test_build_organic_section_no_website_still_lists_competitors():
    summary = _summary([{"rank": 1, "domain": "ace.com"}])
    section = orep.build_organic_section(summary, prospect_website=None, max_competitors=3)
    assert section["prospect_domain"] is None
    assert section["prospect_rank"] is None
    assert section["competitors"][0]["domain"] == "ace.com"


# --- detect_ai_mention + build_llm_section ----------------------------------------------------


def test_detect_ai_mention_name_domain_and_short_guard():
    # Named directly.
    assert orep.detect_ai_mention(
        prospect_name="Drips Plumbing", prospect_domain=None,
        named_businesses=["Ace", "Drips Plumbing"], reference_domains=[], raw_excerpt=None) is True
    # Named only in prose.
    assert orep.detect_ai_mention(
        prospect_name="Drips Plumbing", prospect_domain=None,
        named_businesses=[], reference_domains=[], raw_excerpt="…try Drips Plumbing on Main St…") is True
    # Domain cited in AIO references.
    assert orep.detect_ai_mention(
        prospect_name="X", prospect_domain="drips.com",
        named_businesses=[], reference_domains=["ace.com", "drips.com"], raw_excerpt=None) is True
    # Not named at all.
    assert orep.detect_ai_mention(
        prospect_name="Drips Plumbing", prospect_domain="drips.com",
        named_businesses=["Ace", "Bolt"], reference_domains=["ace.com"], raw_excerpt="Ace and Bolt") is False
    # Short name never matches on substring (avoids trivial hits).
    assert orep.detect_ai_mention(
        prospect_name="AB", prospect_domain=None,
        named_businesses=["ABC Plumbing and Sons"], reference_domains=[], raw_excerpt=None) is False


def test_build_llm_section_measured_marks_visibility_per_engine():
    rows = [
        {"engine": "chatgpt", "present": True,
         "named_businesses": ["Ace Plumbing", "Bolt Rooter", "Drips Plumbing"],
         "reference_domains": [], "raw_excerpt": ""},
        {"engine": "google_aio", "present": True,
         "named_businesses": ["Ace Plumbing"], "reference_domains": ["ace.com"], "raw_excerpt": "Ace"},
    ]
    section = orep.build_llm_section(
        engine_rows=rows, prospect_name="Drips Plumbing", prospect_domain="drips.com",
        region="Van Nuys", name_level="suburb",
    )
    assert section["status"] == orep.STATUS_MEASURED
    by = {e["engine"]: e for e in section["engines"]}
    assert by["chatgpt"]["visible"] is True                      # named in ChatGPT
    assert by["google_aio"]["visible"] is False                  # not named in AIO
    assert by["google_aio"]["sample_businesses"] == ["Ace Plumbing"]
    assert "caveat" not in section                               # suburb -> no neighbourhood caveat


def test_build_llm_section_neighbourhood_carries_caveat():
    rows = [{"engine": "chatgpt", "present": True, "named_businesses": ["Ace"],
             "reference_domains": [], "raw_excerpt": ""}]
    section = orep.build_llm_section(
        engine_rows=rows, prospect_name="Drips", prospect_domain=None,
        region="Hollywood", name_level="neighbourhood",
    )
    assert "caveat" in section


def test_build_llm_section_empty_is_not_scanned():
    section = orep.build_llm_section(
        engine_rows=[], prospect_name="Drips", prospect_domain=None, region="Van Nuys", name_level=None)
    assert section["status"] == orep.STATUS_NOT_SCANNED
    assert section["signal"] == orep.SIGNAL_LLM


def test_build_llm_section_engine_present_false_is_never_visible():
    rows = [{"engine": "chatgpt", "present": False, "named_businesses": [],
             "reference_domains": [], "raw_excerpt": None}]
    section = orep.build_llm_section(
        engine_rows=rows, prospect_name="Drips", prospect_domain=None, region="X", name_level="city")
    assert section["engines"][0]["visible"] is False


# --- paid placement (the fourth signal) -------------------------------------------------------


def _paid_block(advertisers=None, lsa=None):
    ads = advertisers or []
    ls = lsa or []
    return {
        "ads_present": bool(ads), "lsa_present": bool(ls),
        "advertisers": ads, "lsa_advertisers": ls, "seen_item_types": ["organic"],
    }


def test_derive_paid_signal_competitor_gap_is_the_pitch():
    # Rivals paying, prospect not — the highest-value cold-outreach signal (scoring-spec §Buying intent).
    block = _paid_block(
        advertisers=[{"domain": "ace.com", "rank": 1, "title": "Ace"},
                     {"domain": "ace.com", "rank": 2, "title": "Ace dup"},   # deduped by domain
                     {"domain": "bolt.com", "rank": 3, "title": "Bolt"}],
        lsa=[{"name": "Reliable Rooter", "rank": 1}],
    )
    sig = orep.derive_paid_signal(block, prospect_website="drips.com", prospect_name="Drips Plumbing", max_named=3)
    assert sig["ads_present"] is True and sig["lsa_present"] is True
    assert sig["prospect_running_ads"] is False and sig["prospect_running_any"] is False
    assert [a["domain"] for a in sig["competitor_advertisers"]] == ["ace.com", "bolt.com"]  # deduped, rank-sorted
    assert sig["advertiser_count"] == 2 and sig["lsa_count"] == 1
    assert sig["competitors_advertising_gap"] is True


def test_derive_paid_signal_prospect_is_the_advertiser_no_gap():
    # The prospect's OWN domain/name in the ad lists — proven budget, but not the "rivals only" pitch.
    block = _paid_block(
        advertisers=[{"domain": "www.drips.com", "rank": 1, "title": "Drips"}],
        lsa=[{"name": "Drips Plumbing", "rank": 1}],
    )
    sig = orep.derive_paid_signal(block, prospect_website="https://drips.com", prospect_name="Drips Plumbing", max_named=3)
    assert sig["prospect_running_ads"] is True and sig["prospect_running_lsa"] is True
    assert sig["prospect_running_any"] is True
    assert sig["competitor_advertisers"] == [] and sig["competitor_lsa"] == []
    assert sig["competitors_advertising_gap"] is False   # no rival-only gap when the prospect advertises


def test_derive_paid_signal_absent_never_manufactures_a_claim():
    sig = orep.derive_paid_signal(_paid_block(), prospect_website="drips.com", prospect_name="Drips", max_named=3)
    assert sig["ads_present"] is False and sig["lsa_present"] is False
    assert sig["competitors_advertising_gap"] is False


def test_build_paid_section_not_scanned_when_no_summary_or_no_paid_block():
    # No organic capture at all.
    s0 = orep.build_paid_section(None, prospect_website="x.com", prospect_name="X", max_competitors=3)
    assert s0["status"] == orep.STATUS_NOT_SCANNED and s0["signal"] == orep.SIGNAL_PAID
    # A capture that predates paid parsing (no "paid" key) is honestly not_scanned, never "no ads".
    s1 = orep.build_paid_section({"results": []}, prospect_website="x.com", prospect_name="X", max_competitors=3)
    assert s1["status"] == orep.STATUS_NOT_SCANNED


def test_lsa_match_is_one_directional_regression():
    """REGRESSION: a bidirectional substring match made a SHORTER competitor name inside a LONGER
    prospect name read as the prospect — asserting an LSA they don't run AND deleting a real
    competitor. Both are fabrications; the match is one-directional now."""
    block = _paid_block(lsa=[{"name": "AAA Plumbing", "rank": 1}, {"name": "Speedy Rooter", "rank": 2}])
    sig = orep.derive_paid_signal(
        block, prospect_website="aaaplumbingservices.com",
        prospect_name="AAA Plumbing Services", max_named=3,
    )
    assert sig["prospect_running_lsa"] is False          # they run NO LSA
    assert sig["prospect_is_paying"] is False
    assert [c["name"] for c in sig["competitor_lsa"]] == ["AAA Plumbing", "Speedy Rooter"]
    assert sig["competitors_advertising_gap"] is True    # the real pitch survives


def test_lsa_match_still_catches_the_prospects_longer_legal_name():
    # The kept direction: the LSA lists a longer name than the GBP one.
    block = _paid_block(lsa=[{"name": "Drips Plumbing & Sons LLC", "rank": 1}])
    sig = orep.derive_paid_signal(
        block, prospect_website="drips.com", prospect_name="Drips Plumbing", max_named=3)
    assert sig["prospect_running_lsa"] is True and sig["competitor_lsa"] == []


def _tech(**over):
    base = {"fetch_status": "ok", "meta_pixel": False, "google_ads_conversion": False,
            "vendor_tags": [], "gtm_container_ids": []}
    base.update(over)
    return base


def test_derive_paid_signal_folds_site_tech_additively():
    # No SERP ads, but the prospect's own site carries an AW conversion tag + two vendor tags.
    block = _paid_block()
    sig = orep.derive_paid_signal(
        block, prospect_website="drips.com", prospect_name="Drips", max_named=3,
        tech=_tech(google_ads_conversion=True, meta_pixel=True, vendor_tags=["callrail", "podium"]),
    )
    assert sig["tech_measured"] is True
    assert sig["prospect_ad_conversion_tag"] is True and sig["prospect_meta_pixel"] is True
    assert sig["prospect_vendor_tags"] == ["callrail", "podium"]
    assert sig["prospect_likely_represented"] is True          # 2 vendor signals
    # An AW tag means they're paying — the broad "is paying" read used by the losing pitch.
    assert sig["prospect_is_paying"] is True
    # Slice-A SERP semantics are untouched: no SERP ad block -> these stay false.
    assert sig["prospect_running_ads"] is False


def test_derive_paid_signal_failed_tech_fetch_is_unknown_not_absent():
    # A failed fetch must contribute nothing — unknown never reads as "no ad tech".
    sig = orep.derive_paid_signal(
        _paid_block(), prospect_website="drips.com", prospect_name="Drips", max_named=3,
        tech=_tech(fetch_status="unreachable", google_ads_conversion=True),  # booleans ignored
    )
    assert sig["tech_measured"] is False
    assert sig["prospect_ad_conversion_tag"] is False and sig["prospect_is_paying"] is False


def test_build_paid_section_includes_tech():
    summary = {"results": [], "paid": _paid_block()}
    section = orep.build_paid_section(
        summary, prospect_website="drips.com", prospect_name="Drips", max_competitors=3,
        tech=_tech(meta_pixel=True),
    )
    assert section["status"] == orep.STATUS_MEASURED
    assert section["prospect_meta_pixel"] is True


def test_build_paid_section_measured_carries_the_signal():
    summary = {"results": [], "paid": _paid_block(advertisers=[{"domain": "ace.com", "rank": 1, "title": "Ace"}])}
    section = orep.build_paid_section(summary, prospect_website="drips.com", prospect_name="Drips", max_competitors=3)
    assert section["status"] == orep.STATUS_MEASURED and section["signal"] == orep.SIGNAL_PAID
    assert section["competitors_advertising_gap"] is True


def test_client_paid_html_states_the_gap_and_escapes():
    section = orep.build_paid_section(
        {"results": [], "paid": _paid_block(advertisers=[{"domain": "ace.com", "rank": 1, "title": "Ace"}])},
        prospect_website="drips.com", prospect_name="Drips", max_competitors=3,
    )
    doc = _report_doc({"status": "not_measured", "signal": "maps"},
                      orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
                      orep.not_scanned_section(orep.SIGNAL_LLM, "x"), paid=section)
    html = orep.render_client_report_html(doc, agency_name="Amazing Rankings")
    assert "buying the customers you" in html   # the competitor-gap pitch copy
    assert "ace.com" in html and "Google Ads" in html


def test_client_paid_html_no_ads_is_a_finding():
    section = orep.build_paid_section({"results": [], "paid": _paid_block()},
                                      prospect_website="drips.com", prospect_name="Drips", max_competitors=3)
    doc = _report_doc({"status": "not_measured", "signal": "maps"},
                      orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
                      orep.not_scanned_section(orep.SIGNAL_LLM, "x"), paid=section)
    html = orep.render_client_report_html(doc, agency_name="Amazing Rankings")
    assert "still won on merit" in html


def _prospect():
    return {"id": "p1", "name": "Drips Plumbing", "category": "plumber", "phone": "+1",
            "website": "", "address": "1 Main St", "rating": 4.1, "review_count": 4}


def test_build_report_shape_and_client_draft_gate():
    justification = {"measured": True, "hook": "…", "talking_points": [],
                     "provenance": {"snapshot_id": "snap1"}}
    maps = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=[_pack(0, "A", 1)],
        name_by_place_id={"A": "Ace"}, coverage=None, live_points=5, max_competitors=3,
    )
    report = orep.build_report(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys",
        justification=justification, maps_section=maps,
        organic_section=orep.not_scanned_section(orep.SIGNAL_ORGANIC, "staged"),
        llm_section=orep.not_scanned_section(orep.SIGNAL_LLM, "staged"),
        paid_section=orep.not_scanned_section(orep.SIGNAL_PAID, "staged"),
        heatmap_available=True,
    )
    assert report["measured"] is True
    assert report["identity"]["name"] == "Drips Plumbing"
    assert report["signals"]["maps"]["status"] == orep.STATUS_MEASURED
    # Organic, LLM and paid are explicit not_scanned blocks — never an empty table.
    assert report["signals"]["organic"]["status"] == orep.STATUS_NOT_SCANNED
    assert report["signals"]["llm"]["status"] == orep.STATUS_NOT_SCANNED
    assert report["signals"]["paid"]["status"] == orep.STATUS_NOT_SCANNED
    # The client-facing face is a DRAFT, unapproved, until the approval slice lands.
    assert report["client_facing"]["approved"] is False
    # The hook is reused verbatim from the justification, not re-derived.
    assert report["justification"] is justification


def test_build_report_reflects_approval():
    j = {"measured": True, "provenance": {}, "talking_points": []}
    base = dict(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", justification=j,
        maps_section={"status": "measured"},
        organic_section=orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
        llm_section=orep.not_scanned_section(orep.SIGNAL_LLM, "x"),
        paid_section=orep.not_scanned_section(orep.SIGNAL_PAID, "x"),
        heatmap_available=False,
    )
    draft = orep.build_report(**base)
    assert draft["client_facing"]["approved"] is False and draft["client_facing"]["status"] == "draft"

    approved = orep.build_report(**base, approval={"approved_by": "u1", "created_at": "2026-08-08"})
    assert approved["client_facing"]["approved"] is True
    assert approved["client_facing"]["approved_by"] == "u1"
    assert approved["client_facing"]["status"] == "approved"


# --- render_client_report_html ----------------------------------------------------------------


def _report_doc(maps, organic, llm, name="Drips Plumbing", paid=None):
    return {
        "identity": {"name": name}, "keyword": "plumber", "submarket": "Van Nuys",
        "signals": {"maps": maps, "organic": organic, "llm": llm,
                    "paid": paid if paid is not None else orep.not_scanned_section(orep.SIGNAL_PAID, "x")},
    }


def test_render_client_report_html_contains_the_facts_and_escapes():
    maps = orep.build_maps_comparison(
        prospect_place_id="SELF", pack_rows=[_pack(0, "A", 1)],
        name_by_place_id={"A": "Ace Plumbing"},
        coverage={"coverage_pct": 20.0, "points_present": 2, "best_rank": 3, "avg_rank": 5.0},
        live_points=8, max_competitors=3,
    )
    organic = orep.build_organic_section(
        _summary([{"rank": 1, "domain": "ace.com", "title": "Ace"}]),
        prospect_website="drips.com", max_competitors=3,
    )
    llm = orep.build_llm_section(
        engine_rows=[{"engine": "chatgpt", "present": True, "named_businesses": ["Ace"],
                      "reference_domains": [], "raw_excerpt": ""}],
        prospect_name="Drips Plumbing", prospect_domain="drips.com",
        region="Van Nuys", name_level="suburb",
    )
    html = orep.render_client_report_html(
        _report_doc(maps, organic, llm, name="Drips & Sons <Plumbing>"), agency_name="Amazing Rankings"
    )
    assert "Your Google visibility for" in html and "plumber" in html
    assert "Ace Plumbing" in html                       # a maps competitor
    assert "Prepared by Amazing Rankings" in html       # white-label footer
    assert "Draft" not in html                          # approved asset — no draft watermark
    # The prospect name is escaped, not injected as markup.
    assert "Drips &amp; Sons &lt;Plumbing&gt;" in html
    assert "<Plumbing>" not in html


def test_render_client_report_html_not_scanned_blocks_never_empty_tables():
    html = orep.render_client_report_html(
        _report_doc(
            {"status": "not_measured", "signal": "maps"},
            orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
            orep.not_scanned_section(orep.SIGNAL_LLM, "x"),
        ),
        agency_name="Amazing Rankings",
    )
    # Four "will be added" placeholders (maps, organic, llm, paid), no fabricated competitor rows.
    assert html.count("will be added") == 4
    assert "<tbody>" not in html


def test_build_report_deterministic():
    justification = {"measured": True, "provenance": {}, "talking_points": []}
    kwargs = dict(
        prospect=_prospect(), keyword="plumber", submarket="Van Nuys", justification=justification,
        maps_section={"status": "measured"},
        organic_section=orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
        llm_section=orep.not_scanned_section(orep.SIGNAL_LLM, "x"),
        paid_section=orep.not_scanned_section(orep.SIGNAL_PAID, "x"),
        heatmap_available=False,
    )
    assert orep.build_report(**kwargs) == orep.build_report(**kwargs)


def test_paying_evidence_separates_measured_spend_from_a_site_tag():
    """A conversion tag proves tracking is installed, NOT that they bid on this keyword. The two
    must be distinguishable, or a prospect-facing sentence claims unmeasured spend."""
    # Tag only, no ad in this SERP's paid block.
    tag_only = orep.derive_paid_signal(
        _paid_block(), prospect_website="drips.com", prospect_name="Drips", max_named=3,
        tech=_tech(google_ads_conversion=True))
    assert tag_only["paying_evidence"] == "conversion_tag"
    assert tag_only["prospect_is_paying"] is True           # broad read
    assert tag_only["prospect_paying_this_keyword"] is False  # NOT measured on this keyword

    # Measured in this SERP's paid block.
    in_serp = orep.derive_paid_signal(
        _paid_block(advertisers=[{"domain": "drips.com", "rank": 1, "title": "Drips"}]),
        prospect_website="drips.com", prospect_name="Drips", max_named=3,
        tech=_tech(google_ads_conversion=True))
    assert in_serp["paying_evidence"] == "serp_ad"
    assert in_serp["prospect_paying_this_keyword"] is True

    # LSA beats the tag as evidence.
    lsa = orep.derive_paid_signal(
        _paid_block(lsa=[{"name": "Drips Plumbing", "rank": 1}]),
        prospect_website="drips.com", prospect_name="Drips Plumbing", max_named=3,
        tech=_tech(google_ads_conversion=True))
    assert lsa["paying_evidence"] == "lsa" and lsa["prospect_paying_this_keyword"] is True

    # Nothing at all.
    assert orep.derive_paid_signal(_paid_block(), prospect_website="d.com",
                                   prospect_name="D", max_named=3)["paying_evidence"] is None


def test_likely_represented_needs_two_vendor_tags_not_gtm():
    """REGRESSION: GTM is a free, near-universal Google tool, so counting it as an agency signal
    flagged DIY operators. `likely_represented` is the one derived flag that scores NEGATIVE."""
    gtm_plus_one = orep.derive_paid_signal(
        _paid_block(), prospect_website="d.com", prospect_name="Drips", max_named=3,
        tech=_tech(vendor_tags=["callrail"], gtm_container_ids=["GTM-A1"]))
    assert gtm_plus_one["prospect_likely_represented"] is False
    two_vendors = orep.derive_paid_signal(
        _paid_block(), prospect_website="d.com", prospect_name="Drips", max_named=3,
        tech=_tech(vendor_tags=["callrail", "podium"]))
    assert two_vendors["prospect_likely_represented"] is True


def test_client_pdf_does_not_claim_keyword_spend_from_a_site_tag():
    section = orep.build_paid_section(
        {"results": [], "paid": _paid_block(advertisers=[{"domain": "ace.com", "rank": 1, "title": "Ace"}])},
        prospect_website="drips.com", prospect_name="Drips", max_competitors=3,
        tech=_tech(google_ads_conversion=True))
    html = orep.render_client_report_html(
        _report_doc({"status": "not_measured", "signal": "maps"},
                    orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
                    orep.not_scanned_section(orep.SIGNAL_LLM, "x"), paid=section),
        agency_name="AR")
    assert "You’re paying to advertise for" not in html      # the unmeasured claim
    assert "conversion tracking" in html                     # what was actually observed


# --- client-facing valuation box (Phase B) ----------------------------------------------------


def test_client_valuation_html_renders_ad_cost_anchor():
    box = orep._client_valuation_html({
        "available": True,
        "ad_cost_equivalent_monthly": 3400,
        "missed_revenue_low_monthly": 6000,   # present but deliberately NOT shown client-facing
        "missed_revenue_high_monthly": 14000,
        "how_estimated": "Estimated from metro search volume, scaled by population.",
    })
    assert "Estimated missed opportunity" in box
    assert "$3,400/month" in box                       # the ad-cost anchor, formatted
    assert "Estimate, not a guarantee" in box          # honest framing
    assert "scaled by population" in box               # shows its work
    # The soft-assumption missed-revenue band is INTERNAL — it must not appear client-facing.
    assert "6,000" not in box and "14,000" not in box


def test_client_valuation_html_omitted_when_unavailable_or_no_anchor():
    assert orep._client_valuation_html(None) == ""
    assert orep._client_valuation_html({"available": False}) == ""
    # available but no CPC → no ad-cost anchor → a band alone is too soft for a client asset.
    assert orep._client_valuation_html({"available": True, "ad_cost_equivalent_monthly": None}) == ""
    assert orep._client_valuation_html({"available": True, "ad_cost_equivalent_monthly": 0}) == ""


def test_render_client_report_html_includes_valuation_when_present():
    doc = _report_doc(
        {"status": "not_measured", "signal": "maps"},
        orep.not_scanned_section(orep.SIGNAL_ORGANIC, "x"),
        orep.not_scanned_section(orep.SIGNAL_LLM, "x"),
    )
    # No valuation key → box absent (the disabled / unavailable default).
    assert "Estimated missed opportunity" not in orep.render_client_report_html(doc, agency_name="AR")
    # With an available valuation → box present.
    doc["valuation"] = {"available": True, "ad_cost_equivalent_monthly": 1200,
                        "how_estimated": "Estimated from local demand."}
    html = orep.render_client_report_html(doc, agency_name="AR")
    assert "Estimated missed opportunity" in html and "$1,200/month" in html
