"""Step 5 — Embedding + Coverage Graph Construction (Brief Generator v2.0).

Implements PRD §5 Step 5 (5.1 through 5.5):

5.1  Embed seed, title, scope_statement, and every candidate using
     text-embedding-3-large with unit normalization (cosine == dot).
5.2  Pre-filter candidates by cosine to title:
       below relevance_floor   → discard `below_relevance_floor`
       above restatement_ceiling → discard `above_restatement_ceiling`
5.3  Build an undirected coverage graph: edges between candidates whose
     pairwise cosine exceeds edge_threshold (default 0.65).
5.4  Detect regions via Louvain community detection (resolution + seed
     are deterministic, configurable via env).
5.5  Score each region (density, source_diversity, centroid_title_distance,
     information_gain_signal) and eliminate regions whose centroid is
     off-topic or restates the title.

Every gate decision is logged as a structured event (PRD §12.6) with
the heading text and the score that triggered the rejection so operators
can tune thresholds from production logs.

This module is the architectural primitive that anchors the v2.0 fix
for paraphrase-H2 and topical-clone outlines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional

import networkx as nx
from networkx.algorithms.community import louvain_communities

from models.brief import DiscardReason, HeadingSource, ScopeClassification

from .llm import embed_batch_large

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Internal v2.0 candidate type
# ----------------------------------------------------------------------
# This is a working dataclass for in-pipeline state — distinct from the
# Pydantic HeadingItem on the API boundary. Pipeline code mutates these
# in place; assembly converts the survivors into HeadingItem instances.

@dataclass
class Candidate:
    """In-flight heading candidate (Brief v2.0)."""

    text: str
    source: HeadingSource

    # Step 4 aggregation signals
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    source_urls: list[str] = field(default_factory=list)
    llm_fanout_consensus: int = 0

    # Optional pre-sanitization text (some sources track it; v2.0 doesn't
    # surface it on the wire but we keep the field for parity with v1.8
    # parsers we're reusing).
    raw_text: Optional[str] = None

    # Set by `embed_with_gates`
    embedding: list[float] = field(default_factory=list)
    title_relevance: float = 0.0

    # Set by `assign_region_ids`
    region_id: Optional[str] = None

    # Set by Step 7 priority scoring
    information_gain_score: float = 0.0
    heading_priority: float = 0.0

    # Set by Step 7.6 LLM scoring (PRD v2.4) — 0-3 integer scores from a
    # batched LLM call against top-K candidates by vector priority. The
    # combined `llm_quality_score` (0-1) is folded into `heading_priority`
    # via a 70/30 vector/LLM blend before MMR runs. Defaults stay at 0
    # for candidates outside the top-K window or when LLM scoring is
    # disabled (brief_llm_scoring_weight = 0.0).
    llm_topical_relevance: int = 0
    llm_engagement_value: int = 0
    llm_information_depth: int = 0
    llm_quality_score: float = 0.0

    # Set by Step 8.5 scope verification (only on selected H2s)
    scope_classification: Optional[ScopeClassification] = None

    # Set by Step 8.6 H3 selection (only on candidates that get attached
    # as non-authority H3s; remain at defaults for H2s and authority H3s).
    parent_h2_text: Optional[str] = None
    parent_relevance: float = 0.0

    # Set by Step 9 Authority Agent (only on source='authority_gap_sme'
    # candidates; PRD v2.0.3): the agent's own justification for why the
    # H3 stays within the brief's scope_statement.
    scope_alignment_note: Optional[str] = None

    # Set by Step 9 Authority Agent — the level the agent intended for
    # this gap. Most authority gaps are sub-topic H3s under an existing
    # H2, but some are substantive enough to deserve their own H2. When
    # set to "H2", pipeline.py routes the candidate through scope
    # verification + framing validation and inserts it into selected_h2s
    # (capped per intent template). Default None for non-authority-gap
    # candidates.
    authority_gap_level: Optional[Literal["H2", "H3"]] = None

    # Set by Step 8.7 H3 Parent-Fit Verification (PRD v2.2 / Phase 2).
    # Only populated when the LLM tagged the H3 as `marginal` — `good`
    # leaves it None for terseness, `wrong_parent` and `promote_to_h2`
    # exit through routed_to_silos with their discard_reason set.
    parent_fit_classification: Optional[str] = None

    # Set when discarded
    discard_reason: Optional[DiscardReason] = None

    # Set when promoted from candidate to selected H2 (assembly phase)
    exempt: bool = False
    original_source: Optional[str] = None


# ----------------------------------------------------------------------
# Region information
# ----------------------------------------------------------------------

# Sources that count as "SERP" for the information-gain calculation. All
# other sources (Reddit, PAA, autocomplete, LLM fan-out / response,
# persona gap) count as "non-SERP" because they surface reader-side
# demand that competitors aren't addressing.
_SERP_SOURCES: frozenset[str] = frozenset({"serp"})


@dataclass
class RegionInfo:
    """Scored region from PRD §5.5.

    Centroid is the unit-normalized mean of member embeddings.
    `centroid_title_distance` is poorly named in the PRD — it's actually
    a *similarity* (cosine), not a distance. We preserve the PRD name to
    keep grep paths consistent, but the value is in [-1, 1] where higher
    = more similar to title.
    """

    region_id: str
    member_indices: list[int]
    centroid: list[float]

    density: int
    source_diversity: int
    centroid_title_distance: float  # cosine similarity to title
    information_gain_signal: float

    eliminated: bool = False
    elimination_reason: Optional[str] = None  # "off_topic" | "restates_title"
    is_singleton: bool = False


# ----------------------------------------------------------------------
# embed_with_gates — Step 5.1 + 5.2
# ----------------------------------------------------------------------

@dataclass
class GateResult:
    """Output of `embed_with_gates`.

    `eligible` carries embedding + title_relevance populated. `discarded`
    carries the same fields plus `discard_reason` set to one of
    `below_relevance_floor` / `above_restatement_ceiling`.
    """

    seed_embedding: list[float]
    title_embedding: list[float]
    scope_embedding: list[float]
    eligible: list[Candidate]
    discarded: list[Candidate]


# Type alias for the embed function so tests can inject deterministic vectors.
EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]


async def embed_with_gates(
    *,
    seed: str,
    title: str,
    scope_statement: str,
    candidates: list[Candidate],
    relevance_floor: float,
    restatement_ceiling: float,
    embed_fn: Optional[EmbedFn] = None,
) -> GateResult:
    """Embed inputs + candidates and apply the title-relevance gates.

    PRD §5.1: one batch covers seed + title + scope + every candidate.
    All embeddings are unit-normalized so downstream cosine reduces to
    dot product. PRD §5.2 then partitions candidates by their cosine to
    the title vector.

    Mutates each candidate in place: writes `embedding`, `title_relevance`,
    and (for discards) `discard_reason`.

    Empty candidates → returns embeddings for seed/title/scope only.
    """
    if relevance_floor >= restatement_ceiling:
        raise ValueError(
            f"relevance_floor ({relevance_floor}) must be < "
            f"restatement_ceiling ({restatement_ceiling})"
        )

    embed = embed_fn or embed_batch_large

    fixed_texts = [seed, title, scope_statement]
    candidate_texts = [c.text for c in candidates]
    all_vectors = await embed(fixed_texts + candidate_texts)
    if len(all_vectors) != len(fixed_texts) + len(candidate_texts):
        raise RuntimeError(
            "embed_fn returned wrong number of vectors: "
            f"got {len(all_vectors)}, expected "
            f"{len(fixed_texts) + len(candidate_texts)}"
        )

    seed_vec, title_vec, scope_vec = all_vectors[:3]
    candidate_vectors = all_vectors[3:]

    eligible: list[Candidate] = []
    discarded: list[Candidate] = []

    for cand, vec in zip(candidates, candidate_vectors):
        cand.embedding = vec
        # Embeddings are unit-normalized → cosine == dot product.
        relevance = sum(a * b for a, b in zip(vec, title_vec))
        cand.title_relevance = relevance

        if relevance < relevance_floor:
            cand.discard_reason = "below_relevance_floor"
            discarded.append(cand)
            logger.info(
                "brief.gate.relevance_floor.discard",
                extra={
                    "heading": cand.text,
                    "score": round(relevance, 4),
                    "threshold": relevance_floor,
                    "source": cand.source,
                },
            )
            continue

        if relevance > restatement_ceiling:
            cand.discard_reason = "above_restatement_ceiling"
            discarded.append(cand)
            # Restatement ceiling is the most consequential threshold per
            # PRD §12.6 — log at INFO so it's visible in default Railway
            # views during tuning.
            logger.info(
                "brief.gate.restatement_ceiling.discard",
                extra={
                    "heading": cand.text,
                    "score": round(relevance, 4),
                    "threshold": restatement_ceiling,
                    "source": cand.source,
                },
            )
            continue

        eligible.append(cand)
        logger.debug(
            "brief.gate.relevance.pass",
            extra={
                "heading": cand.text,
                "score": round(relevance, 4),
                "source": cand.source,
            },
        )

    logger.info(
        "brief.gate.summary",
        extra={
            "input_count": len(candidates),
            "eligible_count": len(eligible),
            "below_floor_count": sum(
                1 for c in discarded if c.discard_reason == "below_relevance_floor"
            ),
            "above_ceiling_count": sum(
                1 for c in discarded if c.discard_reason == "above_restatement_ceiling"
            ),
            "relevance_floor": relevance_floor,
            "restatement_ceiling": restatement_ceiling,
        },
    )

    return GateResult(
        seed_embedding=seed_vec,
        title_embedding=title_vec,
        scope_embedding=scope_vec,
        eligible=eligible,
        discarded=discarded,
    )


# ----------------------------------------------------------------------
# build_coverage_graph — Step 5.3
# ----------------------------------------------------------------------

def build_coverage_graph(
    candidates: list[Candidate],
    edge_threshold: float,
) -> nx.Graph:
    """Construct an undirected graph: edge (i, j) iff cosine(i, j) > edge_threshold.

    Node IDs are the candidate's index in the input list, so callers can
    map back to the original Candidate objects. Edge weights store the
    cosine value for downstream debugging / tuning visualizations.

    Embeddings are assumed unit-normalized (cosine == dot product). If a
    candidate has no embedding it gets a node with no edges — Louvain
    will isolate it.
    """
    n = len(candidates)
    G = nx.Graph()
    G.add_nodes_from(range(n))
    if n < 2:
        return G

    edge_count = 0
    for i in range(n):
        emb_i = candidates[i].embedding
        if not emb_i:
            continue
        for j in range(i + 1, n):
            emb_j = candidates[j].embedding
            if not emb_j:
                continue
            sim = sum(a * b for a, b in zip(emb_i, emb_j))
            if sim > edge_threshold:
                G.add_edge(i, j, weight=float(sim))
                edge_count += 1

    logger.info(
        "brief.graph.built",
        extra={
            "node_count": n,
            "edge_count": edge_count,
            "edge_threshold": edge_threshold,
        },
    )
    return G


# ----------------------------------------------------------------------
# detect_regions — Step 5.4
# ----------------------------------------------------------------------

def detect_regions(
    G: nx.Graph,
    resolution: float = 1.0,
    seed: int = 42,
) -> list[set[int]]:
    """Louvain community detection (PRD §5.4).

    Returns a list of disjoint node-index sets, one per region. The
    seed makes the partition reproducible across runs with identical
    graphs. Isolated nodes (degree 0) form singleton communities.

    Empty graph → empty list.
    """
    if G.number_of_nodes() == 0:
        return []
    communities = louvain_communities(G, resolution=resolution, seed=seed)
    # `louvain_communities` returns list[set[Any]]; node IDs are ints in
    # our construction, so the cast is safe.
    regions: list[set[int]] = [set(c) for c in communities]  # type: ignore[arg-type]
    logger.info(
        "brief.regions.detected",
        extra={
            "region_count": len(regions),
            "louvain_resolution": resolution,
            "louvain_seed": seed,
        },
    )
    return regions


# ----------------------------------------------------------------------
# score_regions — Step 5.5 (scoring + elimination)
# ----------------------------------------------------------------------

def _centroid(indices: list[int], candidates: list[Candidate]) -> list[float]:
    """Mean of member embeddings, unit-normalized so cosine == dot."""
    if not indices:
        return []
    vec_len = len(candidates[indices[0]].embedding)
    if vec_len == 0:
        return []
    sums = [0.0] * vec_len
    counted = 0
    for idx in indices:
        emb = candidates[idx].embedding
        if not emb or len(emb) != vec_len:
            continue
        for k in range(vec_len):
            sums[k] += emb[k]
        counted += 1
    if counted == 0:
        return []
    mean = [x / counted for x in sums]
    norm = sum(x * x for x in mean) ** 0.5
    if norm == 0.0:
        return mean
    return [x / norm for x in mean]


def _info_gain_signal(indices: list[int], candidates: list[Candidate]) -> float:
    """Fraction of region members whose source is non-SERP (PRD §5.5)."""
    if not indices:
        return 0.0
    non_serp = sum(
        1 for i in indices if candidates[i].source not in _SERP_SOURCES
    )
    return non_serp / len(indices)


def score_regions(
    regions: list[set[int]],
    candidates: list[Candidate],
    title_embedding: list[float],
    relevance_floor: float,
    restatement_ceiling: float,
) -> list[RegionInfo]:
    """Score every region and apply elimination rules (PRD §5.5).

    Eliminated regions stay in the returned list (with `eliminated=True`
    and `elimination_reason` set) so the caller can route members into
    `discarded_headings` with the correct reason. Singletons are flagged
    but not eliminated — they remain selectable in MMR but cannot become
    silos (PRD §5.5 elimination rules).

    Region IDs are assigned in stable density-desc order with a min-index
    tiebreak so two runs over the same input produce identical IDs.
    """
    # Sort: bigger regions first, ties broken by smallest member index
    # (deterministic regardless of set ordering).
    indexed = []
    for r in regions:
        members = sorted(r)
        indexed.append((-len(members), members[0] if members else 0, members))
    indexed.sort()

    out: list[RegionInfo] = []
    for rank, (_, _, members) in enumerate(indexed):
        if not members:
            continue
        centroid = _centroid(members, candidates)
        title_sim = (
            sum(a * b for a, b in zip(centroid, title_embedding))
            if centroid and title_embedding
            else 0.0
        )
        sources = {candidates[i].source for i in members}
        info = RegionInfo(
            region_id=f"region_{rank}",
            member_indices=members,
            centroid=centroid,
            density=len(members),
            source_diversity=len(sources),
            centroid_title_distance=title_sim,
            information_gain_signal=_info_gain_signal(members, candidates),
        )

        if info.density < 2:
            info.is_singleton = True

        if title_sim < relevance_floor:
            info.eliminated = True
            info.elimination_reason = "off_topic"
            logger.info(
                "brief.region.eliminated",
                extra={
                    "region_id": info.region_id,
                    "density": info.density,
                    "centroid_title_similarity": round(title_sim, 4),
                    "threshold": relevance_floor,
                    "reason": "off_topic",
                },
            )
        elif title_sim > restatement_ceiling:
            info.eliminated = True
            info.elimination_reason = "restates_title"
            logger.info(
                "brief.region.eliminated",
                extra={
                    "region_id": info.region_id,
                    "density": info.density,
                    "centroid_title_similarity": round(title_sim, 4),
                    "threshold": restatement_ceiling,
                    "reason": "restates_title",
                },
            )
        else:
            logger.debug(
                "brief.region.kept",
                extra={
                    "region_id": info.region_id,
                    "density": info.density,
                    "source_diversity": info.source_diversity,
                    "centroid_title_similarity": round(title_sim, 4),
                    "information_gain_signal": round(info.information_gain_signal, 4),
                    "is_singleton": info.is_singleton,
                },
            )
        out.append(info)

    return out


# ----------------------------------------------------------------------
# apply_region_outcomes — propagate region elimination to candidates
# ----------------------------------------------------------------------

def apply_region_outcomes(
    regions: list[RegionInfo],
    candidates: list[Candidate],
) -> tuple[list[Candidate], list[Candidate]]:
    """Stamp `region_id` on every candidate and route eliminated-region
    members into discards.

    Returns (kept, eliminated) where:
    - `kept` is candidates from non-eliminated regions (their region_id
      is set; they remain eligible for Step 7 / 8 / 8.5).
    - `eliminated` is candidates whose region was off_topic or restates_
      title (their `discard_reason` is set, `region_id` still recorded).

    This does NOT touch candidates already discarded by the relevance/
    restatement gates in Step 5.2 — those were never put into a region.
    """
    kept: list[Candidate] = []
    eliminated: list[Candidate] = []

    for region in regions:
        for idx in region.member_indices:
            cand = candidates[idx]
            cand.region_id = region.region_id
            if region.eliminated:
                if region.elimination_reason == "off_topic":
                    cand.discard_reason = "region_off_topic"
                elif region.elimination_reason == "restates_title":
                    cand.discard_reason = "region_restates_title"
                eliminated.append(cand)
            else:
                kept.append(cand)

    return kept, eliminated
