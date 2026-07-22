"""Content Scheduler worker unit tests — the GitHub auto-publish gate + payload
wiring (pure logic; no DB / no network)."""

from __future__ import annotations

from services.content_batch import _job_payload, _should_github_publish


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
