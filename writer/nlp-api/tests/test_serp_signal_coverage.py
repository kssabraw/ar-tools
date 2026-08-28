"""Unit tests for the deterministic SERP-signal coverage engine's UI payload.

Covers the additive fields surfaced to the generated-page view: entities_used /
entities_missing (page-level) and the per-zone found/target breakdown. Pure +
offline (bs4 only) — no network, no Anthropic.
Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _serp_analysis():
    """A minimal SERP analysis with keyword + entity zone targets and quadgrams."""
    return {
        "related_keywords": {
            "h2_h3": [
                {"term": "roof restoration", "recommended_mentions": 3, "max_competitor_mentions": 5, "page_spread": 4,
                 "zone_freq": {"h2_h3": 2, "paragraphs": 3}},
                {"term": "roof repairs", "recommended_mentions": 2, "max_competitor_mentions": 2, "page_spread": 3},
            ],
            # "roof restoration" also in paragraphs with a lower recommended — the
            # detail should keep the higher (3) after deduping across zones.
            "paragraphs": [
                {"term": "roof restoration", "recommended_mentions": 1, "max_competitor_mentions": 1, "page_spread": 2},
                {"term": "tile roof", "recommended_mentions": 2, "max_competitor_mentions": 3, "page_spread": 3},
            ],
        },
        "zone_targets": {
            "h2_h3": {"target": 2, "entity_target": 1},
            "paragraphs": {"target": 2, "entity_target": 2},
        },
        "google_entities": [
            {"name": "Melbourne", "page_spread": 5, "recommended_mentions": 4, "max_competitor_mentions": 6, "avg_competitor_mentions": 3.2,
             "zone_freq": {"paragraphs": 4}},
            {"name": "Colorbond", "page_spread": 4, "recommended_mentions": 3, "max_competitor_mentions": 4, "avg_competitor_mentions": 2.5},
            {"name": "Slate", "page_spread": 3, "recommended_mentions": 2, "max_competitor_mentions": 3, "avg_competitor_mentions": 1.5},
        ],
        "serp_bold_keywords": [
            {"term": "free quote", "recommended_mentions": 2, "max_competitor_uses": 2, "avg_uses": 1.5,
             "page_spread": 3, "zone_freq": {"paragraphs": 2}},
        ],
        "top_quadgrams": [{"phrase": "licensed roofing contractor"}],
    }


def test_reports_entities_used_and_missing():
    html = (
        "<article><h2>Roof Restoration in Melbourne</h2>"
        "<p>We install Colorbond roofing across the city. Tile roof work too.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    # Melbourne + Colorbond appear; Slate does not.
    assert set(res["entities_used"]) == {"Melbourne", "Colorbond"}
    assert res["entities_missing"] == ["Slate"]


def test_entity_chips_capped_at_thirty_ranked_by_page_spread():
    # 40 unique entities, all present on the page, ranked by descending
    # page_spread. Both the UI "Entities used" chips AND the per-zone entity
    # score use the top 30 by page_spread (raised from 15).
    entities = [
        {"name": f"Entity{i:02d}", "page_spread": 40 - i, "recommended_mentions": 1}
        for i in range(40)
    ]
    serp = {
        "related_keywords": {},
        "zone_targets": {},
        "google_entities": entities,
        "top_quadgrams": [],
    }
    body = " ".join(e["name"] for e in entities)
    res = main._compute_serp_signal_coverage(f"<article><p>{body}</p></article>", serp)
    # Exactly the top 30 by page_spread surface as chips (all present → all used).
    assert len(res["entities_used"]) == 30
    assert res["entities_missing"] == []
    assert res["entities_used"] == [f"Entity{i:02d}" for i in range(30)]
    # Entity31+ (below the chip cap) are excluded.
    assert "Entity30" not in res["entities_used"]


def test_score_counts_entities_ranked_16_to_30():
    # The per-zone entity SCORE (not just the chips) uses the top 30. A page that
    # mentions ONLY entities ranked 16–19 (outside the old top-15) still gets
    # credit toward the zone's entity_target — so scoring against the wider set
    # can only lift entity_coverage, never lower it (found_ents is a superset;
    # target is fixed).
    entities = [{"name": f"Ent{i:02d}", "page_spread": 20 - i} for i in range(20)]
    serp = {
        "related_keywords": {},
        "zone_targets": {"paragraphs": {"target": 0, "entity_target": 3}},
        "google_entities": entities,
        "top_quadgrams": [],
    }
    body = " ".join(f"Ent{i:02d}" for i in range(16, 20))  # ranks 16–19 only
    res = main._compute_serp_signal_coverage(f"<article><p>{body}</p></article>", serp)
    # Chips include the rank-16–19 entities...
    assert set(res["entities_used"]) == {"Ent16", "Ent17", "Ent18", "Ent19"}
    # ...and the SCORE counts them: 4 found / target 3 -> min(4/3, 1) = 1.0 ->
    # entity_coverage 100. Under a top-15 score these entities were invisible (0).
    assert res["entity_coverage"] == 100.0


def test_nameless_entities_are_skipped():
    # An entity dict without a "name" must not crash (KeyError) and must not be
    # treated as present — an empty name would match every zone.
    entities = [
        {"page_spread": 9},                       # no "name" key
        {"name": "", "page_spread": 8},           # empty name
        {"name": "Melbourne", "page_spread": 7},
    ]
    serp = {
        "related_keywords": {},
        "zone_targets": {"paragraphs": {"target": 0, "entity_target": 1}},
        "google_entities": entities,
        "top_quadgrams": [],
    }
    res = main._compute_serp_signal_coverage(
        "<article><p>Roofing across Melbourne.</p></article>", serp
    )
    assert res["entities_used"] == ["Melbourne"]
    assert res["entities_missing"] == []


def test_reports_per_zone_found_and_target():
    html = (
        "<article><h2>Roof Restoration and Roof Repairs</h2>"
        "<p>Tile roof care in Melbourne.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    zones = {z["zone"]: z for z in res["zones"]}
    # Both H2/H3 keyword targets are met.
    assert zones["H2/H3 headings"]["keyword_found"] == 2
    assert zones["H2/H3 headings"]["keyword_target"] == 2
    # Paragraph zone carries both keyword and entity found/target.
    assert zones["paragraphs"]["keyword_target"] == 2
    assert zones["paragraphs"]["entity_target"] == 2


def test_no_serp_analysis_has_no_coverage_fields():
    res = main._compute_serp_signal_coverage("<p>hi</p>", None)
    assert res["score"] == 50
    assert "entities_used" not in res  # degraded payload stays minimal


def test_entity_detail_reports_current_recommended_and_shortfall():
    # Melbourne x2, Colorbond x1, Slate x0 on the page.
    html = (
        "<article><h2>Roof Restoration in Melbourne</h2>"
        "<p>Colorbond roofing across Melbourne. We install it well.</p></article>"
    )
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    detail = {d["name"]: d for d in res["entity_detail"]}
    # current mention counts (word-boundary, page-level)
    assert detail["Melbourne"]["current"] == 2
    assert detail["Colorbond"]["current"] == 1
    assert detail["Slate"]["current"] == 0
    # recommended carried from the SERP analysis
    assert detail["Melbourne"]["recommended"] == 4
    assert detail["Slate"]["recommended"] == 2
    # shortfall = max(0, recommended - current)
    assert detail["Melbourne"]["shortfall"] == 2   # 4 - 2
    assert detail["Colorbond"]["shortfall"] == 2   # 3 - 1
    assert detail["Slate"]["shortfall"] == 2       # 2 - 0
    # biggest gaps first, ties broken by page_spread (Melbourne before others)
    assert res["entity_detail"][0]["name"] == "Melbourne"
    # rollups
    assert set(res["entities_under_target"]) == {"Melbourne", "Colorbond", "Slate"}
    assert res["total_entity_shortfall"] == 6


def test_capped_max_target_beats_top_competitor_but_caps_outlier():
    # counts [1, 1, 4]: avg 2.0, ceil(1.5*2)=3, max 4 -> recommended capped at 3
    rec, mx, avg = main._capped_max_target([1, 1, 4])
    assert (rec, mx, avg) == (3, 4, 2.0)
    # tight field [3, 3, 4]: avg 3.33, ceil(1.5*3.33)=5, max 4 -> recommended = max (4)
    rec, mx, avg = main._capped_max_target([3, 3, 4])
    assert rec == 4 and mx == 4
    # empty -> floored at 1
    assert main._capped_max_target([]) == (1, 0, 0.0)


def test_entity_detail_carries_competitor_max_and_avg():
    html = "<article><p>Melbourne Colorbond roofing.</p></article>"
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    detail = {d["name"]: d for d in res["entity_detail"]}
    assert detail["Melbourne"]["max_competitor"] == 6
    assert detail["Melbourne"]["avg_competitor"] == 3.2


def test_keyword_detail_dedupes_zones_and_reports_shortfall():
    # "roof restoration" x1 on the page; recommended is the HIGHER of the two zone
    # entries (3), so shortfall = 2. "tile roof" x0 -> shortfall 2. "roof repairs"
    # x0 -> shortfall 2.
    html = "<article><h2>Roof Restoration</h2><p>quality roofing work.</p></article>"
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    kd = {d["name"]: d for d in res["keyword_detail"]}
    assert kd["roof restoration"]["recommended"] == 3   # higher zone wins after dedupe
    assert kd["roof restoration"]["current"] == 1
    assert kd["roof restoration"]["shortfall"] == 2
    assert kd["roof restoration"]["max_competitor"] == 5
    assert set(res["keywords_under_target"]) == {"roof restoration", "roof repairs", "tile roof"}
    assert res["total_keyword_shortfall"] == 2 + 2 + 2  # restoration 2, repairs 2, tile 2


def test_bold_detail_uses_raw_competitor_max():
    # "free quote" appears once; bold benchmark is the raw competitor max (2).
    html = "<article><p>Get a free quote today from our Melbourne team.</p></article>"
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    bd = {d["name"]: d for d in res["bold_detail"]}
    assert bd["free quote"]["current"] == 1
    assert bd["free quote"]["recommended"] == 2      # raw max, not capped
    assert bd["free quote"]["max_competitor"] == 2
    assert bd["free quote"]["shortfall"] == 1
    assert res["total_bold_shortfall"] == 1


def test_zone_breakdown_reports_per_zone_current_vs_target():
    # Melbourne carries a paragraphs zone target of 4; the page uses it once in a
    # <p>, so the body zone row is 1/4 (shortfall 3). Zones without a competitor
    # benchmark (title/h1/h2_h3 for Melbourne) are omitted.
    html = "<article><h2>Roofing</h2><p>Melbourne roofing services.</p></article>"
    res = main._compute_serp_signal_coverage(html, _serp_analysis())
    mel = next(d for d in res["entity_detail"] if d["name"] == "Melbourne")
    zones = {z["zone"]: z for z in mel["zones"]}
    assert set(zones) == {"body"}
    assert zones["body"]["current"] == 1
    assert zones["body"]["recommended"] == 4
    assert zones["body"]["shortfall"] == 3
    # "roof restoration" keyword carries both h2_h3 (2) and paragraphs (3) targets.
    rr = next(d for d in res["keyword_detail"] if d["name"] == "roof restoration")
    kz = {z["zone"]: z for z in rr["zones"]}
    assert set(kz) == {"H2/H3", "body"}
    assert kz["H2/H3"]["recommended"] == 2 and kz["body"]["recommended"] == 3


def test_frequency_grading_folds_into_engine_score():
    serp = _serp_analysis()
    # Low: every tracked term appears about once (well under the higher targets).
    html_low = (
        "<article><h2>Roof Restoration in Melbourne</h2>"
        "<p>Colorbond and slate roofing. Tile roof. Free quote. Roof repairs.</p></article>"
    )
    low = main._compute_serp_signal_coverage(html_low, serp)
    # High: the same terms, repeated toward their recommended counts.
    html_high = (
        "<article><h2>Roof Restoration Melbourne — roof restoration roof restoration</h2>"
        "<p>Melbourne Melbourne Melbourne Melbourne. Colorbond Colorbond Colorbond. "
        "Slate slate. Tile roof tile roof. Free quote free quote. Roof repairs roof repairs.</p></article>"
    )
    high = main._compute_serp_signal_coverage(html_high, serp)
    assert low["frequency_coverage"] is not None
    assert high["frequency_coverage"] > low["frequency_coverage"]
    # Frequency is folded into the engine score, so more mentions => higher score.
    assert high["score"] > low["score"]
    # Attainment is capped at the target: over-using a term can't push it past 100.
    assert high["frequency_coverage"] <= 100.0


def test_frequency_grading_absent_preserves_presence_only_score():
    # No entities, related terms without a recommended benchmark, no bold => no
    # frequency target => frequency_coverage None and the composite is the exact
    # prior presence-only formula.
    serp = {
        "related_keywords": {"h2_h3": [{"term": "roof restoration"}], "paragraphs": []},
        "zone_targets": {"h2_h3": {"target": 1, "entity_target": 1}},
        "google_entities": [],
        "top_quadgrams": [{"phrase": "licensed roofing contractor"}],
    }
    html = "<article><h2>Roof Restoration in Melbourne</h2><p>quality roofing.</p></article>"
    res = main._compute_serp_signal_coverage(html, serp)
    assert res["frequency_coverage"] is None
    expected = round(
        res["keyword_coverage"] * 0.30 + res["entity_coverage"] * 0.50 + res["quadgram_coverage"] * 0.20, 1
    )
    assert res["score"] == expected


def test_word_boundary_counting_does_not_match_substrings():
    # "Slate" must not be counted inside "Slater"; "tile" not inside "tiles".
    html = "<article><p>Mr Slater fitted the tiles. Slate is different.</p></article>"
    serp = {
        "google_entities": [
            {"name": "Slate", "page_spread": 3, "recommended_mentions": 2},
            {"name": "tile", "page_spread": 2, "recommended_mentions": 2},
        ],
    }
    res = main._compute_serp_signal_coverage(html, serp)
    detail = {d["name"]: d for d in res["entity_detail"]}
    assert detail["Slate"]["current"] == 1   # only the standalone "Slate"
    assert detail["tile"]["current"] == 0    # "tiles" does not count
