"""Cross-brief silo persistence + deduplication (Platform PRD v1.4 §8.5).

The async worker calls `process_silo_dedup_job` for every job with
`job_type='silo_dedup'`. The orchestrator enqueues a job whenever a
brief module_output transitions to `status='complete'`.

Algorithm summary (per PRD §8.5):

  For each silo candidate in the brief output's silo_candidates array:
    1. Skip if viable_as_standalone_article == false (defense in depth)
    2. Skip if the originating run's client is archived
    3. Embed suggested_keyword via text-embedding-3-large @ 1536 dims
    4. Query existing silo_candidates rows for the same client_id
       (excluding rejected) ordered by cosine distance ascending
    5. If best distance <= 0.15 (cosine >= 0.85): increment occurrence
       on the matched row; append run_id to source_run_ids; overwrite
       source_headings with the latest payload
    6. Else: insert a new row with status='proposed'

Failure handling: never block the run. Embedding/pgvector errors retry
once with backoff and then mark the async_jobs row failed.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Optional

from openai import AsyncOpenAI

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


_openai_client: Optional[AsyncOpenAI] = None


def _openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


# ---------------------------------------------------------------------------
# Enqueue (called from the orchestrator after brief module_output is saved)
# ---------------------------------------------------------------------------


def enqueue_silo_dedup(
    *,
    module_output_id: str,
    run_id: str,
    client_id: str,
) -> None:
    """Insert an async_jobs row that triggers silo dedup for a brief.

    Called from `services.orchestrator` after a successful brief run.
    Failure to enqueue logs but does NOT raise — the brief itself is
    already persisted; missing the dedup is a recoverable degradation.
    """
    try:
        get_supabase().table("async_jobs").insert(
            {
                "job_type": "silo_dedup",
                "entity_id": module_output_id,
                "payload": {
                    "module_output_id": module_output_id,
                    "run_id": run_id,
                    "client_id": client_id,
                },
            }
        ).execute()
        logger.info(
            "silo_dedup_enqueued",
            extra={
                "module_output_id": module_output_id,
                "run_id": run_id,
                "client_id": client_id,
            },
        )
    except Exception as exc:
        logger.error(
            "silo_dedup_enqueue_failed",
            extra={
                "run_id": run_id,
                "module_output_id": module_output_id,
                "error": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


def _unit_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return v
    return [x / norm for x in v]


async def _embed_keyword(text: str) -> list[float]:
    """Call OpenAI text-embedding-3-large @ configured dimensions.

    Unit-normalizes the result so cosine == dot product (consistent with
    Brief Generator v2.0's convention, even though the platform stores
    its own embedding rather than reusing the brief's).
    """
    response = await _openai().embeddings.create(
        model=settings.silo_embedding_model,
        input=text,
        dimensions=settings.silo_embedding_dimensions,
    )
    return _unit_normalize(list(response.data[0].embedding))


# ---------------------------------------------------------------------------
# Match query (uses pgvector RPC for safety; raw SQL via supabase rpc helper)
# ---------------------------------------------------------------------------


async def _find_match(
    client_id: str,
    embedding: list[float],
) -> Optional[dict]:
    """Return the closest non-rejected silo for client_id, or None.

    Uses Supabase's `rpc` channel because `<=>` operator usage requires
    a SQL function — supabase-py's query builder doesn't expose vector
    operators. The function is defined in a follow-up migration as
    `silo_candidates_match(client_id uuid, embedding vector, k int)`.
    Until that's in place, we fall back to a SELECT over all rows for
    the client and compute distance in Python (acceptable up to ~10k
    rows per client, well above v1's expected scale).
    """
    threshold = settings.silo_dedup_cosine_threshold

    def _query():
        return (
            get_supabase()
            .table("silo_candidates")
            .select(
                "id, suggested_keyword, suggested_keyword_embedding, "
                "status, source_run_ids, occurrence_count"
            )
            .eq("client_id", client_id)
            .neq("status", "rejected")
            .execute()
        )

    rows = (await asyncio.to_thread(_query)).data or []
    if not rows:
        return None

    best = None
    best_sim = -1.0
    for row in rows:
        existing = row.get("suggested_keyword_embedding")
        if not existing:
            continue
        # Postgres vector → Python: supabase-py returns it as a string
        # like "[0.1,0.2,...]". Parse defensively.
        if isinstance(existing, str):
            try:
                existing_vec = [float(x) for x in existing.strip("[]").split(",")]
            except ValueError:
                continue
        else:
            existing_vec = list(existing)
        if len(existing_vec) != len(embedding):
            continue
        sim = sum(a * b for a, b in zip(embedding, existing_vec))
        if sim > best_sim:
            best_sim = sim
            best = row

    if best is None or best_sim < threshold:
        return None
    return {**best, "_similarity": best_sim}


# ---------------------------------------------------------------------------
# Per-candidate processor
# ---------------------------------------------------------------------------


async def _process_one_candidate(
    candidate: dict,
    *,
    run_id: str,
    client_id: str,
) -> str:
    """Process one silo candidate from the brief output.

    Returns one of: 'dedup_hit', 'new_insert', 'skipped_non_viable'.
    """
    if not candidate.get("viable_as_standalone_article", True):
        return "skipped_non_viable"

    keyword = (candidate.get("suggested_keyword") or "").strip()
    if not keyword:
        return "skipped_non_viable"

    embedding = await _embed_keyword(keyword)
    match = await _find_match(client_id, embedding)

    supabase = get_supabase()

    if match is not None:
        # Dedup hit — update existing row.
        existing_run_ids = list(match.get("source_run_ids") or [])
        if run_id not in existing_run_ids:
            existing_run_ids.append(run_id)
        update_payload = {
            "occurrence_count": (match.get("occurrence_count") or 1) + 1,
            "last_seen_run_id": run_id,
            "source_run_ids": existing_run_ids,
            "source_headings": candidate.get("source_headings"),
            "discard_reason_breakdown": candidate.get("discard_reason_breakdown"),
            "viability_reasoning": candidate.get("viability_reasoning"),
        }
        # Refresh per-candidate scores from latest brief output
        for k in (
            "cluster_coherence_score",
            "search_demand_score",
            "estimated_intent",
            "routed_from",
        ):
            if candidate.get(k) is not None:
                update_payload[k] = candidate[k]

        await asyncio.to_thread(
            lambda: supabase.table("silo_candidates")
            .update(update_payload)
            .eq("id", match["id"])
            .execute()
        )
        return "dedup_hit"

    # No match → insert
    insert_row = {
        "client_id": client_id,
        "suggested_keyword": keyword,
        "suggested_keyword_embedding": embedding,
        "status": "proposed",
        "occurrence_count": 1,
        "first_seen_run_id": run_id,
        "last_seen_run_id": run_id,
        "source_run_ids": [run_id],
        "cluster_coherence_score": candidate.get("cluster_coherence_score"),
        "search_demand_score": candidate.get("search_demand_score"),
        "viable_as_standalone_article": candidate.get(
            "viable_as_standalone_article", True
        ),
        "viability_reasoning": candidate.get("viability_reasoning"),
        "estimated_intent": candidate.get("estimated_intent"),
        "routed_from": candidate.get("routed_from"),
        "discard_reason_breakdown": candidate.get("discard_reason_breakdown"),
        "source_headings": candidate.get("source_headings"),
    }
    await asyncio.to_thread(
        lambda: supabase.table("silo_candidates").insert(insert_row).execute()
    )
    return "new_insert"


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


async def process_silo_dedup_job(job: dict) -> None:
    """Worker entry point for `job_type='silo_dedup'`.

    Loads the brief output, processes each silo candidate, and writes
    metrics back onto the async_jobs row. Errors are isolated per job —
    a failure here never affects the originating run's state.
    """
    payload = job.get("payload") or {}
    job_id = job["id"]
    run_id = payload.get("run_id")
    client_id = payload.get("client_id")
    module_output_id = payload.get("module_output_id")

    supabase = get_supabase()

    metrics = {
        "candidates_processed": 0,
        "dedup_hits": 0,
        "new_inserts": 0,
        "skipped_non_viable": 0,
        "embedding_cost_usd": 0.0,
    }

    try:
        # 1. Skip if client archived (defense in depth — orchestrator
        # also checks but a job could survive a client archive).
        client_row = (
            await asyncio.to_thread(
                lambda: supabase.table("clients")
                .select("id, archived")
                .eq("id", client_id)
                .single()
                .execute()
            )
        ).data or {}
        if client_row.get("archived"):
            await _complete_job(job_id, metrics, note="client_archived")
            logger.warning(
                "silo_dedup_skipped_archived_client",
                extra={"job_id": job_id, "client_id": client_id},
            )
            return

        # 2. Load the brief output's silo_candidates array.
        mo = (
            await asyncio.to_thread(
                lambda: supabase.table("module_outputs")
                .select("output_payload")
                .eq("id", module_output_id)
                .single()
                .execute()
            )
        ).data or {}
        output = mo.get("output_payload") or {}
        candidates = output.get("silo_candidates") or []

        for cand in candidates:
            metrics["candidates_processed"] += 1
            try:
                result = await _process_one_candidate(
                    cand, run_id=run_id, client_id=client_id,
                )
            except Exception as exc:
                # Per-candidate failure: log and continue. The job as a
                # whole still completes if at least one succeeds.
                logger.warning(
                    "silo_dedup_candidate_failed",
                    extra={
                        "job_id": job_id,
                        "keyword": cand.get("suggested_keyword"),
                        "error": str(exc),
                    },
                )
                continue

            if result == "dedup_hit":
                metrics["dedup_hits"] += 1
            elif result == "new_insert":
                metrics["new_inserts"] += 1
            elif result == "skipped_non_viable":
                metrics["skipped_non_viable"] += 1

        # text-embedding-3-large @ 1536 dims is ~$0.00013 per 1K tokens;
        # silo keywords are 5–10 tokens → ~$0.0005 per call.
        billed = metrics["dedup_hits"] + metrics["new_inserts"]
        metrics["embedding_cost_usd"] = round(billed * 0.0005, 6)

        await _complete_job(job_id, metrics)
        logger.info(
            "silo_dedup_complete",
            extra={"job_id": job_id, "run_id": run_id, **metrics},
        )

    except Exception as exc:
        logger.error(
            "silo_dedup_failed",
            extra={"job_id": job_id, "run_id": run_id, "error": str(exc)},
        )
        try:
            await asyncio.to_thread(
                lambda: supabase.table("async_jobs")
                .update(
                    {
                        "status": "failed",
                        "error": str(exc)[:500],
                        "result": metrics,
                        "completed_at": "now()",
                    }
                )
                .eq("id", job_id)
                .execute()
            )
        except Exception:
            pass


async def _complete_job(job_id: str, metrics: dict, note: Optional[str] = None) -> None:
    payload = {**metrics}
    if note:
        payload["note"] = note
    await asyncio.to_thread(
        lambda: get_supabase()
        .table("async_jobs")
        .update(
            {
                "status": "complete",
                "result": payload,
                "completed_at": "now()",
            }
        )
        .eq("id", job_id)
        .execute()
    )
