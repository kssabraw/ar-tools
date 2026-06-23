"""Enriched silo anchor — demo-keyword centroid (routing-calibration follow-up).

M5 measured Lever-3 routing at ~71% accuracy because the silo anchor is just an
embedding of the rationale text, and rationales for the same seed all share the
seed token — so anchors cluster in embedding space and tiny cosine differences
decide routing (the documented "everything ≈ the seed" problem).

This module enriches the anchor: at finalize, the LLM generates ~30 example
keywords that exemplify each silo, their embeddings are centroided with the
rationale embedding, and the result is the silo's new anchor. Examples are
silo-discriminative (they contain silo-specific tokens like "peptide" or
"side effects" rather than just the seed), so the centroid pulls a candidate
keyword toward the silo whose examples share its discriminative tokens.

Cost: one LLM call per silo at finalize (cheap, one-off per session) +
embeddings (negligible). Gate-time routing stays pure-embedding — no hot-path
cost change.

Failure handling: if example generation or embedding fails for a silo, the
anchor falls back to the rationale-only embedding (current behavior). Never
raises; the caller decides whether to flag a partial degrade.
"""

from __future__ import annotations

import logging

import numpy as np

from fanout.concurrency import ContextThreadPoolExecutor

logger = logging.getLogger(__name__)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n == 0:
        return v
    return v / n


def compute_centroid(
    rationale_embedding: list[float],
    example_embeddings: list[list[float]],
) -> list[float]:
    """Unit-normalized mean of (rationale + examples). The rationale gets the
    same weight as one example, so a silo with N examples is N+1 vectors averaged.
    Cosine works on direction only, so the final unit-normalization keeps the
    anchor compatible with the existing scorers."""
    vecs = [np.asarray(rationale_embedding, dtype=np.float64)]
    for e in example_embeddings:
        if e:  # skip empty vectors (failed embeddings)
            vecs.append(np.asarray(e, dtype=np.float64))
    if not vecs:
        return rationale_embedding
    normed = [_unit(v) for v in vecs]
    mean = np.mean(np.stack(normed, axis=0), axis=0)
    return _unit(mean).tolist()


def generate_examples_for_silos(
    *,
    seed: str,
    silos: list[dict],
    peer_terms: list[str],
    llm,
    n: int,
    max_workers: int,
) -> dict[str, list[str]]:
    """Parallel LLM call per silo. Returns silo_id -> list of example keywords
    (may be shorter than `n` after the model returns + validation). A silo
    that fails (LLM error, parse error) gets [], and the caller falls back to
    the rationale-only anchor for it."""
    results: dict[str, list[str]] = {silo["id"]: [] for silo in silos}
    if not silos:
        return results

    def one(silo: dict) -> tuple[str, list[str]]:
        try:
            examples = llm.silo_anchor_examples(
                seed=seed,
                silo_name=silo.get("name") or "",
                rationale=silo.get("rationale") or "",
                relationship_type=silo.get("relationship_type") or "",
                peer_terms=peer_terms,
                n=n,
            )
            return silo["id"], examples
        except Exception as exc:  # noqa: BLE001 — degrade per-silo
            logger.warning(
                "silo_anchor_examples_failed",
                extra={"event": "silo_anchor_examples_failed",
                       "silo_id": silo["id"], "reason": repr(exc)},
            )
            return silo["id"], []

    with ContextThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        for sid, examples in ex.map(one, silos):
            results[sid] = examples
    return results


def build_enriched_anchors(
    *,
    seed: str,
    silos: list[dict],
    rationale_embeddings: dict[str, list[float]],
    peer_terms: list[str],
    llm,
    embed_fn,
    n: int = 30,
    max_workers: int = 5,
) -> tuple[dict[str, list[float]], dict[str, int]]:
    """Compute one enriched anchor per silo. Returns (anchors_by_silo_id,
    example_counts_by_silo_id). Silos for which example generation or embedding
    fails fall back to their rationale embedding (anchor unchanged)."""
    examples_by_silo = generate_examples_for_silos(
        seed=seed, silos=silos, peer_terms=peer_terms,
        llm=llm, n=n, max_workers=max_workers,
    )

    # Embed every example across all silos in one batched call.
    flat: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    for silo in silos:
        ex = examples_by_silo.get(silo["id"], [])
        spans[silo["id"]] = (len(flat), len(flat) + len(ex))
        flat.extend(ex)
    example_vectors: list[list[float]] = []
    if flat:
        try:
            example_vectors = embed_fn(flat)
        except Exception as exc:  # noqa: BLE001 — degrade to rationale-only anchors
            logger.warning(
                "silo_anchor_example_embed_failed",
                extra={"event": "silo_anchor_example_embed_failed",
                       "reason": repr(exc)},
            )
            example_vectors = []
        if len(example_vectors) != len(flat):
            # Partial result; treat as full failure for safety (don't half-enrich).
            example_vectors = []

    anchors: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for silo in silos:
        sid = silo["id"]
        rationale = rationale_embeddings.get(sid)
        if not rationale:
            continue
        start, end = spans[sid]
        if example_vectors:
            anchors[sid] = compute_centroid(rationale, example_vectors[start:end])
            counts[sid] = end - start
        else:
            anchors[sid] = rationale  # fallback
            counts[sid] = 0
    return anchors, counts
