"""SOP / playbook store — CRUD + resolution for the reoptimization planner.

Two layers (per the chosen design):
  - agency-wide SOPs  (client_id IS NULL)  apply to every client
  - per-client SOPs   (client_id set)      override / augment for one client

`resolve_sops_text` merges both into a single token-budgeted block the Action
Plan's enrichment step hands to Claude. Content is parsed plain text — pasted
directly, or extracted from an uploaded document via /files/upload before insert.

Pure-ish: the CRUD calls touch Supabase; `_format_sops` / `_truncate` are pure
(unit-tested) so the budgeting logic is testable without a DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Categories accepted by the DB CHECK constraint (keep in sync with the migration).
VALID_CATEGORIES = {"general", "reoptimization", "link_building", "local", "content", "theory"}

# Soft cap on how much SOP text is fed to the enrichment LLM, so a large library
# can't blow the context window / cost. Agency + per-client share this budget;
# per-client wins when the budget is tight (it's appended last but kept whole).
_DEFAULT_BUDGET_CHARS = 24_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, limit: int) -> str:
    """Trim to a character budget on a word boundary, with an elision marker. Pure."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip() + " …[truncated]"


def _format_sops(agency: list[dict], client: list[dict], budget_chars: int) -> str:
    """Render the agency-wide + per-client SOP rows into one prompt block, within a
    character budget. Per-client SOPs are placed last (highest precedence) and kept
    whole; agency-wide text is truncated first if the budget is tight. Pure
    (unit-tested). Returns '' when there are no enabled SOPs."""
    def _block(rows: list[dict], heading: str) -> str:
        if not rows:
            return ""
        parts = [heading]
        for r in rows:
            title = (r.get("title") or "Untitled").strip()
            cat = (r.get("category") or "general").strip()
            body = (r.get("content") or "").strip()
            if not body:
                continue
            parts.append(f"### {title} [{cat}]\n{body}")
        return "\n\n".join(parts) if len(parts) > 1 else ""

    client_block = _block(client, "## CLIENT-SPECIFIC SOPs (take precedence)")
    # Reserve room for the per-client block, then give the rest to agency-wide.
    agency_budget = max(0, budget_chars - len(client_block))
    agency_block = _truncate(_block(agency, "## AGENCY-WIDE PLAYBOOK & THEORIES"), agency_budget)

    blocks = [b for b in (agency_block, client_block) if b]
    return "\n\n".join(blocks)


# --- impure: DB-backed CRUD + resolution -------------------------------------
def list_sops(client_id: "str | None", *, include_agency: bool = True) -> list[dict]:
    """List SOPs. With client_id None → agency-wide only. With a client_id →
    that client's SOPs plus (when include_agency) the agency-wide ones."""
    supabase = get_supabase()
    rows: list[dict] = []
    if client_id is None:
        rows = (
            supabase.table("sops").select("*")
            .is_("client_id", "null")
            .order("created_at", desc=True)
            .execute()
        ).data or []
    else:
        rows = (
            supabase.table("sops").select("*")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        if include_agency:
            agency = (
                supabase.table("sops").select("*")
                .is_("client_id", "null")
                .order("created_at", desc=True)
                .execute()
            ).data or []
            rows = rows + agency
    return rows


def create_sop(
    *, client_id: "str | None", title: str, content: str,
    category: str = "general", source: str = "paste",
) -> dict:
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        raise HTTPException(status_code=422, detail="title_and_content_required")
    if category not in VALID_CATEGORIES:
        category = "general"
    if source not in ("paste", "upload"):
        source = "paste"
    supabase = get_supabase()
    try:
        row = (
            supabase.table("sops").insert({
                "client_id": client_id,
                "title": title,
                "content": content,
                "category": category,
                "source": source,
            }).execute()
        ).data[0]
    except Exception as exc:
        logger.error("sop_create_failed", extra={"client_id": client_id, "error": str(exc)})
        raise HTTPException(status_code=502, detail="sop_create_failed") from exc
    return row


def update_sop(sop_id: str, updates: dict) -> dict:
    allowed = {k: v for k, v in updates.items() if k in ("title", "content", "category", "enabled")}
    if "category" in allowed and allowed["category"] not in VALID_CATEGORIES:
        del allowed["category"]
    if not allowed:
        raise HTTPException(status_code=422, detail="no_valid_fields")
    allowed["updated_at"] = _now_iso()
    supabase = get_supabase()
    result = supabase.table("sops").update(allowed).eq("id", sop_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="sop_not_found")
    return result.data[0]


def delete_sop(sop_id: str) -> None:
    supabase = get_supabase()
    supabase.table("sops").delete().eq("id", sop_id).execute()


def resolve_sops_text(client_id: "str | None", budget_chars: int = _DEFAULT_BUDGET_CHARS) -> str:
    """The merged, budgeted SOP prompt block for a client (agency-wide + the
    client's own enabled SOPs). Returns '' when there are no enabled SOPs — the
    planner uses that to skip enrichment entirely (keeping it free until a
    playbook exists). Best-effort: any read failure yields ''."""
    supabase = get_supabase()
    try:
        agency = (
            supabase.table("sops").select("title, content, category")
            .is_("client_id", "null").eq("enabled", True).execute()
        ).data or []
        client: list[dict] = []
        if client_id:
            client = (
                supabase.table("sops").select("title, content, category")
                .eq("client_id", client_id).eq("enabled", True).execute()
            ).data or []
    except Exception as exc:
        logger.warning("sop_resolve_failed", extra={"client_id": client_id, "error": str(exc)})
        return ""
    return _format_sops(agency, client, budget_chars)
