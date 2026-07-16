#!/usr/bin/env python3
"""One-off: re-embed every silo_candidates row with Gemini at cutover.

The suite standardized off OpenAI embeddings. `silo_candidates.suggested_keyword_embedding`
holds the ONLY persisted embeddings that were OpenAI (`text-embedding-3-large` @ 1536);
a Gemini vector can't be cosine-compared against an OpenAI one, so every existing row
must be re-embedded with Gemini before the new dedup path can trust cross-brief matches.

The dimension is unchanged (1536), so there is NO schema change — this script only
overwrites the vector values. It re-embeds each row's stored `suggested_keyword` via
`services.silo_dedup._embed_keyword` (the same Gemini call the live path now uses), so
the model/space/normalization match exactly.

Idempotent + resumable: re-embedding is an overwrite, so re-running is safe. Rows are
processed oldest-first in pages; use --limit to chunk a very large table across runs.
Per-row failures are logged and skipped (the row keeps its old vector and can be retried
on a later run) rather than aborting the whole backfill.

Run from the platform-api directory, with the platform env (GEMINI_API_KEY,
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, silo_embedding_model) loaded:

    python -m scripts.backfill_silo_embeddings_gemini            # all rows
    python -m scripts.backfill_silo_embeddings_gemini --dry-run  # count only, no writes
    python -m scripts.backfill_silo_embeddings_gemini --limit 500 --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings                       # noqa: E402
from db.supabase_client import get_supabase        # noqa: E402
from services.silo_dedup import _embed_keyword     # noqa: E402  (reuse the live Gemini path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_silo_embeddings")

_PAGE = 500  # PostgREST fetch page size


def _fetch_page(offset: int, limit: int) -> list[dict]:
    return (
        get_supabase()
        .table("silo_candidates")
        .select("id, suggested_keyword")
        .order("created_at", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
        .data
        or []
    )


def _write_vector(row_id: str, vector: list[float]) -> None:
    get_supabase().table("silo_candidates").update(
        {"suggested_keyword_embedding": vector}
    ).eq("id", row_id).execute()


async def _reembed_row(row: dict, sem: asyncio.Semaphore, dry_run: bool) -> str:
    """Return 'ok' | 'skipped' | 'failed' for one row."""
    keyword = (row.get("suggested_keyword") or "").strip()
    if not keyword:
        return "skipped"
    async with sem:
        try:
            vector = await _embed_keyword(keyword)
        except Exception as exc:  # noqa: BLE001 - log + continue, retry next run
            logger.warning("embed failed for %s (%r): %s", row.get("id"), keyword, exc)
            return "failed"
    if dry_run:
        return "ok"
    try:
        await asyncio.to_thread(_write_vector, row["id"], vector)
    except Exception as exc:  # noqa: BLE001
        logger.warning("write failed for %s: %s", row.get("id"), exc)
        return "failed"
    return "ok"


async def main() -> int:
    ap = argparse.ArgumentParser(description="Re-embed silo_candidates with Gemini.")
    ap.add_argument("--limit", type=int, default=0, help="max rows to process (0 = all)")
    ap.add_argument("--concurrency", type=int, default=4, help="parallel embed calls")
    ap.add_argument("--dry-run", action="store_true", help="embed but do not write")
    args = ap.parse_args()

    if not settings.gemini_api_key:
        logger.error("GEMINI_API_KEY not configured — aborting.")
        return 2
    logger.info(
        "Backfill starting: model=%s dim=%s dry_run=%s concurrency=%s",
        settings.silo_embedding_model, settings.silo_embedding_dimensions,
        args.dry_run, args.concurrency,
    )

    sem = asyncio.Semaphore(max(1, args.concurrency))
    totals = {"ok": 0, "skipped": 0, "failed": 0}
    offset = 0
    while True:
        want = _PAGE if args.limit == 0 else min(_PAGE, args.limit - totals["ok"] - totals["skipped"] - totals["failed"])
        if want <= 0:
            break
        rows = await asyncio.to_thread(_fetch_page, offset, want)
        if not rows:
            break
        results = await asyncio.gather(*(_reembed_row(r, sem, args.dry_run) for r in rows))
        for r in results:
            totals[r] += 1
        offset += len(rows)
        logger.info("progress: %s", totals)
        if len(rows) < want:
            break

    logger.info("Backfill complete: %s", totals)
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
