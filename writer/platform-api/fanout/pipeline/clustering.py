"""Statistical clustering (PRD §7.9).

Per topic (never across topics): build a NetworkX similarity graph over the
surviving keywords — an edge wherever cosine similarity exceeds 0.55 — and run
Louvain community detection to extract candidate groupings. Each grouping gets a
representative keyword (single-pick MMR == the medoid, the keyword most central
to the grouping) and a cohesion score (mean pairwise cosine).

This produces *candidate groupings, not articles* — an intermediate signal that
feeds the editorial orchestrator in §7.10 (M5). It is persisted to the session's
`statistical_clustering_log` jsonb for debugging/re-runnability and is never
shown to the user directly.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from community import community_louvain

logger = logging.getLogger(__name__)

_EDGE_THRESHOLD = 0.55
_RANDOM_STATE = 42  # deterministic Louvain across re-runs


@dataclass
class Grouping:
    id: str
    keywords: list[str]
    representative: str
    cohesion: float
    size: int


@dataclass
class ClusterResult:
    # topic_id -> candidate groupings
    per_topic: dict[str, list[Grouping]] = field(default_factory=dict)
    edge_threshold: float = _EDGE_THRESHOLD

    def to_log(self) -> dict:
        """JSON-serializable form for sessions.statistical_clustering_log."""
        return {
            "edge_threshold": self.edge_threshold,
            "topics": {
                tid: {
                    "grouping_count": len(groupings),
                    "groupings": [
                        {
                            "id": g.id,
                            "representative": g.representative,
                            "cohesion": round(g.cohesion, 4),
                            "size": g.size,
                            "keywords": g.keywords,
                        }
                        for g in groupings
                    ],
                }
                for tid, groupings in self.per_topic.items()
            },
        }


def _normalized(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def cluster_topic(
    topic_id: str,
    keywords: list[str],
    embeddings: list[list[float]],
    *,
    edge_threshold: float = _EDGE_THRESHOLD,
    resolution: float = 1.0,
) -> list[Grouping]:
    """Louvain groupings for one topic's surviving keywords. `keywords[i]` is
    described by `embeddings[i]`. `edge_threshold` and `resolution` control
    granularity: a higher threshold keeps only very-similar edges and a higher
    resolution favors more, smaller communities — both yield finer (more) groupings."""
    n = len(keywords)
    if n == 0:
        return []
    if n == 1:
        return [Grouping(f"{topic_id}:g0", [keywords[0]], keywords[0], 1.0, 1)]

    # float32 halves the n x n similarity matrix's footprint (the dominant
    # allocation here); precision is ample for a 0.55 cosine threshold.
    vn = _normalized(np.asarray(embeddings, dtype=np.float32))
    sims = vn @ vn.T  # cosine similarity matrix (rows are unit vectors)

    graph = nx.Graph()
    graph.add_nodes_from(range(n))  # include isolated nodes so they cluster alone
    iu = np.triu_indices(n, k=1)
    pair_sims = sims[iu]
    mask = pair_sims > edge_threshold
    rows = iu[0][mask].tolist()
    cols = iu[1][mask].tolist()
    weights = pair_sims[mask].tolist()
    graph.add_weighted_edges_from(zip(rows, cols, weights))

    partition = community_louvain.best_partition(
        graph, weight="weight", resolution=resolution, random_state=_RANDOM_STATE
    )

    members: dict[int, list[int]] = defaultdict(list)
    for node, comm_id in partition.items():
        members[comm_id].append(node)

    groupings: list[Grouping] = []
    for gi, comm_id in enumerate(sorted(members)):
        idx = sorted(members[comm_id])
        sub = sims[np.ix_(idx, idx)]
        if len(idx) > 1:
            # mean pairwise cosine (exclude the diagonal)
            off_diag_sum = sub.sum() - np.trace(sub)
            cohesion = float(off_diag_sum / (len(idx) * (len(idx) - 1)))
            # representative = medoid: highest mean similarity to the rest.
            mean_to_others = (sub.sum(axis=1) - np.diag(sub)) / (len(idx) - 1)
            rep_local = int(np.argmax(mean_to_others))
        else:
            cohesion = 1.0
            rep_local = 0
        groupings.append(
            Grouping(
                id=f"{topic_id}:g{gi}",
                keywords=[keywords[i] for i in idx],
                representative=keywords[idx[rep_local]],
                cohesion=cohesion,
                size=len(idx),
            )
        )
    return groupings


def run_clustering(
    *,
    per_topic_keywords: dict[str, list[str]],
    per_topic_embeddings: dict[str, list[list[float]]],
    edge_threshold: float = _EDGE_THRESHOLD,
    resolution: float = 1.0,
) -> ClusterResult:
    """Cluster each topic independently. Inputs are the active keywords and their
    (gate-computed) embeddings, aligned per topic."""
    result = ClusterResult(edge_threshold=edge_threshold)
    for tid, keywords in per_topic_keywords.items():
        embeddings = per_topic_embeddings.get(tid, [])
        result.per_topic[tid] = cluster_topic(
            tid, keywords, embeddings, edge_threshold=edge_threshold, resolution=resolution
        )

    total_groupings = sum(len(g) for g in result.per_topic.values())
    logger.info(
        "step_complete",
        extra={"event": "step_complete", "step": "statistical_clustering",
               "topic_count": len(result.per_topic),
               "grouping_count": total_groupings,
               "edge_threshold": edge_threshold},
    )
    return result
