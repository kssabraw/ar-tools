"""Unit tests for deploy resolution.

The two values that carry the weight here are 'superseded' and 'unknown'. Both
exist because the obvious mapping — everything that is not a success is a
failure — produces a wall of red on a successful batch publish and sends people
to re-push a site that already shipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from services import website_deploy as wd
from services import website_provision as wpv

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class TestStatusMapping:
    def test_in_flight_runs_are_building(self):
        assert wpv.deploy_status_from_run({"status": "in_progress"}) == "building"
        assert wpv.deploy_status_from_run({"status": "queued"}) == "building"

    def test_success_is_success(self):
        assert wpv.deploy_status_from_run({"status": "completed", "conclusion": "success"}) == "success"

    def test_cancelled_is_superseded_not_failed(self):
        # The template's workflow sets cancel-in-progress, so a batch publish
        # cancels every run but the last. Those runs' content shipped in the run
        # that replaced them.
        run = {"status": "completed", "conclusion": "cancelled"}
        assert wpv.deploy_status_from_run(run) == "superseded"

    @pytest.mark.parametrize("conclusion", ["failure", "timed_out", "startup_failure", ""])
    def test_everything_else_completed_is_a_failure(self, conclusion):
        run = {"status": "completed", "conclusion": conclusion}
        assert wpv.deploy_status_from_run(run) == "failed"


class TestMatchRun:
    RUNS = [
        {"id": 3, "head_sha": "ccc"},
        {"id": 2, "head_sha": "bbb"},
        {"id": 1, "head_sha": "aaa"},
    ]

    def test_matched_on_commit_not_on_recency(self):
        # A batch publish pushes several commits; "the newest run" is the wrong
        # run for every deploy but one.
        assert wd.match_run({"commit_sha": "aaa"}, self.RUNS)["id"] == 1

    def test_a_known_run_id_wins(self):
        assert wd.match_run({"actions_run_id": "2", "commit_sha": "aaa"}, self.RUNS)["id"] == 2

    def test_no_match_returns_none(self):
        assert wd.match_run({"commit_sha": "zzz"}, self.RUNS) is None

    def test_a_deploy_with_no_sha_cannot_be_matched(self):
        assert wd.match_run({}, self.RUNS) is None


class TestResolveDeploy:
    def test_a_matched_run_carries_its_url_and_id(self):
        patch_ = wd.resolve_deploy(
            {"status": "queued", "commit_sha": "aaa"},
            {"id": 7, "status": "completed", "conclusion": "success",
             "head_sha": "aaa", "html_url": "https://gh/run/7"},
            now=NOW,
            timeout_minutes=20,
        )
        assert patch_["status"] == "success"
        assert patch_["actions_run_id"] == "7"
        assert patch_["url"] == "https://gh/run/7"

    def test_no_change_writes_nothing(self):
        patch_ = wd.resolve_deploy(
            {"status": "building", "actions_run_id": "7", "commit_sha": "aaa"},
            {"id": 7, "status": "in_progress"},
            now=NOW,
            timeout_minutes=20,
        )
        assert patch_ == {}

    def test_a_young_unmatched_deploy_is_left_alone(self):
        # The run may simply not have registered yet.
        deploy = {"status": "queued", "created_at": (NOW - timedelta(minutes=2)).isoformat()}
        assert wd.resolve_deploy(deploy, None, now=NOW, timeout_minutes=20) == {}

    def test_a_timed_out_deploy_is_unknown_never_failed(self):
        # PRD §6.3: the site is very likely serving fine and we simply stopped
        # being able to see the run. Reporting that as failed sends someone to
        # re-push a site that already shipped.
        deploy = {"status": "queued", "created_at": (NOW - timedelta(minutes=45)).isoformat()}
        patch_ = wd.resolve_deploy(deploy, None, now=NOW, timeout_minutes=20)
        assert patch_["status"] == "unknown"
        assert patch_["error"] == "deploy_run_not_found"

    def test_an_already_unknown_deploy_is_not_rewritten(self):
        deploy = {"status": "unknown", "created_at": (NOW - timedelta(hours=3)).isoformat()}
        assert wd.resolve_deploy(deploy, None, now=NOW, timeout_minutes=20) == {}

    def test_an_unknown_deploy_recovers_when_its_run_reappears(self):
        deploy = {"status": "unknown", "commit_sha": "aaa",
                  "created_at": (NOW - timedelta(hours=3)).isoformat()}
        run = {"id": 9, "status": "completed", "conclusion": "success", "head_sha": "aaa"}
        assert wd.resolve_deploy(deploy, run, now=NOW, timeout_minutes=20)["status"] == "success"


class TestNotifications:
    def test_success_notifies(self):
        note = wd.notification_for("success", {"name": "Acme"}, {"url": "https://x"})
        assert note["kind"] == "website_deployed"
        assert note["severity"] == "info"

    def test_failure_says_the_site_is_still_serving(self):
        # A red chip with no context reads as "the site is down".
        note = wd.notification_for("failed", {"name": "Acme"}, {})
        assert note["kind"] == "website_deploy_failed"
        assert "still serving" in note["summary"]

    @pytest.mark.parametrize("status", ["superseded", "unknown", "building", "queued"])
    def test_the_quiet_statuses_stay_quiet(self, status):
        # Superseded is the normal shape of a batch publish; unknown is a chip
        # with a re-check button. Alarming on either is noise on the one signal
        # that has to stay credible.
        assert wd.notification_for(status, {"name": "Acme"}, {}) is None


class TestScheduler:
    def test_the_sweep_is_inert_while_the_module_is_dark(self):
        with patch.object(wd.settings, "website_builder_enabled", False), patch.object(
            wd, "get_supabase"
        ) as sb:
            assert wd.enqueue_due_deploy_polls() == 0
        sb.assert_not_called()

    def test_one_poll_job_per_site_with_pending_deploys(self):
        rows = [{"website_id": "w1"}, {"website_id": "w1"}, {"website_id": "w2"}]
        client = MagicMock()
        chain = client.table.return_value
        chain.select.return_value = chain
        chain.in_.return_value = chain
        chain.limit.return_value = chain
        chain.execute.return_value = MagicMock(data=rows)
        with patch.object(wd.settings, "website_builder_enabled", True), patch.object(
            wd, "get_supabase", return_value=client
        ), patch.object(wd, "enqueue_deploy_poll", side_effect=lambda wid: f"job-{wid}") as enq:
            assert wd.enqueue_due_deploy_polls() == 2
        assert {c.args[0] for c in enq.call_args_list} == {"w1", "w2"}
