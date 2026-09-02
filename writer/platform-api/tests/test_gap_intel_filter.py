"""Unit tests for services.gap_intel_filter — the gap-keyword quality chokepoint
(deterministic navigational/brand/address gate + best-effort LLM product-brand
pass). Pure logic + the LLM guard (mocked transport)."""

from unittest.mock import patch

from services import gap_intel_filter as gif


_BSA_MATCHERS = [{"sedgwick"}]  # a registered competitor's brand label


def _row(kw, comp="rival.com", client_pos=None):
    return {"keyword": kw, "competitor_domain": comp, "client_position": client_pos}


def test_deterministic_verdict():
    assert gif.deterministic_verdict("sedgwick claim phone number", _BSA_MATCHERS) == "navigational"
    assert gif.deterministic_verdict("mysedgwick portal", _BSA_MATCHERS) == "navigational"
    assert gif.deterministic_verdict("my sedgwick", _BSA_MATCHERS) == "competitor"
    assert gif.deterministic_verdict("190 bowery new york ny 10012", _BSA_MATCHERS) == "address"
    assert gif.deterministic_verdict("claims outsourcing", _BSA_MATCHERS) == "keep"
    assert gif.deterministic_verdict("sedgwick alternatives", _BSA_MATCHERS) == "keep"  # comparison rescued


def test_apply_verdicts_drops_both_layers_keeps_rest():
    rows = [
        _row("sedgwick claim phone number"),   # deterministic: navigational
        _row("my sedgwick"),                    # deterministic: competitor
        _row("autoclaims", comp="sedgwick.com"),  # llm: product brand
        _row("timeoff", comp="sedgwick.com"),      # llm: product brand
        _row("claims outsourcing"),             # keep
        _row("third party administrator"),      # keep
    ]
    llm_drop = {"autoclaims", "timeoff"}
    kept, report = gif.apply_verdicts(rows, _BSA_MATCHERS, llm_drop)
    assert [r["keyword"] for r in kept] == ["claims outsourcing", "third party administrator"]
    assert report["dropped_deterministic"] == 2
    assert report["dropped_llm"] == 2
    assert report["kept"] == 2


def test_apply_verdicts_no_llm_drop_is_deterministic_only():
    rows = [_row("autoclaims", comp="sedgwick.com"), _row("claims outsourcing")]
    kept, report = gif.apply_verdicts(rows, _BSA_MATCHERS, set())
    # Without the LLM layer, the coined product brand survives (token rules can't name it).
    assert [r["keyword"] for r in kept] == ["autoclaims", "claims outsourcing"]
    assert report["dropped_llm"] == 0


def test_llm_junk_keywords_guards_hallucinations_and_normalizes():
    rows = [_row("autoclaims"), _row("timeoff"), _row("claims outsourcing")]
    fake = {"not_content_keywords": [
        {"keyword": "AutoClaims", "reason": "brand_or_product"},   # case-normalized → autoclaims
        {"keyword": "timeoff", "reason": "brand_or_product"},
        {"keyword": "some hallucinated keyword", "reason": "other"},  # not in input → ignored
    ]}
    with patch.object(gif.settings, "anthropic_api_key", "k"), \
         patch("services.report_llm.run_forced_tool_sync", return_value=fake):
        drop = gif.llm_junk_keywords(rows, {"name": "BSA Claims"})
    assert drop == {"autoclaims", "timeoff"}  # hallucinated key dropped from the drop set


def test_llm_junk_keywords_best_effort_disabled_and_failure():
    rows = [_row("autoclaims")]
    with patch.object(gif.settings, "domain_intel_gap_llm_filter", False):
        assert gif.llm_junk_keywords(rows, {"name": "x"}) == set()
    # empty rows → no call
    assert gif.llm_junk_keywords([], {"name": "x"}) == set()
    # a raised call degrades to empty (never blocks the plan)
    with patch.object(gif.settings, "domain_intel_gap_llm_filter", True), \
         patch.object(gif.settings, "anthropic_api_key", "k"), \
         patch("services.report_llm.run_forced_tool_sync", side_effect=RuntimeError("boom")):
        assert gif.llm_junk_keywords(rows, {"name": "x"}) == set()


def test_filter_gap_rows_end_to_end():
    rows = [
        _row("my sedgwick"),                       # deterministic drop
        _row("autoclaims", comp="sedgwick.com"),   # llm drop
        _row("claims outsourcing"),                # keep
    ]
    fake = {"not_content_keywords": [{"keyword": "autoclaims", "reason": "brand_or_product"}]}
    with patch.object(gif, "_client_context", return_value={"name": "BSA Claims"}), \
         patch.object(gif.settings, "domain_intel_gap_llm_filter", True), \
         patch.object(gif.settings, "anthropic_api_key", "k"), \
         patch("services.report_llm.run_forced_tool_sync", return_value=fake):
        kept, report = gif.filter_gap_rows(rows, _BSA_MATCHERS, "c1")
    assert [r["keyword"] for r in kept] == ["claims outsourcing"]
    assert report["dropped_deterministic"] == 1 and report["dropped_llm"] == 1


def test_filter_gap_rows_nav_off_llm_on_skips_deterministic():
    # nav filter off → the deterministic gate is fully off (prior behavior), so a
    # brand term survives unless the LLM flags it; the LLM layer still runs.
    rows = [_row("my sedgwick"), _row("autoclaims"), _row("claims outsourcing")]
    fake = {"not_content_keywords": [{"keyword": "autoclaims", "reason": "brand_or_product"}]}
    with patch.object(gif.settings, "domain_intel_navigational_filter", False), \
         patch.object(gif.settings, "domain_intel_gap_llm_filter", True), \
         patch.object(gif.settings, "anthropic_api_key", "k"), \
         patch.object(gif, "_client_context", return_value={"name": "x"}), \
         patch("services.report_llm.run_forced_tool_sync", return_value=fake):
        kept, report = gif.filter_gap_rows(rows, _BSA_MATCHERS, "c1")
    assert [r["keyword"] for r in kept] == ["my sedgwick", "claims outsourcing"]
    assert report["dropped_deterministic"] == 0 and report["dropped_llm"] == 1


def test_filter_gap_rows_both_filters_off_is_passthrough():
    rows = [_row("my sedgwick"), _row("autoclaims")]
    with patch.object(gif.settings, "domain_intel_navigational_filter", False), \
         patch.object(gif.settings, "domain_intel_gap_llm_filter", False):
        kept, report = gif.filter_gap_rows(rows, _BSA_MATCHERS, "c1")
    assert len(kept) == 2 and report["kept"] == 2
