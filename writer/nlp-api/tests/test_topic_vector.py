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


def test_extract_page_claims_drops_site_chrome():
    # Chrome/boilerplate sentences carry a stray number (age-gate, cart, discount
    # popup, "N min read" blog-index blurb) so they pass the fact-signal gate, but
    # they are NOT product claims — left in, they self-ground and corrupt gain
    # (a live Nova run credited the age-gate as a realized gain). They must drop.
    secs = [
        "I acknowledge that I am age 21 or older.",
        "Want 25% Off Your First Order? Fill out the form below and we'll send your discount code.",
        "Your Cart Is Empty. Cart Total: Total $ 0.00.",
        "FEATURED Uncategorized 17 min read GLP-2TZ Reviews and Side Effects in 2026.",
        "Added to cart. Check out our shop to see what's available.",
        # A real product claim in the same batch survives.
        "GLP-3RT is verified to 99% purity with a COA on every 10mg batch.",
    ]
    claims = tv.extract_page_claims(secs)
    low = " || ".join(c.lower() for c in claims)
    assert "age 21" not in low
    assert "25% off" not in low and "discount code" not in low
    assert "cart is empty" not in low and "cart total" not in low
    assert "min read" not in low and "uncategorized" not in low
    assert "added to cart" not in low
    # The genuine claim is kept.
    assert any("99% purity" in c.lower() for c in claims)


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
        {"type": "storage_temp", "value": "-20", "unit": "°C"},
        {"type": "purity", "value": "99", "unit": "%"},
    ]}
    page_text = "this page already mentions 99% purity but not the storage temperature"
    block = tv.render_gain_guidance(measure_result, idx, page_text)
    assert "Receptor Agonism" in block            # under-served subtopic coached
    assert "-20" in block                         # missing site-invariant fact coached
    assert "storage_temp: -20 °c" in block.lower()
    # A fact already on the page is NOT re-coached (anti-noise; value "99" present).
    assert "purity" not in block.lower()


def test_render_gain_guidance_excludes_per_product_and_transactional_facts():
    """Coaching PUSHES a fact onto ONE page; the site-claim index is client-level
    (whole site). Per-product (size), per-compound (cas / molecular_weight) and
    transactional (price — incl. the $0.00 empty-cart artifact) facts belong to
    some OTHER page and must never be coached onto a specific product page
    (a live Nova reoptimize surfaced 'price: 0.00 USD' + five cross-product
    semaglutide sizes onto a retatrutide PDP)."""
    measure_result = {"available": True, "inverse_gain_gap": []}
    idx = {"facts": [
        {"type": "price", "value": "0.00", "unit": "USD"},   # empty-cart garbage
        {"type": "size", "value": "75", "unit": "mg"},        # cross-product size
        {"type": "cas", "value": "2381089-83-2", "unit": ""}, # per-compound identity
        {"type": "molecular_weight", "value": "4731", "unit": "da"},
        {"type": "coa", "value": "present", "unit": ""},      # site-invariant → kept
        {"type": "storage_temp", "value": "-80", "unit": "°C"},  # site-invariant → kept
    ]}
    block = tv.render_gain_guidance(measure_result, idx, page_text="a page with none of these values")
    low = block.lower()
    assert "0.00" not in block
    assert "75" not in block
    assert "2381089-83-2" not in block
    assert "4731" not in block
    assert "coa: present" in low
    assert "storage_temp: -80 °c" in low


def _attach_score_time_guidance(report, site_index, page_text):
    """Mirror exactly what /score-blog-page does: attach the rendered coaching
    string onto the report-only topic_vector field so a blog reopt (which rewrites
    in pipeline-api, unable to call this nlp renderer) can reuse the SCORE's
    already-computed measure with no second nlp call. Report-only — a string key,
    never in `scores`."""
    if isinstance(report, dict):
        report["gain_guidance"] = tv.render_gain_guidance(report, site_index, page_text)
    return report


def test_blog_score_attaches_nonempty_gain_guidance_when_actionable():
    # An actionable measure (an on-vector gap + a missing site-invariant fact) →
    # /score-blog-page emits topic_vector.gain_guidance as a NON-EMPTY string that
    # a blog reopt threads into the writer as advisory notes.
    report = {"available": True, "inverse_gain_gap": [{"label": "Receptor Agonism"}]}
    idx = {"facts": [{"type": "storage_temp", "value": "-20", "unit": "°C"}]}
    out = _attach_score_time_guidance(report, idx, "a page without that temp")
    assert isinstance(out["gain_guidance"], str)
    assert out["gain_guidance"]  # non-empty
    assert "Receptor Agonism" in out["gain_guidance"]
    # Report-only: the string is a key on topic_vector, never in a scored block.
    assert "gain_guidance" not in out.get("coverage", {})


def test_blog_score_attaches_empty_gain_guidance_when_nothing_actionable():
    # Nothing to coach → "" so the reopt prompt is byte-identical to a run with no
    # measure (never a misleading number, never a fabricated addition).
    report = {"available": True, "inverse_gain_gap": [], "coverage": {}}
    assert _attach_score_time_guidance(report, {"facts": []}, "page")["gain_guidance"] == ""
    # An unavailable measure (no GEMINI key / thin index) → "" too.
    unavailable = {"available": False, "reason": "gemini_key_absent"}
    assert _attach_score_time_guidance(unavailable, None, "page")["gain_guidance"] == ""


def test_measure_does_not_add_gain_to_composite_inputs():
    # information_gain is a SEPARATE key — it never appears in the coverage/
    # centering blocks that a composite could read.
    r = _measure_gain(_NOVA_HTML, "Buy GLP-3RT", None)
    assert "information_gain" in r
    assert "information_gain" not in r["coverage"]
    assert "information_gain" not in r["centering"]


def test_include_gain_false_skips_scored_gain_but_keeps_coverage():
    # The reopt coaching pass opts out of the scored gain (and its extra
    # embeddings) — the measure still runs centering + coverage + inverse gap,
    # but Information Gain is 'not_requested', NOT scored, even with a rich index.
    idx = {
        "claims": ["GLP-3RT ships in 10mg vials at $90 with a verified COA",
                   "GLP-3RT has 99% HPLC purity per batch",
                   "Every batch includes a certificate of analysis"],
        "facts": [{"type": "price", "value": "90", "unit": "USD"}],
    }
    r = run(tv.measure(
        embed_fn=fake_embed, query=_QUERY, page_title="Buy GLP-3RT",
        page_html=_NOVA_HTML, aio_present=True, aio_text=_AIO,
        top10_headings=_TOP10, tier2_headings=_TIER2, site_claim_index=idx,
        include_gain=False,
    ))
    assert r["available"] is True                        # P0 still runs
    assert "centering" in r and "coverage" in r and "inverse_gain_gap" in r
    assert r["information_gain"]["available"] is False
    assert r["information_gain"]["reason"] == "not_requested"


def test_absent_index_skips_gain_claim_embeddings():
    # Every /score-page / /score-blog-page consumer that passes NO site index
    # (content-gap, the strategist audit_page, a raw score) still runs the P0
    # measure — but must NOT embed the page's claim sentences for a gain score
    # that will only be suppressed. Assert the batch is the P0 size (no extra
    # page-claim / site-claim vectors) and gain suppresses with the right reason.
    batches = []

    async def counting_embed(texts):
        batches.append(list(texts))
        return [_vec(t) for t in texts]

    def _n(idx):
        batches.clear()
        run(tv.measure(
            embed_fn=counting_embed, query=_QUERY, page_title="Buy GLP-3RT",
            page_html=_NOVA_HTML, aio_present=True, aio_text=_AIO,
            top10_headings=_TOP10, tier2_headings=_TIER2, site_claim_index=idx,
            include_gain=True,
        ))
        return len(batches[0])

    n_absent = _n(None)
    rich = {
        "claims": ["GLP-3RT ships in 10mg vials at $90 with a verified COA",
                   "GLP-3RT has 99% HPLC purity per batch",
                   "Every batch includes a certificate of analysis"],
        "facts": [{"type": "price", "value": "90", "unit": "USD"}],
    }
    batches.clear()
    r_rich = run(tv.measure(
        embed_fn=counting_embed, query=_QUERY, page_title="Buy GLP-3RT",
        page_html=_NOVA_HTML, aio_present=True, aio_text=_AIO,
        top10_headings=_TOP10, tier2_headings=_TIER2, site_claim_index=rich,
        include_gain=True,
    ))
    n_rich = len(batches[0])
    # A usable index embeds MORE (the page-claim + site-claim vectors); an absent
    # one embeds only the P0 vectors.
    assert n_rich > n_absent
    # Absent index → gain suppressed (not scored 0), P0 still available.
    r_absent = run(tv.measure(
        embed_fn=counting_embed, query=_QUERY, page_title="Buy GLP-3RT",
        page_html=_NOVA_HTML, aio_present=True, aio_text=_AIO,
        top10_headings=_TOP10, tier2_headings=_TIER2, site_claim_index=None,
        include_gain=True,
    ))
    assert r_absent["available"] is True
    assert r_absent["information_gain"]["available"] is False
    assert r_absent["information_gain"]["reason"] == "no_site_index"
    assert r_rich["information_gain"]["available"] is True


# --- P2 — emotional-arc rubric (§10a). Pure logic; the LLM call lives in main.py
# and is not exercised here (offline). ----------------------------------------

_ARC_CARD = {
    "audience_label": "Melbourne homeowner with a 20+ year old tile roof",
    "audience_pain_points": ["worried the roof will leak in winter storms",
                             "afraid of being upsold a full replacement"],
    "audience_objections": ["not sure repair is enough", "concerned about cost"],
    "audience_triggers": ["saw a water stain on the ceiling"],
    "audience_motivations": ["a roof they can stop worrying about",
                             "an honest assessment"],
}


def test_build_arc_states_assembles_before_after_from_audience_fields():
    st = tv.build_arc_states(_ARC_CARD)
    # before = pains + objections + triggers; after = motivations (§10a).
    assert st["pains"] == _ARC_CARD["audience_pain_points"]
    assert st["objections"] == _ARC_CARD["audience_objections"]
    assert st["triggers"] == _ARC_CARD["audience_triggers"]
    assert st["motivations"] == _ARC_CARD["audience_motivations"]
    assert st["audience_label"].startswith("Melbourne homeowner")


def test_has_arc_inputs_true_for_card_with_audience():
    assert tv.has_arc_inputs(_ARC_CARD) is True


def test_no_audience_fields_suppressed_not_zero():
    # A card with a brand voice but NO audience signals → the arc is suppressed
    # ("not measured"), never a 0 score (§10a subordinate-tail: no input, no verdict).
    voice_only = {"brand_name": "Acme", "tone_adjectives": ["warm"], "person": "first"}
    assert tv.has_arc_inputs(voice_only) is False
    assert tv.has_arc_inputs(None) is False
    assert tv.has_arc_inputs({}) is False
    supp = tv.suppressed_arc("no_audience_fields")
    assert supp["available"] is False
    assert supp["reason"] == "no_audience_fields"
    assert supp["composite_weight"] == 0.0
    assert "score" not in supp  # suppressed ≠ scored 0


def test_build_arc_prompt_carries_audience_signals_and_page_text():
    st = tv.build_arc_states(_ARC_CARD)
    prompt = tv.build_arc_prompt(st, "Our honest assessment tells you when a repair is enough.")
    assert "afraid of being upsold a full replacement" in prompt
    assert "an honest assessment" in prompt   # a motivation
    assert "saw a water stain on the ceiling" in prompt  # a trigger
    assert "honest assessment tells you when a repair is enough" in prompt  # the page text


def test_sanitize_arc_drops_unevidenced_verdicts():
    # A fabricated positive verdict with no page quote is NOT credited (mirrors
    # the vibe_read sanitize; the §14 "gain never rewards fabrication" analog).
    st = tv.build_arc_states(_ARC_CARD)
    raw = {
        "arc_present": True,
        "before_acknowledged": True,
        "before_evidence": "",  # claims yes but no quote → dropped
        "after_resolved": True,
        "after_evidence": "We give you a roof you can stop worrying about.",
        "transitions": [
            {"concern": "afraid of being upsold", "addressed": True,
             "evidence": "We tell you honestly when a repair is all you need."},
            {"concern": "concerned about cost", "addressed": True,
             "evidence": ""},  # unevidenced → flipped to not-addressed
        ],
        "score": 88,
    }
    arc = tv.sanitize_arc(raw, st)
    assert arc["available"] is True
    assert arc["composite_weight"] == 0.0
    assert arc["before_acknowledged"] is False        # unevidenced → dropped
    assert arc["before_evidence"] == ""
    assert arc["after_resolved"] is True              # had a quote → kept
    # Only the evidenced transition counts as resolved.
    assert arc["transition_count"] == 2
    assert arc["resolved_count"] == 1
    addressed = {t["concern"]: t["addressed"] for t in arc["transitions"]}
    assert addressed["afraid of being upsold"] is True
    assert addressed["concerned about cost"] is False
    assert arc["grounded"] is True                    # at least one survived


def test_sanitize_arc_clamps_score_and_survives_garbage():
    st = tv.build_arc_states(_ARC_CARD)
    assert tv.sanitize_arc({"score": 999}, st)["score"] == 100.0
    assert tv.sanitize_arc({"score": -5}, st)["score"] == 0.0
    assert tv.sanitize_arc({"score": "not a number"}, st)["score"] == 0.0
    # Malformed / non-dict input never raises; degrades to safe defaults.
    junk = tv.sanitize_arc(None, st)
    assert junk["available"] is True
    assert junk["score"] == 0.0
    assert junk["transitions"] == []
    assert junk["grounded"] is False


def test_sanitize_arc_never_surfaces_a_forbidden_term():
    # Non-negotiable (§10b): a never_use term must never appear in ANY arc string
    # (verdict evidence, rationale, or a transition concern).
    st = tv.build_arc_states(_ARC_CARD)
    raw = {
        "arc_present": True,
        "before_acknowledged": True,
        "before_evidence": "The retatrutide peptide worries them.",  # forbidden word
        "after_resolved": True,
        "after_evidence": "We deliver a roof you can stop worrying about.",
        "transitions": [
            {"concern": "unsure about retatrutide dosing", "addressed": True,
             "evidence": "Our page explains it."},  # forbidden word in concern
            {"concern": "concerned about cost", "addressed": True,
             "evidence": "Buy retatrutide today at a fair price."},  # forbidden in evidence
        ],
        "rationale": "The page mentions retatrutide throughout.",  # forbidden word
    }
    arc = tv.sanitize_arc(raw, st, never_use_terms=["retatrutide"])

    def _all_strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from _all_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _all_strings(v)

    assert not any("retatrutide" in s.lower() for s in _all_strings(arc))
    # The transition whose CONCERN carried the forbidden word is dropped entirely;
    # the one with the forbidden word only in evidence keeps the concern but the
    # evidence is blanked → its verdict is un-evidenced → not addressed.
    concerns = [t["concern"] for t in arc["transitions"]]
    assert "unsure about retatrutide dosing" not in " ".join(concerns).lower() and \
        all("retatrutide" not in c.lower() for c in concerns)
    cost = next((t for t in arc["transitions"] if t["concern"] == "concerned about cost"), None)
    assert cost is not None
    assert cost["addressed"] is False and cost["evidence"] == ""
    # before_evidence carried the forbidden word → blanked → verdict dropped.
    assert arc["before_acknowledged"] is False
    assert arc["rationale"] == ""


def test_arc_clean_str_scrubs_before_capping():
    # A forbidden term straddling the cap boundary must not leave a surviving
    # fragment — the scrub scans the FULL string, then truncates.
    rx = tv._forbidden_regex(["retatrutide"])
    straddle = "x" * 295 + " retatrutide tail"  # "retatrutide" spans the 300 cap
    assert tv._arc_clean_str(straddle, rx, cap=300) == ""  # whole string dropped
    # A clean over-length string is CAPPED, not blanked.
    assert tv._arc_clean_str("y" * 500, rx, cap=300) == "y" * 300
    # No forbidden terms configured → nothing is scrubbed (rx is None).
    assert tv._arc_clean_str("buy retatrutide now", None, cap=300) == "buy retatrutide now"


def test_arc_list_ignores_non_list_field():
    # A hand-crafted card whose audience field is a bare string must yield [] —
    # never char-iterate into single-character "items".
    st = tv.build_arc_states({"audience_pain_points": "a leaky roof"})
    assert st["pains"] == []
    assert tv.has_arc_inputs({"audience_pain_points": "a leaky roof"}) is False
