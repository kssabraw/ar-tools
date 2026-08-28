"""Unit tests for the owned-property backing of a standalone website.

The load-bearing rules: a property is minted as a `kind='owned_property'` client
so every generator works unchanged; its globally-unique name is disambiguated on
collision without polluting the public business name; and its brand voice is
editable from the site only when it really is a property, never for a real client.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import website_owner as wo


class _FakeTable:
    def __init__(self, sb, name):
        self.sb = sb
        self.name = name
        self._op = None
        self._payload = None

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self.name == "clients" and self._op == "insert":
            row = self._payload
            if row["name"] in self.sb.fail_names:
                raise Exception('duplicate key value violates unique constraint "clients_name_unique"')
            self.sb.clients_inserted.append(row)
            return MagicMock(data=[{"id": "c1", **row}])
        if self.name == "clients" and self._op == "update":
            self.sb.clients_updated.append(self._payload)
            return MagicMock(data=[{"id": "c1"}])
        if self.name == "async_jobs" and self._op == "insert":
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            self.sb.jobs_inserted.extend(rows)
            return MagicMock(data=[])
        return MagicMock(data=[])


class _FakeSupabase:
    def __init__(self, fail_names=()):
        self.fail_names = set(fail_names)
        self.clients_inserted: list = []
        self.clients_updated: list = []
        self.jobs_inserted: list = []

    def table(self, name):
        return _FakeTable(self, name)


class TestBuildPropertyRow:
    def test_it_is_an_owned_property(self):
        row = wo.build_property_row(name="  Tree Pros  ")
        assert row["kind"] == "owned_property"
        assert row["name"] == "Tree Pros"

    def test_status_is_pending_only_with_a_url(self):
        assert wo.build_property_row(name="X", website_url="https://x.com")["website_analysis_status"] == "pending"
        # No URL: nothing to analyze, so 'complete' rather than a stuck 'pending'.
        assert wo.build_property_row(name="X")["website_analysis_status"] == "complete"

    def test_a_typed_guide_becomes_canonical_brand_voice(self):
        row = wo.build_property_row(name="X", brand_voice_text="Sound friendly.", icp_text="Homeowners.")
        assert row["brand_voice"]["raw_text"] == "Sound friendly."
        assert row["brand_voice"]["source"] == "user"
        assert row["detected_icp"]["raw_text"] == "Homeowners."

    def test_no_guide_leaves_the_fields_off(self):
        row = wo.build_property_row(name="X")
        assert "brand_voice" not in row
        assert "detected_icp" not in row

    def test_a_property_opts_out_of_the_strategist_by_default(self):
        assert wo.build_property_row(name="X")["strategist_enabled"] is False


class TestNameCandidates:
    def test_disambiguates_in_order(self):
        cands = wo._name_candidates("Tree Pros", "seattle")
        assert cands[0] == "Tree Pros"
        assert cands[1] == "Tree Pros (seattle)"
        assert cands[2].startswith("Tree Pros (")  # uuid fallback


class TestCreatePropertyClient:
    def test_it_inserts_a_property(self):
        sb = _FakeSupabase()
        with patch.object(wo, "get_supabase", return_value=sb):
            client = wo.create_property_client(name="Tree Pros", user_id="u1")
        assert client["kind"] == "owned_property"
        assert sb.clients_inserted[0]["name"] == "Tree Pros"

    def test_it_retries_on_a_name_collision(self):
        # The globally-unique name collides; the disambiguated candidate wins, and
        # the clean public name still lives on config.business elsewhere.
        sb = _FakeSupabase(fail_names={"Tree Pros"})
        with patch.object(wo, "get_supabase", return_value=sb):
            client = wo.create_property_client(name="Tree Pros", disambiguator="seattle-tree-pros", user_id="u1")
        assert client["name"] == "Tree Pros (seattle-tree-pros)"

    def test_a_url_enqueues_the_auto_scan(self):
        sb = _FakeSupabase()
        with patch.object(wo, "get_supabase", return_value=sb), patch.object(
            wo.settings, "auto_generate_brand_voice_icp", True
        ):
            wo.create_property_client(name="X", website_url="https://x.com", user_id="u1")
        assert {j["job_type"] for j in sb.jobs_inserted} == {"brand_voice_scan", "icp_scan"}

    def test_no_url_enqueues_nothing(self):
        sb = _FakeSupabase()
        with patch.object(wo, "get_supabase", return_value=sb):
            wo.create_property_client(name="X", user_id="u1")
        assert sb.jobs_inserted == []


class TestBrandEditing:
    PROPERTY = ({"id": "w1", "client_id": "c1"},
                {"id": "c1", "kind": "owned_property", "strategist_enabled": False,
                 "brand_voice": {"raw_text": "friendly", "source": "user"}})
    CLIENT = ({"id": "w1", "client_id": "c1"}, {"id": "c1", "kind": "client"})

    def test_get_brand_is_editable_only_for_a_property(self):
        with patch.object(wo, "_load", return_value=self.PROPERTY), patch(
            "services.website_generate.has_brand_context", return_value=True
        ):
            out = wo.get_brand("w1")
        assert out["editable"] is True
        assert out["brand_voice"] == "friendly"
        assert out["has_context"] is True

    def test_get_brand_not_editable_for_a_real_client(self):
        with patch.object(wo, "_load", return_value=self.CLIENT), patch(
            "services.website_generate.has_brand_context", return_value=False
        ):
            assert wo.get_brand("w1")["editable"] is False

    def test_set_brand_refuses_a_real_client(self):
        with patch.object(wo, "_load", return_value=self.CLIENT):
            with pytest.raises(wo.OwnerError) as ei:
                wo.set_brand("w1", brand_voice="x")
        assert ei.value.code == "not_a_property"
        assert ei.value.status == 409

    def test_set_brand_writes_the_merged_voice(self):
        sb = _FakeSupabase()
        with patch.object(wo, "_load", return_value=self.PROPERTY), patch.object(
            wo, "get_supabase", return_value=sb
        ), patch.object(wo, "get_brand", return_value={"ok": True}):
            wo.set_brand("w1", brand_voice="be bold")
        assert sb.clients_updated
        assert sb.clients_updated[0]["brand_voice"]["raw_text"] == "be bold"

    def test_get_brand_reports_the_strategist_flag(self):
        with patch.object(wo, "_load", return_value=self.PROPERTY), patch(
            "services.website_generate.has_brand_context", return_value=True
        ):
            assert wo.get_brand("w1")["strategist_enabled"] is False

    def test_set_strategist_toggles_a_property(self):
        sb = _FakeSupabase()
        with patch.object(wo, "_load", return_value=self.PROPERTY), patch.object(
            wo, "get_supabase", return_value=sb
        ), patch.object(wo, "get_brand", return_value={"ok": True}):
            wo.set_strategist("w1", enabled=True)
        assert sb.clients_updated[0]["strategist_enabled"] is True

    def test_set_strategist_refuses_a_real_client(self):
        with patch.object(wo, "_load", return_value=self.CLIENT):
            with pytest.raises(wo.OwnerError) as ei:
                wo.set_strategist("w1", enabled=False)
        assert ei.value.code == "not_a_property"
