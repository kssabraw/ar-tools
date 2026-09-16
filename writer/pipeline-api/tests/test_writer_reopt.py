"""Unit tests for the blog Writer's reoptimization directive.

Pure — no network, no LLM. The directive is folded into the per-run user_notes
so every section/intro/conclusion prompt is steered to fix the scorer's
deficiencies while preserving the prior draft's strengths.
"""

import importlib.util
import os

# Load reopt.py directly (it has no framework deps), so this test doesn't drag in
# the writer package __init__ (fastapi, etc.).
_REOPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "modules", "writer", "reopt.py",
)
_spec = importlib.util.spec_from_file_location("writer_reopt", _REOPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
reopt_directive = _mod.reopt_directive
compose_reopt_notes = _mod.compose_reopt_notes


def test_empty_deficiencies_returns_empty():
    assert reopt_directive([]) == ""
    assert reopt_directive(None) == ""  # type: ignore[arg-type]


def test_non_dict_deficiencies_ignored():
    assert reopt_directive(["nope", 5]) == ""  # type: ignore[list-item]


def test_directive_lists_engines_issues_and_fixes():
    defs = [
        {
            "engine": "AEO / LLM Retrieval Engine",
            "issues": ["No direct answer sentence", "No Key Takeaways"],
            "recommendations": ["Add a liftable answer", "Add a takeaways block"],
        },
        {"engine_key": "eeat_citations", "issues": ["Uncited stats"], "recommendations": []},
    ]
    out = reopt_directive(defs)
    assert "REOPTIMIZATION PASS" in out
    assert "AEO / LLM Retrieval Engine" in out
    assert "No direct answer sentence; No Key Takeaways" in out
    assert "Add a liftable answer; Add a takeaways block" in out
    # Falls back to engine_key when no human label present.
    assert "eeat_citations" in out


def test_prior_sections_named_for_preservation():
    out = reopt_directive(
        [{"engine": "Content Depth", "issues": ["thin"], "recommendations": ["expand"]}],
        prior_sections=[{"heading": "What is X"}, {"heading": "How X works"}, {"no_heading": 1}],
    )
    assert "preserve what already works" in out
    assert "What is X" in out
    assert "How X works" in out


# ---- compose_reopt_notes: gain guidance rides as advisory steering, out of QA ----

_GAIN = (
    "TOPIC & INFORMATION-GAIN GUIDANCE (report-only signal — improve where it "
    "does not conflict...):\n  - subtopic: dosing protocols"
)


def test_compose_generate_no_gain_is_byte_identical():
    # A plain generate run with no gain guidance: section notes == QA notes == the
    # user's own notes (byte-identical to prior behaviour).
    section, qa = compose_reopt_notes("mention Acme", mode="generate")
    assert section == "mention Acme"
    assert qa == "mention Acme"


def test_compose_none_everywhere_returns_none():
    section, qa = compose_reopt_notes(None, mode="generate")
    assert section is None and qa is None


def test_compose_reoptimize_folds_directive_into_both():
    defs = [{"engine": "AEO", "issues": ["no FAQ"], "recommendations": ["add FAQ"]}]
    section, qa = compose_reopt_notes(
        "mention Acme", mode="reoptimize", deficiencies=defs,
    )
    # The must-land directive is in BOTH (it's a real fix instruction, graded).
    assert "REOPTIMIZATION PASS" in section
    assert "REOPTIMIZATION PASS" in qa
    assert "mention Acme" in section and "mention Acme" in qa
    assert section == qa  # no gain guidance → identical


def test_compose_gain_guidance_only_in_section_notes_not_qa():
    section, qa = compose_reopt_notes(
        "mention Acme", mode="reoptimize",
        deficiencies=[{"engine": "AEO", "issues": ["x"], "recommendations": ["y"]}],
        gain_guidance=_GAIN,
    )
    # Advisory coaching steers the writing...
    assert "INFORMATION-GAIN GUIDANCE" in section
    assert "dosing protocols" in section
    # ...but is NEVER graded as a must-land user directive.
    assert "INFORMATION-GAIN GUIDANCE" not in qa
    assert "dosing protocols" not in qa
    # The must-land content survives in both.
    assert "mention Acme" in qa and "REOPTIMIZATION PASS" in qa


def test_compose_gain_guidance_with_no_user_notes():
    # Gain guidance alone (no user notes, generate mode) still steers, still out of QA.
    section, qa = compose_reopt_notes(None, mode="generate", gain_guidance=_GAIN)
    assert section is not None and "dosing protocols" in section
    assert qa is None  # nothing must-land


def test_compose_empty_gain_guidance_is_ignored():
    section, qa = compose_reopt_notes("notes", mode="generate", gain_guidance="   ")
    assert section == "notes" and qa == "notes"


def test_compose_gain_is_never_a_deficiency():
    # The guidance is text-only steering; it never becomes a scored deficiency.
    defs = [{"engine": "AEO", "issues": ["x"], "recommendations": ["y"]}]
    section, _ = compose_reopt_notes(
        "n", mode="reoptimize", deficiencies=defs, gain_guidance=_GAIN,
    )
    # compose_reopt_notes returns notes strings, never a deficiency list — the
    # caller (pipeline) passes `deficiencies` separately and unchanged.
    assert isinstance(section, str)
    assert defs == [{"engine": "AEO", "issues": ["x"], "recommendations": ["y"]}]
