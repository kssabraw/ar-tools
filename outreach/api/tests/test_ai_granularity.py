"""The I-004 spike's analysis layer.

Everything tested here is pure. The engine call is not tested against a fake OpenAI, because a
fake only ever confirms the response shape you already assumed — the same reasoning that kept the
DataForSEO `task_get` envelope unverified by synthetic test and verified instead by a deliberately
small first batch.

What IS worth locking down is the arithmetic that turns nine answers into a verdict, because that
arithmetic is the thing a person will read months from now and act on.
"""

from api.services.ai_granularity import (
    GranularityReport,
    LevelSample,
    build_prompt,
    level_stability,
    names_at_level,
    normalize,
    overlap,
    parse_business_names,
    summarize,
)


def _report(**per_level) -> GranularityReport:
    """A report from {level: [ [names...], [names...] ]}."""
    levels = {level: level.title() for level in per_level}
    report = GranularityReport(keyword="plumber", levels=levels)
    for level, samples in per_level.items():
        for i, names in enumerate(samples):
            report.samples.append(
                LevelSample(
                    level=level, place=levels[level], sample_index=i, businesses=tuple(names)
                )
            )
    return report


# --- prompt ------------------------------------------------------------------------------


def test_the_prompt_differs_between_levels_only_in_the_place_name():
    """If the wording varied by level, a difference in the answers could be the wording rather
    than the geography, and the comparison would be uninterpretable."""
    a = build_prompt("plumber", "Los Angeles")
    b = build_prompt("plumber", "Hollywood")
    assert a.replace("Los Angeles", "PLACE") == b.replace("Hollywood", "PLACE")


# --- parsing -----------------------------------------------------------------------------


def test_parses_a_bare_json_array():
    assert parse_business_names('["Acme Plumbing", "Bob & Sons"]') == (
        "Acme Plumbing",
        "Bob & Sons",
    )


def test_parses_json_wrapped_in_prose_and_fences():
    """Models add commentary no matter how firmly the prompt forbids it. Being strict here would
    turn a perfectly good answer into an empty sample, which `summarize` would then report as the
    model naming nothing — a wrong finding produced by our own parser."""
    raw = 'Sure! Here you go:\n```json\n["Acme Plumbing", "Cole Drains"]\n```\nHope that helps.'
    assert parse_business_names(raw) == ("Acme Plumbing", "Cole Drains")


def test_falls_back_to_numbered_and_bulleted_lines():
    raw = "1. Acme Plumbing\n2. Cole Drains\n- Rapid Rooter"
    assert parse_business_names(raw) == ("Acme Plumbing", "Cole Drains", "Rapid Rooter")


def test_unparseable_text_yields_nothing_rather_than_garbage():
    assert parse_business_names("I'm not able to help with that.") == ()
    assert parse_business_names("") == ()


def test_normalize_ignores_punctuation_and_case():
    assert normalize("Bob & Sons, Inc.") == normalize("bob  sons inc")


# --- overlap -----------------------------------------------------------------------------


def test_identical_sets_overlap_completely():
    assert overlap(["Acme", "Cole"], ["cole", "ACME!"]) == 1.0


def test_disjoint_sets_do_not_overlap():
    assert overlap(["Acme"], ["Cole"]) == 0.0


def test_an_empty_side_is_zero_not_an_error():
    """An empty sample means the model named nothing. That is data, and it must not divide by
    zero on its way to being reported."""
    assert overlap([], ["Acme"]) == 0.0
    assert overlap(["Acme"], []) == 0.0


def test_partial_overlap_is_jaccard():
    # {a,b} vs {b,c} -> 1 shared of 3 distinct
    assert round(overlap(["a", "b"], ["b", "c"]), 3) == round(1 / 3, 3)


# --- aggregation -------------------------------------------------------------------------


def test_names_at_level_dedupes_across_samples_and_keeps_order():
    report = _report(metro=[["Acme", "Cole"], ["cole", "Rapid"]])
    assert names_at_level(report, "metro") == ("Acme", "Cole", "Rapid")


def test_stability_of_a_single_sample_is_zero_not_perfect():
    """One sample cannot disagree with itself, and calling that perfect stability would report
    the strongest possible confidence from the weakest possible evidence."""
    assert level_stability(_report(metro=[["Acme"]]), "metro") == 0.0


def test_stability_is_mean_pairwise_overlap():
    report = _report(suburb=[["a", "b"], ["a", "b"], ["c", "d"]])
    # pairs: 1.0, 0.0, 0.0
    assert round(level_stability(report, "suburb"), 3) == round(1 / 3, 3)


# --- the verdict -------------------------------------------------------------------------


def test_high_neighbourhood_metro_overlap_is_called_out_as_silent_fallback():
    """The failure the whole spike exists to catch: a name that reads specific and returns the
    metro answer."""
    metro = [["Acme", "Cole", "Rapid"]]
    report = _report(metro=metro, suburb=[["Lopez", "Vega"]], neighbourhood=metro)

    summary = summarize(report)

    assert summary["overlap"]["neighbourhood_vs_metro"] == 1.0
    assert any("SILENT FALLBACK" in f for f in summary["findings"])


def test_distinct_answers_at_each_level_report_the_names_discriminating():
    report = _report(
        metro=[["Acme", "Cole"]],
        suburb=[["Lopez", "Vega"]],
        neighbourhood=[["Ng", "Silva"]],
    )
    summary = summarize(report)
    assert summary["findings"] == [
        "each level named a materially different set of businesses — the names are "
        "discriminating as intended"
    ]


def test_the_threshold_used_is_reported_alongside_the_verdict():
    """0.7 is a starting point, not a measured constant. Whoever reads this JSON needs to see
    which number produced the finding, or the finding reads as more settled than it is."""
    summary = summarize(_report(metro=[["Acme"]]), fallback_threshold=0.5)
    assert summary["fallback_threshold"] == 0.5


def test_errors_and_empty_samples_are_counted_separately():
    """A failed call and an answer naming nobody are different claims — one says we did not ask
    successfully, the other says the model knows no one there — and collapsing them would let an
    outage read as evidence about the place."""
    report = _report(metro=[["Acme"]])
    report.samples.append(
        LevelSample(level="metro", place="Metro", sample_index=1, businesses=(), error="HTTP 429")
    )
    report.samples.append(
        LevelSample(level="metro", place="Metro", sample_index=2, businesses=())
    )

    summary = summarize(report)

    assert summary["errors"] == 1
    assert summary["empty_samples"] == 1


def test_the_summary_says_it_is_not_a_decision():
    """The granularity to use is recorded by a human in ai_region.name_level. This output is the
    evidence for that call, and the note is in the payload rather than only in a docstring
    because the payload is what gets pasted into an issue."""
    summary = summarize(_report(metro=[["Acme"]]))
    assert "human decision" in summary["note"]
    assert "ai_region.name_level" in summary["note"]
