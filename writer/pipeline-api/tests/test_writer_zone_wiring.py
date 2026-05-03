"""Writer-side SIE v1.4 zone × category wiring tests.

Covers the three-bucket aggregate flow (entities / related_keywords /
keyword_variants) wired through:
  - generate_title (title-zone targets)
  - generate_h1_enrichment (h1-zone targets)
  - write_faqs (paragraphs-zone aggregate scaled to FAQ-zone)
  - optimize_headings (h2 + h3 = subheadings aggregate)

Plus the SIE benchmark math (`build_zone_category_targets`) — trimmed-
max competitor counts × 0.50, with outlier exclusion in safe mode.
"""

from __future__ import annotations

import pytest

from modules.sie.usage import (
    CATEGORY_ENTITIES,
    CATEGORY_KEYWORD_VARIANTS,
    CATEGORY_RELATED_KEYWORDS,
    ZONE_CATEGORY_TARGET_MULT,
    _classify_term,
    build_zone_category_targets,
)
from modules.sie.zones import PageZones
from modules.writer.faqs import (
    _derive_faq_category_targets,
    _scale_paragraphs_target,
    write_faqs,
)
from modules.writer.heading_seo_optimizer import optimize_headings
from modules.writer.reconciliation import (
    FilteredSIETerms,
    ReconciledTerm,
)
from modules.writer.title import generate_h1_enrichment, generate_title


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capturing_json(response):
    captured = {}

    async def _call(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        return response

    return _call, captured


# ---------------------------------------------------------------------------
# SIE benchmark — _classify_term
# ---------------------------------------------------------------------------


def test_classify_entity_takes_precedence_over_seed_fragment():
    """If a term is somehow flagged as both entity and seed-fragment
    (upstream invariant break), entity wins."""
    cat = _classify_term(
        "tiktok shop",
        entity_meta={"tiktok shop": {"is_entity": True}},
        seed_fragment_terms={"tiktok shop"},
    )
    assert cat == CATEGORY_ENTITIES


def test_classify_seed_fragment_when_not_entity():
    cat = _classify_term(
        "how to",
        entity_meta={},
        seed_fragment_terms={"how to"},
    )
    assert cat == CATEGORY_KEYWORD_VARIANTS


def test_classify_default_related_keyword():
    cat = _classify_term(
        "social commerce",
        entity_meta={},
        seed_fragment_terms=set(),
    )
    assert cat == CATEGORY_RELATED_KEYWORDS


# ---------------------------------------------------------------------------
# SIE benchmark — build_zone_category_targets
# ---------------------------------------------------------------------------


def _page_with_paragraphs(url: str, paragraphs: list[str], word_count: int = 1000) -> PageZones:
    p = PageZones(url=url, word_count=word_count)
    p.paragraphs = paragraphs
    return p


def test_zone_category_target_is_half_of_trimmed_max():
    """3 competitors mention 4, 4, 4 distinct entities in body. Trimmed
    max = 4. Target = round(4 × 0.50) = 2."""
    # All four entities present in each page → distinct count = 4 per page.
    pages = [
        _page_with_paragraphs(f"https://t.com/{i}", [
            "Discussion of TikTok Shop, Checkout Flow, Conversion Rate, GMV Max."
        ])
        for i in range(3)
    ]
    aggregates = {
        "tiktok shop": object(),
        "checkout flow": object(),
        "conversion rate": object(),
        "gmv max": object(),
    }
    entity_meta = {
        t: {"is_entity": True, "entity_category": "concepts"}
        for t in aggregates
    }
    out = build_zone_category_targets(
        aggregates=aggregates, pages=pages,
        entity_meta=entity_meta, seed_fragment_terms=set(),
        outlier_mode="safe",
    )
    assert out["paragraphs"]["entities"]["max"] == 4
    assert out["paragraphs"]["entities"]["target"] == 2


def test_zone_category_target_excludes_outlier_in_safe_mode():
    """A page with distinct count ≥ 3× median is treated as an outlier
    in safe mode and dropped from the trimmed-max calculation."""
    # Pages 0-3: 1 distinct entity each (just "tiktok shop")
    pages = [
        _page_with_paragraphs(f"https://t.com/{i}", [
            "Discussion of TikTok Shop only."
        ])
        for i in range(4)
    ]
    # Outlier page: 4 distinct entities (4 >= 3 × median of 1).
    pages.append(_page_with_paragraphs("https://t.com/outlier", [
        "TikTok Shop, Checkout Flow, Conversion Rate, GMV Max all packed in.",
    ]))
    aggregates = {
        "tiktok shop": object(),
        "checkout flow": object(),
        "conversion rate": object(),
        "gmv max": object(),
    }
    entity_meta = {t: {"is_entity": True} for t in aggregates}

    safe = build_zone_category_targets(
        aggregates=aggregates, pages=pages,
        entity_meta=entity_meta, seed_fragment_terms=set(),
        outlier_mode="safe",
    )
    aggressive = build_zone_category_targets(
        aggregates=aggregates, pages=pages,
        entity_meta=entity_meta, seed_fragment_terms=set(),
        outlier_mode="aggressive",
    )
    # Safe mode drops the outlier — trimmed max becomes 1.
    assert safe["paragraphs"]["entities"]["max"] == 1
    # Aggressive keeps the outlier — max stays 4.
    assert aggressive["paragraphs"]["entities"]["max"] == 4


def test_zone_category_target_buckets_three_categories():
    """Pages contain a mix: one entity, one related keyword, one variant
    each. Each bucket should get max=1, target=1 (or 0 — round depends
    on multiplier)."""
    pages = [
        _page_with_paragraphs(f"https://t.com/{i}", [
            "TikTok Shop sellers face checkout flow drop-off when ROI dips below benchmarks."
        ])
        for i in range(3)
    ]
    aggregates = {
        "tiktok shop": object(),       # entity
        "checkout flow": object(),     # related keyword
        "roi": object(),               # seed fragment (variant)
    }
    entity_meta = {"tiktok shop": {"is_entity": True}}
    seed_fragments = {"roi"}

    out = build_zone_category_targets(
        aggregates=aggregates, pages=pages,
        entity_meta=entity_meta, seed_fragment_terms=seed_fragments,
        outlier_mode="safe",
    )
    # Each category appears in every page = max 1 across pages.
    assert out["paragraphs"]["entities"]["max"] == 1
    assert out["paragraphs"]["related_keywords"]["max"] == 1
    assert out["paragraphs"]["keyword_variants"]["max"] == 1
    # 1 × 0.50 → round → 0 or 1 depending on Python rounding; assert
    # the formula directly so we don't depend on banker's rounding.
    expected = int(round(1 * ZONE_CATEGORY_TARGET_MULT))
    assert out["paragraphs"]["entities"]["target"] == expected


def test_zone_category_target_zero_when_no_pages():
    out = build_zone_category_targets(
        aggregates={"x": object()}, pages=[],
        entity_meta={}, seed_fragment_terms=set(),
        outlier_mode="safe",
    )
    assert out["paragraphs"]["entities"] == {"target": 0, "max": 0}


def test_zone_category_target_consumes_shared_scan():
    """When the caller passes a pre-built zone_count_by_term_and_url
    map, build_zone_category_targets must use it instead of re-scanning.
    We verify by passing a map that contradicts the page text (terms
    flagged present in pages where they don't textually appear) — if
    the function honors the map the result reflects the map; if it
    re-scans we'd see the empty pages and produce zero counts."""
    pages = [
        _page_with_paragraphs(f"https://t.com/{i}", ["completely unrelated text"])
        for i in range(3)
    ]
    aggregates = {"phantom": object()}
    entity_meta = {"phantom": {"is_entity": True}}
    fake_scan = {
        "phantom": {
            "paragraphs": {p.url: 5 for p in pages},  # Pretend present everywhere.
        }
    }
    out = build_zone_category_targets(
        aggregates=aggregates, pages=pages,
        entity_meta=entity_meta, seed_fragment_terms=set(),
        outlier_mode="safe",
        zone_count_by_term_and_url=fake_scan,
    )
    # If the shared map were ignored the substring scan would find
    # nothing and we'd get max=0; honoring it produces max=1.
    assert out["paragraphs"]["entities"]["max"] == 1


# ---------------------------------------------------------------------------
# Title-zone wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_title_lists_three_categories(monkeypatch):
    call, captured = _capturing_json({"candidates": ["A: TikTok Shop ROI Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    title = await generate_title(
        keyword="tiktok shop roi",
        intent_type="how-to",
        entities=["TikTok Shop", "Checkout Flow"],
        related_keywords=["social commerce"],
        keyword_variants=["roi"],
        title_targets={
            "entities": 2, "related_keywords": 1, "keyword_variants": 1,
        },
    )
    assert "tiktok shop roi" in title.lower()
    user = captured["user"]
    assert "Entities: TikTok Shop, Checkout Flow" in user
    assert "Related keywords: social commerce" in user
    assert "Keyword variants: roi" in user
    assert "include at least 2 entities" in user
    assert "include at least 1 related keyword" in user
    assert "include at least 1 keyword variant" in user


@pytest.mark.asyncio
async def test_generate_title_clamps_directive_to_listed_count(monkeypatch):
    """SIE recommends 30 entities for the title; only 5 fit the prompt."""
    call, captured = _capturing_json({"candidates": ["TikTok Shop Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)

    await generate_title(
        keyword="tiktok shop",
        intent_type="how-to",
        entities=[f"E{i}" for i in range(30)],
        related_keywords=[],
        keyword_variants=[],
        title_targets={"entities": 30, "related_keywords": 0, "keyword_variants": 0},
    )
    user = captured["user"]
    assert "include at least 5 entities" in user
    assert "include at least 30" not in user


@pytest.mark.asyncio
async def test_generate_title_falls_back_when_no_targets(monkeypatch):
    """All-zero targets produce the legacy 'coverage over brevity' copy."""
    call, captured = _capturing_json({"candidates": ["TikTok Shop Guide"]})
    monkeypatch.setattr("modules.writer.title.claude_json", call)
    await generate_title(
        keyword="tiktok shop",
        intent_type="how-to",
        entities=["TikTok Shop"],
        related_keywords=[],
        keyword_variants=[],
        title_targets={"entities": 0, "related_keywords": 0, "keyword_variants": 0},
    )
    assert "include at least" not in captured["user"]


# ---------------------------------------------------------------------------
# H1 lede wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_h1_enrichment_caps_at_lede_ceiling(monkeypatch):
    """A 25-word lede can't carry more than 2 of any category."""
    call, captured = _capturing_json({"sentence": "lede"})
    monkeypatch.setattr("modules.writer.title.claude_json", call)
    await generate_h1_enrichment(
        keyword="kw",
        h1_text="H1",
        entities=[
            {"term": "E1", "entity_category": "services"},
            {"term": "E2", "entity_category": "equipment"},
            {"term": "E3", "entity_category": "problems"},
        ],
        related_keywords=["r1", "r2", "r3"],
        keyword_variants=["v1", "v2", "v3"],
        h1_targets={"entities": 5, "related_keywords": 5, "keyword_variants": 5},
    )
    user = captured["user"]
    assert "include at least 2 entities" in user
    assert "include at least 2 related keywords" in user
    assert "include at least 2 keyword variants" in user


@pytest.mark.asyncio
async def test_generate_h1_enrichment_skips_when_all_lists_empty(monkeypatch):
    """No entities + no related keywords + no variants → empty string."""
    called = False

    async def _call(*a, **kw):
        nonlocal called
        called = True
        return {"sentence": "x"}

    monkeypatch.setattr("modules.writer.title.claude_json", _call)
    out = await generate_h1_enrichment(
        keyword="kw",
        h1_text="H1",
        entities=[],
        related_keywords=[],
        keyword_variants=[],
        h1_targets={"entities": 2, "related_keywords": 2, "keyword_variants": 2},
    )
    assert out == ""
    assert called is False


# ---------------------------------------------------------------------------
# FAQ derivation + wiring
# ---------------------------------------------------------------------------


def test_scale_paragraphs_target_floors_to_one():
    assert _scale_paragraphs_target(0) == 0
    assert _scale_paragraphs_target(1) == 1  # min floor
    assert _scale_paragraphs_target(20) == int(round(20 * 0.12))


def test_derive_faq_category_targets_returns_three_bucket_dict():
    out = _derive_faq_category_targets({
        "entities": 20, "related_keywords": 10, "keyword_variants": 5,
    })
    assert set(out.keys()) == {"entities", "related_keywords", "keyword_variants"}
    assert all(isinstance(v, int) for v in out.values())


@pytest.mark.asyncio
async def test_write_faqs_lists_three_categories(monkeypatch):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"faqs": [
            {"question": "Q1?", "answer": "answer text placeholder."},
        ]}

    monkeypatch.setattr("modules.writer.faqs.claude_json", _call)
    filtered = FilteredSIETerms(required=[
        ReconciledTerm(term="TikTok Shop", is_entity=True),
        ReconciledTerm(term="checkout flow", is_entity=False),
        ReconciledTerm(term="roi", is_seed_fragment=True),
    ])
    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?"],
        filtered_terms=filtered,
        brand_voice_card=None,
        banned_regex=None,
        paragraphs_zone_targets={
            "entities": 20, "related_keywords": 14, "keyword_variants": 6,
        },
    )
    user = captured["user"]
    assert "ENTITIES: TikTok Shop" in user
    assert "RELATED_KEYWORDS: checkout flow" in user
    assert "KEYWORD_VARIANTS: roi" in user
    assert "COVERAGE_TARGETS" in user


@pytest.mark.asyncio
async def test_write_faqs_skips_directive_when_no_paragraphs_data(monkeypatch):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"faqs": [{"question": "Q1?", "answer": "answer."}]}

    monkeypatch.setattr("modules.writer.faqs.claude_json", _call)
    filtered = FilteredSIETerms(required=[
        ReconciledTerm(term="x", is_entity=True),
    ])
    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?"],
        filtered_terms=filtered,
        brand_voice_card=None,
        banned_regex=None,
        paragraphs_zone_targets=None,
    )
    assert "COVERAGE_TARGETS" not in captured["user"]


# ---------------------------------------------------------------------------
# Heading optimizer — three-bucket payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimize_headings_includes_keyword_variants():
    """SIE v1.4 — the optimizer no longer excludes seed fragments. They
    appear in the keyword_variants bucket as explicit injection
    candidates."""
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return {"rewrites": []}

    fragment = ReconciledTerm(
        term="roi",
        is_entity=False,
        is_seed_fragment=True,
    )
    structure = [
        {"level": "H2", "text": "Driving ROI", "order": 1,
         "type": "content", "source": "serp"},
    ]
    result = await optimize_headings(
        structure,
        keyword="roi tactics",
        reconciled_terms=[fragment],
        forbidden_terms=[],
        subheadings_targets={
            "entities": 0, "related_keywords": 0, "keyword_variants": 1,
        },
        llm_json_fn=_call,
    )
    assert result.llm_called is True
    assert '"keyword_variants": 1' in captured["user"]
    assert "roi" in captured["user"].lower()
