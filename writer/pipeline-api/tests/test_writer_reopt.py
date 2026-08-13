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
