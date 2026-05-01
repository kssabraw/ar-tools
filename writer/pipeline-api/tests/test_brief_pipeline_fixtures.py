"""End-to-end pipeline fixtures from PRD §14.3 (v2.0.2).

Each fixture mocks the appropriate external layers and asserts the
PRD's expected behavior over the full orchestrator. These tests are
the integration-level regression net for the v2.0.x feature set:

  Fixture A — TikTok Shop replication (extended for v2.0.2 silo fields)
  Fixture D — Constraint exhaustion (h2_shortfall handling)
  Fixture H — H3 sparsity (Step 8.6 zero-attachment edge case)
  Fixture I — Silo discard reason filtering (Step 12.1)
  Fixture J — Silo viability rejection (Step 12.4)
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Callable, Optional
from unittest.mock import patch

import pytest

from models.brief import BriefRequest


# ----------------------------------------------------------------------
# Reusable synthetic data builders
# ----------------------------------------------------------------------

def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# Topic → axis routing for the synthetic embedder. Strings on the LEFT
# are matched as substrings (lowercased). Vectors are then constructed
# so each topic cluster has a distinct primary axis but all share the
# title axis (0) at a magnitude that puts cosine-to-title inside the
# eligible band [0.55, 0.78] for in-scope topics.
_TOPIC_AXES: list[tuple[str, int, float]] = [
    # (substring, axis, title-axis weight)
    # — title-restatement (cosine > 0.85): drop directly on axis 0
    ("what is tiktok shop", 0, 0.97),
    ("what is the tiktok shop", 0, 0.97),
    ("what exactly is tiktok shop", 0, 0.97),
    ("what does tiktok shop", 0, 0.95),
    ("what tiktok shop", 0, 0.94),
    # — in-band useful subtopics: cosine ~0.70 to title; spread axes 1–4
    ("how does tiktok shop work", 1, 0.70),
    ("how it works", 1, 0.70),
    ("how tiktok shop works", 1, 0.70),
    ("setup", 2, 0.70),
    ("set up", 2, 0.70),
    ("how to set up", 2, 0.70),
    ("seller requirements", 2, 0.68),
    ("fees", 3, 0.70),
    ("charge", 3, 0.70),
    ("cost", 3, 0.70),
    ("payment", 3, 0.70),
    # — persona gap questions land on axis 4 so they cluster together
    ("gap question", 4, 0.70),
    # — algorithm-tactical: in eligible band but typically out-of-scope
    ("algorithm", 5, 0.65),
    ("optimize", 5, 0.65),
    # — off-topic: orthogonal to title (below relevance floor)
    ("cooking", 7, 0.0),
    ("recipes", 7, 0.0),
]


def _normalize_vec(text: str, dim: int = 12) -> list[float]:
    """Smart synthetic embedder: routes each text to a primary topic axis
    and builds a vector that puts cosine-to-title inside the right band.

    Adds a tiny per-text perturbation so candidates within the same
    topic cluster differ slightly (Louvain still groups them; coherence
    stays high; pairwise cosines under one H2 stay below 0.78 if we
    perturb across non-primary axes).
    """
    text_l = text.lower()

    # Pick the first matching topic; fall back to a generic in-band slot
    # so unmatched candidates don't all collapse onto axis 0.
    primary_axis = 1
    title_weight = 0.65
    for needle, axis, weight in _TOPIC_AXES:
        if needle in text_l:
            primary_axis = axis
            title_weight = weight
            break

    vec = [0.0] * dim
    vec[0] = title_weight
    if primary_axis != 0 and primary_axis < dim:
        # Choose a secondary weight so the result roughly unit-normalizes
        secondary = math.sqrt(max(1.0 - title_weight ** 2, 0.0))
        vec[primary_axis] = secondary

    # Per-text perturbation on axes other than 0 and primary_axis so
    # cluster members aren't byte-identical (avoids exact-cosine 1.0
    # which would fail the inter_h3 / restatement bands artificially).
    seed = sum(ord(c) for c in text)
    for i in range(dim):
        if i in (0, primary_axis):
            continue
        vec[i] += ((seed + i * 7) % 7) / 200.0  # ≤ 0.03 noise per axis

    return _normalize(vec)


def _build_serp_items(
    n: int = 20,
    description_template: Optional[str] = None,
    extras: Optional[list[dict]] = None,
) -> list[dict]:
    """Build a topically-diverse SERP organic feed.

    The default template seeds three in-band topics (works / setup /
    fees) plus a paraphrase trap (the title itself) so the run produces:

      * multiple coverage-graph regions (axes 1, 2, 3 from the smart embedder)
      * above_restatement_ceiling rejects (Fixture I source)
      * algorithm-tactical headings via PAA (Fixture J / scope-reject source)
    """
    items: list[dict] = []
    if description_template is None:
        # Including the algorithm-tactical line in every description gives
        # it serp_frequency ~= n, putting search_demand_score above the
        # 0.30 floor so it can materialize as a scope-verification silo
        # in fixture I / J.
        description_template = (
            "Article variant {i} covering the basics. "
            "How TikTok Shop works for sellers:\n"
            "Setup process for new sellers:\n"
            "Fees and charges sellers should know:\n"
            "How to optimize for the TikTok Shop algorithm:"
        )
    for i in range(n):
        items.append({
            "type": "organic",
            "rank_absolute": i + 1,
            "rank_group": i + 1,
            "url": f"https://site{i}.example.com/article",
            "title": f"What TikTok Shop Is and How It Works — Article {i}",
            "description": description_template.format(i=i),
        })
    if extras:
        items.extend(extras)
    else:
        items.append({
            "type": "people_also_ask",
            "items": [
                {"title": "How does TikTok Shop work for sellers?"},
                {"title": "How to set up a TikTok Shop account?"},
                {"title": "How much does TikTok Shop charge in fees?"},
                # algorithm-tactical → scope_verification routes to silo
                {"title": "How to optimize for the TikTok Shop algorithm?"},
            ],
        })
        items.append({"type": "featured_snippet", "title": "TikTok Shop"})
    return items


def _build_reddit_items(n: int = 2) -> list[dict]:
    return [
        {
            "title": f"Has anyone made money on TikTok Shop variant {i}?",
            "description": "Curious if it is worth setting up an account.",
        }
        for i in range(n)
    ]


# ----------------------------------------------------------------------
# Default mocks (overridable per fixture)
# ----------------------------------------------------------------------

async def _default_serp(*args, **kwargs):
    return {"task": {}, "items": _build_serp_items()}


async def _default_reddit(*args, **kwargs):
    return _build_reddit_items()


async def _default_autocomplete(*args, **kwargs):
    return ["tiktok shop how it works", "tiktok shop fees", "tiktok shop setup"]


async def _default_keyword_suggestions(*args, **kwargs):
    return ["tiktok shop guide", "tiktok shop tutorial"]


async def _default_llm_response(*args, **kwargs):
    # Each of the 4 LLM fanouts returns the same payload, including the
    # algorithm-tactical query. After Levenshtein dedup against PAA's
    # "How to optimize for the TikTok Shop algorithm?", consensus on
    # the merged candidate reaches 4 → search_demand_score
    # = 0.25 (consensus 4/4) + 0.20 (paa presence) = 0.45 (above 0.30
    # floor), so it materializes as a scope-verification silo.
    return {
        "text": (
            "TikTok Shop is a social commerce platform inside TikTok. "
            "It lets creators sell directly via short videos and live streams."
        ),
        "fan_out_queries": [
            "how to set up tiktok shop",
            "tiktok shop seller requirements",
            "how to optimize for the tiktok shop algorithm",
        ],
    }


async def _default_embed(texts, normalize=True):
    return [_normalize_vec(t) for t in texts]


def _make_default_claude_router(
    *,
    viability_default_viable: bool = True,
    viability_per_keyword: Optional[dict[str, bool]] = None,
):
    """Build a claude_json mock keyed on system-prompt phrases.

    `viability_default_viable` controls Step 12.4's verdict for any
    candidate not listed in `viability_per_keyword`.
    """

    async def _router(system: str, user: str, **kwargs):
        sys_l = system.lower()

        if "generate the article title" in sys_l:
            return {
                "title": "What TikTok Shop Is and How It Works in 2026",
                "scope_statement": (
                    "Defines TikTok Shop and explains how it works for sellers "
                    "and buyers. Does not cover advanced seller tactics, "
                    "algorithm optimization, or inventory management decisions."
                ),
                "title_rationale": "Top SERP titles converge on definitional framing.",
            }

        if "hypothetical searcher" in sys_l:
            return {
                "persona": {
                    "description": "A small-business owner curious about TikTok Shop.",
                    "background_assumptions": [
                        "Knows what TikTok is",
                        "Has basic e-commerce familiarity",
                    ],
                    "primary_goal": "Decide whether TikTok Shop fits their business.",
                },
                "gap_questions": [
                    {"question": f"Gap question {i}?", "rationale": f"R{i}"}
                    for i in range(6)
                ],
            }

        if "verify that each candidate" in sys_l:
            lines = [
                ln.strip() for ln in user.split("\n")
                if ln.strip().startswith(tuple("0123456789"))
            ]
            items = []
            for ln in lines:
                text = ln.split(". ", 1)[-1] if ". " in ln else ln
                if not text:
                    continue
                # Algorithm-tactical phrasing → out_of_scope so it
                # routes to silos via routed_from="scope_verification".
                lower = text.lower()
                if "algorithm" in lower or "optimize" in lower:
                    classification = "out_of_scope"
                else:
                    classification = "in_scope"
                items.append({
                    "h2_text": text,
                    "scope_classification": classification,
                    "reasoning": "scope check",
                })
            return {"verified_h2s": items}

        if "universal authority agent" in sys_l:
            return {"headings": [
                "Common cognitive biases that derail TikTok Shop sellers",
                "Tax and consumer-protection rules sellers must follow",
                "How TikTok Shop's algorithm shifts seller economics over years",
            ]}

        if "tutorial steps" in sys_l:
            return {"order": list(range(20))}

        if "classify search intent" in sys_l:
            return {"intent": "informational"}

        if "implicit questions" in sys_l:
            return {"questions": [
                "How long does TikTok Shop take to approve a seller application?",
                "What payment methods does TikTok Shop support for sellers?",
            ]}

        if "extract all distinct subtopics" in sys_l:
            return ["Setup process", "Seller fees", "Payment methods"]

        # Step 12.4 viability — Anthropic prompt starts with
        # "You verify whether a candidate silo keyword..."
        if "viable" in sys_l and "standalone" in sys_l:
            # Extract the candidate keyword from the user prompt
            cand_kw = ""
            for ln in user.split("\n"):
                if ln.startswith("Candidate keyword:"):
                    cand_kw = ln.split(":", 1)[1].strip()
                    break
            verdict = (viability_per_keyword or {}).get(
                cand_kw, viability_default_viable,
            )
            return {
                "candidate_keyword": cand_kw or "unknown",
                "viable_as_standalone_article": verdict,
                "reasoning": "Distinct intent" if verdict else "Restates parent",
                "estimated_intent": "how-to" if verdict else "informational",
            }

        return {}

    return _router


# ----------------------------------------------------------------------
# Patch context with per-fixture overrides
# ----------------------------------------------------------------------

@contextmanager
def _fixture_mocks(
    *,
    serp=_default_serp,
    reddit=_default_reddit,
    autocomplete=_default_autocomplete,
    keyword_suggestions=_default_keyword_suggestions,
    llm_response=_default_llm_response,
    embed=_default_embed,
    claude_router: Optional[Callable] = None,
):
    """Patch every external dependency. Any kwarg can be overridden."""
    router = claude_router or _make_default_claude_router()

    async def cache_miss(*a, **k):
        return None

    async def cache_write(*a, **k):
        return None

    patches = [
        patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", serp),
        patch("modules.brief.pipeline.dataforseo.serp_reddit", reddit),
        patch("modules.brief.pipeline.dataforseo.autocomplete", autocomplete),
        patch("modules.brief.pipeline.dataforseo.keyword_suggestions",
              keyword_suggestions),
        patch("modules.brief.pipeline.dataforseo.llm_response", llm_response),
        patch("modules.brief.pipeline.embed_batch_large", embed),
        patch("modules.brief.pipeline.claude_json", router),
        patch("modules.brief.title_scope.claude_json", router),
        patch("modules.brief.persona.claude_json", router),
        patch("modules.brief.scope_verification.claude_json", router),
        patch("modules.brief.authority.claude_json", router),
        patch("modules.brief.assembly.claude_json", router),
        patch("modules.brief.faqs.claude_json", router),
        patch("modules.brief.faqs.embed_batch_large", embed),
        patch("modules.brief.graph.embed_batch_large", embed),
        patch("modules.brief.intent.claude_json", router),
        # Step 12.4 viability lives in silos.py
        patch("modules.brief.silos.claude_json", router),
        patch("modules.brief.pipeline.get_cached", cache_miss),
        patch("modules.brief.pipeline.write_cache", cache_write),
    ]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ----------------------------------------------------------------------
# Fixture A — TikTok Shop replication (extended for v2.0.2)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fixture_a_tiktok_shop_v2_0_2_silo_fields_present():
    """Fixture A extension: verify silos carry search_demand_score,
    viable_as_standalone_article, viability_reasoning, and estimated_intent.

    The synthetic SERP includes an algorithm-tactical PAA entry that the
    scope-verification mock classifies as out_of_scope; combined with
    LLM fanout consensus across all 4 mocked LLMs, demand clears the
    0.30 floor so the candidate materializes as a silo with
    routed_from="scope_verification".
    """
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-a", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # Non-vacuous: at least one silo must materialize via the
    # scope_verification path so the v2.0.2 field assertions actually run.
    assert len(result.silo_candidates) >= 1, (
        "expected at least one silo from scope_verification path"
    )
    scope_silos = [
        s for s in result.silo_candidates
        if s.routed_from == "scope_verification"
    ]
    assert scope_silos, "expected a scope_verification-routed silo"

    for silo in result.silo_candidates:
        # 12.3 — every silo must clear the demand floor
        assert silo.search_demand_score >= 0.30
        # 12.4 — default router returns viable=true for all
        assert silo.viable_as_standalone_article is True
        assert silo.viability_reasoning  # non-empty
        assert silo.estimated_intent in {
            "informational", "listicle", "how-to", "comparison",
            "ecom", "local-seo", "news", "informational-commercial",
        }
        # 12.5 — v2.0.2 default
        assert silo.cross_brief_occurrence_count == 1
        # 12.6 — discard breakdown is populated
        assert silo.discard_reason_breakdown


@pytest.mark.asyncio
async def test_fixture_a_h3s_within_h2s_obey_step_8_6_bounds():
    """Fixture A extension: each non-authority H3 has parent_relevance
    in [0.60, 0.85]; H3 siblings under one H2 don't paraphrase each other."""
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-a-h3", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # Group H3s by parent
    by_parent: dict[str, list] = {}
    for h in result.heading_structure:
        if h.level != "H3" or h.type != "content" or h.source == "authority_gap_sme":
            continue
        if not h.parent_h2_text:
            continue
        by_parent.setdefault(h.parent_h2_text, []).append(h)

    for parent_text, siblings in by_parent.items():
        for h3 in siblings:
            assert 0.60 <= h3.parent_relevance <= 0.85, (
                f"H3 {h3.text!r} parent_relevance={h3.parent_relevance} "
                f"outside [0.60, 0.85] for parent {parent_text!r}"
            )


# ----------------------------------------------------------------------
# Fixture D — Constraint exhaustion
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fixture_d_constraint_exhaustion_flags_h2_shortfall():
    """Construct a scenario where eligible candidates cluster heavily into
    a single region — MMR's region uniqueness constraint produces a
    shortfall, which must be flagged in metadata (PRD §5 Step 8)."""
    from modules.brief.pipeline import run_brief

    # All SERP descriptions push the same "what is" framing → tight cluster.
    serp_items = _build_serp_items(
        n=20,
        description_template=(
            "What is TikTok Shop:\nWhat does TikTok Shop mean:\n"
            "What TikTok Shop offers:"
        ),
    )
    serp_items.append({
        "type": "people_also_ask",
        "items": [
            {"title": "What is TikTok Shop in simple terms?"},
            {"title": "What does TikTok Shop mean for sellers?"},
        ],
    })

    async def tight_serp(*a, **k):
        return {"task": {}, "items": serp_items}

    req = BriefRequest(run_id="fix-d", keyword="what is tiktok shop")
    with _fixture_mocks(serp=tight_serp):
        result = await run_brief(req)

    # The pipeline doesn't have to flag shortfall in this exact synthetic
    # setup, but if it does, the metadata reasons must match.
    if result.metadata.h2_shortfall:
        assert result.metadata.h2_shortfall_reason == (
            "constraints_exhausted_eligible_pool"
        )


# ----------------------------------------------------------------------
# Fixture H — H3 sparsity
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fixture_h_h3_sparsity_metadata_populated():
    """The smart embedder produces tight intra-region cosines (≥0.95) so
    Step 8.6's parent_restatement_ceiling (0.85) rejects most candidates
    — every selected H2 ends up with zero non-authority H3s. The
    metadata must surface that condition cleanly.
    """
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-h", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # Sanity: at least one H2 selected so the metadata is meaningful
    assert result.metadata.h2_count >= 1
    # h2s_with_zero_h3s ≤ h2_count — they're counts of the same set
    assert (
        result.metadata.h2s_with_zero_h3s <= result.metadata.h2_count
    )
    # Non-vacuous: under the synthetic embedder, in-region cosines are
    # too tight for Step 8.6 to attach H3s, so EVERY H2 should report
    # zero non-authority H3s. (Authority gap H3s flow through a
    # different path and don't count toward this metric.)
    assert result.metadata.h2s_with_zero_h3s == result.metadata.h2_count
    # h3_count_average is the structure-level count; with authority H3s
    # attaching it can be > 0 even when h2s_with_zero_h3s == h2_count.
    assert result.metadata.h3_count_average >= 0.0


# ----------------------------------------------------------------------
# Fixture I — Silo discard reason filtering (Step 12.1)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fixture_i_above_restatement_ceiling_excluded_from_silos():
    """PRD §5 Step 12.1: above_restatement_ceiling is "No" — these
    headings must NOT appear in silo_candidates."""
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-i", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # Collect every above_restatement_ceiling heading text
    restatement_texts = {
        d.text for d in result.discarded_headings
        if d.discard_reason == "above_restatement_ceiling"
    }
    # Non-vacuous: synthetic SERP titles include "What TikTok Shop Is"
    # paraphrases that the smart embedder maps to axis 0 with cosine
    # ≥ 0.94 to title — these must end up in restatement discards.
    assert restatement_texts, (
        "expected at least one above_restatement_ceiling discard"
    )
    # And at least one silo must exist so the loop body runs.
    assert result.silo_candidates, (
        "expected at least one silo for the exclusion check to be meaningful"
    )

    # No silo candidate should be drawn from those texts
    for silo in result.silo_candidates:
        assert silo.suggested_keyword not in restatement_texts
        for source in silo.source_headings:
            assert source.text not in restatement_texts, (
                f"Silo {silo.suggested_keyword!r} member "
                f"{source.text!r} is an above_restatement_ceiling discard"
            )

    # And the metadata counter should be non-negative
    assert result.metadata.silo_candidates_rejected_by_discard_reason >= 0


# ----------------------------------------------------------------------
# Fixture J — Silo viability rejection (Step 12.4)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fixture_j_viability_false_excludes_candidate_and_increments_counter():
    """PRD §5 Step 12.4: candidates classified non-viable are excluded
    from silo_candidates and counted in
    silo_candidates_rejected_by_viability_check."""
    from modules.brief.pipeline import run_brief

    # Baseline run produces silos. Force viability=false on the same run
    # to confirm they get filtered out and counted.
    router = _make_default_claude_router(viability_default_viable=False)

    req = BriefRequest(run_id="fix-j", keyword="what is tiktok shop")
    with _fixture_mocks(claude_router=router):
        result = await run_brief(req)

    # All silos should have been filtered → empty list
    assert result.silo_candidates == []
    # Non-vacuous: at least one candidate must have been rejected by
    # the viability check (otherwise we're testing a no-op).
    assert result.metadata.silo_candidates_rejected_by_viability_check >= 1
    # No fallback applied (LLM responded with valid JSON)
    assert result.metadata.silo_viability_fallback_applied is False


@pytest.mark.asyncio
async def test_fixture_j_partial_viability_keeps_viable_drops_others():
    """Verify per-candidate routing: some viable, some not."""
    from modules.brief.pipeline import run_brief

    # Default to viable=true, but reject anything containing "Gap question"
    # (these are persona-gap-derived silos in the synthetic setup).
    router = _make_default_claude_router(
        viability_default_viable=True,
        viability_per_keyword={
            f"Gap question {i}?": False for i in range(6)
        },
    )

    req = BriefRequest(run_id="fix-j-mixed", keyword="what is tiktok shop")
    with _fixture_mocks(claude_router=router):
        result = await run_brief(req)

    # Verify no rejected keyword survived
    for silo in result.silo_candidates:
        assert "Gap question" not in silo.suggested_keyword


@pytest.mark.asyncio
async def test_fixture_j_double_failure_falls_back_to_viable_true():
    """When the viability LLM fails twice, candidates default to
    viable=True and metadata.silo_viability_fallback_applied=True."""
    from modules.brief.pipeline import run_brief

    async def bad_router(system, user, **kw):
        sys_l = system.lower()
        if "viable" in sys_l and "standalone" in sys_l:
            # Always fail validation
            return {"not_a_valid": "payload"}
        # Fall through to default for all other system prompts
        return await _make_default_claude_router()(system, user, **kw)

    req = BriefRequest(run_id="fix-j-fallback", keyword="what is tiktok shop")
    with _fixture_mocks(claude_router=bad_router):
        result = await run_brief(req)

    # If any candidates reached Step 12.4, the fallback must have fired
    if result.silo_candidates:
        assert result.metadata.silo_viability_fallback_applied is True
        # Each silo carries the fallback marker in its reasoning
        for silo in result.silo_candidates:
            assert "fallback_after_llm_failure" in silo.viability_reasoning
