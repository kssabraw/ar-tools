"""Citation endpoints — the paste-in citation list + liveness state.

The team pastes citation URLs (from vendor deliverables) in bulk; the weekly
`citation_check` sweep keeps the liveness state fresh. Any signed-in user can
manage the list (VAs order the citations).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["citations"])

_MAX_BULK = 500


class CitationBulkAddRequest(BaseModel):
    # Raw paste: URLs separated by newlines/whitespace/commas.
    urls_text: str


def normalize_citation_urls(raw: str, cap: int = _MAX_BULK) -> list[str]:
    """Parse a pasted blob into clean, deduped, capped http(s) URLs. Pure."""
    out: list[str] = []
    seen: set[str] = set()
    for token in raw.replace(",", "\n").split():
        u = token.strip().strip('"').strip("'")
        if not u:
            continue
        if "//" not in u:
            u = "https://" + u
        parsed = urlparse(u)
        # A real host needs a dot — filters prose words from a sloppy paste.
        if parsed.scheme not in ("http", "https") or "." not in parsed.netloc:
            continue
        key = u.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
        if len(out) >= cap:
            break
    return out


@router.get("/clients/{client_id}/citations")
async def list_citations(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    rows = (
        get_supabase()
        .table("client_citations")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .execute()
    ).data or []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"citations": rows, "counts": counts}


@router.post("/clients/{client_id}/citations", status_code=201)
async def add_citations(
    client_id: UUID, body: CitationBulkAddRequest, auth: dict = Depends(require_auth)
) -> dict:
    urls = normalize_citation_urls(body.urls_text)
    if not urls:
        raise HTTPException(status_code=422, detail="no_valid_urls")
    supabase = get_supabase()
    added = 0
    for u in urls:
        try:
            supabase.table("client_citations").upsert(
                {"client_id": str(client_id), "url": u},
                on_conflict="client_id,url",
                ignore_duplicates=True,
            ).execute()
            added += 1
        except Exception as exc:
            logger.warning("citations.add_failed", extra={"url": u, "error": str(exc)})
    return {"added": added, "parsed": len(urls)}


@router.delete("/citations/{citation_id}", status_code=204)
async def delete_citation(citation_id: UUID, auth: dict = Depends(require_auth)) -> None:
    get_supabase().table("client_citations").delete().eq("id", str(citation_id)).execute()


@router.post("/clients/{client_id}/citations/check")
async def check_now(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Enqueue an on-demand liveness check (deduped against an in-flight one)."""
    supabase = get_supabase()
    pending = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "citation_check")
        .eq("entity_id", str(client_id))
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data or []
    if pending:
        return {"job_id": pending[0]["id"], "status": "already_running"}
    job = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "citation_check",
                "entity_id": str(client_id),
                "payload": {"client_id": str(client_id)},
            }
        )
        .execute()
    ).data[0]
    return {"job_id": job["id"], "status": "enqueued"}
