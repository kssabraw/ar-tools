"""Unit tests for the Slack assistant pure helpers (no network)."""

from __future__ import annotations

import hashlib
import hmac

from services import slack_assistant

# The package facade re-exports everything, so calls go through
# `slack_assistant.…` unchanged — but monkeypatching must target the DEFINING
# submodule (patching a re-exported name on the facade doesn't rebind the
# implementation module's global).
from services.slack_assistant import actions as sa_actions
from services.slack_assistant import context as sa_context


SECRET = "shhh-signing-secret"


def _sign(timestamp: str, body: str, secret: str = SECRET) -> str:
    base = f"v0:{timestamp}:{body}".encode()
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# verify_slack_signature
# ---------------------------------------------------------------------------
def test_signature_valid():
    ts, body = "1000000", '{"type":"event_callback"}'
    sig = _sign(ts, body)
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000005) is True


def test_signature_wrong_secret_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body, secret="other")
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000005) is False


def test_signature_tampered_body_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body)
    assert slack_assistant.verify_slack_signature(SECRET, ts, "{tampered}", sig, now_ts=1000005) is False


def test_signature_stale_timestamp_rejected():
    ts, body = "1000000", "{}"
    sig = _sign(ts, body)
    # 10 minutes later → outside the 5-min replay window.
    assert slack_assistant.verify_slack_signature(SECRET, ts, body, sig, now_ts=1000000 + 600) is False


def test_signature_missing_pieces_fail_closed():
    assert slack_assistant.verify_slack_signature("", "1", "b", "v0=x", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "", "b", "v0=x", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "1", "b", "", 1) is False
    assert slack_assistant.verify_slack_signature(SECRET, "notanint", "b", "v0=x", 1) is False


# ---------------------------------------------------------------------------
# strip_mention
# ---------------------------------------------------------------------------
def test_strip_mention():
    assert slack_assistant.strip_mention("<@U12345> how is Acme?") == "how is Acme?"
    assert slack_assistant.strip_mention("hey <@U1> and <@U2> ping") == "hey  and  ping".strip()
    assert slack_assistant.strip_mention("   ") == ""
    assert slack_assistant.strip_mention(None) == ""


# ---------------------------------------------------------------------------
# resolve_client
# ---------------------------------------------------------------------------
_CLIENTS = [
    {"id": "1", "name": "Acme"},
    {"id": "2", "name": "Acme Plumbing"},
    {"id": "3", "name": "Bright Dental"},
]


def test_resolve_prefers_longest_full_name():
    c = slack_assistant.resolve_client("how is acme plumbing doing this month?", _CLIENTS)
    assert c["id"] == "2"


def test_resolve_exact_short_name():
    c = slack_assistant.resolve_client("any drops for Acme?", _CLIENTS)
    assert c["id"] == "1"


def test_resolve_token_overlap_fallback():
    # "dental" isn't the full name but is a distinctive token of "Bright Dental".
    c = slack_assistant.resolve_client("hows the dental account", _CLIENTS)
    assert c["id"] == "3"


def test_resolve_none_when_no_match():
    assert slack_assistant.resolve_client("how are rankings overall?", _CLIENTS) is None
    assert slack_assistant.resolve_client("", _CLIENTS) is None


def test_resolve_ignores_generic_tokens():
    # "services" is a stop word — shouldn't match a client named "... Services".
    clients = [{"id": "9", "name": "Premier Services"}]
    assert slack_assistant.resolve_client("what about our other services", clients) is None


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# build_context registry behavior (providers isolated; empties omitted)
# ---------------------------------------------------------------------------
def test_build_context_assembles_isolates_and_omits(monkeypatch):
    monkeypatch.setattr(sa_context, "get_supabase", lambda: object())

    def good(sb, cid, today):
        return {"ok": True}

    def empty(sb, cid, today):
        return None

    def boom(sb, cid, today):
        raise RuntimeError("module down")

    monkeypatch.setattr(
        sa_context,
        "_CONTEXT_PROVIDERS",
        [("alpha", good), ("beta", empty), ("gamma", boom)],
    )
    ctx = slack_assistant.build_context("client-1")
    assert ctx == {"alpha": {"ok": True}}  # empty omitted, failing one isolated


def test_ctx_setup_exposes_full_gbp_profile():
    from datetime import date
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {
            "website_url": "https://firstclassroofing.com",
            "gbp_place_id": "ChIJabc123",
            "gbp": {
                "business_name": "First Class Roofing",
                "address": "123 Main St, Wooster, OH 44691",
                "latitude": 40.805,
                "longitude": -81.935,
                "phone": "(330) 555-0100",
                "gbp_category": "Roofing contractor",
                "gbp_categories": ["Roofing contractor", "Gutter service"],
                "gbp_rating": 4.9,
                "gbp_review_count": 120,
                "reviews": [{"text": "bulky — must not pass through"}],
            },
            "brand_voice": {"tone": "warm"},
            "detected_icp": None,
            "differentiators": None,
            "icp_text": None,
            "target_cities": ["Wooster", "Orrville"],
            "retainer_monthly": 2500,
            "is_sab": False,
            "client_type": "local",
        }
    ]

    out = slack_assistant._ctx_setup(supabase, "c1", date(2026, 7, 7))
    gbp = out["gbp"]
    assert gbp["address"] == "123 Main St, Wooster, OH 44691"
    assert gbp["latitude"] == 40.805 and gbp["longitude"] == -81.935
    assert gbp["phone"] == "(330) 555-0100"
    assert gbp["place_id"] == "ChIJabc123"
    assert gbp["rating"] == 4.9 and gbp["review_count"] == 120
    assert "reviews" not in gbp  # bulky raw assets stay out
    assert out["target_cities"] == ["Wooster", "Orrville"]
    assert out["client_type"] == "local"
    assert out["has_brand_voice"] is True


def test_ctx_task_plan_maps_plan_lines():
    from datetime import date
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {
            "month": "2026-07-01",
            "margin_used": 0.34,
            "deployable": 850,
            "spent": 700,
            "remaining": 150,
            "flags": ["capacity_capped"],
            "plan": {
                "diagnosis": {"deficient": ["referring_domains"]},
                "tasks": [
                    {"task_type": "citations", "label": "40 Citations", "quantity": 1,
                     "unit_cost": 40.0, "line_cost": 40.0, "assignee": "Minda"},
                ],
            },
        }
    ]
    out = slack_assistant._ctx_task_plan(supabase, "c1", date(2026, 7, 7))
    assert out["deployable"] == 850
    assert out["flags"] == ["capacity_capped"]
    assert out["tasks"] == [
        {"task": "40 Citations", "quantity": 1, "line_cost": 40.0, "assignee": "Minda"}
    ]
    assert out["diagnosis"] == {"deficient": ["referring_domains"]}


def test_ctx_strategist_shapes_and_truncates():
    from datetime import date
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {
            "assessment": "x" * 2000,
            "proposals": [{"title": f"P{i}", "status": "proposed", "requires": "approval",
                           "rationale": "long text that must not pass through"} for i in range(12)],
            "questions": [f"Q{i}" for i in range(9)],
            "trigger": "scheduled",
            "created_at": "2026-07-06T00:00:00Z",
        }
    ]
    out = slack_assistant._ctx_strategist(supabase, "c1", date(2026, 7, 7))
    assert len(out["assessment"]) == 1200
    assert len(out["proposals"]) == 8
    assert out["proposals"][0] == {"title": "P0", "status": "proposed", "requires": "approval"}
    assert out["questions"] == [f"Q{i}" for i in range(5)]


def test_stage_live_serp_requires_keyword():
    import asyncio

    outcome, reply = asyncio.run(slack_assistant._stage_live_serp("c1", {}))
    assert outcome == "reply"
    assert "keyword" in reply.lower()

    outcome, staged = asyncio.run(
        slack_assistant._stage_live_serp("c1", {"keyword": "roof repair akron"})
    )
    assert outcome == "confirm"
    assert "roof repair akron" in staged["_confirm"]


def test_run_live_gsc_reports_unconfigured(monkeypatch):
    import asyncio

    from services import gsc_service

    monkeypatch.setattr(gsc_service, "is_configured", lambda: False)
    out = asyncio.run(slack_assistant._run_live_gsc("c1", {"dimension": "query"}))
    assert "not configured" in out


def test_list_nonindexed_reports_unconfigured(monkeypatch):
    import asyncio

    from services import gsc_service

    monkeypatch.setattr(gsc_service, "is_configured", lambda: False)
    out = asyncio.run(slack_assistant._run_list_nonindexed("c1", {}))
    assert "not configured" in out


def test_list_nonindexed_collects_reasons_and_skips_indexed(monkeypatch):
    """The sweep keeps only non-PASS pages, tagging each with its coverage
    reason, and never lets one failing inspection sink the batch."""
    import asyncio
    import json

    from services import gsc_service, rank_materialize, site_page_index
    from services import dataforseo_rank

    monkeypatch.setattr(gsc_service, "is_configured", lambda: True)
    monkeypatch.setattr(
        rank_materialize, "_verified_property", lambda sb, cid: {"site_url": "https://ex.com/"}
    )
    # Client row + locale.
    class _Resp:
        data = [{"website_url": "https://ex.com/"}]

    class _Q:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return _Resp()

    monkeypatch.setattr(
        slack_assistant.llm, "get_supabase",
        lambda: type("S", (), {"table": lambda self, *a: _Q()})(),
    )
    monkeypatch.setattr(dataforseo_rank, "location_code_for", lambda row: 2840)

    async def _discover(website, loc):
        return (
            ["https://ex.com/a", "https://ex.com/b", "https://ex.com/c", "https://ex.com/d"],
            "sitemap",
        )

    monkeypatch.setattr(site_page_index, "discover_site_urls", _discover)

    verdicts = {
        "https://ex.com/a": {"verdict": "PASS", "coverage_state": "Submitted and indexed"},
        "https://ex.com/b": {"verdict": "NEUTRAL", "coverage_state": "Crawled - currently not indexed"},
        "https://ex.com/c": {"verdict": "NEUTRAL", "coverage_state": "Page with redirect"},
        # /d raises — must be captured as an inspection error, not a crash.
    }

    def _inspect(site_url, url):
        if url == "https://ex.com/d":
            raise RuntimeError("quota exceeded")
        return verdicts[url]

    monkeypatch.setattr(gsc_service, "inspect_url", _inspect)

    out = asyncio.run(slack_assistant._run_list_nonindexed("c1", {}))
    payload = json.loads(out)
    assert payload["indexed_count"] == 1
    assert payload["nonindexed_count"] == 2
    reasons = {r["url"]: r["reason"] for r in payload["nonindexed"]}
    assert reasons["https://ex.com/b"] == "Crawled - currently not indexed"
    assert reasons["https://ex.com/c"] == "Page with redirect"
    assert payload["inspection_errors"] and payload["inspection_errors"][0]["url"] == "https://ex.com/d"


# ---------------------------------------------------------------------------
# Maps geo-grid trend helpers (pure) + the maps_history tool + _ctx_maps trend
# ---------------------------------------------------------------------------
class _FakeExec:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """A chainable no-op query; each execute() pops the next canned result for
    its table (FIFO, so multiple same-table queries return in call order)."""

    def __init__(self, queue):
        self._queue = queue

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _FakeExec(self._queue.pop(0) if self._queue else [])


class _FakeSupabase:
    def __init__(self, by_table):
        self._by_table = {t: list(v) for t, v in by_table.items()}

    def table(self, name):
        return _FakeQuery(self._by_table.setdefault(name, []))


def test_maps_series_point_pack_presence():
    pt = slack_assistant.maps_series_point(
        {"average_rank": 2.0, "found_pins": 10, "total_pins": 25, "top3_pins": 5}, "2026-07-01"
    )
    assert pt["pack_presence_pct"] == 20.0  # 5/25
    assert pt["scanned_at"] == "2026-07-01"
    z = slack_assistant.maps_series_point({"total_pins": 0, "top3_pins": 0}, None)
    assert z["pack_presence_pct"] is None  # zero total never divides


def test_group_maps_series_orders_oldest_first_and_drops_orphans():
    scans = [
        {"id": "s2", "completed_at": "2026-07-08"},
        {"id": "s1", "completed_at": "2026-07-01"},
    ]
    results = [
        {"scan_id": "s1", "keyword": "roofing", "total_pins": 25, "top3_pins": 5},
        {"scan_id": "s2", "keyword": "roofing", "total_pins": 25, "top3_pins": 10},
        {"scan_id": "sX", "keyword": "roofing", "total_pins": 25, "top3_pins": 99},  # orphan
    ]
    series = slack_assistant.group_maps_series(scans, results)
    assert [p["pack_presence_pct"] for p in series["roofing"]] == [20.0, 40.0]


def test_build_maps_trend_direction_and_deltas():
    series = [
        {"pack_presence_pct": 20.0, "average_rank": 4.0, "found_pins": 10, "total_pins": 25, "top3_pins": 5},
        {"pack_presence_pct": 40.0, "average_rank": 2.5, "found_pins": 18, "total_pins": 25, "top3_pins": 10},
    ]
    out = slack_assistant.build_maps_trend("roofing", series)
    assert out["pack_presence_delta"] == 20.0
    assert out["average_rank_delta"] == -1.5  # lower rank = improved
    assert out["direction"] == "improving"
    assert out["pack_presence_series"] == [20.0, 40.0]
    solo = slack_assistant.build_maps_trend("roofing", series[:1])
    assert "direction" not in solo and solo["scans"] == 1  # single scan → no deltas


def test_build_maps_trend_flat_when_movement_is_noise():
    series = [
        {"pack_presence_pct": 40.0, "average_rank": 2.0, "found_pins": 18, "total_pins": 25, "top3_pins": 10},
        {"pack_presence_pct": 41.0, "average_rank": 2.1, "found_pins": 18, "total_pins": 25, "top3_pins": 10},
    ]
    assert slack_assistant.build_maps_trend("x", series)["direction"] == "flat"


def test_run_maps_history_builds_series(monkeypatch):
    import asyncio
    import json

    scans = [
        {"id": "s2", "completed_at": "2026-07-08", "trigger": "scheduled"},
        {"id": "s1", "completed_at": "2026-07-01", "trigger": "manual"},
    ]
    results = [
        {"scan_id": "s1", "keyword": "roofing wooster", "average_rank": 4.0,
         "found_pins": 10, "total_pins": 25, "top3_pins": 5, "top10_pins": 9},
        {"scan_id": "s2", "keyword": "roofing wooster", "average_rank": 2.5,
         "found_pins": 18, "total_pins": 25, "top3_pins": 12, "top10_pins": 20},
    ]
    alerts = [{"keyword": "roofing wooster", "alert_type": "maps_decline",
               "message": "drop", "created_at": "2026-07-08", "resolved_at": None}]
    fake = _FakeSupabase(
        {"maps_scans": [scans], "maps_scan_results": [results], "maps_alerts": [alerts]}
    )
    monkeypatch.setattr(slack_assistant.llm, "get_supabase", lambda: fake)
    out = asyncio.run(slack_assistant._run_maps_history("c1", {}))
    payload = json.loads(out)
    assert payload["scans_analyzed"] == 2
    kw = payload["keywords"][0]
    assert kw["keyword"] == "roofing wooster"
    assert kw["summary"]["direction"] == "improving"
    assert [p["pack_presence_pct"] for p in kw["series_oldest_first"]] == [20.0, 48.0]
    assert payload["recent_alerts"]


def test_run_maps_history_no_scans(monkeypatch):
    import asyncio

    fake = _FakeSupabase({"maps_scans": [[]]})
    monkeypatch.setattr(slack_assistant.llm, "get_supabase", lambda: fake)
    out = asyncio.run(slack_assistant._run_maps_history("c1", {}))
    assert "No completed geo-grid scans" in out


def test_ctx_maps_includes_trend_over_completed_scans():
    from datetime import date

    latest_scan = [{"id": "s2", "status": "complete", "created_at": "2026-07-08"}]
    latest_results = [{"keyword": "roofing", "average_rank": 2.5, "top3_pins": 12,
                       "top10_pins": 20, "report_weak_locations": None}]
    completed = [
        {"id": "s2", "completed_at": "2026-07-08"},
        {"id": "s1", "completed_at": "2026-07-01"},
    ]
    trend_results = [
        {"scan_id": "s1", "keyword": "roofing", "average_rank": 4.0,
         "found_pins": 10, "total_pins": 25, "top3_pins": 5},
        {"scan_id": "s2", "keyword": "roofing", "average_rank": 2.5,
         "found_pins": 18, "total_pins": 25, "top3_pins": 12},
    ]
    fake = _FakeSupabase({
        "maps_scans": [latest_scan, completed],
        "maps_scan_results": [latest_results, trend_results],
        "maps_alerts": [[]],
    })
    out = slack_assistant._ctx_maps(fake, "c1", date(2026, 7, 8))
    assert out["latest_scan_status"] == "complete"
    assert "trend" in out and "trend_note" in out
    t = out["trend"][0]
    assert t["keyword"] == "roofing" and t["direction"] == "improving"


def test_context_providers_cover_all_modules():
    keys = [k for k, _ in slack_assistant._CONTEXT_PROVIDERS]
    for expected in (
        "campaign_goals", "competitors", "forecast", "trends", "organic_rank",
        "maps_geogrid", "ai_visibility", "content", "keyword_research",
        "task_plan", "citations", "syndication", "reports", "sops", "asana",
        "health", "strategist_review", "setup",
    ):
        assert expected in keys


def test_format_history_labels_roles_and_skips_empty():
    out = slack_assistant.format_history([
        {"role": "user", "content": "how is Acme?"},
        {"role": "assistant", "content": "Acme is #4, steady."},
        {"role": "user", "content": "  "},
        {"role": "user", "content": "what about Maps?"},
    ])
    assert out == (
        "Teammate: how is Acme?\n"
        "SerMastr: Acme is #4, steady.\n"
        "Teammate: what about Maps?"
    )


def test_format_history_empty():
    assert slack_assistant.format_history([]) == ""


# ---------------------------------------------------------------------------
# weak_cities (shape-tolerant — the real stored value is an object, not a list)
# ---------------------------------------------------------------------------
def test_weak_cities_from_object_shape():
    rwl = {"geocoded": True, "capped": False, "weak_areas": [
        {"city": "Port Melbourne", "pins": 5},
        {"city": "Toorak", "pins": 3},
        {"pins": 1},  # no city → skipped
    ]}
    assert slack_assistant.weak_cities(rwl) == ["Port Melbourne", "Toorak"]


def test_weak_cities_from_list_shape():
    assert slack_assistant.weak_cities([{"city": "A"}, {"city": "B"}]) == ["A", "B"]


def test_weak_cities_tolerates_none_and_junk():
    assert slack_assistant.weak_cities(None) == []
    assert slack_assistant.weak_cities("oops") == []
    assert slack_assistant.weak_cities({"weak_areas": None}) == []


def test_weak_cities_caps_at_five():
    rwl = {"weak_areas": [{"city": f"C{i}"} for i in range(9)]}
    assert slack_assistant.weak_cities(rwl) == ["C0", "C1", "C2", "C3", "C4"]


# ---------------------------------------------------------------------------
# is_affirmative (confirmation of a pending paid action)
# ---------------------------------------------------------------------------
def test_is_affirmative_accepts_yeses():
    for t in ["yes", "Yes", "YES!", "yep", "yeah", "confirm", "do it", "go ahead",
              "proceed", "ok", "sure", "yes please", "yes, go"]:
        assert slack_assistant.is_affirmative(t) is True, t


def test_is_affirmative_rejects_others():
    for t in ["no", "not yet", "what?", "how is acme", "yesterday", "", "maybe"]:
        assert slack_assistant.is_affirmative(t) is False, t


# ---------------------------------------------------------------------------
# action registry/tools consistency
# ---------------------------------------------------------------------------
def test_action_tools_match_registry():
    tool_names = {t["name"] for t in slack_assistant._ACTION_TOOLS}
    assert tool_names == set(slack_assistant._ACTIONS)
    for meta in slack_assistant._ACTIONS.values():
        assert callable(meta["run"])
        assert isinstance(meta["paid"], bool)
    # exactly one free action (rebuild plan), the scans are paid.
    assert slack_assistant._ACTIONS["rebuild_action_plan"]["paid"] is False
    assert all(slack_assistant._ACTIONS[k]["paid"] for k in
               ("run_maps_scan", "run_gsc_research", "run_ai_visibility_scan"))
    # the Asana push isn't API spend but still confirm-gated (creates real
    # tasks) — with its own confirm wording.
    push = slack_assistant._ACTIONS["push_task_plan"]
    assert push["paid"] is True
    assert "Asana" in push["note"]
    # the task-management actions are parameterized + staged, and their tool
    # schemas carry the params so Claude can fill them.
    for name in ("add_asana_task", "remove_asana_task", "complete_asana_task"):
        meta = slack_assistant._ACTIONS[name]
        assert meta["paid"] is True and callable(meta["stage"])
        tool = next(t for t in slack_assistant._ACTION_TOOLS if t["name"] == name)
        assert "task_name" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["task_name"]


# ---------------------------------------------------------------------------
# conversational task management
# ---------------------------------------------------------------------------
def test_match_open_tasks_exact_beats_substring_and_skips_completed():
    tasks = [
        {"gid": "1", "name": "Citations", "completed": False},
        {"gid": "2", "name": "Citations — batch 2", "completed": False},
        {"gid": "3", "name": "Citations — batch 3", "completed": True},
    ]
    # exact name → only that task, even though others contain the query
    assert [t["gid"] for t in slack_assistant.match_open_tasks(tasks, "citations")] == ["1"]
    # substring → open matches only (the completed batch 3 never surfaces)
    assert [t["gid"] for t in slack_assistant.match_open_tasks(tasks, "batch")] == ["2"]
    assert slack_assistant.match_open_tasks(tasks, "") == []
    assert slack_assistant.match_open_tasks(tasks, "nothing") == []


def test_stage_pick_task_resolves_disambiguates_and_guards(monkeypatch):
    import asyncio

    from services import asana_service

    monkeypatch.setattr(sa_actions, "_asana_ready", lambda cid: ("777", None))
    tasks = [
        {"gid": "t1", "name": "Fix GBP categories", "completed": False,
         "assignee": {"name": "Ivy Gervacio"}},
        {"gid": "t2", "name": "Fix citations", "completed": False, "assignee": None},
    ]

    async def fake_list(project_gid):
        return tasks

    monkeypatch.setattr(asana_service, "list_project_tasks", fake_list)

    # one match → staged with the exact gid + a confirm naming task & assignee
    outcome, staged = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "gbp"}, "permanently delete")
    )
    assert outcome == "confirm"
    assert staged["task_gid"] == "t1"
    assert "Fix GBP categories" in staged["_confirm"] and "Ivy Gervacio" in staged["_confirm"]

    # several matches → immediate disambiguation reply, nothing staged
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "fix"}, "permanently delete")
    )
    assert outcome == "reply" and "matches 2 open tasks" in reply

    # no match → the open tasks are listed back
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "zzz"}, "permanently delete")
    )
    assert outcome == "reply" and "Fix GBP categories" in reply

    # unready Asana → the guard's guidance passes straight through
    monkeypatch.setattr(sa_actions, "_asana_ready", lambda cid: (None, "not set up"))
    outcome, reply = asyncio.run(
        slack_assistant._stage_pick_task("c1", {"task_name": "gbp"}, "permanently delete")
    )
    assert outcome == "reply" and reply == "not set up"


def test_stage_add_task_matches_assignee_and_flags_unknown(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    monkeypatch.setattr(sa_actions, "_asana_ready", lambda cid: ("777", None))
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"gid": "g1", "name": "Ivy Gervacio"},
    ]
    monkeypatch.setattr(sa_actions, "get_supabase", lambda: supabase)

    # An explicit due date wins and is echoed in the confirm.
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task(
            "c1", {"task_name": "Audit citations", "assignee": "Ivy", "due_date": "2026-12-31"}
        )
    )
    assert outcome == "confirm"
    assert staged["assignee_gid"] == "g1"
    assert "Ivy Gervacio" in staged["_confirm"]
    assert staged["due_date"] == "2026-12-31"
    assert "due 2026-12-31" in staged["_confirm"]

    # No explicit date + a matching SOP task → the delivery turnaround defaults
    # the due date, and the confirm cites the SOP.
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task(
            "c1", {"task_name": "Order a niche edit", "sop_task": "Niche edit"}
        )
    )
    assert outcome == "confirm"
    assert staged["due_date"] is not None
    assert "SOP delivery: 2 weeks for Niche edit" in staged["_confirm"]

    # No explicit date + no matching SOP task → ask the teammate to confirm.
    outcome, reply = asyncio.run(
        slack_assistant._stage_add_task("c1", {"task_name": "Fix GBP categories"})
    )
    assert outcome == "reply"
    assert "due date" in reply.lower()

    # A recurring-cadence SOP task (no concrete turnaround) also asks.
    outcome, reply = asyncio.run(
        slack_assistant._stage_add_task(
            "c1", {"task_name": "Do the reporting", "sop_task": "Monthly reporting (per client)"}
        )
    )
    assert outcome == "reply"

    # Explicit opt-out → create with no due date.
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task(
            "c1", {"task_name": "Ad-hoc thing", "no_due_date": True}
        )
    )
    assert outcome == "confirm"
    assert staged["due_date"] is None
    assert "no due date" in staged["_confirm"]

    # A malformed explicit due date is rejected before anything is staged.
    outcome, reply = asyncio.run(
        slack_assistant._stage_add_task("c1", {"task_name": "Audit citations", "due_date": "Friday"})
    )
    assert outcome == "reply"
    assert "YYYY-MM-DD" in reply

    # Unknown assignee is flagged (using no_due_date to isolate the assignee path).
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_task(
            "c1", {"task_name": "Audit citations", "assignee": "Bob", "no_due_date": True}
        )
    )
    assert outcome == "confirm"
    assert staged["assignee_gid"] is None
    assert "couldn't match" in staged["_confirm"]

    # Missing task name is caught first.
    outcome, reply = asyncio.run(slack_assistant._stage_add_task("c1", {}))
    assert outcome == "reply"


def test_run_action_awaits_async_runners(monkeypatch):
    import asyncio

    async def async_runner(client_id, args=None):
        return f"async:{client_id}"

    def sync_runner(client_id, args=None):
        return f"sync:{client_id}"

    monkeypatch.setitem(slack_assistant._ACTIONS, "add_asana_task",
                        {**slack_assistant._ACTIONS["add_asana_task"], "run": async_runner})
    monkeypatch.setitem(slack_assistant._ACTIONS, "rebuild_action_plan",
                        {**slack_assistant._ACTIONS["rebuild_action_plan"], "run": sync_runner})
    assert asyncio.run(slack_assistant._run_action("add_asana_task", "c1", {})) == "async:c1"
    assert asyncio.run(slack_assistant._run_action("rebuild_action_plan", "c1", None)) == "sync:c1"


def test_push_task_plan_action_guards_and_enqueues(monkeypatch):
    from unittest.mock import MagicMock

    from services import asana_monthly, asana_push, asana_service

    monkeypatch.setattr(asana_service, "is_configured", lambda: True)
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: "777")

    # no plan row → guidance, nothing enqueued
    supabase = MagicMock()
    chain = supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute
    chain.return_value.data = []
    monkeypatch.setattr(sa_actions, "get_supabase", lambda: supabase)
    enqueued = []
    monkeypatch.setattr(asana_push, "enqueue_asana_push", lambda cid, pid: enqueued.append((cid, pid)))
    out = slack_assistant._act_push_task_plan("c1")
    assert "No monthly task plan" in out and not enqueued

    # empty plan → guidance, nothing enqueued
    chain.return_value.data = [{"id": "p1", "month": "2026-07-01", "plan": {"tasks": []}}]
    out = slack_assistant._act_push_task_plan("c1")
    assert "no task lines" in out and not enqueued

    # real plan → enqueued
    chain.return_value.data = [{"id": "p1", "month": "2026-07-01", "plan": {"tasks": [{"task_type": "das_v2"}]}}]
    out = slack_assistant._act_push_task_plan("c1")
    assert enqueued == [("c1", "p1")]
    assert "Pushing the latest task plan" in out

    # unmapped project → guidance
    monkeypatch.setattr(asana_monthly, "get_project_gid", lambda cid: None)
    out = slack_assistant._act_push_task_plan("c1")
    assert "no Asana project mapped" in out


def test_format_context_is_json_with_client():
    import json

    out = slack_assistant.format_context(
        {"name": "Acme", "website_url": "https://acme.com"},
        {"keyword_count": 3, "open_drop_alerts": []},
    )
    parsed = json.loads(out)
    assert parsed["client"]["name"] == "Acme"
    assert parsed["client"]["website"] == "https://acme.com"
    assert parsed["keyword_count"] == 3


# ---------------------------------------------------------------------------
# admin actions — pure helpers
# ---------------------------------------------------------------------------
def test_match_named_exact_beats_substring():
    rows = [
        {"id": "1", "keyword": "roof repair"},
        {"id": "2", "keyword": "roof repair near me"},
    ]
    assert [r["id"] for r in slack_assistant.match_named(rows, "roof repair", key="keyword")] == ["1"]
    assert [r["id"] for r in slack_assistant.match_named(rows, "near", key="keyword")] == ["2"]
    assert slack_assistant.match_named(rows, "", key="keyword") == []
    assert slack_assistant.match_named(rows, "zzz", key="keyword") == []


def test_merge_cities_dedupes_case_insensitively():
    merged, added, already = slack_assistant.merge_cities(
        ["Austin", "Round Rock"], ["round rock", "Pflugerville", "  ", "pflugerville"]
    )
    assert merged == ["Austin", "Round Rock", "Pflugerville"]
    assert added == ["Pflugerville"]
    assert already == ["round rock"]


def test_merge_cities_from_empty():
    merged, added, already = slack_assistant.merge_cities(None, ["Austin"])
    assert merged == ["Austin"] and added == ["Austin"] and already == []


def test_drop_cities_matches_stored_casing_and_reports_missing():
    remaining, removed, missing = slack_assistant.drop_cities(
        ["Austin", "Round Rock", "Pflugerville"], ["round rock", "Nowhere"]
    )
    assert remaining == ["Austin", "Pflugerville"]
    assert removed == ["Round Rock"]  # stored casing
    assert missing == ["Nowhere"]


def test_coerce_profile_value_typing():
    assert slack_assistant.coerce_profile_value("retainer_monthly", "$4,500") == (4500.0, None)
    assert slack_assistant.coerce_profile_value("retainer_monthly", "lots")[1] is not None
    assert slack_assistant.coerce_profile_value("client_type", "Enterprise") == ("enterprise", None)
    assert slack_assistant.coerce_profile_value("client_type", "franchise")[1] is not None
    assert slack_assistant.coerce_profile_value("is_sab", "yes") == (True, None)
    assert slack_assistant.coerce_profile_value("is_sab", "no") == (False, None)
    assert slack_assistant.coerce_profile_value("is_sab", "maybe")[1] is not None
    assert slack_assistant.coerce_profile_value("website_url", "acme.com") == ("https://acme.com", None)
    assert slack_assistant.coerce_profile_value("website_url", "https://acme.com") == ("https://acme.com", None)
    assert slack_assistant.coerce_profile_value("gsc_property", " sc-domain:acme.com ") == ("sc-domain:acme.com", None)
    # non-editable / empty → error
    assert slack_assistant.coerce_profile_value("name", "Acme")[1] is not None
    assert slack_assistant.coerce_profile_value("wordpress_app_password", "x")[1] is not None
    assert slack_assistant.coerce_profile_value("website_url", "")[1] is not None


def test_clean_list_trims_and_dedupes():
    assert slack_assistant._clean_list(["  Austin ", "austin", "", None, "Waco"]) == ["Austin", "Waco"]
    assert slack_assistant._clean_list(None) == []


# ---------------------------------------------------------------------------
# admin actions — staging (mocked DB)
# ---------------------------------------------------------------------------
def test_stage_update_profile_confirms_change_and_skips_noop(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        sa_actions, "_client_row", lambda cid, cols: {"retainer_monthly": 3000.0}
    )
    outcome, staged = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "retainer_monthly", "value": "$4,500"})
    )
    assert outcome == "confirm"
    assert staged["coerced_value"] == 4500.0
    assert "$4,500" in staged["_confirm"] and "$3,000" in staged["_confirm"]

    # same value → immediate reply, nothing staged
    outcome, reply = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "retainer_monthly", "value": "3000"})
    )
    assert outcome == "reply" and "already" in reply

    # bad field → the coercion error passes straight through
    outcome, reply = asyncio.run(
        slack_assistant._stage_update_profile("c1", {"field": "name", "value": "X"})
    )
    assert outcome == "reply" and "can't edit" in reply


def test_stage_add_and_remove_cities(monkeypatch):
    import asyncio

    monkeypatch.setattr(
        sa_actions, "_client_row", lambda cid, cols: {"target_cities": ["Austin", "Waco"]}
    )
    outcome, staged = asyncio.run(
        slack_assistant._stage_add_cities("c1", {"cities": ["waco", "Temple"]})
    )
    assert outcome == "confirm"
    assert staged["added"] == ["Temple"] and staged["merged"] == ["Austin", "Waco", "Temple"]
    assert "Temple" in staged["_confirm"] and "already on the list" in staged["_confirm"]

    outcome, reply = asyncio.run(slack_assistant._stage_add_cities("c1", {"cities": ["austin"]}))
    assert outcome == "reply" and "nothing to add" in reply

    outcome, staged = asyncio.run(
        slack_assistant._stage_remove_cities("c1", {"cities": ["WACO"]})
    )
    assert outcome == "confirm" and staged["removed"] == ["Waco"] and staged["remaining"] == ["Austin"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_cities("c1", {"cities": ["Nowhere"]})
    )
    assert outcome == "reply" and "Austin" in reply  # lists current cities back

    outcome, reply = asyncio.run(slack_assistant._stage_add_cities("c1", {}))
    assert outcome == "reply"


def test_stage_add_goal_validates_like_the_api():
    import asyncio

    stage = slack_assistant._stage_add_goal
    # unknown type
    outcome, reply = asyncio.run(stage("c1", {"goal_type": "wat", "label": "x"}))
    assert outcome == "reply" and "Goal type" in reply
    # non-custom needs target_value
    outcome, reply = asyncio.run(stage("c1", {"goal_type": "organic_clicks", "label": "x"}))
    assert outcome == "reply" and "target value" in reply
    # keyword_position needs keyword
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "keyword_position", "label": "x", "target_value": 3})
    )
    assert outcome == "reply" and "keyword" in reply.lower()
    # keywords_in_top needs target_position
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "keywords_in_top", "label": "x", "target_value": 5})
    )
    assert outcome == "reply" and "position" in reply.lower()
    # bad due date
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "x", "target_value": 800, "due_date": "Q4"})
    )
    assert outcome == "reply" and "YYYY-MM-DD" in reply
    # valid → confirm names the goal
    outcome, staged = asyncio.run(
        stage("c1", {
            "goal_type": "keyword_position", "label": "'roof repair' to top 3",
            "target_value": 3, "keyword": "roof repair", "due_date": "2026-12-31",
        })
    )
    assert outcome == "confirm"
    assert "'roof repair' to top 3" in staged["_confirm"] and "due 2026-12-31" in staged["_confirm"]
    # numbers arriving as strings are coerced, not crashed on
    outcome, staged = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "800 clicks/mo", "target_value": "800"})
    )
    assert outcome == "confirm" and staged["target_value"] == 800.0
    outcome, reply = asyncio.run(
        stage("c1", {"goal_type": "organic_clicks", "label": "x", "target_value": "lots"})
    )
    assert outcome == "reply" and "isn't a number" in reply


def test_stage_remove_tracked_keyword_resolves_and_disambiguates(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock

    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "k1", "keyword": "roof repair"},
        {"id": "k2", "keyword": "roof repair near me"},
    ]
    monkeypatch.setattr(sa_actions, "get_supabase", lambda: supabase)

    outcome, staged = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "roof repair"})
    )
    assert outcome == "confirm" and staged["keyword_id"] == "k1"
    assert "rank history" in staged["_confirm"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "roof"})
    )
    assert outcome == "reply" and "matches 2" in reply

    outcome, reply = asyncio.run(
        slack_assistant._stage_remove_tracked_keyword("c1", {"keyword": "plumber"})
    )
    assert outcome == "reply" and "roof repair" in reply


def test_stage_generate_report_wording_and_validation():
    import asyncio

    outcome, staged = asyncio.run(slack_assistant._stage_generate_report("c1", {}))
    assert outcome == "confirm"
    assert staged["report_type"] == "monthly" and staged["deliver"] is False
    assert "not delivered" in staged["_confirm"]

    outcome, staged = asyncio.run(
        slack_assistant._stage_generate_report("c1", {"report_type": "ai_visibility", "deliver": True})
    )
    assert outcome == "confirm" and "DELIVER" in staged["_confirm"]

    outcome, reply = asyncio.run(
        slack_assistant._stage_generate_report("c1", {"report_type": "quarterly"})
    )
    assert outcome == "reply" and "Report type" in reply


def test_act_generate_report_enqueues(monkeypatch):
    from services import client_report

    calls = []
    monkeypatch.setattr(
        client_report, "enqueue_client_report",
        lambda cid, rtype, deliver=False: calls.append((cid, rtype, deliver)) or "r1",
    )
    out = slack_assistant._act_generate_report("c1", {"report_type": "weekly", "deliver": True})
    assert calls == [("c1", "weekly", True)]
    assert "delivered" in out


def test_act_add_tracked_keywords_upserts_and_enqueues(monkeypatch):
    from unittest.mock import MagicMock

    from services import keyword_market, rank_materialize

    supabase = MagicMock()
    monkeypatch.setattr(sa_actions, "get_supabase", lambda: supabase)
    mats, markets = [], []
    monkeypatch.setattr(rank_materialize, "enqueue_materialize", lambda cid: mats.append(cid))
    monkeypatch.setattr(
        keyword_market, "enqueue_keyword_market", lambda cid, **kw: markets.append(cid)
    )
    out = slack_assistant._act_add_tracked_keywords("c1", {"new": ["roof repair", "roof leak"]})
    rows = supabase.table.return_value.upsert.call_args[0][0]
    assert [r["keyword"] for r in rows] == ["roof repair", "roof leak"]
    assert all(r["client_id"] == "c1" for r in rows)
    assert mats == ["c1"] and markets == ["c1"]
    assert "roof repair" in out

    # staged args lost → guidance, nothing written
    supabase.reset_mock()
    out = slack_assistant._act_add_tracked_keywords("c1", {})
    assert "lost track" in out and not supabase.table.called


def test_act_update_profile_website_triggers_rescrape(monkeypatch):
    from unittest.mock import MagicMock

    supabase = MagicMock()
    monkeypatch.setattr(sa_actions, "get_supabase", lambda: supabase)
    out = slack_assistant._act_update_profile(
        "c1", {"field": "website_url", "coerced_value": "https://new.acme.com"}
    )
    updates = supabase.table.return_value.update.call_args[0][0]
    assert updates["website_url"] == "https://new.acme.com"
    assert updates["website_analysis_status"] == "pending"
    job = supabase.table.return_value.insert.call_args[0][0]
    assert job["job_type"] == "website_scrape"
    assert job["payload"]["website_url"] == "https://new.acme.com"
    assert "re-running the site analysis" in out

    # a non-website field writes only the field (no scrape job)
    supabase.reset_mock()
    out = slack_assistant._act_update_profile("c1", {"field": "is_sab", "coerced_value": True})
    updates = supabase.table.return_value.update.call_args[0][0]
    assert updates["is_sab"] is True
    assert not supabase.table.return_value.insert.called
    assert "SAB" in out


# ---------------------------------------------------------------------------
# web search (server-side tool) — tool list, response parsing, pause_turn
# ---------------------------------------------------------------------------
def test_build_llm_tools_gates_web_search_on_setting(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "slack_assistant_web_search_enabled", True)
    monkeypatch.setattr(settings, "slack_assistant_web_search_max_uses", 3)
    tools = slack_assistant.build_llm_tools()
    ws = [t for t in tools if t.get("name") == "web_search"]
    assert len(ws) == 1
    assert ws[0]["type"] == "web_search_20260209"
    assert ws[0]["max_uses"] == 3
    # every action tool still present
    assert {t["name"] for t in slack_assistant._ACTION_TOOLS} <= {t["name"] for t in tools}

    monkeypatch.setattr(settings, "slack_assistant_web_search_enabled", False)
    tools = slack_assistant.build_llm_tools()
    assert all(t.get("name") != "web_search" for t in tools)
    assert len(tools) == len(slack_assistant._ACTION_TOOLS)


def test_extract_interpretation_ignores_server_tool_blocks():
    from types import SimpleNamespace as NS

    # a searched answer: server tool use + result + interleaved text → text
    content = [
        NS(type="text", text="Let me check their reviews."),
        NS(type="server_tool_use", name="web_search", input={"query": "FCR reviews"}),
        NS(type="web_search_tool_result", content=[]),
        NS(type="text", text="TrustPilot shows 4.2/5 across 87 reviews."),
    ]
    kind, payload = slack_assistant.extract_interpretation(content)
    assert kind == "text"
    assert "TrustPilot shows 4.2/5" in payload and "Let me check" in payload

    # an action tool call wins over text
    content = [
        NS(type="text", text="Sure."),
        NS(type="tool_use", name="rebuild_action_plan", input={}),
    ]
    kind, payload = slack_assistant.extract_interpretation(content)
    assert kind == "action" and payload["name"] == "rebuild_action_plan"

    # a tool_use whose name isn't a registered action is NOT an action
    content = [NS(type="tool_use", name="unknown_tool", input={}), NS(type="text", text="hi")]
    kind, payload = slack_assistant.extract_interpretation(content)
    assert kind == "text" and payload == "hi"

    # nothing usable → fallback message
    kind, payload = slack_assistant.extract_interpretation([])
    assert kind == "text" and "try rephrasing" in payload


def test_create_with_continuation_resumes_pause_turn():
    import asyncio
    from types import SimpleNamespace as NS

    class FakeApi:
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = []

        @property
        def messages(self):
            return self

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return self._responses.pop(0)

    paused = NS(stop_reason="pause_turn", content=[NS(type="server_tool_use", name="web_search")])
    done = NS(stop_reason="end_turn", content=[NS(type="text", text="answer")])

    api = FakeApi([paused, done])
    messages = [{"role": "user", "content": "q"}]
    resp = asyncio.run(slack_assistant._create_with_continuation(api, "sys", messages, []))
    assert resp is done
    assert len(api.calls) == 2
    # the resumed request re-sends user + the paused assistant content — and the
    # interim assistant turn lands in the SHARED list (outer tool loops rely on it)
    second = api.calls[1]["messages"]
    assert second[0] == {"role": "user", "content": "q"}
    assert second[1]["role"] == "assistant" and second[1]["content"] is paused.content
    assert messages[1]["content"] is paused.content
    # no tool_choice kwarg unless one was passed
    assert "tool_choice" not in api.calls[0]

    # tool_choice is forwarded on every call when given
    api = FakeApi([NS(stop_reason="end_turn", content=[])])
    asyncio.run(slack_assistant._create_with_continuation(
        api, "sys", [{"role": "user", "content": "q"}], [], tool_choice={"type": "none"}
    ))
    assert api.calls[0]["tool_choice"] == {"type": "none"}

    # bounded: a turn that never finishes stops after 1 + N continuations
    always_paused = [
        NS(stop_reason="pause_turn", content=[])
        for _ in range(slack_assistant._PAUSE_TURN_CONTINUATIONS + 5)
    ]
    api = FakeApi(always_paused)
    resp = asyncio.run(slack_assistant._create_with_continuation(
        api, "sys", [{"role": "user", "content": "q"}], []
    ))
    assert len(api.calls) == 1 + slack_assistant._PAUSE_TURN_CONTINUATIONS
    assert resp.stop_reason == "pause_turn"  # caller gets the last response as-is


def test_admin_actions_registered_confirm_gated_and_staged():
    admin_actions = (
        "update_client_profile", "add_target_cities", "remove_target_cities",
        "add_tracked_keywords", "remove_tracked_keyword",
        "add_ai_keywords", "remove_ai_keyword", "add_ai_competitor", "remove_ai_competitor",
        "add_campaign_goal", "remove_campaign_goal", "generate_client_report",
    )
    for name in admin_actions:
        meta = slack_assistant._ACTIONS[name]
        # every admin write is confirm-gated with its own wording, and staged so
        # the confirm names the exact change before anything is written.
        assert meta["paid"] is True, name
        assert meta.get("note"), name
        assert callable(meta.get("stage")), name
        tool = next(t for t in slack_assistant._ACTION_TOOLS if t["name"] == name)
        assert tool["input_schema"]["properties"], name


# ---------------------------------------------------------------------------
# is_local_client
# ---------------------------------------------------------------------------
def test_is_local_client_no_signals_is_not_local():
    assert slack_assistant.is_local_client({}) is False
    # client_type is deliberately ignored — it defaults to 'local' for everyone.
    assert slack_assistant.is_local_client({"client_type": "local"}) is False


def test_is_local_client_client_row_signals():
    assert slack_assistant.is_local_client({"gbp": {"place_id": "abc"}}) is True
    assert slack_assistant.is_local_client({"gbp": {"business_name": "Acme Plumbing"}}) is True
    assert slack_assistant.is_local_client({"is_sab": True}) is True
    assert slack_assistant.is_local_client({"business_location": "123 Main St, Austin"}) is True
    assert slack_assistant.is_local_client({"target_cities": ["Penrith"]}) is True
    # Empty/null shapes stay non-local.
    assert slack_assistant.is_local_client({"gbp": {}, "target_cities": [], "is_sab": False}) is False


def test_is_local_client_actual_local_work_counts():
    assert slack_assistant.is_local_client({}, local_seo_pages=2) is True
    assert slack_assistant.is_local_client({}, maps_scans=1) is True
    assert slack_assistant.is_local_client({}, local_seo_pages=0, maps_scans=0) is False


# ---------------------------------------------------------------------------
# SOP grounding — the strategy-question gate + domain selection (pure).
# ---------------------------------------------------------------------------
def test_wants_sop_grounding_matches_strategy_shapes():
    for q in (
        "How is our strategy working?",
        "Should we change the approach for Acme?",
        "What's the forecast for next quarter?",
        "What should we improve?",
        "Why did rankings drop last week?",
        "How do we grow GBP reviews?",
        "Can we shift budget into link building?",
        "how should we prioritize the action plan",
    ):
        assert slack_assistant.wants_sop_grounding(q), q


def test_wants_sop_grounding_skips_pure_data_reads():
    # Grounding defaults ON since 2026-07-30 (owner ruling) — these are the
    # narrow opt-outs: a stored number, or a bare command whose answer is a
    # tool call rather than advice.
    for q in (
        "What's our rank for roof repair?",
        "Show me the tracked keywords",
        "Who are the top competitors?",
        "add an asana task for Ivy",
    ):
        assert not slack_assistant.wants_sop_grounding(q), q
    assert not slack_assistant.wants_sop_grounding("")
    assert not slack_assistant.wants_sop_grounding(None)


def test_sop_domains_from_question_keywords():
    assert "maps" in slack_assistant.sop_domains("how do we win the local pack?", {})
    assert "ai_visibility" in slack_assistant.sop_domains("why is ChatGPT not mentioning us", {})
    assert "offpage" in slack_assistant.sop_domains("do we need more backlinks?", {})
    assert "budget" in slack_assistant.sop_domains("where should the retainer go", {})
    assert "content" in slack_assistant.sop_domains("plan more blog content", {})
    assert "organic_drop" in slack_assistant.sop_domains("rankings fell — is this cannibalization?", {})


def test_sop_domains_from_context_signals():
    ctx = {
        "organic_rank": {"open_drop_alerts": [{"keyword": "roof repair"}]},
        "maps_geogrid": {"scans": []},
        "ai_visibility": {"visibility": 40},
    }
    domains = slack_assistant.sop_domains("how is the campaign going", ctx)
    assert {"organic_drop", "maps", "ai_visibility"} <= domains
    # No alerts / modules → no context-driven domains, but never empty: an empty
    # set collapses the SOP selection to the router doc alone, which is the
    # thin-advice failure the 2026-07-30 Pompano Beach turn exhibited.
    assert slack_assistant.sop_domains("how is the campaign going", {"organic_rank": {}}) == {"content"}


def test_read_sop_tool_lists_docs():
    tool = slack_assistant._read_sop_tool()
    assert tool["name"] == "read_sop"
    assert "doc" in tool["input_schema"]["properties"]
    # The live SOP corpus is vendored into the service — the catalog should name it.
    assert "How_To_Rank_In_Google_Maps_SOP.md" in tool["description"]


# ---------------------------------------------------------------------------
# interpret — capacity-error degrade (429/529 → friendly reply, not an error)
# ---------------------------------------------------------------------------
def _capacity_interpret(status_code: int):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    anthropic = __import__("anthropic")
    import httpx

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status_code, request=req, json={"type": "error"})
    err = anthropic.APIStatusError("capacity", response=resp, body=None)
    err.status_code = status_code

    api = MagicMock()
    api.messages.create = AsyncMock(side_effect=err)
    with patch.object(anthropic, "AsyncAnthropic", return_value=api):
        return asyncio.run(
            slack_assistant.interpret("how are we doing?", {"id": "c1", "name": "Acme"}, {})
        )


def test_interpret_rate_limited_returns_busy_reply():
    import pytest

    pytest.importorskip("anthropic")
    kind, payload = _capacity_interpret(429)
    assert kind == "text"
    assert payload == slack_assistant._BUSY_REPLY


def test_interpret_overloaded_returns_busy_reply():
    import pytest

    pytest.importorskip("anthropic")
    kind, payload = _capacity_interpret(529)
    assert kind == "text"
    assert payload == slack_assistant._BUSY_REPLY


def test_interpret_other_api_error_still_raises():
    import pytest

    anthropic = pytest.importorskip("anthropic")
    with pytest.raises(anthropic.APIStatusError):
        _capacity_interpret(500)


# --- wants_portfolio (portfolio-mode phrase gate) ------------------------------
def test_wants_portfolio_matches_agency_wide_asks():
    assert slack_assistant.wants_portfolio("Which clients need attention this week?")
    assert slack_assistant.wants_portfolio("give me a portfolio health check")
    assert slack_assistant.wants_portfolio("how are all our clients doing?")
    assert slack_assistant.wants_portfolio("any clients on fire today?")
    assert slack_assistant.wants_portfolio("What's happening across the board?")
    assert slack_assistant.wants_portfolio("an agency-wide summary please")


def test_wants_portfolio_ignores_single_client_asks():
    assert not slack_assistant.wants_portfolio("How is Acme Plumbing's campaign going?")
    assert not slack_assistant.wants_portfolio("rebuild the action plan")
    assert not slack_assistant.wants_portfolio("what should we improve next?")
    assert not slack_assistant.wants_portfolio("")
    assert not slack_assistant.wants_portfolio(None)


# ---------------------------------------------------------------------------
# looks_underspecified — the deterministic "ask, don't waffle" trigger
# ---------------------------------------------------------------------------
_CTX_WITH_KEYWORDS = {
    "organic_rank": {"keywords": [{"keyword": "emergency plumber sydney"}, {"keyword": "blocked drain"}]}
}


def test_underspecified_bare_requests_for_direction():
    for msg in [
        "what should we do?",
        "what should we do next for these guys",
        "any ideas?",
        "thoughts?",
        "what would you do here",
        "how should we approach this",
        "help me out",
        "what's next",
    ]:
        assert slack_assistant.looks_underspecified(msg, {}, []), msg


def test_anchored_asks_are_not_flagged():
    # Each names something advice can attach to, so the model should just answer.
    for msg in [
        "what should we do about the maps drop?",
        "what should we do with our link building budget",
        "any ideas for the blog content plan",
        "what should we do about 'emergency plumber sydney'",
        "what should we do — we're at position 14",
        "how should we approach Q4",
        "what should we do about https://example.com/services",
    ]:
        assert not slack_assistant.looks_underspecified(msg, {}, []), msg


def test_tracked_keyword_counts_as_an_anchor():
    msg = "what should we do about emergency plumber sydney"
    assert not slack_assistant.looks_underspecified(msg, _CTX_WITH_KEYWORDS, [])
    # …and the same question without it stays flagged.
    assert slack_assistant.looks_underspecified("what should we do", _CTX_WITH_KEYWORDS, [])


def test_vague_followup_in_an_anchored_conversation_is_not_flagged():
    # "what should we do?" three turns into a conversation about the geo-grid is
    # not a vague question — the thread already says about what.
    history = [
        {"role": "user", "content": "how are the maps rankings looking?"},
        {"role": "assistant", "content": "Pack presence is 6/25 pins…"},
    ]
    assert not slack_assistant.looks_underspecified("what should we do?", {}, history)


def test_anchorless_history_does_not_rescue_a_vague_ask():
    history = [
        {"role": "user", "content": "hey"},
        {"role": "assistant", "content": "Hi — what can I help with?"},
    ]
    assert slack_assistant.looks_underspecified("what should we do?", {}, history)


def test_non_advice_messages_never_flagged():
    for msg in [
        "how is the campaign going?",
        "run a maps scan",
        "what's our rank for blocked drain",
        "add 'roof repair' to the tracker",
        "",
    ]:
        assert not slack_assistant.looks_underspecified(msg, {}, []), msg


def test_gate_tolerates_missing_or_malformed_context():
    assert slack_assistant.looks_underspecified("what should we do?", None, None)
    assert slack_assistant.looks_underspecified("what should we do?", {"organic_rank": {}}, [])
    assert slack_assistant.looks_underspecified("what should we do?", {"organic_rank": {"keywords": ["oops"]}}, [])


def _system_prompt_for(question: str, context=None, history=None) -> str:
    """Run one interpret() turn against a stubbed Anthropic and return the
    system prompt it sent — the way to assert per-turn prompt assembly."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    anthropic = __import__("anthropic")
    seen = {}

    async def _create(**kwargs):
        seen["system"] = kwargs.get("system", "")
        block = MagicMock()
        block.type = "text"
        block.text = "ok"
        resp = MagicMock()
        resp.content = [block]
        resp.stop_reason = "end_turn"
        return resp

    api = MagicMock()
    api.messages.create = AsyncMock(side_effect=_create)
    with patch.object(anthropic, "AsyncAnthropic", return_value=api):
        asyncio.run(
            slack_assistant.interpret(
                question, {"id": "c1", "name": "Acme"}, context or {}, history or []
            )
        )
    return seen["system"]


def test_vague_ask_gets_the_clarify_instruction():
    system = _system_prompt_for("what should we do?")
    assert "THIS TURN IS UNDERSPECIFIED" in system


def test_anchored_ask_does_not_get_the_clarify_instruction():
    system = _system_prompt_for("what should we do about the maps drop?")
    assert "THIS TURN IS UNDERSPECIFIED" not in system
    # …but the standing posture rule is still there.
    assert "DECIDE, DON'T INTERROGATE" in system


# ---------------------------------------------------------------------------
# The Pompano Beach regression (2026-07-30)
#
# "how can bsa claims rank in pompano beach" — a textbook How-To-Rank-In-Maps
# question — got NO SOP block and NO clarifying question, and read as generic.
# Three separate gates were wrong at once, so all three are pinned here.
# ---------------------------------------------------------------------------
_POMPANO = "how can bsa claims rank in pompano beach"


def test_pompano_question_is_sop_grounded():
    # Was False: the allowlist had "how do we"/"how should" but not "how can",
    # and no ranking vocabulary at all.
    assert slack_assistant.wants_sop_grounding(_POMPANO)


def test_pompano_question_selects_real_sop_domains():
    # Was an empty set, which collapses the selection to the router doc alone.
    domains = slack_assistant.sop_domains(_POMPANO, {"maps_geogrid": {}})
    assert "maps" in domains and "content" in domains


def test_pompano_question_is_flagged_underspecified():
    # Was False twice over: the advice gate demanded "how can WE", and the
    # anchor test counted the question's own verb ("rank") as specificity.
    assert slack_assistant.looks_underspecified(_POMPANO, {}, [])


def test_sop_grounding_defaults_on_for_unanticipated_phrasings():
    for msg in [
        "how can bsa claims rank in pompano beach",
        "any way to get found in Boca?",
        "we want to show up in more suburbs",
        "thoughts on the fort lauderdale market",
    ]:
        assert slack_assistant.wants_sop_grounding(msg), msg


def test_pure_data_reads_skip_the_sop_block():
    for msg in [
        "what's our rank for blocked drain",
        "how many keywords do we track",
        "when was the last maps scan",
        "list our open alerts",
        "do we have a geo-grid for tampa",
        "thanks!",
    ]:
        assert not slack_assistant.wants_sop_grounding(msg), msg


def test_lookup_with_an_advisory_tail_still_grounds():
    # The strategy shape wins over the lookup shape when both are present.
    assert slack_assistant.wants_sop_grounding(
        "what's our rank for blocked drain and how do we improve it"
    )


def test_sop_domains_never_empty():
    # An empty set degrades the SOP block to the router doc — the thin-advice
    # failure. There's always a floor.
    assert slack_assistant.sop_domains("something unclassifiable", {})


# ---------------------------------------------------------------------------
# Ranking-strategy asks — scope (keyword + channel) before strategising.
#
# The Pompano question is answerable only once you know WHICH search and WHICH
# channel; the generic clarify gate catches it but asks for one specific, and a
# campaign plan needs both.
# ---------------------------------------------------------------------------


def test_ranking_strategy_ask_fires_on_the_pompano_question():
    assert slack_assistant.looks_like_ranking_strategy_ask(_POMPANO)


def test_ranking_strategy_ask_fires_across_phrasings():
    for msg in [
        "how can bsa claims rank in pompano beach",
        "how do we rank for water damage restoration",
        "we want to rank in Boca Raton",
        "how can we get into the map pack in Deerfield",
        "help us show up in more suburbs",
        "any ideas how to improve our rankings in Tampa?",
        "what should we do to compete in Fort Lauderdale",
        "trying to break into the top 3 in Orlando",
    ]:
        assert slack_assistant.looks_like_ranking_strategy_ask(msg), msg


def test_ranking_metric_lookups_are_not_strategy_asks():
    # These want a number, not a plan — the gate must not turn a lookup into
    # an interrogation.
    for msg in [
        "what's our rank for blocked drain",
        "how did we rank last month",
        "where do we rank in pompano beach",
        "what rank are we for roof repair",
        "list the keywords ranking in the top 10",
    ]:
        assert not slack_assistant.looks_like_ranking_strategy_ask(msg), msg


def test_non_ranking_advice_is_not_a_ranking_strategy_ask():
    # Advice-shaped but not about ranking — these belong to the generic gate.
    for msg in [
        "what should we do about the budget",
        "any thoughts on the new brief?",
        "how can we speed up content delivery",
    ]:
        assert not slack_assistant.looks_like_ranking_strategy_ask(msg), msg


def test_pompano_question_gets_the_ranking_instruction_not_the_generic_one():
    # Wiring: the specific instruction reaches the prompt, and the generic
    # "ask ONE question" instruction is suppressed so they can't conflict.
    system = _system_prompt_for(_POMPANO)
    assert "THIS TURN IS A RANKING-STRATEGY REQUEST" in system
    assert "THIS TURN IS UNDERSPECIFIED" not in system


def test_ranking_instruction_decides_both_specifics_itself():
    system = _system_prompt_for(_POMPANO)
    # It must OWN both calls rather than ask for them.
    assert "TARGET KEYWORD" in system and "THE CHANNEL" in system
    assert "YOU DECIDE BOTH YOURSELF" in system
    assert "ANSWER IT" in system
    for channel in ("organic", "local pack", "AI answers"):
        assert channel in system, channel


def test_non_ranking_vague_ask_still_gets_the_generic_instruction():
    system = _system_prompt_for("what should we do?")
    assert "THIS TURN IS UNDERSPECIFIED" in system
    assert "THIS TURN IS A RANKING-STRATEGY REQUEST" not in system


# ---------------------------------------------------------------------------
# check_live_serp — location-scoped, and read for both channels.
#
# Without a location the check runs at the client's CONFIGURED tracking
# location, so a question about a new city silently returns the old one.
# ---------------------------------------------------------------------------


def test_live_serp_action_accepts_a_location():
    params = slack_assistant._ACTIONS["check_live_serp"]["params"]
    assert "location" in params["properties"]
    assert params["required"] == ["keyword"]  # still optional


def test_live_serp_stage_resolves_a_location_and_names_it_in_the_confirm():
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.slack_assistant import actions

    with patch.object(actions, "_client_for_serp", return_value={"gbp": {}}), \
         patch("services.locations_service.search_locations", new=AsyncMock(
             return_value=[{"location_code": 1015214, "location_name": "Pompano Beach,Florida,United States"}])):
        kind, staged = asyncio.run(actions._stage_live_serp(
            "c1", {"keyword": "water damage restoration", "location": "pompano beach"}
        ))
    assert kind == "confirm"
    assert staged["location_code"] == 1015214
    assert "Pompano Beach" in staged["_confirm"]
    assert "water damage restoration" in staged["_confirm"]


def test_live_serp_stage_asks_again_when_a_location_cannot_be_resolved():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from services.slack_assistant import actions

    with patch.object(actions, "_client_for_serp", return_value={"gbp": {}}), \
         patch("services.locations_service.search_locations", new=AsyncMock(return_value=[])):
        kind, msg = asyncio.run(actions._stage_live_serp(
            "c1", {"keyword": "roof repair", "location": "nowhereville"}
        ))
    assert kind == "reply"
    assert "nowhereville" in msg


def test_live_serp_without_a_location_falls_back_to_the_tracked_location():
    import asyncio
    from unittest.mock import patch

    from services.slack_assistant import actions

    # No location supplied: must not touch the DB at all.
    with patch.object(actions, "_client_for_serp", side_effect=AssertionError("should not read the client")):
        kind, staged = asyncio.run(actions._stage_live_serp("c1", {"keyword": "roof repair"}))
    assert kind == "confirm"
    assert staged["location_code"] is None
    assert "their tracked location" in staged["_confirm"]


# ---------------------------------------------------------------------------
# save_strategy_actions — a written strategy becomes Action Plan steps.
# ---------------------------------------------------------------------------


def test_clean_strategy_actions_normalizes_objects_and_bare_strings():
    from services.slack_assistant import actions

    cleaned = actions._clean_strategy_actions([
        {"title": "  Build a Pompano page  ", "detail": "no page exists", "keyword": "water damage"},
        "Add Pompano to tracked keywords",
        {"title": "   "},          # empty title — dropped
        {"detail": "orphan"},      # no title — dropped
        42,                        # not a step at all
    ])
    assert [c["title"] for c in cleaned] == [
        "Build a Pompano page", "Add Pompano to tracked keywords",
    ]
    assert cleaned[0]["keyword"] == "water damage"
    assert cleaned[1]["detail"] is None


def test_stage_save_strategy_actions_lists_every_step_in_the_confirm():
    import asyncio

    from services.slack_assistant import actions

    kind, staged = asyncio.run(actions._stage_save_strategy_actions("c1", {
        "actions": [{"title": "Build a Pompano page"}, {"title": "Run a geo-grid"}],
    }))
    assert kind == "confirm"
    assert "Build a Pompano page" in staged["_confirm"]
    assert "Run a geo-grid" in staged["_confirm"]


def test_stage_save_strategy_actions_asks_again_with_nothing_to_save():
    import asyncio

    from services.slack_assistant import actions

    kind, msg = asyncio.run(actions._stage_save_strategy_actions("c1", {"actions": []}))
    assert kind == "reply"
    assert "steps" in msg.lower()


def test_stage_save_strategy_actions_caps_and_says_what_was_dropped():
    import asyncio

    from services.reopt_planner import ASSISTANT_ACTION_MAX
    from services.slack_assistant import actions

    kind, staged = asyncio.run(actions._stage_save_strategy_actions("c1", {
        "actions": [{"title": f"step {i}"} for i in range(ASSISTANT_ACTION_MAX + 3)],
    }))
    assert kind == "confirm"
    assert len(staged["actions"]) == ASSISTANT_ACTION_MAX
    assert "3 more didn't fit" in staged["_confirm"]


# ---------------------------------------------------------------------------
# The keyword-inference regression (2026-07-30, live).
#
# "I want to rank bsa claims in pompano beach. what do we need to do?" tripped
# the gate and the instruction reached the model, which asked about the CHANNEL
# but not the KEYWORD — it treated the client's 27 existing tracked keywords as
# already answering "which keyword". Those are anchored to Tampa, Fort
# Lauderdale, Orlando and Jacksonville; not one names Pompano Beach. Picking
# what to rank for in a new city is the teammate's commercial decision.
# ---------------------------------------------------------------------------
_POMPANO_WANT = "I want to rank bsa claims in pompano beach. what do we need to do?"


def test_the_want_to_rank_phrasing_trips_the_ranking_gate():
    assert slack_assistant.looks_like_ranking_strategy_ask(_POMPANO_WANT)


def test_client_plus_city_only_is_treated_as_normal_not_as_a_gap():
    # "rank <client> in <city>" names no keyword. That is the COMMON case and
    # must produce a chosen target, not a question back.
    system = _system_prompt_for(_POMPANO_WANT)
    assert "NORMAL and you are expected to choose" in system


def test_ranking_instruction_still_forbids_reusing_other_cities_keywords():
    # The one real finding from the live failure survives the reversal: the
    # client's existing keywords carry the wrong geo-modifier.
    system = _system_prompt_for(_POMPANO_WANT)
    assert "existing tracked keywords for other cities" in system
    assert "build the local equivalent" in system


def test_ranking_instruction_requires_stated_assumptions_not_a_gate():
    # Control over the target is preserved by making the assumption explicit
    # and correctable — never by withholding the strategy.
    system = _system_prompt_for(_POMPANO_WANT)
    assert "INVITATION, not a" in system
    assert "I've assumed" in system


# ---------------------------------------------------------------------------
# Post-turn memory capture.
#
# The `remember` TOOL never fired once in weeks — assistant_memories was empty
# across all 14 clients. It isn't broken; it's starved. It lives in interpret's
# tool loop, where a call competes with writing the answer, and the round that
# produces the reply runs with tool_choice="none". Capture now happens after the
# turn instead.
# ---------------------------------------------------------------------------


def _capture(monkeypatch, notes, **cfg):
    """Run capture_memories against a stubbed Anthropic; return saved notes."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from config import settings
    from services.slack_assistant import context as ctx

    for k, v in cfg.items():
        monkeypatch.setattr(settings, k, v, raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)

    saved: list[str] = []
    monkeypatch.setattr(ctx, "_run_remember",
                        lambda cid, args, src: saved.append(args["note"]) or "ok")
    monkeypatch.setattr(ctx, "get_supabase", lambda: MagicMock())

    block = MagicMock()
    block.type = "tool_use"
    block.input = {"notes": notes}
    resp = MagicMock()
    resp.content = [block]
    api = MagicMock()
    api.messages.create = AsyncMock(return_value=resp)

    anthropic = __import__("anthropic")
    with patch.object(anthropic, "AsyncAnthropic", return_value=api):
        asyncio.run(ctx.capture_memories("c1", "q", "r" * 900, "chat"))
    return saved


def test_capture_saves_the_notes_the_model_returns(monkeypatch):
    saved = _capture(monkeypatch, ["Targeting independent insurance adjuster Pompano Beach."])
    assert saved == ["Targeting independent insurance adjuster Pompano Beach."]


def test_capture_saves_nothing_when_the_turn_holds_nothing_durable(monkeypatch):
    # The common, correct outcome — a data lookup is not a memory.
    assert _capture(monkeypatch, []) == []


def test_capture_respects_the_per_turn_note_cap(monkeypatch):
    saved = _capture(monkeypatch, ["a", "b", "c", "d"], slack_assistant_memory_max_notes=2)
    assert len(saved) == 2


def test_capture_drops_blank_notes(monkeypatch):
    assert _capture(monkeypatch, ["  ", "", "real note"]) == ["real note"]


def test_capture_skips_trivial_replies(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock, patch

    from config import settings
    from services.slack_assistant import context as ctx

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    anthropic = __import__("anthropic")
    with patch.object(anthropic, "AsyncAnthropic") as api:
        # Below slack_assistant_memory_min_reply_chars — must not call the API.
        n = asyncio.run(ctx.capture_memories("c1", "thanks", "no worries", "chat"))
    assert n == 0 and api.call_count == 0


def test_capture_is_disabled_by_its_flag(monkeypatch):
    import asyncio

    from config import settings
    from services.slack_assistant import context as ctx

    monkeypatch.setattr(settings, "slack_assistant_memory_enabled", False, raising=False)
    assert asyncio.run(ctx.capture_memories("c1", "q", "r" * 900, "chat")) == 0


def test_capture_never_raises_into_the_turn(monkeypatch):
    import asyncio
    from unittest.mock import MagicMock, patch

    from config import settings
    from services.slack_assistant import context as ctx

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(ctx, "get_supabase", MagicMock(side_effect=RuntimeError("db down")))
    anthropic = __import__("anthropic")
    with patch.object(anthropic, "AsyncAnthropic"):
        assert asyncio.run(ctx.capture_memories("c1", "q", "r" * 900, "chat")) == 0


# ---------------------------------------------------------------------------
# cost_plan — affordability computed, not asserted.
# ---------------------------------------------------------------------------


def _cost_plan(items, retainer=500.0, margin=None, is_sab=False):
    import asyncio
    import json
    from unittest.mock import MagicMock, patch

    from services.slack_assistant import llm

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"retainer_monthly": retainer, "is_sab": is_sab}
    ]
    args = {"items": items}
    if margin is not None:
        args["margin"] = margin
    with patch.object(llm, "get_supabase", return_value=sb):
        return json.loads(asyncio.run(llm._run_cost_plan("c1", args)))


def test_cost_plan_flags_a_plan_the_retainer_cannot_fund():
    # BSA Claims: $500/mo is already negative before anything is proposed.
    out = _cost_plan([{"task_type": "content_page", "quantity": 4}])
    assert out["budget"]["discretionary"] == -115.0
    assert out["proposed_total"] == 20.0
    assert out["fits"] is False
    assert out["over_budget_by"] == 135.0
    assert "OVER by" in out["verdict"]


def test_cost_plan_accepts_a_plan_that_fits():
    out = _cost_plan([{"task_type": "content_page", "quantity": 4}], retainer=2500.0)
    assert out["budget"]["discretionary"] == 565.0
    assert out["fits"] is True and out["over_budget_by"] == 0


def test_cost_plan_prices_from_the_real_catalog():
    out = _cost_plan(
        [{"task_type": "reviews", "quantity": 10}, {"task_type": "content_page", "quantity": 2}],
        retainer=2500.0,
    )
    assert out["proposed_total"] == 160.0  # 10×15 + 2×5
    assert {line["task_type"] for line in out["proposed"]} == {"reviews", "content_page"}


def test_cost_plan_reports_unknown_task_types_instead_of_silently_dropping_them():
    out = _cost_plan([{"task_type": "magic_beans", "quantity": 3}], retainer=2500.0)
    assert out["unknown_task_types"] == ["magic_beans"]
    assert out["proposed_total"] == 0


def test_cost_plan_clamps_the_margin_to_the_sop_floor_and_ceiling():
    # Below 0.34 would spend past the agency's margin target; above 0.50 is a
    # hard stop in the Recipe Engine.
    assert _cost_plan([], retainer=1000.0, margin=0.10)["budget"]["margin_used"] == 0.34
    assert _cost_plan([], retainer=1000.0, margin=0.90)["budget"]["margin_used"] == 0.50


def test_cost_plan_handles_a_client_with_no_retainer():
    out = _cost_plan([{"task_type": "content_page", "quantity": 1}], retainer=None)
    assert out["budget"]["deployable"] == 0.0 and out["fits"] is False
