"""Unit tests for Social P4 (Phase B): the Social Manager orchestrator loop's pure core
(plan / source selection / batching), its gate + decision paths, the enqueue dedup, and
the fan-out auto-queue + provenance wiring. Pure helpers + DB/LLM-mocked (no network).
Async entrypoints are driven via asyncio.run so no pytest-asyncio is needed."""

import asyncio
from types import SimpleNamespace

import pytest

from config import settings
from services.social import fanout, manager


# ── a tiny fake Supabase (records inserts/updates; returns canned select rows) ─

class _Q:
    def __init__(self, store, tbl):
        self.store, self.tbl, self._op, self._fields = store, tbl, None, None

    def insert(self, fields):
        self.store.setdefault("inserts", []).append((self.tbl, fields))
        self._op, self._fields = "insert", fields
        return self

    def update(self, fields):
        self.store.setdefault("updates", []).append((self.tbl, fields))
        self._op, self._fields = "update", fields
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        rows = self.store.get("rows", {}).get(self.tbl, [])
        if self._op == "insert":
            # echo an id list (job/draft inserts read .data[0]["id"])
            data = self._fields if isinstance(self._fields, list) else [self._fields]
            return SimpleNamespace(data=[{**d, "id": d.get("id", "new-id")} for d in data])
        return SimpleNamespace(data=rows)


def _fake_sb(store):
    return SimpleNamespace(table=lambda t: _Q(store, t))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "social_enabled", True)
    monkeypatch.setattr(settings, "social_autonomy_enabled", True)
    monkeypatch.setattr(settings, "social_autonomy_cap_tier", 2)
    monkeypatch.setattr(settings, "social_autonomy_target_queue", 2)
    monkeypatch.setattr(settings, "social_autonomy_max_per_week", 14)
    # The storyboard-propose seam (P5 a.1) adds a new impure read into the run path; stub
    # it to "none recent" by default so run tests stay network-free (seam tests override it).
    monkeypatch.setattr(manager, "_platforms_with_recent_storyboard", lambda c, d: set())


# ── pure core ──────────────────────────────────────────────────────────────

def test_source_key():
    assert manager.source_key("topic", text=" Roof Restoration ") == "topic:roof restoration"
    assert manager.source_key("blog_run", "r1") == "blog_run:r1"
    assert manager.source_key("local_seo_page", "p1") == "local_seo_page:p1"


def test_filter_candidates_drops_blocked_titles():
    cands = [{"type": "blog_run", "id": "1", "title": "Our pricing guide"},
             {"type": "blog_run", "id": "2", "title": "Storm damage repair"},
             {"type": "blog_run", "id": "3", "title": None}]  # title-less always kept
    out = manager.filter_candidates(cands, ["pricing"])
    assert [c["id"] for c in out] == ["2", "3"]
    # no blocked list → unchanged
    assert manager.filter_candidates(cands, []) == cands


def test_platform_deficits():
    d = manager.platform_deficits(["facebook", "instagram"], {"facebook": 1}, 2)
    assert d == {"facebook": 1, "instagram": 2}


def test_plan_batches_basic():
    # facebook needs 2, instagram needs 1, ample headroom → [[fb,ig],[fb]]
    assert manager.plan_batches({"facebook": 2, "instagram": 1}, 10) == [
        ["facebook", "instagram"], ["facebook"]
    ]


def test_plan_batches_respects_weekly_cap():
    # cap of 2 drafts total → only the first batch (2 drafts)
    assert manager.plan_batches({"facebook": 2, "instagram": 1}, 2) == [["facebook", "instagram"]]
    # no headroom → nothing
    assert manager.plan_batches({"facebook": 2}, 0) == []
    # zero deficits → nothing
    assert manager.plan_batches({"facebook": 0}, 10) == []


def test_compose_angle():
    assert manager.compose_angle({"title": "T", "hook": "H"}) == ("T. H", "T")
    assert manager.compose_angle({"title": "Only title", "hook": ""}) == ("Only title", "Only title")
    assert manager.compose_angle({"title": "", "hook": "Just a hook"}) == ("Just a hook", "Just a hook")


def test_select_source_rotates_then_falls_back_to_topics():
    cands = [{"type": "blog_run", "id": "1", "title": "A"},
             {"type": "local_seo_page", "id": "2", "title": "B"}]
    used: set[str] = set()
    first = manager.select_source(cands, used, ["topic one"])
    assert first["source_type"] == "blog_run" and first["source_id"] == "1"
    used.add(first["key"])
    second = manager.select_source(cands, used, ["topic one"])
    assert second["source_id"] == "2"          # rotated to the next unused content
    used.add(second["key"])
    third = manager.select_source(cands, used, ["topic one"])
    assert third["source_type"] == "topic" and third["text"] == "topic one"   # content exhausted → topic bank
    used.add(third["key"])
    assert manager.select_source(cands, used, ["topic one"]) is None            # nothing fresh left


# ── run gate + decision paths (async via asyncio.run) ────────────────────────

def _run(client_id="c1", **kw):
    return asyncio.run(manager.run_social_autonomy_for_client(client_id, **kw))


def test_run_disabled(monkeypatch):
    monkeypatch.setattr(settings, "social_autonomy_enabled", False)
    assert _run()["status"] == "disabled"


def test_run_not_opted_in(monkeypatch):
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 0})
    assert _run()["status"] == "not_opted_in"


def test_run_frozen(monkeypatch):
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 1})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: True)
    assert _run()["status"] == "frozen"


def test_run_noop_no_platforms(monkeypatch):
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 1})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)
    monkeypatch.setattr(manager, "_active_cadence_platforms", lambda c: [])
    assert _run()["status"] == "noop"


def test_run_proposes_when_over_budget(monkeypatch):
    # tier 1, an under-target platform, but the month's budget is exhausted → the
    # generate action classifies "propose": nothing is dispatched, a proposal is recorded.
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 1})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)
    monkeypatch.setattr(manager, "_active_cadence_platforms", lambda c: ["facebook"])
    monkeypatch.setattr(manager, "_queued_counts", lambda c: {})
    monkeypatch.setattr(manager, "_autonomy_drafts_this_week", lambda c: 0)
    monkeypatch.setattr(manager, "_per_draft_image_cost", lambda: 0.10)
    monkeypatch.setattr(manager.budget, "spent_this_month", lambda c, t=None: 10_000.0)  # over any ceiling
    dispatched = []
    monkeypatch.setattr(manager, "_dispatch_batch", lambda *a, **k: dispatched.append(a) or "as1")
    monkeypatch.setattr(manager, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(manager, "_emit_digest", lambda *a, **k: None)
    out = _run()
    assert out["status"] == "proposed"
    assert dispatched == []          # over budget → nothing generated


def test_run_dispatches_and_auto_queues_at_tier2(monkeypatch):
    # tier 2 + budget OK → the generate action is auto AND queue_social_draft is auto,
    # so the run dispatches a fan-out batch with auto_queue=True.
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 2})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)
    monkeypatch.setattr(manager, "_active_cadence_platforms", lambda c: ["facebook"])
    monkeypatch.setattr(manager, "_queued_counts", lambda c: {})              # deficit 2
    monkeypatch.setattr(manager, "_autonomy_drafts_this_week", lambda c: 0)
    monkeypatch.setattr(manager, "_per_draft_image_cost", lambda: 0.10)
    monkeypatch.setattr(manager.budget, "spent_this_month", lambda c, t=None: 0.0)
    monkeypatch.setattr(manager, "_recent_source_keys", lambda c, d: set())
    monkeypatch.setattr(manager, "_candidate_sources",
                        lambda c: [{"type": "blog_run", "id": "r1", "title": "A"},
                                   {"type": "blog_run", "id": "r2", "title": "B"}])

    async def _fake_angle(cid, src, uid):
        return ("angle", "Angle")
    monkeypatch.setattr(manager, "_angle_for_source", _fake_angle)
    seen = []
    monkeypatch.setattr(manager, "_dispatch_batch",
                        lambda cid, plats, src, angle, title, aq, uid: seen.append(aq) or "as1")
    monkeypatch.setattr(manager, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(manager, "_emit_digest", lambda *a, **k: None)
    out = _run()
    assert out["status"] == "ran"
    assert out["auto_queue"] is True
    assert seen and all(aq is True for aq in seen)     # every batch dispatched with auto_queue


def test_run_tier1_does_not_auto_queue(monkeypatch):
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 1})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)
    monkeypatch.setattr(manager, "_active_cadence_platforms", lambda c: ["facebook"])
    monkeypatch.setattr(manager, "_queued_counts", lambda c: {"facebook": 1})   # deficit 1
    monkeypatch.setattr(manager, "_autonomy_drafts_this_week", lambda c: 0)
    monkeypatch.setattr(manager, "_per_draft_image_cost", lambda: 0.10)
    monkeypatch.setattr(manager.budget, "spent_this_month", lambda c, t=None: 0.0)
    monkeypatch.setattr(manager, "_recent_source_keys", lambda c, d: set())
    monkeypatch.setattr(manager, "_candidate_sources",
                        lambda c: [{"type": "blog_run", "id": "r1", "title": "A"}])

    async def _fake_angle(cid, src, uid):
        return ("angle", "Angle")
    monkeypatch.setattr(manager, "_angle_for_source", _fake_angle)
    seen = []
    monkeypatch.setattr(manager, "_dispatch_batch",
                        lambda cid, plats, src, angle, title, aq, uid: seen.append(aq) or "as1")
    monkeypatch.setattr(manager, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(manager, "_emit_digest", lambda *a, **k: None)
    out = _run()
    assert out["status"] == "ran"
    assert out["auto_queue"] is False
    assert seen == [False]      # generated to 'ready', never auto-queued at tier 1


# ── enqueue dedup + gate ─────────────────────────────────────────────────────

def test_enqueue_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "social_autonomy_enabled", False)
    assert manager.enqueue_social_autonomy_run("c1") is None


def test_enqueue_dedups_in_flight(monkeypatch):
    monkeypatch.setattr(manager, "_in_flight_run", lambda c: True)
    assert manager.enqueue_social_autonomy_run("c1") is None


def test_enqueue_clean_inserts(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(manager, "_in_flight_run", lambda c: False)
    monkeypatch.setattr(manager, "_sb", lambda: _fake_sb(store))
    jid = manager.enqueue_social_autonomy_run("c1", "empty_queue", platform="facebook")
    assert jid == "new-id"
    tbl, fields = store["inserts"][-1]
    assert tbl == "async_jobs" and fields["job_type"] == "social_autonomy_run"
    assert fields["payload"]["platform"] == "facebook" and fields["payload"]["trigger"] == "empty_queue"


# ── fan-out wiring: enqueue payload carries auto_queue + produced_by ──────────

def test_enqueue_fanout_threads_autonomy_flags(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(fanout, "_client_accounts", lambda c: [{"platform": "facebook"}])
    monkeypatch.setattr(fanout, "_sb", lambda: _fake_sb(store))
    req = SimpleNamespace(
        angle="angle", angle_title="Angle", platforms=["facebook"], format="feed",
        source_type="blog_run", source_id="r1", url=None, text=None, tone=None,
        include_image=True, include_hashtags=True, slides=None,
        auto_queue=True, produced_by="autonomy",
    )
    fanout.enqueue_fanout("c1", req, "u1")
    job = next(f for t, f in store["inserts"] if t == "async_jobs")
    assert job["payload"]["auto_queue"] is True
    assert job["payload"]["produced_by"] == "autonomy"


# ── run_fanout_job: auto_queue turns a ready draft into queued + stamps provenance ─

def test_run_fanout_job_auto_queues_and_stamps(monkeypatch):
    from services.social import creator

    store_updates: list = []

    class _FJQ:
        def __init__(self, tbl):
            self.tbl = tbl
            self._op = None

        def update(self, fields):
            self._op, self._fields = "update", fields
            if self.tbl == "social_drafts":
                store_updates.append(fields)
            return self

        def select(self, *a, **k):
            self._op = "select"
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            if self.tbl == "social_drafts" and self._op == "select":
                return SimpleNamespace(data=[{"id": "d1", "platform": "facebook", "format": "feed"}])
            return SimpleNamespace(data=[{"id": "job1"}])

    monkeypatch.setattr(fanout, "_sb", lambda: SimpleNamespace(table=lambda t: _FJQ(t)))
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)

    async def _load_source(cid, st, **k):
        return ("Title", "body text", {"type": "blog_run", "run_id": "r1"})
    monkeypatch.setattr(creator, "load_source", _load_source)
    monkeypatch.setattr(creator, "source_version_of", lambda t: "v1")
    monkeypatch.setattr(creator, "_client_row", lambda c: {"id": c})

    async def _voice(client, uid):
        return ({}, "", "")
    monkeypatch.setattr(creator, "resolve_voice_context", _voice)

    async def _copy(**k):
        return ("hello copy", [], [])
    monkeypatch.setattr(creator, "draft_platform_copy", _copy)
    # facebook doesn't require an image, so the draft is 'ready' without one.
    monkeypatch.setattr(fanout, "_platform_spec", lambda p: {"requires_image": False})
    from services import notifications
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: None)
    from services.social import qa as social_qa
    monkeypatch.setattr(social_qa, "qa_gate_enabled", lambda c: False)   # gate off → queue as before

    job = {"id": "job1", "payload": {
        "client_id": "c1", "angle_set_id": "as1", "angle": "a", "angle_title": "A",
        "format": "feed", "include_image": False, "source_type": "blog_run",
        "source_id": "r1", "produced_by": "autonomy", "auto_queue": True,
    }}
    asyncio.run(fanout.run_fanout_job(job))

    draft_update = next(u for u in store_updates if u.get("status") in ("queued", "ready"))
    assert draft_update["status"] == "queued"                       # auto_queue: ready → queued
    assert draft_update["platform_metadata"]["produced_by"] == "autonomy"


def test_run_fanout_job_qa_holds_failing_draft(monkeypatch):
    """QA gate on + a blocking verdict → an auto_queue draft is HELD at 'ready' (not
    queued), and the verdict rides on the draft."""
    from services.social import creator

    store_updates: list = []

    class _FJQ:
        def __init__(self, tbl):
            self.tbl = tbl
            self._op = None

        def update(self, fields):
            self._op = "update"
            if self.tbl == "social_drafts":
                store_updates.append(fields)
            return self

        def select(self, *a, **k):
            self._op = "select"
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            if self.tbl == "social_drafts" and self._op == "select":
                return SimpleNamespace(data=[{"id": "d1", "platform": "facebook", "format": "feed"}])
            return SimpleNamespace(data=[{"id": "job1"}])

    monkeypatch.setattr(fanout, "_sb", lambda: SimpleNamespace(table=lambda t: _FJQ(t)))
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)

    async def _load_source(cid, st, **k):
        return ("Title", "body", {"type": "blog_run", "run_id": "r1"})
    monkeypatch.setattr(creator, "load_source", _load_source)
    monkeypatch.setattr(creator, "source_version_of", lambda t: "v1")
    monkeypatch.setattr(creator, "_client_row", lambda c: {"id": c})

    async def _voice(client, uid):
        return ({}, "", "")
    monkeypatch.setattr(creator, "resolve_voice_context", _voice)

    async def _copy(**k):
        return ("copy without a hook", [], [])
    monkeypatch.setattr(creator, "draft_platform_copy", _copy)
    monkeypatch.setattr(fanout, "_platform_spec", lambda p: {"requires_image": False})
    from services import notifications
    monkeypatch.setattr(notifications, "emit", lambda *a, **k: None)
    from services.social import qa as social_qa
    monkeypatch.setattr(social_qa, "qa_gate_enabled", lambda c: True)
    monkeypatch.setattr(social_qa, "review_draft",
                        lambda **k: {"verdict": "minor_revisions", "critical": [], "failed": ["Has a call to action"]})

    job = {"id": "job1", "payload": {
        "client_id": "c1", "angle_set_id": "as1", "angle": "a", "angle_title": "A",
        "format": "feed", "include_image": False, "source_type": "blog_run",
        "source_id": "r1", "produced_by": "autonomy", "auto_queue": True,
    }}
    asyncio.run(fanout.run_fanout_job(job))

    draft_update = next(u for u in store_updates if u.get("status") in ("queued", "ready"))
    assert draft_update["status"] == "ready"          # QA held it — NOT auto-queued
    assert draft_update["qa_verdict"]["verdict"] == "minor_revisions"


# ── P5 (slice a.1): the storyboard-PROPOSE seam ──────────────────────────────

def test_gather_storyboard_proposals_video_only_and_capped():
    # instagram + facebook + youtube are video platforms; linkedin is not. facebook has a
    # recent storyboard (excluded). cap = 1 → only the first eligible (instagram) is proposed.
    props = manager.gather_storyboard_proposals(
        ["linkedin", "facebook", "instagram", "youtube"],
        recent_platforms={"facebook"}, max_proposals=1,
    )
    assert [p["platform"] for p in props] == ["instagram"]
    assert props[0]["format"] == "reel"


def test_gather_storyboard_proposals_youtube_is_short():
    props = manager.gather_storyboard_proposals(["youtube"], set(), max_proposals=3)
    assert props == [{"platform": "youtube", "format": "short",
                      "reason": "no recent video storyboard for this platform"}]


def test_gather_storyboard_proposals_none_when_all_recent_or_off_topic():
    assert manager.gather_storyboard_proposals(["instagram"], {"instagram"}, 5) == []
    assert manager.gather_storyboard_proposals(["linkedin", "x"], set(), 5) == []
    assert manager.gather_storyboard_proposals(["instagram"], set(), 0) == []


def test_storyboard_proposal_decisions_are_propose_never_auto(monkeypatch):
    monkeypatch.setattr(manager, "_platforms_with_recent_storyboard", lambda c, d: set())
    monkeypatch.setattr(settings, "social_autonomy_storyboard_proposals", True)
    monkeypatch.setattr(settings, "social_autonomy_storyboard_max_per_run", 2)
    decisions = manager._storyboard_proposal_decisions("c1", ["facebook", "youtube"], tier=1)
    assert [d["platform"] for d in decisions] == ["facebook", "youtube"]
    assert all(d["action"] == "propose_social_storyboard" for d in decisions)
    assert all(d["outcome"] == "propose" for d in decisions)   # requires=approval ⇒ never auto
    # and never in AUTO_EXECUTE (belt + suspenders)
    assert "propose_social_storyboard" not in manager.AUTO_EXECUTE


def test_storyboard_proposal_decisions_gated_off(monkeypatch):
    monkeypatch.setattr(settings, "social_autonomy_storyboard_proposals", False)
    assert manager._storyboard_proposal_decisions("c1", ["facebook"], tier=2) == []


def test_activity_item_counts_storyboard_proposals():
    row = {
        "id": "r1", "trigger": "scheduled", "tier": 1, "cost_usd": 0,
        "goal_snapshot": {"deficits": {"facebook": 1}},
        "decisions": [
            {"proposed_batches": [["facebook"]]},
            {"action": "propose_social_storyboard", "outcome": "propose", "platform": "youtube"},
        ],
        "actions_taken": [],
    }
    item = manager.activity_item(row)
    assert item["storyboards"] == 1
    assert item["proposed"] == 1
    assert item["platforms"] == ["facebook", "youtube"]   # deficit + storyboard platforms merged


def test_run_records_storyboard_proposal_even_when_queues_full(monkeypatch):
    # draft queues full (deficit 0) → normally a bare noop; a storyboard proposal still
    # surfaces as a "proposed" run that records the decision + digests it.
    monkeypatch.setattr(manager, "_policy_row", lambda c: {"autonomy_tier": 1})
    import services.freeze as freeze
    monkeypatch.setattr(freeze, "is_frozen", lambda c: False)
    monkeypatch.setattr(manager, "_active_cadence_platforms", lambda c: ["facebook"])
    monkeypatch.setattr(manager, "_queued_counts", lambda c: {"facebook": 2})   # deficit 0 → no batches
    monkeypatch.setattr(manager, "_autonomy_drafts_this_week", lambda c: 0)
    monkeypatch.setattr(manager, "_platforms_with_recent_storyboard", lambda c, d: set())
    monkeypatch.setattr(settings, "social_autonomy_storyboard_proposals", True)
    monkeypatch.setattr(settings, "social_autonomy_storyboard_max_per_run", 1)
    ledger: dict = {}
    monkeypatch.setattr(manager, "_write_ledger",
                        lambda cid, tr, ti, defs, decs, dispatched, auto_queue: ledger.update(decisions=decs))
    monkeypatch.setattr(manager, "_emit_digest", lambda *a, **k: None)
    out = _run()
    assert out["status"] == "proposed" and out["storyboards"] == 1 and out["batches"] == 0
    sb = [d for d in ledger["decisions"] if d.get("action") == "propose_social_storyboard"]
    assert len(sb) == 1 and sb[0]["platform"] == "facebook" and sb[0]["outcome"] == "propose"
