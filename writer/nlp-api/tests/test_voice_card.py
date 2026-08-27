"""Unit tests for the Brand Voice & Audience Card.

Pure + offline — no network, no Anthropic. Covers card parsing (including the
never-use safety net), the ICP directive resolution that replaces the keyword
heuristic, the prompt block, and the deterministic compliance checks that make
"we verified the voice" a fact rather than a claim.
Run with `pytest writer/nlp-api/tests/`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_card as vc  # noqa: E402


def _card(**overrides):
    card = vc.empty_card()
    card.update(overrides)
    return card


# --- parse_voice_card ------------------------------------------------------

def test_parse_full_card_round_trips():
    card = vc.parse_voice_card({
        "brand_name": "First Class Roofing",
        "tone_adjectives": ["straight-talking", "reassuring"],
        "person": "first",
        "voice_directives": ["Lead with the outcome, not the process"],
        "sentence_rhythm": "Short sentences. Vary length.",
        "must_use_terms": ["roof restoration"],
        "never_use_terms": ["cheap", "world-class"],
        "discouraged_terms": ["leverage"],
        "cta_language": ["Book a free roof inspection"],
        "audience_label": "Melbourne homeowner, 20+ year old tile roof",
        "audience_pain_points": ["worried the roof will leak before summer"],
        "audience_triggers": ["a storm just went through"],
        "audience_motivations": ["protect the house without a full replacement"],
        "audience_objections": ["worried it's a upsell to replacement"],
    })
    assert card["brand_name"] == "First Class Roofing"
    assert card["person"] == "first"
    assert card["never_use_terms"] == ["cheap", "world-class"]
    assert card["cta_language"] == ["Book a free roof inspection"]
    assert card["audience_triggers"] == ["a storm just went through"]


def test_parse_distinctiveness_fields_round_trip_and_cap():
    card = vc.parse_voice_card({
        "differentiators": ["50-year workmanship warranty", "only Malarkey-certified crew"]
        + [f"extra{i}" for i in range(10)],
        "signature_phrases": ["Roofs done right, rain or shine"]
        + [f"phrase{i}" for i in range(20)],
    })
    assert card["differentiators"][0] == "50-year workmanship warranty"
    assert len(card["differentiators"]) == 6   # capped
    assert card["signature_phrases"][0] == "Roofs done right, rain or shine"
    assert len(card["signature_phrases"]) == 8  # capped


def test_parse_missing_distinctiveness_fields_default_empty():
    """A legacy card (or a distillation that stated nothing distinctive) yields
    empty lists, never a KeyError downstream."""
    card = vc.parse_voice_card({"brand_name": "X"})
    assert card["differentiators"] == []
    assert card["signature_phrases"] == []


def test_parse_never_raises_on_garbage():
    for raw in [None, "not a dict", 42, [], {"person": {"nested": True}}]:
        card = vc.parse_voice_card(raw)
        assert card["brand_name"] == ""
        assert card["never_use_terms"] == []


def test_parse_rejects_invalid_person():
    assert vc.parse_voice_card({"person": "plural"})["person"] == ""
    assert vc.parse_voice_card({"person": "FIRST"})["person"] == "first"


def test_parse_applies_caps():
    card = vc.parse_voice_card({
        "never_use_terms": [f"term{i}" for i in range(80)],
        "tone_adjectives": [f"tone{i}" for i in range(40)],
    })
    assert len(card["never_use_terms"]) == 30
    assert len(card["tone_adjectives"]) == 10


def test_never_use_stoplist_drops_catastrophic_terms():
    """A guide that "bans" a pronoun is a distillation artifact. Honouring it
    would hard-block every page ever written."""
    card = vc.parse_voice_card({"never_use_terms": ["we", "our", "a", "world-class"]})
    assert card["never_use_terms"] == ["world-class"]


# --- is_card_empty / fingerprint -------------------------------------------

def test_is_card_empty():
    assert vc.is_card_empty(None)
    assert vc.is_card_empty({})
    assert vc.is_card_empty(vc.empty_card())
    assert not vc.is_card_empty(_card(tone_adjectives=["warm"]))
    # A guide that says only "write as we/our" is still worth enforcing —
    # it is exactly the rule the third-person default was overriding.
    assert not vc.is_card_empty(_card(person="first"))
    # Distinctiveness raw material alone is enough to render + enforce.
    assert not vc.is_card_empty(_card(differentiators=["50-year warranty"]))
    assert not vc.is_card_empty(_card(signature_phrases=["rain or shine"]))


def test_fingerprint_is_stable_and_change_sensitive():
    a = vc.card_fingerprint("guide text", "icp text")
    assert a == vc.card_fingerprint("  guide text  ", "icp text\n")
    assert a != vc.card_fingerprint("guide text", "different icp")
    assert a != vc.card_fingerprint("different guide", "icp text")
    # The separator prevents a field-boundary collision.
    assert vc.card_fingerprint("ab", "c") != vc.card_fingerprint("a", "bc")


# --- resolve_icp_directives ------------------------------------------------

FALLBACK = (
    "General Homeowner (professional/reliable)",
    "confident and trustworthy",
    '"Get a free estimate"',
)


def test_icp_directives_fall_back_without_a_card():
    assert vc.resolve_icp_directives(None, FALLBACK) == FALLBACK
    assert vc.resolve_icp_directives(vc.empty_card(), FALLBACK) == FALLBACK


def test_icp_directives_prefer_the_clients_own_icp():
    card = _card(
        audience_label="Melbourne homeowner with an ageing tile roof",
        tone_adjectives=["straight-talking"],
        audience_motivations=["avoid a full replacement"],
        audience_pain_points=["leaks before summer"],
        cta_language=["Book a free roof inspection"],
    )
    label, tone, cta = vc.resolve_icp_directives(card, FALLBACK)
    assert label == "Melbourne homeowner with an ageing tile roof"
    assert "straight-talking" in tone
    assert "avoid a full replacement" in tone
    assert "Book a free roof inspection" in cta
    assert "free estimate" not in cta


def test_icp_directives_fill_gaps_from_the_keyword_heuristic():
    """A card with audience data but no CTA language keeps the heuristic CTA
    rather than emitting nothing."""
    card = _card(audience_label="Commercial property manager")
    label, tone, cta = vc.resolve_icp_directives(card, FALLBACK)
    assert label == "Commercial property manager"
    assert tone == FALLBACK[1]
    assert cta == FALLBACK[2]


# --- render_voice_card_block -----------------------------------------------

def test_render_empty_card_emits_nothing():
    assert vc.render_voice_card_block(None) == ""
    assert vc.render_voice_card_block(vc.empty_card()) == ""


def test_render_block_states_the_override_and_the_rules():
    card = _card(
        brand_name="First Class Roofing",
        tone_adjectives=["straight-talking"],
        person="first",
        must_use_terms=["roof restoration"],
        never_use_terms=["world-class"],
        cta_language=["Book a free roof inspection"],
        audience_pain_points=["leaks before summer"],
    )
    block = vc.render_voice_card_block(card)
    assert "HIGHEST PRIORITY FOR EXPRESSION" in block
    assert "THESE RULES WIN" in block
    assert "FIRST PERSON" in block
    assert "roof restoration" in block
    assert "world-class" in block
    assert "Book a free roof inspection" in block
    assert "leaks before summer" in block
    # Structure must survive the override, or AEO scoring collapses.
    assert "Structural requirements" in block


def test_render_block_third_person_directive():
    block = vc.render_voice_card_block(_card(person="third", tone_adjectives=["formal"]))
    assert "THIRD PERSON" in block
    assert "FIRST PERSON" not in block


def test_render_block_carries_the_distinctiveness_directive():
    """The write-time mirror of the hardened judge: the writer is told it will
    be scored on the name-swap test and handed the client's distinctive
    material to lead with."""
    card = _card(
        tone_adjectives=["straight-talking"],
        differentiators=["50-year workmanship warranty", "only Malarkey-certified crew"],
        signature_phrases=["Roofs done right, rain or shine"],
    )
    block = vc.render_voice_card_block(card)
    assert "BE UNMISTAKABLY THIS CLIENT" in block
    assert "swapping the brand name" in block
    assert "50-year workmanship warranty" in block
    assert '"Roofs done right, rain or shine"' in block


def test_render_block_directive_fires_without_distinctiveness_material():
    """A thin/legacy card (no differentiators, missing keys entirely) still gets
    the directive — it leans on the audience block — and never KeyErrors."""
    block = vc.render_voice_card_block({"brand_name": "X", "tone_adjectives": ["bold"]})
    assert "BE UNMISTAKABLY THIS CLIENT" in block
    assert "Brand: X" in block
    # No spurious differentiator/signature lines when the fields are absent.
    assert "What sets this client apart" not in block
    assert "This brand's own words" not in block


# --- check_voice_compliance ------------------------------------------------

BODY = " ".join(["Roof restoration protects the home."] * 40)  # ~200 words


def test_clean_page_has_no_violations():
    card = _card(must_use_terms=["roof restoration"], never_use_terms=["world-class"])
    assert vc.check_voice_compliance(BODY, card) == []


def test_no_card_means_no_violations():
    assert vc.check_voice_compliance(BODY, None) == []
    assert vc.check_voice_compliance(BODY, vc.empty_card()) == []


def test_empty_page_is_not_flagged():
    card = _card(must_use_terms=["roof restoration"])
    assert vc.check_voice_compliance("", card) == []


def test_never_use_term_is_critical():
    card = _card(never_use_terms=["world-class", "cheap"])
    violations = vc.check_voice_compliance("We offer World-Class roofing.", card)
    assert len(violations) == 1
    assert violations[0]["check"] == "never_use_terms"
    assert violations[0]["severity"] == "critical"
    assert violations[0]["terms"] == ["world-class"]
    assert vc.has_critical(violations)


def test_never_use_matching_is_word_boundaried():
    """"cheap" must not fire on "cheaper" — a substring match would make the
    hard block unusable."""
    card = _card(never_use_terms=["cheap"])
    assert vc.check_voice_compliance("A cheaper option exists.", card) == []
    assert vc.check_voice_compliance("A cheap option exists.", card) != []


def test_term_regex_handles_punctuation_edges():
    regex = vc.build_term_regex(["100% guaranteed", "world-class"])
    assert regex.search("we are 100% guaranteed here")
    assert regex.search("a world-class team")
    assert vc.build_term_regex([]) is None
    assert vc.build_term_regex(["  "]) is None


def test_missing_required_term_warns():
    card = _card(must_use_terms=["roof restoration", "Colorbond"])
    violations = vc.check_voice_compliance(BODY, card)
    assert len(violations) == 1
    assert violations[0]["check"] == "must_use_terms"
    assert violations[0]["severity"] == "warning"
    assert violations[0]["terms"] == ["Colorbond"]
    assert not vc.has_critical(violations)


def test_person_first_but_page_is_third_person():
    card = _card(person="first")
    violations = vc.check_voice_compliance(BODY, card)
    assert [v["check"] for v in violations] == ["person"]
    assert violations[0]["severity"] == "warning"


def test_person_first_and_page_is_first_person_passes():
    card = _card(person="first")
    body = " ".join(["We restore roofs and our team protects the home."] * 25)
    assert vc.check_voice_compliance(body, card) == []


def test_person_third_but_page_leans_on_we():
    card = _card(person="third")
    body = " ".join(["We restore roofs and our crew protects our clients."] * 25)
    violations = vc.check_voice_compliance(body, card)
    assert [v["check"] for v in violations] == ["person"]


def test_person_check_skipped_on_short_text():
    """Density on a 20-word snippet is noise, not signal."""
    card = _card(person="first")
    assert vc.check_voice_compliance("Roof restoration protects the home.", card) == []


def test_cta_language_ignored_warns():
    card = _card(cta_language=["Book a free roof inspection"])
    violations = vc.check_voice_compliance(BODY + " Contact us today.", card)
    assert [v["check"] for v in violations] == ["cta_language"]


def test_cta_language_matches_loosely():
    """Natural variation must not trip the check — "Book your free inspection"
    is the client's CTA, not a violation."""
    card = _card(cta_language=["Book a free roof inspection"])
    assert vc.check_voice_compliance(BODY + " Book your free inspection now.", card) == []


# --- reporting helpers -----------------------------------------------------

def test_violations_to_corrections_names_the_exact_fix():
    card = _card(never_use_terms=["world-class"], must_use_terms=["Colorbond"])
    violations = vc.check_voice_compliance("We are world-class. " + BODY, card)
    text = vc.violations_to_corrections(violations)
    assert "HIGHEST PRIORITY" in text
    assert "MUST FIX" in text
    assert "world-class" in text
    assert "Colorbond" in text
    assert "schema block" in text  # never-use must be swept from schema too


def test_violations_to_corrections_empty_when_clean():
    assert vc.violations_to_corrections([]) == ""
    assert vc.violations_to_corrections(None) == ""


def test_compliance_summary_counts():
    card = _card(never_use_terms=["world-class"], must_use_terms=["Colorbond"])
    summary = vc.compliance_summary(vc.check_voice_compliance("world-class " + BODY, card))
    assert summary["passed"] is False
    assert summary["critical_count"] == 1
    assert summary["warning_count"] == 1
    assert vc.compliance_summary([])["passed"] is True


# --- distillation prompt ---------------------------------------------------

def test_distill_prompt_carries_both_documents():
    prompt = vc.build_distill_prompt("BRAND RULES HERE", "ICP DETAIL HERE")
    assert "BRAND RULES HERE" in prompt
    assert "ICP DETAIL HERE" in prompt


def test_distill_prompt_marks_missing_documents():
    prompt = vc.build_distill_prompt("", "ICP ONLY")
    assert "(none provided)" in prompt
    assert "ICP ONLY" in prompt


# --- the voice scorecard ---------------------------------------------------

def _dims(**overrides):
    """A full set of applicable dimensions, all scoring 100 unless overridden."""
    dims = {key: {"score": 100, "applicable": True} for key in vc.VOICE_DIMENSIONS}
    for key, value in overrides.items():
        dims[key] = value if isinstance(value, dict) else {"score": value, "applicable": True}
    return dims


def test_dimension_weights_sum_to_one():
    assert round(sum(m["weight"] for m in vc.VOICE_DIMENSIONS.values()), 6) == 1.0


def test_compute_voice_score_all_perfect():
    assert vc.compute_voice_score(_dims()) == 100.0


def test_compute_voice_score_is_weighted():
    # distinctiveness carries 0.10, so a zero there costs exactly 10 points.
    assert vc.compute_voice_score(_dims(distinctiveness=0)) == 90.0
    # tone carries 0.15.
    assert vc.compute_voice_score(_dims(tone=0)) == 85.0


def test_inapplicable_dimensions_are_excluded_and_renormalized():
    """A guide that says nothing about sentence rhythm must not be punished for
    it — the remaining weights renormalize rather than scoring it zero."""
    dims = _dims(writing_style={"applicable": False})
    assert vc.compute_voice_score(dims) == 100.0
    dims = _dims(writing_style={"applicable": False}, tone=0)
    # tone 0.15 of the remaining 0.85 → 100 * (0.85-0.15)/0.85
    assert vc.compute_voice_score(dims) == round(100 * 0.70 / 0.85, 1)


def test_compute_voice_score_none_when_nothing_scoreable():
    assert vc.compute_voice_score({}) is None
    assert vc.compute_voice_score(None) is None
    assert vc.compute_voice_score({k: {"applicable": False} for k in vc.VOICE_DIMENSIONS}) is None


def test_compute_voice_score_clamps_and_ignores_junk():
    assert vc.compute_voice_score(_dims(tone={"score": 500, "applicable": True})) == 100.0
    assert vc.compute_voice_score(_dims(tone={"score": "high", "applicable": True})) == 100.0


def test_voice_band_thresholds():
    # Bands reference VOICE_PASS_THRESHOLD (the "mostly on voice" floor) rather
    # than a hardcoded literal, so raising the bar doesn't silently break this.
    assert vc.voice_band(95) == "on_voice"
    assert vc.voice_band(vc.VOICE_PASS_THRESHOLD) == "mostly_on_voice"
    assert vc.voice_band(vc.VOICE_PASS_THRESHOLD - 0.1) == "drifting"
    assert vc.voice_band(59) == "off_voice"
    assert vc.voice_band(None) == "not_scored"


def test_deterministic_caps_override_a_generous_judge():
    """A scorer cannot call vocabulary strong on a page that provably contains a
    forbidden word."""
    violations = [{"check": "never_use_terms", "severity": "critical", "terms": ["world-class"]}]
    capped = vc.apply_deterministic_caps(_dims(), violations)
    assert capped["vocabulary"]["score"] == 40.0
    assert capped["vocabulary"]["capped_by_check"] == "never_use_terms"
    # Untouched dimensions keep their score.
    assert capped["tone"]["score"] == 100


def test_deterministic_caps_never_raise_a_score():
    violations = [{"check": "never_use_terms", "severity": "critical"}]
    capped = vc.apply_deterministic_caps(_dims(vocabulary=10), violations)
    assert capped["vocabulary"]["score"] == 10


def test_deterministic_caps_map_each_check():
    for check, (dimension, cap) in vc._DETERMINISTIC_CAPS.items():
        capped = vc.apply_deterministic_caps(_dims(), [{"check": check, "severity": "warning"}])
        assert capped[dimension]["score"] == cap


def test_build_voice_deficiencies_only_failing_worst_first():
    dims = _dims(tone=55, cta_fit=70, vocabulary=95)
    deficiencies = vc.build_voice_deficiencies(dims)
    assert [d["engine_key"] for d in deficiencies] == ["tone", "cta_fit"]
    assert deficiencies[0]["score"] == 55


def test_build_voice_deficiencies_skips_inapplicable():
    assert vc.build_voice_deficiencies(_dims(tone={"applicable": False})) == []


def test_voice_scorecard_assembles_everything():
    violations = [{"check": "never_use_terms", "severity": "critical", "terms": ["world-class"],
                   "message": "forbidden"}]
    card = vc.voice_scorecard(_dims(tone=60), violations)
    assert card["score"] is not None
    assert card["band"] in ("drifting", "mostly_on_voice", "off_voice")
    assert card["critical_count"] == 1
    assert card["passed"] is False
    assert card["needs_rewrite"] is True
    assert "tone" in card["dimensions"]
    assert card["dimensions"]["tone"]["label"] == "Tone & personality"
    assert {d["engine_key"] for d in card["deficiencies"]} >= {"tone", "vocabulary"}


def test_voice_scorecard_needs_rewrite_on_low_score_alone():
    """No forbidden word, but the page does not sound like the client."""
    card = vc.voice_scorecard(_dims(tone=40, distinctiveness=30, audience_fit=50), [])
    assert card["critical_count"] == 0
    assert card["score"] < vc.VOICE_PASS_THRESHOLD
    assert card["needs_rewrite"] is True


def test_voice_scorecard_clean_page_needs_no_rewrite():
    card = vc.voice_scorecard(_dims(), [])
    assert card["needs_rewrite"] is False
    assert card["passed"] is True
    assert card["score"] == 100.0


def test_voice_scorecard_survives_a_scorer_that_returned_nothing():
    card = vc.voice_scorecard({}, [])
    assert card["score"] is None
    assert card["band"] == "not_scored"
    assert card["needs_rewrite"] is False


def test_voice_deficiency_text_names_dimension_and_evidence():
    dims = _dims(tone={"score": 45, "applicable": True, "issues": ["reads like a brochure"],
                       "recommendations": ["use their plain-spoken register"],
                       "evidence": "We are a world-class provider of solutions"})
    text = vc.voice_deficiency_text(vc.build_voice_deficiencies(dims))
    assert "Tone & personality" in text
    assert "45/100" in text
    assert "reads like a brochure" in text
    assert "use their plain-spoken register" in text
    assert "world-class provider" in text


def test_voice_deficiency_text_empty_when_clean():
    assert vc.voice_deficiency_text([]) == ""
    assert vc.voice_deficiency_text(None) == ""


# --- "we could not check this" is its own answer ---------------------------

def test_scorecard_marks_analysis_full_when_dimensions_scored():
    assert vc.voice_scorecard(_dims(), [])["analysis"] == "full"


def test_scorecard_marks_deterministic_only_when_the_scorer_gave_nothing():
    """A scoring outage still runs the regex checks — but the page must not be
    mistaken for one that passed the full analysis."""
    card = vc.voice_scorecard({}, [{"check": "never_use_terms", "severity": "critical",
                                    "message": "forbidden word present"}])
    assert card["analysis"] == "deterministic_only"
    assert card["score"] is None
    assert card["band"] == "not_scored"
    # Crucially: a forbidden word still earns a rewrite with no scorer at all.
    assert card["needs_rewrite"] is True
    assert card["critical_count"] == 1


def test_deterministic_only_clean_page_needs_no_rewrite():
    card = vc.voice_scorecard({}, [])
    assert card["analysis"] == "deterministic_only"
    assert card["needs_rewrite"] is False


def test_unanalyzed_scorecard_is_not_a_pass():
    card = vc.unanalyzed_scorecard("guide could not be prepared")
    assert card["analysis"] == "not_analyzed"
    assert card["passed"] is False          # never looks clean
    assert card["score"] is None
    assert card["needs_rewrite"] is False   # nothing to rewrite toward
    assert card["reason"] == "guide could not be prepared"
    assert card["violations"] == []


def test_dimension_score_rejects_booleans():
    """isinstance(True, int) is True in Python — a scorer emitting
    `"score": true` must read as unscoreable, not as 1/100."""
    dims = _dims(tone={"score": True, "applicable": True})
    # tone excluded → renormalized over the rest, still 100.
    assert vc.compute_voice_score(dims) == 100.0


# --- missing_required_terms + insert_required_terms (deterministic net) -----

def _voice_card(**overrides):
    """A non-empty card (so is_card_empty is False) with must_use terms."""
    return _card(tone_adjectives=["reassuring"], **overrides)


def test_missing_required_terms_uses_page_presence():
    card = _voice_card(must_use_terms=["trusted", "expert", "premium materials"])
    # Only 'trusted' present → the other two are missing.
    missing = vc.missing_required_terms("We are trusted local specialists.", card)
    assert missing == ["expert", "premium materials"]
    # All present → none missing.
    assert vc.missing_required_terms(
        "Trusted expert roofing with premium materials.", card
    ) == []


def test_insert_swaps_filler_for_missing_required_adjective():
    card = _voice_card(must_use_terms=["trusted"])
    html = "<article><p>We built a great reputation on honest work.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == ["trusted"]
    assert "trusted reputation" in out
    assert "great reputation" not in out


def test_insert_never_touches_headings_or_chrome():
    card = _voice_card(must_use_terms=["trusted"])
    # 'great' only appears in a heading and a nav — neither is body prose.
    html = (
        "<nav>Great deals here</nav>"
        "<article><h2>Great service</h2><p>Reliable roofing, done well.</p></article>"
    )
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == []
    assert out == html  # untouched — no body-prose filler to swap


def test_insert_idiom_guard_leaves_measure_phrases_alone():
    card = _voice_card(must_use_terms=["trusted"])
    html = "<article><p>We do a great deal of our work in the area.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == []
    assert "great deal" in out  # 'a great deal' is an idiom, not an adjective+noun


def test_insert_fixes_indefinite_article_agreement():
    card = _voice_card(must_use_terms=["trusted", "expert"])
    html = "<article><p>An amazing standard and a great appearance.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == ["trusted", "expert"]
    # 'an amazing' -> 'a trusted' (consonant); 'a great' -> 'an expert' (vowel).
    assert "a trusted standard" in out.lower()
    assert "an expert appearance" in out.lower()
    assert "an trusted" not in out.lower()
    assert "a expert" not in out.lower()


def test_insert_skips_multiword_required_phrases():
    # A phrase can't be swapped for a single filler safely — left to the LLM loop.
    card = _voice_card(must_use_terms=["premium materials"])
    html = "<article><p>We use the best materials on every job.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == []


def test_insert_no_op_when_terms_present_or_no_filler():
    card = _voice_card(must_use_terms=["trusted"])
    # already present → nothing to do
    present = "<article><p>We are a trusted roofer.</p></article>"
    assert vc.insert_required_terms(present, card) == (present, [])
    # missing but no filler to swap → unchanged
    no_filler = "<article><p>We fix roofs across the city.</p></article>"
    assert vc.insert_required_terms(no_filler, card) == (no_filler, [])


def test_insert_one_swap_per_missing_term():
    card = _voice_card(must_use_terms=["trusted"])
    # two fillers, one missing term → exactly one swap
    html = "<article><p>A great reputation and a great appearance.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    assert swapped == ["trusted"]
    assert out.lower().count("trusted") == 1
    assert "great appearance" in out  # the second filler is left alone


def test_insert_respects_client_required_filler_and_discouraged():
    # 'best' is REQUIRED by this client → it must not be treated as a filler.
    card = _voice_card(must_use_terms=["trusted", "best"])
    html = "<article><p>We offer the best value in town.</p></article>"
    out, swapped = vc.insert_required_terms(html, card)
    # 'best' is present (required) so not missing; 'trusted' is missing but 'best'
    # is not an eligible filler → no swap.
    assert swapped == []


def test_insert_empty_card_and_empty_html_are_safe():
    assert vc.insert_required_terms("<p>hi</p>", {}) == ("<p>hi</p>", [])
    assert vc.insert_required_terms("", _voice_card(must_use_terms=["trusted"])) == ("", [])
    assert vc.missing_required_terms("", _voice_card(must_use_terms=["trusted"])) == []
