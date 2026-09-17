"""Unit tests for the deterministic per-client term-substitution helper.

Covers the pure text pass (case preservation, word boundaries, plurals,
longest-first, idempotency) and the HTML pass (visible text only — hrefs and
script/style untouched), plus Nova Life Peptides' real compliance map.
"""

from services import term_substitution as ts

NOVA = {
    "semaglutide": "glp1-sg",
    "tirzepatide": "glp2-tirz",
    "retatrutide": "glp3-rt",
}


# ── parse_substitutions ────────────────────────────────────────────────────


def test_parse_normalizes_and_drops_junk():
    raw = {
        "  retatrutide ": " glp3-rt ",   # trimmed
        "semaglutide": "glp1-sg",
        "empty": "",                     # blank value dropped
        "": "x",                          # blank key dropped
        "same": "same",                  # no-op pair dropped
        "num": 3,                         # non-str value dropped
    }
    out = ts.parse_substitutions(raw)
    assert out == {"retatrutide": "glp3-rt", "semaglutide": "glp1-sg"}


def test_parse_tolerates_non_dict():
    assert ts.parse_substitutions(None) == {}
    assert ts.parse_substitutions("retatrutide") == {}
    assert ts.parse_substitutions([("a", "b")]) == {}


# ── substitute_text: casing ────────────────────────────────────────────────


def test_case_preserved():
    assert ts.substitute_text("retatrutide kit", NOVA) == "glp3-rt kit"
    assert ts.substitute_text("Retatrutide Kit", NOVA) == "Glp3-rt Kit"
    assert ts.substitute_text("RETATRUTIDE", NOVA) == "GLP3-RT"


def test_title_position_gets_leading_cap():
    title = "Retatrutide 10-Vial Kit for Sale in 2026: What to Check First"
    assert ts.substitute_text(title, NOVA) == (
        "Glp3-rt 10-Vial Kit for Sale in 2026: What to Check First"
    )


# ── substitute_text: boundaries / plurals / multiple terms ─────────────────


def test_word_boundary_only():
    # a coded term is never a substring of a source term, and vice-versa; also a
    # longer word merely containing the term is left alone.
    assert ts.substitute_text("retatrutidergic", NOVA) == "retatrutidergic"


def test_plural_caught():
    assert ts.substitute_text("comparing retatrutides", NOVA) == "comparing glp3-rts"


def test_multiple_terms_one_pass():
    text = "We stock semaglutide, tirzepatide, and retatrutide."
    assert ts.substitute_text(text, NOVA) == "We stock glp1-sg, glp2-tirz, and glp3-rt."


def test_slug_form():
    assert ts.substitute_text("retatrutide-10-vial-kit", NOVA) == "glp3-rt-10-vial-kit"


def test_idempotent():
    once = ts.substitute_text("Retatrutide vials", NOVA)
    assert ts.substitute_text(once, NOVA) == once == "Glp3-rt vials"


def test_noop_cases():
    assert ts.substitute_text("", NOVA) == ""
    assert ts.substitute_text(None, NOVA) is None
    assert ts.substitute_text("retatrutide", {}) == "retatrutide"


def test_longest_first_no_preemption():
    subs = {"reta": "SHORT", "retatrutide": "glp3-rt"}
    # the full compound must win over the shorter overlapping key
    assert ts.substitute_text("retatrutide", subs) == "glp3-rt"


# ── substitute_text: non-string inputs never crash ─────────────────────────
# Regression: the Fanout writer passed its structured `intro` beats DICT to
# substitute_text, and the regex pass raised
# TypeError("expected string or bytes-like object, got 'dict'"), which failed
# every Nova scheduled article. A non-string is now returned unchanged.


def test_substitute_text_returns_non_string_unchanged():
    intro = {"agree": "x", "promise": "y", "preview": "z"}
    assert ts.substitute_text(intro, NOVA) is intro       # dict — no crash, unchanged
    assert ts.substitute_text(["retatrutide"], NOVA) == ["retatrutide"]  # list unchanged
    assert ts.substitute_text(42, NOVA) == 42             # number unchanged


# ── substitute_value: codes strings and structured fields ──────────────────


def test_substitute_value_codes_plain_string():
    assert ts.substitute_value("Buy retatrutide", NOVA) == "Buy glp3-rt"


def test_substitute_value_codes_intro_beats_dict():
    intro = {
        "agree": "You research retatrutide protocols.",
        "promise": "This covers semaglutide sourcing.",
        "preview": "No compound mentioned here.",
    }
    out = ts.substitute_value(intro, NOVA)
    assert out == {
        "agree": "You research glp3-rt protocols.",
        "promise": "This covers glp1-sg sourcing.",
        "preview": "No compound mentioned here.",
    }


def test_substitute_value_recurses_lists_and_leaves_non_str():
    val = {"terms": ["retatrutide", "clean"], "count": 3, "flag": None}
    out = ts.substitute_value(val, NOVA)
    assert out == {"terms": ["glp3-rt", "clean"], "count": 3, "flag": None}


def test_substitute_value_empty_map_is_noop():
    intro = {"agree": "retatrutide"}
    assert ts.substitute_value(intro, {}) is intro


# ── substitute_html: visible text only ─────────────────────────────────────


def test_html_replaces_visible_text():
    html = "<h1>Retatrutide Kit</h1><p>Buy retatrutide today.</p>"
    out = ts.substitute_html(html, NOVA)
    assert "Glp3-rt Kit" in out
    assert "Buy glp3-rt today." in out
    assert "retatrutide" not in out.lower()


def test_html_leaves_hrefs_untouched():
    html = '<a href="https://novalifepeptides.com/retatrutide-kit">Retatrutide kit</a>'
    out = ts.substitute_html(html, NOVA)
    # the visible anchor text is switched, the URL is preserved
    assert ">Glp3-rt kit<" in out
    assert "novalifepeptides.com/retatrutide-kit" in out


def test_html_skips_script_style():
    html = "<script>var x='retatrutide';</script><p>retatrutide</p>"
    out = ts.substitute_html(html, NOVA)
    assert "var x='retatrutide'" in out       # script body untouched
    assert "<p>glp3-rt</p>" in out            # visible text switched


def test_html_noop_cases():
    assert ts.substitute_html("", NOVA) == ""
    assert ts.substitute_html(None, NOVA) is None
    assert ts.substitute_html("<p>retatrutide</p>", {}) == "<p>retatrutide</p>"


# ── reconcile_voice_verdict ────────────────────────────────────────────────


def _verdict(*, score, terms, extra_violations=None):
    v = {
        "score": score,
        "band": "off_voice",
        "passed": False,
        "needs_rewrite": True,
        "critical_count": 1,
        "violations": [{"check": "never_use_terms", "terms": terms, "severity": "critical"}],
    }
    if extra_violations:
        v["violations"].extend(extra_violations)
    return v


def test_reconcile_noop_cases():
    assert ts.reconcile_voice_verdict(None, NOVA) is None
    assert ts.reconcile_voice_verdict({"x": 1}, NOVA) == {"x": 1}   # no violations key
    v = _verdict(score=59.6, terms=["retatrutide"])
    assert ts.reconcile_voice_verdict(v, {}) == v                   # empty map


def test_reconcile_drops_substituted_critical_low_score_still_fails():
    v = _verdict(score=59.6, terms=["retatrutide"])
    out = ts.reconcile_voice_verdict(v, NOVA)
    assert out["violations"] == []                 # the false critical is gone
    assert out["critical_count"] == 0
    assert out["passed"] is False                  # 59.6 < 80 → still off-voice
    assert out["needs_rewrite"] is True
    assert v["violations"]                          # original not mutated


def test_reconcile_high_score_becomes_pass():
    v = _verdict(score=86.0, terms=["Retatrutide"])
    out = ts.reconcile_voice_verdict(v, NOVA)
    assert out["critical_count"] == 0
    assert out["passed"] is True
    assert out["needs_rewrite"] is False


def test_reconcile_keeps_non_substituted_banned_term():
    # a banned competitor brand that has no substitution stays a live critical
    v = _verdict(score=90.0, terms=["retatrutide", "Ozempic"])
    out = ts.reconcile_voice_verdict(v, NOVA)
    assert out["violations"][0]["terms"] == ["Ozempic"]
    assert out["critical_count"] == 1
    assert out["passed"] is False


# ── substitute_page_result (Local SEO / Ecommerce shared) ──────────────────


def test_substitute_page_result_codes_and_reconciles():
    result = {
        "content_html": '<h1>Retatrutide Kit</h1><a href="/shop/glp-3-reta/">buy retatrutide</a>',
        "page_title": "Retatrutide 10-Vial Kit",
        "schema_json": '{"@type":"Product","name":"retatrutide kit"}',
        "voice_compliance": _verdict(score=59.6, terms=["retatrutide"]),
        "content_gaps": ["price of retatrutide"],  # internal advisory — left alone
    }
    out = ts.substitute_page_result(result, NOVA)
    assert out["page_title"] == "Glp3-rt 10-Vial Kit"
    assert ">Glp3-rt Kit<" in out["content_html"]
    assert ">buy glp3-rt<" in out["content_html"]
    assert "/shop/glp-3-reta/" in out["content_html"]      # real href preserved
    assert "retatrutide" not in out["schema_json"]
    assert out["voice_compliance"]["critical_count"] == 0  # false critical resolved
    assert out["content_gaps"] == ["price of retatrutide"]  # untouched


def test_substitute_page_result_noop():
    assert ts.substitute_page_result({"content_html": "retatrutide"}, {}) == {"content_html": "retatrutide"}
    assert ts.substitute_page_result(None, NOVA) is None


def test_reconcile_leaves_other_criticals():
    v = _verdict(
        score=90.0,
        terms=["retatrutide"],
        extra_violations=[{"check": "other", "severity": "critical"}],
    )
    out = ts.reconcile_voice_verdict(v, NOVA)
    assert out["critical_count"] == 1              # the unrelated critical remains
    assert out["passed"] is False
