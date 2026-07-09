"""ICP Creator module — orchestration + persistence (client-level, converged).

platform-api owns auth + persistence; the private nlp service runs the actual
page discovery + enrichment + ICP/differentiator LLM call (`/analyze-business`).
detected_icp is the canonical client asset (Option A), consumed by both the
Local SEO nlp generator (segments + differentiators, structured) and — rendered,
with differentiators folded in — the Blog Writer run snapshot.

ICP and differentiators are produced by one call, so a single provenance
(`detected_icp.source`) governs supersede for both: a user-authored structured
ICP is never clobbered by an auto-scan unless `force=True`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from db.supabase_client import get_supabase

# Reuse the Local SEO transport + client→business mapping (no drift).
from services.local_seo_service import _business_fields, _get_client, _post_nlp

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_icp() -> dict:
    return {
        "source": None,
        "raw_text": None,
        "segments": None,
        "reasoning": None,
        "generated_at": None,
        "edited_at": None,
    }


def _scan_blocked(existing: dict, force: bool) -> bool:
    """An auto-scan is blocked only when the user authored *structured* ICP
    (segments) that the scan would overwrite. A user with only raw_text (a
    freeform ICP write-up) can still be enriched — the scan preserves it."""
    if force:
        return False
    return existing.get("source") == "user" and bool(existing.get("segments"))


def merge_raw_text(existing: dict | None, raw_text: str | None) -> dict | None:
    """Keep detected_icp in sync with the legacy free-text icp_text so newly
    created / edited clients converge. The write-up is user input, so a non-empty
    value is marked source:'user'. Structured fields are preserved. Returns None
    when nothing meaningful remains (collapses back to SQL NULL)."""
    text = (raw_text or "").strip()
    blob = {**_empty_icp(), **(existing or {})}
    blob["raw_text"] = text or None
    if text:
        blob["source"] = "user"
        blob["edited_at"] = _now_iso()
    if not any(blob.get(k) for k in ("raw_text", "segments", "reasoning")):
        return None
    return blob


def _persist(client_id: str, updates: dict) -> None:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .update({**updates, "updated_at": _now_iso()})
        .eq("id", client_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")


def get_icp(client_id: str) -> dict:
    """Return the stored detected_icp + differentiators for a client."""
    client = _get_client(client_id)
    return {
        "detected_icp": client.get("detected_icp"),
        "differentiators": client.get("differentiators"),
    }


def ensure_scannable(client_id: str, force: bool) -> None:
    """Pre-flight the supersede guard so the router returns a real HTTP 409
    before opening the SSE stream."""
    existing = _get_client(client_id).get("detected_icp") or {}
    if _scan_blocked(existing, force):
        raise HTTPException(status_code=409, detail="icp_user_authored")


async def scan(client_id: str, force: bool, user_id: str) -> dict:
    """Run the app ICP analysis and persist detected_icp (source:'app') +
    differentiators. Refuses to overwrite a user-authored structured ICP unless
    `force`. GBP-independent: identity falls back to the client row."""
    client = _get_client(client_id)
    existing = client.get("detected_icp") or {}

    if _scan_blocked(existing, force):
        raise HTTPException(status_code=409, detail="icp_user_authored")

    fields = _business_fields(client)
    gbp = client.get("gbp") or {}
    payload = {
        "website_url": fields.get("website"),
        "business_name": fields.get("business_name") or "",
        "gbp_category": fields.get("gbp_category") or "",
        "gbp_categories": gbp.get("gbp_categories") or [],
    }

    result = await _post_nlp("/analyze-business", payload, user_id=user_id)
    icp = result.get("detected_icp") or {}
    diffs = result.get("differentiators") or []

    # Preserve any user freeform ICP (raw_text) — it still supersedes in
    # rendering — while the scan fills the structured segments around it.
    preserved_raw = existing.get("raw_text")
    blob = _empty_icp()
    blob.update(
        {
            "source": "app",
            "raw_text": preserved_raw,
            "segments": icp.get("segments"),
            "reasoning": icp.get("reasoning"),
            "generated_at": _now_iso(),
            "edited_at": existing.get("edited_at") if preserved_raw else None,
        }
    )
    _persist(client_id, {"detected_icp": blob, "differentiators": diffs})
    logger.info(
        "icp.scan_persisted",
        extra={"client_id": client_id, "pages_crawled": result.get("pages_crawled"),
               "status": result.get("analysis_status")},
    )
    return {
        "detected_icp": blob,
        "differentiators": diffs,
        "pages_crawled": result.get("pages_crawled"),
        "analysis_status": result.get("analysis_status"),
    }


async def run_icp_scan_job(job: dict) -> None:
    """Async worker entry: auto-generate a client's ICP + differentiators
    (enqueued at client creation). Best-effort — a provider error or the
    user-authored supersede guard (409) is not a hard failure. Persists via
    `scan`; this only manages the async_jobs row."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    user_id = payload.get("user_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await scan(
            client_id=client_id, force=bool(payload.get("force")), user_id=user_id
        )
        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {
                    "pages_crawled": result.get("pages_crawled"),
                    "analysis_status": result.get("analysis_status"),
                },
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info("icp.auto_scan_complete", extra={"client_id": client_id})
    except HTTPException as exc:
        # 409 = a user already authored a structured ICP → nothing to do (not an
        # error). Anything else is a best-effort miss recorded on the job.
        status = "complete" if exc.status_code == 409 else "failed"
        supabase.table("async_jobs").update(
            {"status": status, "error": str(exc.detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info(
            "icp.auto_scan_skipped",
            extra={"client_id": client_id, "status": status, "detail": str(exc.detail)},
        )
    except Exception as exc:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.warning(
            "icp.auto_scan_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )


async def enqueue_scan(client_id: str, force: bool, user_id: str) -> str:
    """Enqueue an `icp_scan` job for a manual Detect/Re-scan. Returns the job id.
    Runs in the worker (`run_icp_scan_job`), which persists the ICP, so the UI can
    navigate away and reconnect (poll `get_scan_job`). The caller should
    `ensure_scannable` first to surface the supersede 409 up front."""
    _get_client(client_id)  # validate ownership / existence
    res = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": "icp_scan",
                "entity_id": client_id,
                "payload": {"client_id": client_id, "user_id": user_id, "force": bool(force)},
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_scan_job(job_id: str, client_id: str) -> dict:
    """Poll an ICP scan job (scoped to the client). Returns {status, error}. On
    completion the caller refetches the ICP via `get_icp`."""
    res = (
        get_supabase()
        .table("async_jobs")
        .select("status, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="scan_job_not_found")
    row = res.data[0]
    return {"status": row["status"], "error": row.get("error")}


def update(
    client_id: str,
    *,
    raw_text: str | None,
    segments: list | None,
    reasoning: str | None,
    differentiators: list | None,
    user_id: str,
) -> dict:
    """Merge a manual edit into the stored ICP and mark it source:'user'
    (supersede). Differentiators are replaced when provided."""
    client = _get_client(client_id)
    blob = {**_empty_icp(), **(client.get("detected_icp") or {})}

    if raw_text is not None:
        blob["raw_text"] = raw_text
    if segments is not None:
        blob["segments"] = segments
    if reasoning is not None:
        blob["reasoning"] = reasoning
    blob["source"] = "user"
    blob["edited_at"] = _now_iso()

    updates: dict = {"detected_icp": blob}
    if differentiators is not None:
        updates["differentiators"] = differentiators
    _persist(client_id, updates)
    logger.info("icp.user_updated", extra={"client_id": client_id})
    return {
        "detected_icp": blob,
        "differentiators": differentiators if differentiators is not None
        else client.get("differentiators"),
    }


# ── Rendering for the Blog Writer run snapshot (Option A bridge) ─────────────

def _render_icp_block(detected_icp: dict | None, max_segments: int = 3) -> str:
    """Platform-side mirror of nlp-api's _build_icp_text. raw_text is returned
    unwrapped so free-text clients get byte-identical snapshot text; structured
    segments render to a readable block."""
    if not detected_icp:
        return ""
    raw = (detected_icp.get("raw_text") or "").strip()
    if raw:
        return raw  # unwrapped — identical to the legacy icp_text value
    segments = detected_icp.get("segments") or []
    if not segments:
        return ""

    ordered = sorted(segments, key=lambda s: 0 if s.get("primary") else 1)
    lines = ["TARGET CUSTOMER PROFILES (write to these pain points and motivations):"]
    for seg in ordered[:max_segments]:
        label = seg.get("label") or "Customer"
        marker = " — PRIMARY" if seg.get("primary") else ""
        lines.append(f"  [{label}{marker}]")
        demo = seg.get("demographics") or {}
        if demo.get("description"):
            lines.append(f"    Demographics: {demo['description']}")
        if demo.get("situation"):
            lines.append(f"    Situation: {demo['situation']}")
        psy = seg.get("psychographics") or {}
        if psy.get("trigger"):
            lines.append(f"    Search trigger: {psy['trigger']}")
        if psy.get("fears"):
            lines.append(f"    Fears (address these): {'; '.join(psy['fears'])}")
        if psy.get("motivations"):
            lines.append(f"    Motivations (emphasise these): {'; '.join(psy['motivations'])}")
        if psy.get("buying_behavior"):
            lines.append(f"    Buying behaviour: {psy['buying_behavior']}")
        msg = seg.get("messaging") or {}
        if msg.get("tone"):
            lines.append(f"    Messaging tone: {msg['tone']}")
        if msg.get("hooks"):
            lines.append(f"    Headline hooks: {'; '.join(msg['hooks'])}")
        if msg.get("trust_signals"):
            lines.append(f"    Trust signals: {'; '.join(msg['trust_signals'])}")
    return "\n".join(lines)


def _render_diff_block(differentiators: list | None) -> str:
    """Mirror of nlp-api's differentiators block."""
    if not differentiators:
        return ""
    lines = ["DIFFERENTIATORS (weave these in naturally — include the mechanism, not just the claim):"]
    for d in differentiators:
        claim = (d or {}).get("claim", "")
        mechanism = (d or {}).get("mechanism", "")
        lines.append(f"  - {claim} (mechanism: {mechanism})")
    return "\n".join(lines)


def resolve_icp_text(client: dict) -> str:
    """Canonical ICP text for a run snapshot. Prefers the converged detected_icp
    (with differentiators folded in, per the chosen design); falls back to the
    legacy free-text icp_text column when detected_icp is unset."""
    icp = _render_icp_block(client.get("detected_icp"))
    diff = _render_diff_block(client.get("differentiators"))
    parts = [p for p in (icp, diff) if p]
    if parts:
        return "\n\n".join(parts)
    return client.get("icp_text") or ""
