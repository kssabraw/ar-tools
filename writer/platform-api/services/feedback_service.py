"""Feedback Board service — CRUD for internal bug/wishlist items + comments.

Admin-only board (the router gates on require_admin); rows are reached with the
service-role key. Author names are resolved from `profiles.full_name` in a
single batched lookup per read, matching services/task_collab.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Status values that count as resolved — used to stamp/clear resolved_at.
_TERMINAL_STATUSES = {"done", "declined"}

_ITEM_COLUMNS = "id, kind, title, body, status, priority, labels, created_by, resolved_at, created_at, updated_at"


def clean_labels(labels: Optional[list[str]]) -> list[str]:
    """Trim, drop blanks, de-dupe (case-insensitive, keeping first spelling),
    cap each label at 60 chars and the list at 20. Pure."""
    if not labels:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in labels:
        label = (raw or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(label[:60])
    return out[:20]


def build_insert_row(fields: dict, created_by: Optional[str]) -> dict:
    """Normalize a create payload into the DB row shape. Pure."""
    return {
        "kind": fields["kind"],
        "title": (fields.get("title") or "").strip()[:200],
        "body": (fields.get("body") or "").strip() or None,
        "priority": fields.get("priority") or "medium",
        "labels": clean_labels(fields.get("labels")),
        "created_by": created_by,
    }


def build_update_patch(changes: dict) -> dict:
    """Normalize a partial update. Stamps/clears resolved_at when status crosses
    the terminal boundary, and always bumps updated_at. Pure."""
    patch = dict(changes)
    if "labels" in patch:
        patch["labels"] = clean_labels(patch["labels"])
    if "title" in patch and patch["title"] is not None:
        patch["title"] = str(patch["title"]).strip()[:200]
    if "body" in patch and patch["body"] is not None:
        patch["body"] = str(patch["body"]).strip() or None
    if "status" in patch:
        patch["resolved_at"] = "now()" if patch["status"] in _TERMINAL_STATUSES else None
    patch["updated_at"] = "now()"
    return patch


def _names_for(ids: list[Optional[str]]) -> dict[str, str]:
    """Batch-resolve profile ids → full_name (or 'Someone' when name is blank)."""
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    try:
        rows = (
            get_supabase().table("profiles").select("id, full_name").in_("id", list(set(wanted))).execute()
        ).data or []
    except Exception as exc:  # a name lookup must never break the board
        logger.warning("feedback.name_lookup_failed", extra={"error": str(exc)})
        return {}
    return {r["id"]: (r.get("full_name") or "Someone") for r in rows}


def _comment_counts(item_ids: list[str]) -> dict[str, int]:
    if not item_ids:
        return {}
    try:
        rows = (
            get_supabase().table("feedback_comments").select("item_id").in_("item_id", item_ids).execute()
        ).data or []
    except Exception as exc:
        logger.warning("feedback.comment_count_failed", extra={"error": str(exc)})
        return {}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["item_id"]] = counts.get(r["item_id"], 0) + 1
    return counts


def list_items(
    kind: Optional[str] = None,
    status: Optional[str] = None,
    include_resolved: bool = True,
) -> list[dict]:
    """List feedback items (newest first), with author name + comment count."""
    supabase = get_supabase()
    query = supabase.table("feedback_items").select(_ITEM_COLUMNS)
    if kind:
        query = query.eq("kind", kind)
    if status:
        query = query.eq("status", status)
    if not include_resolved:
        query = query.not_.in_("status", list(_TERMINAL_STATUSES))
    rows = (query.order("created_at", desc=True).execute()).data or []

    names = _names_for([r.get("created_by") for r in rows])
    counts = _comment_counts([r["id"] for r in rows])
    for r in rows:
        r["created_by_name"] = names.get(r.get("created_by")) if r.get("created_by") else None
        r["comment_count"] = counts.get(r["id"], 0)
    return rows


def get_item(item_id: str) -> Optional[dict]:
    """One item with its threaded comments (oldest first)."""
    supabase = get_supabase()
    rows = (
        supabase.table("feedback_items").select(_ITEM_COLUMNS).eq("id", item_id).execute()
    ).data or []
    if not rows:
        return None
    item = rows[0]
    comments = (
        supabase.table("feedback_comments")
        .select("id, item_id, author_id, body, created_at")
        .eq("item_id", item_id)
        .order("created_at", desc=False)
        .execute()
    ).data or []

    names = _names_for([item.get("created_by"), *[c.get("author_id") for c in comments]])
    item["created_by_name"] = names.get(item.get("created_by")) if item.get("created_by") else None
    for c in comments:
        c["author_name"] = names.get(c.get("author_id")) if c.get("author_id") else None
    item["comments"] = comments
    item["comment_count"] = len(comments)
    return item


def create_item(fields: dict, created_by: Optional[str] = None) -> dict:
    supabase = get_supabase()
    row = build_insert_row(fields, created_by)
    inserted = (supabase.table("feedback_items").insert(row).execute()).data[0]
    inserted["created_by_name"] = (
        _names_for([created_by]).get(created_by) if created_by else None
    )
    inserted["comment_count"] = 0
    return inserted


def update_item(item_id: str, changes: dict) -> Optional[dict]:
    """Apply a partial update. Stamps/clears resolved_at when status crosses the
    terminal boundary, and always bumps updated_at."""
    supabase = get_supabase()
    patch = build_update_patch(changes)

    rows = (
        supabase.table("feedback_items").update(patch).eq("id", item_id).execute()
    ).data or []
    if not rows:
        return None
    # Return it fully hydrated so the UI updates in place.
    return get_item(item_id)


def delete_item(item_id: str) -> bool:
    rows = (
        get_supabase().table("feedback_items").delete().eq("id", item_id).execute()
    ).data or []
    return bool(rows)


def add_comment(item_id: str, body: str, author_id: Optional[str] = None) -> Optional[dict]:
    supabase = get_supabase()
    exists = (
        supabase.table("feedback_items").select("id").eq("id", item_id).execute()
    ).data or []
    if not exists:
        return None
    inserted = (
        supabase.table("feedback_comments")
        .insert({"item_id": item_id, "author_id": author_id, "body": body.strip()})
        .execute()
    ).data[0]
    inserted["author_name"] = _names_for([author_id]).get(author_id) if author_id else None
    return inserted


def delete_comment(item_id: str, comment_id: str) -> bool:
    rows = (
        get_supabase().table("feedback_comments").delete()
        .eq("id", comment_id).eq("item_id", item_id).execute()
    ).data or []
    return bool(rows)
