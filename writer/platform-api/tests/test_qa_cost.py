"""Unit tests for the QA per-review cost/token accumulator (services/qa_cost.py).

Pure contextvar accounting — no network. Mirrors the blog cost tally.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import qa_cost  # noqa: E402


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Msg:
    def __init__(self, i, o):
        self.usage = _Usage(i, o)


def test_noop_when_not_started():
    # A stray record outside a review must not raise or leak into the next review.
    qa_cost.record_from_message(_Msg(100, 50), "claude-haiku-4-5")
    assert qa_cost.total_cost() == 0.0
    assert qa_cost.total_tokens() == {"input_tokens": 0, "output_tokens": 0}


def test_accumulates_tokens_and_cost_haiku():
    qa_cost.start_accounting()
    qa_cost.record_from_message(_Msg(1_000_000, 1_000_000), "claude-haiku-4-5-20251001")
    qa_cost.record_from_message(_Msg(500_000, 0), "claude-haiku-4-5-20251001")
    assert qa_cost.total_tokens() == {"input_tokens": 1_500_000, "output_tokens": 1_000_000}
    # Haiku $1 in / $5 out per 1M: 1.5*1 + 1.0*5 = 6.50
    assert qa_cost.total_cost() == 6.5


def test_unknown_model_falls_back_to_haiku():
    qa_cost.start_accounting()
    qa_cost.record_from_message(_Msg(1_000_000, 0), "some-unknown-model")
    assert qa_cost.total_cost() == 1.0  # haiku input price


def test_missing_usage_is_ignored():
    qa_cost.start_accounting()
    qa_cost.record_from_message(object(), "claude-haiku-4-5")  # no .usage
    assert qa_cost.total_tokens() == {"input_tokens": 0, "output_tokens": 0}
    assert qa_cost.total_cost() == 0.0
