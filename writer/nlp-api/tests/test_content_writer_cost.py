"""Unit tests for content-writer prose cost attribution in `main.py`.

Background: the four page generate/reoptimize handlers (Local SEO + Ecommerce)
route their DRAFT prose through `_generate_prose`, which may call OpenAI ("Luna",
gpt-5.6-luna). Their main-prose token record used to hardcode `GENERATION_MODEL`
(Claude Sonnet), so a Luna-written page was billed at Sonnet's $3/$15 instead of
Luna's $0.20/$1.20 — the `_MODEL_PRICING["gpt-5.6-luna"]` rate was never reached
and `/cost-report` overstated Luna page cost ~13x. `_effective_prose_model`
returns the model that actually wrote the prose so the token record prices it
correctly. Pure + offline (no network).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


# ── _effective_prose_model ──────────────────────────────────────────────────
def test_effective_model_defaults_to_sonnet(monkeypatch):
    # No provider / explicit anthropic -> the generation model (Claude), unchanged.
    assert main._effective_prose_model(None) == main.GENERATION_MODEL
    assert main._effective_prose_model("anthropic") == main.GENERATION_MODEL


def test_effective_model_openai_with_key_is_luna(monkeypatch):
    monkeypatch.setattr(main, "OPENAI_API_KEY", "sk-test")
    assert main._effective_prose_model("openai") == main.CONTENT_WRITER_OPENAI_MODEL
    # Resolver normalizes case, so the effective model follows.
    assert main._effective_prose_model("OpenAI") == main.CONTENT_WRITER_OPENAI_MODEL


def test_effective_model_openai_without_key_degrades_to_sonnet(monkeypatch):
    # An openai request with no key degrades to Claude in _generate_prose, so the
    # recorded model must degrade with it — never record a model that didn't run.
    monkeypatch.setattr(main, "OPENAI_API_KEY", "")
    assert main._effective_prose_model("openai") == main.GENERATION_MODEL


def test_unknown_provider_falls_back_to_sonnet(monkeypatch):
    monkeypatch.setattr(main, "OPENAI_API_KEY", "sk-test")
    assert main._effective_prose_model("gpt-4-turbo") == main.GENERATION_MODEL


# ── end-to-end pricing: the actual regression this fixes ────────────────────
def test_openai_page_prices_at_luna_not_sonnet(monkeypatch):
    monkeypatch.setattr(main, "OPENAI_API_KEY", "sk-test")
    model = main._effective_prose_model("openai")
    rec = main._token_record("generate-page", model, 1_000_000, 1_000_000)
    # Priced at Luna ($0.20 in + $1.20 out per 1M), NOT Sonnet ($3 + $15).
    assert rec["model"] == "gpt-5.6-luna"
    assert rec["cost_usd"] == 0.20 + 1.20
    # Guard against a silent regression back to the Sonnet rate.
    sonnet = main._token_record("generate-page", main.GENERATION_MODEL, 1_000_000, 1_000_000)
    assert sonnet["cost_usd"] == 3.00 + 15.00
    assert rec["cost_usd"] < sonnet["cost_usd"]


def test_anthropic_page_pricing_unchanged(monkeypatch):
    # A Claude-written page is byte-for-byte identical to prior behaviour.
    rec = main._token_record("generate-page", main._effective_prose_model("anthropic"), 1_000_000, 1_000_000)
    assert rec["model"] == main.GENERATION_MODEL
    assert rec["cost_usd"] == 3.00 + 15.00
