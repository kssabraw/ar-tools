"""Unit tests for the admin Cost & Usage Report pure aggregation helpers.

No network — labelling, cost/token summation, and the by-type / by-client /
by-member / daily rollups with previous-period deltas. build_report's DB reads
are covered by integration against the cost_events view.
"""

from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# cost_analytics imports deliverables_analytics, which imports db.supabase_client
# at load. Stub it (pure tests never touch the DB) — see test_deliverables_analytics.
if "db.supabase_client" not in sys.modules:
    sys.modules.setdefault("db", types.ModuleType("db"))
    _fake_db = types.ModuleType("db.supabase_client")
    _fake_db.get_supabase = lambda: None  # type: ignore[attr-defined]
    sys.modules["db.supabase_client"] = _fake_db

from services import cost_analytics as ca  # noqa: E402


def _ev(cost_type, cost, tin=0, tout=0, client_id=None, actor_id=None, actor_name=None, occurred_at=None, model=None):
    return {
        "cost_type": cost_type, "cost_usd": cost, "input_tokens": tin, "output_tokens": tout,
        "client_id": client_id, "actor_id": actor_id, "actor_name": actor_name,
        "occurred_at": occurred_at, "model": model,
    }


def test_label_and_group():
    assert ca.label_for("local_seo_page") == "Local SEO page"
    assert ca.label_for("autonomy_run") == "Autonomy run"
    assert ca.label_for("mystery_thing") == "Mystery Thing"
    assert ca.group_for("blog_post") == "Content pages"
    assert ca.group_for("ecommerce_product") == "Content pages"
    assert ca.group_for("keyword_research") == "Research"
    # autonomy + strategist are agent runs
    assert ca.group_for("autonomy_run") == "Agents"


def test_leadoff_and_strategist_labels_and_groups():
    assert ca.label_for("strategist_review") == "Strategist review"
    assert ca.group_for("strategist_review") == "Agents"
    assert ca.label_for("leadoff_scout") == "LeadOff scout"
    assert ca.label_for("leadoff_ai_probe") == "LeadOff AI probe"
    # unmapped leadoff action → readable "LeadOff <action>" fallback
    assert ca.label_for("leadoff_something_new") == "LeadOff something new"
    assert ca.group_for("leadoff_scout") == "Market research"
    assert ca.group_for("leadoff_something_new") == "Market research"


def test_qa_review_label_and_group():
    assert ca.label_for("qa_review") == "QA review"
    assert ca.group_for("qa_review") == "Agents"


def test_aggregate_sums_cost_and_tokens():
    events = [
        _ev("local_seo_page", 0.35, 1500, 1200, client_id="c1", actor_id="p1", occurred_at="2026-09-01T10:00:00Z"),
        _ev("local_seo_page", 0.25, 1000, 800, client_id="c1", actor_id="p1", occurred_at="2026-09-01T12:00:00Z"),
        _ev("blog_post", 0.50, 0, 0, client_id="c2", actor_id="p2", occurred_at="2026-09-02T09:00:00Z"),
        _ev("keyword_research", 0.20, 0, 0, client_id=None, occurred_at="2026-09-02T09:30:00Z"),
    ]
    agg = ca.aggregate(events)
    assert round(agg["total"]["cost"], 2) == 1.30
    assert agg["total"]["input_tokens"] == 2500
    assert agg["total"]["output_tokens"] == 2000
    assert agg["total"]["events"] == 4
    assert round(agg["by_type"]["local_seo_page"]["cost"], 2) == 0.60
    assert agg["by_type"]["local_seo_page"]["input_tokens"] == 2500
    assert round(agg["by_client"]["c1"]["cost"], 2) == 0.60
    assert agg["by_client"][None]["events"] == 1  # keyword_research has no client
    assert agg["by_member"][("profile", "p1")]["events"] == 2
    assert round(agg["by_day"]["2026-09-02"]["cost"], 2) == 0.70


def test_build_type_rows_with_prev_deltas():
    cur = ca.aggregate([_ev("local_seo_page", 1.00, 100, 50, client_id="c1")])["by_type"]
    prev = ca.aggregate([_ev("local_seo_page", 0.40, 60, 40, client_id="c1"),
                         _ev("blog_post", 0.30, 0, 0, client_id="c1")])["by_type"]
    rows = {r["type"]: r for r in ca.build_type_rows(cur, prev)}
    ls = rows["local_seo_page"]
    assert ls["cost"] == 1.0 and ls["prev_cost"] == 0.4 and ls["cost_delta"] == 0.6
    assert ls["tokens"] == 150 and ls["prev_tokens"] == 100 and ls["tokens_delta"] == 50
    # blog_post ran last period, none this period → surfaces with negative deltas
    assert rows["blog_post"]["cost"] == 0.0 and rows["blog_post"]["cost_delta"] == -0.3


def test_build_client_rows_names_and_internal_bucket():
    cur = ca.aggregate([_ev("blog_post", 0.5, client_id="c1"), _ev("keyword_research", 0.2, client_id=None)])["by_client"]
    rows = ca.build_client_rows(cur, {"c1": "Acme"})
    by_name = {r["client_name"]: r for r in rows}
    assert by_name["Acme"]["cost"] == 0.5
    assert by_name[ca.da._NO_CLIENT]["cost"] == 0.2


def test_build_member_rows_assignee_and_system():
    by_member = ca.aggregate([
        _ev("task_x", 0.0, client_id="c1", actor_name="Ivy"),  # name bucket
        _ev("blog_post", 0.5, client_id="c1", actor_id="p1"),   # profile bucket
        _ev("keyword_research", 0.2, client_id="c1"),           # system bucket
    ])["by_member"]
    rows = {r["member"]: r for r in ca.build_member_rows(by_member, {"p1": "Kyle"})}
    assert rows["Ivy"]["events"] == 1
    assert rows["Kyle"]["cost"] == 0.5
    assert rows[ca.da._SYSTEM_MEMBER]["cost"] == 0.2


def test_model_label_for():
    assert ca.model_label_for("claude-sonnet-4-6") == "Claude Sonnet 4.6"
    assert ca.model_label_for("gpt-5.6-luna") == "OpenAI GPT-5.6 (Luna)"
    assert ca.model_label_for("mixed") == "Blog/service pipeline (mixed models)"
    # null → non-LLM bucket
    assert "Non-LLM" in ca.model_label_for(None)
    assert "Non-LLM" in ca.model_label_for("")
    # unmapped ids → readable, provider-prefixed fallbacks (future models)
    assert ca.model_label_for("claude-haiku-9") == "Claude Haiku"
    assert ca.model_label_for("claude-opus-5") == "Claude Opus"
    assert ca.model_label_for("gpt-4.1") == "OpenAI gpt-4.1"


def test_aggregate_and_build_model_rows():
    events = [
        _ev("local_seo_page", 0.60, 100, 50, model="claude-sonnet-4-6"),
        _ev("ecommerce_product", 0.20, 40, 20, model="gpt-5.6-luna"),
        _ev("blog_post", 0.50, 10, 5, model="mixed"),
        _ev("keyword_research", 0.30, 0, 0, model=None),  # non-LLM
        _ev("qa_review", 0.01, 5, 1, model=""),            # empty → non-LLM sentinel
    ]
    by_model = ca.aggregate(events)["by_model"]
    assert round(by_model["claude-sonnet-4-6"]["cost"], 2) == 0.60
    assert by_model["gpt-5.6-luna"]["input_tokens"] == 40
    # both the None and "" model land in the same non-LLM sentinel bucket
    assert round(by_model[ca._NON_LLM_KEY]["cost"], 2) == 0.31
    assert by_model[ca._NON_LLM_KEY]["events"] == 2

    rows = {r["model"]: r for r in ca.build_model_rows(by_model)}
    assert rows["gpt-5.6-luna"]["label"] == "OpenAI GPT-5.6 (Luna)"
    assert "Non-LLM" in rows[ca._NON_LLM_KEY]["label"]
    # sorted by cost desc → Sonnet ($0.60) first
    assert ca.build_model_rows(by_model)[0]["model"] == "claude-sonnet-4-6"


def test_build_model_rows_prev_deltas():
    cur = ca.aggregate([_ev("local_seo_page", 1.0, 100, 50, model="claude-sonnet-4-6")])["by_model"]
    prev = ca.aggregate([
        _ev("local_seo_page", 0.4, 60, 40, model="claude-sonnet-4-6"),
        _ev("ecommerce_product", 0.3, 10, 5, model="gpt-5.6-luna"),
    ])["by_model"]
    rows = {r["model"]: r for r in ca.build_model_rows(cur, prev)}
    assert rows["claude-sonnet-4-6"]["cost_delta"] == 0.6
    # Luna ran last period, none this period → surfaces with a negative delta
    assert rows["gpt-5.6-luna"]["cost"] == 0.0 and rows["gpt-5.6-luna"]["cost_delta"] == -0.3


def test_daily_series_zero_filled():
    by_day = ca.aggregate([_ev("blog_post", 0.5, 0, 0, occurred_at="2026-09-02T00:00:00Z")])["by_day"]
    series = ca.build_daily_series(by_day, date(2026, 9, 1), date(2026, 9, 3))
    assert series == [
        {"date": "2026-09-01", "cost": 0.0, "tokens": 0},
        {"date": "2026-09-02", "cost": 0.5, "tokens": 0},
        {"date": "2026-09-03", "cost": 0.0, "tokens": 0},
    ]


def test_total_block_deltas():
    cur = ca.aggregate([_ev("local_seo_page", 1.0, 100, 100)])["total"]
    prev = ca.aggregate([_ev("local_seo_page", 0.6, 40, 60)])["total"]
    tb = ca.total_block(cur, prev)
    assert tb["cost"] == 1.0 and tb["cost_delta"] == 0.4
    assert tb["tokens"] == 200 and tb["prev_tokens"] == 100 and tb["tokens_delta"] == 100
