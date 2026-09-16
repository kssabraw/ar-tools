"""Unit tests for the P0 topic-vector measure (centering / per-subtopic coverage
/ inverse gain gap).

Pure + offline: the embedding dependency is a deterministic injected fake (no
GEMINI_API_KEY, no network). The fake maps text -> a bag-of-concept vector over a
fixed vocabulary, so cosine reflects topical overlap and we can build a labeled
mini-set that mirrors the plan's §14 acceptance check.

Run with `pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import topic_vector as tv  # noqa: E402


def run(coro):
    # Own loop per call — robust to earlier suite tests having closed the default
    # event loop (Python 3.11 get_event_loop() then raises), and doesn't perturb
    # the global loop other test modules rely on.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- Deterministic fake embedder -------------------------------------------
# Each dimension is a "concept"; a text's vector counts that concept's trigger
# words. cosine then measures shared-concept overlap. Enough to order a
# vendor-trust-drift page below an on-vector PDP against a compound centroid.
_CONCEPTS = [
    ("commercial", ["buy", "price", "order", "purchase", "sizes", "stock", "shop", "shipping", "vial"]),
    ("vendor",     ["coa", "hplc", "batch", "verified", "purity", "tested", "lab", "certificate"]),
    ("receptor",   ["receptor", "agonism", "agonist", "binding"]),
    ("metabolic",  ["metabolic", "glucose", "weight", "appetite", "energy"]),
    ("triple",     ["triple", "glp", "gip", "glucagon"]),
    ("entity",     ["retatrutide", "glp-3rt", "peptide", "compound"]),
]


def _vec(text: str) -> list:
    t = (text or "").lower()
    return [float(sum(t.count(w) for w in words)) for _, words in _CONCEPTS]


async def fake_embed(texts):
    return [_vec(t) for t in texts]


async def blank_embed(texts):
    """Returns zero vectors — exercises the empty-centroid / no-signal guards."""
    return [[0.0] * len(_CONCEPTS) for _ in texts]


# --- Tiering (§3): re-partition the already-scraped set by SERP rank --------

def test_build_heading_tiers_partitions_by_rank():
    h2 = [["Receptor Agonism"], ["Metabolic Effects"], ["Storage And Handling"]]
    h3 = [[], [], []]
    # ranks: page0 -> 1 (top10), page1 -> 9 (top10), page2 -> 12 (tier2)
    tiers = tv.build_heading_tiers(h2, h3, [1, 9, 12])
    top_texts = {h["text"] for h in tiers["top10_headings"]}
    assert "Receptor Agonism" in top_texts and "Metabolic Effects" in top_texts
    assert tiers["top10_pages"] == 2
    assert tiers["tier2_pages"] == 1


def test_tier2_two_page_spread_guard():
    # One tier-2 heading appears on a single page -> dropped; one on two -> kept.
    h2 = [
        ["Shared Angle"],            # rank 11
        ["Shared Angle", "Lonely"],  # rank 12
    ]
    h3 = [[], []]
    tiers = tv.build_heading_tiers(h2, h3, [11, 12])
    kept = {h["text"]: h["page_spread"] for h in tiers["tier2_headings"]}
    assert kept.get("Shared Angle") == 2
    assert "Lonely" not in kept  # page_spread 1 < TIER2_MIN_PAGE_SPREAD


def test_tiers_drop_chrome_and_count_spread():
    h2 = [["Reviews", "Receptor Agonism"], ["Receptor Agonism"]]
    h3 = [["FAQ"], []]
    tiers = tv.build_heading_tiers(h2, h3, [1, 2])
    labels = {h["text"]: h["page_spread"] for h in tiers["top10_headings"]}
    assert "Reviews" not in labels and "FAQ" not in labels  # chrome dropped
    assert labels.get("Receptor Agonism") == 2               # per-page spread


# --- Clustering -------------------------------------------------------------

def test_cluster_merges_near_duplicates_and_promotes_specificity():
    top10 = [
        {"text": "Receptor Agonism", "page_spread": 3},
        {"text": "Retatrutide Receptor Agonism Mechanism", "page_spread": 2},
    ]
    clusters = tv.cluster_headings(top10, [])
    assert len(clusters) == 1
    # Label promoted to the most token-rich (most specific) member.
    assert clusters[0].label == "Retatrutide Receptor Agonism Mechanism"
    assert clusters[0].tier == "top10"
    assert clusters[0].page_spread == 5


def test_cluster_top10_tier_wins_over_tier2():
    top10 = [{"text": "Receptor Agonism Binding", "page_spread": 2}]
    tier2 = [{"text": "Receptor Agonism Study", "page_spread": 2}]
    clusters = tv.cluster_headings(top10, tier2)
    assert len(clusters) == 1
    assert clusters[0].tier == "top10"  # any consensus member => top10


def test_cluster_keeps_distinct_subtopics_apart():
    top10 = [
        {"text": "Receptor Agonism", "page_spread": 3},
        {"text": "Metabolic Effects", "page_spread": 2},
        {"text": "Triple Agonist Mechanism", "page_spread": 2},
    ]
    clusters = tv.cluster_headings(top10, [])
    assert len(clusters) == 3


def test_cluster_drops_chrome_headings():
    clusters = tv.cluster_headings([{"text": "Reviews"}, {"text": "FAQ"}], [])
    assert clusters == []


def test_cluster_tolerates_malformed_entries():
    # Mixed dicts / bare strings / None / dict-without-text must not raise and
    # must not produce a "None" garbage subtopic.
    top10 = [
        {"text": "Receptor Agonism", "page_spread": 3},
        "Metabolic Effects",   # bare string
        None,                  # dropped
        {"page_spread": 2},    # no text -> empty -> dropped
        {"text": "  "},        # whitespace -> dropped
    ]
    clusters = tv.cluster_headings(top10, [])
    labels = {c.label for c in clusters}
    assert "None" not in labels
    assert "Receptor Agonism" in labels
    assert "Metabolic Effects" in labels
    assert len(clusters) == 2


# --- Centroid assembly (§4) -------------------------------------------------

def test_centroid_excludes_implied_query_uses_query_aio_top10():
    comps = tv.build_centroid_component_texts(
        "buy retatrutide", "Retatrutide is a triple-agonist peptide.",
        ["Retatrutide Receptor Agonism", "Buy Retatrutide Vials"],
    )
    assert comps[0] == "buy retatrutide"                     # query present
    assert any("triple-agonist" in c for c in comps)         # AIO present
    assert any("Receptor Agonism" in c for c in comps)       # top-10 headings
    # No implied-query / JTBD text is ever injected here.
    assert len(comps) == 3


def test_centroid_falls_back_to_query_and_headings_when_no_aio():
    comps = tv.build_centroid_component_texts("buy retatrutide", "", ["Receptor Agonism"])
    assert comps == ["buy retatrutide", "Receptor Agonism"]


def test_mean_vector_normalizes_and_skips_zero():
    mv = tv.mean_vector([[3.0, 0.0], [0.0, 4.0], [0.0, 0.0]])
    # Each non-zero vector is L2-normalised to a unit basis vector, then averaged.
    assert mv == [0.5, 0.5]
    assert tv.mean_vector([]) == []
    assert tv.mean_vector([[0.0, 0.0]]) == []


def test_mean_vector_skips_mismatched_dim():
    # A vector whose length differs from the first usable one is skipped (no
    # IndexError in the final comprehension); the result keeps the first dim.
    mv = tv.mean_vector([[1.0, 0.0], [0.0, 1.0, 0.0]])
    assert mv == [1.0, 0.0]


# --- Section extraction -----------------------------------------------------

def test_extract_sections_splits_on_headings():
    html = ("<h1>Buy Retatrutide</h1><p>Lead paragraph.</p>"
            "<h2>Receptor Agonism</h2><p>Body about receptors.</p>"
            "<h2>Shipping</h2><ul><li>Fast shipping</li></ul>")
    sections = tv.extract_sections(html)
    assert len(sections) == 3
    assert sections[0].startswith("Buy Retatrutide")
    assert "receptors" in sections[1].lower()


def test_extract_sections_no_headings_fallback():
    sections = tv.extract_sections("<div><p>Just some prose with no headings.</p></div>")
    assert len(sections) == 1
    assert "prose" in sections[0].lower()


def test_extract_sections_empty():
    assert tv.extract_sections("") == []


# --- Coverage / on-vector verdicts ------------------------------------------

def test_coverage_verdicts_covered_and_on_vector():
    st = tv.Subtopic(label="Receptor Agonism", tier="top10", page_spread=3)
    centroid = _vec("retatrutide receptor agonism metabolic triple")
    label_vec = _vec("receptor agonism")
    covering_section = _vec("this section discusses receptor agonism in detail")
    off_section = _vec("shipping and returns policy")
    v = tv.coverage_verdicts([st], [label_vec], [covering_section, off_section], centroid)[0]
    assert v["covered"] is True
    assert v["on_vector"] is True

    v2 = tv.coverage_verdicts([st], [label_vec], [off_section], centroid)[0]
    assert v2["covered"] is False  # no section is near the subtopic


# --- Orchestrator degradation (never a misleading number) -------------------

def test_measure_skips_without_embedder():
    out = run(tv.measure(
        embed_fn=None, query="buy x", page_title="", page_html="<p>x</p>",
        aio_present=False, aio_text="", top10_headings=[{"text": "Receptor Agonism"}],
        tier2_headings=[],
    ))
    assert out == {"available": False, "reason": "gemini_key_absent"}


def test_measure_skips_without_headings_or_query():
    out = run(tv.measure(
        embed_fn=fake_embed, query="", page_title="", page_html="<p>x</p>",
        aio_present=False, aio_text="", top10_headings=[], tier2_headings=[],
    ))
    assert out["available"] is False
    assert out["reason"] == "no_competitor_headings"


def test_measure_reports_aio_availability_for_comparability():
    out = run(tv.measure(
        embed_fn=fake_embed, query="buy retatrutide", page_title="Buy Retatrutide",
        page_html="<h2>Receptor Agonism</h2><p>receptor agonism</p>",
        aio_present=False, aio_text="",
        top10_headings=[{"text": "Receptor Agonism", "page_spread": 3}],
        tier2_headings=[],
    ))
    assert out["available"] is True
    assert out["aio_present"] is False
    assert "aio_present=False" in out["comparability_note"]


# --- §14 acceptance mini-set (name-agnostic, offline) -----------------------

# The compound centroid: transactional query + a compound-centric AIO + a
# consensus heading set. Shared by both pages under test.
_QUERY = "buy retatrutide"
_AIO = ("Retatrutide is a triple-agonist peptide studied for metabolic and weight "
        "regulation via GLP-1, GIP and glucagon receptor agonism.")
_TOP10 = [
    {"text": "Retatrutide Receptor Agonism", "page_spread": 4},
    {"text": "Retatrutide Metabolic Effects", "page_spread": 3},
    {"text": "Triple-Agonist Mechanism", "page_spread": 3},
    {"text": "Buy Retatrutide Vials", "page_spread": 2},
]
_TIER2 = [{"text": "Retatrutide Storage And Handling", "page_spread": 2}]

# The Nova page: drifted onto the vendor-trust vector (COA / HPLC / purity /
# batch / verified) — commercial + vendor-trust, essentially no compound
# mechanism. Uses the CODED name (never "retatrutide"), so this is name-agnostic.
_NOVA_HTML = (
    "<h1>Buy GLP-3RT Research Peptide</h1>"
    "<p>GLP-3RT is a verified research peptide you can buy today.</p>"
    "<h2>Third-Party COA And HPLC Purity</h2>"
    "<p>Every batch is HPLC tested with a verified COA and lab certificate for purity.</p>"
    "<h2>Buy GLP-3RT: Price, Sizes And Shipping</h2>"
    "<p>Order GLP-3RT vials with fast shipping; price and stock shown at checkout.</p>"
)

# A strong on-vector competitor PDP for the same query: commercial + the compound
# mechanism (receptor / metabolic / triple-agonist).
_COMPETITOR_HTML = (
    "<h1>Buy Retatrutide Peptide</h1>"
    "<p>Retatrutide is a triple-agonist peptide you can buy for research.</p>"
    "<h2>Retatrutide Receptor Agonism</h2>"
    "<p>Retatrutide drives receptor agonism and binding at the target receptor.</p>"
    "<h2>Retatrutide Metabolic And Weight Effects</h2>"
    "<p>Studied for metabolic and weight and glucose and appetite regulation.</p>"
    "<h2>Triple-Agonist Mechanism: GLP, GIP, Glucagon</h2>"
    "<p>The triple agonist acts across GLP, GIP and glucagon receptors.</p>"
    "<h2>Buy Retatrutide: Price And Sizes</h2>"
    "<p>Order retatrutide vials; price and sizes and stock at checkout.</p>"
)


def _measure(page_html, page_title):
    return run(tv.measure(
        embed_fn=fake_embed, query=_QUERY, page_title=page_title, page_html=page_html,
        aio_present=True, aio_text=_AIO, top10_headings=_TOP10, tier2_headings=_TIER2,
    ))


def test_acceptance_drifted_page_centers_below_on_vector_competitor():
    nova = _measure(_NOVA_HTML, "Buy GLP-3RT Research Peptide")
    comp = _measure(_COMPETITOR_HTML, "Buy Retatrutide Peptide")
    assert nova["available"] and comp["available"]
    # The vendor-trust-drift page must score BELOW the on-vector PDP (§14).
    assert comp["centering"]["cosine"] > nova["centering"]["cosine"]


def test_acceptance_inverse_gap_surfaces_mechanism_cluster():
    nova = _measure(_NOVA_HTML, "Buy GLP-3RT Research Peptide")
    gap_labels = " ".join(g["label"].lower() for g in nova["inverse_gain_gap"])
    # The mechanism the page under-covers must surface (receptor / metabolic /
    # triple-agonist) — every gap item is on-vector and competitor-grounded.
    assert any(k in gap_labels for k in ("receptor", "metabolic", "triple"))
    assert all(g["on_vector"] for g in nova["inverse_gain_gap"])
    # The strong competitor covers those same subtopics, so its gap is smaller.
    comp = _measure(_COMPETITOR_HTML, "Buy Retatrutide Peptide")
    assert len(comp["inverse_gain_gap"]) < len(nova["inverse_gain_gap"])


def test_acceptance_coverage_names_covered_and_missing():
    nova = _measure(_NOVA_HTML, "Buy GLP-3RT Research Peptide")
    cov = nova["coverage"]
    assert cov["total"] >= 3
    # Nova covers the commercial "buy" subtopic but misses the mechanism ones.
    covered = {s["label"].lower() for s in cov["subtopics"] if s["covered"]}
    missing = {s["label"].lower() for s in cov["subtopics"] if not s["covered"]}
    assert any("buy" in c for c in covered)
    assert any(("receptor" in m or "metabolic" in m or "triple" in m) for m in missing)


# --- P1: Information Gain (scored) ------------------------------------------

def test_extract_page_claims_keeps_fact_bearing_only():
    secs = [
        "GLP-3RT ships in 10mg vials at $90. We care deeply about quality and service here.",
        "The compound has 99% purity confirmed by HPLC on every batch.",
    ]
    claims = tv.extract_page_claims(secs)
    assert any("10mg" in c or "$90" in c for c in claims)
    assert any("99%" in c for c in claims)
    # A sentence with no number / % / ° / $ is not a claim.
    assert not any("care deeply" in c for c in claims)


def test_site_fact_values_and_value_grounding():
    idx = {"facts": [
        {"type": "cas", "value": "2381089-83-2", "unit": ""},
        {"type": "purity", "value": "98.5", "unit": "%"},
    ]}
    vals = tv._site_fact_values(idx)
    assert tv._claim_value_grounded("Its CAS number 2381089-83-2 is documented", vals)
    assert tv._claim_value_grounded("Purity is 98.5% by HPLC", vals)
    # Bare small integers (a pack size) are too common to ground.
    assert not tv._claim_value_grounded("Available in 10 mg vials", vals)


def test_information_gain_verdicts_classifies_realized_rare_grounded():
    # Explicit orthonormal-ish vectors so on-vector / rare / grounded are
    # controlled independently of any embedder.
    centroid = [1, 0, 0, 0]
    subtopic_vecs = [[1, 1, 0, 0]]           # a consensus subtopic (on-vector)
    claims = ["realized fact 5mg", "consensus claim 3x", "novel claim 9x"]
    page_vecs = [[1, 0, 0, 1], [1, 1, 0, 0], [1, 0, 1, 0]]
    site_vecs = [[1, 0, 0, 1]]               # grounds only the realized claim
    v = tv.information_gain_verdicts(
        claims, page_vecs, subtopic_vecs, centroid, site_vecs, set(),
        centering_floor=0.6, rarity_ceiling=0.72, grounding_floor=0.78,
    )
    # realized: on-vector + rare + grounded
    assert v[0]["realized_gain"] and not v[0]["ungrounded_novelty"]
    # consensus: on-vector but NOT rare (== a competitor subtopic) → not gain
    assert not v[1]["rare"] and not v[1]["realized_gain"]
    # ungrounded novelty (fabrication): on-vector + rare but NOT site-grounded
    assert v[2]["ungrounded_novelty"] and not v[2]["realized_gain"]


def test_score_information_gain_normalizes_and_flags():
    claim_verdicts = [
        {"realized_gain": True, "ungrounded_novelty": False, "claim": "real"},
        {"realized_gain": False, "ungrounded_novelty": True, "claim": "made-up"},
    ]
    cov = [
        {"tier": "tier2", "covered": True},
        {"tier": "tier2", "covered": False},
        {"tier": "top10", "covered": True},
    ]
    g = tv.score_information_gain(claim_verdicts, cov, target=3)
    assert g["realized_gain_count"] == 1
    assert g["ungrounded_novelty_count"] == 1 and "made-up" in g["ungrounded_claims"]
    assert g["differentiation_available"] == 2 and g["captured_differentiation"] == 1
    assert g["composite_weight"] == 0.0            # never enters the composite
    # 0.60 * (1/3) + 0.40 * (1/2) = 0.4 → 40.0
    assert g["score"] == 40.0


def _measure_gain(page_html, title, site_index):
    return run(tv.measure(
        embed_fn=fake_embed, query=_QUERY, page_title=title, page_html=page_html,
        aio_present=True, aio_text=_AIO, top10_headings=_TOP10, tier2_headings=_TIER2,
        site_claim_index=site_index,
    ))


def test_gain_suppressed_without_site_index():
    r = _measure_gain(_NOVA_HTML, "Buy GLP-3RT", None)
    assert r["information_gain"]["available"] is False
    assert r["information_gain"]["reason"] == "no_site_index"


def test_gain_suppressed_when_index_thin():
    # Fewer than GAIN_MIN_SITE_CLAIMS claim phrases AND no typed facts → suppress,
    # never a misleading 0 (§6).
    r = _measure_gain(_NOVA_HTML, "Buy GLP-3RT", {"claims": ["only one 5mg claim here"], "facts": []})
    assert r["information_gain"]["available"] is False
    assert r["information_gain"]["reason"] == "site_index_thin"


def test_gain_available_with_site_index():
    html = ("<h1>Buy GLP-3RT</h1>"
            "<p>GLP-3RT ships in 10mg vials at $90 with a verified COA per batch.</p>"
            "<h2>Purity</h2><p>GLP-3RT has 99% HPLC purity confirmed on every batch.</p>")
    idx = {
        "claims": [
            "GLP-3RT ships in 10mg vials at $90 with a verified COA",
            "GLP-3RT has 99% HPLC purity per batch documentation",
            "Every batch includes a verified certificate of analysis",
        ],
        "facts": [{"type": "price", "value": "90", "unit": "USD"},
                  {"type": "size", "value": "10", "unit": "mg"}],
    }
    r = _measure_gain(html, "Buy GLP-3RT", idx)
    assert r["information_gain"]["available"] is True
    assert "score" in r["information_gain"]
    assert r["information_gain"]["composite_weight"] == 0.0


def test_render_gain_guidance_empty_when_unavailable():
    assert tv.render_gain_guidance({"available": False}) == ""
    assert tv.render_gain_guidance(None) == ""


def test_render_gain_guidance_lists_gaps_and_missing_site_facts():
    measure_result = {"available": True,
                      "inverse_gain_gap": [{"label": "Receptor Agonism"}]}
    idx = {"facts": [
        {"type": "cas", "value": "2381089-83-2", "unit": ""},
        {"type": "price", "value": "90", "unit": "USD"},
    ]}
    page_text = "this page already mentions the $90 price but not the cas number"
    block = tv.render_gain_guidance(measure_result, idx, page_text)
    assert "Receptor Agonism" in block            # under-served subtopic coached
    assert "2381089-83-2" in block                # missing site fact coached
    # A fact already on the page is NOT re-coached (anti-noise; value "90" present).
    assert "cas: 2381089-83-2" in block.lower()


def test_measure_does_not_add_gain_to_composite_inputs():
    # information_gain is a SEPARATE key — it never appears in the coverage/
    # centering blocks that a composite could read.
    r = _measure_gain(_NOVA_HTML, "Buy GLP-3RT", None)
    assert "information_gain" in r
    assert "information_gain" not in r["coverage"]
    assert "information_gain" not in r["centering"]
