"""Pure tests for the content scheduler's bounded-retry policy
(fanout.writer.retry).

The scheduler treats a generation miss as transient and requeues with
exponential backoff up to `scheduler_max_attempts`, then dead-letters. These
tests pin the two pure decisions — attempt counting / retry-vs-dead-letter and
the backoff curve — independently of the DB and asyncio loop.
"""

from __future__ import annotations

from fanout.writer.retry import (
    next_attempt_number,
    retry_delay_seconds,
    should_retry,
)


def test_next_attempt_number_from_zero_or_none():
    assert next_attempt_number(None) == 1
    assert next_attempt_number(0) == 1
    assert next_attempt_number(2) == 3
    # Defensive: a negative stored value never yields < 1.
    assert next_attempt_number(-5) == 1


def test_should_retry_budget_with_max_4():
    # attempts is the post-increment count. max=4 -> retry on 1,2,3; dead-letter at 4.
    assert should_retry(1, 4) is True
    assert should_retry(2, 4) is True
    assert should_retry(3, 4) is True
    assert should_retry(4, 4) is False
    assert should_retry(5, 4) is False


def test_should_retry_max_one_is_no_retry():
    # max_attempts=1 means a single try, no retries.
    assert should_retry(1, 1) is False
    # A non-positive max is floored to 1 (never divide the budget to zero).
    assert should_retry(1, 0) is False


def test_retry_delay_exponential_and_capped():
    base, cap = 300, 3600
    assert retry_delay_seconds(1, base, cap) == 300      # base
    assert retry_delay_seconds(2, base, cap) == 600      # 2x
    assert retry_delay_seconds(3, base, cap) == 1200     # 4x
    assert retry_delay_seconds(4, base, cap) == 2400     # 8x
    assert retry_delay_seconds(5, base, cap) == 3600     # 16x -> capped
    assert retry_delay_seconds(50, base, cap) == 3600    # far past cap, no overflow


def test_retry_delay_floors_attempt_and_base():
    # attempt <= 0 is treated as 1 (never a zero/negative wait).
    assert retry_delay_seconds(0, 300, 3600) == 300
    assert retry_delay_seconds(-3, 300, 3600) == 300
    # cap below base is floored to base (delay never below base).
    assert retry_delay_seconds(1, 300, 10) == 300
