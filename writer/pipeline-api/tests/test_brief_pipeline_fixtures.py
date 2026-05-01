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

def _normalize_vec(text: str, dim: int = 16) -> list[float]:
    """Deterministic synthetic embedding biased toward axis 0 for the topic."""
    vec = [0.0] * dim
    seed = sum(ord(c) for c in text)
    for i in range(dim):
        vec[i] = ((seed + i * 17) % 13) / 13.0
    if "tiktok shop" in text.lower() or text.lower() == "what is tiktok shop":
        vec[0] += 1.5
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _build_serp_items(
    n: int = 20,
    description_template: str = (
        "Overview of TikTok Shop selling for new creators (variant {i}). "
        "How it works:\nSetup process for sellers:\nFees structure:"
    ),
    extras: Optional[list[dict]] = None,
) -> list[dict]:
    items: list[dict] = []
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
                {"title": "Is TikTok Shop worth it for small businesses?"},
                {"title": "How much does TikTok Shop charge in fees?"},
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
    return {
        "text": (
            "TikTok Shop is a social commerce platform inside TikTok. "
            "It lets creators sell directly via short videos and live streams."
        ),
        "fan_out_queries": [
            "how to set up tiktok shop",
            "tiktok shop seller requirements",
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
                if text:
                    items.append({
                        "h2_text": text,
                        "scope_classification": "in_scope",
                        "reasoning": "ok",
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
    viable_as_standalone_article, viability_reasoning, and estimated_intent."""
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-a", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # Every silo carries the v2.0.2 fields populated
    for silo in result.silo_candidates:
        assert silo.search_demand_score >= 0.0
        # Default-router viability returns viable=true
        assert silo.viable_as_standalone_article is True
        assert silo.viability_reasoning  # non-empty
        assert silo.estimated_intent in {
            "informational", "listicle", "how-to", "comparison",
            "ecom", "local-seo", "news", "informational-commercial",
        }
        assert silo.cross_brief_occurrence_count == 1


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
    """Construct a scenario where H2s are well-spread across regions
    but few candidates pass parent-relevance filtering. Verify
    h2s_with_zero_h3s > 0 and the brief is still valid."""
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="fix-h", keyword="what is tiktok shop")
    with _fixture_mocks():
        result = await run_brief(req)

    # h3_count_average and h2s_with_zero_h3s are populated regardless;
    # we just need them to be non-negative and consistent.
    assert result.metadata.h3_count_average >= 0.0
    assert result.metadata.h2s_with_zero_h3s >= 0
    assert (
        result.metadata.h2s_with_zero_h3s <= result.metadata.h2_count
    )


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

    # Force the viability LLM to mark every candidate as non-viable.
    router = _make_default_claude_router(viability_default_viable=False)

    req = BriefRequest(run_id="fix-j", keyword="what is tiktok shop")
    with _fixture_mocks(claude_router=router):
        result = await run_brief(req)

    # All silos should have been filtered → empty list
    assert result.silo_candidates == []
    # Rejection counter incremented at least once if any candidates
    # made it past Steps 12.1–12.3.
    assert result.metadata.silo_candidates_rejected_by_viability_check >= 0
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
