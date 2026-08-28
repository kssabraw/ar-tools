"""What the resumable expansion path shares with the monolithic one — and where
it provably differs.

`fanout_resumable_expand_enabled` switches `_expand_core` (one
`run_refinement_pipeline` call) for `_expand_core_resumable`
(`run_resumable_expansion` per silo, then `gate_and_cluster`). The existing
`test_fanout_resumable.py` fakes the compute units and pins the CHECKPOINT
mechanics; it deliberately says nothing about whether the two paths agree on the
keywords they produce. That is the property the flag actually risks: the
resumable path calls `run_expansion` per silo with `include_seed_level=False`
and mines each silo separately, where the monolith batches all of it.

`resumable.py`'s docstring declares two deliberate divergences, one of them
"autocomplete coverage differs slightly". These pin what that actually means, by
faking only the DataForSEO client so the real `run_expansion` /
`run_competitor_mining` / anchor / normalise / merge logic runs on BOTH sides and
the pools handed to `gate_and_cluster` can be compared directly.

Measured result: every keyword from a substantive source (ideas, PAA,
suggestions, fanouts, competitor) is identical across the two paths. The only
difference is autocomplete REACH — the monolith autocompletes the merged pool
including the fanned seed-level keywords, so it derives extra terms from them;
the resumable path autocompletes each silo's own ideas+PAA and never the
seed-level terms. That is a difference in composition, not a strict loss: the
autocomplete call budget (`autocomplete_max`) is global and gets spent on silo
keywords instead. Locking it here means any future change to that trade-off is
caught rather than discovered on a client's bill.
"""

from __future__ import annotations

import pytest

from fanout.pipeline.expansion import ExpansionTopic, build_anchor, run_expansion
from fanout.pipeline.competitor import MineTopic, run_competitor_mining
from fanout.pipeline.orchestrate import _SEED_MINE_ID
from fanout.pipeline.resumable import merge_source_lists


SEED = "retatrutide"
TOPICS = [
    ("t1", "weight loss use"),
    ("t2", "retatrutide dosing"),
    ("t3", "side effects"),
]


class FakeDFS:
    """Deterministic stand-in. Every response is a pure function of its anchor,
    so the ONLY thing that can make the two paths differ is how they batch the
    calls — which is exactly what's under test. Also counts calls, so the
    resumable path's promise (never re-pay the seed-level endpoints per silo)
    is checked rather than assumed."""

    def __init__(self) -> None:
        self.calls: dict[str, list[str]] = {}

    def _log(self, name: str, arg: str) -> None:
        self.calls.setdefault(name, []).append(arg)

    def keyword_suggestions(self, anchor, limit=None):
        self._log("keyword_suggestions", anchor)
        return [f"{anchor} suggestion a", f"{anchor} suggestion b"]

    def query_fanouts(self, anchor, limit=None):
        self._log("query_fanouts", anchor)
        return [f"{anchor} fanout"]

    def keyword_ideas(self, anchor, limit=None):
        self._log("keyword_ideas", anchor)
        return [f"{anchor} idea"]

    def people_also_ask(self, anchor):
        self._log("people_also_ask", anchor)
        return [f"why {anchor}"]

    def autocomplete(self, anchor, limit=None):
        self._log("autocomplete", anchor)
        return [f"{anchor} autocomplete"]

    # --- competitor mining ------------------------------------------------
    def serp_top_urls(self, anchor, top_n=None):
        self._log("serp_top_urls", anchor)
        return [f"https://example-{abs(hash(anchor)) % 7}.com/a"]

    def domain_of(self, url):
        return url.split("//")[-1].split("/")[0]

    def ranked_keywords(self, domain, limit=None, max_position=None):
        self._log("ranked_keywords", domain)
        return [f"{domain} ranked kw"]


def _params():
    from fanout.pipeline.resumable import ExpandParams
    return ExpandParams(
        keyword_ideas_limit=50, keyword_suggestions_limit=50, query_fanouts_limit=50,
        paa_tier1_seeds=2, paa_tier2_cap=4, autocomplete_max=50,
        expansion_max_workers=2, expansion_time_budget_s=30.0,
        competitor_top_n=2, ranked_keywords_limit=50, competitor_max_position=20,
        competitor_max_workers=2, competitor_time_budget_s=30.0,
    )


def _sorted_pool(pool):
    """Normalise to {topic: {keyword: sorted(sources)}} for comparison."""
    return {tid: {kw: sorted(srcs) for kw, srcs in kws.items()}
            for tid, kws in pool.items()}


def _monolith_pools(monkeypatch, dfs, gated: set[str]):
    """What the REAL run_refinement_pipeline hands to the relevance gate.

    Intercepts `gate_and_cluster` rather than reimplementing steps 1-2, so this
    side of the comparison is the production code path, not a paraphrase of it.
    """
    from fanout.pipeline import orchestrate
    from fanout.pipeline.orchestrate import PipelineTopic, run_refinement_pipeline

    captured = {}

    class _GC:
        degraded_notes: list = []
        per_topic_gated: dict = {}
        clustering_log: dict = {}

    def _capture(**kwargs):
        captured["per_topic_lists"] = kwargs["per_topic_lists"]
        return _GC()

    monkeypatch.setattr(orchestrate, "gate_and_cluster", _capture)
    p = _params()
    run_refinement_pipeline(
        seed=SEED,
        topics=[PipelineTopic(id=tid, name=name, embedding=None, gated=(tid in gated))
                for tid, name in TOPICS],
        dfs=dfs,
        embed_fn=lambda *a, **k: [],
        seed_terms=[SEED], peer_terms=[],
        keyword_ideas_limit=p.keyword_ideas_limit,
        keyword_suggestions_limit=p.keyword_suggestions_limit,
        query_fanouts_limit=p.query_fanouts_limit,
        paa_tier1_seeds=p.paa_tier1_seeds, paa_tier2_cap=p.paa_tier2_cap,
        autocomplete_max=p.autocomplete_max,
        expansion_max_workers=p.expansion_max_workers,
        expansion_time_budget_s=p.expansion_time_budget_s,
        competitor_top_n=p.competitor_top_n,
        ranked_keywords_limit=p.ranked_keywords_limit,
        competitor_max_position=p.competitor_max_position,
        competitor_max_workers=p.competitor_max_workers,
        competitor_time_budget_s=p.competitor_time_budget_s,
    )
    return _sorted_pool(captured["per_topic_lists"])


def _resumable_pools(dfs, gated: set[str], checkpoint=None):
    """What the REAL run_resumable_expansion returns for the same inputs."""
    from fanout.pipeline.resumable import ResumableTopic, run_resumable_expansion

    per_topic_lists, _notes = run_resumable_expansion(
        seed=SEED,
        topics=[ResumableTopic(id=tid, name=name, gated=(tid in gated))
                for tid, name in TOPICS],
        dfs=dfs,
        params=_params(),
        checkpoint=checkpoint if checkpoint is not None else {},
        save=lambda cp: None,
    )
    return _sorted_pool(per_topic_lists)


AUTOCOMPLETE = "autocomplete"


def _without_autocomplete_only(pool):
    """Drop keywords whose ONLY source is autocomplete — what remains is every
    keyword a substantive endpoint produced."""
    return {
        tid: {kw: srcs for kw, srcs in kws.items() if srcs != [AUTOCOMPLETE]}
        for tid, kws in pool.items()
    }


@pytest.mark.parametrize("gated", [set(), {"t2"}, {"t1", "t3"}, {"t1", "t2", "t3"}])
def test_both_paths_agree_on_every_substantively_sourced_keyword(monkeypatch, gated):
    """The property that matters: switching paths must not change which keywords
    the PAID endpoints (ideas, PAA, suggestions, fanouts, competitor mining)
    contribute, for any deep-mine selection. Autocomplete-only derivations are
    compared separately below."""
    mono = _without_autocomplete_only(_monolith_pools(monkeypatch, FakeDFS(), gated))
    res = _without_autocomplete_only(_resumable_pools(FakeDFS(), gated))
    assert mono == res


@pytest.mark.parametrize("gated", [set(), {"t1", "t2", "t3"}])
def test_only_autocomplete_reach_differs_and_only_over_seed_level_terms(monkeypatch, gated):
    """Pins resumable.py's declared "autocomplete coverage differs slightly".

    Every keyword the monolith has and the resumable path lacks is an
    autocomplete derivation of a SEED-LEVEL term — because the monolith
    autocompletes the merged pool (which carries the fanned seed-level
    keywords) while the resumable path autocompletes each silo's own ideas+PAA.
    If that ever stops being the shape of the difference, this fails."""
    mono = _monolith_pools(monkeypatch, FakeDFS(), gated)
    res = _resumable_pools(FakeDFS(), gated)
    for tid, _ in TOPICS:
        missing = set(mono[tid]) - set(res[tid])
        assert missing, "the difference is expected to exist; see the module docstring"
        for kw in missing:
            assert mono[tid][kw] == [AUTOCOMPLETE], (tid, kw, mono[tid][kw])
            # ...derived from a seed-level term, i.e. built off the bare seed.
            assert kw.startswith(SEED), (tid, kw)
        # The resumable path never invents keywords the monolith lacks.
        assert not set(res[tid]) - set(mono[tid])


def test_resuming_from_a_partial_checkpoint_matches_an_uninterrupted_run():
    """The feature's core promise: a crash mid-expansion must not change the
    result. Run until a simulated crash, then finish from that checkpoint — the
    pool must equal what an uninterrupted resumable run produces."""
    from fanout.pipeline.resumable import ResumableTopic, run_resumable_expansion

    partial: dict = {}
    stop = {"n": 0}

    def _abort_after_two_units():
        stop["n"] += 1
        if stop["n"] > 2:
            raise RuntimeError("simulated crash mid-expansion")

    with pytest.raises(RuntimeError):
        run_resumable_expansion(
            seed=SEED,
            topics=[ResumableTopic(id=tid, name=name, gated=False) for tid, name in TOPICS],
            dfs=FakeDFS(), params=_params(), checkpoint=partial, save=lambda cp: None,
            raise_if_cancelled=_abort_after_two_units,
        )
    assert partial.get("seed_done") is True            # real partial progress banked
    assert 0 < len(partial.get("topics") or {}) < len(TOPICS)

    resumed = _resumable_pools(FakeDFS(), set(), checkpoint=partial)
    assert resumed == _resumable_pools(FakeDFS(), set())


def test_the_seed_level_endpoints_are_paid_for_once_not_per_silo():
    """The resumable path's whole cost argument: the seed's phrase endpoints are
    hit once no matter how many silos there are — otherwise resuming would cost
    MORE than the monolith it replaces."""
    dfs = FakeDFS()
    _resumable_pools(dfs, {"t1"})
    assert dfs.calls["keyword_suggestions"] == [SEED]
    assert dfs.calls["query_fanouts"] == [SEED]


def test_a_resumed_run_does_not_re_pay_for_finished_work():
    """The saving itself: units already in the checkpoint must issue no further
    DataForSEO calls."""
    from fanout.pipeline.resumable import ResumableTopic, run_resumable_expansion

    cp: dict = {}
    topics = [ResumableTopic(id=tid, name=name, gated=False) for tid, name in TOPICS]
    run_resumable_expansion(seed=SEED, topics=topics, dfs=FakeDFS(), params=_params(),
                            checkpoint=cp, save=lambda c: None)
    second = FakeDFS()
    run_resumable_expansion(seed=SEED, topics=topics, dfs=second, params=_params(),
                            checkpoint=cp, save=lambda c: None)
    assert second.calls == {}, "a fully-checkpointed run must re-pay nothing"
