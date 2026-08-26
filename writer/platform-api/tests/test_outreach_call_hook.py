"""Pure-logic tests for the loss-framed LLM phrasing pass over the "Why call?" hook.

What matters here is the invariant guard (fear-of-loss copy is where an LLM invents a "$X/month"
number) and the cache fingerprint (identical facts → identical key → replayable). The LLM transport
is mocked — never a real call.
"""

import services.report_llm as report_llm
from services import outreach_call_hook as och


def _justification(**over):
    base = {
        "measured": True,
        "prospect_name": "Drips Plumbing",
        "hook": "I searched “plumber” across Van Nuys — Ace Rooter is taking 18 of the exact spots you never appear.",
        "hook_element": "competitor",
        "provenance": {"keyword": "plumber", "submarket": "Van Nuys"},
        "talking_points": [
            {"element": "competitor", "text": "Ace Rooter is taking 18 of the points…",
             "facts": {"named": [{"name": "Ace Rooter", "points": 18}], "invisible_points": 20}},
            {"element": "reviews", "text": "Only 4 Google reviews…",
             "facts": {"review_count": 4, "field_median": 40.0, "field_sample": 8}},
        ],
    }
    base.update(over)
    return base


# --- the grounding guard ----------------------------------------------------------------------


def test_guard_rejects_a_dollar_figure():
    assert och.has_fabricated_number("you're losing about $5,000 a year to competitors")
    assert not och.guard_output("that's $5k walking out the door", [])


def test_guard_rejects_per_month_and_roi_framing():
    for bad in ("300 clicks per month", "roughly 50 leads a month", "10k in monthly revenue"):
        assert och.has_fabricated_number(bad), bad
    assert not och.guard_output("competitors are taking 50 jobs a month from you", [])


def test_guard_rejects_estimated_outcome_volume():
    assert och.has_fabricated_number("dozens of customers are calling someone else")
    assert och.has_fabricated_number("that's 25 new customers going elsewhere")


def test_guard_allows_the_legitimate_measured_numbers():
    """Percentages, review counts, 'top 3', point counts and miles all come from the facts and must
    NOT trip the guard — only invented money/volume does."""
    clean = (
        "You're invisible for “plumber” across 70% of Van Nuys, you've got 4 reviews against a "
        "field of about 40, and Ace Rooter is sitting in the top 3 at 18 of the spots you never "
        "appear, 2 miles from your shop."
    )
    assert not och.has_fabricated_number(clean)
    assert och.guard_output(clean, [{"element": "reviews", "text": "4 reviews vs about 40 in the field"}])


def test_guard_scans_the_rephrased_points_too():
    assert not och.guard_output(
        "clean hook", [{"element": "x", "text": "you're bleeding $2,000 a month"}]
    )


# --- fingerprint ------------------------------------------------------------------------------


def test_fingerprint_is_stable_for_the_same_facts():
    a = och.facts_fingerprint(_justification())
    b = och.facts_fingerprint(_justification())
    assert a == b


def test_fingerprint_ignores_prose_but_tracks_facts():
    # Rewriting the deterministic prose (text) but keeping the facts must NOT change the key —
    # the prose is exactly what we regenerate.
    reworded = _justification()
    reworded["talking_points"][0]["text"] = "totally different wording, same facts"
    assert och.facts_fingerprint(reworded) == och.facts_fingerprint(_justification())
    # But a changed FACT (a new scan) must change the key so the cache regenerates.
    changed = _justification()
    changed["talking_points"][1]["facts"]["review_count"] = 9
    assert och.facts_fingerprint(changed) != och.facts_fingerprint(_justification())


# --- prompt builder ---------------------------------------------------------------------------


def test_build_prompt_carries_identity_facts_and_the_loss_instruction():
    system, user = och.build_prompt(_justification())
    assert "LOCAL BUSINESS OWNER" in system and "NEVER invent or estimate money" in system
    assert "Drips Plumbing" in user and "plumber" in user and "Van Nuys" in user
    # the raw facts are handed over so the model can only re-word grounded material
    assert "Ace Rooter" in user and "review_count" in user


# --- generate_hook (LLM mocked) ---------------------------------------------------------------


def test_generate_hook_returns_a_clean_llm_hook(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "outreach_call_hook_llm_enabled", True)
    monkeypatch.setattr(
        report_llm, "run_forced_tool_sync",
        lambda **_k: {
            "hook": "Right now, every “plumber” search in Van Nuys is going to Ace Rooter, not you.",
            "talking_points": [{"element": "reviews", "text": "4 reviews where the field runs 40 — you lose the click."}],
        },
    )
    out = och.generate_hook(_justification())
    assert out and "Ace Rooter" in out["hook"]
    assert out["talking_points"][0]["element"] == "reviews"


def test_generate_hook_rejects_a_fabricated_money_hook(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "outreach_call_hook_llm_enabled", True)
    monkeypatch.setattr(
        report_llm, "run_forced_tool_sync",
        lambda **_k: {"hook": "You're losing $8,000 a month to Ace Rooter.", "talking_points": []},
    )
    # The guard sends it back to the deterministic hook (None), never ships the invented figure.
    assert och.generate_hook(_justification()) is None


def test_generate_hook_is_disabled_by_the_flag(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "outreach_call_hook_llm_enabled", False)
    assert och.generate_hook(_justification()) is None


def test_generate_hook_skips_an_unmeasured_justification(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "outreach_call_hook_llm_enabled", True)
    assert och.generate_hook(_justification(measured=False)) is None


def test_generate_hook_survives_a_provider_error(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "outreach_call_hook_llm_enabled", True)

    def boom(**_k):
        raise RuntimeError("all providers failed")

    monkeypatch.setattr(report_llm, "run_forced_tool_sync", boom)
    assert och.generate_hook(_justification()) is None
