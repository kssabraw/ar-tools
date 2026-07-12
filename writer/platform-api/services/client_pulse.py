"""Weekly Pulse — the copy-paste client update block (owner request 2026-07-12).

A short, client-friendly plain-text update per client — "done last week / on
tap this week" — generated weekly (and on demand) and shown on the client
workspace with a Copy button. **Staff deliver it** (paste into their own
email/message, personalize the greeting); nothing is ever auto-sent to a
client. Rows purge after `pulse_retention_days` (~2 weeks), so only the
current + prior pulse exist.

Content rules (owner rulings):
- **Category filter**: tasks whose category is in `pulse_itemize_categories`
  are itemized by name; everything else is summarized as a count per category
  ("4 Link Building actions") — internal line-item detail stays internal.
- **Published content** (blog runs + Local SEO pages) is always itemized — it's
  the client-visible deliverable.
- Deterministic, no LLM, no paid calls — the text is predictable and staff can
  edit it after pasting.
- Completed-task reads use the import-stamp filter (`pace_report`) so Asana
  import artifacts never read as "done last week". Pre-cutover honesty: task
  completions live in Asana until `native_tasks_enabled`, so the task portions
  fill in fully at cutover; the published-content portion is accurate today.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services.pace_report import is_import_stamped

logger = logging.getLogger(__name__)

_CONTENT_TYPE_LABELS = {
    "blog_post": "blog post",
    "service_page": "service page",
    "location_page": "location page",
}
_MAX_ITEMS_PER_SECTION = 8


# ---------------------------------------------------------------------------
# Pure builders (unit-tested)
# ---------------------------------------------------------------------------
def week_start_of(today: date) -> date:
    """The Monday of ``today``'s week. Pure."""
    return today - timedelta(days=today.weekday())


def split_by_category(tasks: list[dict], itemize_keys: set, cat_labels: dict) -> tuple[list[str], list[str]]:
    """(itemized task names, summary count lines) under the category filter.
    Unknown/missing categories are summarized (never itemized by accident). Pure."""
    itemized: list[str] = []
    counts: dict[str, int] = {}
    for t in tasks:
        cat = (t.get("category") or "").strip()
        if cat in itemize_keys:
            itemized.append((t.get("name") or "").strip())
        else:
            label = cat_labels.get(cat, "other")
            counts[label] = counts.get(label, 0) + 1
    summaries = [
        f"{n} {label} action{'s' if n != 1 else ''}"
        for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return itemized, summaries


def _bulleted(lines: list[str], done_suffix: str = "") -> list[str]:
    out = [f"• {line}{done_suffix}" for line in lines[:_MAX_ITEMS_PER_SECTION]]
    if len(lines) > _MAX_ITEMS_PER_SECTION:
        out.append(f"• …and {len(lines) - _MAX_ITEMS_PER_SECTION} more")
    return out


def render_pulse(client_name: str, week_start: date, done_items: list[str],
                 done_summaries: list[str], published: list[str],
                 upcoming_items: list[str], upcoming_summaries: list[str],
                 agency_name: str) -> str:
    """The copyable plain-text update. Pure. No markdown syntax — it pastes
    cleanly into any email/message; staff add the greeting."""
    prev_start = week_start - timedelta(days=7)
    lines = [
        f"Weekly update — {client_name}",
        f"({prev_start.strftime('%b %-d')} – {(week_start - timedelta(days=1)).strftime('%b %-d')} "
        f"recap · week of {week_start.strftime('%b %-d')} ahead)",
        "",
        "Done last week:",
    ]
    if published:
        lines.extend(_bulleted([f"Published: {p}" for p in published]))
    if done_items:
        lines.extend(_bulleted(done_items, " — completed"))
    if done_summaries:
        lines.extend(f"• {s} completed" for s in done_summaries)
    if not (published or done_items or done_summaries):
        lines.append("• Groundwork and ongoing optimization (no itemized deliverables closed this week)")
    lines.extend(["", "On tap this week:"])
    if upcoming_items:
        lines.extend(_bulleted(upcoming_items))
    if upcoming_summaries:
        lines.extend(f"• {s} planned" for s in upcoming_summaries)
    if not (upcoming_items or upcoming_summaries):
        lines.append("• Continuing the monthly plan — details to follow")
    lines.extend(["", f"— {agency_name}"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Impure gather + store
# ---------------------------------------------------------------------------
def build_pulse(client_id: str, today: Optional[date] = None) -> Optional[str]:
    """Build + upsert this week's pulse for one client; returns the body.
    None when the client is missing. Best-effort per source."""
    today = today or date.today()
    ws = week_start_of(today)
    sb = get_supabase()
    crow = (sb.table("clients").select("id, name").eq("id", client_id).limit(1).execute()).data
    if not crow:
        return None
    client_name = crow[0].get("name") or "your campaign"

    itemize = set(settings.pulse_itemize_categories or [])
    cat_labels = {}
    try:
        for c in (sb.table("task_categories").select("key, label").execute()).data or []:
            cat_labels[c["key"]] = c.get("label") or c["key"]
    except Exception:
        pass

    prev_start_iso = (ws - timedelta(days=7)).isoformat()
    week_end_iso = (ws + timedelta(days=7)).isoformat()

    # Done last week: completed tasks (import-stamp filtered) under the category filter.
    done_items: list[str] = []
    done_summaries: list[str] = []
    try:
        rows = (
            sb.table("tasks")
            .select("name, category, source, created_at, completed_at")
            .eq("client_id", client_id).eq("completed", True)
            .is_("deleted_at", "null").is_("parent_task_id", "null")
            .gte("completed_at", prev_start_iso).lt("completed_at", ws.isoformat())
            .execute()
        ).data or []
        rows = [r for r in rows if not is_import_stamped(r)]
        done_items, done_summaries = split_by_category(rows, itemize, cat_labels)
    except Exception as exc:
        logger.warning("pulse_done_read_failed", extra={"client_id": client_id, "error": str(exc)})

    # Published content last week (always itemized — the client-visible deliverable).
    published: list[str] = []
    try:
        runs = (
            sb.table("runs").select("keyword, content_type")
            .eq("client_id", client_id).eq("status", "complete")
            .gte("created_at", prev_start_iso).lt("created_at", ws.isoformat())
            .execute()
        ).data or []
        published.extend(
            f"“{r.get('keyword')}” ({_CONTENT_TYPE_LABELS.get(r.get('content_type'), 'content')})"
            for r in runs if r.get("keyword")
        )
    except Exception:
        pass
    try:
        pages = (
            sb.table("local_seo_pages").select("page_title, keyword")
            .eq("client_id", client_id).is_("deleted_at", "null")
            .gte("created_at", prev_start_iso).lt("created_at", ws.isoformat())
            .execute()
        ).data or []
        published.extend(
            f"“{p.get('page_title') or p.get('keyword')}” (local page)" for p in pages
        )
    except Exception:
        pass

    # On tap this week: open tasks due this week + work already in progress.
    upcoming_items: list[str] = []
    upcoming_summaries: list[str] = []
    try:
        statuses = (sb.table("task_statuses").select("key, category").execute()).data or []
        in_progress_keys = {s["key"] for s in statuses if s.get("category") == "in_progress"}
        rows = (
            sb.table("tasks")
            .select("name, category, status_key, due_date")
            .eq("client_id", client_id).eq("completed", False)
            .is_("deleted_at", "null").is_("parent_task_id", "null")
            .execute()
        ).data or []
        upcoming = [
            t for t in rows
            if (t.get("due_date") and ws.isoformat() <= t["due_date"] < week_end_iso)
            or t.get("status_key") in in_progress_keys
        ]
        upcoming_items, upcoming_summaries = split_by_category(upcoming, itemize, cat_labels)
    except Exception as exc:
        logger.warning("pulse_upcoming_read_failed", extra={"client_id": client_id, "error": str(exc)})

    body = render_pulse(client_name, ws, done_items, done_summaries, published,
                        upcoming_items, upcoming_summaries,
                        settings.client_report_agency_name)
    try:
        sb.table("client_pulses").upsert(
            {"client_id": client_id, "week_start": ws.isoformat(), "body": body,
             "created_at": "now()"},
            on_conflict="client_id,week_start",
        ).execute()
    except Exception as exc:
        logger.warning("pulse_store_failed", extra={"client_id": client_id, "error": str(exc)})
    return body


def latest_pulse(client_id: str) -> Optional[dict]:
    rows = (
        get_supabase().table("client_pulses")
        .select("body, week_start, created_at")
        .eq("client_id", client_id).order("week_start", desc=True).limit(1).execute()
    ).data
    return rows[0] if rows else None


def run_weekly_pulses(today: Optional[date] = None) -> dict:
    """Generate every client's pulse on `pulse_weekday` + purge expired rows.
    Self-gated; best-effort per client."""
    if not settings.pulse_enabled:
        return {"generated": 0, "reason": "disabled"}
    today = today or date.today()
    if today.weekday() != settings.pulse_weekday:
        return {"generated": 0, "reason": "not_due"}
    sb = get_supabase()
    # Retention: the owner's 2-week rule.
    try:
        cutoff = (today - timedelta(days=settings.pulse_retention_days)).isoformat()
        sb.table("client_pulses").delete().lt("week_start", cutoff).execute()
    except Exception as exc:
        logger.warning("pulse_purge_failed", extra={"error": str(exc)})
    clients = (sb.table("clients").select("id").execute()).data or []
    generated = 0
    for c in clients:
        try:
            if build_pulse(c["id"], today):
                generated += 1
        except Exception as exc:
            logger.warning("pulse_generate_failed", extra={"client_id": c["id"], "error": str(exc)})
    return {"generated": generated, "clients": len(clients)}
