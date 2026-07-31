"""Internal-link injection gating (`fanout.jobs._inject_internal_links`).

The two target sources are gated independently: the M6 architecture graph supplies
lateral peer links (needs `site_base_url` + a generated architecture), while the
session's `extra_link_urls` are absolute money-page URLs that need neither.

Regression: they used to share one early return, so a session whose architecture was
never generated published every article with NO links at all — including the money page
the owner had explicitly configured on it. That is exactly what happened to the Nova Life
Peptides "semaglutide" session: 1,594 clusters planned, a `/shop/glp-1-sema/` extra link
set, an active Mon/Wed schedule — and five live posts with zero internal links.
"""

from unittest.mock import patch

import pytest

pytest.importorskip("pydantic")
jobs = pytest.importorskip("fanout.jobs")   # heavy deps (spaCy/louvain) — skip without them

from fanout.writer.models import ArticleItem, WriterOutput  # noqa: E402

_SESSION = {
    "id": "s1",
    "seed_keyword": "semaglutide",
    "site_base_url": "https://novalifepeptides.com",
    "extra_link_urls": ["https://novalifepeptides.com/shop/glp-1-sema/"],
}


def _article() -> WriterOutput:
    return WriterOutput(
        keyword="semaglutide for pcos",
        article=[
            ArticleItem(order=1, level="H1", type="title", heading="Semaglutide and PCOS"),
            ArticleItem(order=2, level="none", type="intro",
                        body="Semaglutide is a GLP-1 agonist studied for weight loss."),
            ArticleItem(order=3, level="H2", type="content", heading="How it works"),
            ArticleItem(order=4, level="none", type="content",
                        body="Clinical trials report meaningful reductions in body weight."),
            ArticleItem(order=5, level="H2", type="conclusion", heading="Conclusion"),
        ],
    )


def _inject(article, *, architecture=None, session=None):
    """Run the injector with the storage layer stubbed out."""
    with patch("fanout.storage.silo.get_session", return_value=session or _SESSION), \
         patch("fanout.storage.silo.get_architecture", return_value=architecture), \
         patch("fanout.jobs._client_blog_url_style", return_value=None):
        jobs._inject_internal_links("s1", "c1", article)
    return article


def test_money_page_links_without_a_generated_architecture():
    # THE REGRESSION. No architecture row -> laterals are impossible, but the owner's
    # money page must still be linked rather than the whole article shipping bare.
    article = _inject(_article(), architecture=None)

    links = article.metadata["internal_links"]
    assert links["target_count"] == 1
    assert links["linked"] == ["https://novalifepeptides.com/shop/glp-1-sema/"]
    assert "](https://novalifepeptides.com/shop/glp-1-sema/)" in article.article_markdown


def test_money_page_anchors_the_seed_keyword_in_prose():
    # "glp 1 sema" (the slug) appears in no article, so the seed keyword is what
    # actually earns the inline link — in the body, not a Related Articles bullet.
    article = _inject(_article(), architecture=None)

    assert article.metadata["internal_links"]["related_fallback"] == []
    body = next(it.body for it in article.article if it.type == "intro")
    assert "[Semaglutide](https://novalifepeptides.com/shop/glp-1-sema/)" in body


def test_no_targets_at_all_leaves_the_article_untouched():
    session = {**_SESSION, "extra_link_urls": []}
    article = _inject(_article(), architecture=None, session=session)

    assert "internal_links" not in article.metadata
    assert article.article_markdown == ""      # never re-serialized
