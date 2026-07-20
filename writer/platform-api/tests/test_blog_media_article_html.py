"""Unit tests for the deterministic article-structure core (blog_media.article_html):
block parsing + spans, stable ID assignment, ID-bearing HTML, the anchor index,
placement resolution (anchor → section → excerpt), idempotent figure insertion,
and the word-count/budget helpers."""
from services.blog_media import article_html as ah
from services.blog_media.article_html import ResolvedFigure

ARTICLE = """## Intro Heading

First intro paragraph with some words.

Second paragraph here.

## Costs Section

- item one
- item two

A paragraph after the list.

### A Subsection

Deeper paragraph.

<ol class="sources-cited">
  <li>Source one.</li>
</ol>
"""


def _blocks():
    return ah.assign_ids(ah.parse_blocks(ARTICLE))


def test_parse_blocks_kinds_and_order():
    kinds = [b.kind for b in ah.parse_blocks(ARTICLE)]
    assert kinds == [
        "heading", "paragraph", "paragraph", "heading", "list",
        "paragraph", "heading", "paragraph", "html",
    ]


def test_parse_blocks_spans_are_verbatim():
    blocks = ah.parse_blocks(ARTICLE)
    lines = ARTICLE.split("\n")
    for b in blocks:
        assert "\n".join(lines[b.start:b.end]) == b.text


def test_assign_ids_only_headings_and_paragraphs():
    blocks = _blocks()
    ids = {b.kind: [] for b in blocks}
    for b in blocks:
        ids.setdefault(b.kind, []).append(b.id)
    assert ids["heading"] == ["section-001", "section-002", "subsection-001"]
    assert ids["paragraph"] == ["paragraph-001", "paragraph-002", "paragraph-003", "paragraph-004"]
    assert all(b.id is None for b in blocks if b.kind in ("list", "html"))


def test_render_html_with_ids_puts_ids_on_headings_and_paragraphs():
    html = ah.render_html_with_ids(_blocks())
    assert '<h2 id="section-001">Intro Heading</h2>' in html
    assert '<p id="paragraph-001">First intro paragraph with some words.</p>' in html
    assert '<h3 id="subsection-001">A Subsection</h3>' in html
    # list has no id
    assert "<ul>" in html and 'id="' not in html.split("<ul>")[1].split("</ul>")[0]


def test_build_id_index_and_paragraph_section_containment():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    assert "section-002" in idx.section_ids
    assert "paragraph-001" in idx.anchor_ids
    # paragraph after "Costs Section" heading belongs to section-002
    assert idx.paragraph_section["paragraph-003"] == "section-002"
    # deeper paragraph belongs to the subsection
    assert idx.paragraph_section["paragraph-004"] == "subsection-001"


def test_resolve_placement_by_anchor_id():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement({"anchor_id": "paragraph-002"}, blocks, idx, ARTICLE)
    assert blocks[pos].id == "paragraph-002"


def test_resolve_placement_by_section_id_targets_last_paragraph():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    # section-002 contains a list + "A paragraph after the list." (paragraph-003)
    pos = ah.resolve_placement({"section_id": "section-002"}, blocks, idx, ARTICLE)
    assert blocks[pos].id == "paragraph-003"


def test_resolve_placement_by_fallback_excerpt():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement(
        {"fallback_excerpt": "Second paragraph here.", "fallback_excerpt_occurrence": 1},
        blocks, idx, ARTICLE,
    )
    assert blocks[pos].id == "paragraph-002"


def test_resolve_placement_unresolvable_returns_none():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    assert ah.resolve_placement({"anchor_id": "paragraph-999"}, blocks, idx, ARTICLE) is None


def test_insert_figures_after_anchor():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement({"anchor_id": "paragraph-002"}, blocks, idx, ARTICLE)
    fig = ResolvedFigure(
        block_index=pos, position="after", media_id="inline-1",
        markup=ah.figure_markdown(media_id="inline-1", src="/i/x.webp", alt="An alt", caption=None, css_class="article-inline-image"),
    )
    out = ah.insert_figures(ARTICLE, blocks, [fig])
    # figure appears after the second paragraph and before the Costs heading
    p2 = out.index("Second paragraph here.")
    figpos = out.index('data-media-id="inline-1"')
    costs = out.index("## Costs Section")
    assert p2 < figpos < costs


def test_insert_figures_is_idempotent():
    blocks = _blocks()
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement({"anchor_id": "paragraph-002"}, blocks, idx, ARTICLE)
    fig = ResolvedFigure(
        block_index=pos, position="after", media_id="inline-1",
        markup=ah.figure_markdown(media_id="inline-1", src="/i/x.webp", alt="a", caption=None, css_class="c"),
    )
    once = ah.insert_figures(ARTICLE, blocks, [fig])
    twice = ah.insert_figures(once, ah.assign_ids(ah.parse_blocks(once)), [fig])
    assert once.count('data-media-id="inline-1"') == 1
    assert twice.count('data-media-id="inline-1"') == 1


def test_figure_markdown_escapes_and_includes_caption():
    md = ah.figure_markdown(
        media_id="inline-2", src="/i/y.webp", alt='He said "hi" <ok>',
        caption="Source: Nature", css_class="article-chart",
    )
    assert 'data-media-id="inline-2"' in md
    assert "&quot;hi&quot;" in md and "&lt;ok&gt;" in md
    assert "<figcaption>Source: Nature</figcaption>" in md


def test_word_count_and_budget():
    assert ah.inline_budget(600) == 0
    assert ah.inline_budget(999) == 0
    assert ah.inline_budget(1000) == 1
    assert ah.inline_budget(1999) == 1
    assert ah.inline_budget(2000) == 2
    assert ah.inline_budget(8000) == 2
    # word_count ignores markup/marks
    assert ah.word_count("## Heading\n\ntwo words") == 3


def test_resolve_placement_excerpt_matches_wrapped_lines():
    # The plan copies excerpts from a whitespace-normalized view; the raw
    # paragraph wraps across lines. Must still resolve to the right block.
    md = "## H\n\nFirst paragraph\nwraps across lines here.\n\nSecond one.\n"
    blocks = ah.assign_ids(ah.parse_blocks(md))
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement(
        {"fallback_excerpt": "First paragraph wraps across lines here.", "fallback_excerpt_occurrence": 1},
        blocks, idx, md,
    )
    assert pos is not None and blocks[pos].id == "paragraph-001"


def test_resolve_placement_excerpt_nth_occurrence_raw_offset():
    md = "## H\n\nrepeat me now.\n\nmiddle text.\n\nrepeat me now.\n"
    blocks = ah.assign_ids(ah.parse_blocks(md))
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement(
        {"fallback_excerpt": "repeat me now.", "fallback_excerpt_occurrence": 2},
        blocks, idx, md,
    )
    assert pos is not None and blocks[pos].id == "paragraph-003"


def test_resolve_placement_bad_occurrence_value_defaults_to_first():
    md = "## H\n\nonly paragraph.\n"
    blocks = ah.assign_ids(ah.parse_blocks(md))
    idx = ah.build_id_index(blocks)
    pos = ah.resolve_placement(
        {"fallback_excerpt": "only paragraph.", "fallback_excerpt_occurrence": "not-a-number"},
        blocks, idx, md,
    )
    assert pos is not None and blocks[pos].id == "paragraph-001"
