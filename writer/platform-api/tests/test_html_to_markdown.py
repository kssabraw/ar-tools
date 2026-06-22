import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.html_to_markdown import html_to_markdown  # noqa: E402


def test_headings_paragraph_bold_link():
    md = html_to_markdown('<h1>Title</h1><h2>Sub</h2><p>Hi <strong>x</strong> <a href="u">L</a></p>')
    assert "# Title" in md
    assert "## Sub" in md
    assert "**x**" in md
    assert "[L](u)" in md


def test_unordered_list_items_consecutive():
    md = html_to_markdown("<ul><li>a</li><li>b</li></ul>")
    assert "- a\n- b" in md  # no blank line between items


def test_ordered_list_numbers():
    md = html_to_markdown("<ol><li>first</li><li>second</li></ol>")
    assert "1. first\n2. second" in md


def test_table_renders_pipe_table():
    md = html_to_markdown(
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_blockquote_prefixed():
    md = html_to_markdown("<blockquote><p>quoted</p></blockquote>")
    assert md.startswith("> quoted")


def test_script_and_style_skipped():
    md = html_to_markdown("<p>keep</p><script>var x=1</script><style>.a{}</style>")
    assert "keep" in md
    assert "var x" not in md
    assert ".a{}" not in md


def test_empty_input():
    assert html_to_markdown("") == ""
    assert html_to_markdown("   ") == ""
