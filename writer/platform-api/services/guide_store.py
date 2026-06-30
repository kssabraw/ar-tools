"""Guides store — CRUD + idempotent default-seeding for the in-app Guides portal.

The DB `guides` table is the source of truth. seed_defaults() (run at startup)
inserts any default guide whose slug isn't present yet, so a fresh environment
comes up populated while edits/deletes made in-app are never clobbered.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services.guide_seed import DEFAULT_GUIDES

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"Start here", "Content", "Tracking", "Reporting", "Setup"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_guides(include_disabled: bool = False) -> list[dict]:
    """All guides, ordered for display. Enabled-only by default (public read);
    pass include_disabled=True for the admin editor."""
    supabase = get_supabase()
    q = supabase.table("guides").select("*")
    if not include_disabled:
        q = q.eq("enabled", True)
    rows = q.order("sort_order").order("title").execute().data or []
    return rows


def get_guide(slug: str) -> "dict | None":
    supabase = get_supabase()
    rows = supabase.table("guides").select("*").eq("slug", slug).limit(1).execute().data
    return rows[0] if rows else None


def create_guide(
    *, slug: str, title: str, body: str, summary: str = "",
    category: str = "Setup", icon: str = "BookOpen", sort_order: int = 0,
) -> dict:
    slug = (slug or "").strip().lower().replace(" ", "-")
    title = (title or "").strip()
    if not slug or not title:
        raise HTTPException(status_code=422, detail="slug_and_title_required")
    if category not in VALID_CATEGORIES:
        category = "Setup"
    supabase = get_supabase()
    try:
        row = (
            supabase.table("guides").insert({
                "slug": slug, "title": title, "body": body or "", "summary": summary or "",
                "category": category, "icon": icon or "BookOpen", "sort_order": sort_order,
            }).execute()
        ).data[0]
    except Exception as exc:
        # A duplicate slug is the likely cause; surface it cleanly.
        logger.warning("guide_create_failed", extra={"slug": slug, "error": str(exc)})
        raise HTTPException(status_code=409, detail="guide_slug_exists") from exc
    return row


def update_guide(guide_id: str, updates: dict) -> dict:
    allowed = {
        k: v for k, v in updates.items()
        if k in ("title", "body", "summary", "category", "icon", "sort_order", "enabled")
    }
    if "category" in allowed and allowed["category"] not in VALID_CATEGORIES:
        del allowed["category"]
    if not allowed:
        raise HTTPException(status_code=422, detail="no_valid_fields")
    allowed["updated_at"] = _now_iso()
    supabase = get_supabase()
    result = supabase.table("guides").update(allowed).eq("id", guide_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="guide_not_found")
    return result.data[0]


def delete_guide(guide_id: str) -> None:
    supabase = get_supabase()
    supabase.table("guides").delete().eq("id", guide_id).execute()


def seed_defaults() -> int:
    """Insert any default guide whose slug isn't already present. Idempotent —
    never overwrites an existing (possibly edited) guide. Returns how many were
    inserted. Best-effort: logs and returns 0 on failure (never blocks startup)."""
    supabase = get_supabase()
    try:
        existing = supabase.table("guides").select("slug").execute().data or []
        have = {r["slug"] for r in existing}
        to_insert = [
            {
                "slug": g["slug"], "title": g["title"], "category": g["category"],
                "icon": g["icon"], "summary": g.get("summary", ""), "body": g["body"],
                "sort_order": g.get("sort_order", 0),
            }
            for g in DEFAULT_GUIDES if g["slug"] not in have
        ]
        if not to_insert:
            return 0
        supabase.table("guides").insert(to_insert).execute()
        logger.info("guides_seeded", extra={"count": len(to_insert)})
        return len(to_insert)
    except Exception as exc:
        logger.warning("guides_seed_failed", extra={"error": str(exc)})
        return 0
