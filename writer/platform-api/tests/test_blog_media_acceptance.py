"""Acceptance-matrix tests (addendum §Acceptance Tests) exercised at the pure
decision layer: word-count → budget, validation/count enforcement, chart
grounding, placement fallback, and idempotent insertion. Integration-level cases
(live render/commit) are out of scope for the pure suite."""
from services.blog_media import charts as ch
from services.blog_media import validate as v
from services.blog_media.article_html import (
    IdIndex, ResolvedFigure, assign_ids, build_id_index, figure_markdown,
    inline_budget, insert_figures, parse_blocks, resolve_placement,
)


def _idx():
    return IdIndex(
        anchor_ids={"section-001", "paragraph-001", "paragraph-002"},
        section_ids={"section-001"},
        id_to_index={"section-001": 0, "paragraph-001": 1, "paragraph-002": 2},
        paragraph_section={"paragraph-001": "section-001", "paragraph-002": "section-001"},
    )


def _hero():
    return {"status": "create", "prompt": "hero", "alt_text": "a",
            "filename": "hero.webp", "width": 2048, "height": 1152, "confidence": 0.9}


def _img(aid="inline-1", anchor="paragraph-002", filename="a.webp"):
    return {"asset_id": aid, "asset_type": "generated_image",
            "placement": {"anchor_type": "paragraph", "anchor_id": anchor, "position": "after"},
            "generated_image": {"status": "create", "prompt": "p", "alt_text": "alt",
                                "filename": filename, "confidence": 0.8}}


def _chart_asset(aid="inline-1", filename="c.svg"):
    q = "AI Overviews now appear in 60.32% of U.S. queries"
    q2 = "The prior year figure was 25% of queries"
    return {
        "asset_id": aid, "asset_type": "chart",
        "placement": {"anchor_id": "paragraph-002"},
        "generated_image": {"status": "skip"},
        "chart": {"status": "create", "type": "bar", "filename": filename, "confidence": 0.95,
                  "series": [{"data": [
                      {"label": "2026", "value": 60.32, "display_value": "60.32%", "source_quote": q, "source_name": "X"},
                      {"label": "2025", "value": 25, "display_value": "25%", "source_quote": q2, "source_name": "X"},
                  ]}]},
    }, q + " " + q2


def _run(plan, *, max_inline, allow_charts=True):
    return v.validate_and_clean(plan, idx=_idx(), max_inline=max_inline, allow_charts=allow_charts,
                                hero_min=0.75, inline_min=0.75, chart_min=0.90)


# 1. Article < 1000 words → one hero, zero inline.
def test_case_1_short_article_no_inline():
    assert inline_budget(600) == 0
    r = _run({"hero_image": _hero(), "inline_assets": [_img()]}, max_inline=0)
    assert r.hero_ok and r.inline == []


# 2. 1000–1999 words, no stats → one hero + one generated image.
def test_case_2_one_inline_image():
    assert inline_budget(1500) == 1
    r = _run({"hero_image": _hero(), "inline_assets": [_img()]}, max_inline=1)
    assert len(r.inline) == 1 and r.inline[0]["asset_type"] == "image"


# 3. 1000–1999 with one valid statistic → one hero + one chart.
def test_case_3_one_chart_occupies_the_slot():
    chart, article = _chart_asset()
    r = _run({"hero_image": _hero(), "inline_assets": [chart]}, max_inline=1)
    assert len(r.inline) == 1 and r.inline[0]["asset_type"] == "chart"
    ok, _ = ch.validate_chart_spec(r.inline[0]["chart"], article_text=article, allow_derived=False)
    assert ok


# 6 / 18. Incompatible or unknown chart → skipped, never fabricated.
def test_case_6_unknown_chart_type_skipped():
    ok, reason = ch.validate_chart_spec({"type": "pie", "series": []}, article_text="x", allow_derived=False)
    assert not ok and reason == "unsupported_type"


# 7. One percentage, derived disabled → no invented remainder.
def test_case_7_derived_remainder_rejected_when_disabled():
    q = "AI Overviews now appear in 60.32% of U.S. queries"
    donut = {"type": "donut", "series": [{"data": [
        {"label": "with", "value": 60.32, "display_value": "60.32%", "source_quote": q, "source_name": "X"},
        {"label": "without", "value": 39.68, "display_value": "39.68%", "derived": True,
         "formula": "100 - 60.32", "derivation_explanation": "remainder"},
    ]}]}
    ok, reason = ch.validate_chart_spec(donut, article_text=q, allow_derived=False)
    assert not ok and reason == "derived_values_not_allowed"


# 8. One percentage, derived enabled → valid derived remainder for a defined whole.
def test_case_8_derived_remainder_ok_when_enabled():
    q = "AI Overviews now appear in 60.32% of U.S. queries"
    donut = {"type": "donut", "series": [{"data": [
        {"label": "with", "value": 60.32, "display_value": "60.32%", "source_quote": q, "source_name": "X"},
        {"label": "without", "value": 39.68, "display_value": "39.68%", "derived": True,
         "formula": "100 - 60.32", "derivation_explanation": "remainder"},
    ]}]}
    ok, _ = ch.validate_chart_spec(donut, article_text=q, allow_derived=True)
    assert ok


# 9. Invalid placement anchor → unresolvable (no unrelated insertion).
def test_case_9_invalid_anchor_unresolvable():
    md = "## H\n\npara one.\n\npara two.\n"
    blocks = assign_ids(parse_blocks(md))
    idx = build_id_index(blocks)
    assert resolve_placement({"anchor_id": "paragraph-404"}, blocks, idx, md) is None


# 10. Duplicate job execution → no duplicate figures.
def test_case_10_idempotent_insertion():
    md = "## H\n\npara one.\n\npara two.\n"
    blocks = assign_ids(parse_blocks(md))
    idx = build_id_index(blocks)
    pos = resolve_placement({"anchor_id": "paragraph-001"}, blocks, idx, md)
    fig = ResolvedFigure(pos, "after", "inline-1",
                         figure_markdown(media_id="inline-1", src="/x.webp", alt="a", caption=None, css_class="c"))
    once = insert_figures(md, blocks, [fig])
    twice = insert_figures(once, assign_ids(parse_blocks(once)), [fig])
    assert twice.count('data-media-id="inline-1"') == 1


# 17. Model returns more assets than permitted → extras rejected before generation.
def test_case_17_over_budget_rejected():
    assets = [_img("inline-1", filename="a.webp"),
              _img("inline-2", anchor="paragraph-001", filename="b.webp"),
              _img("inline-3", filename="c.webp")]
    r = _run({"hero_image": _hero(), "inline_assets": assets}, max_inline=2)
    assert len(r.inline) == 2
