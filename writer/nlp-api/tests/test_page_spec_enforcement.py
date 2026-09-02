"""Phase 2 of the page spec (docs/modules/local-seo-page-spec-plan-v1_0.md):
the vendored `page_spec.py` stays byte-identical to platform-api's (one
definition of the bands + measurement for the suite), and the pure halves of
the section-scoped trim + the length axis on the keep-best key. Offline."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
import page_spec as pspec  # noqa: E402

_HERE = Path(__file__).resolve()
_PLATFORM_COPY = _HERE.parents[2] / "platform-api" / "services" / "page_spec.py"
_VENDORED_COPY = _HERE.parents[1] / "page_spec.py"


def test_vendored_page_spec_matches_platform_api():
    """The spec's bands + measurement are defined ONCE for the suite: the nlp
    copy is vendored byte-identical (mirrors the voice_card.py precedent)."""
    if not _PLATFORM_COPY.exists():  # nlp-api checked out alone
        return
    assert _VENDORED_COPY.read_bytes() == _PLATFORM_COPY.read_bytes(), (
        "writer/nlp-api/page_spec.py has drifted from "
        "writer/platform-api/services/page_spec.py — re-copy it"
    )


_SERP = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}


def _spec():
    return pspec.build_spec(client_id="c", keyword="k", location="L", location_code=1, serp_analysis=_SERP,
                            reference_entry=None, reference_page_type=None, fallback_target=1200)


def _page(words_by_key):
    return "<article>" + "".join(
        f'<section id="{k}"><h2>{k}</h2><p>' + " ".join(["w"] * n) + "</p></section>"
        for k, n in words_by_key.items()
    ) + "</article>"


def test_spec_trim_targets_only_over_sections_worst_first():
    spec = _spec()
    bands = {s["key"]: s for s in spec["sections"]}
    html = _page({
        "intro": bands["intro"]["max_words"] + 40,
        "services": bands["services"]["max_words"] + 200,
        "usp": bands["usp"]["min_words"],
    })
    measure = pspec.measure_page(html, spec)
    targets = main._spec_trim_targets(measure, spec)
    assert [t["key"] for t in targets] == ["services", "intro"]
    assert targets[0]["cut"] == 200 and targets[1]["cut"] == 40
    assert targets[0]["max_words"] == bands["services"]["max_words"]


def test_spec_trim_targets_empty_when_nothing_over():
    spec = _spec()
    html = _page({s["key"]: s["min_words"] for s in spec["sections"]})
    assert main._spec_trim_targets(pspec.measure_page(html, spec), spec) == []


def test_spec_trim_prompt_names_budget_and_only_targeted_sections():
    import section_edit
    spec = _spec()
    bands = {s["key"]: s for s in spec["sections"]}
    html = _page({"intro": bands["intro"]["max_words"] + 40, "usp": 50})
    sections = section_edit.split_sections(html)
    targets = main._spec_trim_targets(pspec.measure_page(html, spec), spec)
    prompt = main._spec_trim_prompt(targets, sections, "Acme Roofing", "roof restoration", "Melbourne", "VOICE")
    assert "[intro]" in prompt and "[usp]" not in prompt
    assert f"max {bands['intro']['max_words']} words" in prompt
    assert "CUT at least ~40 words" in prompt
    assert "VOICE" in prompt and "Acme Roofing" in prompt


def test_spec_verdict_measures_before_injected_blocks_and_none_without_spec():
    spec = _spec()
    html = _page({s["key"]: s["min_words"] for s in spec["sections"]})
    v = main._spec_verdict(html, spec)
    assert v["status"] == "in_band" and "measure" in v
    assert main._spec_verdict(html, None) is None
    # the deterministic contact block is not authored content: it never counts
    with_block = html.replace("</article>", '<section id="contact-find-us"><p>' + " ".join(["x"] * 400) + "</p></section></article>")
    assert main._spec_verdict(with_block, spec)["total_words"] == v["total_words"]


def test_combined_rank_key_prefers_in_band_over_a_higher_score():
    # A pass that lifts SEO but pushes the page over its band ranks BELOW the
    # in-band state — the length axis sits right after voice criticals.
    voice = {"score": 85, "needs_rewrite": False, "critical_count": 0}
    in_band = main._combined_rank_key(80.0, voice, 90.0, length_ok=True)
    over = main._combined_rank_key(95.0, voice, 90.0, length_ok=False)
    assert in_band > over
    # no spec → length is not a bar → key identical to the pre-Phase-2 shape
    assert main._combined_rank_key(80.0, voice, 90.0) == main._combined_rank_key(80.0, voice, 90.0, length_ok=True)


def test_request_models_accept_page_spec():
    spec = _spec()
    g = main.GeneratePageRequest(keyword="k", location="L", business_name="B", gbp_category="Roofer",
                                 address="1 St", page_spec=spec)
    assert g.page_spec["total"]["target"] == 1058
    r = main.ReoptimizePageRequest(keyword="k", location="L", existing_page_html="<p>x</p>", deficiencies=[],
                                   business_name="B", gbp_category="Roofer")
    assert r.page_spec is None
