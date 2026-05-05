"""Article structure tests — order resequencing, intro position,
FAQ-after-conclusion, orphan-ordinal validator.

Repros the user-reported bugs:
  1. Intro renders at the bottom of H2 #1 instead of after H1 (caused
     by writer's `next_order` colliding with brief heading_structure
     orders).
  2. "Step 3:" body reference with no Step 1 or Step 2 antecedent.
  3. FAQ rendering before the conclusion.
"""

from __future__ import annotations

from models.writer import ArticleSection
from modules.writer.pipeline import _validate_article_structure


def _section(
    *,
    order: int,
    level: str,
    type: str,
    heading: str | None = None,
    body: str = "",
) -> ArticleSection:
    return ArticleSection(
        order=order, level=level, type=type, heading=heading, body=body,
    )


# ---------------------------------------------------------------------------
# Orphan ordinal references
# ---------------------------------------------------------------------------


def test_orphan_step_3_without_step_1_or_2_warns():
    article = [
        _section(order=1, level="H1", type="content", heading="Title"),
        _section(order=2, level="none", type="intro", body="Intro paragraph."),
        _section(order=3, level="H2", type="content", heading="X",
                 body="Step 3: do the thing."),
    ]
    warnings = _validate_article_structure(article)
    assert any(w.startswith("orphan_ordinal") for w in warnings)
    assert "Step 3" in next(w for w in warnings if "orphan_ordinal" in w)


def test_step_1_then_step_2_then_step_3_no_warning():
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="intro", body=""),
        _section(order=3, level="H2", type="content", heading="A",
                 body="Step 1: foo."),
        _section(order=4, level="H2", type="content", heading="B",
                 body="Step 2: bar."),
        _section(order=5, level="H2", type="content", heading="C",
                 body="Step 3: baz."),
    ]
    warnings = _validate_article_structure(article)
    assert not any(w.startswith("orphan_ordinal") for w in warnings)


def test_step_1_only_no_warning():
    """A single 'Step 1' is fine — no antecedent required."""
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="H2", type="content", heading="A",
                 body="Step 1: only step."),
    ]
    warnings = _validate_article_structure(article)
    assert not any(w.startswith("orphan_ordinal") for w in warnings)


# ---------------------------------------------------------------------------
# Intro position
# ---------------------------------------------------------------------------


def test_intro_after_first_h2_warns():
    """Repro of the user-reported bug: intro at index 3, first H2 at
    index 2, so intro renders inside H2 #1 visually."""
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="h1-enrichment", body="lede"),
        _section(order=3, level="H2", type="content", heading="First H2",
                 body="body"),
        # BUG: intro after first H2.
        _section(order=4, level="none", type="intro", body="actual intro"),
        _section(order=5, level="H2", type="content", heading="Second H2",
                 body="body"),
    ]
    warnings = _validate_article_structure(article)
    assert any(w.startswith("intro_position") for w in warnings)


def test_intro_before_first_h2_no_warning():
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="h1-enrichment", body="lede"),
        _section(order=3, level="none", type="intro", body="intro"),
        _section(order=4, level="H2", type="content", heading="A", body="body"),
        _section(order=5, level="H2", type="content", heading="B", body="body"),
    ]
    warnings = _validate_article_structure(article)
    assert not any(w.startswith("intro_position") for w in warnings)


# ---------------------------------------------------------------------------
# Conclusion + FAQ ordering
# ---------------------------------------------------------------------------


def test_missing_conclusion_warns():
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="intro", body=""),
        _section(order=3, level="H2", type="content", heading="A", body=""),
    ]
    warnings = _validate_article_structure(article)
    assert any(w.startswith("missing_conclusion") for w in warnings)


def test_faq_before_conclusion_warns():
    """User-reported convention preference: FAQ should come AFTER the
    conclusion, not before."""
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="intro", body=""),
        _section(order=3, level="H2", type="content", heading="A", body=""),
        _section(order=4, level="H2", type="faq-header", heading="FAQ"),
        _section(order=5, level="H3", type="faq-question", heading="Q1?"),
        _section(order=6, level="none", type="conclusion", body="wrap"),
    ]
    warnings = _validate_article_structure(article)
    assert any(w.startswith("faq_before_conclusion") for w in warnings)


def test_faq_after_conclusion_no_warning():
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="intro", body=""),
        _section(order=3, level="H2", type="content", heading="A", body=""),
        _section(order=4, level="none", type="conclusion", body="wrap"),
        _section(order=5, level="H2", type="faq-header", heading="FAQ"),
        _section(order=6, level="H3", type="faq-question", heading="Q1?"),
    ]
    warnings = _validate_article_structure(article)
    assert not any(w.startswith("faq_before_conclusion") for w in warnings)
    assert not any(w.startswith("missing_conclusion") for w in warnings)


# ---------------------------------------------------------------------------
# Order resequencing semantics — sanity
# ---------------------------------------------------------------------------


def test_write_conclusion_emits_h2_with_conclusion_heading(monkeypatch):
    """User feedback: 'I also didn't see a specific conclusion heading.'
    write_conclusion must emit an ArticleSection with level='H2' and
    heading='Conclusion' so the rendered article has a visible
    section break before the wrap-up."""
    import asyncio

    from models.writer import BrandVoiceCard
    from modules.writer.banned_terms import build_banned_regex
    from modules.writer.conclusion import write_conclusion

    async def _fake_call(system, user, **kw):
        return {"conclusion": " ".join(["wrap"] * 100)}

    monkeypatch.setattr("modules.writer.conclusion.claude_json", _fake_call)

    section = asyncio.run(write_conclusion(
        keyword="kw",
        intent_type="how-to",
        section_summaries=["A: foo", "B: bar"],
        brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        conclusion_order=99,
    ))

    assert section.type == "conclusion"
    assert section.level == "H2"
    assert section.heading == "Conclusion"
    assert section.body  # non-empty


def test_renumbered_orders_match_list_position():
    """Sanity: after the writer's resequencing loop (idx, start=1),
    each section's `order` field equals its 1-indexed list position.
    We model that here to verify the validator works on resequenced
    articles."""
    article = [
        _section(order=1, level="H1", type="content", heading="T"),
        _section(order=2, level="none", type="h1-enrichment", body=""),
        _section(order=3, level="none", type="intro", body=""),
        _section(order=4, level="H2", type="content", heading="A", body=""),
        _section(order=5, level="none", type="conclusion", body=""),
        _section(order=6, level="H2", type="faq-header", heading="FAQ"),
    ]
    for i, s in enumerate(article, start=1):
        assert s.order == i
    # And the structure validator is happy with this canonical order.
    warnings = _validate_article_structure(article)
    assert not warnings, f"unexpected warnings: {warnings}"
