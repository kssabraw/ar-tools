"""Keyword Research — Gemini semantic relevance gate.

The token-based gates (coherence / brand-flood / generic-drift) are cheap and
catch the obvious drift, but they can't judge MEANING: a keyword that shares a
seed word can still be off-topic ("party rentals" from "third party ..."), and a
genuinely relevant adjacent term that shares no seed word looks the same to them
as junk. This adds a semantic layer ON TOP of the token gates (never replacing
them — per the Fanout experience, embedding cosine alone drifts on broad seeds):

  * embed a rich ANCHOR set — the seeds + the LLM-fanned-out seed intents + the
    client's own site topics (see keyword_research_topics) — with the suite's
    standard gemini-embedding-2, and
  * score each candidate keyword by its max cosine similarity to any anchor,
    dropping those below a floor while ALWAYS keeping phrase-containment keywords
    (which are on-topic by construction).

The score is stored on every surviving keyword so the view can sort by it and
nothing is silently lost. Design mirrors services/keyword_research.py: the
scoring/gating math is PURE and unit-tested; the embedding call is the only I/O
and is best-effort (any failure → the gate is skipped and the run keeps the
token-gated set unchanged).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional

import httpx

from config import settings
from services import keyword_research

logger = logging.getLogger(__name__)

_GEMINI_EMBED_BASE = "https://generativelanguage.googleapis.com/v1beta"
_EMBED_BATCH = 100      # Gemini batchEmbedContents request cap per call
_EMBED_CONCURRENCY = 4  # concurrent batch calls
_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def unit_normalize(v: list[float]) -> list[float]:
    """Unit-normalize a vector so cosine similarity == dot product. Pure."""
    norm = math.sqrt(sum(x * x for x in v))
    return v if norm == 0.0 else [x / norm for x in v]


def max_cosine(vec: list[float], anchors: list[list[float]]) -> float:
    """Max cosine similarity of a (unit) vector to any (unit) anchor vector.
    Both sides are assumed unit-normalized, so cosine == dot product. Returns
    0.0 when there are no anchors or the vector is empty. Pure."""
    if not vec or not anchors:
        return 0.0
    best = -1.0
    for a in anchors:
        if len(a) != len(vec):
            continue
        dot = sum(x * y for x, y in zip(vec, a))
        if dot > best:
            best = dot
    return best if best > -1.0 else 0.0


def contains_seed_phrase(keyword: Optional[str], seeds: list[str]) -> bool:
    """Whether a keyword contains a full seed phrase (phrase-containment) — those
    are on-topic by construction and must never be dropped by the semantic gate.
    Uses significant tokens so "third party claims administrator" matches a
    keyword containing all of {third, party, claims, administrator}. Pure."""
    kt = keyword_research.token_set(keyword)
    if not kt:
        return False
    for s in seeds or []:
        st = keyword_research.token_set(s)
        if st and st <= kt:
            return True
    return False


def apply_relevance(
    rows: list[dict],
    scores: list[float],
    seeds: list[str],
    floor: float,
) -> tuple[list[dict], dict]:
    """Attach ``relevance_score`` to each row and drop the semantically off-topic
    ones (score < floor), ALWAYS keeping phrase-containment keywords regardless of
    score. Returns (kept_rows, report). ``rows`` and ``scores`` are index-aligned.

    ``report`` = {gate, floor, scored, kept, dropped}. Pure — the caller does the
    embedding I/O and passes the scores in."""
    kept: list[dict] = []
    dropped = 0
    for r, score in zip(rows, scores):
        r = {**r, "relevance_score": round(float(score), 4)}
        if score >= floor or contains_seed_phrase(r.get("keyword"), seeds):
            kept.append(r)
        else:
            dropped += 1
    report = {"gate": "semantic", "floor": round(float(floor), 3),
              "scored": len(rows), "kept": len(kept), "dropped": dropped}
    return kept, report


# ---------------------------------------------------------------------------
# Embedding (I/O) — Gemini batchEmbedContents, best-effort.
# ---------------------------------------------------------------------------
def _model_path() -> str:
    model = settings.keyword_research_embedding_model or settings.silo_embedding_model
    return model if model.startswith("models/") else f"models/{model}"


async def _embed_one_batch(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    model_path = _model_path()
    dims = settings.silo_embedding_dimensions
    payload = {
        "requests": [
            {
                "model": model_path,
                "content": {"parts": [{"text": t}]},
                "taskType": "SEMANTIC_SIMILARITY",
                "outputDimensionality": dims,
            }
            for t in texts
        ]
    }
    resp = await client.post(
        f"{_GEMINI_EMBED_BASE}/{model_path}:batchEmbedContents",
        headers={"x-goog-api-key": settings.gemini_api_key},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    out: list[list[float]] = []
    for emb in data.get("embeddings") or []:
        values = (emb.get("values") if isinstance(emb, dict) else None) or []
        out.append(unit_normalize([float(x) for x in values]))
    return out


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with gemini-embedding-2 (unit-normalized), chunked + concurrent.
    Returns a list index-aligned with ``texts`` ([] entries for any that failed to
    come back). Raises only if the Gemini key is missing — batch HTTP errors
    propagate to the caller, which treats the whole gate as best-effort."""
    if not settings.gemini_api_key:
        raise RuntimeError("gemini_api_key_not_configured")
    clean = [(t or "").strip() for t in texts]
    batches = [clean[i:i + _EMBED_BATCH] for i in range(0, len(clean), _EMBED_BATCH)]

    sem = asyncio.Semaphore(_EMBED_CONCURRENCY)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async def _run(batch: list[str]) -> list[list[float]]:
            async with sem:
                return await _embed_one_batch(client, batch)

        results = await asyncio.gather(*[_run(b) for b in batches])

    out: list[list[float]] = []
    for res in results:
        out.extend(res)
    # Guard against a provider returning fewer vectors than inputs.
    if len(out) < len(clean):
        out.extend([[] for _ in range(len(clean) - len(out))])
    return out[: len(clean)]


async def score_relevance(
    rows: list[dict],
    anchors: list[str],
    seeds: list[str],
    floor: float,
) -> tuple[list[dict], dict]:
    """Embed the anchors + candidate keywords, score each keyword by max cosine to
    any anchor, and apply the floor (keeping phrase-containment keywords). Returns
    (kept_rows_with_scores, report). Best-effort: if embedding fails or there are
    no anchors, returns (rows, {gate: 'skipped', ...}) untouched.

    The anchor set is deduped and capped so the embedding cost stays bounded."""
    if not rows:
        return rows, {"gate": "skipped", "reason": "no_rows"}
    anchor_texts = _dedupe_cap(anchors, settings.keyword_research_relevance_anchor_cap)
    if not anchor_texts:
        return rows, {"gate": "skipped", "reason": "no_anchors"}
    if not settings.gemini_api_key:
        return rows, {"gate": "skipped", "reason": "no_gemini_key"}

    keywords = [(r.get("keyword") or "") for r in rows]
    try:
        vecs = await embed_texts(anchor_texts + keywords)
    except Exception as exc:  # noqa: BLE001 — the gate is best-effort
        logger.warning("keyword_research_relevance.embed_failed", extra={"error": str(exc)})
        return rows, {"gate": "skipped", "reason": "embed_error"}

    anchor_vecs = [v for v in vecs[: len(anchor_texts)] if v]
    kw_vecs = vecs[len(anchor_texts):]
    if not anchor_vecs:
        return rows, {"gate": "skipped", "reason": "no_anchor_vecs"}

    scores = [max_cosine(v, anchor_vecs) for v in kw_vecs]
    return apply_relevance(rows, scores, seeds, floor)


def _dedupe_cap(texts: list[str], cap: int) -> list[str]:
    """Order-preserving dedupe (case-insensitive) + cap. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for t in texts or []:
        s = (t or "").strip()
        low = s.lower()
        if s and low not in seen:
            seen.add(low)
            out.append(s)
        if len(out) >= cap:
            break
    return out
