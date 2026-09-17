"""Integration guard for per-client term substitution across the Fanout writer.

Regression: PR #1199 — a client with a `term_substitutions` map (e.g. Nova Life
Peptides: retatrutide -> glp3-rt) crashed EVERY scheduled article with
`TypeError: expected string or bytes-like object, got 'dict'`, because the
in-writer substitution block fed the writer's structured `intro` beats DICT
({agree, promise, preview}) to a regex-based string substituter. The piece-level
substitution helpers were unit-tested, but nothing ran the FULL `generate_article`
with a substitution map — so the dict-shaped field slipping into the string path
was invisible until it hit production on the Luna provider (whose intro tool call
had independently been broken, hiding the bug).

This drives `generate_article` end to end with a substitution map and a fake LLM,
asserting: no crash, EVERY output field (title, the intro dict, body, takeaways,
cta) is coded, and no raw banned term survives anywhere.

The pipeline is provider-AGNOSTIC — the concrete provider (Anthropic vs the Luna
OpenAIWriterLLM) is an injected `WriterDeps.section_llm`, and both adapters return
the same shapes (`call_tool -> dict`, `complete_text -> str`). The integration test
drives the shared pipeline once; a separate matrix test asserts BOTH real adapters
satisfy that contract (the `WriterLLM` Protocol the substitution step relies on), so
a future provider that returns a non-dict from `call_tool` is caught.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from fanout.writer import pipeline as P  # noqa: E402
from fanout.writer.models import (  # noqa: E402
    Brief,
    BriefHeading,
    SieInput,
)

_SUBS = {"retatrutide": "glp3-rt"}
_RAW = "retatrutide"
_CODED = "glp3-rt"


class _MatrixLLM:
    """A fake WriterLLM implementing BOTH prose methods, returning the real output
    shapes each pipeline step consumes. Every string carries the raw banned term so
    the test can prove substitution reached each one. `call_tool` returns a dict —
    the exact contract the substitution step must handle for the `intro` field."""

    def complete_text(self, *, system, user, purpose, max_tokens=None, temperature=None) -> str:
        if purpose == "writer_enrichment_lede":
            return "Retatrutide is a research peptide handled to laboratory standards."
        if purpose == "writer_conclusion":
            return "In summary, retatrutide research demands verified documentation."
        # writer_section — answer-first prose + a list, all mentioning the raw term.
        return (
            "Retatrutide is supplied for research use only. Every batch of "
            "retatrutide ships with documentation.\n\n"
            "- Retatrutide requires cold storage\n"
            "- Retatrutide batches carry a Certificate of Analysis\n"
        )

    def call_tool(self, *, system, user, tool_name, tool_description,
                  input_schema, purpose, max_tokens=None, temperature=None) -> dict:
        if tool_name == "intro":  # the structured field that crashed the regex pass
            return {
                "agree": "You are comparing retatrutide sources.",
                "promise": "This guide covers retatrutide documentation.",
                "preview": "Sourcing, handling, and verification.",
            }
        if tool_name == "cta":
            return {"cta": "Review the retatrutide Certificate of Analysis before ordering."}
        if tool_name == "takeaways":
            return {"takeaways": [
                "Retatrutide is supplied for research use only.",
                "Every retatrutide batch ships with a Certificate of Analysis.",
                "Retatrutide handling follows laboratory standards.",
            ]}
        return {}


def _brief() -> Brief:
    return Brief(
        keyword="retatrutide",
        title="Retatrutide Research Sourcing Guide",
        seo_title="Retatrutide Sourcing — Documentation & Handling",
        scope_statement="How to evaluate retatrutide research suppliers.",
        heading_structure=[
            BriefHeading(order=1, level="H2", text="Sourcing and Documentation", type="content"),
            BriefHeading(order=2, level="H2", text="Conclusion", type="conclusion"),
        ],
    )


def _sie() -> SieInput:
    # extra="allow" on the SIE models keeps this minimal; the writer reads terms /
    # entities / entity_benchmark_target, all safely empty here.
    return SieInput.model_validate({
        "keyword": "retatrutide",
        "word_count": {"target": 800, "min": 600, "max": 1000},
        "target_keyword": {"term": "retatrutide", "minimum_usage": {}},
        "terms": {"required": [], "avoid": []},
        "entities": [],
        "entity_benchmark_target": 0,
    })


def _deps() -> P.WriterDeps:
    llm = _MatrixLLM()
    # Identical unit vectors → every H2 clears the topic-adherence gate (cosine 1.0),
    # so the section is kept and actually written (and thus substituted).
    return P.WriterDeps(section_llm=llm, short_llm=llm,
                        embed_fn=lambda texts: [[1.0, 0.0] for _ in texts])


def test_generate_article_codes_every_output_field_with_substitutions():
    out = P.generate_article(
        _brief(), _sie(), warnings={}, deps=_deps(),
        word_budget=800, brand_voice_card=None, substitutions=_SUBS,
    )

    # 1. No crash + the whole rendered article is coded.
    assert _CODED in out.article_markdown
    assert _RAW not in out.article_markdown.lower()
    assert _RAW not in out.article_html.lower()

    # 2. The structured `intro` DICT — the exact field that raised the TypeError —
    #    is coded, not skipped and not crashed.
    assert isinstance(out.intro, dict)
    intro_blob = " ".join(str(v) for v in out.intro.values()).lower()
    assert _RAW not in intro_blob
    assert _CODED in intro_blob

    # 3. Title + the other structured fields are coded too.
    assert out.title == "Glp3-rt Research Sourcing Guide"
    assert _RAW not in out.seo_title.lower()
    assert out.key_takeaways and all(_RAW not in t.lower() for t in out.key_takeaways)
    assert _RAW not in out.cta.lower()


def test_generate_article_without_substitutions_leaves_terms_intact():
    """No map (every client but the few that opt in) → the writer is a no-op on
    terms: the raw term is preserved end to end (byte-for-byte prior behaviour)."""
    out = P.generate_article(
        _brief(), _sie(), warnings={}, deps=_deps(),
        word_budget=800, brand_voice_card=None, substitutions=None,
    )
    assert _RAW in out.article_markdown.lower()
    assert _CODED not in out.article_markdown.lower()


@pytest.mark.parametrize("module_path,cls_name", [
    ("fanout.llm.anthropic_client", "AnthropicLLM"),
    ("fanout.llm.openai_writer_client", "OpenAIWriterLLM"),
])
def test_both_writer_adapters_satisfy_the_writerllm_contract(module_path, cls_name):
    """Provider matrix: both prose adapters must expose the two methods the writer
    drives (and that the `WriterLLM` Protocol / the substitution step assume) —
    `complete_text` and `call_tool`. Their return-shape correctness (call_tool ->
    dict) is exercised against a mocked SDK in test_fanout_openai_writer.py."""
    mod = pytest.importorskip(module_path)
    cls = getattr(mod, cls_name)
    for method in ("complete_text", "call_tool"):
        assert callable(getattr(cls, method, None)), f"{cls_name} is missing {method}"
