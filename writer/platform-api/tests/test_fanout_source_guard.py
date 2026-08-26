"""Source-aware relevance guard (fanout §7.6 follow-up).

The embedding cosine gate alone let ~half the active pool drift off-topic on
broad multi-token seeds: the two noisiest sources (keyword_ideas category drift +
whole-domain competitor mining) dominate the pool, and gemini-embedding-2 can't
separate their drift from real signal (junk and on-topic keywords land in the
same narrow cosine band). The guard requires a keyword from a NON-trusted source
to prove topicality another way — a shared seed/alias token OR an elevated cosine
— while leaving trusted phrase/seed-match sources and single-token entity seeds
untouched.

These pin the pure helpers and the gate integration, including the four exemptions
(trusted source / topical token / high cosine / short seed) that keep the guard
from over-dropping legitimate token-disjoint long-tail.
"""

import math

import pytest

pytest.importorskip("numpy")

from fanout.pipeline.relevance import (  # noqa: E402
    _sig_tokens,
    _source_guard_demotes,
    _topical_vocabulary,
    run_relevance_gate,
)

_SEED = "third party claims administrator"
_SEED_TERMS = [_SEED, "TPA", "claims administrator", "independent adjuster"]
_ANCHOR = [1.0, 0.0]


def _fake_embed(scores: dict[str, float]):
    """embed_fn returning, for each keyword, a unit 2-vector whose cosine to the
    anchor [1,0] equals the desired score — so the gate scores each keyword exactly
    `scores[kw]`."""
    def embed(batch: list[str]) -> list[list[float]]:
        out = []
        for kw in batch:
            s = scores[kw]
            out.append([s, math.sqrt(max(0.0, 1.0 - s * s))])
        return out
    return embed


def _gate(pool_scores, *, seed=_SEED, seed_terms=None, enabled=True, min_score=0.80):
    """Run the gate over one topic with the given {keyword: (score, [sources])}."""
    per_topic = {"t1": {kw: srcs for kw, (_, srcs) in pool_scores.items()}}
    scores = {kw: sc for kw, (sc, _) in pool_scores.items()}
    res = run_relevance_gate(
        per_topic=per_topic,
        topic_embeddings={"t1": _ANCHOR},
        embed_fn=_fake_embed(scores),
        threshold=0.65,
        seed_terms=seed_terms if seed_terms is not None else _SEED_TERMS,
        seed=seed,
        source_guard_enabled=enabled,
        source_guard_min_score=min_score,
        source_guard_min_seed_tokens=2,
        language_filter=None,
    )
    return {g.keyword: g.status for g in res.per_topic["t1"]}


# ---- pure helpers ----------------------------------------------------------

def test_sig_tokens_stems_and_drops_stopwords():
    assert _sig_tokens("third party claims administrator") == {
        "third", "party", "claim", "administrator"
    }
    # stopwords ("and", "of") and 1-char tokens dropped
    assert _sig_tokens("board of directors and performance") == {
        "board", "director", "performance"
    }


def test_topical_vocabulary_unions_seed_and_aliases_not_silos():
    vocab = _topical_vocabulary(_SEED_TERMS)
    assert {"third", "party", "claim", "administrator", "tpa", "independent",
            "adjuster"} <= vocab
    # a generic silo word must NOT be in the vocabulary (that's what re-admits drift)
    assert "performance" not in vocab


def test_demote_predicate_exemptions():
    vocab = _topical_vocabulary(_SEED_TERMS)
    # broad-only, token-disjoint, low score -> demote
    assert _source_guard_demotes(["keyword_ideas"], "fund performance", 0.70, vocab, 0.80)
    # trusted source -> exempt
    assert not _source_guard_demotes(["keyword_suggestions"], "fund performance", 0.70, vocab, 0.80)
    # high cosine -> exempt (rescues legit token-disjoint long-tail)
    assert not _source_guard_demotes(["competitor"], "subrogated recoveries", 0.83, vocab, 0.80)
    # topical token ("claim") -> exempt
    assert not _source_guard_demotes(["competitor"], "claims handling process", 0.70, vocab, 0.80)


# ---- gate integration ------------------------------------------------------

def test_guard_demotes_broad_drift_but_keeps_signal():
    out = _gate({
        "corporate governance performance": (0.70, ["keyword_ideas"]),  # drift -> demote
        "board of directors performance": (0.71, ["competitor"]),       # drift -> demote
        "subrogated recoveries": (0.83, ["competitor"]),                # rescued by score
        "claims handling process": (0.70, ["competitor"]),              # topical token
        "insurance tpas": (0.70, ["keyword_ideas"]),                    # topical token (tpa)
    })
    assert out["corporate governance performance"] == "filtered_relevance"
    assert out["board of directors performance"] == "filtered_relevance"
    assert out["subrogated recoveries"] == "active"
    assert out["claims handling process"] == "active"
    assert out["insurance tpas"] == "active"


def test_trusted_source_is_never_guarded():
    # Same token-disjoint low-score keyword: demoted from a broad source, kept when
    # it also surfaced from a trusted phrase/seed-match source.
    broad = _gate({"fund performance": (0.70, ["keyword_ideas"])})
    trusted = _gate({"fund performance": (0.70, ["keyword_ideas", "query_fanouts"])})
    assert broad["fund performance"] == "filtered_relevance"
    assert trusted["fund performance"] == "active"


def test_single_token_seed_leaves_guard_inactive():
    # An entity seed like "retatrutide" (1 significant token) is left to the
    # embedding + peer gate — the source guard must not fire.
    out = _gate(
        {"triple agonist weight loss": (0.70, ["competitor"])},
        seed="retatrutide",
        seed_terms=["retatrutide"],
    )
    assert out["triple agonist weight loss"] == "active"


def test_disabled_guard_keeps_everything_active():
    out = _gate(
        {"fund performance": (0.70, ["keyword_ideas"])},
        enabled=False,
    )
    assert out["fund performance"] == "active"


def test_below_threshold_is_relevance_filtered_regardless_of_guard():
    # A keyword under the cosine threshold is filtered_relevance either way — the
    # guard only ever demotes keywords that otherwise cleared the gate.
    out = _gate({"unrelated thing": (0.40, ["keyword_ideas"])})
    assert out["unrelated thing"] == "filtered_relevance"
