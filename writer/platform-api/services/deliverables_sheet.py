"""Deliverables Sheet Sync — auto-maintain each client's Google deliverables sheet.

The module (docs/modules/deliverables-sheet-sync-prd-v1_0.md) does two things,
per client, with no VA involvement:

* **Write** — when a task is marked Complete on the native task board, append a
  row to the client's deliverables sheet: column A = the type dropdown, B = the
  keyword, C = the deliverable as a titled hyperlink, D = the delivery date.
  The client-owned Status/Notes columns are never touched. The link resolves
  from the suite-published content the task is linked to (``source=content_run``
  → ``runs.published_doc_url``), else the first URL in the task's description,
  else the first task attachment (long-lived signed URL); a missing link still
  appends the row and flags it (never silently dropped).
* **Watch** — a poller on the shared scheduler reads each sheet's Notes column,
  diffs it against a stored snapshot, and alerts staff in Slack (via the
  notifications service) when a client leaves a note.

PACE surfaces the activity in its daily digest; it does not execute the sync —
the engine here is deterministic (no LLM in either path).

Layout: pure helpers first (tab/dropdown mapping, row assembly, notes diff —
unit-tested in tests/test_deliverables_sheet.py), then the impure hook, jobs,
and scheduler enqueue. Sheets I/O lives in `services/google_sheets.py` and is
called via ``asyncio.to_thread`` (googleapiclient is sync).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary (PRD §4/§6). The sheet's REAL dropdown list is read at runtime and
# matched against; these are the expected values + the offline fallback.
# ---------------------------------------------------------------------------
CONTENT_TAB_HEADER = "content type"   # A1 of the content tab
LINKS_TAB_HEADER = "links type"       # A1 of the links tab
NOTES_HEADER = "notes"

DEFAULT_CONTENT_TYPES = [
    "Blog Post", "Local Landing Page", "Service Page", "Location Page",
    "GBP Post", "Other", "Ecommerce",
]
DEFAULT_LINK_TYPES = [
    "Tiered Link Pyramid", "Niche Edit", "Guest Post", "Cloud Stack",
    "Google Stack", "Tier 2", "Citations", "Press Release", "Other Links",
]

# runs.content_type → Content-tab dropdown label.
_RUN_CONTENT_TYPE_MAP = {
    "blog_post": "Blog Post",
    "service_page": "Service Page",
    "location_page": "Location Page",
}

# Task-name keyword → Content-tab dropdown label (checked in order; first hit
# wins — more specific phrases first so "local landing page" doesn't fall
# through to a broader match).
_CONTENT_NAME_RULES: list[tuple[str, str]] = [
    ("local landing", "Local Landing Page"),
    ("landing page", "Local Landing Page"),
    ("service page", "Service Page"),
    ("location page", "Location Page"),
    ("gbp post", "GBP Post"),
    ("blog", "Blog Post"),
    ("ecommerce", "Ecommerce"),
]

# Task-name keyword → Links-tab dropdown label. "SEO NEO" first — SEO NEO is a
# link-building TOOL (tasks are named "SEO NEO — <diagram>", assigned to
# Minda/Ivy), and every SEO NEO run logs as Tiered Link Pyramid (owner rule).
_LINK_NAME_RULES: list[tuple[str, str]] = [
    ("seo neo", "Tiered Link Pyramid"),
    ("tiered link", "Tiered Link Pyramid"),
    ("niche edit", "Niche Edit"),
    ("guest post", "Guest Post"),
    ("cloud stack", "Cloud Stack"),
    ("google stack", "Google Stack"),
    ("tier 2", "Tier 2"),
    ("citation", "Citations"),
    ("press release", "Press Release"),
]

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Long-lived signed URL for attachment links written into the client-facing
# sheet (the task-attachments bucket is private; a short expiry would rot).
_ATTACHMENT_SIGN_SECONDS = 10 * 365 * 24 * 3600
_ATTACHMENTS_BUCKET = "task-attachments"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def extract_url(text: Optional[str]) -> Optional[str]:
    """First http(s) URL in a blob of text (the VA pastes the delivered link
    into the task description). Trailing punctuation stripped."""
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    return m.group(0).rstrip(".,;:!?")


def safe_cell(text: Optional[str]) -> str:
    """Neutralize formula injection for a plain text cell written USER_ENTERED:
    a value starting with = + or @ would execute as a formula in the client's
    sheet — prefix the standard apostrophe escape (renders as the bare text)."""
    clean = (text or "").strip()
    if clean and clean[0] in "=+@":
        return "'" + clean
    return clean


def hyperlink_formula(url: Optional[str], title: Optional[str]) -> str:
    """Column C: a titled hyperlink matching the VA's style. =HYPERLINK formula
    (written USER_ENTERED); bare URL when there's no title; "" when no link.
    Both arguments are quote-escaped so neither can break out of the formula
    string (titles come from task names / file names; URLs from descriptions)."""
    if not url:
        return ""
    # A single line only — a newline inside a formula literal breaks it.
    clean_title = " ".join((title or "").split())
    if not clean_title or clean_title == url:
        return url
    esc_url = url.replace('"', '""')
    esc_title = clean_title.replace('"', '""')
    return f'=HYPERLINK("{esc_url}", "{esc_title}")'


def format_sheet_date(d: date) -> str:
    """Human-readable date matching the sheet's existing style: 'July 12, 2026'."""
    return f"{d:%B} {d.day}, {d.year}"


def match_dropdown(options: list[str], desired: str, fallback_contains: str = "other") -> str:
    """Case-insensitive match of `desired` against the tab's REAL dropdown
    list; unmatched → the sheet's own 'Other'/'Other Links' entry (any option
    containing `fallback_contains`), else `desired` as-is (a foreign value in a
    validated cell shows a warning triangle but still lands — better than
    dropping the row). Every fallback is the caller's cue to log."""
    lowered = {opt.strip().lower(): opt for opt in options if opt and opt.strip()}
    hit = lowered.get(desired.strip().lower())
    if hit:
        return hit
    for key, opt in lowered.items():
        if fallback_contains in key:
            return opt
    return desired


def classify_tabs(headers_by_tab: dict[str, list[str]]) -> dict[str, str]:
    """Detect the logical tabs by their header row (robust to tab renames):
    A1 == 'Content Type' → content; A1 == 'Links Type' → links. Returns
    {'content': <tab title>, 'links': <tab title>} for those found."""
    out: dict[str, str] = {}
    for title, headers in headers_by_tab.items():
        first = (headers[0] if headers else "").strip().lower()
        if first == CONTENT_TAB_HEADER and "content" not in out:
            out["content"] = title
        elif first == LINKS_TAB_HEADER and "links" not in out:
            out["links"] = title
    return out


def notes_column_index(headers: list[str]) -> Optional[int]:
    """0-based index of the Notes column (rightmost 'Notes' header wins —
    content tab is A..F with Notes at F, links tab A..E with Notes at E)."""
    idx = None
    for i, h in enumerate(headers):
        if (h or "").strip().lower() == NOTES_HEADER:
            idx = i
    return idx


def pick_tab(task: dict) -> Optional[str]:
    """Which logical tab a completed task logs to, or None to skip.

    * ``source == 'content_run'`` → content (the producer's "Review & publish"
      task, linked to a published run — category-less but clearly content).
    * category content → content; link_building → links.
    * gbp_authority → content ONLY for GBP-post tasks (GBP Blast/Sniper etc.
      are ranking work, not client deliverables — PRD §6 note).
    * strategy / no category → skip (producer alert-tasks land here).
    """
    if (task.get("source") or "") == "content_run":
        return "content"
    # tasks.category is normally a task_categories KEY, but resolve_category_key
    # passes unmatched labels through as-is (imported/legacy tasks can carry
    # "Link Building") — normalize spaces so both spellings route.
    category = (task.get("category") or "").strip().lower().replace(" ", "_")
    name = (task.get("name") or "").lower()
    if category == "content":
        return "content"
    if category == "link_building":
        return "links"
    if category == "gbp_authority" and "gbp post" in name:
        return "content"
    return None


def map_content_type(task: dict, run_content_type: Optional[str] = None) -> str:
    """Desired Content-tab dropdown label for a task (linked run's content_type
    first, else task-name keywords, else 'Other')."""
    if run_content_type and run_content_type in _RUN_CONTENT_TYPE_MAP:
        return _RUN_CONTENT_TYPE_MAP[run_content_type]
    name = (task.get("name") or "").lower()
    for needle, label in _CONTENT_NAME_RULES:
        if needle in name:
            return label
    return "Other"


def map_link_type(task_name: Optional[str]) -> str:
    """Desired Links-tab dropdown label from the task name (SEO NEO override
    first — owner rule), else 'Other Links'."""
    name = (task_name or "").lower()
    for needle, label in _LINK_NAME_RULES:
        if needle in name:
            return label
    return "Other Links"


def build_row(type_value: str, keyword: Optional[str], url: Optional[str],
              title: Optional[str], when: date) -> list[str]:
    """The appended row, columns A..D only (Status/Notes stay client-owned)."""
    return [
        safe_cell(type_value),
        safe_cell(keyword),
        hyperlink_formula(url, title),
        format_sheet_date(when),
    ]


def note_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def diff_notes(old_snapshot: dict, cells: dict[str, str]) -> tuple[list[dict], dict]:
    """Compare the current Notes cells against the stored snapshot.

    `cells` maps "<tab>!<row>" → cell text (empty cells may be present or
    absent). Returns (alerts, new_snapshot): an alert for every non-empty cell
    whose hash differs from the snapshot (new note OR edited note — PRD §13
    'alert on any change'); the new snapshot holds hashes for every non-empty
    cell. A note that is *cleared* just drops out of the snapshot (no alert)."""
    alerts: list[dict] = []
    new_snapshot: dict[str, str] = {}
    for key, text in cells.items():
        clean = (text or "").strip()
        if not clean:
            continue
        h = note_hash(clean)
        new_snapshot[key] = h
        if old_snapshot.get(key) != h:
            alerts.append({"key": key, "text": clean, "hash": h})
    return alerts, new_snapshot


# ---------------------------------------------------------------------------
# Write side — task-Complete hook + the deliverables_log job
# ---------------------------------------------------------------------------
def on_task_completed(task: dict) -> None:
    """Called from ``task_service.complete_task`` (covers interactive complete,
    board drag-to-done, and producer auto-close — everything funnels there).
    Cheap DB-only work: gate, record the sync-log row (the idempotency guard),
    enqueue the Sheets write as a ``deliverables_log`` job. Never raises."""
    try:
        if not (settings.deliverables_sheet_enabled and settings.deliverables_write_enabled):
            return
        client_id = task.get("client_id")
        if not client_id or task.get("parent_task_id"):
            return  # internal-board tasks and subtasks are not deliverables
        if pick_tab(task) is None:
            return
        supabase = get_supabase()
        client = (
            supabase.table("clients")
            .select("id, deliverables_sheet_id")
            .eq("id", client_id).limit(1).execute().data
        )
        sheet_id = (client[0].get("deliverables_sheet_id") if client else None)
        if not sheet_id:
            return  # per-client enablement is implicit (PRD §11)
        # UNIQUE task_id = the reopen→re-complete guard: only the first insert
        # enqueues; a duplicate is a no-op — EXCEPT a previously FAILED row,
        # which re-completing retries (otherwise a transient Sheets error would
        # be a permanent dead end: failed jobs are terminal and the conflict
        # would swallow every later attempt). The failed→pending flip is
        # conditional, so concurrent completions race to exactly one enqueue.
        inserted = (
            supabase.table("deliverables_sync_log")
            .upsert(
                {"task_id": task["id"], "client_id": client_id,
                 "sheet_id": sheet_id, "status": "pending"},
                on_conflict="task_id", ignore_duplicates=True,
            )
            .execute().data
        )
        if not inserted:
            retried = (
                supabase.table("deliverables_sync_log")
                .update({"status": "pending", "error": None})
                .eq("task_id", task["id"]).eq("status", "failed")
                .execute().data
            )
            if not retried:
                return  # already written / pending — the true no-op
        supabase.table("async_jobs").insert(
            {"job_type": "deliverables_log", "entity_id": task["id"],
             "payload": {"task_id": task["id"], "client_id": client_id}}
        ).execute()
    except Exception as exc:
        logger.warning(
            "deliverables_hook_failed",
            extra={"task_id": task.get("id"), "error": str(exc)},
        )


def _linked_run(task: dict) -> Optional[dict]:
    """The published run a content_run producer task points at, or None."""
    if (task.get("source") or "") != "content_run" or not task.get("source_ref"):
        return None
    try:
        rows = (
            get_supabase().table("runs")
            .select("keyword, content_type, published_doc_url, published_url")
            .eq("id", task["source_ref"]).limit(1).execute().data
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("deliverables_run_lookup_failed",
                       extra={"task_id": task.get("id"), "error": str(exc)})
        return None


def _resolve_link(task: dict, run: Optional[dict]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(url, title, keyword) for a completed task, best source first:
    linked published run → description URL → first attachment (long signed
    URL). Any leg failing falls through to the next."""
    # 1) Suite-published content the task is linked to.
    if run:
        url = run.get("published_doc_url") or run.get("published_url")
        if url:
            return url, run.get("keyword"), run.get("keyword")
    # 2) First URL in the task description (the VA's paste-on-the-task flow).
    url = extract_url(task.get("description"))
    if url:
        return url, task.get("name"), None
    # 3) First attachment (private bucket → long-lived signed URL).
    try:
        supabase = get_supabase()
        atts = (
            supabase.table("task_attachments")
            .select("file_name, storage_path")
            .eq("task_id", task["id"])
            .order("created_at").limit(1).execute().data
        )
        if atts:
            signed = supabase.storage.from_(_ATTACHMENTS_BUCKET).create_signed_url(
                atts[0]["storage_path"], _ATTACHMENT_SIGN_SECONDS
            )
            signed_url = (signed or {}).get("signedURL") or (signed or {}).get("signedUrl")
            if signed_url:
                return signed_url, atts[0].get("file_name"), None
    except Exception as exc:
        logger.warning("deliverables_attachment_failed",
                       extra={"task_id": task.get("id"), "error": str(exc)})
    return None, None, None


def _sheet_tabs_and_options(sheet_id: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """({'content': tab, 'links': tab}, {logical: dropdown options}). Sync —
    call via to_thread. Dropdown read is best-effort (falls back to the
    expected vocabulary when a tab has no validation on A2)."""
    from services import google_sheets

    titles = google_sheets.list_tabs(sheet_id)
    headers_by_tab: dict[str, list[str]] = {}
    for t in titles[:5]:  # the template has 3 tabs; cap the reads
        rows = google_sheets.read_values(sheet_id, f"{google_sheets.a1_tab(t)}!A1:H1")
        headers_by_tab[t] = rows[0] if rows else []
    logical = classify_tabs(headers_by_tab)
    options: dict[str, list[str]] = {}
    for kind, default in (("content", DEFAULT_CONTENT_TYPES), ("links", DEFAULT_LINK_TYPES)):
        tab = logical.get(kind)
        opts: list[str] = []
        if tab:
            try:
                opts = google_sheets.read_dropdown_values(sheet_id, tab)
            except Exception:
                opts = []
        options[kind] = opts or default
    return logical, options


async def run_log_job(job: dict) -> None:
    """Async worker entry for ``deliverables_log``: resolve the row and append
    it to the client's sheet. Missing link → append anyway + flag (PRD §8)."""
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    task_id = payload.get("task_id")
    try:
        log_rows = (
            supabase.table("deliverables_sync_log")
            .select("*").eq("task_id", task_id).limit(1).execute().data
        )
        if not log_rows or log_rows[0].get("status") == "written":
            supabase.table("async_jobs").update(
                {"status": "complete", "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return
        log = log_rows[0]
        task = (
            supabase.table("tasks").select("*").eq("id", task_id).limit(1).execute().data
        )
        if not task:
            raise ValueError("task_not_found")
        task = task[0]
        client = (
            supabase.table("clients").select("id, name, deliverables_sheet_id")
            .eq("id", log["client_id"]).limit(1).execute().data
        )[0]
        sheet_id = client.get("deliverables_sheet_id")
        if not sheet_id:
            raise ValueError("client_sheet_unset")

        kind = pick_tab(task)
        if kind is None:  # category changed since enqueue
            supabase.table("deliverables_sync_log").update(
                {"status": "skipped", "error": "not_a_deliverable"}
            ).eq("id", log["id"]).execute()
            supabase.table("async_jobs").update(
                {"status": "complete", "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return

        run = _linked_run(task)
        url, title, keyword = _resolve_link(task, run)
        run_content_type = run.get("content_type") if run else None

        logical, options = await asyncio.to_thread(_sheet_tabs_and_options, sheet_id)
        tab = logical.get(kind)
        if not tab:
            raise ValueError(f"tab_not_found:{kind}")
        desired = (
            map_content_type(task, run_content_type) if kind == "content"
            else map_link_type(task.get("name"))
        )
        chosen = match_dropdown(options[kind], desired)
        if chosen.strip().lower() != desired.strip().lower():
            logger.info(  # tune the mapping rules from these (PRD §6)
                "deliverables_dropdown_fallback",
                extra={"task_id": task_id, "desired": desired, "chosen": chosen},
            )
        when = date.today()
        if task.get("completed_at"):
            try:
                when = datetime.fromisoformat(
                    task["completed_at"].replace("Z", "+00:00")
                ).date()
            except ValueError:
                pass
        row = build_row(chosen, keyword, url, title, when)
        from services import google_sheets  # lazy: keeps google deps import-safe

        await asyncio.to_thread(google_sheets.append_row, sheet_id, tab, row)

        supabase.table("deliverables_sync_log").update(
            {"status": "written", "tab": kind, "row_values": row,
             "link_url": url, "written_at": "now()", "error": None}
        ).eq("id", log["id"]).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "completed_at": "now()"}
        ).eq("id", job_id).execute()

        if not url:  # delivered-but-linkless: flagged, never silent (PRD §8)
            notifications.emit(
                client_id=log["client_id"],
                kind="deliverable_link_missing",
                title=f"Deliverable logged without a link — '{task.get('name')}'",
                summary=("The task completed with no resolvable link (no published "
                         "content, no URL in the description, no attachment). The sheet "
                         "row was appended with a blank link — fill it in."),
                severity="warning",
                payload={"task_id": task_id, "sheet_id": sheet_id},
            )
        logger.info("deliverables_row_written",
                    extra={"task_id": task_id, "tab": kind, "has_link": bool(url)})
    except Exception as exc:
        logger.warning("deliverables_log_failed",
                       extra={"task_id": task_id, "error": str(exc)})
        try:
            supabase.table("deliverables_sync_log").update(
                {"status": "failed", "error": str(exc)[:500]}
            ).eq("task_id", task_id).execute()
        except Exception:
            pass
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Watch side — the Notes poller
# ---------------------------------------------------------------------------
def enqueue_due_notes_scans() -> int:
    """Scheduler tick: enqueue a ``deliverable_notes_scan`` per client whose
    sheet is set and whose last scan is older than the interval. Skips clients
    with a scan already pending/running (the tick is much shorter than the
    interval). Returns the enqueue count; never raises."""
    if not (settings.deliverables_sheet_enabled and settings.deliverables_notes_watch_enabled):
        return 0
    try:
        supabase = get_supabase()
        clients = (
            supabase.table("clients").select("id, deliverables_sheet_id")
            .not_.is_("deliverables_sheet_id", "null").execute().data
        ) or []
        if not clients:
            return 0
        states = (
            supabase.table("deliverables_notes_state").select("client_id, scanned_at")
            .execute().data
        ) or []
        scanned = {s["client_id"]: s.get("scanned_at") for s in states}
        in_flight = (
            supabase.table("async_jobs").select("entity_id")
            .eq("job_type", "deliverable_notes_scan")
            .in_("status", ["pending", "running"]).execute().data
        ) or []
        busy = {j.get("entity_id") for j in in_flight}
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=settings.deliverables_notes_scan_interval_minutes
        )
        n = 0
        for c in clients:
            if c["id"] in busy:
                continue
            last = scanned.get(c["id"])
            if last:
                try:
                    if datetime.fromisoformat(last.replace("Z", "+00:00")) > cutoff:
                        continue
                except ValueError:
                    pass
            supabase.table("async_jobs").insert(
                {"job_type": "deliverable_notes_scan", "entity_id": c["id"],
                 "payload": {"client_id": c["id"]}}
            ).execute()
            n += 1
        return n
    except Exception as exc:
        logger.warning("deliverables_notes_enqueue_failed", extra={"error": str(exc)})
        return 0


def _read_notes_cells(sheet_id: str) -> dict[str, str]:
    """All Notes-column cells across the watched tabs, keyed "<tab>!<row>".
    Sync — call via to_thread."""
    from services import google_sheets

    titles = google_sheets.list_tabs(sheet_id)
    cells: dict[str, str] = {}
    for t in titles[:5]:
        rows = google_sheets.read_values(sheet_id, f"{google_sheets.a1_tab(t)}!A1:H500")
        if not rows:
            continue
        headers = rows[0]
        first = (headers[0] if headers else "").strip().lower()
        if first not in (CONTENT_TAB_HEADER, LINKS_TAB_HEADER):
            continue  # v1 watches the Content + Links tabs only
        col = notes_column_index(headers)
        if col is None:
            continue
        for i, row in enumerate(rows[1:], start=2):
            text = row[col] if len(row) > col else ""
            if (text or "").strip():
                cells[f"{t}!{i}"] = text
    return cells


def _row_context(sheet_id: str, key: str) -> str:
    """Best-effort one-liner describing the noted row (type · keyword · date)."""
    try:
        from services import google_sheets

        tab, row_num = key.rsplit("!", 1)
        vals = google_sheets.read_values(
            sheet_id, f"{google_sheets.a1_tab(tab)}!A{row_num}:D{row_num}"
        )
        if vals and vals[0]:
            return " · ".join(v for v in vals[0][:4] if (v or "").strip())
    except Exception:
        pass
    return key


async def run_notes_scan_job(job: dict) -> None:
    """Async worker entry for ``deliverable_notes_scan``: read the Notes
    column, diff against the snapshot, alert on new/changed notes, store the
    new snapshot + scanned_at (which also advances the interval gate)."""
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    try:
        client = (
            supabase.table("clients").select("id, name, deliverables_sheet_id")
            .eq("id", client_id).limit(1).execute().data
        )
        sheet_id = client[0].get("deliverables_sheet_id") if client else None
        if not sheet_id:
            raise ValueError("client_sheet_unset")
        name = client[0].get("name") or "client"

        state = (
            supabase.table("deliverables_notes_state").select("snapshot")
            .eq("client_id", client_id).limit(1).execute().data
        )
        # First scan of a sheet is a BASELINE (suite precedent: competitor
        # content watch's is_baseline): pre-existing notes are snapshotted, not
        # alerted — enabling the watcher on a lived-in sheet must not flood
        # Slack with months-old notes. The state row is deleted when a client's
        # sheet is switched (routers/deliverables PUT), re-baselining cleanly.
        is_baseline = not state
        old_snapshot = (state[0].get("snapshot") if state else None) or {}

        cells = await asyncio.to_thread(_read_notes_cells, sheet_id)
        alerts, new_snapshot = diff_notes(old_snapshot, cells)
        if is_baseline and alerts:
            logger.info("deliverable_notes_baseline",
                        extra={"client_id": client_id, "existing_notes": len(alerts)})
            alerts = []

        for a in alerts:
            context = await asyncio.to_thread(_row_context, sheet_id, a["key"])
            notifications.emit(
                client_id=client_id,
                kind="deliverable_note",
                title=f"{name} left a note on a deliverable",
                summary=f"{context}\n“{a['text'][:500]}”",
                severity="info",
                payload={"sheet_id": sheet_id, "cell": a["key"],
                         "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}"},
                dedupe_key=f"deliverable_note:{sheet_id}:{a['key']}:{a['hash']}",
            )

        supabase.table("deliverables_notes_state").upsert(
            {"client_id": client_id, "sheet_id": sheet_id,
             "snapshot": new_snapshot, "scanned_at": "now()", "updated_at": "now()"},
            on_conflict="client_id",
        ).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"alerts": len(alerts), "notes": len(new_snapshot)},
             "completed_at": "now()"}
        ).eq("id", job_id).execute()
        if alerts:
            logger.info("deliverable_notes_alerted",
                        extra={"client_id": client_id, "alerts": len(alerts)})
    except Exception as exc:
        logger.warning("deliverable_notes_scan_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def recent_note_stats(hours: int = 24) -> tuple[int, int]:
    """(new notes, distinct clients) in the window — the PACE digest line.
    Best-effort: (0, 0) on any failure."""
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = (
            get_supabase().table("notifications").select("client_id")
            .eq("kind", "deliverable_note").gte("created_at", since).execute().data
        ) or []
        return len(rows), len({r.get("client_id") for r in rows if r.get("client_id")})
    except Exception as exc:
        logger.warning("deliverables_note_stats_failed", extra={"error": str(exc)})
        return 0, 0


# ---------------------------------------------------------------------------
# Provisioning (PRD §5.5) — Drive files.copy of the master template
# ---------------------------------------------------------------------------
def provision_configured() -> bool:
    return bool(
        settings.deliverables_sheet_enabled
        and settings.deliverables_provision_enabled
        and settings.deliverables_template_sheet_id
        and settings.deliverables_drive_folder_id
    )


def enqueue_provision(client_id: str) -> bool:
    """Queue sheet creation for a client (client-create hook + admin route +
    a PACE-surfaced backfill). No-op when unconfigured. Never raises."""
    if not provision_configured():
        return False
    try:
        get_supabase().table("async_jobs").insert(
            {"job_type": "deliverables_sheet_provision", "entity_id": client_id,
             "payload": {"client_id": client_id}}
        ).execute()
        return True
    except Exception as exc:
        logger.warning("deliverables_provision_enqueue_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        return False


async def run_provision_job(job: dict) -> None:
    """Async worker entry for ``deliverables_sheet_provision``: copy the master
    template into the Shared Drive as "<client name>" and store the new sheet
    id. Idempotent — a client that already has a sheet is a clean no-op (never
    creates a second). Client-facing sharing stays manual in v1 (owner call)."""
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    try:
        rows = (
            supabase.table("clients").select("id, name, deliverables_sheet_id")
            .eq("id", client_id).limit(1).execute().data
        )
        if not rows:
            raise ValueError("client_not_found")
        client = rows[0]
        if client.get("deliverables_sheet_id"):
            supabase.table("async_jobs").update(
                {"status": "complete",
                 "result": {"skipped": "already_provisioned",
                            "sheet_id": client["deliverables_sheet_id"]},
                 "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return
        if not provision_configured():
            raise ValueError("provisioning_not_configured")

        from services import google_sheets

        copied = await asyncio.to_thread(
            google_sheets.copy_template,
            settings.deliverables_template_sheet_id,
            client.get("name") or "Client deliverables",
            settings.deliverables_drive_folder_id,
        )
        # Conditional write: only the first provisioner lands (a concurrent
        # create-hook + admin-backfill race must not flip the stored id under
        # a sheet that's already in use). The loser's copy is orphaned in
        # Drive — logged so it can be deleted by hand.
        claimed = (
            supabase.table("clients")
            .update({"deliverables_sheet_id": copied["id"]})
            .eq("id", client_id).is_("deliverables_sheet_id", "null")
            .execute().data
        )
        if not claimed:
            logger.warning(
                "deliverables_provision_lost_race",
                extra={"client_id": client_id, "orphan_sheet_id": copied["id"]},
            )
        supabase.table("async_jobs").update(
            {"status": "complete",
             "result": {"sheet_id": copied["id"], "url": copied.get("webViewLink")},
             "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("deliverables_sheet_provisioned",
                    extra={"client_id": client_id, "sheet_id": copied["id"]})
    except Exception as exc:
        logger.warning("deliverables_provision_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def validate_sheet(sheet_id: str) -> dict[str, Any]:
    """Admin-route helper: prove the service account can open `sheet_id` and
    report what it found (tabs + detected content/links tabs + dropdowns).
    Sync — the route calls it via to_thread. Raises on unreachable sheets."""
    logical, options = _sheet_tabs_and_options(sheet_id)
    return {
        "content_tab": logical.get("content"),
        "links_tab": logical.get("links"),
        "content_types": options.get("content", []),
        "link_types": options.get("links", []),
    }
