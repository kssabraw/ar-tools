"""Step 11.6 - Listicle minimum ranked-item enforcement.

Covers the pure/mockable logic of `modules.brief.listicle_items`:
- reaching `min_h2_count` by synthesizing named ranked items,
- honest-fallback (short outline kept, never fabricated) on LLM failure or
  an empty/decline response,
- no LLM call when the floor is already met,
- de-duplication against existing items and the `max_h2_count` ceiling,
- deterministic 1..N renumbering + FAQ-block-preserving insertion.
"""

from __future__ import annotations

import pytest

from models.brief import HeadingItem
from modules.brief.intent_template import get_template
from modules.brief.listicle_items import (
    apply_title_count,
    ensure_min_ranked_items,
    extract_title_count,
    strip_leading_ordinal,
    synthesize_item_names,
)


def _h1(text: str = "Best Widgets") -> HeadingItem:
    return HeadingItem(level="H1", text=text, type="content", source="serp")


def _ranked(text: str) -> HeadingItem:
    return HeadingItem(level="H2", text=text, type="content", source="serp")


def _faq_block() -> list[HeadingItem]:
    return [
        HeadingItem(level="H2", text="Frequently Asked Questions",
                    type="faq-header", source="synthesized"),
        HeadingItem(level="H3", text="Is X worth it?",
                    type="faq-question", source="synthesized"),
    ]


def _content_h2_texts(structure: list[HeadingItem]) -> list[str]:
    return [h.text for h in structure if h.level == "H2" and h.type == "content"]


def _make_llm(items):
    """Fake claude_json returning a fixed items payload; records call count."""
    calls: list[tuple] = []

    async def llm_fn(system, user, **kwargs):
        calls.append((system, user, kwargs))
        return {"items": items}

    llm_fn.calls = calls  # type: ignore[attr-defined]
    return llm_fn


# ---------------------------------------------------------------------------
# strip_leading_ordinal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1. Reveel", "Reveel"),
    ("2) Sifted", "Sifted"),
    ("#3 Enveyo", "Enveyo"),
    ("4: Zero Down", "Zero Down"),
    ("Reveel", "Reveel"),
    ("Top 10 Tools", "Top 10 Tools"),  # not an item ordinal - left intact
])
def test_strip_leading_ordinal(text, expected):
    assert strip_leading_ordinal(text) == expected


# ---------------------------------------------------------------------------
# ensure_min_ranked_items - happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fills_up_to_min_and_renumbers():
    template = get_template("listicle")  # min 5, max 10
    structure = [
        _h1(),
        _ranked("Best Widget Software for Cost Control"),
        *_faq_block(),
    ]
    llm = _make_llm([
        {"name": "Reveel", "angle": "audit automation"},
        {"name": "Sifted", "angle": "contract modeling"},
        {"name": "Enveyo", "angle": "carrier analytics"},
        {"name": "LateShipment", "angle": "refund recovery"},
    ])

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="best widget software",
        title="Best Widget Software",
        scope_statement="Ranked widget platforms.",
        min_count=template.min_h2_count,
        max_count=template.max_h2_count,
        llm_json_fn=llm,
    )

    assert result.added == 4
    assert result.after_count == 5  # reached the floor
    texts = _content_h2_texts(structure)
    # Sequential 1..N ordinals, existing item renumbered too.
    assert texts[0].startswith("1. ")
    assert [t.split(".", 1)[0] for t in texts] == ["1", "2", "3", "4", "5"]
    assert "Reveel" in " ".join(texts)
    # FAQ block stays at the tail, after the ranked items.
    assert structure[-2].type == "faq-header"
    assert structure[-1].type == "faq-question"
    # order reindexed 0-based across the whole structure.
    assert [h.order for h in structure] == list(range(len(structure)))


@pytest.mark.asyncio
async def test_no_llm_call_when_floor_already_met():
    template = get_template("listicle")
    structure = [_h1()] + [_ranked(f"{i}. Item {i}") for i in range(1, 6)] + _faq_block()
    llm = _make_llm([{"name": "Nope", "angle": "x"}])

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="t", scope_statement="s",
        min_count=template.min_h2_count, max_count=template.max_h2_count,
        llm_json_fn=llm,
    )
    assert result.llm_called is False
    assert result.added == 0
    assert llm.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_respects_max_count_ceiling():
    # min 5, but start with 4 and offer far more than the 1 slot of room:
    # only 1 may be added so total never exceeds max? Here we test the more
    # important direction - never exceed max_count even if LLM over-returns.
    structure = [_h1()] + [_ranked(f"{i}. Item {i}") for i in range(1, 5)] + _faq_block()
    llm = _make_llm([{"name": f"Tool{i}", "angle": "a"} for i in range(20)])

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="t", scope_statement="s",
        min_count=5, max_count=6,
        llm_json_fn=llm,
    )
    # Need = 1 to reach min 5; only 1 added even though room to 6 exists and
    # the LLM offered 20 (we fill to the floor, not the ceiling).
    assert result.added == 1
    assert result.after_count == 5


# ---------------------------------------------------------------------------
# Honest fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_failure_leaves_outline_unchanged():
    structure = [_h1(), _ranked("1. Only Item"), *_faq_block()]
    before = [h.text for h in structure]

    async def boom(*a, **k):
        raise RuntimeError("api down")

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="t", scope_statement="s",
        min_count=5, max_count=10,
        llm_json_fn=boom,
    )
    assert result.added == 0
    assert result.fallback_short is True
    assert [h.text for h in structure] == before  # untouched, not renumbered


@pytest.mark.asyncio
async def test_empty_llm_response_is_honest_fallback():
    structure = [_h1(), _ranked("1. Only Item"), *_faq_block()]
    llm = _make_llm([])  # model declined to name real items

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="t", scope_statement="s",
        min_count=5, max_count=10,
        llm_json_fn=llm,
    )
    assert result.added == 0
    assert result.fallback_short is True
    assert _content_h2_texts(structure) == ["1. Only Item"]


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedups_against_existing_and_itself():
    structure = [_h1(), _ranked("1. Reveel: Audit Automation"), *_faq_block()]
    llm = _make_llm([
        {"name": "Reveel", "angle": "dup of existing"},   # dropped (existing)
        {"name": "Sifted", "angle": "contract modeling"},
        {"name": "Sifted", "angle": "dup of itself"},      # dropped (self dup)
        {"name": "Enveyo", "angle": "analytics"},
    ])

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="t", scope_statement="s",
        min_count=5, max_count=10,
        llm_json_fn=llm,
    )
    names = " ".join(_content_h2_texts(structure))
    assert result.added == 2  # Sifted + Enveyo only
    assert names.count("Sifted") == 1
    assert names.count("Reveel") == 1


# ---------------------------------------------------------------------------
# Title count extraction / rewrite (year-safety is the critical case)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Top 10 Parcel Tools Ranked", 10),
    ("10 Best Parcel Tools in 2026", 10),          # count, NOT the year
    ("25 Best Widgets for 2026", 25),
    ("The 7 Best CRMs", 7),
    ("Top 7 CRMs in 2026", 7),
    # No count present -> None (and the year must never be read as a count).
    ("Best Parcel Software in 2026: Top Tools Ranked", None),
    ("Best Parcel Spend Management Software in 2026: Top Tools Ranked", None),
    ("Top Tools Ranked for Shippers", None),
    ("Best Widgets of 2026", None),
])
def test_extract_title_count(title, expected):
    assert extract_title_count(title) == expected


@pytest.mark.parametrize("title,count,expected", [
    ("Top 10 Parcel Tools in 2026", 7, "Top 7 Parcel Tools in 2026"),   # year kept
    ("10 Best Widgets 2026", 6, "6 Best Widgets 2026"),                  # year kept
    ("25 Best CRMs", 10, "10 Best CRMs"),
    ("Top Tools Ranked", 8, "Top Tools Ranked"),                        # no count -> unchanged
    ("Best Software in 2026", 5, "Best Software in 2026"),              # no count -> unchanged
])
def test_apply_title_count(title, count, expected):
    assert apply_title_count(title, count) == expected


@pytest.mark.asyncio
async def test_fill_target_can_exceed_min_for_a_titled_count():
    # Simulates "Top 8": caller passes min_count=8 (the clamped title number).
    structure = [_h1(), _ranked("Best Widget for Cost Control"), *_faq_block()]
    llm = _make_llm([{"name": f"Tool{i}", "angle": "a"} for i in range(10)])

    result = await ensure_min_ranked_items(
        structure=structure,
        keyword="k", title="Top 8 Widgets", scope_statement="s",
        min_count=8, max_count=10,
        llm_json_fn=llm,
    )
    assert result.after_count == 8
    texts = _content_h2_texts(structure)
    assert [t.split(".", 1)[0] for t in texts] == [str(i) for i in range(1, 9)]


@pytest.mark.asyncio
async def test_synthesize_item_names_zero_count_short_circuits():
    llm = _make_llm([{"name": "X", "angle": "y"}])
    out = await synthesize_item_names(
        keyword="k", title="t", scope_statement="s",
        count=0, existing_names=set(), llm_json_fn=llm,
    )
    assert out == []
    assert llm.calls == []  # type: ignore[attr-defined]
