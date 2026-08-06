"""Unit tests for the Website Builder's pure provisioning logic.

Everything here runs without GitHub, Cloudflare or Supabase — the step machine's
resumability and the §4.5 business-fact precedence are the two things most
likely to break silently, so they get the most attention.
"""

from __future__ import annotations

import json

import pytest

from services import website_provision as wp


class TestSlugs:
    def test_slugify_normalizes(self):
        assert wp.slugify("Ridgeline Roofing, LLC") == "ridgeline-roofing-llc"

    def test_slugify_collapses_and_trims_separators(self):
        assert wp.slugify("  --Foo___Bar!!  ") == "foo-bar"

    def test_slugify_never_returns_empty(self):
        # A name of pure punctuation must still yield a usable repo/worker name.
        assert wp.slugify("!!!") == "site"
        assert wp.slugify("") == "site"

    def test_slugify_bounded(self):
        assert len(wp.slugify("x" * 200)) <= 54

    def test_repo_and_worker_share_the_slug(self):
        # They must stay in step: the repo is the site and the worker serves it.
        assert wp.repo_name("Acme Co") == wp.worker_name("Acme Co") == "site-acme-co"

    def test_staging_url(self):
        assert wp.staging_url("site-acme", "kyle") == "https://site-acme.kyle.workers.dev"


class TestStepMachine:
    def test_first_step_on_empty_state(self):
        assert wp.next_step({}) == "generate"

    def test_resumes_at_first_incomplete_step(self):
        state = {"done": ["generate", "secrets"]}
        assert wp.next_step(state) == "configure"

    def test_complete_returns_none(self):
        assert wp.next_step({"done": list(wp.STEPS)}) is None

    def test_mark_done_is_idempotent(self):
        state = wp.mark_done({"done": ["generate"]}, "generate")
        assert state["done"] == ["generate"]

    def test_mark_done_preserves_order_and_other_keys(self):
        state = wp.mark_done({"done": ["generate"], "note": "x"}, "secrets")
        assert state["done"] == ["generate", "secrets"]
        assert state["note"] == "x"

    def test_out_of_order_completion_still_reports_earliest_gap(self):
        # A step marked done out of order must not let an earlier one be skipped.
        assert wp.next_step({"done": ["generate", "configure"]}) == "secrets"


class TestSiteConfig:
    def _site(self, **over):
        return {"name": "Acme Roofing", "site_type": "local_business", "config": {}, **over}

    def test_gbp_fills_empty_business_facts(self):
        cfg = wp.build_site_config(
            self._site(),
            {"name": "Acme", "gbp": {"phone": "+1 816 555 0142", "city": "Kansas City"}},
        )
        assert cfg["business"]["phoneReal"] == "+1 816 555 0142"
        assert cfg["business"]["provenance"]["phoneReal"] == "gbp"

    def test_user_entered_facts_win_over_gbp(self):
        # §4.5: a later GBP sync fills gaps but never overwrites a human's entry.
        site = self._site(config={"business": {"phoneReal": "+1 999 000 0000"}})
        cfg = wp.build_site_config(site, {"gbp": {"phone": "+1 816 555 0142"}})
        assert cfg["business"]["phoneReal"] == "+1 999 000 0000"
        assert cfg["business"]["provenance"]["phoneReal"] == "user"

    def test_no_gbp_leaves_facts_absent_rather_than_blank(self):
        cfg = wp.build_site_config(self._site(), {"name": "Acme"})
        b = cfg["business"]
        # Absent, not empty strings — the template hides sections on falsy values
        # either way, but absent keeps "we never learned this" distinguishable.
        assert "street" not in b and "postalCode" not in b

    def test_service_area_places_become_area_served(self):
        cfg = wp.build_site_config(
            self._site(), {"gbp": {"service_area_places": ["Olathe", "Lenexa"]}}
        )
        assert cfg["business"]["areaServed"] == ["Olathe", "Lenexa"]

    def test_area_served_is_capped(self):
        cfg = wp.build_site_config(
            self._site(), {"gbp": {"service_area_places": [f"City{i}" for i in range(30)]}}
        )
        assert len(cfg["business"]["areaServed"]) == 12

    def test_custom_domain_wins_over_staging_for_canonical_url(self):
        site = self._site(custom_domain="acme.com", staging_url="https://x.workers.dev")
        assert wp.build_site_config(site, {})["url"] == "https://acme.com"

    def test_staging_url_used_before_a_domain_exists(self):
        site = self._site(staging_url="https://x.workers.dev")
        assert wp.build_site_config(site, {})["url"] == "https://x.workers.dev"

    def test_no_nav_is_guessed_at_provisioning_time(self):
        # The template derives the SOP global nav set from published pages. The
        # guess this replaced pointed at /services, /locations, /about and
        # /contact — none of them routes, so every generated site carried a
        # global nav of dead links on every page.
        for site_type in ("local_business", "informational"):
            config = wp.build_site_config(self._site(site_type=site_type), {})
            assert config["nav"] == []
            assert config["footerNav"] == []

    def test_existing_nav_is_preserved(self):
        site = self._site(config={"nav": [{"label": "Work", "href": "/work"}]})
        assert wp.build_site_config(site, {})["nav"] == [{"label": "Work", "href": "/work"}]


class TestWrangler:
    def test_worker_name_is_set_and_output_is_valid_json(self):
        parsed = json.loads(wp.build_wrangler("site-acme"))
        assert parsed["name"] == "site-acme"
        assert parsed["assets"]["directory"] == "./dist"


class TestDeployStatus:
    @pytest.mark.parametrize("status", ["queued", "in_progress", "waiting"])
    def test_incomplete_runs_are_building(self, status):
        assert wp.deploy_status_from_run({"status": status}) == "building"

    def test_completed_success(self):
        assert (
            wp.deploy_status_from_run({"status": "completed", "conclusion": "success"})
            == "success"
        )

    @pytest.mark.parametrize("conclusion", ["failure", "timed_out", "skipped", None])
    def test_any_other_completed_conclusion_is_failure(self, conclusion):
        # Nothing shipped, so nothing is "sort of deployed".
        assert (
            wp.deploy_status_from_run({"status": "completed", "conclusion": conclusion})
            == "failed"
        )

    def test_cancelled_is_superseded_rather_than_failed(self):
        # The template's workflow sets `concurrency: cancel-in-progress: true`,
        # so publishing a batch cancels every run but the last. The content
        # those runs carried shipped in the run that replaced them, and calling
        # that failed paints a successful 20-page batch red 19 times.
        assert (
            wp.deploy_status_from_run({"status": "completed", "conclusion": "cancelled"})
            == "superseded"
        )


class TestSecretEncryption:
    def test_missing_pynacl_raises_a_clear_code(self, monkeypatch):
        # The dependency is imported lazily so the rest of the module keeps
        # working without it; the failure must still be legible.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("nacl"):
                raise ImportError("no nacl")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(wp.ProvisionError, match="pynacl_not_installed"):
            wp.encrypt_secret("aGVsbG8=", "value")
