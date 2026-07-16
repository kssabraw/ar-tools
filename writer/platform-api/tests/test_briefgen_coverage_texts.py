"""Regression test for the brief coverage-audit text extraction
(fanout.briefgen.pipeline._coverage_texts).

The coverage audit runs only when a cluster has supporting keywords. It used to
treat `heading_structure` / `faqs` as dicts (`h["text"]`, `h.get("source")`),
but they are Pydantic models (`HeadingItem` / `FAQ`), so it crashed with
`AttributeError: 'HeadingItem' object has no attribute 'get'` — aborting brief
generation for EVERY multi-keyword cluster (observed live: Nova Life Peptides'
'liraglutide vs semaglutide'). This pins attribute access on the real models.
"""

from __future__ import annotations

from fanout.briefgen.models import FAQ, HeadingItem
from fanout.briefgen.pipeline import _coverage_texts


def test_coverage_texts_uses_attribute_access_on_models():
    headings = [
        HeadingItem(text="What is semaglutide", source="serp"),
        HeadingItem(text="Semaglutide dosage", source="cluster_keyword"),
        HeadingItem(text="", source="serp"),          # empty text is dropped
    ]
    faqs = [FAQ(question="Is it safe?"), FAQ(question="")]  # empty question dropped

    heading_texts, used_texts = _coverage_texts(headings, faqs)

    # Headings (non-empty) + FAQ questions (non-empty), in order.
    assert heading_texts == ["What is semaglutide", "Semaglutide dosage", "Is it safe?"]
    # Only headings sourced from a cluster keyword count as "used".
    assert used_texts == ["Semaglutide dosage"]


def test_coverage_texts_empty_inputs():
    assert _coverage_texts([], []) == ([], [])
