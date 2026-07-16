"""Native task manager — collaboration (PRD §6.10, Phase 2).

Comments (markdown + @mentions), attachments (Supabase Storage bucket
``task-attachments``, signed URLs), watchers, duplicate, and the Trash reads.
Sits beside ``task_service`` (which owns core CRUD + activity) — this module
imports it, never the reverse.

Mentions are parsed against suite users (``profiles.full_name``): a comment
containing ``@Full Name`` or ``@Firstname`` (case-insensitive) mentions that
user, stores their id on the comment row, auto-adds them as a watcher, and
emits a ``task_mention`` notification through the shared notifications
service. Pure helpers are unit-tested.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import uuid4

from db.supabase_client import get_supabase
from services import notifications, task_service

logger = logging.getLogger(__name__)

ATTACHMENTS_BUCKET = "task-attachments"
SIGNED_URL_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def parse_mentions(body: str, candidates: list[dict]) -> list[str]:
    """Profile ids mentioned in a comment body. A candidate is mentioned when
    ``@<full name>`` or ``@<first name>`` appears (case-insensitive). Longer
    names are checked first so "@Ivy Lane" doesn't also credit a bare "Ivy"
    candidate spuriously — but an explicit first-name mention still works."""
    if not body or "@" not in body:
        return []
    low = body.casefold()
    found: list[str] = []
    for c in candidates:
        name = (c.get("full_name") or "").strip()
        if not name or not c.get("id"):
            continue
        tokens = {name.casefold(), name.split()[0].casefold()}
        if any(f"@{t}" in low for t in tokens):
            found.append(c["id"])
    # Preserve candidate order, dedupe.
    seen: set[str] = set()
    return [x for x in found if not (x in seen or seen.add(x))]


def safe_filename(name: Optional[str]) -> str:
    """A storage-key-safe version of an upload's filename."""
    base = (name or "upload").strip().replace("\\", "/").split("/")[-1] or "upload"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:120]


# ---------------------------------------------------------------------------
# Mention candidates (suite users; external 'client' viewers excluded)
# ---------------------------------------------------------------------------
def mention_candidates() -> list[dict]:
    rows = (
        get_supabase()
        .table("profiles")
        .select("id, full_name, role")
        .neq("role", "client")
        .execute()
    ).data or []
    return [{"id": r["id"], "full_name": r.get("full_name")} for r in rows if r.get("full_name")]


def profile_names(ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (
        get_supabase().table("profiles").select("id, full_name").in_("id", ids).execute()
    ).data or []
    return {r["id"]: r.get("full_name") or "someone" for r in rows}


# ---------------------------------------------------------------------------
# Watchers
# ---------------------------------------------------------------------------
def list_watchers(task_id: str) -> list[str]:
    rows = (
        get_supabase().table("task_watchers").select("user_id").eq("task_id", task_id).execute()
    ).data or []
    return [r["user_id"] for r in rows]


def add_watchers(task_id: str, user_ids: list[str]) -> None:
    """Idempotent watcher add (composite-PK upsert). Best-effort."""
    rows = [{"task_id": task_id, "user_id": uid} for uid in user_ids if uid]
    if not rows:
        return
    try:
        get_supabase().table("task_watchers").upsert(rows).execute()
    except Exception as exc:
        logger.warning("task_watch_add_failed", extra={"task_id": task_id, "error": str(exc)})


def remove_watcher(task_id: str, user_id: str) -> None:
    get_supabase().table("task_watchers").delete().eq("task_id", task_id).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
def list_comments(task_id: str) -> list[dict]:
    """Live comments, oldest first, with the author's display name attached."""
    rows = (
        get_supabase()
        .table("task_comments")
        .select("*")
        .eq("task_id", task_id)
        .is_("deleted_at", "null")
        .order("created_at")
        .execute()
    ).data or []
    names = profile_names(sorted({r["author_id"] for r in rows if r.get("author_id")}))
    for r in rows:
        r["author_name"] = names.get(r.get("author_id"))
    return rows


def create_comment(task: dict, author_id: str, body: str) -> dict:
    """Insert a comment: parse mentions, auto-watch author + mentioned, write
    the 'commented' activity, and notify (best-effort): mentioned users get a
    ``task_mention``; pre-existing watchers (beyond the author + the mentioned,
    who already heard) get one ``task_comment`` (PRD §6.11)."""
    watchers_before = list_watchers(task["id"])
    mentions = parse_mentions(body, mention_candidates())
    row = (
        get_supabase()
        .table("task_comments")
        .insert(
            {
                "task_id": task["id"],
                "author_id": author_id,
                "body": body,
                "mentions": mentions or None,
            }
        )
        .execute()
    ).data[0]
    task_service.record_activity(task["id"], "commented", actor_id=author_id)
    # First human touch starts a Not Started task (stage auto-advance Rule A).
    task_service.start_task_on_touch(task["id"], actor_id=author_id)
    add_watchers(task["id"], [author_id, *mentions])

    if mentions:
        try:
            author = profile_names([author_id]).get(author_id, "Someone")
            link = (
                f"/clients/{task['client_id']}/tasks?task={task['id']}"
                if task.get("client_id")
                else "/my-tasks"
            )
            # One personal notification per mentioned person → their own bell.
            for m in mentions:
                notifications.emit(
                    client_id=task.get("client_id"),
                    kind="task_mention",
                    title=f"{author} mentioned you on '{task.get('name')}'",
                    summary=body[:300],
                    severity="info",
                    payload={"link": link, "task_id": task["id"], "mentions": mentions},
                    recipient_profile_id=m,
                )
        except Exception as exc:  # a notify failure never fails the comment
            logger.warning("task_mention_notify_failed", extra={"task_id": task["id"], "error": str(exc)})

    other_watchers = [w for w in watchers_before if w != author_id and w not in mentions]
    if other_watchers:
        try:
            author = profile_names([author_id]).get(author_id, "Someone")
            link = (
                f"/clients/{task['client_id']}/tasks?task={task['id']}"
                if task.get("client_id")
                else "/my-tasks"
            )
            notifications.emit(
                client_id=task.get("client_id"),
                kind="task_comment",
                title=f"{author} commented on '{task.get('name')}'",
                summary=body[:300],
                severity="info",
                payload={"link": link, "task_id": task["id"], "watchers": other_watchers},
            )
        except Exception as exc:
            logger.warning("task_comment_notify_failed", extra={"task_id": task["id"], "error": str(exc)})

    row["author_name"] = profile_names([author_id]).get(author_id)
    return row


def update_comment(comment_id: str, author_id: str, body: str) -> Optional[dict]:
    """Edit a comment — authors may only edit their own. Returns None when the
    comment isn't theirs (or doesn't exist)."""
    supabase = get_supabase()
    rows = supabase.table("task_comments").select("*").eq("id", comment_id).is_("deleted_at", "null").limit(1).execute().data
    if not rows or rows[0].get("author_id") != author_id:
        return None
    updated = (
        supabase.table("task_comments")
        .update({"body": body, "edited_at": "now()"})
        .eq("id", comment_id)
        .execute()
    ).data[0]
    updated["author_name"] = profile_names([author_id]).get(author_id)
    return updated


def delete_comment(comment_id: str, author_id: str, *, is_admin: bool = False) -> bool:
    """Soft-delete a comment (own comments; admins may delete any)."""
    supabase = get_supabase()
    rows = supabase.table("task_comments").select("author_id").eq("id", comment_id).limit(1).execute().data
    if not rows:
        return False
    if rows[0].get("author_id") != author_id and not is_admin:
        return False
    supabase.table("task_comments").update({"deleted_at": "now()"}).eq("id", comment_id).execute()
    return True


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def list_attachments(task_id: str) -> list[dict]:
    """Attachment rows with fresh signed download URLs (private bucket)."""
    supabase = get_supabase()
    rows = (
        supabase.table("task_attachments")
        .select("*")
        .eq("task_id", task_id)
        .order("created_at")
        .execute()
    ).data or []
    for r in rows:
        try:
            signed = supabase.storage.from_(ATTACHMENTS_BUCKET).create_signed_url(
                r["storage_path"], SIGNED_URL_TTL_SECONDS
            )
            r["url"] = (signed or {}).get("signedURL") or (signed or {}).get("signedUrl")
        except Exception as exc:
            logger.warning("task_attachment_sign_failed", extra={"id": r.get("id"), "error": str(exc)})
            r["url"] = None
    return rows


def add_attachment(
    task: dict, *, file_name: str, data: bytes, mime_type: Optional[str], uploaded_by: str
) -> dict:
    """Upload to storage + record the row + write the 'attached' activity."""
    supabase = get_supabase()
    path = f"{task['id']}/{uuid4().hex}-{safe_filename(file_name)}"
    supabase.storage.from_(ATTACHMENTS_BUCKET).upload(
        path, data, {"content-type": mime_type or "application/octet-stream"}
    )
    row = (
        supabase.table("task_attachments")
        .insert(
            {
                "task_id": task["id"],
                "file_name": file_name,
                "storage_path": path,
                "mime_type": mime_type,
                "size_bytes": len(data),
                "uploaded_by": uploaded_by,
            }
        )
        .execute()
    ).data[0]
    task_service.record_activity(task["id"], "attached", actor_id=uploaded_by, detail={"file": file_name})
    # First human touch starts a Not Started task (stage auto-advance Rule A).
    task_service.start_task_on_touch(task["id"], actor_id=uploaded_by)
    add_watchers(task["id"], [uploaded_by])
    return row


def delete_attachment(attachment_id: str) -> bool:
    """Remove an attachment row + its storage object (best-effort on storage)."""
    supabase = get_supabase()
    rows = supabase.table("task_attachments").select("*").eq("id", attachment_id).limit(1).execute().data
    if not rows:
        return False
    try:
        supabase.storage.from_(ATTACHMENTS_BUCKET).remove([rows[0]["storage_path"]])
    except Exception as exc:
        logger.warning("task_attachment_remove_failed", extra={"id": attachment_id, "error": str(exc)})
    supabase.table("task_attachments").delete().eq("id", attachment_id).execute()
    return True


# ---------------------------------------------------------------------------
# Duplicate (PRD §6.1)
# ---------------------------------------------------------------------------
def duplicate_task(task_id: str, *, with_subtasks: bool, actor_id: Optional[str]) -> Optional[dict]:
    """Copy a task (name + fields; not completed, fresh audit) and optionally
    its live subtask checklist (all unchecked). Source/producer keys are NOT
    copied — a duplicate is a manual task."""
    original = task_service.get_task_detail(task_id)
    if not original:
        return None
    copy = task_service.create_task(
        f"{original['name']} (copy)",
        client_id=original.get("client_id"),
        section_id=original.get("section_id"),
        description=original.get("description"),
        assignee_gid=original.get("assignee_gid"),
        assignee_name=original.get("assignee_name"),
        category=original.get("category"),
        due_date=original.get("due_date"),
        start_date=original.get("start_date"),
        est_hours=original.get("est_hours"),
        sort_order=(original.get("sort_order") or 0) + 1,
        library_task_name=original.get("library_task_name"),
        created_by=actor_id,
    )
    if with_subtasks:
        names = [s.get("name") or "" for s in original.get("subtasks") or []]
        task_service.create_subtasks(copy, [n for n in names if n], created_by=actor_id)
    return copy


# ---------------------------------------------------------------------------
# Trash (PRD §6.1 / §14)
# ---------------------------------------------------------------------------
def list_trash(client_id: str) -> list[dict]:
    """A client's trashed tasks, newest first."""
    return (
        get_supabase()
        .table("tasks")
        .select("id, name, parent_task_id, deleted_at, section_id, assignee_name")
        .eq("client_id", client_id)
        .not_.is_("deleted_at", "null")
        .order("deleted_at", desc=True)
        .execute()
    ).data or []


def purge_task(task_id: str) -> None:
    """Permanent delete (admin-only at the router). Row cascades take
    subtasks, comments, attachment rows, activity, and watchers; storage
    objects are removed explicitly first (best-effort)."""
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("task_attachments").select("storage_path").eq("task_id", task_id).execute()
        ).data or []
        if rows:
            supabase.storage.from_(ATTACHMENTS_BUCKET).remove([r["storage_path"] for r in rows])
    except Exception as exc:
        logger.warning("task_purge_storage_failed", extra={"task_id": task_id, "error": str(exc)})
    supabase.table("tasks").delete().eq("id", task_id).execute()
