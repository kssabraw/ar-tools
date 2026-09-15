"""Unit tests for PAA → SEO Neo v1 pure helpers (services/paa_seo.py).

All pure (no I/O): the geo-modified query, candidate assembly + slug dedup, the
three-rule writer_notes composition, and the two deterministic writer-constraint
checks (exact-match + service-page link) + the cannibalization gate. The I/O layer
(services/paa_sets_service.py) is exercised in test_paa_sets_service.py with mocks.
"""

from services import paa_seo as p


# ── geo_query (geo_mode) ──────────────────────────────────────────────────────
def test_geo_query_geo_appends_city():
    assert p.geo_query("metal roof repair", "Denver, CO", "geo") == "metal roof repair Denver"


def test_geo_query_naked_is_bare():
    assert p.geo_query("metal roof repair", "Denver, CO", "naked") == "metal roof repair"


def test_geo_query_geo_skips_city_already_in_keyword():
    # Mirrors local_seo_precheck._ranking_queries: don't double the city.
    assert p.geo_query("metal roof repair denver", "Denver", "geo") == "metal roof repair denver"


def test_geo_query_geo_no_city_falls_back_to_bare():
    assert p.geo_query("metal roof repair", "", "geo") == "metal roof repair"
    assert p.geo_query("metal roof repair", None, "geo") == "metal roof repair"


def test_geo_query_unknown_mode_defaults_geo():
    assert p.geo_query("roof repair", "Denver", "weird") == "roof repair Denver"


def test_geo_query_blank_keyword():
    assert p.geo_query("", "Denver", "geo") == ""


# ── build_paa_candidates (dedupe + slug + market merge) ───────────────────────
def test_build_paa_candidates_dedupes_case_insensitively_and_slugs():
    market = {"how much does metal roof repair cost?": {"search_volume": 320, "cpc": 6.1, "competition": "LOW"}}
    out = p.build_paa_candidates(
        [
            "How much does metal roof repair cost?",
            "how much does METAL roof repair cost?",  # dupe (case)
            "   ",  # blank
            "Is metal roof repair worth it?",
        ],
        market,
    )
    assert [c["question"] for c in out] == [
        "How much does metal roof repair cost?",
        "Is metal roof repair worth it?",
    ]
    first = out[0]
    assert first["slug"] == "how-much-does-metal-roof-repair-cost"
    assert first["volume"] == 320 and first["cpc_usd"] == 6.1 and first["competition"] == "LOW"
    # No market row for the second → None enrichment, still a candidate.
    assert out[1]["volume"] is None


def test_build_paa_candidates_drops_unsluggable():
    # A question of all-generic words slugifies to something; but empty/whitespace
    # is dropped. Use a purely punctuation question to force an empty slug.
    out = p.build_paa_candidates(["?!.", "Real question here"], {})
    assert [c["question"] for c in out] == ["Real question here"]


def test_build_paa_candidates_preserves_first_seen_order():
    out = p.build_paa_candidates(["B question", "A question", "B question"], {})
    assert [c["question"] for c in out] == ["B question", "A question"]


# ── compose_writer_notes (the three rules) ────────────────────────────────────
def test_compose_writer_notes_carries_all_three_rules_with_service_page():
    notes = p.compose_writer_notes(
        "How much does metal roof repair cost?",
        "https://c.com/metal-roof-repair/",
        service_keyword="metal roof repair",
        location="Denver",
    )
    # Rule 1 (one question), rule 2 (exact title + H2), rule 3 (link high to the URL).
    assert "one question, one post" in notes.lower()
    assert "How much does metal roof repair cost?" in notes
    assert "title" in notes.lower() and "h2" in notes.lower()
    assert "https://c.com/metal-roof-repair/" in notes
    assert "money page" in notes.lower()


def test_compose_writer_notes_without_service_page_still_says_link_high():
    notes = p.compose_writer_notes("Do I need a permit?", None)
    assert "link high" in notes.lower()
    assert "homepage" in notes.lower()


# ── check_exact_match ─────────────────────────────────────────────────────────
def test_check_exact_match_exact_title_ignores_trailing_punct_and_case():
    r = p.check_exact_match(
        "How much does metal roof repair cost?",
        title="how much does metal roof repair cost",  # no ?, different case
        headings=["Overview", "Cost factors"],
    )
    assert r["ok"] is True and r["match"] == "exact" and r["found_in"] == "title"


def test_check_exact_match_in_h2():
    r = p.check_exact_match(
        "Is metal roof repair worth it?",
        title="A guide to metal roofs",
        headings=["Is metal roof repair worth it?"],
    )
    assert r["ok"] is True and r["match"] == "exact" and r["found_in"] == "h2"


def test_check_exact_match_contains_when_embedded_in_heading():
    r = p.check_exact_match(
        "How much does metal roof repair cost?",
        headings=["How much does metal roof repair cost? A 2026 breakdown"],
    )
    assert r["ok"] is True and r["match"] == "contains" and r["found_in"] == "h2"


def test_check_exact_match_none_when_absent():
    r = p.check_exact_match("Do I need a permit?", title="Metal roofs 101", headings=["Costs"])
    assert r["ok"] is False and r["match"] == "none" and r["found_in"] is None


def test_check_exact_match_exact_wins_over_contains():
    # A heading contains it, but the title equals it → exact/title, not contains.
    r = p.check_exact_match(
        "Why choose metal?",
        title="Why choose metal?",
        headings=["Why choose metal? Five reasons"],
    )
    assert r["match"] == "exact" and r["found_in"] == "title"


# ── service_link_verdict (reuses local_seo_matrix.check_internal_links) ───────
def test_service_link_verdict_present():
    html = '<article>See our <a href="https://c.com/metal-roof-repair/">service page</a>.</article>'
    r = p.service_link_verdict(html, "https://c.com/metal-roof-repair")
    assert r["ok"] is True and r["expected"] == 1 and r["present"]


def test_service_link_verdict_missing():
    html = "<article>No links here.</article>"
    r = p.service_link_verdict(html, "https://c.com/metal-roof-repair")
    assert r["ok"] is False


def test_service_link_verdict_not_applicable_without_target():
    r = p.service_link_verdict("<article>x</article>", None)
    assert r["ok"] is None and r["service_page_url"] is None


# ── verify_item_checks (bundle) ───────────────────────────────────────────────
def test_verify_item_checks_bundles_both():
    html = '<h1>How much does metal roof repair cost?</h1><a href="https://c.com/s/">svc</a>'
    r = p.verify_item_checks(
        "How much does metal roof repair cost?",
        html,
        "https://c.com/s",
        title="How much does metal roof repair cost?",
        h1="How much does metal roof repair cost?",
        headings=[],
    )
    assert r["exact_match"]["ok"] is True
    assert r["service_link"]["ok"] is True


# ── resolve_service_page_url (PRD §8.3) ───────────────────────────────────────
def test_resolve_service_page_url_explicit_wins():
    r = p.resolve_service_page_url("https://c.com/explicit/", "https://c.com/auto/")
    assert r == {"url": "https://c.com/explicit/", "source": "explicit", "needs_prompt": False}


def test_resolve_service_page_url_auto_fallback():
    r = p.resolve_service_page_url("", "https://c.com/auto/")
    assert r == {"url": "https://c.com/auto/", "source": "auto", "needs_prompt": False}


def test_resolve_service_page_url_none_needs_prompt():
    r = p.resolve_service_page_url(None, None)
    assert r == {"url": None, "source": "none", "needs_prompt": True}


# ── find_slug_collisions (cannibalization, cross-set) ─────────────────────────
def test_find_slug_collisions_flags_reused_slug():
    existing = [
        {"slug": "how-much-does-roof-repair-cost", "question": "...", "set_id": "other"},
        {"slug": "is-it-worth-it"},
    ]
    out = p.find_slug_collisions(
        ["how-much-does-roof-repair-cost", "brand-new-slug"], existing
    )
    assert len(out) == 1 and out[0]["slug"] == "how-much-does-roof-repair-cost"
    assert out[0]["existing"]


def test_find_slug_collisions_none_when_all_new():
    assert p.find_slug_collisions(["a", "b"], [{"slug": "c"}]) == []


def test_find_slug_collisions_dedupes_candidate_slugs():
    out = p.find_slug_collisions(["dup", "dup"], [{"slug": "dup"}])
    assert len(out) == 1


# ── cannibalization_gates (reuses local_seo_matrix.scale_gates) ───────────────
def test_cannibalization_gates_clean_run_no_issues():
    assert p.cannibalization_gates(create_count=4, total_client_paa_pages=4) == []


def test_cannibalization_gates_slug_collision_is_acknowledgeable():
    gates = p.cannibalization_gates(
        create_count=4,
        total_client_paa_pages=8,
        slug_collisions=[{"slug": "x", "existing": [{}]}],
    )
    kinds = {g["kind"]: g for g in gates}
    assert "paa_slug_collision" in kinds
    assert kinds["paa_slug_collision"]["blocking"] is True
    assert kinds["paa_slug_collision"]["acknowledgeable"] is True


def test_cannibalization_gates_existing_page_is_acknowledgeable():
    gates = p.cannibalization_gates(
        create_count=2,
        total_client_paa_pages=2,
        existing_site_matches=[{"question": "q", "url": "https://c.com/p/"}],
    )
    assert any(g["kind"] == "paa_existing_page" and g["acknowledgeable"] for g in gates)


def test_cannibalization_gates_acknowledge_clears_acknowledgeable_issues():
    gates = p.cannibalization_gates(
        create_count=2,
        total_client_paa_pages=2,
        slug_collisions=[{"slug": "x", "existing": [{}]}],
        existing_site_matches=[{"question": "q", "url": "u"}],
        signoff_acknowledged=True,
    )
    assert gates == []


def test_cannibalization_gates_cell_limit_not_acknowledgeable():
    gates = p.cannibalization_gates(
        create_count=p.PAA_MAX_PER_RUN + 5,
        total_client_paa_pages=10,
        signoff_acknowledged=True,  # ack does NOT clear the hard per-run cap
    )
    assert any(g["kind"] == "matrix_cell_limit" for g in gates)


def test_cannibalization_gates_scale_signoff_over_threshold():
    gates = p.cannibalization_gates(
        create_count=4,
        total_client_paa_pages=p.MATRIX_SIGNOFF_THRESHOLD + 1,
    )
    assert any(g["kind"] == "matrix_signoff_required" for g in gates)
