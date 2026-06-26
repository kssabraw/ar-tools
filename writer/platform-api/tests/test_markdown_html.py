import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.markdown_html import markdown_to_html  # noqa: E402


def test_headings_and_paragraph():
    html = markdown_to_html("## Sub\n\nHello world.")
    assert "<h2>Sub</h2>" in html
    assert "<p>Hello world.</p>" in html


def test_inline_bold_italic_link_code():
    html = markdown_to_html("A **b** and *i* and [L](https://x.com) and `c`.")
    assert "<strong>b</strong>" in html
    assert "<em>i</em>" in html
    assert '<a href="https://x.com" rel="noopener" target="_blank">L</a>' in html
    assert "<code>c</code>" in html


def test_unordered_list_wrapped_once():
    html = markdown_to_html("- a\n- b")
    assert html.count("<ul>") == 1 and html.count("</ul>") == 1
    assert "<li>a</li>" in html and "<li>b</li>" in html


def test_ordered_list():
    html = markdown_to_html("1. first\n2. second")
    assert "<ol>" in html and "<li>first</li>" in html and "<li>second</li>" in html


def test_html_is_escaped_in_text():
    html = markdown_to_html("5 < 6 & 7 > 2")
    assert "&lt;" in html and "&amp;" in html and "&gt;" in html


def test_code_span_contents_not_emphasised():
    html = markdown_to_html("use `**not bold**` here")
    assert "<code>**not bold**</code>" in html
    assert "<strong>" not in html


def test_image_converted_to_img_tag():
    html = markdown_to_html("![a hero](https://cdn.example.com/x.jpg)")
    assert '<img src="https://cdn.example.com/x.jpg" alt="a hero" />' in html


def test_image_is_not_double_rendered_as_link():
    html = markdown_to_html("![alt](https://cdn.example.com/x.png)")
    assert "<a " not in html


def test_empty_input():
    assert markdown_to_html("") == ""


def test_paragraphs_separated_by_blank_lines():
    html = markdown_to_html("one\n\ntwo")
    assert html.count("<p>") == 2
