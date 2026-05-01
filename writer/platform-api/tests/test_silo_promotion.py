"""Tests for services.silo_promotion (Platform PRD v1.4 §7.7.3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_supabase_mock(*, candidate=None, client=None):
    """Build a mock supabase client whose .table().select()...execute()
    chains return the candidate / client / runs row depending on context.
    Track all .insert() and .update() payloads on the mock for assertions.
    """
    insert_calls: list[tuple[str, dict]] = []
    update_calls: list[tuple[str, dict]] = []
    insert_returns: dict[str, list[dict]] = {
        "runs": [{"id": "new-run-id"}],
        "client_context_snapshots": [{}],
    }

    class TableMock:
        def __init__(self, name: str):
            self.name = name
            self._select_args = None
            self._eq_kvs: list[tuple[str, str]] = []
            self._is_select = False
            self._is_insert = False
            self._is_update = False
            self._payload: dict | None = None

        def select(self, *args, **kwargs):
            self._is_select = True
            return self

        def insert(self, payload):
            self._is_insert = True
            self._payload = payload
            insert_calls.append((self.name, payload))
            return self

        def update(self, payload):
            self._is_update = True
            self._payload = payload
            update_calls.append((self.name, payload))
            return self

        def eq(self, k, v):
            self._eq_kvs.append((k, v))
            return self

        def in_(self, k, v):
            return self

        def single(self):
            return self

        def execute(self):
            if self._is_insert:
                return MagicMock(
                    data=insert_returns.get(self.name, [{"id": "x"}])
                )
            if self._is_update:
                return MagicMock(data=[{}])
            # SELECT
            if self.name == "silo_candidates" and candidate is not None:
                return MagicMock(data=candidate)
            if self.name == "clients" and client is not None:
                return MagicMock(data=client)
            if self.name == "runs":
                return MagicMock(count=0, data=[])
            return MagicMock(data=None)

    sb = MagicMock()
    sb.table.side_effect = lambda name: TableMock(name)
    return sb, insert_calls, update_calls


# ----------------------------------------------------------------------
# promote_candidate happy path
# ----------------------------------------------------------------------

def test_promote_creates_run_and_updates_candidate():
    from services import silo_promotion
    from services.file_parser import detect_format

    candidate = {
        "id": "cand-1",
        "client_id": "client-1",
        "suggested_keyword": "How TikTok Shop charges fees",
        "estimated_intent": "informational",
        "status": "approved",
    }
    client = {
        "id": "client-1",
        "archived": False,
        "brand_guide_text": "brand text",
        "icp_text": "icp text",
        "website_analysis": {"services": []},
        "website_analysis_status": "complete",
    }
    sb, inserts, updates = _make_supabase_mock(candidate=candidate, client=client)

    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with patch.object(silo_promotion, "in_flight_run_count", return_value=0):
            result = silo_promotion.promote_candidate(
                candidate_id="cand-1",
                user_id="user-1",
            )

    assert result["run_id"] == "new-run-id"
    assert result["status"] == "in_progress"

    # runs row inserted with the candidate's keyword + intent
    runs_inserts = [p for name, p in inserts if name == "runs"]
    assert len(runs_inserts) == 1
    assert runs_inserts[0]["keyword"] == "How TikTok Shop charges fees"
    assert runs_inserts[0]["intent_override"] == "informational"
    assert runs_inserts[0]["client_id"] == "client-1"
    assert runs_inserts[0]["status"] == "queued"

    # client_context_snapshot created
    snapshot_inserts = [p for name, p in inserts if name == "client_context_snapshots"]
    assert len(snapshot_inserts) == 1
    assert snapshot_inserts[0]["run_id"] == "new-run-id"

    # candidate updated to in_progress
    silo_updates = [p for name, p in updates if name == "silo_candidates"]
    assert len(silo_updates) == 1
    assert silo_updates[0]["status"] == "in_progress"
    assert silo_updates[0]["promoted_to_run_id"] == "new-run-id"
    assert silo_updates[0]["last_promotion_failed_at"] is None


# ----------------------------------------------------------------------
# Validation failures
# ----------------------------------------------------------------------

def test_promote_rejects_when_candidate_not_found():
    from services import silo_promotion

    sb, _, _ = _make_supabase_mock(candidate=None)
    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with pytest.raises(silo_promotion.PromotionError) as ei:
            silo_promotion.promote_candidate(
                candidate_id="missing", user_id="user-1",
            )
    assert ei.value.code == "candidate_not_found"


def test_promote_rejects_invalid_status():
    from services import silo_promotion
    candidate = {
        "id": "c", "client_id": "x", "suggested_keyword": "k",
        "estimated_intent": "informational", "status": "in_progress",
    }
    sb, _, _ = _make_supabase_mock(candidate=candidate)
    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with pytest.raises(silo_promotion.PromotionError) as ei:
            silo_promotion.promote_candidate(candidate_id="c", user_id="u")
    assert ei.value.code == "invalid_status"


def test_promote_rejects_archived_client():
    from services import silo_promotion
    candidate = {
        "id": "c", "client_id": "client-x", "suggested_keyword": "k",
        "estimated_intent": "informational", "status": "approved",
    }
    client = {"id": "client-x", "archived": True}
    sb, _, _ = _make_supabase_mock(candidate=candidate, client=client)
    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with pytest.raises(silo_promotion.PromotionError) as ei:
            silo_promotion.promote_candidate(candidate_id="c", user_id="u")
    assert ei.value.code == "client_archived"


def test_promote_rejects_at_concurrency_cap():
    from services import silo_promotion
    candidate = {
        "id": "c", "client_id": "client-x", "suggested_keyword": "k",
        "estimated_intent": "informational", "status": "approved",
    }
    client = {"id": "client-x", "archived": False, "brand_guide_text": "",
              "icp_text": "", "website_analysis": None,
              "website_analysis_status": "pending"}
    sb, _, _ = _make_supabase_mock(candidate=candidate, client=client)

    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with patch.object(silo_promotion, "in_flight_run_count", return_value=5):
            with pytest.raises(silo_promotion.PromotionError) as ei:
                silo_promotion.promote_candidate(
                    candidate_id="c", user_id="u",
                    enforce_concurrency_cap=True, max_concurrent=5,
                )
    assert ei.value.code == "concurrency_limit"


def test_promote_bypasses_concurrency_cap_when_disabled():
    """Bulk promote disables the cap to allow many `queued` runs."""
    from services import silo_promotion
    candidate = {
        "id": "c", "client_id": "client-x", "suggested_keyword": "k",
        "estimated_intent": "informational", "status": "approved",
    }
    client = {"id": "client-x", "archived": False, "brand_guide_text": "",
              "icp_text": "", "website_analysis": None,
              "website_analysis_status": "pending"}
    sb, inserts, _ = _make_supabase_mock(candidate=candidate, client=client)

    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with patch.object(silo_promotion, "in_flight_run_count", return_value=99):
            result = silo_promotion.promote_candidate(
                candidate_id="c", user_id="u",
                enforce_concurrency_cap=False,
            )

    assert result["run_id"] == "new-run-id"
    runs_inserts = [p for name, p in inserts if name == "runs"]
    # New run inserted in queued state — dispatcher will hold it
    assert runs_inserts[0]["status"] == "queued"


# ----------------------------------------------------------------------
# Re-promotion of `published` candidates
# ----------------------------------------------------------------------

def test_promote_allows_published_candidate_to_be_re_promoted():
    from services import silo_promotion
    candidate = {
        "id": "c", "client_id": "client-x", "suggested_keyword": "k",
        "estimated_intent": "informational", "status": "published",
    }
    client = {"id": "client-x", "archived": False, "brand_guide_text": "",
              "icp_text": "", "website_analysis": None,
              "website_analysis_status": "pending"}
    sb, _, updates = _make_supabase_mock(candidate=candidate, client=client)

    with patch.object(silo_promotion, "get_supabase", return_value=sb):
        with patch.object(silo_promotion, "in_flight_run_count", return_value=0):
            result = silo_promotion.promote_candidate(
                candidate_id="c", user_id="u",
            )

    assert result["status"] == "in_progress"
    silo_updates = [p for name, p in updates if name == "silo_candidates"]
    assert silo_updates[0]["status"] == "in_progress"
