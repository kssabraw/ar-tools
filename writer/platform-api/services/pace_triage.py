"""PACE v1.4 Phase 10 — autonomous triage of new work (§4.10).

Nothing sits untriaged: a daily generator finds open tasks past the untriaged
grace window that are missing a due date / category / estimate and proposes ONE
`triage_task` Chase-Plan item per task, filling the gaps from **library data
only** — the §9 rule: no LLM guessing, an unfilled gap beats a hallucinated one.

- **Due date** — the last day of the task's month section (parsed from the
  section's "%B %Y" label); tasks outside a month section get no due proposal.
- **Category + estimate** — from the Task Library row matched by the task's
  `library_task_name` (or an exact casefold name match); the library's
  `default_category_name` is mapped label→key against `task_categories`.
  Non-library tasks get no category/estimate proposal (silently — the digest
  already counts untriaged work; a daily flag per oddball task would be noise).
- **Assignee** is NOT handled here — unassigned work is the §4.9 episode
  generator's job (it proposes `assign_task` with the full placement engine).

Pure `build_triage_updates` is unit-tested; the generator does batched reads.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services.pace_proposals import register_generator

logger = logging.getLogger(__name__)

_TRIAGE_PRIORITY = 40  # below the chase loop (50–80): hygiene, not fires


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def month_end_from_label(label: Optional[str]) -> Optional[str]:
    """'July 2026' → '2026-07-31'; anything unparseable → None. Pure."""
    if not label:
        return None
    try:
        parsed = datetime.strptime(label.strip(), "%B %Y")
    except ValueError:
        return None
    last = calendar.monthrange(parsed.year, parsed.month)[1]
    return date(parsed.year, parsed.month, last).isoformat()


def library_match(task: dict, library_by_name: dict) -> Optional[dict]:
    """The Task Library row a task derives from: its recorded
    `library_task_name` first, else an exact casefold name match. Pure."""
    for candidate in (task.get("library_task_name"), task.get("name")):
        if candidate and (row := library_by_name.get(candidate.strip().casefold())):
            return row
    return None


def build_triage_updates(task: dict, library_by_name: dict, cat_key_by_label: dict,
                         section_label: Optional[str]) -> dict:
    """The gap-fill updates for one task — only fields that are EMPTY, only
    values the library/section actually carry. Empty dict ⇒ nothing to triage.
    Pure."""
    updates: dict = {}
    if not task.get("due_date"):
        due = month_end_from_label(section_label)
        if due:
            updates["due_date"] = due
    lib = library_match(task, library_by_name)
    if lib:
        if not task.get("category"):
            key = cat_key_by_label.get((lib.get("default_category_name") or "").strip().casefold())
            if key:
                updates["category"] = key
        if task.get("est_hours") is None and lib.get("default_hours") is not None:
            updates["est_hours"] = lib["default_hours"]
    return updates


def triage_reason(task_name: str, updates: dict) -> str:
    parts = []
    if "due_date" in updates:
        parts.append(f"due {updates['due_date']}")
    if "category" in updates:
        parts.append(f"category {updates['category']}")
    if "est_hours" in updates:
        parts.append(f"est {updates['est_hours']}h")
    return f"Triage “{task_name}” — set {', '.join(parts)}"


# ---------------------------------------------------------------------------
# The registered generator
# ---------------------------------------------------------------------------
@register_generator
def triage_proposals(today: date) -> list[dict]:
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return []
    sb = get_supabase()
    cutoff = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    grace_days = settings.pace_untriaged_grace_days
    tasks = (
        sb.table("tasks")
        .select("id, client_id, section_id, name, library_task_name, due_date, category, est_hours, created_at")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .or_("due_date.is.null,category.is.null,est_hours.is.null")
        .not_.is_("client_id", "null")
        .execute()
    ).data or []
    # Grace window: don't triage brand-new tasks (a human may still be typing).
    def _old_enough(t: dict) -> bool:
        try:
            created = datetime.fromisoformat(str(t.get("created_at")).replace("Z", "+00:00"))
        except ValueError:
            return True
        return (cutoff - created).days >= grace_days
    tasks = [t for t in tasks if _old_enough(t)]
    if not tasks:
        return []

    library_by_name = {
        (r.get("name") or "").strip().casefold(): r
        for r in (sb.table("asana_task_library").select("name, default_hours, default_category_name")
                  .eq("active", True).execute()).data or []
    }
    cat_key_by_label = {
        (c.get("label") or "").strip().casefold(): c["key"]
        for c in (sb.table("task_categories").select("key, label").execute()).data or []
    }
    section_ids = sorted({t["section_id"] for t in tasks if t.get("section_id")})
    section_labels = {}
    if section_ids:
        for s in (sb.table("task_sections").select("id, name").in_("id", section_ids).execute()).data or []:
            section_labels[s["id"]] = s.get("name")
    client_names = {}
    client_ids = sorted({t["client_id"] for t in tasks})
    if client_ids:
        for c in (sb.table("clients").select("id, name").in_("id", client_ids).execute()).data or []:
            client_names[c["id"]] = c.get("name")

    proposals = []
    for t in tasks:
        updates = build_triage_updates(t, library_by_name, cat_key_by_label,
                                       section_labels.get(t.get("section_id")))
        if not updates:
            continue
        proposals.append({
            "action": "triage_task", "client_id": t["client_id"],
            "client_name": client_names.get(t["client_id"], "client"),
            "args": {"task_name": t.get("name") or "", **updates},
            "reason": triage_reason(t.get("name") or "", updates),
            "priority": _TRIAGE_PRIORITY, "kind": "triage", "perm": "triage_task",
        })
    return proposals
