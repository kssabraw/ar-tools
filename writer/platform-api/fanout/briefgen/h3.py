"""Brief Generator Step 8.6 — regular H3 selection (M13 slice 5c-iii).

For each MCS-selected H2, choose 0-2 H3s from the subtopic candidate pool that elaborate
the H2 without restating it: parent-relevance band [0.65, 0.85] (cosine to the H2,
3-large), SAME coverage-graph region as the H2 (Louvain), MMR with a 0.78 inter-H3
anti-redundancy constraint, ≤2/H2, honest shortfall. Authority-gap H3s (Step 9) merge in
afterward and may displace a lower-priority regular H3 (the per-H2 cap may reach 3 when an
authority H3 overflows).

Pure: `parent_relevance_filter`, `mmr_select`, `merge_h3s`. Egress: region assignment
(networkx + Louvain) + the embedding batch in `select_h3s`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entity import cosine

H3_PARENT_LO = 0.65       # below -> unrelated to the H2
H3_PARENT_HI = 0.85       # above -> restates the H2
H3_REDUNDANCY = 0.78      # inter-H3 anti-redundancy (pairwise)
H3_PER_H2 = 2
REGION_EDGE_THRESHOLD = 0.55   # coverage-graph edge floor for Louvain


@dataclass
class H3Candidate:
    text: str
    source: str = "coverage_graph"


# ----- pure -----------------------------------------------------------------


def parent_relevance_filter(
    cand_rel: list[tuple[str, float]], *, lo: float = H3_PARENT_LO, hi: float = H3_PARENT_HI,
) -> list[tuple[str, float]]:
    """Keep (text, parent_relevance) pairs inside the band [lo, hi], sorted by relevance
    desc (the band: related to the H2 but not a restatement of it)."""
    kept = [(t, r) for t, r in cand_rel if lo <= r <= hi]
    return sorted(kept, key=lambda x: x[1], reverse=True)


def mmr_select(
    ranked: list[tuple[str, float]], vec_by_text: dict[str, list[float]], *,
    k: int = H3_PER_H2, redundancy: float = H3_REDUNDANCY,
) -> list[str]:
    """Pick up to `k` by relevance, hard-dropping any candidate whose cosine to an
    already-selected H3 exceeds `redundancy` (Step 8.6 MMR anti-restatement)."""
    selected: list[str] = []
    for text, _rel in ranked:                       # already relevance-sorted desc
        if len(selected) >= k:
            break
        red = max((cosine(vec_by_text[text], vec_by_text[s]) for s in selected), default=0.0)
        if red > redundancy:
            continue
        selected.append(text)
    return selected


def merge_h3s(
    regular_by_h2: dict[str, list[dict]], authority_by_h2: dict[str, list[dict]], *,
    cap: int = H3_PER_H2,
) -> dict[str, list[dict]]:
    """Combine regular + authority H3s per H2. Authority H3s have priority and are never
    dropped; if they overflow the cap, a regular H3 is displaced (cap may reach cap+1 when
    authority H3s caused the overflow, per Step 8.6)."""
    out: dict[str, list[dict]] = {}
    for h2 in set(regular_by_h2) | set(authority_by_h2):
        authority = authority_by_h2.get(h2, [])[: cap + 1]
        room = max(0, cap - len(authority))
        regular = regular_by_h2.get(h2, [])[:room]
        out[h2] = [*regular, *authority]
    return out


# ----- egress orchestration -------------------------------------------------


def _assign_regions(texts: list[str], vecs: list[list[float]], *, threshold: float) -> dict[str, int]:
    """Coverage-graph Louvain regions over the candidate+H2 set (the same networkx +
    python-louvain the keyword pipeline uses). Lazy-imported; on any failure every node
    falls into one region (the band + MMR still apply)."""
    try:
        import community as community_louvain
        import networkx as nx
    except Exception:  # noqa: BLE001 — libs absent -> single region
        return {t: 0 for t in texts}
    g = nx.Graph()
    g.add_nodes_from(range(len(texts)))
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            w = cosine(vecs[i], vecs[j])
            if w >= threshold:
                g.add_edge(i, j, weight=w)
    parts = community_louvain.best_partition(g, random_state=42) if g.number_of_edges() else {}
    return {texts[i]: parts.get(i, i) for i in range(len(texts))}


def select_h3s(
    *, h2_texts: list[str], candidates: list[H3Candidate], scope_statement: str, embed_3large,
    lo: float = H3_PARENT_LO, hi: float = H3_PARENT_HI, cap: int = H3_PER_H2,
) -> dict[str, list[dict]]:
    """Returns {h2_text: [h3 dict{text, source, parent_h2_text, parent_relevance, region_id}]}.
    Embeds the H2s + candidates once (3-large), partitions into regions, then per H2 keeps
    same-region candidates in the parent-relevance band and MMR-selects ≤cap."""
    cand_texts = [c.text for c in candidates if c.text and c.text not in set(h2_texts)]
    if not h2_texts or not cand_texts:
        return {h2: [] for h2 in h2_texts}
    all_texts = [*h2_texts, *cand_texts]
    vecs = embed_3large(all_texts)
    vec_by_text = dict(zip(all_texts, vecs))
    regions = _assign_regions(all_texts, vecs, threshold=REGION_EDGE_THRESHOLD)
    src_by_text = {c.text: c.source for c in candidates}

    out: dict[str, list[dict]] = {}
    for h2 in h2_texts:
        h2_vec, h2_region = vec_by_text[h2], regions.get(h2)
        cand_rel = [
            (t, cosine(vec_by_text[t], h2_vec)) for t in cand_texts
            if regions.get(t) == h2_region
        ]
        ranked = parent_relevance_filter(cand_rel, lo=lo, hi=hi)
        picks = mmr_select(ranked, vec_by_text, k=cap)
        rel_by_text = dict(ranked)
        out[h2] = [{
            "text": t, "source": src_by_text.get(t, "coverage_graph"),
            "parent_h2_text": h2, "parent_relevance": round(rel_by_text[t], 4),
            "region_id": str(h2_region) if h2_region is not None else None,
        } for t in picks]
    return out
