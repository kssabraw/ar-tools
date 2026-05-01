"""Integration tests for the v2.0 Brief Generator orchestrator.

Mocks every external call (DataForSEO, Anthropic, OpenAI, Supabase). Verifies
the pipeline produces a schema-valid BriefResponse and runs the v2 flow:
title/scope → graph → persona → MMR → scope verification → silos.

The tests pin contract properties (schema version, presence of regions,
threshold echo, persona persistence) without asserting tight numerical
counts that could drift with mock-data tweaks.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from models.brief import BriefRequest


# ----------------------------------------------------------------------
# Synthetic data
# ----------------------------------------------------------------------

# Twenty organic SERP rows that produce enough headings to drive Steps 4 / 5.
SERP_ITEMS: list[dict] = []
for i in range(20):
    SERP_ITEMS.append({
        "type": "organic",
        "rank_absolute": i + 1,
        "rank_group": i + 1,
        "url": f"https://site{i}.example.com/article",
        "title": f"What TikTok Shop Is and How It Works — Article {i}",
        "description": (
            f"Overview of TikTok Shop selling for new creators (variant {i}). "
            "How it works:\nSetup process for sellers:\nFees structure:"
        ),
    })
SERP_ITEMS.append({
    "type": "people_also_ask",
    "items": [
        {"title": "How does TikTok Shop work for sellers?"},
        {"title": "Is TikTok Shop worth it for small businesses?"},
        {"title": "How much does TikTok Shop charge in fees?"},
    ],
})
SERP_ITEMS.append({"type": "featured_snippet", "title": "TikTok Shop"})


REDDIT_ITEMS = [
    {"title": "Has anyone actually made money on TikTok Shop?",
     "description": "Curious if it's worth setting up an account."},
    {"title": "TikTok Shop fees explained",
     "description": "Are the seller fees actually transparent?"},
]


# ----------------------------------------------------------------------
# Mocks
# ----------------------------------------------------------------------

def _normalized_vec(text: str, dim: int = 16) -> list[float]:
    """Deterministic synthetic embedding — mostly along axis 0 for any text
    containing 'tiktok shop' so cosine to title is high."""
    vec = [0.0] * dim
    seed = sum(ord(c) for c in text)
    for i in range(dim):
        vec[i] = ((seed + i * 17) % 13) / 13.0
    # Bias toward axis 0 for in-topic text
    if "tiktok shop" in text.lower() or text.lower() == "what is tiktok shop":
        vec[0] += 1.5
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def fake_serp_organic(*args, **kwargs):
    return {"task": {}, "items": SERP_ITEMS}


async def fake_serp_reddit(*args, **kwargs):
    return REDDIT_ITEMS


async def fake_autocomplete(*args, **kwargs):
    return ["tiktok shop how it works", "tiktok shop fees", "tiktok shop setup"]


async def fake_keyword_suggestions(*args, **kwargs):
    return ["tiktok shop guide", "tiktok shop tutorial"]


async def fake_llm_response(*args, **kwargs):
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


async def fake_embed_batch_large(texts, normalize=True):
    return [_normalized_vec(t) for t in texts]


async def fake_claude_json(system: str, user: str, **kwargs):
    """Route Anthropic calls by uniquely identifying phrases in each
    prompt. Ordering matters — most specific matches first.

    Each step's SYSTEM_PROMPT is grep'd for a phrase that appears nowhere
    else; this lets the mock disambiguate without false positives between
    sibling steps that share generic vocabulary like "title" or "scope".
    """
    sys_l = system.lower()

    # title_scope: "you generate the article title and scope statement"
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

    # persona: "you profile the hypothetical searcher"
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

    # scope_verification: "you verify that each candidate h2 heading"
    if "verify that each candidate" in sys_l:
        # Mark every H2 from the user message in_scope.
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

    # authority gap: "you are the universal authority agent"
    if "universal authority agent" in sys_l:
        return {"headings": [
            "Common cognitive biases that derail TikTok Shop sellers",
            "Tax and consumer-protection rules sellers must follow",
            "How TikTok Shop's algorithm shifts seller economics over years",
        ]}

    # how-to reorder: "organizing how-to tutorial steps"
    if "tutorial steps" in sys_l:
        return {"order": list(range(20))}  # large enough for any pool size

    # intent borderline_ecom_check: "you classify search intent"
    if "classify search intent" in sys_l:
        return {"intent": "informational"}

    # FAQ llm_concern_extraction: "extract up to 10 distinct implicit questions"
    if "implicit questions" in sys_l:
        return {"questions": [
            "How long does TikTok Shop take to approve a seller application?",
            "What payment methods does TikTok Shop support for sellers?",
        ]}

    # Subtopic extraction: "extract all distinct subtopics"
    if "extract all distinct subtopics" in sys_l:
        return ["Setup process", "Seller fees", "Payment methods"]

    return {}


async def fake_get_cached(*args, **kwargs):
    return None


async def fake_write_cache(*args, **kwargs):
    return None


# ----------------------------------------------------------------------
# Patch context
# ----------------------------------------------------------------------

class _AllMocks:
    """Convenience container that patches every external call needed by
    the orchestrator. Used as a single nested with-block per test."""

    def __init__(self):
        self.patches = [
            patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", fake_serp_organic),
            patch("modules.brief.pipeline.dataforseo.serp_reddit", fake_serp_reddit),
            patch("modules.brief.pipeline.dataforseo.autocomplete", fake_autocomplete),
            patch("modules.brief.pipeline.dataforseo.keyword_suggestions", fake_keyword_suggestions),
            patch("modules.brief.pipeline.dataforseo.llm_response", fake_llm_response),
            patch("modules.brief.pipeline.embed_batch_large", fake_embed_batch_large),
            patch("modules.brief.pipeline.claude_json", fake_claude_json),
            # The submodules each import claude_json / embed_batch_large
            # directly; patch those bindings too so the same mock is hit.
            patch("modules.brief.title_scope.claude_json", fake_claude_json),
            patch("modules.brief.persona.claude_json", fake_claude_json),
            patch("modules.brief.scope_verification.claude_json", fake_claude_json),
            patch("modules.brief.authority.claude_json", fake_claude_json),
            patch("modules.brief.assembly.claude_json", fake_claude_json),
            patch("modules.brief.faqs.claude_json", fake_claude_json),
            patch("modules.brief.faqs.embed_batch_large", fake_embed_batch_large),
            patch("modules.brief.graph.embed_batch_large", fake_embed_batch_large),
            patch("modules.brief.intent.claude_json", fake_claude_json),
            patch("modules.brief.pipeline.get_cached", fake_get_cached),
            patch("modules.brief.pipeline.write_cache", fake_write_cache),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()


# ----------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_produces_schema_v2_response():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="t1", keyword="what is tiktok shop")

    with _AllMocks():
        result = await run_brief(req)

    # ---- Schema contract ----
    assert result.metadata.schema_version == "2.0"
    assert result.metadata.embedding_model == "text-embedding-3-large"

    # ---- Step 3.5 outputs surface on the response ----
    assert result.title.startswith("What TikTok Shop Is")
    assert "does not cover" in result.scope_statement.lower()
    assert result.title_rationale  # non-empty

    # ---- Step 6 persona is captured ----
    assert "small-business owner" in result.persona.description
    assert len(result.persona.background_assumptions) >= 1
    assert result.persona.primary_goal


@pytest.mark.asyncio
async def test_pipeline_produces_h1_h2_outline():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="t2", keyword="what is tiktok shop")
    with _AllMocks():
        result = await run_brief(req)

    levels = [h.level for h in result.heading_structure]
    assert levels[0] == "H1"
    assert result.heading_structure[0].text == "what is tiktok shop"
    # At least one H2
    assert "H2" in levels
    # Order numbers are sequential
    orders = [h.order for h in result.heading_structure]
    assert orders == sorted(orders)


@pytest.mark.asyncio
async def test_pipeline_metadata_threshold_echo():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="t3", keyword="what is tiktok shop")
    with _AllMocks():
        result = await run_brief(req)

    m = result.metadata
    assert m.relevance_floor_threshold == 0.55
    assert m.restatement_ceiling_threshold == 0.78
    assert m.inter_heading_threshold == 0.75
    assert m.edge_threshold == 0.65
    assert m.mmr_lambda == 0.7
    # Region detection ran
    assert m.regions_detected >= 1


@pytest.mark.asyncio
async def test_pipeline_competitor_domains_populated():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="t4", keyword="what is tiktok shop")
    with _AllMocks():
        result = await run_brief(req)

    assert len(result.metadata.competitor_domains) > 0
    assert all("." in d for d in result.metadata.competitor_domains)


@pytest.mark.asyncio
async def test_pipeline_h2_headings_carry_v2_fields():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="t5", keyword="what is tiktok shop")
    with _AllMocks():
        result = await run_brief(req)

    h2s = [h for h in result.heading_structure if h.level == "H2" and h.type == "content"]
    assert h2s, "expected at least one content H2"
    for h in h2s:
        # Step 5 wrote title_relevance
        assert h.title_relevance >= 0.0
        # Step 5 wrote region_id
        assert h.region_id is not None
        # Step 8.5 wrote scope_classification
        assert h.scope_classification in ("in_scope", "borderline")


# ----------------------------------------------------------------------
# Cache integration
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_short_circuits_pipeline():
    from modules.brief.pipeline import run_brief

    cached_payload = {
        "keyword": "what is tiktok shop",
        "title": "Cached Title for TikTok Shop",
        "scope_statement": "Cached scope. Does not cover X.",
        "title_rationale": "cached rationale",
        "intent_type": "informational",
        "intent_confidence": 0.9,
        "intent_review_required": False,
        "persona": {
            "description": "cached persona",
            "background_assumptions": [],
            "primary_goal": "cached",
        },
        "heading_structure": [],
        "faqs": [],
        "structural_constants": {
            "conclusion": {"type": "conclusion", "text": "[Conclusion placeholder]"}
        },
        "format_directives": {
            "require_bulleted_lists": True,
            "require_tables": True,
            "min_lists_per_article": 2,
            "min_tables_per_article": 1,
            "preferred_paragraph_max_words": 80,
            "answer_first_paragraphs": True,
        },
        "discarded_headings": [],
        "silo_candidates": [],
        "metadata": {
            "schema_version": "2.0",
            "word_budget": 2500,
            "faq_count": 0,
            "h2_count": 0,
            "h3_count": 0,
            "total_content_subheadings": 0,
            "discarded_headings_count": 0,
            "silo_candidates_count": 0,
            "competitors_analyzed": 20,
            "reddit_threads_analyzed": 0,
            "h2_shortfall": False,
            "h2_shortfall_reason": None,
            "regions_detected": 0,
            "regions_eliminated_off_topic": 0,
            "regions_eliminated_restate_title": 0,
            "regions_contributing_h2s": 0,
            "scope_verification_borderline_count": 0,
            "scope_verification_rejected_count": 0,
            "llm_fanout_queries_captured": {"chatgpt": 0, "claude": 0, "gemini": 0, "perplexity": 0},
            "llm_response_subtopics_extracted": {"chatgpt": 0, "claude": 0, "gemini": 0, "perplexity": 0},
            "intent_signals": {"shopping_box": False, "news_box": False, "local_pack": False, "featured_snippet": False, "comparison_tables": False},
            "embedding_model": "text-embedding-3-large",
            "relevance_floor_threshold": 0.55,
            "restatement_ceiling_threshold": 0.78,
            "inter_heading_threshold": 0.75,
            "edge_threshold": 0.65,
            "mmr_lambda": 0.7,
            "low_serp_coverage": False,
            "reddit_unavailable": False,
            "llm_fanout_unavailable": {"chatgpt": False, "claude": False, "gemini": False, "perplexity": False},
            "competitor_domains": [],
        },
    }

    serp_called = {"hit": False}

    async def boom_serp(*a, **k):
        serp_called["hit"] = True
        raise AssertionError("must not call SERP on cache hit")

    async def cache_hit(*a, **k):
        return cached_payload

    req = BriefRequest(run_id="cache-hit", keyword="what is tiktok shop")
    with (
        patch("modules.brief.pipeline.get_cached", cache_hit),
        patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", boom_serp),
    ):
        result = await run_brief(req)

    assert serp_called["hit"] is False
    assert result.title == "Cached Title for TikTok Shop"


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache():
    from modules.brief.pipeline import run_brief

    cache_called = {"hit": False}

    async def hit(*a, **k):
        cache_called["hit"] = True
        return None

    req = BriefRequest(
        run_id="force",
        keyword="what is tiktok shop",
        force_refresh=True,
    )
    with _AllMocks(), patch("modules.brief.pipeline.get_cached", hit):
        await run_brief(req)

    assert cache_called["hit"] is False


@pytest.mark.asyncio
async def test_pipeline_writes_to_cache_after_generation():
    from modules.brief.pipeline import run_brief

    write_called = {"hit": False, "args": None}

    async def write(**kwargs):
        write_called["hit"] = True
        write_called["args"] = kwargs

    req = BriefRequest(
        run_id="cache-write",
        keyword="what is tiktok shop",
        client_id="client-uuid-123",
    )
    with _AllMocks(), patch("modules.brief.pipeline.write_cache", write):
        await run_brief(req)

    assert write_called["hit"] is True
    args = write_called["args"]
    assert args["keyword"] == "what is tiktok shop"
    assert args["location_code"] == 2840
    assert args["schema_version"] == "2.0"
    assert args["triggered_by_client_id"] == "client-uuid-123"
    assert args["duration_ms"] >= 0


# ----------------------------------------------------------------------
# Failure modes
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_raises_on_empty_serp():
    from modules.brief.errors import BriefError
    from modules.brief.pipeline import run_brief

    async def empty_serp(*a, **k):
        return {"task": {}, "items": []}

    req = BriefRequest(run_id="empty", keyword="what is tiktok shop")
    with (
        _AllMocks(),
        patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", empty_serp),
    ):
        with pytest.raises(BriefError) as ei:
            await run_brief(req)
    assert ei.value.code == "serp_no_results"


@pytest.mark.asyncio
async def test_pipeline_validation_error_on_empty_keyword():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BriefRequest(run_id="x", keyword="")
