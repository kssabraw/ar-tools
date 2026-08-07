"""Unit tests for editing a site's business facts.

The load-bearing property is provenance: a field a person edits must survive a
later GBP re-scan, and a field they clear must go back to GBP. These tests pin
that against the real `build_site_config` fill step, because the two are only
correct together — the editor stamps `user`, and the fill step is what reads the
stamp.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import website_settings as ws
from services.website_provision import build_site_config


class TestApplyEdit:
    def test_a_set_field_is_stamped_user(self):
        out = ws.apply_facts_edit({}, business={"phoneReal": "555-1234"})
        assert out["business"]["phoneReal"] == "555-1234"
        assert out["business"]["provenance"]["phoneReal"] == "user"

    def test_the_input_config_is_not_mutated(self):
        original = {"business": {"name": "Old"}}
        ws.apply_facts_edit(original, business={"name": "New"})
        assert original["business"]["name"] == "Old"

    def test_clearing_a_field_hands_it_back_to_gbp(self):
        # Empty value → drop the value AND its stamp, so build_site_config's fill
        # step refills it from GBP rather than seeing a user-owned blank.
        cfg = {"business": {"city": "Anaheim", "provenance": {"city": "user"}}}
        out = ws.apply_facts_edit(cfg, business={"city": ""})
        assert "city" not in out["business"]
        assert "city" not in out["business"]["provenance"]

    def test_an_absent_field_is_untouched(self):
        cfg = {"business": {"name": "Acme", "provenance": {"name": "user"}}}
        out = ws.apply_facts_edit(cfg, business={"phoneReal": "555"})
        assert out["business"]["name"] == "Acme"

    def test_area_served_is_a_capped_cleaned_list(self):
        out = ws.apply_facts_edit({}, business={"areaServed": ["  Brea ", "", "Yorba Linda"] + [f"c{i}" for i in range(20)]})
        assert out["business"]["areaServed"][:2] == ["Brea", "Yorba Linda"]
        assert len(out["business"]["areaServed"]) == 12
        assert out["business"]["provenance"]["areaServed"] == "user"

    def test_tagline_and_description_are_plain_overrides(self):
        out = ws.apply_facts_edit({"tagline": "old"}, tagline="Roofs done right", description="")
        assert out["tagline"] == "Roofs done right"
        assert out["description"] == ""

    def test_only_whitelisted_integration_keys_are_written(self):
        out = ws.apply_facts_edit(
            {"forms": {"web3formsKey": "old"}},
            forms={"web3formsKey": "new", "evilKey": "x"},
            analytics={"ga4": "G-123"},
        )
        assert out["forms"] == {"web3formsKey": "new"}
        assert "evilKey" not in out["forms"]
        assert out["analytics"]["ga4"] == "G-123"

    def test_an_unknown_business_field_is_ignored(self):
        out = ws.apply_facts_edit({}, business={"mapPlaceId": "spoofed", "name": "Acme"})
        # mapPlaceId is GBP-only; a settings edit can't set it.
        assert "mapPlaceId" not in out["business"]
        assert out["business"]["name"] == "Acme"


class TestProvenanceInteractsWithGbp:
    """The whole point, verified against the real build."""

    CLIENT = {"id": "c1", "name": "Client Name", "gbp": {"phone": "555-GBP", "city": "GbpCity"}}

    def test_a_user_edit_survives_the_gbp_fill(self):
        edited = ws.apply_facts_edit({}, business={"phoneReal": "555-USER"})
        website = {"name": "Acme", "site_type": "local_business", "config": edited}
        built = build_site_config(website, self.CLIENT)
        # GBP has a phone, but the user set one — the user's wins and stays user.
        assert built["business"]["phoneReal"] == "555-USER"
        assert built["business"]["provenance"]["phoneReal"] == "user"
        # A field the user never touched still fills from GBP.
        assert built["business"]["city"] == "GbpCity"
        assert built["business"]["provenance"]["city"] == "gbp"

    def test_a_cleared_field_refills_from_gbp(self):
        cfg = {"business": {"city": "WasUser", "provenance": {"city": "user"}}}
        cleared = ws.apply_facts_edit(cfg, business={"city": ""})
        website = {"name": "Acme", "site_type": "local_business", "config": cleared}
        built = build_site_config(website, self.CLIENT)
        assert built["business"]["city"] == "GbpCity"
        assert built["business"]["provenance"]["city"] == "gbp"


class TestFactsView:
    def test_the_view_labels_each_field_by_source(self):
        website = {"name": "Acme", "site_type": "local_business",
                   "config": {"business": {"name": "User Co", "provenance": {"name": "user"}}}}
        client = {"id": "c1", "gbp": {"city": "GbpCity"}}
        view = ws.facts_view(build_site_config(website, client))
        assert view["business"]["name"] == "User Co"
        assert view["provenance"]["name"] == "user"
        assert view["provenance"]["city"] == "gbp"
        # A field neither source supplied is unset, not a phantom value.
        assert view["business"]["region"] == ""
        assert view["provenance"]["region"] is None


class TestSave:
    @pytest.mark.asyncio
    async def test_an_unprovisioned_site_saves_without_a_deploy(self, monkeypatch):
        website = {"id": "w1", "client_id": "c1", "github_repo": None, "config": {}}
        supabase = MagicMock()
        supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{**website, "config": {"business": {"name": "Acme"}}}]
        )
        monkeypatch.setattr(ws, "_load", lambda wid: (website, {"id": "c1"}))
        monkeypatch.setattr("db.supabase_client.get_supabase", lambda: supabase)
        commit = AsyncMock()
        with patch("services.github_publish.commit_files_to_github", new=commit):
            out = await ws.save_facts("w1", {"business": {"name": "Acme"}})
        assert out["committed"] is False
        commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_provisioned_site_recommits_and_records_a_config_deploy(self, monkeypatch):
        website = {"id": "w1", "client_id": "c1", "name": "Acme",
                   "site_type": "local_business", "github_repo": "kssabraw/acme", "config": {}}
        supabase = MagicMock()
        supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[website]
        )
        supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "deploy-1"}]
        )
        monkeypatch.setattr(ws, "_load", lambda wid: (website, {"id": "c1"}))
        monkeypatch.setattr("db.supabase_client.get_supabase", lambda: supabase)

        commit = AsyncMock(return_value={"commit_sha": "abc123"})
        with patch("services.github_publish.commit_files_to_github", new=commit):
            out = await ws.save_facts("w1", {"tagline": "Roofs"})
        assert out["committed"] is True
        assert out["deploy_id"] == "deploy-1"
        commit.assert_called_once()
        # The deploy row is a 'config' trigger (allowed by the live CHECK).
        insert_arg = supabase.table.return_value.insert.call_args[0][0]
        assert insert_arg["trigger"] == "config"
        assert insert_arg["commit_sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_a_commit_failure_keeps_the_saved_facts(self, monkeypatch):
        website = {"id": "w1", "client_id": "c1", "name": "Acme",
                   "site_type": "local_business", "github_repo": "kssabraw/acme", "config": {}}
        supabase = MagicMock()
        supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[website]
        )
        monkeypatch.setattr(ws, "_load", lambda wid: (website, {"id": "c1"}))
        monkeypatch.setattr("db.supabase_client.get_supabase", lambda: supabase)

        commit = AsyncMock(side_effect=RuntimeError("github down"))
        with patch("services.github_publish.commit_files_to_github", new=commit):
            out = await ws.save_facts("w1", {"tagline": "Roofs"})
        # The facts are saved; only the redeploy failed — reported, not raised.
        assert out["committed"] is False
