"""Embedding backends (provider-pluggable).

Locked-decision override (owner, 2026-06-15): the app's embedding model moves
from OpenAI ``text-embedding-3-small`` to Google ``gemini-embedding-001``,
whole-app, for quality/consistency. The swap is gated behind
``settings.embedding_provider`` (default ``"openai"``) so it ships **dormant**:
flip to ``"gemini"`` only after ``GEMINI_API_KEY`` is provisioned + smoke-tested,
then recalibrate the cosine thresholds in ``config.py`` on live Gemini runs (their
similarity distribution differs from OpenAI's).

Correctness rule: cosine comparisons must never mix providers' vectors — they are
the same length (1536) but live in different spaces, so cross-provider cosine is
meaningless. This is enforced per-session via ``sessions.embedding_model``.
"""

from __future__ import annotations

import logging
import math
import time

import httpx

from fanout.cancellation import raise_if_cancelled
from fanout.concurrency import ContextThreadPoolExecutor
from fanout.cost_meter import embedding_token_cost, record_cost

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when an embedding provider call fails."""


def l2_normalize(vec: list[float]) -> list[float]:
    """Scale a vector to unit length (no-op for an already-unit / zero vector)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


class OpenAIEmbedder:
    """``text-embedding-3-*`` via the OpenAI SDK (the historical default)."""

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        raise_if_cancelled()
        started = time.perf_counter()
        try:
            resp = self._client.embeddings.create(model=self._model, input=texts)
        except Exception as exc:  # noqa: BLE001 — surfaced as EmbeddingError to caller
            raise EmbeddingError(f"OpenAI embedding call failed: {exc}") from exc
        usage = getattr(resp, "usage", None)
        cost = embedding_token_cost(self._model, getattr(usage, "total_tokens", None))
        record_cost(cost)  # PRD §16.4 — token-derived cost
        logger.info(
            "external_call",
            extra={
                "event": "external_call",
                "service": "openai",
                "endpoint": "embeddings",
                "result_count": len(texts),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "cost_usd": cost,
            },
        )
        # Order by the response's `index` rather than trusting list order, so each
        # vector stays aligned with texts[i] (#4). OpenAI returns in order today;
        # this makes it an enforced invariant. (Gemini's batch has no such field.)
        ordered = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        return [d.embedding for d in ordered]


class GeminiEmbedder:
    """``gemini-embedding-001`` via the Gemini API (Google AI Studio, REST).

    Requests ``output_dimensionality`` (default 1536, Matryoshka) so the stored
    ``vector(1536)`` columns are unchanged. Gemini does NOT unit-normalize
    truncated (<3072-dim) vectors, so we L2-normalize here to keep cosine math
    consistent with the rest of the pipeline. Batches are chunked to stay within
    the provider's per-request limit.
    """

    _BASE = "https://generativelanguage.googleapis.com/v1beta"
    _MAX_BATCH = 100  # conservative; the relevance gate calls with up to 1000

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        output_dim: int = 1536,
        task_type: str = "SEMANTIC_SIMILARITY",
        timeout_s: float = 60.0,
        max_workers: int = 8,
    ):
        if not api_key:
            raise EmbeddingError(
                "embedding_provider='gemini' but GEMINI_API_KEY is not set"
            )
        self._api_key = api_key
        self._model = model if model.startswith("models/") else f"models/{model}"
        self._output_dim = output_dim
        self._task_type = task_type
        self._timeout_s = timeout_s
        # Max chunk requests in flight at once. Bounded to respect Gemini's region
        # RPM (the 5M tok/min quota is no constraint for short keywords).
        self._max_workers = max(1, max_workers)

    @property
    def model(self) -> str:
        # The bare model id (no "models/" prefix) — used to tag sessions + meter.
        return self._model.removeprefix("models/")

    def _embed_chunk(self, texts: list[str]) -> list[list[float]]:
        raise_if_cancelled()
        started = time.perf_counter()
        url = f"{self._BASE}/{self._model}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": self._model,
                    "content": {"parts": [{"text": t}]},
                    "taskType": self._task_type,
                    "outputDimensionality": self._output_dim,
                }
                for t in texts
            ]
        }
        try:
            resp = httpx.post(
                url,
                headers={"x-goog-api-key": self._api_key},
                json=payload,
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Gemini embedding call failed: {exc}") from exc
        # Parse defensively: a 200 with a non-JSON body or an unexpected shape
        # (missing "embeddings"/"values", null entries) must surface as an
        # EmbeddingError so the OpenAILLM.embed -> LLMError contract holds for the
        # synchronous callers (finalize, disambiguation) that catch LLMError only.
        try:
            embeddings = resp.json()["embeddings"]
            vectors = [l2_normalize(e["values"]) for e in embeddings]
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError(
                f"Gemini returned a malformed embeddings response: {exc}"
            ) from exc
        # Alignment (#4): batchEmbedContents returns one embedding per request in
        # request order, with NO index/echo field to verify against — so vectors are
        # aligned to texts[i] by position and the count check is the only enforceable
        # guard (an API reorder would be undetectable here).
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Gemini returned {len(vectors)} embeddings for {len(texts)} inputs"
            )
        # Meter + log per chunk (#5) so a partial failure of a later chunk still
        # attributes the cost of the chunks that already completed (they were
        # billed). Gemini's response carries no token usage; estimate from length.
        est_tokens = sum(max(1, len(t) // 4) for t in texts)
        cost = embedding_token_cost(self.model, est_tokens)
        record_cost(cost)  # PRD §16.4 — per chunk
        logger.info(
            "external_call",
            extra={
                "event": "external_call",
                "service": "gemini",
                "endpoint": "batchEmbedContents",
                "result_count": len(texts),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "cost_usd": cost,
            },
        )
        return vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        raise_if_cancelled()
        chunks = [
            texts[i : i + self._MAX_BATCH]
            for i in range(0, len(texts), self._MAX_BATCH)
        ]
        if len(chunks) == 1:
            return self._embed_chunk(chunks[0])
        # Chunks are independent network calls; run them concurrently (bounded) so a
        # 1000-item batch isn't 10 sequential round-trips — Gemini caps
        # batchEmbedContents at 100 requests/call, so the chunk count can't shrink.
        # ContextThreadPoolExecutor propagates the cost-meter + cancellation
        # contextvars into the workers; .map preserves input order and re-raises the
        # first failing chunk's EmbeddingError. Each chunk meters its own cost (#5).
        workers = min(self._max_workers, len(chunks))
        with ContextThreadPoolExecutor(max_workers=workers) as pool:
            chunk_results = list(pool.map(self._embed_chunk, chunks))
        return [v for chunk_vecs in chunk_results for v in chunk_vecs]
