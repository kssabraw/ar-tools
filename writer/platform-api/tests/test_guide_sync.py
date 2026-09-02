"""Unit tests for services.guide_sync — DORA's guide sync.

Pure helpers (payload normalization, the rewrite sanity check, the #dora
notification copy, prompt assembly) plus the review flow with the LLM,
store, and notifier stubbed: auto-apply snapshots the prior body, a
not-user-visible verdict is silent, a bad rewrite is rejected (never written),
auto-apply off parks a proposal, and the human apply / revert / dismiss
transitions. Ingest idempotency runs against a tiny in-memory Supabase fake.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from config import settings
from services import guide_sync as G


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------
class _Query:
    def __init__(self, table, rows):
        self.table = table
        self.rows = rows
        self._filters = []
        self._limit = None
        self._insert = None
        self._update = None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters.append(lambda r: r.get(k) == v)
        return self

    def in_(self, k, vs):
        self._filters.append(lambda r: r.get(k) in vs)
        return self

    def gte(self, k, v):
        self._filters.append(lambda r: (r.get(k) or "") >= v)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self._insert = row
        return self

    def update(self, upd):
        self._update = upd
        return self

    def _matching(self):
        out = [r for r in self.rows if all(f(r) for f in self._filters)]
        return out[: self._limit] if self._limit else out

    def execute(self):
        if self._insert is not None:
            rows = self._insert if isinstance(self._insert, list) else [self._insert]
            for r in rows:
                r.setdefault("id", f"{self.table}-{len(self.rows) + 1}")
                self.rows.append(r)
            return type("R", (), {"data": rows})()
        if self._update is not None:
            hit = self._matching()
            for r in hit:
                r.update(self._update)
            return type("R", (), {"data": hit})()
        return type("R", (), {"data": self._matching()})()


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {"guide_sync_runs": [], "async_jobs": [], "guides": []}

    def table(self, name):
        return _Query(name, self.tables.setdefault(name, []))


GUIDE = {"id": "g-1", "slug": "rank-tracker", "title": "Organic Rank Tracker",
         "summary": "Track rankings.", "body": "# Organic Rank Tracker\n\n## Tabs\n- Overview\n- Pages\n"}
RUN = {"id": "r-1", "module_key": "rank_tracker", "module_label": "Organic Rank Tracker",
       "guide_slug": "rank-tracker", "status": "queued", "commit_sha": "abc1234",
       "commits": [{"sha": "abc1234", "title": "Rankings: add a CSV export button", "body": ""}],
       "files": ["frontend/src/pages/Rankings.tsx"], "diff": "+ <button>Export CSV</button>"}


@pytest.fixture
def fake_store(monkeypatch):
    """A stubbed guide store + run store: the flow tests read/write dicts."""
    state = {"guide": {**GUIDE}, "run": {**RUN}, "updates": []}
    monkeypatch.setattr(G.guide_store, "get_guide", lambda slug: dict(state["guide"]) if slug == state["guide"]["slug"] else None)

    def _update_guide(gid, updates):
        state["updates"].append(updates)
        state["guide"].update(updates)
        return dict(state["guide"])

    monkeypatch.setattr(G.guide_store, "update_guide", _update_guide)
    monkeypatch.setattr(G, "_get_run", lambda rid: dict(state["run"]) if rid == state["run"]["id"] else None)

    def _set_run(rid, updates):
        state["run"].update(updates)
        return dict(state["run"])

    monkeypatch.setattr(G, "_set_run", _set_run)
    state["notes"] = []
    monkeypatch.setattr(G, "_notify", lambda run, guide: state["notes"].append((run.get("status"), (guide or {}).get("title"))))
    monkeypatch.setattr(settings, "director_enabled", True)
    monkeypatch.setattr(settings, "guide_sync_enabled", True)
    monkeypatch.setattr(settings, "guide_sync_auto_apply", True)
    return state


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_gate_rides_director_master_gate(monkeypatch):
    monkeypatch.setattr(settings, "director_enabled", False)
    monkeypatch.setattr(settings, "guide_sync_enabled", True)
    assert not G.gate_open()
    monkeypatch.setattr(settings, "director_enabled", True)
    assert G.gate_open()
    monkeypatch.setattr(settings, "guide_sync_enabled", False)
    assert not G.gate_open()


def test_clip_text_marks_the_cut():
    assert G.clip_text("abc", 10) == "abc"
    out = G.clip_text("x" * 20, 5)
    assert out.startswith("xxxxx") and "truncated 15" in out
    assert G.clip_text(None, 5) == ""


def test_normalize_change_uses_registry_and_drops_non_user_facing():
    out = G.normalize_change({
        "module": "rank_tracker",
        "files": ["frontend/src/pages/Rankings.tsx", "writer/platform-api/tests/test_rank.py", " "],
        "diff": "d",
        "commits": [{"sha": "a" * 50, "title": "t", "body": "b"}, "junk", {"sha": "", "title": ""}],
    })
    assert out["guide_slug"] == "rank-tracker"
    assert out["module_label"] == "Organic Rank Tracker"
    assert out["files"] == ["frontend/src/pages/Rankings.tsx"]
    assert out["commits"] == [{"sha": "a" * 40, "title": "t", "body": "b"}]


def test_normalize_change_refuses_unmapped_unknown_and_empty():
    assert G.normalize_change({"module": "unmapped", "files": ["frontend/src/App.tsx"]}) is None
    assert G.normalize_change({"module": "not_a_module", "files": ["frontend/src/App.tsx"]}) is None
    assert G.normalize_change({"module": "rank_tracker", "files": ["docs/x.md"]}) is None
    assert G.normalize_change("nope") is None


def test_validate_revision_bands_and_shape(monkeypatch):
    monkeypatch.setattr(settings, "guide_sync_min_ratio", 0.5)
    monkeypatch.setattr(settings, "guide_sync_max_ratio", 2.5)
    prior = "# Guide\n\n" + ("line of text\n" * 20)
    assert G.validate_revision(prior, prior + "- New: CSV export\n") == (True, None)
    assert G.validate_revision(prior, "") == (False, "empty_body")
    assert G.validate_revision(prior, "just prose, no heading") == (False, "not_a_guide")
    assert G.validate_revision(prior, "```md\n# Guide\n```") == (False, "fenced_body")
    assert G.validate_revision(prior, prior) == (False, "identical")
    assert G.validate_revision(prior, "# Guide\nshort")[1].startswith("too_short")
    assert G.validate_revision(prior, prior * 4)[1].startswith("too_long")
    # No prior body → any well-formed guide is fine (a fresh guide).
    assert G.validate_revision("", "# New guide\n\ntext") == (True, None)


def test_summarize_commits_and_prompt_contain_the_inputs():
    text = G.summarize_commits(RUN["commits"] + [{"sha": "", "title": "Second", "body": "l1\nl2"}])
    assert "- Rankings: add a CSV export button (abc1234)" in text
    assert "    l1" in text
    prompt = G.build_review_prompt(GUIDE, RUN)
    assert "MODULE: Organic Rank Tracker" in prompt
    assert "## Tabs" in prompt
    assert "frontend/src/pages/Rankings.tsx" in prompt
    assert "Export CSV" in prompt


def test_notification_copy_per_status():
    applied = G.notification_for({**RUN, "status": "applied", "change_summary": "You can now export CSV."}, "Organic Rank Tracker")
    assert applied["title"] == "DORA updated the “Organic Rank Tracker” guide"
    assert "export CSV" in applied["summary"] and "Revert" in applied["summary"]
    assert "Rankings: add a CSV export button" in applied["summary"]
    proposed = G.notification_for({**RUN, "status": "proposed"}, None)
    assert "proposes" in proposed["title"] and "Apply or Dismiss" in proposed["summary"]
    rejected = G.notification_for({**RUN, "status": "rejected", "error": "too_long:3.10"}, "X")
    assert rejected["severity"] == "warning" and "too_long" in rejected["summary"]
    assert G.notification_for({**RUN, "status": "no_guide"}, None)["severity"] == "info"
    assert G.notification_for({**RUN, "status": "no_change"}, "X") is None
    assert G.notification_for({**RUN, "status": "dismissed"}, "X") is None


# ---------------------------------------------------------------------------
# The review flow
# ---------------------------------------------------------------------------
NEW_BODY = GUIDE["body"] + "\n## Export\n- Click **Export CSV** to download the table.\n"


@pytest.mark.asyncio
async def test_process_run_auto_applies_and_snapshots_prior(fake_store):
    review = {"needs_update": True, "reason": "new button", "change_summary": "CSV export added.",
              "updated_body": NEW_BODY, "updated_summary": "Track rankings + export."}
    with patch.object(G, "review_guide", AsyncMock(return_value=review)):
        row = await G.process_run("r-1")
    assert row["status"] == "applied"
    assert row["prior_body"] == GUIDE["body"]
    assert row["proposed_body"] == NEW_BODY.strip()
    assert fake_store["guide"]["body"] == NEW_BODY.strip()
    assert fake_store["guide"]["summary"] == "Track rankings + export."
    assert fake_store["notes"] == [("applied", "Organic Rank Tracker")]


@pytest.mark.asyncio
async def test_process_run_not_user_visible_is_silent(fake_store):
    review = {"needs_update": False, "reason": "refactor only"}
    with patch.object(G, "review_guide", AsyncMock(return_value=review)):
        row = await G.process_run("r-1")
    assert row["status"] == "no_change"
    assert fake_store["updates"] == []
    assert fake_store["notes"] == []


@pytest.mark.asyncio
async def test_process_run_rejects_a_bad_rewrite_without_writing(fake_store):
    review = {"needs_update": True, "reason": "x", "change_summary": "y", "updated_body": "# Guide\nshort"}
    with patch.object(G, "review_guide", AsyncMock(return_value=review)):
        row = await G.process_run("r-1")
    assert row["status"] == "rejected"
    assert row["error"].startswith("too_short")
    assert fake_store["updates"] == []
    assert fake_store["notes"] == [("rejected", "Organic Rank Tracker")]


@pytest.mark.asyncio
async def test_process_run_identical_rewrite_counts_as_no_change(fake_store):
    review = {"needs_update": True, "reason": "x", "updated_body": GUIDE["body"]}
    with patch.object(G, "review_guide", AsyncMock(return_value=review)):
        row = await G.process_run("r-1")
    assert row["status"] == "no_change" and row["error"] == "identical_body"
    assert fake_store["updates"] == []


@pytest.mark.asyncio
async def test_process_run_parks_a_proposal_when_auto_apply_off(fake_store, monkeypatch):
    monkeypatch.setattr(settings, "guide_sync_auto_apply", False)
    review = {"needs_update": True, "reason": "x", "change_summary": "y", "updated_body": NEW_BODY}
    with patch.object(G, "review_guide", AsyncMock(return_value=review)):
        row = await G.process_run("r-1")
    assert row["status"] == "proposed"
    assert fake_store["guide"]["body"] == GUIDE["body"]  # untouched
    assert fake_store["notes"] == [("proposed", "Organic Rank Tracker")]


@pytest.mark.asyncio
async def test_process_run_llm_failure_is_recorded_and_flagged(fake_store):
    with patch.object(G, "review_guide", AsyncMock(side_effect=RuntimeError("boom"))):
        row = await G.process_run("r-1")
    assert row["status"] == "failed" and "boom" in row["error"]
    assert fake_store["notes"] == [("failed", "Organic Rank Tracker")]


@pytest.mark.asyncio
async def test_process_run_no_guide(fake_store):
    fake_store["run"]["guide_slug"] = "nope"
    with patch.object(G, "review_guide", AsyncMock()) as rv:
        row = await G.process_run("r-1")
    assert row["status"] == "no_guide"
    rv.assert_not_called()
    assert fake_store["notes"] == [("no_guide", None)]


@pytest.mark.asyncio
async def test_process_run_skips_an_already_settled_run(fake_store):
    fake_store["run"]["status"] = "applied"
    with patch.object(G, "review_guide", AsyncMock()) as rv:
        row = await G.process_run("r-1")
    assert row["status"] == "applied"
    rv.assert_not_called()


# ---------------------------------------------------------------------------
# Human decisions
# ---------------------------------------------------------------------------
def test_apply_then_revert_round_trip(fake_store):
    fake_store["run"].update({"status": "proposed", "proposed_body": NEW_BODY, "proposed_summary": "S2"})
    fake_store["guide"]["body"] = "# Organic Rank Tracker\n\nhand-edited since\n" * 3
    edited = fake_store["guide"]["body"]
    row = G.apply_run("r-1", decided_by="u-1")
    assert row["status"] == "applied" and row["decided_by"] == "u-1"
    assert row["prior_body"] == edited  # re-snapshotted at apply time
    assert fake_store["guide"]["body"] == NEW_BODY and fake_store["guide"]["summary"] == "S2"
    row = G.revert_run("r-1", decided_by="u-2")
    assert row["status"] == "reverted"
    assert fake_store["guide"]["body"] == edited
    assert fake_store["guide"]["summary"] == "Track rankings."


def test_decisions_refuse_wrong_status(fake_store):
    fake_store["run"]["status"] = "no_change"
    with pytest.raises(HTTPException) as exc:
        G.revert_run("r-1")
    assert exc.value.status_code == 409 and exc.value.detail == "guide_sync_run_no_change"
    with pytest.raises(HTTPException):
        G.apply_run("r-1")
    with pytest.raises(HTTPException) as exc:
        G.dismiss_run("missing")
    assert exc.value.status_code == 404


def test_dismiss_proposed_or_failed(fake_store):
    fake_store["run"]["status"] = "failed"
    assert G.dismiss_run("r-1", "u")["status"] == "dismissed"
    assert fake_store["updates"] == []


# ---------------------------------------------------------------------------
# Ingest (idempotent per commit+module) + the read-model rollup
# ---------------------------------------------------------------------------
def test_ingest_records_once_per_commit_module_and_enqueues(monkeypatch):
    fake = FakeSupabase()
    fake.tables["guides"].append({**GUIDE})
    monkeypatch.setattr(G, "get_supabase", lambda: fake)
    monkeypatch.setattr(G.guide_store, "get_guide", lambda slug: GUIDE if slug == "rank-tracker" else None)
    payload = {
        "commit_sha": "abc1234abc1234",
        "commit_range": "111..222",
        "changes": [
            {"module": "rank_tracker", "files": ["frontend/src/pages/Rankings.tsx"], "diff": "+x",
             "commits": [{"sha": "abc1234abc1234", "title": "Add export"}]},
            {"module": "unmapped", "files": ["writer/platform-api/services/report_llm.py"]},
            {"module": "rank_tracker", "files": ["docs/only.md"]},
        ],
    }
    out = G.ingest_module_changes(payload)
    assert len(out["accepted"]) == 1 and out["skipped"] == 2
    run = fake.tables["guide_sync_runs"][0]
    assert run["guide_id"] == "g-1" and run["status"] == "queued" and run["guide_slug"] == "rank-tracker"
    assert fake.tables["async_jobs"][0]["job_type"] == "guide_sync"
    assert fake.tables["async_jobs"][0]["entity_id"] == run["id"]
    # Re-delivery: nothing new recorded, nothing re-enqueued.
    again = G.ingest_module_changes(payload)
    assert again["accepted"] == [] and again["skipped"] == 3
    assert len(fake.tables["guide_sync_runs"]) == 1 and len(fake.tables["async_jobs"]) == 1


def test_ingest_requires_commit_sha(monkeypatch):
    monkeypatch.setattr(G, "get_supabase", lambda: FakeSupabase())
    assert G.ingest_module_changes({"changes": []})["error"] == "missing_commit_sha"


def test_recent_activity_rollup(monkeypatch):
    monkeypatch.setattr(settings, "guide_sync_enabled", True)
    fake = FakeSupabase()
    fake.tables["guide_sync_runs"] = [
        {"id": "1", "module_label": "A", "guide_slug": "a", "status": "applied", "change_summary": "x",
         "commits": [{"title": "c1"}], "created_at": "2026-09-01T00:00:00+00:00"},
        {"id": "2", "module_label": "B", "guide_slug": "b", "status": "proposed", "reason": "r",
         "commits": [], "created_at": "2026-09-01T00:00:00+00:00"},
        {"id": "3", "module_label": "C", "guide_slug": "c", "status": "no_change",
         "commits": [], "created_at": "2026-09-01T00:00:00+00:00"},
        {"id": "4", "module_label": "D", "guide_slug": "d", "status": "applied",
         "commits": [], "created_at": "2026-01-01T00:00:00+00:00"},  # outside the window
    ]
    out = G.recent_activity(fake, date(2026, 9, 2), days=30)
    assert out["runs"] == 3
    assert out["by_status"] == {"applied": 1, "proposed": 1, "no_change": 1}
    assert [p["guide_slug"] for p in out["open_proposals"]] == ["b"]
    assert out["recent"][0] == {"run_id": "1", "guide_slug": "a", "module": "A", "status": "applied",
                                "what_changed": "x", "commit": "c1", "at": "2026-09-01T00:00:00+00:00"}
    assert G.recent_activity(FakeSupabase(), date(2026, 9, 2)) is None
    monkeypatch.setattr(settings, "guide_sync_enabled", False)
    assert G.recent_activity(fake, date(2026, 9, 2)) is None


@pytest.mark.asyncio
async def test_job_handler_settles_dark_without_llm(monkeypatch):
    fake = FakeSupabase()
    fake.tables["async_jobs"].append({"id": "j1", "job_type": "guide_sync", "status": "running"})
    fake.tables["guide_sync_runs"].append({"id": "r-1", "status": "queued"})
    monkeypatch.setattr(G, "get_supabase", lambda: fake)
    monkeypatch.setattr(settings, "director_enabled", False)
    with patch.object(G, "process_run", AsyncMock()) as pr:
        await G.run_guide_sync_job({"id": "j1", "payload": {"run_id": "r-1"}})
    pr.assert_not_called()
    assert fake.tables["async_jobs"][0]["status"] == "complete"
    assert fake.tables["guide_sync_runs"][0]["status"] == "dismissed"
