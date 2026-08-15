"""Resumable Fanout expansion (issue #686 Phase 2): the per-silo checkpoint.

The pure checkpoint helpers are validated directly; the orchestration
(`run_resumable_expansion`) is driven with the two impure compute units faked, so
these run without the DataForSEO/pipeline stack — they pin the checkpoint
mechanics: skip already-done silos, persist after every unit, resume from a
partial checkpoint, and honour cancellation between units.
"""

import pytest

from fanout.pipeline import resumable
from fanout.pipeline.resumable import (
    ExpandParams,
    ResumableTopic,
    assemble_pool,
    expansion_complete,
    merge_source_lists,
    pending_topic_ids,
    run_resumable_expansion,
)


def _params() -> ExpandParams:
    return ExpandParams(
        keyword_ideas_limit=1000, keyword_suggestions_limit=500, query_fanouts_limit=300,
        paa_tier1_seeds=8, paa_tier2_cap=40, autocomplete_max=1500,
        expansion_max_workers=8, expansion_time_budget_s=240.0,
        competitor_top_n=5, ranked_keywords_limit=500, competitor_max_position=20,
        competitor_max_workers=8, competitor_time_budget_s=240.0,
    )


# ---- pure helpers ----------------------------------------------------------

def test_merge_source_lists_unions_and_sorts():
    assert merge_source_lists({"a": ["x"]}, {"a": ["y"], "b": ["z"]}) == {"a": ["x", "y"], "b": ["z"]}
    assert merge_source_lists({}, {}) == {}
    assert merge_source_lists({"a": ["y", "x", "x"]}, {}) == {"a": ["x", "y"]}


def test_pending_topic_ids_skips_done_preserving_order():
    cp = {"topics": {"t1": {"a": ["x"]}}}
    assert pending_topic_ids(["t1", "t2", "t3"], cp) == ["t2", "t3"]
    assert pending_topic_ids(["t1"], {}) == ["t1"]


def test_assemble_pool_fans_seed_into_every_topic():
    cp = {"seed_pool": {"s": ["keyword_suggestions"]},
          "topics": {"t1": {"a": ["paa_t1"]}, "t2": {}}}
    asm = assemble_pool(["t1", "t2"], cp)
    assert asm["t1"] == {"a": ["paa_t1"], "s": ["keyword_suggestions"]}
    assert asm["t2"] == {"s": ["keyword_suggestions"]}


def test_expansion_complete():
    assert expansion_complete(["t1", "t2"], {"seed_done": True, "topics": {"t1": {}, "t2": {}}})
    assert not expansion_complete(["t1", "t2"], {"seed_done": True, "topics": {"t1": {}}})
    assert not expansion_complete(["t1"], {"seed_done": False, "topics": {"t1": {}}})


# ---- orchestration (compute units faked) -----------------------------------

def _fake_units(monkeypatch, seed_calls, topic_calls):
    def fake_seed(seed, dfs, params):
        seed_calls.append(seed)
        return {"seedkw": ["keyword_suggestions"]}, ["seed note"]

    def fake_topic(seed, topic, dfs, params, cap):
        topic_calls.append(topic.id)
        return {f"{topic.id}_kw": ["paa_t1"]}, []

    monkeypatch.setattr(resumable, "_compute_seed_pool", fake_seed)
    monkeypatch.setattr(resumable, "_compute_topic_pool", fake_topic)


def test_fresh_run_computes_seed_and_every_silo(monkeypatch):
    seed_calls, topic_calls, saves = [], [], []
    _fake_units(monkeypatch, seed_calls, topic_calls)
    checkpoint: dict = {}
    topics = [ResumableTopic("t1", "One", False), ResumableTopic("t2", "Two", True)]
    per_topic, notes = run_resumable_expansion(
        seed="acme", topics=topics, dfs=None, params=_params(),
        checkpoint=checkpoint, save=lambda cp: saves.append(dict(cp)),
    )
    assert seed_calls == ["acme"]
    assert topic_calls == ["t1", "t2"]
    # persisted after the seed unit and after each silo (3 saves)
    assert len(saves) == 3
    # every silo carries its own keyword + the fanned seed keyword
    assert per_topic["t1"] == {"t1_kw": ["paa_t1"], "seedkw": ["keyword_suggestions"]}
    assert per_topic["t2"] == {"t2_kw": ["paa_t1"], "seedkw": ["keyword_suggestions"]}
    assert "seed note" in notes
    assert checkpoint["seed_done"] is True
    assert set(checkpoint["topics"]) == {"t1", "t2"}


def test_resume_skips_finished_seed_and_silo(monkeypatch):
    """A requeue after a crash: the checkpoint already has the seed + t1, so only
    t2 is (re-)computed — the whole point of Phase 2."""
    seed_calls, topic_calls, saves = [], [], []
    _fake_units(monkeypatch, seed_calls, topic_calls)
    checkpoint = {
        "seed_done": True,
        "seed_pool": {"seedkw": ["keyword_suggestions"]},
        "topics": {"t1": {"t1_kw": ["paa_t1"]}},
        "degraded_notes": ["seed note"],
    }
    topics = [ResumableTopic("t1", "One", False), ResumableTopic("t2", "Two", True)]
    per_topic, _notes = run_resumable_expansion(
        seed="acme", topics=topics, dfs=None, params=_params(),
        checkpoint=checkpoint, save=lambda cp: saves.append(dict(cp)),
    )
    assert seed_calls == []          # seed not recomputed (no re-pay)
    assert topic_calls == ["t2"]     # only the unfinished silo
    assert len(saves) == 1           # one save (t2)
    assert per_topic["t1"] == {"t1_kw": ["paa_t1"], "seedkw": ["keyword_suggestions"]}
    assert per_topic["t2"] == {"t2_kw": ["paa_t1"], "seedkw": ["keyword_suggestions"]}


def test_cancellation_between_units_aborts(monkeypatch):
    seed_calls, topic_calls = [], []
    _fake_units(monkeypatch, seed_calls, topic_calls)

    class _Cancel(BaseException):
        pass

    def raise_after_seed():
        # allow the seed unit, abort before the first silo
        if seed_calls:
            raise _Cancel()

    checkpoint: dict = {}
    topics = [ResumableTopic("t1", "One", False)]
    with pytest.raises(_Cancel):
        run_resumable_expansion(
            seed="acme", topics=topics, dfs=None, params=_params(),
            checkpoint=checkpoint, save=lambda cp: None,
            raise_if_cancelled=raise_after_seed,
        )
    assert seed_calls == ["acme"]
    assert topic_calls == []  # aborted before expanding any silo
