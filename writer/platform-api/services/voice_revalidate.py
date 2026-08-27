"""Async `voice_revalidate` job — re-score the voice-scored pages through the
deployed nlp path and store the before/after distribution on the job row.

Why a job (not just the CLI). `scripts/revalidate_voice_scores.py` does the same
measurement from a shell, but the shell isn't always reachable: a sandboxed
operator has no private-network path to `nlp.railway.internal`. The async worker
runs *inside* PLATFORM and does — the same access every generate/reoptimize job
already relies on. So this wraps the re-score as a job whose result lands on the
`async_jobs` row, readable straight from Supabase.

Read-only w.r.t. the page baselines: like clicking "Score" in the UI it inserts
one score-history row, but it never overwrites `voice_score`/`voice_violations`,
so the stored baseline stays intact for the before/after comparison.

Cost: one SERP + one scoring call per page (SERP is cached per keyword+location),
the same as a UI score.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# The eight voice-scorecard dimensions, in rubric order.
DIMENSIONS = [
    "tone", "writing_style", "person", "vocabulary",
    "audience_fit", "pain_points", "cta_fit", "distinctiveness",
]

# Re-score at most this many pages concurrently. nlp /score-page is rate-limited
# (10/min) and each call is slow (SERP + LLM), so a small fan-out keeps a full
# 17-page run well under the stale-job timeout without tripping the limiter.
_DEFAULT_CONCURRENCY = 3


def _dim_scores(voice_violations: Optional[dict]) -> dict[str, Optional[float]]:
    """Per-dimension scores from a stored/returned scorecard, applicable-aware.

    Mirrors `voice_card._dimension_score`: a dimension the judge marked
    ``applicable: false`` contributes None, not its placeholder score (those are
    renormalized out of the headline score, so counting a placeholder 0 in a
    per-dimension mean would understate that dimension). `bool` is excluded too.
    """
    dims = (voice_violations or {}).get("dimensions") or {}
    out: dict[str, Optional[float]] = {}
    for key in DIMENSIONS:
        entry = dims.get(key)
        if not isinstance(entry, dict) or entry.get("applicable") is False:
            out[key] = None
            continue
        score = entry.get("score")
        out[key] = (
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else None
        )
    return out


def _fetch_pages(limit: int = 0) -> list[dict]:
    """Every voice-scored page from both tables, newest first, with baseline."""
    sb = get_supabase()
    rows: list[dict] = []

    local = (
        sb.table("local_seo_pages")
        .select("id, client_id, keyword, location, content_html, voice_score, "
                "voice_violations, deleted_at, created_at")
        .not_.is_("voice_score", "null")
        .order("created_at", desc=True)
        .execute()
    )
    for r in local.data or []:
        rows.append({**r, "kind": "local_seo"})

    ecom = (
        sb.table("ecommerce_pages")
        .select("id, client_id, keyword, page_type, content_html, voice_score, "
                "voice_violations, deleted_at, created_at")
        .not_.is_("voice_score", "null")
        .order("created_at", desc=True)
        .execute()
    )
    for r in ecom.data or []:
        rows.append({**r, "kind": "ecommerce"})

    if limit and limit > 0:
        rows = rows[:limit]
    return rows


async def _rescore(page: dict) -> dict:
    """Re-score one page via the production path. Returns the nlp voice
    scorecard, or ``{"error": …}`` — one bad page never aborts the run."""
    from services import ecommerce_service, local_seo_service
    try:
        if page["kind"] == "local_seo":
            result = await local_seo_service.score_page(
                client_id=page["client_id"],
                keyword=page["keyword"],
                location=page.get("location") or "",
                location_code=None,
                page_url=None,
                page_content=page.get("content_html"),
                serp_analysis=None,
            )
        else:
            result = await ecommerce_service.score_page(
                client_id=page["client_id"],
                keyword=page["keyword"],
                page_type=page.get("page_type") or "product",
                page_url=None,
                page_content=page.get("content_html"),
                serp_analysis=None,
            )
        return result.get("voice_compliance") or {"error": "no_voice_compliance_in_response"}
    except Exception as exc:  # noqa: BLE001 — report + continue, never abort the batch
        return {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def _dist(scores: list[float]) -> Optional[dict]:
    if not scores:
        return None
    return {
        "n": len(scores),
        "min": round(min(scores), 1),
        "avg": round(statistics.mean(scores), 1),
        "median": round(statistics.median(scores), 1),
        "max": round(max(scores), 1),
        "below_80": sum(1 for s in scores if s < 80),
        "at_or_above_90": sum(1 for s in scores if s >= 90),
    }


def _summarize(results: list[dict]) -> dict:
    """Assemble the storable before/after summary from per-page results."""
    base_scores = [r["baseline_score"] for r in results if r["baseline_score"] is not None]
    new_scores = [r["new_score"] for r in results if r["new_score"] is not None]
    moved = [
        r["new_score"] - r["baseline_score"]
        for r in results
        if r["baseline_score"] is not None and r["new_score"] is not None
    ]
    per_dimension: dict[str, dict] = {}
    for key in DIMENSIONS:
        b = [r["baseline_dims"].get(key) for r in results if r["baseline_dims"].get(key) is not None]
        a = [r["new_dims"].get(key) for r in results if r["new_dims"].get(key) is not None]
        per_dimension[key] = {
            "before": round(statistics.mean(b), 1) if b else None,
            "after": round(statistics.mean(a), 1) if a else None,
        }
    return {
        "count": len(results),
        "errors": sum(1 for r in results if r["error"]),
        "before": _dist(base_scores),
        "after": _dist(new_scores),
        "delta": {
            "mean": round(statistics.mean(moved), 1) if moved else None,
            "down": sum(1 for d in moved if d < 0),
            "up": sum(1 for d in moved if d > 0),
            "unchanged": sum(1 for d in moved if d == 0),
        },
        "per_dimension": per_dimension,
        "pages": [
            {
                "kind": r["kind"],
                "keyword": r["keyword"],
                "baseline": r["baseline_score"],
                "new": r["new_score"],
                "delta": (
                    round(r["new_score"] - r["baseline_score"], 1)
                    if r["baseline_score"] is not None and r["new_score"] is not None
                    else None
                ),
                "analysis": r["analysis"],
                "error": r["error"],
            }
            for r in results
        ],
    }


async def run_revalidation(limit: int = 0, concurrency: int = _DEFAULT_CONCURRENCY) -> dict:
    """Re-score the voice-scored pages and return the before/after summary."""
    pages = _fetch_pages(limit)
    if not pages:
        return {"count": 0, "errors": 0, "before": None, "after": None,
                "delta": {}, "per_dimension": {}, "pages": [], "note": "no_scored_pages"}

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(page: dict) -> dict:
        async with sem:
            baseline = page.get("voice_score")
            baseline = float(baseline) if baseline is not None else None
            baseline_dims = _dim_scores(page.get("voice_violations"))
            scorecard = await _rescore(page)
            new = scorecard.get("score") if isinstance(scorecard, dict) else None
            new = float(new) if isinstance(new, (int, float)) and not isinstance(new, bool) else None
            return {
                "kind": page["kind"],
                "keyword": page.get("keyword"),
                "baseline_score": baseline,
                "baseline_dims": baseline_dims,
                "new_score": new,
                "new_dims": _dim_scores(scorecard) if isinstance(scorecard, dict) else {},
                "analysis": scorecard.get("analysis") if isinstance(scorecard, dict) else None,
                "error": scorecard.get("error") if isinstance(scorecard, dict) else None,
            }

    results = await asyncio.gather(*[_one(p) for p in pages])
    return _summarize(list(results))


async def run_revalidate_job(job: dict) -> None:
    """Job handler: re-score and settle the row with the summary as `result`."""
    payload = job.get("payload") or {}
    try:
        limit = int(payload.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    try:
        concurrency = int(payload.get("concurrency") or _DEFAULT_CONCURRENCY)
    except (TypeError, ValueError):
        concurrency = _DEFAULT_CONCURRENCY

    logger.info("voice_revalidate.start", extra={"job_id": job.get("id"), "limit": limit})
    summary = await run_revalidation(limit=limit, concurrency=concurrency)
    get_supabase().table("async_jobs").update(
        {"status": "complete", "result": summary, "completed_at": "now()"}
    ).eq("id", job["id"]).execute()
    logger.info(
        "voice_revalidate.done",
        extra={"job_id": job.get("id"), "count": summary.get("count"),
               "errors": summary.get("errors")},
    )
