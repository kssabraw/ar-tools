"""HTML serialization of a fanout article body.

The article body is GFM markdown (tables, lists, bold, links). `to_html` must
render it to real HTML — a table becomes <table>/<tr>/<td>, a bullet block
becomes <ul><li> — rather than HTML-escaping the raw markdown into a single
<p> (which rendered as literal pipes/dashes on the published page).
"""

from fanout.writer.models import ArticleItem
from fanout.writer.serialize import to_html

_TABLE_BODY = (
    "The table below summarizes checkpoints:\n\n"
    "| Titration Phase | Dose Range | Plateau Signal |\n"
    "|---|---|---|\n"
    "| Early (weeks 1-8) | 0.5-1 mg | Not applicable |\n"
    "| Mid (weeks 9-20) | 1.5-2.5 mg | Unlikely; reassess |\n\n"
    "If stabilized, that is the intended outcome."
)


def test_markdown_table_body_renders_as_html_table():
    article = [ArticleItem(level="none", heading="", body=_TABLE_BODY)]
    out = to_html(article)
    assert "<table>" in out and "</table>" in out
    assert "<th>Titration Phase</th>" in out
    assert "<td>Early (weeks 1-8)</td>" in out
    # The raw markdown pipe rows must not survive as literal text.
    assert "| Early" not in out
    assert "|---|" not in out


def test_bullet_body_renders_as_unordered_list():
    body = "- First point about dosing.\n- Second point about titration."
    article = [ArticleItem(level="none", heading="Key Takeaways", body=body)]
    out = to_html(article)
    assert "<h2>Key Takeaways</h2>" in out
    assert "<ul>" in out and "</ul>" in out
    assert "<li>First point about dosing.</li>" in out
    # No leftover dash bullets swallowed into a single paragraph.
    assert "<p>- First point" not in out


def test_prose_body_is_still_paragraph():
    article = [ArticleItem(level="none", heading="", body="A simple sentence.")]
    assert "<p>A simple sentence.</p>" in to_html(article)


def test_headings_are_escaped_not_markdown_rendered():
    article = [
        ArticleItem(level="H1", heading="Retatrutide Dosage & Titration", body=""),
        ArticleItem(level="H2", heading="How it works", body=""),
    ]
    out = to_html(article)
    assert "<h1>Retatrutide Dosage &amp; Titration</h1>" in out
    assert "<h2>How it works</h2>" in out


def test_empty_article_is_empty_string():
    assert to_html([]) == ""
