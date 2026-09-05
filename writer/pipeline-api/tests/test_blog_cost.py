"""Unit tests for the blog-pipeline cost accumulator (modules/brief/cost.py).

Blog modules used to persist `module_outputs.cost_usd = $0` because the shared
transport never recorded usage; this accumulator (fed by the transport, started +
surfaced by the main.py middleware) is what makes that figure honest.
"""

from __future__ import annotations

import asyncio

from modules.brief import cost


def test_unstarted_accounting_is_a_noop():
    # A non-blog request never calls start_accounting → record_usage must no-op,
    # so leaving the transport hook in unconditionally is safe.
    cost._cost_accumulator.set(None)
    cost.record_usage("claude-sonnet-4-6", 1000, 1000)
    assert cost.total_cost() == 0.0


def test_records_and_prices_by_model_tier():
    cost.start_accounting()
    cost.record_usage("claude-sonnet-4-6", 1_000_000, 1_000_000)  # $3 + $15
    cost.record_usage("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)  # $1 + $5
    cost.record_usage("claude-opus-4-8", 1_000_000, 1_000_000)  # $5 + $25
    # 18 + 6 + 30
    assert cost.total_cost() == 54.0


def test_unknown_model_defaults_to_sonnet_pricing():
    cost.start_accounting()
    cost.record_usage("some-future-model", 1_000_000, 0)
    assert cost.total_cost() == 3.0


def test_tokens_accumulate_alongside_cost():
    cost.start_accounting()
    cost.record_usage("claude-sonnet-4-6", 1500, 1200)
    cost.record_usage("claude-haiku-4-5-20251001", 500, 300)
    assert cost.total_tokens() == {"input_tokens": 2000, "output_tokens": 1500}


def test_total_tokens_zero_when_unstarted():
    cost._cost_accumulator.set(None)
    cost._token_accumulator.set(None)
    cost.record_usage("claude-sonnet-4-6", 1000, 1000)
    assert cost.total_tokens() == {"input_tokens": 0, "output_tokens": 0}


def test_start_accounting_resets_between_requests():
    cost.start_accounting()
    cost.record_usage("claude-sonnet-4-6", 1_000_000, 0)
    assert cost.total_cost() == 3.0
    cost.start_accounting()
    assert cost.total_cost() == 0.0


def test_child_coroutines_share_the_tally():
    # The modules fan out LLM calls with asyncio.gather; the single-element-list
    # trick means calls in copied child contexts mutate the same accumulator.
    async def _run():
        cost.start_accounting()

        async def _one():
            cost.record_usage("claude-sonnet-4-6", 1_000_000, 0)

        await asyncio.gather(*[_one() for _ in range(4)])
        return cost.total_cost()

    assert asyncio.run(_run()) == 12.0
