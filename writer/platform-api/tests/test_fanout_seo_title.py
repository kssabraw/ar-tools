"""Distinct SEO title generation in the fanout brief's title step.

WordPress needs separate <title> (post title) and on-page H1 strings — the
brief's title call now also emits `seo_title`, which the WP publish paths
prefer over the H1. Soft field: blank (identical-to-H1 or missing) means
consumers fall back to the H1.
"""

from fanout.briefgen.title import TitleScope, generate_title_scope


class _FakeLLM:
    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    def call_tool(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self._result)


_VALID = {
    "title": "How Retatrutide Works: Mechanism, Dosing, and Results",
    "seo_title": "Retatrutide: Mechanism, Dosing & Results Explained",
    "scope_statement": "Covers mechanism and dosing. Does not cover tirzepatide or semaglutide.",
}


def _gen(result: dict) -> TitleScope:
    return generate_title_scope(
        "retatrutide", intent_type="informational", serp_titles=[], serp_h1s=[],
        serp_metas=[], llm_answers={}, llm=_FakeLLM(result),
    )


def test_seo_title_carried_distinct_from_h1():
    ts = _gen(_VALID)
    assert ts.title == _VALID["title"]
    assert ts.seo_title == _VALID["seo_title"]
    assert ts.seo_title != ts.title


def test_seo_title_identical_to_h1_is_blanked():
    ts = _gen({**_VALID, "seo_title": _VALID["title"].upper()})
    assert ts.seo_title == ""          # consumers fall back to the H1


def test_missing_seo_title_defaults_blank():
    result = dict(_VALID)
    del result["seo_title"]
    ts = _gen(result)
    assert ts.seo_title == ""


def test_schema_requires_seo_title():
    llm = _FakeLLM(_VALID)
    generate_title_scope(
        "retatrutide", intent_type="informational", serp_titles=[], serp_h1s=[],
        serp_metas=[], llm_answers={}, llm=llm,
    )
    schema = llm.calls[0]["input_schema"]
    assert "seo_title" in schema["properties"]
    assert "seo_title" in schema["required"]
