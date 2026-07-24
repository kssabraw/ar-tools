"""Content Scheduler worker unit tests — the GitHub auto-publish gate + payload
wiring + the transient-failure item retry (DB mocked; no network)."""

from __future__ import annotations

from unittest.mock import MagicMock

import services.content_batch as cb
from config import settings
from services.content_batch import _job_payload, _reschedule_or_fail, _should_github_publish


class TestShouldGithubPublish:
    def test_blog_post_run_opted_in_publishes(self):
        assert _should_github_publish("blog_post", "run", True) is True

    def test_opt_out_never_publishes(self):
        assert _should_github_publish("blog_post", "run", False) is False

    def test_non_blog_types_do_not_publish(self):
        # GitHub auto-publish is scoped to blog posts (the media SOP path) for v1.
        assert _should_github_publish("service_page", "run", True) is False
        assert _should_github_publish("local_seo_page", "local_seo_page", True) is False
        assert _should_github_publish("ecommerce", "ecommerce_page", True) is False

    def test_non_run_result_kind_does_not_publish(self):
        # Only an actual suite run (which carries publishable module output) qualifies.
        assert _should_github_publish("blog_post", "local_seo_page", True) is False

    def test_falsy_inputs(self):
        assert _should_github_publish(None, None, True) is False
        assert _should_github_publish("blog_post", "run", 0) is False  # type: ignore[arg-type]


class TestJobPayloadCarriesGithubPublish:
    def _batch(self, **over) -> dict:
        base = {
            "id": "b1", "client_id": "c1", "content_type": "blog_post",
            "created_by": "u1",
        }
        base.update(over)
        return base

    def _item(self) -> dict:
        return {"id": "i1", "keyword": "how to unblock a drain"}

    def test_github_publish_true_threads_through(self):
        payload = _job_payload(self._batch(github_publish=True), self._item())
        assert payload["github_publish"] is True
        assert payload["content_type"] == "blog_post"
        assert payload["keyword"] == "how to unblock a drain"

    def test_github_publish_defaults_false_when_absent(self):
        payload = _job_payload(self._batch(), self._item())
        assert payload["github_publish"] is False


class TestRescheduleOrFail:
    """The content-batch transient-failure retry: re-schedule with backoff up to
    run_transient_retry_max, then terminally fail. Mirrors the fanout scheduler's
    own retry so `disarm_scheduled_retry` is correct for content batches too."""

    def _fake_supabase(self):
        sb = MagicMock()
        # .table(...).update(...).eq(...).execute() chains to a no-op.
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = None
        return sb

    def test_first_transient_failure_reschedules_with_incremented_attempt(self, monkeypatch):
        monkeypatch.setattr(settings, "run_transient_retry_max", 3)
        resched = MagicMock()
        finish = MagicMock()
        monkeypatch.setattr(cb.store, "reschedule_item_for_retry", resched)
        monkeypatch.setattr(cb.store, "finish_item", finish)

        _reschedule_or_fail(self._fake_supabase(), {"id": "i1", "retry_attempt": 0}, "job1", "boom")

        finish.assert_not_called()  # not terminal — it retries
        assert resched.call_count == 1
        args, _ = resched.call_args
        assert args[0] == "i1"        # item_id
        assert args[2] == 1           # next attempt = prior 0 + 1

    def test_missing_retry_attempt_treated_as_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "run_transient_retry_max", 3)
        resched = MagicMock()
        monkeypatch.setattr(cb.store, "reschedule_item_for_retry", resched)
        monkeypatch.setattr(cb.store, "finish_item", MagicMock())

        _reschedule_or_fail(self._fake_supabase(), {"id": "i1"}, "job1", "boom")

        assert resched.call_args[0][2] == 1

    def test_exhausted_budget_fails_terminally(self, monkeypatch):
        monkeypatch.setattr(settings, "run_transient_retry_max", 3)
        resched = MagicMock()
        finish = MagicMock()
        monkeypatch.setattr(cb.store, "reschedule_item_for_retry", resched)
        monkeypatch.setattr(cb.store, "finish_item", finish)

        _reschedule_or_fail(self._fake_supabase(), {"id": "i1", "retry_attempt": 3}, "job1", "boom")

        resched.assert_not_called()   # no further retry
        finish.assert_called_once()
        assert finish.call_args[0][1] == "failed"

    def test_disabled_when_max_zero(self, monkeypatch):
        monkeypatch.setattr(settings, "run_transient_retry_max", 0)
        resched = MagicMock()
        finish = MagicMock()
        monkeypatch.setattr(cb.store, "reschedule_item_for_retry", resched)
        monkeypatch.setattr(cb.store, "finish_item", finish)

        _reschedule_or_fail(self._fake_supabase(), {"id": "i1", "retry_attempt": 0}, "job1", "boom")

        resched.assert_not_called()   # attempt 0 >= max 0 → straight to failed
        finish.assert_called_once()
