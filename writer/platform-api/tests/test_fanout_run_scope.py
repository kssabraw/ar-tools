"""Per-silo run scope, independent of the deep-mine gate (fanout).

`is_gated_for_competitor_mining` only ever gated competitor mining, so a user who
ticked 3 of 5 silos on the "choose silos to deep-mine" screen still had all 5
expanded, clustered and planned — the screen read like it scoped the run.
`is_in_run_scope` carries the run scope separately.

These pin the pure selection logic (fanout/run_scope.py), the storage helpers,
and the one property that keeps every existing caller safe: an absent scope means
*every* silo, never none.
"""

from unittest.mock import patch

import pytest

from fanout.run_scope import SelectionError, resolve_selection

pytest.importorskip("supabase")

from fanout.storage import silo  # noqa: E402


_ALL = ["t1", "t2", "t3"]


# ---- selection logic -------------------------------------------------------

def test_omitted_run_scope_means_every_silo():
    """The VA wizard and any older client send no run_topic_ids. That must keep
    meaning "run everything" — the pre-existing behaviour — not "run nothing"."""
    sel = resolve_selection(all_topic_ids=_ALL, topic_ids=["t1"], run_topic_ids=None)
    assert sel.run_topic_ids == _ALL
    assert sel.gated_topic_ids == ["t1"]


def test_run_scope_narrows_the_run_without_touching_the_gate():
    sel = resolve_selection(
        all_topic_ids=_ALL, topic_ids=["t1"], run_topic_ids=["t1", "t2"]
    )
    assert sel.run_topic_ids == ["t1", "t2"]
    assert sel.gated_topic_ids == ["t1"]


def test_a_silo_can_run_without_being_mined():
    """The whole point of splitting the two selections: run 2 silos, mine 1."""
    sel = resolve_selection(
        all_topic_ids=_ALL, topic_ids=[], run_topic_ids=["t1", "t2"]
    )
    assert sel.run_topic_ids == ["t1", "t2"]
    assert sel.gated_topic_ids == []


def test_both_lists_are_deduped_in_order():
    sel = resolve_selection(
        all_topic_ids=_ALL,
        topic_ids=["t2", "t2", "t1"],
        run_topic_ids=["t2", "t1", "t2"],
    )
    assert sel.run_topic_ids == ["t2", "t1"]
    assert sel.gated_topic_ids == ["t2", "t1"]


def test_empty_run_scope_is_rejected():
    with pytest.raises(SelectionError):
        resolve_selection(all_topic_ids=_ALL, topic_ids=[], run_topic_ids=[])


def test_run_scope_must_belong_to_the_session():
    with pytest.raises(SelectionError) as exc:
        resolve_selection(
            all_topic_ids=_ALL, topic_ids=[], run_topic_ids=["t1", "other"]
        )
    assert "other" in exc.value.detail


def test_gated_topics_must_belong_to_the_session():
    with pytest.raises(SelectionError) as exc:
        resolve_selection(all_topic_ids=_ALL, topic_ids=["nope"], run_topic_ids=None)
    assert "nope" in exc.value.detail


def test_mining_a_silo_outside_the_run_is_rejected():
    """Mining spends SERP budget; doing it for a silo nothing downstream reads is
    always a mistake, so it fails loudly instead of being narrowed silently — a
    quiet drop looks exactly like the bug this control exists to fix."""
    with pytest.raises(SelectionError) as exc:
        resolve_selection(
            all_topic_ids=_ALL, topic_ids=["t3"], run_topic_ids=["t1", "t2"]
        )
    assert "deep-mined" in exc.value.detail


# ---- storage helpers -------------------------------------------------------

def test_in_run_scope_defaults_to_true_when_flag_absent():
    # Topics stored before the column existed must keep running.
    assert silo.in_run_scope({"id": "t1"}) is True
    assert silo.in_run_scope({"id": "t1", "is_in_run_scope": None}) is True


def test_in_run_scope_respects_an_explicit_exclusion():
    assert silo.in_run_scope({"id": "t1", "is_in_run_scope": False}) is False
    assert silo.in_run_scope({"id": "t1", "is_in_run_scope": True}) is True


def test_list_run_topics_drops_excluded_silos():
    rows = [
        {"id": "t1", "is_in_run_scope": True},
        {"id": "t2", "is_in_run_scope": False},
        {"id": "t3"},  # legacy row -> in scope
    ]
    with patch.object(silo, "list_topics", return_value=rows):
        assert [t["id"] for t in silo.list_run_topics("s1")] == ["t1", "t3"]


class _RecordingClient:
    """Records the update payloads set_run_scope issues, in order."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def table(self, _name):
        return self

    def update(self, payload):
        self.calls.append({"payload": payload, "in_": None})
        return self

    def eq(self, *_args):
        return self

    def in_(self, _col, values):
        self.calls[-1]["in_"] = values
        return self

    def execute(self):
        return None


def test_set_run_scope_with_an_empty_list_restores_every_silo():
    """An empty scope must never mean "run nothing" — a caller that doesn't use
    the control would otherwise silently empty its own run."""
    client = _RecordingClient()
    with patch.object(silo, "get_service_client", return_value=client):
        silo.set_run_scope("s1", [])
    assert client.calls == [{"payload": {"is_in_run_scope": True}, "in_": None}]


def test_set_run_scope_clears_then_sets_the_selection():
    client = _RecordingClient()
    with patch.object(silo, "get_service_client", return_value=client):
        silo.set_run_scope("s1", ["t1", "t3"])
    assert client.calls[0]["payload"] == {"is_in_run_scope": False}
    assert client.calls[0]["in_"] is None  # clears the whole session first
    assert client.calls[1]["payload"] == {"is_in_run_scope": True}
    assert client.calls[1]["in_"] == ["t1", "t3"]
