"""Brand Voice module — orchestration + persistence (client-level, converged).

platform-api owns auth + persistence; the private nlp service runs the actual
crawl/scrape/3-LLM-call analysis (`/analyze-brand-voice`). The structured voice
is the canonical client asset (Option A) consumed by both the Local SEO nlp
service and — rendered into the run snapshot — the Blog Writer.

Provenance (`brand_voice.source`) enforces the supersede rule: a user-authored
voice is never clobbered by an auto-scan unless the caller passes `force=True`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from db.supabase_client import get_supabase

# Reuse the Local SEO transport + client→business mapping so the two modules
# can't drift on how a client row maps to the nlp payload.
from services.local_seo_service import _business_fields, _get_client, _post_nlp

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_blob() -> dict:
    return {
        "source": None,
        "raw_text": None,
        "current_voice": None,
        "recommended_voice": None,
        "recommended_accepted": None,
        "writer_execution_guide": None,
        "generated_at": None,
        "edited_at": None,
    }


def _persist(client_id: str, blob: dict) -> None:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .update({"brand_voice": blob, "updated_at": _now_iso()})
        .eq("id", client_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")


def get_brand_voice(client_id: str) -> dict:
    """Return the stored brand_voice blob (or None) for a client."""
    client = _get_client(client_id)
    return {"brand_voice": client.get("brand_voice")}


async def scan(client_id: str, force: bool, user_id: str) -> dict:
    """Run the app brand-voice analysis and persist it as source:'app'.

    Refuses to overwrite a user-authored voice unless `force` is set.
    Works without GBP: business identity falls back to the client row.
    """
    client = _get_client(client_id)
    existing = client.get("brand_voice") or {}

    if existing.get("source") == "user" and not force:
        # Manual content supersedes — don't silently clobber it.
        raise HTTPException(status_code=409, detail="brand_voice_user_authored")

    fields = _business_fields(client)
    payload = {
        "website_url": fields.get("website"),
        "business_name": fields.get("business_name") or "",
        "gbp_category": fields.get("gbp_category") or "",
    }

    result = await _post_nlp("/analyze-brand-voice", payload)
    engine = result.get("brand_voice") or {}

    blob = _empty_blob()
    blob.update(
        {
            "source": "app",
            "raw_text": None,  # app voice is structured; no freeform passthrough
            "current_voice": engine.get("current_voice"),
            "recommended_voice": engine.get("recommended_voice"),
            "recommended_accepted": engine.get("recommended_accepted"),
            "writer_execution_guide": engine.get("writer_execution_guide"),
            "generated_at": _now_iso(),
            "edited_at": existing.get("edited_at"),
        }
    )
    _persist(client_id, blob)
    logger.info(
        "brand_voice.scan_persisted",
        extra={"client_id": client_id, "pages_sampled": result.get("pages_sampled")},
    )
    return {"brand_voice": blob, "pages_sampled": result.get("pages_sampled")}


def update(
    client_id: str,
    *,
    raw_text: str | None,
    current_voice: dict | None,
    recommended_accepted: bool | None,
    user_id: str,
) -> dict:
    """Merge a manual edit into the stored voice and mark it source:'user'.

    This is the supersede path: a user-authored voice blocks future auto-scans.
    """
    client = _get_client(client_id)
    blob = {**_empty_blob(), **(client.get("brand_voice") or {})}

    if raw_text is not None:
        blob["raw_text"] = raw_text
    if current_voice is not None:
        blob["current_voice"] = current_voice
    if recommended_accepted is not None:
        blob["recommended_accepted"] = recommended_accepted

    blob["source"] = "user"
    blob["edited_at"] = _now_iso()

    _persist(client_id, blob)
    logger.info("brand_voice.user_updated", extra={"client_id": client_id})
    return {"brand_voice": blob}
