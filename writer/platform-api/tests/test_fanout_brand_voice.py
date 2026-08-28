"""Tests for Fan-out brand-voice enforcement (fanout/writer/brand_voice.py).

Covers: the vendored voice_card.py stays byte-identical to the canonical
(sync-guard), the copied scorer/reviser prompts stay in step with the
interactive writer's (parallel-maintained guard), the pure selection/apply
helpers, and the full enforce_voice loop driven by a fake sync LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fanout.writer import brand_voice as bv
from fanout.writer import voice_card as vcard

_REPO = Path(__file__).resolve().parents[3]      # …/ (repo root)
_PLATFORM = Path(__file__).resolve().parents[1]  # …/writer/platform-api


# ---------------------------------------------------------------------------
# vendoring / drift guards
# ---------------------------------------------------------------------------
def test_vendored_voice_card_matches_canonical():
    """The Fan-out copy of voice_card.py must stay byte-identical to nlp-api's
    canonical, so the voice-scoring math/weights/threshold never drift."""
    canonical = _REPO / "writer" / "nlp-api" / "voice_card.py"
    if not canonical.exists():  # nlp-api absent from this checkout
        return
    vendored = _PLATFORM / "fanout" / "writer" / "voice_card.py"
    assert vendored.read_text() == canonical.read_text(), (
        "fanout/writer/voice_card.py drifted from writer/nlp-api/voice_card.py — "
        "re-copy the canonical."
    )


def test_score_and_revise_prompts_match_interactive_writer():
    """The scorer/reviser rubric prompts are copied from the interactive writer's
    voice_review.py and parallel-maintained; guard that they haven't drifted."""
    source_path = (_REPO / "writer" / "pipeline-api" / "modules" / "writer"
                   / "voice_review.py")
    if not source_path.exists():
        return
    source = source_path.read_text()
    assert bv._SCORE_SYSTEM in source, "fanout _SCORE_SYSTEM drifted from voice_review.py"
    assert bv._REVISE_SYSTEM in source, "fanout _REVISE_SYSTEM drifted from voice_review.py"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@dataclass
class _Section:
    heading: str | None
    body: str
    word_count: int = 0


def _card() -> dict:
    card = vcard.empty_card()
    card.update({
        "brand_name": "Acme Plumbing",
        "tone_adjectives": ["warm", "direct"],
        "person": "first",
        "never_use_terms": ["cheapest"],
        "must_use_terms": [],
        "audience_label": "homeowners",
    })
    return card


class _FakeLLM:
    """A fan-out section_llm stub: complete_text returns queued responses."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_text(self, *, system, user, purpose, max_tokens=None, temperature=None):
        self.calls.append({"system": system, "user": user, "purpose": purpose})
        return self._responses.pop(0) if self._responses else "{}"


_LOW_SCORE = (
    '{"tone":{"score":40,"applicable":true,"evidence":"x"},'
    '"writing_style":{"score":45,"applicable":true,"evidence":"x"},'
    '"person":{"score":40,"applicable":true,"evidence":"x"},'
    '"vocabulary":{"score":40,"applicable":true,"evidence":"x"},'
    '"audience_fit":{"score":45,"applicable":true,"evidence":"x"},'
    '"pain_points":{"score":40,"applicable":true,"evidence":"x"},'
    '"cta_fit":{"score":40,"applicable":true,"evidence":"x"},'
    '"distinctiveness":{"score":40,"applicable":true,"evidence":"x"}}'
)
_HIGH_SCORE = (
    '{"tone":{"score":92,"applicable":true,"evidence":"x"},'
    '"writing_style":{"score":90,"applicable":true,"evidence":"x"},'
    '"person":{"score":95,"applicable":true,"evidence":"x"},'
    '"vocabulary":{"score":93,"applicable":true,"evidence":"x"},'
    '"audience_fit":{"score":90,"applicable":true,"evidence":"x"},'
    '"pain_points":{"score":90,"applicable":true,"evidence":"x"},'
    '"cta_fit":{"score":90,"applicable":true,"evidence":"x"},'
    '"distinctiveness":{"score":91,"applicable":true,"evidence":"x"}}'
)


# ---------------------------------------------------------------------------
# render_block
# ---------------------------------------------------------------------------
def test_render_block_empty_card_is_blank():
    assert bv.render_block(None) == ""
    assert bv.render_block({}) == ""
    assert bv.render_block(vcard.empty_card()) == ""


def test_render_block_populated_card_has_content():
    block = bv.render_block(_card())
    assert block.strip()
    assert "Acme Plumbing" in block


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------
def test_select_sections_prioritises_forbidden_term():
    scorecard = {"needs_rewrite": True}
    secs = [
        _Section("Pricing", "We offer the cheapest rates in town."),  # forbidden term
        _Section("About", "A" * 400),                                 # longest, but clean
    ]
    targets = bv.select_sections_to_revise(secs, scorecard, _card())
    assert targets[0][0] == "Pricing"  # forbidden-term section first


def test_select_sections_none_when_no_rewrite_needed():
    assert bv.select_sections_to_revise([_Section("H", "b")], {"needs_rewrite": False}, _card()) == []


def test_apply_revisions_mutates_by_heading_and_skips_unknown():
    secs = [_Section("Intro", "old body", 2), _Section("Body", "old two", 2)]
    n = bv.apply_revisions(secs, {"sections": [
        {"heading": "intro", "body": "new intro body"},   # case-insensitive match
        {"heading": "ghost", "body": "ignored"},          # unknown heading skipped
    ]})
    assert n == 1
    assert secs[0].body == "new intro body"
    assert secs[0].word_count == 3
    assert secs[1].body == "old two"  # untouched


def test_apply_revisions_tolerates_malformed():
    assert bv.apply_revisions([_Section("H", "b")], None) == 0
    assert bv.apply_revisions([_Section("H", "b")], {"sections": "nope"}) == 0
    assert bv.apply_revisions([_Section("H", "b")], {"sections": [{"heading": "H", "body": ""}]}) == 0


def test_parse_json_tolerant():
    assert bv._parse_json('{"a": 1}') == {"a": 1}
    assert bv._parse_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert bv._parse_json('prose then {"a": 3} trailing') == {"a": 3}
    assert bv._parse_json("not json") is None
    assert bv._parse_json("") is None


# ---------------------------------------------------------------------------
# enforce_voice
# ---------------------------------------------------------------------------
def test_enforce_voice_none_without_card():
    secs = [_Section("H", "body")]
    assert bv.enforce_voice("Title", secs, None, _FakeLLM([])) is None
    assert bv.enforce_voice("Title", secs, vcard.empty_card(), _FakeLLM([])) is None


def test_enforce_voice_rewrites_low_scoring_article():
    secs = [
        _Section("How we work", "B" * 300),
        _Section("Our promise", "C" * 300),
    ]
    # Pass 1: low score → triggers a revision → re-score high (keep-best stops).
    revision = ('{"sections":[{"heading":"How we work","body":"Rewritten on-voice body."},'
                '{"heading":"Our promise","body":"Rewritten promise body."}]}')
    llm = _FakeLLM([_LOW_SCORE, revision, _HIGH_SCORE])
    scorecard = bv.enforce_voice("Title", secs, _card(), llm, max_passes=2)
    assert scorecard is not None
    assert scorecard["score"] >= vcard.VOICE_PASS_THRESHOLD
    # The low-scoring bodies were rewritten in place.
    assert secs[0].body == "Rewritten on-voice body."
    assert secs[1].body == "Rewritten promise body."


def test_enforce_voice_deterministic_only_on_score_failure():
    # LLM score returns junk (no JSON) → deterministic-only scorecard, no crash,
    # article left as written.
    secs = [_Section("Pricing", "We are not the cheapest, but the best.")]
    llm = _FakeLLM(["totally not json", "totally not json", "totally not json"])
    scorecard = bv.enforce_voice("Title", secs, _card(), llm, max_passes=1)
    assert scorecard is not None
    assert scorecard["analysis"] in ("deterministic_only", "full")
    # A forbidden term present → critical finding surfaced.
    assert scorecard["critical_count"] >= 1
