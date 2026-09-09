"""Unit tests for modules.writer.voice_review — the article-level voice review.

Pure + offline: the two LLM calls are injected via `judge_fn`. Also guards the
vendored `voice_card.py` against drifting from nlp-api's canonical copy — if
those two diverge, "did it sound like the client" silently starts meaning two
different things depending on which generator produced the text.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from models.writer import ArticleSection, BrandVoiceCard
from modules.writer import voice_review as vr

SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_ROOT.parent


def _run(coro):
    # asyncio.run, not get_event_loop().run_until_complete: the latter reuses a
    # process-wide loop that another test in the suite may already have closed,
    # which makes these pass in isolation and fail in a full run.
    return asyncio.run(coro)


def _section(heading: str, body: str) -> ArticleSection:
    return ArticleSection(
        order=1, level="H2", type="content", heading=heading, body=body,
        word_count=len(body.split()),
    )


def _card(**overrides) -> BrandVoiceCard:
    base = dict(
        brand_name="Acme Roofing",
        tone_adjectives=["straight-talking"],
        person="first",
        preferred_terms=["roof restoration"],
        banned_terms=["world-class"],
        audience_pain_points=["worried it leaks before winter"],
        cta_language=["Book a free roof inspection"],
    )
    base.update(overrides)
    return BrandVoiceCard(**base)


def _dims(score=95):
    return {key: {"score": score, "applicable": True} for key in
            ("tone", "writing_style", "person", "vocabulary",
             "audience_fit", "pain_points", "cta_fit", "distinctiveness")}


# ---------------------------------------------------------------------------
# Vendored-copy sync guard
# ---------------------------------------------------------------------------
def test_vendored_voice_card_matches_nlp_api():
    canonical = REPO_ROOT / "nlp-api" / "voice_card.py"
    vendored = SERVICE_ROOT / "modules" / "writer" / "voice_card.py"
    if not canonical.exists():  # nlp-api absent from this checkout
        return
    assert vendored.read_text() == canonical.read_text(), (
        "modules/writer/voice_card.py drifted from writer/nlp-api/voice_card.py. "
        "Re-copy it — the two services must score voice identically, and the "
        "pipeline-api Docker context cannot see nlp-api."
    )


# ---------------------------------------------------------------------------
# card_to_dict
# ---------------------------------------------------------------------------
def test_card_to_dict_maps_the_renamed_term_lists():
    card = vr.card_to_dict(_card())
    assert card["must_use_terms"] == ["roof restoration"]   # was preferred_terms
    assert card["never_use_terms"] == ["world-class"]       # was banned_terms
    assert card["person"] == "first"


def test_card_to_dict_maps_the_distinctiveness_fields():
    card = vr.card_to_dict(_card(
        differentiators=["50-year workmanship warranty"],
        signature_phrases=["Roofs done right, rain or shine"],
    ))
    assert card["differentiators"] == ["50-year workmanship warranty"]
    assert card["signature_phrases"] == ["Roofs done right, rain or shine"]


def test_card_to_dict_synthesises_an_audience_label():
    card = vr.card_to_dict(_card(
        audience_personas=["VP of Growth"], audience_verticals=["Beauty"],
    ))
    assert "VP of Growth" in card["audience_label"]
    assert "Beauty" in card["audience_label"]


def test_card_to_dict_falls_back_to_the_summary_for_the_label():
    card = vr.card_to_dict(_card(audience_summary="Melbourne homeowners"))
    assert card["audience_label"] == "Melbourne homeowners"


def test_card_to_dict_handles_none():
    assert vr.card_to_dict(None) == vr.vcard.empty_card()


# ---------------------------------------------------------------------------
# select_sections_to_revise
# ---------------------------------------------------------------------------
def test_no_sections_selected_when_the_article_passes():
    article = [_section("A", "body " * 50)]
    assert vr.select_sections_to_revise(article, {"needs_rewrite": False}, {}) == []


def test_forbidden_term_sections_are_selected_first():
    """A forbidden word is a fact and must be rewritten wherever it sits, even
    if that section is short."""
    article = [
        _section("Long one", "clean prose " * 200),
        _section("Short offender", "we are world-class"),
    ]
    card = {"never_use_terms": ["world-class"]}
    picked = vr.select_sections_to_revise(article, {"needs_rewrite": True}, card)
    assert picked[0][0] == "Short offender"


def test_longest_sections_selected_when_nothing_is_forbidden():
    article = [_section("Short", "a b"), _section("Long", "word " * 100)]
    picked = vr.select_sections_to_revise(article, {"needs_rewrite": True}, {})
    assert picked[0][0] == "Long"


def test_selection_is_capped():
    article = [_section(f"H{i}", "body " * 20) for i in range(20)]
    picked = vr.select_sections_to_revise(article, {"needs_rewrite": True}, {})
    assert len(picked) == vr._MAX_REVISED_SECTIONS


def test_sections_without_a_heading_or_body_are_skipped():
    article = [_section("", "orphan body"), _section("H", "   ")]
    assert vr.select_sections_to_revise(article, {"needs_rewrite": True}, {}) == []


# ---------------------------------------------------------------------------
# apply_revisions
# ---------------------------------------------------------------------------
def test_apply_revisions_replaces_body_and_recounts_words():
    article = [_section("Heading One", "old body")]
    applied = vr.apply_revisions(article, {"sections": [
        {"heading": "Heading One", "body": "a brand new body here"},
    ]})
    assert applied == 1
    assert article[0].body == "a brand new body here"
    assert article[0].word_count == 5


def test_apply_revisions_matches_headings_case_insensitively():
    article = [_section("Heading One", "old")]
    assert vr.apply_revisions(article, {"sections": [
        {"heading": "  heading ONE ", "body": "new"},
    ]}) == 1


def test_apply_revisions_never_adds_or_reorders_sections():
    """The model returning a heading we did not ask about must not create one —
    headings carry the SEO structure and a voice pass never touches them."""
    article = [_section("Real", "old")]
    vr.apply_revisions(article, {"sections": [
        {"heading": "Invented Heading", "body": "text"},
    ]})
    assert len(article) == 1
    assert article[0].body == "old"


def test_apply_revisions_tolerates_malformed_payloads():
    article = [_section("H", "original")]
    for payload in (None, {}, {"sections": "nope"}, {"sections": [None, 42]},
                    {"sections": [{"heading": "H"}]},
                    {"sections": [{"heading": "H", "body": "   "}]}):
        assert vr.apply_revisions(article, payload) == 0
    assert article[0].body == "original"


# ---------------------------------------------------------------------------
# review_article_voice
# ---------------------------------------------------------------------------
def test_no_card_means_no_review():
    calls = []

    async def judge(*a, **k):
        calls.append(a)
        return {}

    assert _run(vr.review_article_voice("T", [_section("H", "b")], None, judge_fn=judge)) is None
    assert calls == []


def test_clean_article_is_scored_but_not_revised():
    body = " ".join(["We handle roof restoration and our crew protects the home."] * 20)
    article = [_section("H", body + " Book a free roof inspection.")]
    calls = []

    async def judge(system, user, **k):
        calls.append(system)
        return _dims(95)

    card = _run(vr.review_article_voice("T", article, _card(), judge_fn=judge))
    assert card["needs_rewrite"] is False
    assert card["score"] == 95
    assert len(calls) == 1  # scored once, never revised


def test_forbidden_word_triggers_a_revision_that_fixes_it():
    article = [_section(
        "H",
        "We are world-class at roof restoration. " + "We protect our clients. " * 30
        + " Book a free roof inspection.",
    )]
    calls = []

    async def judge(system, user, **k):
        calls.append(system)
        if "revising" in system:
            return {"sections": [{
                "heading": "H",
                "body": "We are meticulous at roof restoration. "
                        + "We protect our clients. " * 30
                        + " Book a free roof inspection.",
            }]}
        return _dims(95)

    scorecard = _run(vr.review_article_voice("T", article, _card(), judge_fn=judge))
    assert "world-class" not in article[0].body
    assert scorecard["critical_count"] == 0
    assert scorecard["needs_rewrite"] is False


def test_low_score_triggers_a_revision_even_with_no_forbidden_word():
    body = " ".join(["We handle roof restoration and our crew protects the home."] * 20)
    article = [_section("H", body + " Book a free roof inspection.")]
    scores = iter([_dims(40), _dims(92)])
    revised = []

    async def judge(system, user, **k):
        if "revising" in system:
            revised.append(user)
            return {"sections": [{"heading": "H", "body": body + " Book a free roof inspection."}]}
        return next(scores)

    scorecard = _run(vr.review_article_voice("T", article, _card(), judge_fn=judge))
    assert revised, "a below-threshold score should have earned a revision pass"
    assert scorecard["score"] == 92


def test_scoring_failure_still_returns_the_deterministic_verdict():
    """The regex half needs no network — a judge outage must not mean no check."""
    article = [_section("H", "We are world-class. " + "filler words here. " * 40)]

    async def judge(*a, **k):
        raise RuntimeError("api down")

    scorecard = _run(vr.review_article_voice("T", article, _card(), judge_fn=judge))
    assert scorecard["analysis"] == "deterministic_only"
    assert scorecard["critical_count"] == 1


def test_revision_failure_leaves_the_article_untouched():
    original = "We are world-class. " + "filler words here. " * 40
    article = [_section("H", original)]

    async def judge(system, user, **k):
        if "revising" in system:
            raise RuntimeError("revision api down")
        return _dims(95)

    scorecard = _run(vr.review_article_voice("T", article, _card(), judge_fn=judge))
    assert article[0].body == original
    assert scorecard["critical_count"] == 1


def test_review_stops_after_the_pass_budget():
    """A model that never fixes the problem must not loop forever."""
    article = [_section("H", "We are world-class. " + "filler words here. " * 40)]
    revisions = []

    async def judge(system, user, **k):
        if "revising" in system:
            revisions.append(user)
            return {"sections": [{"heading": "H", "body": "Still world-class here. " * 20}]}
        return _dims(95)

    _run(vr.review_article_voice("T", article, _card(), judge_fn=judge, max_passes=2))
    assert len(revisions) == 2


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------
def test_score_prompt_carries_the_guide_and_the_article():
    prompt = vr.build_score_prompt("THE ARTICLE TEXT", vr.card_to_dict(_card()))
    assert "THE ARTICLE TEXT" in prompt
    assert "world-class" in prompt   # the forbidden list reaches the judge
    assert "FIRST PERSON" in prompt


def test_score_prompt_truncates_head_and_tail():
    text = "START" + ("x" * 40_000) + "END"
    prompt = vr.build_score_prompt(text, vr.card_to_dict(_card()))
    assert "START" in prompt
    assert "END" in prompt          # tail survives, so late drift is visible
    assert "middle truncated" in prompt


def test_revise_prompt_names_the_sections_and_the_faults():
    scorecard = vr.vcard.voice_scorecard(
        {"tone": {"score": 40, "applicable": True, "issues": ["reads generic"]}},
        [{"check": "never_use_terms", "severity": "critical",
          "message": 'forbidden: "world-class"'}],
    )
    prompt = vr.build_revise_prompt(
        vr.card_to_dict(_card()), scorecard, [("Heading One", "the body")],
    )
    assert "Heading One" in prompt
    assert "the body" in prompt
    assert "world-class" in prompt
    assert "reads generic" in prompt


# ---------------------------------------------------------------------------
# Mid-page voice-drift localizer (Lever 2)
# ---------------------------------------------------------------------------

def test_build_drift_block_filters_unknown_keys_and_dedupes():
    drift = {"drift": [
        {"key": "Our Process", "dimensions": ["rhythm", "register"], "note": "clipped list"},
        {"key": "Ghost Section", "dimensions": ["tone"], "note": "not on the page"},
        {"key": "Our Process", "dimensions": ["distinctiveness"], "note": "dupe key"},
    ]}
    block = vr.build_drift_block(drift, {"Our Process", "Intro"})
    assert "SECTIONS THAT DRIFT" in block
    assert "[Our Process]" in block
    assert "rhythm, register" in block
    assert "clipped list" in block
    # Unknown key dropped; duplicate key collapsed to a single line.
    assert "Ghost Section" not in block
    assert block.count("[Our Process]") == 1


def test_build_drift_block_accepts_bare_list_and_caps_at_six():
    keys = {f"S{i}" for i in range(10)}
    items = [{"key": f"S{i}", "dimensions": ["tone"]} for i in range(10)]
    block = vr.build_drift_block(items, keys)  # bare list, no wrapper
    assert block.count("  [S") == 6  # capped at 6 lines


def test_build_drift_block_empty_when_nothing_usable():
    assert vr.build_drift_block({"drift": []}, {"A"}) == ""
    assert vr.build_drift_block({"drift": [{"key": "X"}]}, {"A"}) == ""  # X not on page
    assert vr.build_drift_block("not a map", {"A"}) == ""


def test_section_digest_truncates_long_bodies():
    long_body = "word " * 1000
    digest = vr.section_digest(
        [{"key": "K", "heading": "H", "text": long_body}], max_inner_chars=50,
    )
    assert digest.startswith("[K] H:")
    assert "…" in digest
    assert len(digest) < 200


def test_localize_voice_drift_returns_block_from_audit():
    seen = {}

    async def judge(system, user, **kwargs):
        seen["system"] = system
        seen["user"] = user
        seen["model"] = kwargs.get("model")
        return {"drift": [{"key": "Commercial Roofing", "dimensions": ["register"],
                           "note": "bare bullet list"}]}

    sections = [
        {"key": "Commercial Roofing", "heading": "Commercial Roofing", "text": "Flat catalogue copy."},
        {"key": "Intro", "heading": "Intro", "text": "On-brand opening."},
    ]
    block = _run(vr.localize_voice_drift(sections, _card(), judge_fn=judge, model="claude-haiku-4-5-20251001"))
    assert "[Commercial Roofing]" in block
    assert "register" in block
    # The guide + the section digest both reach the auditor, at the chosen model.
    assert "world-class" in seen["user"]  # forbidden list from the rendered card
    assert "Commercial Roofing" in seen["user"]
    assert seen["model"] == "claude-haiku-4-5-20251001"


def test_localize_voice_drift_noops_without_a_guide_or_sections():
    calls = []

    async def judge(*a, **k):
        calls.append(a)
        return {"drift": [{"key": "A", "dimensions": ["tone"]}]}

    # No card -> empty card -> no audit call.
    assert _run(vr.localize_voice_drift([{"key": "A", "heading": "A", "text": "x"}], None, judge_fn=judge)) == ""
    # No sections -> no audit call.
    assert _run(vr.localize_voice_drift([], _card(), judge_fn=judge)) == ""
    assert calls == []


def test_localize_voice_drift_degrades_on_audit_failure():
    async def judge(*a, **k):
        raise RuntimeError("haiku down")

    block = _run(vr.localize_voice_drift(
        [{"key": "A", "heading": "A", "text": "x"}], _card(), judge_fn=judge,
    ))
    assert block == ""  # best-effort: failure -> no block, prior behaviour
