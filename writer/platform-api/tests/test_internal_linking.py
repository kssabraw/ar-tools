"""Unit tests for services.internal_linking pure helpers — normalization, anchor
phrase derivation, opportunity finding (with guardrails), and bs4 injection."""

from __future__ import annotations

from services import internal_linking as il


# ── norm_url ──────────────────────────────────────────────────────────────────
def test_norm_url_strips_scheme_www_trailing_slash():
    assert il.norm_url("https://www.X.com/Foo/") == "www.x.com/foo"
    assert il.norm_url("http://x.com/a?b=1#c") == "x.com/a"
    assert il.norm_url("x.com") == "x.com"
    assert il.norm_url("") is None


# ── page_anchor_phrases ───────────────────────────────────────────────────────
def test_anchor_phrases_keywords_first_then_title_deduped_bounded():
    out = il.page_anchor_phrases(
        "Emergency Plumber Sydney | ACME Plumbing",
        keywords=["emergency plumber sydney", "x"],  # "x" too short (1 word)
        min_words=2, max_words=8,
    )
    # keyword first; 'x' dropped (1 word); the title dedups against the equal
    # lowercase keyword (matching is case-insensitive, so casing doesn't matter).
    assert out[0] == "emergency plumber sydney"
    assert len(out) == 1
    assert all(len(p.split()) >= 2 for p in out)


def test_anchor_phrases_distinct_title_kept_alongside_keyword():
    out = il.page_anchor_phrases("Blocked Drain Repair", keywords=["emergency plumber sydney"], min_words=2)
    assert out == ["emergency plumber sydney", "Blocked Drain Repair"]


def test_anchor_phrases_drop_too_long_titles():
    long_title = " ".join(f"w{i}" for i in range(12))
    assert il.page_anchor_phrases(long_title, max_words=8) == []


# ── extract_existing_links ────────────────────────────────────────────────────
def test_extract_existing_links_internal_only():
    html = '<a href="https://x.com/a">a</a> <a href="https://other.com/b">b</a>'
    assert il.extract_existing_links(html, internal_host="x.com") == {"x.com/a"}
    assert il.extract_existing_links(html) == {"x.com/a", "other.com/b"}


# ── visible_text skips boilerplate + links ────────────────────────────────────
def test_visible_text_excludes_nav_and_anchors():
    html = "<nav>menu plumber</nav><p>hello <a>linked</a> world</p>"
    text = il.visible_text(html)
    assert "hello" in text and "world" in text
    assert "menu" not in text and "linked" not in text


# ── find_opportunities ────────────────────────────────────────────────────────
def _pages():
    return [
        {"url": "https://x.com/emergency-plumber-sydney", "title": "Emergency Plumber Sydney",
         "html": "<p>We are the best.</p>", "post_id": 1, "type": "posts"},
        {"url": "https://x.com/blocked-drains", "title": "Blocked Drains",
         "html": "<p>Need an emergency plumber sydney for your blocked drains?</p>", "post_id": 2, "type": "posts"},
    ]


def test_find_opportunities_links_mention_to_page():
    edits = il.find_opportunities(_pages(), max_per_page=3, max_inbound_per_target=5, min_words=2)
    assert len(edits) == 1
    e = edits[0]
    assert e["source_url"].endswith("/blocked-drains")
    assert e["target_url"].endswith("/emergency-plumber-sydney")
    assert e["anchor_text"].lower() == "emergency plumber sydney"
    assert e["injectable"] is True


def test_find_opportunities_never_self_links():
    pages = [{"url": "https://x.com/p", "title": "Emergency Plumber Sydney",
              "html": "<p>emergency plumber sydney repeated emergency plumber sydney</p>",
              "post_id": 1, "type": "posts"}]
    assert il.find_opportunities(pages, max_per_page=3, max_inbound_per_target=5, min_words=2) == []


def test_find_opportunities_skips_already_linked_target():
    pages = _pages()
    pages[1]["html"] = (
        '<p>Need an <a href="https://x.com/emergency-plumber-sydney">emergency plumber sydney</a>?</p>'
    )
    # The phrase is already inside an <a> AND already links the target → no edit.
    assert il.find_opportunities(pages, max_per_page=3, max_inbound_per_target=5, min_words=2) == []


def test_find_opportunities_respects_inbound_cap():
    pages = [
        {"url": "https://x.com/target", "title": "Emergency Plumber Sydney",
         "html": "<p>home</p>", "post_id": 1, "type": "posts"},
        {"url": "https://x.com/a", "title": "A", "html": "<p>emergency plumber sydney</p>", "post_id": 2, "type": "posts"},
        {"url": "https://x.com/b", "title": "B", "html": "<p>emergency plumber sydney</p>", "post_id": 3, "type": "posts"},
    ]
    edits = il.find_opportunities(pages, max_per_page=3, max_inbound_per_target=1, min_words=2)
    # Only one inbound link to /target allowed.
    assert sum(1 for e in edits if e["target_url"].endswith("/target")) == 1


# ── inject_link_html ──────────────────────────────────────────────────────────
def test_inject_wraps_first_occurrence_preserving_text():
    html, ok = il.inject_link_html("<p>Call an emergency plumber sydney now.</p>",
                                   "emergency plumber sydney", "https://x.com/p")
    assert ok
    assert '<a href="https://x.com/p">emergency plumber sydney</a>' in html
    assert "Call an" in html and "now." in html


def test_inject_skips_text_inside_existing_anchor():
    html, ok = il.inject_link_html('<p><a href="/old">emergency plumber sydney</a></p>',
                                   "emergency plumber sydney", "https://x.com/p")
    assert ok is False
    assert html == '<p><a href="/old">emergency plumber sydney</a></p>'


def test_inject_returns_false_when_absent():
    html, ok = il.inject_link_html("<p>nothing here</p>", "emergency plumber sydney", "https://x.com/p")
    assert ok is False
