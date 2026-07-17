"""Unit tests for the ecommerce Max-Cosine Synthesis module.

Pure + offline: spaCy is optional (the module falls back to a regex noun-phrase
extractor), and every embedding is a deterministic injected fake. Run with
`pytest writer/nlp-api/tests/` or `python -m pytest`.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ecommerce_mcs as mcs  # noqa: E402


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Phase 1: extract_aio ---------------------------------------------------

def test_extract_aio_markdown_and_refs():
    items = [
        {"type": "organic", "url": "https://x.com"},
        {
            "type": "ai_overview",
            "markdown": "Angel number 327 encourages positive transformation.",
            "references": [{"domain": "Healthline.com"}, {"domain": "example.com"}],
            "items": [{"type": "ai_overview_element", "title": "What does 327 mean?"}],
        },
    ]
    aio = mcs.extract_aio(items)
    assert aio["present"] is True
    assert "transformation" in aio["text"]
    assert aio["sources"] == ["healthline.com", "example.com"]
    assert aio["fanout"] == ["What does 327 mean?"]
    assert aio["asynchronous"] is False


def test_extract_aio_subitem_text_and_nested_refs():
    items = [{
        "type": "ai_overview",
        "items": [
            {"type": "ai_overview_element", "text": "Trail running shoes grip loose terrain."},
            {"type": "ai_overview_reference", "domain": "rei.com"},
        ],
        "asynchronous_ai_overview": True,
    }]
    aio = mcs.extract_aio(items)
    assert aio["present"] is True
    assert "grip loose terrain" in aio["text"]
    assert aio["sources"] == ["rei.com"]
    assert aio["asynchronous"] is True


def test_extract_aio_absent():
    assert mcs.extract_aio([{"type": "organic"}])["present"] is False
    assert mcs.extract_aio([])["present"] is False


# --- Phase 2: entity derivation --------------------------------------------

def test_pdp_keeps_input_entity_even_when_aio_is_generic():
    # AIO drifts to the generic category; PDP must NOT adopt it.
    aio = ("Trail running shoes are lightweight shoes for off-road running. "
           "Trail running shoes have aggressive lugs. Trail running shoes protect the foot.")
    ent = run(mcs.derive_main_entity(
        page_type="product", input_entity="Acme Trail Runner",
        primary_keyword="acme trail runner", aio_text=aio,
    ))
    assert ent.canonical == "Acme Trail Runner"
    assert ent.source == "input_pdp"
    assert ent.emq_identical is True


def test_pdp_absorbs_superset_variant_only():
    aio = ("The Acme Trail Runner shoe is built for wet rock. "
           "The Acme Trail Runner shoe uses Vibram. Generic sandals are different.")
    ent = run(mcs.derive_main_entity(
        page_type="product", input_entity="Acme Trail Runner",
        primary_keyword="acme trail runner shoe", aio_text=aio,
    ))
    assert ent.canonical == "Acme Trail Runner"
    # A superset surface ("acme trail runner shoe") may be offered as a variant;
    # an unrelated/generic noun phrase ("sandals") must never appear.
    assert all("acme trail runner" in v.lower() for v in ent.variants)
    assert ent.emq_identical is False


def test_plp_adopts_aio_entity_above_floor():
    # Input category and AIO agree closely → adopt AIO surface form.
    aio = ("Trail running shoes are grippy off-road shoes. Trail running shoes "
           "resist mud. Trail running shoes suit ultra runners. Trail running shoes last long.")
    ent = run(mcs.derive_main_entity(
        page_type="collection", input_entity="trail running shoes",
        primary_keyword="best trail running shoes", aio_text=aio,
    ))
    assert "trail running shoe" in ent.canonical.lower()
    assert ent.source == "aio"


def test_plp_falls_back_when_aio_drifts_off_category():
    # AIO is about something unrelated to the input category → keep input.
    aio = ("Kitchen blenders crush ice. Kitchen blenders have powerful motors. "
           "Kitchen blenders make smoothies. Kitchen blenders vary in wattage.")
    ent = run(mcs.derive_main_entity(
        page_type="collection", input_entity="trail running shoes",
        primary_keyword="trail running shoes", aio_text=aio,
    ))
    assert ent.canonical == "trail running shoes"
    assert ent.source == "input_fallback"


def test_no_aio_returns_input_fallback():
    ent = run(mcs.derive_main_entity(
        page_type="collection", input_entity="garden hoses",
        primary_keyword="garden hoses", aio_text="",
    ))
    assert ent.canonical == "garden hoses"
    assert ent.source == "input_fallback"


def test_plp_floor_uses_injected_embedder():
    # Fake embedder makes the winner far from the input → fall back despite freq.
    async def far_embed(texts):
        return [[1.0, 0.0] if i == 0 else [0.0, 1.0] for i, _ in enumerate(texts)]

    aio = ("Widget alpha is fast. Widget alpha is cheap. Widget alpha is light. Widget alpha ships free.")
    ent = run(mcs.derive_main_entity(
        page_type="collection", input_entity="widget alpha",
        primary_keyword="widget alpha", aio_text=aio, embed_fn=far_embed,
    ))
    assert ent.source == "input_fallback"


# --- Phase 3: fact parsing --------------------------------------------------

def test_parse_facts_json():
    raw = '["grips wet rock", "fits true to size", "grips wet rock"]'
    assert mcs.parse_facts(raw) == ["grips wet rock", "fits true to size"]


def test_parse_facts_fenced_and_limit():
    raw = "```json\n[\"a fact\", \"b fact\", \"c fact\"]\n```"
    assert mcs.parse_facts(raw, limit=2) == ["a fact", "b fact"]


def test_parse_facts_line_fallback():
    raw = "- grips wet rock\n- fits true to size\n"
    assert mcs.parse_facts(raw) == ["grips wet rock", "fits true to size"]


def test_build_fact_messages_contains_entity_and_answer():
    system, user = mcs.build_fact_extraction_messages("The answer text.", "Acme Runner")
    assert "JSON array" in system
    assert "Acme Runner" in user and "The answer text." in user


# --- Phase 4: synthesis -----------------------------------------------------

def test_build_candidate_headings_dedup_and_no_double_entity():
    cands = mcs.build_candidate_headings("Acme Runner", [
        "grips wet rock", "Acme Runner fits wide feet", "grips wet rock.",
    ])
    assert "Acme Runner grips wet rock" in cands
    assert "Acme Runner fits wide feet" in cands  # not doubled
    assert len(cands) == 2  # the duplicate "grips wet rock." collapses


def test_cosine_basic():
    assert mcs.cosine([1, 0], [1, 0]) == 1.0
    assert mcs.cosine([1, 0], [0, 1]) == 0.0
    assert mcs.cosine([], [1]) == 0.0


def test_synthesize_greedy_selection_and_near_dup_skip():
    # answer=[1,0]. `a` is closest; `c` is a near-dup of `a` (must be skipped);
    # `b` and `d` are distinct and kept. top_k=3 → [a, b, d].
    space = {
        "ANSWER": [1.0, 0.0],
        "E fact a": [0.995, 0.10],
        "E fact b": [0.80, 0.60],
        "E fact c": [0.99, 0.14],    # near-dup of "E fact a"
        "E fact d": [0.0, 1.0],
    }

    async def fake_embed(texts):
        return [space["ANSWER"] if t == "ANSWER" else space[t] for t in texts]

    kept = run(mcs.synthesize_headings(
        aio_text="ANSWER", entity="E", facts=["fact a", "fact b", "fact c", "fact d"],
        embed_fn=fake_embed, candidates=list(space.keys())[1:], top_k=3,
    ))
    headings = [k.heading for k in kept]
    assert headings == ["E fact a", "E fact b", "E fact d"]
    assert "E fact c" not in headings          # dropped as near-duplicate of a
    assert [k.cosine for k in kept] == sorted((k.cosine for k in kept), reverse=True)


def test_synthesize_empty_without_answer():
    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]
    assert run(mcs.synthesize_headings(
        aio_text="", entity="E", facts=["x"], embed_fn=fake_embed)) == []


# --- Prompt block -----------------------------------------------------------

def test_prompt_block_empty_without_signal():
    ent = mcs.MCSEntity(canonical="garden hoses", source="input_fallback")
    assert mcs.build_mcs_prompt_block(ent, facts=[]) == ""


def test_prompt_block_with_facts_and_entity():
    ent = mcs.MCSEntity(canonical="Acme Runner", variants=["Acme Runner shoe"],
                        source="input_pdp", emq_identical=True)
    block = mcs.build_mcs_prompt_block(ent, facts=["grips wet rock", "fits wide feet"])
    assert "Acme Runner" in block
    assert "grips wet rock" in block
    assert "EMQ out of subheadings" in block


def test_prompt_block_prefers_synthesized_headings():
    ent = mcs.MCSEntity(canonical="Acme Runner", source="aio")
    synth = [mcs.ScoredHeading("Acme Runner grips wet rock", 0.94)]
    block = mcs.build_mcs_prompt_block(ent, facts=["grips wet rock"], synthesized=synth)
    assert "Acme Runner grips wet rock" in block
    assert "max-cosine heading targets" in block


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
