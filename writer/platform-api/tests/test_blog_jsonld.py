"""Unit tests for the blog JSON-LD builder (BlogPosting + FAQPage)."""

import json

from services.blog_jsonld import (
    build_blog_jsonld,
    faqs_from_article,
    inline_jsonld_script,
    markdown_to_plain,
)


def _graph(schema: str) -> list[dict]:
    parsed = json.loads(schema)
    assert parsed["@context"] == "https://schema.org"
    return parsed["@graph"]


def test_minimal_blogposting_with_only_title():
    schema = build_blog_jsonld(title="How to Fix a Leaky Roof")
    graph = _graph(schema)
    assert len(graph) == 1
    posting = graph[0]
    assert posting["@type"] == "BlogPosting"
    assert posting["headline"] == "How to Fix a Leaky Roof"
    assert posting["inLanguage"] == "en"
    # No brand/faqs → no author/publisher/FAQPage.
    assert "author" not in posting
    assert "publisher" not in posting


def test_empty_title_returns_empty_string():
    assert build_blog_jsonld(title="") == ""
    assert build_blog_jsonld(title="   ") == ""


def test_headline_clipped_to_110_chars():
    long_title = "Roof " * 40  # 200 chars
    posting = _graph(build_blog_jsonld(title=long_title))[0]
    assert len(posting["headline"]) <= 110


def test_full_graph_with_brand_dates_image_and_faqs():
    schema = build_blog_jsonld(
        title="Emergency Plumbing Guide",
        faqs=[
            {"question": "How fast can you come?", "answer": "Within an hour."},
            {"question": "Do you work weekends?", "answer": "Yes, 24/7."},
        ],
        brand_name="Acme Plumbing",
        site_url="https://acme.example",
        image_url="https://cdn.example/hero.jpg",
        date_published="2026-07-01",
        date_modified="2026-07-20",
    )
    graph = _graph(schema)
    assert len(graph) == 2
    posting, faqpage = graph[0], graph[1]

    assert posting["@type"] == "BlogPosting"
    assert posting["image"] == "https://cdn.example/hero.jpg"
    assert posting["datePublished"] == "2026-07-01"
    assert posting["dateModified"] == "2026-07-20"
    assert posting["author"] == {
        "@type": "Organization",
        "name": "Acme Plumbing",
        "url": "https://acme.example",
    }
    assert posting["publisher"] == posting["author"]

    assert faqpage["@type"] == "FAQPage"
    assert len(faqpage["mainEntity"]) == 2
    first = faqpage["mainEntity"][0]
    assert first["@type"] == "Question"
    assert first["name"] == "How fast can you come?"
    assert first["acceptedAnswer"] == {"@type": "Answer", "text": "Within an hour."}


def test_no_faqpage_when_faqs_empty_or_incomplete():
    schema = build_blog_jsonld(
        title="No FAQ Here",
        faqs=[{"question": "Q only"}, {"answer": "A only"}, {}],
    )
    graph = _graph(schema)
    assert len(graph) == 1
    assert graph[0]["@type"] == "BlogPosting"


def test_brand_without_site_url_omits_url():
    posting = _graph(build_blog_jsonld(title="X", brand_name="Acme"))[0]
    assert posting["author"] == {"@type": "Organization", "name": "Acme"}


def test_markdown_to_plain_strips_formatting_links_and_citations():
    md = "See **our guide** and [this page](https://x.example) for details [1].\n\nAlso `code` here."
    plain = markdown_to_plain(md)
    assert plain == "See our guide and this page for details . Also code here."
    assert "**" not in plain
    assert "http" not in plain
    assert "[1]" not in plain


def test_markdown_to_plain_drops_images_and_strips_heading_markers():
    md = "## Heading\n\n![alt](https://x/img.png) Real answer text."
    plain = markdown_to_plain(md)
    # The image is removed and the `##` marker stripped (heading text is kept,
    # then whitespace collapses to a single line).
    assert plain == "Heading Real answer text."


def test_faqs_from_article_extracts_faq_questions_only():
    article = [
        {"type": "intro", "heading": None, "body": "Intro prose."},
        {"type": "content", "heading": "A Section", "body": "Body."},
        {"type": "faq-header", "heading": "FAQ", "body": ""},
        {"type": "faq-question", "heading": "What is X?", "body": "X is a **thing** [1]."},
        {"type": "faq-question", "heading": "Missing answer?", "body": ""},
        {"type": "faq-question", "heading": "", "body": "orphan answer"},
        "not a dict",
    ]
    faqs = faqs_from_article(article)
    assert faqs == [{"question": "What is X?", "answer": "X is a thing ."}]


def test_faqs_from_article_handles_non_list():
    assert faqs_from_article(None) == []
    assert faqs_from_article("nope") == []


def test_inline_jsonld_script_wraps_and_escapes_angle_brackets():
    schema = build_blog_jsonld(
        title="Safe",
        faqs=[{"question": "Q?", "answer": "Use </script> carefully"}],
    )
    block = inline_jsonld_script(schema)
    assert block.startswith('<script type="application/ld+json">')
    assert block.endswith("</script>")
    # The FAQ answer's literal </script> is escaped so it can't close the block.
    inner = block[len('<script type="application/ld+json">'):-len("</script>")]
    assert "</script>" not in inner
    assert "\\u003c/script>" in inner


def test_inline_jsonld_script_empty_on_blank():
    assert inline_jsonld_script("") == ""
    assert inline_jsonld_script("   ") == ""
