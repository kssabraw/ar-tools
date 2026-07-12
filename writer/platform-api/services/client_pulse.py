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
- **Narrative mode** (owner request 2026-07-12): the gathered facts are handed
  to one small LLM pass that writes a warm client email — what we did AND WHY
  it matters, what's next and why, a questions invitation to close. Hard
  grounding: the model only receives the already-filtered facts (so it cannot
  leak what it never sees) and is forbidden to invent results/metrics. Any
  failure (no key, API error, empty output) falls back to the deterministic
  bullet format — the pulse always exists.
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

# The always-on work the suite runs for EVERY client, EVERY week (owner ruling
# 2026-07-12). A light week is never "nothing done" — these modules genuinely
# run continuously, so a quiet itemized list is still a floor of real service.
# We never tell a client "no deliverables" / "nothing to report".
_ALWAYS_ON = [
    "Monitoring your Google search rankings and local map pack positions",
    "Tracking your visibility across AI search (ChatGPT, Google AI, and others)",
    "Keeping an eye on your competitors' rankings and new content",
    "Running optimization tests to keep your campaign on the cutting edge",
]


# ---------------------------------------------------------------------------
# Pure builders (unit-tested)
# ---------------------------------------------------------------------------
def week_start_of(today: date) -> date:
    """The Monday of ``today``'s week. Pure."""
    return today - timedelta(days=today.weekday())


def _norm_phrase(text: str) -> str:
    """Normalize for fuzzy blurb matching: casefold, drop parenthesized
    placeholder tokens ("(Number)") and digits, collapse whitespace. Pure."""
    import re

    t = re.sub(r"\([^)]*\)", " ", (text or "").casefold())
    t = re.sub(r"\d+", " ", t)
    return " ".join(t.split())


def match_blurb(task: dict, blurbs: dict) -> Optional[str]:
    """The central-library blurb for a task: exact match on its recorded
    library_task_name / name first, then a fuzzy pass — the library entry's
    normalized phrase appearing inside the task's normalized name ("(Number)
    Citations" → "150 Citations"; longest/most-specific entry wins, so
    "HyperLocal GBP Blast" beats "GBP Blast"). Pure."""
    for key in (task.get("library_task_name"), task.get("name")):
        if key and (blurb := blurbs.get(key.strip().casefold())):
            return blurb
    task_norm = _norm_phrase(task.get("name") or "")
    if not task_norm:
        return None
    best_key = None
    for key in blurbs:
        key_norm = _norm_phrase(key)
        if len(key_norm) >= 4 and key_norm in task_norm:
            if best_key is None or len(key_norm) > len(_norm_phrase(best_key)):
                best_key = key
    return blurbs.get(best_key) if best_key else None


def describe_task(task: dict, blurbs: Optional[dict] = None) -> str:
    """One itemized task line, enriched with its client-facing context: the
    task's own client_note wins (task-specific), else the central Task Library
    blurb for its type ("why it matters", exact or fuzzy match), else just the
    name. Pure. The INTERNAL description field is deliberately never used here."""
    name = (task.get("name") or "").strip()
    note = (task.get("client_note") or "").strip()
    if note:
        return f"{name} — {note}"
    if blurbs and (blurb := match_blurb(task, blurbs)):
        return f"{name} — why it matters: {blurb}"
    return name


def split_by_category(tasks: list[dict], itemize_keys: set, cat_labels: dict,
                      blurbs: Optional[dict] = None) -> tuple[list[str], list[str]]:
    """(itemized task lines, summary count lines) under the category filter.
    Unknown/missing categories are summarized (never itemized by accident). Pure."""
    itemized: list[str] = []
    counts: dict[str, int] = {}
    for t in tasks:
        cat = (t.get("category") or "").strip()
        if cat in itemize_keys:
            itemized.append(describe_task(t, blurbs))
        else:
            label = cat_labels.get(cat, "other")
            counts[label] = counts.get(label, 0) + 1
    summaries = [
        f"{n} {label} action{'s' if n != 1 else ''}"
        for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return itemized, summaries


def business_context(client: dict) -> str:
    """A short 'who this client is' block for the narrative model — makes the
    'why' copy specific to their business instead of generic. Pure, best-effort
    per field; empty string when nothing is known."""
    gbp = client.get("gbp") or {}
    lines = []
    industry = (gbp.get("gbp_category") or "").strip()
    place = (client.get("business_location") or gbp.get("address") or "").strip()
    if industry and place:
        lines.append(f"Business type: {industry}, based in {place}")
    elif industry:
        lines.append(f"Business type: {industry}")
    elif place:
        lines.append(f"Based in: {place}")
    try:
        from services.icp_service import resolve_icp_text

        icp = (resolve_icp_text(client) or "").strip()
        if icp:
            lines.append(f"Their ideal customer: {icp[:280]}")
    except Exception:
        pass
    return "\n".join(lines)


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
        # Never "no deliverables" — surface the always-on monitoring as the floor.
        lines.extend(f"• {a}" for a in _ALWAYS_ON)
    lines.extend(["", "On tap this week:"])
    if upcoming_items:
        lines.extend(_bulleted(upcoming_items))
    if upcoming_summaries:
        lines.extend(f"• {s} planned" for s in upcoming_summaries)
    if not (upcoming_items or upcoming_summaries):
        lines.append("• Continuing your campaign: ongoing rankings & AI-visibility "
                     "monitoring, competitor tracking, and optimization")
    lines.extend(["", f"— {agency_name}"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Narrative pass (LLM over the filtered facts; best-effort)
# ---------------------------------------------------------------------------
_NARRATIVE_SYSTEM = (
    "You write short weekly update emails from an SEO agency to its client — a busy "
    "small-business owner, not a marketer. Warm, plain-English, confident, zero jargon "
    "(explain work in terms of what it does for their business). STRICT GROUNDING: "
    "mention ONLY the work items provided; NEVER invent results, rankings, metrics, or "
    "work that isn't listed. NEVER tell the client there are 'no deliverables', "
    "'nothing to report', or that it was a 'quiet/slow week' — every week we are at "
    "minimum monitoring their rankings and AI-search visibility, watching competitors, "
    "and running optimization tests, so a light itemized week still leads with that "
    "always-on work as real, valuable service. Format: plain text only (no markdown, no emojis, no "
    "subject line). Start with exactly 'Hi [First name],' on its own line (the account "
    "manager personalizes it). Structure: one short paragraph on what was done last "
    "week and why it helps; one on what's planned this week and why; close by inviting "
    "questions (e.g. 'If you have any questions about any of this, just reply — happy "
    "to walk you through it.'). Sign off with the agency name provided. 120–190 words. "
    "Use the business context (industry, location, ideal customer) to make the 'why' "
    "specific to THEIR business. Where a work item carries a 'why it matters' or note, "
    "prefer that explanation over your own. FRAMING: always positive and proactive — "
    "diagnostic or repair work is 'proactive optimization/tune-up'; NEVER tell the "
    "client their rankings dropped or something is broken."
)


def narrative_facts(client_name: str, week_start: date, done_items: list[str],
                    done_summaries: list[str], published: list[str],
                    upcoming_items: list[str], upcoming_summaries: list[str],
                    agency_name: str, business: str = "") -> str:
    """The grounded fact sheet the narrative model may draw from — nothing else
    ever reaches it, so the category filter holds by construction. Pure."""
    prev = week_start - timedelta(days=7)
    lines = [
        f"Client: {client_name}",
        f"Last week: {prev.isoformat()} to {(week_start - timedelta(days=1)).isoformat()}",
        f"This week starts: {week_start.isoformat()}",
        f"Agency signature: {agency_name}",
    ]
    if business:
        lines.extend(["", "BUSINESS CONTEXT:", business])
    lines.extend([
        "",
        "ALWAYS-ON WORK (runs continuously every week — mention briefly, and LEAD "
        "with it when the itemized list below is light; NEVER say 'nothing was "
        "done', 'no deliverables', or 'quiet week'):",
    ])
    lines.extend(f"- {a}" for a in _ALWAYS_ON)
    lines.extend([
        "",
        "ITEMIZED WORK COMPLETED LAST WEEK:",
    ])
    lines.extend(f"- Published: {p}" for p in published)
    lines.extend(f"- {d}" for d in done_items)
    lines.extend(f"- {s} (summarize as ongoing authority/technical work)" for s in done_summaries)
    if not (published or done_items or done_summaries):
        lines.append("- (light week on itemized items — lead the recap with the "
                     "always-on monitoring above; frame it as steady, active service)")
    lines.append("")
    lines.append("PLANNED THIS WEEK:")
    lines.extend(f"- {u}" for u in upcoming_items)
    lines.extend(f"- {s} (summarize as ongoing authority/technical work)" for s in upcoming_summaries)
    if not (upcoming_items or upcoming_summaries):
        lines.append("- (continuing the monthly plan — ongoing rankings & "
                     "AI-visibility monitoring, competitor tracking, optimization)")
    return "\n".join(lines)


# Owner ruling (absolute): a client never reads these. The prompt forbids them,
# but prompts aren't guarantees — violates_never_say() enforces it in code: a
# narrative containing any of these is discarded and the caller falls back to
# the deterministic bullet body (which is clean by construction).
_NEVER_SAY = (
    "no deliverable", "nothing to report", "nothing was done",
    "no major deliverables", "quiet week", "slow week",
)


def violates_never_say(text: str) -> bool:
    """True when a narrative contains client-facing phrasing the owner has
    banned ("no deliverables to report", "quiet week", …). Pure."""
    low = (text or "").casefold()
    return any(p in low for p in _NEVER_SAY)


def narrate_pulse(facts: str) -> Optional[str]:
    """One small Claude call: facts → the client email. None on ANY failure
    (missing key, API error, empty text, banned phrasing) — the caller falls
    back to bullets."""
    if not (settings.pulse_narrative_enabled
            and (settings.anthropic_api_key or settings.openai_api_key or settings.gemini_api_key)):
        return None
    try:
        from services import report_llm

        # Runs on Anthropic with automatic OpenAI→Gemini fallback on a transient failure.
        text = report_llm.generate_text_sync(
            system=_NARRATIVE_SYSTEM,
            user=facts,
            model=settings.pulse_model,
            max_tokens=settings.pulse_max_tokens,
            log_tag="client_pulse",
        )
        if text and violates_never_say(text):
            # The model ignored the never-say rule — discard; bullets are clean.
            logger.warning("pulse_narrative_banned_phrase")
            return None
        return text or None
    except Exception as exc:
        logger.warning("pulse_narrative_failed", extra={"error": str(exc)})
        return None


# ---------------------------------------------------------------------------
# Impure gather + store
# ---------------------------------------------------------------------------
def build_pulse(client_id: str, today: Optional[date] = None) -> Optional[str]:
    """Build + upsert this week's pulse for one client; returns the body.
    None when the client is missing. Best-effort per source."""
    today = today or date.today()
    ws = week_start_of(today)
    sb = get_supabase()
    crow = (
        sb.table("clients")
        .select("id, name, gbp, business_location, detected_icp, differentiators, icp_text")
        .eq("id", client_id).limit(1).execute()
    ).data
    if not crow:
        return None
    client_name = crow[0].get("name") or "your campaign"
    business = business_context(crow[0])

    itemize = set(settings.pulse_itemize_categories or [])
    cat_labels = {}
    try:
        for c in (sb.table("task_categories").select("key, label").execute()).data or []:
            cat_labels[c["key"]] = c.get("label") or c["key"]
    except Exception:
        pass
    # Task Library blurbs — the team's own "why this work matters" per task type.
    blurbs: dict = {}
    try:
        for r in (sb.table("asana_task_library").select("name, client_blurb").execute()).data or []:
            if r.get("client_blurb"):
                blurbs[(r.get("name") or "").strip().casefold()] = r["client_blurb"].strip()
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
            .select("name, category, source, created_at, completed_at, client_note, library_task_name")
            .eq("client_id", client_id).eq("completed", True)
            .is_("deleted_at", "null").is_("parent_task_id", "null")
            .gte("completed_at", prev_start_iso).lt("completed_at", ws.isoformat())
            .execute()
        ).data or []
        rows = [r for r in rows if not is_import_stamped(r)]
        done_items, done_summaries = split_by_category(rows, itemize, cat_labels, blurbs)
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
            .select("name, category, status_key, due_date, client_note, library_task_name")
            .eq("client_id", client_id).eq("completed", False)
            .is_("deleted_at", "null").is_("parent_task_id", "null")
            .execute()
        ).data or []
        upcoming = [
            t for t in rows
            if (t.get("due_date") and ws.isoformat() <= t["due_date"] < week_end_iso)
            or t.get("status_key") in in_progress_keys
        ]
        upcoming_items, upcoming_summaries = split_by_category(upcoming, itemize, cat_labels, blurbs)
    except Exception as exc:
        logger.warning("pulse_upcoming_read_failed", extra={"client_id": client_id, "error": str(exc)})

    # Both renders every time (owner request — a toggleable view): the bullet
    # LIST is the at-a-glance scan + the always-works fallback; the NARRATIVE
    # is the client-ready email (LLM over the same filtered facts).
    agency = settings.client_report_agency_name
    body_list = render_pulse(client_name, ws, done_items, done_summaries, published,
                             upcoming_items, upcoming_summaries, agency)
    body = narrate_pulse(narrative_facts(
        client_name, ws, done_items, done_summaries, published,
        upcoming_items, upcoming_summaries, agency, business=business,
    )) or body_list
    try:
        sb.table("client_pulses").upsert(
            {"client_id": client_id, "week_start": ws.isoformat(), "body": body,
             "body_list": body_list, "created_at": "now()"},
            on_conflict="client_id,week_start",
        ).execute()
    except Exception as exc:
        logger.warning("pulse_store_failed", extra={"client_id": client_id, "error": str(exc)})
    return body


def latest_pulse(client_id: str) -> Optional[dict]:
    rows = (
        get_supabase().table("client_pulses")
        .select("body, body_list, week_start, created_at")
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
    clients = (
        sb.table("clients").select("id").eq("archived", False).execute()
    ).data or []
    generated = 0
    for c in clients:
        try:
            if build_pulse(c["id"], today):
                generated += 1
        except Exception as exc:
            logger.warning("pulse_generate_failed", extra={"client_id": c["id"], "error": str(exc)})
    return {"generated": generated, "clients": len(clients)}
