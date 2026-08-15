"""Tests for the Fan-out blog reoptimization reflection (fanout.suite_mirror).

Reoptimizing a Fan-out article runs the suite blog reopt spine on its mirrored
suite run, then reflects the improved article back onto a fresh
`fanout.article_outputs` row. `build_reflected_article` is the pure core of that
reflection — no network. Guarantees under test:

  * the reoptimized suite sections + title replace the prior article's body, and
    markdown/HTML are re-rendered from those sections (the Fan-out serializer),
  * the word count is recomputed from the new sections,
  * non-body fields (seo_title, metadata extras, client_context_summary) survive,
  * sections that aren't ArticleItem-shaped (e.g. a stray figure) are skipped,
    never crashing the render.
"""

from __future__ import annotations

from fanout import suite_mirror


def _sections():
    return [
        {"order": 0, "level": "H1", "type": "title", "heading": "Reoptimized Title", "body": ""},
        {"order": 1, "level": "H2", "type": "content", "heading": "How it works",
         "body": "A clear, reoptimized paragraph about the topic."},
        {"order": 2, "level": "H2", "type": "content", "heading": "Why it matters",
         "body": "Another improved paragraph with more useful detail here."},
    ]


def test_build_reflected_article_swaps_body_and_rerenders():
    prior = {
        "title": "Old Title",
        "seo_title": "Old SEO Title",
        "article": [{"order": 0, "level": "H2", "heading": "Stale", "body": "old body"}],
        "article_markdown": "## Stale\n\nold body\n",
        "article_html": "<h2>Stale</h2>",
        "metadata": {"total_word_count": 2, "section_count": 1},
        "client_context_summary": {"schema_version_effective": "1.7-no-context"},
    }
    out = suite_mirror.build_reflected_article(prior, _sections(), "Reoptimized Title")

    aj = out["article_json"]
    # Title + sections replaced.
    assert aj["title"] == "Reoptimized Title"
    assert aj["article"] == _sections()
    # Non-body fields preserved.
    assert aj["seo_title"] == "Old SEO Title"
    assert aj["client_context_summary"]["schema_version_effective"] == "1.7-no-context"
    assert aj["metadata"]["section_count"] == 1  # extra metadata kept
    # Re-rendered body reflects the NEW sections, not the stale ones.
    assert "Stale" not in out["article_markdown"]
    assert "reoptimized paragraph" in out["article_markdown"]
    assert "<h2>" in out["article_html"]
    assert "Why it matters" in out["article_html"]
    # Word count recomputed from the new sections (well above the prior 2).
    assert out["total_word_count"] > 5
    assert aj["metadata"]["total_word_count"] == out["total_word_count"]
    # article_json carries the rendered bodies too.
    assert aj["article_markdown"] == out["article_markdown"]
    assert aj["article_html"] == out["article_html"]


def test_build_reflected_article_empty_title_keeps_prior():
    prior = {"title": "Kept Title", "article": []}
    out = suite_mirror.build_reflected_article(prior, _sections(), "")
    assert out["article_json"]["title"] == "Kept Title"


def test_build_reflected_article_skips_non_articleitem_sections():
    sections = _sections() + ["not a dict", {"type": "figure", "html": "<img src=x>"}]
    # Must not raise; the malformed entries are skipped in rendering.
    out = suite_mirror.build_reflected_article({}, sections, "T")
    assert out["total_word_count"] > 5
    assert "How it works" in out["article_html"]


def test_build_reflected_article_no_prior_json():
    out = suite_mirror.build_reflected_article({}, _sections(), "Fresh")
    assert out["article_json"]["title"] == "Fresh"
    assert out["article_json"]["article"] == _sections()
