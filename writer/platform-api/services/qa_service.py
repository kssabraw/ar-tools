"""QA Agent — orchestration (qa-agent-plan Phases 0–2).

The impure half of QA: resolve a task's deliverable, gather the material
(fetch pages, read link-shared Google Sheets via CSV export, download .txt
attachments, one bounded LLM judgement for the map-embed assertion sentence),
hand everything to ``qa_signals``'s pure checks, persist a ``qa_reviews`` row,
and apply the outcome to the board.

Trigger: entry into the ``in_qa`` status (``on_task_status_change``, wired in
``task_service.update_task``; auto-advance Rule B already moves a task there
when its last work item is ticked, so QA runs automatically as work
completes) + on-demand via ``POST /tasks/{id}/qa``.

Outcomes (QA_Checklists.md is the grounding standard):
- ``fail``        → bounce to ``qa_fail_status`` + "QA fix: …" rework subtasks.
                    Those subtasks ARE work items, so ticking them all
                    auto-advances the task back to In QA — the rework loop
                    re-QAs itself with no human dispatch.
- ``pass``        → stay in In QA by default (``qa_pass_status`` can advance);
                    verdict recorded on the activity feed (+ optional notify).
- ``needs_human`` → stay put + a warning notification; QA never guesses.
- ``skipped``     → owner-ruled do-not-check / SerMaStr handoff; recorded.

Every entry point is best-effort — QA must never break the task board that
hosts it. Not freeze-gated: QA is observation, not content creation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import qa_signals as sig
from services import task_service

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; ARTools-QA/1.0)"


# ---------------------------------------------------------------------------
# Trigger + enqueue
# ---------------------------------------------------------------------------
def on_task_status_change(before: dict, after: dict, *, actor_id: Optional[str] = None) -> None:
    """update_task hook: a top-level task entering the trigger status enqueues
    one review. Best-effort, double-guarded (flag + status), idempotent."""
    try:
        if not settings.qa_enabled:
            return
        if after.get("parent_task_id") or after.get("completed"):
            return
        target = settings.qa_trigger_status
        if after.get("status_key") != target or before.get("status_key") == target:
            return
        enqueue_qa_review(after["id"], trigger="status")
    except Exception as exc:  # never break update_task
        logger.warning("qa_trigger_failed", extra={"task_id": after.get("id"), "error": str(exc)})


def enqueue_qa_review(task_id: str, *, trigger: str = "manual") -> Optional[str]:
    """Enqueue one qa_review job for a task; a pending/running review for the
    same task is reused (idempotent — a double drag doesn't double-review).

    Flap guard (hardening #3): an AUTOMATIC re-trigger within
    ``qa_recheck_cooldown_minutes`` of a PASSED review is skipped — a passed
    task stays in In QA, so dragging it out and back must not re-pay the
    review. Scoped to pass only: re-entry after a fail is the designed rework
    loop and a needs_human re-entry is the documented recovery path — both
    must re-run. The manual Run QA button always bypasses (trigger='manual')."""
    supabase = get_supabase()
    rows = (
        supabase.table("tasks").select("id, parent_task_id, completed")
        .eq("id", task_id).is_("deleted_at", "null").limit(1).execute()
    ).data
    if not rows or rows[0].get("parent_task_id"):
        return None
    if trigger == "status" and settings.qa_recheck_cooldown_minutes > 0:
        latest = (
            supabase.table("qa_reviews").select("verdict, created_at")
            .eq("task_id", str(task_id)).order("created_at", desc=True).limit(1).execute()
        ).data
        if latest and latest[0].get("verdict") == sig.PASS:
            from datetime import datetime, timedelta, timezone

            try:
                ts = datetime.fromisoformat(latest[0]["created_at"].replace("Z", "+00:00"))
                cutoff = datetime.now(timezone.utc) - timedelta(
                    minutes=settings.qa_recheck_cooldown_minutes
                )
                if ts >= cutoff:
                    logger.info("qa_recheck_cooldown_skip", extra={"task_id": task_id})
                    return None
            except (ValueError, KeyError):
                pass  # unparsable timestamp → don't block the review
    open_jobs = (
        supabase.table("async_jobs").select("id, payload")
        .eq("job_type", "qa_review").in_("status", ["pending", "running"]).execute()
    ).data or []
    for j in open_jobs:
        if (j.get("payload") or {}).get("task_id") == str(task_id):
            return j["id"]
    job = (
        supabase.table("async_jobs")
        .insert({
            "job_type": "qa_review",
            "entity_id": str(task_id),
            "payload": {"task_id": str(task_id), "trigger": trigger},
        })
        .execute()
    ).data[0]
    return job["id"]


# ---------------------------------------------------------------------------
# Gathering helpers (IO)
# ---------------------------------------------------------------------------
async def _fetch(url: str) -> Optional[str]:
    """Fetch a page/CSV; None on any failure (fail-open → needs_human)."""
    try:
        async with httpx.AsyncClient(
            timeout=settings.qa_fetch_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                return None
            return resp.text
    except Exception:
        return None


def _client_fields(client: Optional[dict]) -> dict[str, Any]:
    gbp = (client or {}).get("gbp") or {}
    return {
        "business_name": gbp.get("business_name") or (client or {}).get("name"),
        "address": gbp.get("address"),
        "phone": gbp.get("phone"),
        "domain": sig.domain_of((client or {}).get("website_url")),
        "service": gbp.get("gbp_category") or "",
    }


def _deliverable_urls(task: dict, subtasks: list[dict], attachments_text: str) -> list[str]:
    """URLs from the 'Deliverable links' subtask(s) (name + description), any
    .txt attachment content, then the task description — deduped, capped."""
    chunks: list[str] = []
    for s in subtasks:
        if sig.is_deliverable_subtask(s.get("name")):
            chunks.extend([s.get("name") or "", s.get("description") or ""])
    chunks.append(attachments_text)
    chunks.append(task.get("description") or "")
    urls = sig.extract_urls("\n".join(chunks))
    return urls[: settings.qa_max_urls_per_review]


def _txt_attachments_text(task_id: str) -> str:
    """Concatenated content of the task's .txt attachments (map-embed lists)."""
    try:
        from services.task_collab import ATTACHMENTS_BUCKET

        supabase = get_supabase()
        rows = (
            supabase.table("task_attachments").select("file_name, storage_path")
            .eq("task_id", task_id).execute()
        ).data or []
        parts: list[str] = []
        for r in rows:
            if not (r.get("file_name") or "").casefold().endswith(".txt"):
                continue
            try:
                blob = supabase.storage.from_(ATTACHMENTS_BUCKET).download(r["storage_path"])
                parts.append(blob.decode("utf-8", errors="replace"))
            except Exception:
                continue
        return "\n".join(parts)
    except Exception:
        return ""


async def _resolve_sheet_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    """Expand any link-shared Google Sheets into their listed URLs (public CSV
    export — QA_Checklists cross-cutting #1). Returns (page_urls, blocked)."""
    pages: list[str] = []
    blocked: list[str] = []
    for url in urls:
        sheet_id = sig.sheet_id_of(url)
        if not sheet_id:
            pages.append(url)
            continue
        csv_text = await _fetch(sig.sheet_csv_export_url(sheet_id))
        if csv_text is None:
            blocked.append(url)
            continue
        pages.extend(sig.urls_from_sheet_csv(csv_text))
    # dedupe, keep order, cap
    seen: set[str] = set()
    out = []
    for u in pages:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out, blocked


_ASSERTION_RE = re.compile(r'"present"\s*:\s*(true|false)', re.IGNORECASE)


async def _judge_assertion(page_text: str, business_name: str, service: str) -> tuple[Optional[bool], str]:
    """The one LLM judgement in QA (owner ruling, QA_Checklists §Map Embeds):
    does the page contain a grammatically-correct plain-English sentence
    asserting the client provides the service? Best-effort → (None, note)."""
    try:
        import anthropic

        api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0)
        clipped = page_text[:6000]
        msg = await api.messages.create(
            model=settings.qa_assertion_model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "You are a QA checker. Does the following page text contain a "
                    "grammatically correct plain-English sentence asserting that the "
                    f"business \"{business_name}\" provides "
                    f"{service or 'its service'} (an explicit 'X does/provides Y' "
                    "statement)? Reply with ONLY a JSON object: "
                    '{"present": true|false, "sentence": "<the sentence or empty>"}\n\n'
                    f"PAGE TEXT:\n{clipped}"
                ),
            }],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        m = _ASSERTION_RE.search(text)
        if not m:
            return None, "assertion judge returned no verdict"
        present = m.group(1).lower() == "true"
        sent = ""
        sm = re.search(r'"sentence"\s*:\s*"([^"]*)"', text)
        if sm:
            sent = sm.group(1)[:200]
        return present, (f"found: “{sent}”" if present and sent else "")
    except Exception as exc:
        return None, f"assertion judge unavailable ({type(exc).__name__})"


def _blog_markdown(run_id: str) -> Optional[str]:
    """The finished article markdown for a content run (sources_cited output —
    same source the publish path reads)."""
    try:
        rows = (
            get_supabase().table("module_outputs")
            .select("output_payload")
            .eq("run_id", run_id).eq("module", "sources_cited").eq("status", "complete")
            .order("attempt_number", desc=True).limit(1).execute()
        ).data
        if not rows:
            return None
        payload = rows[0].get("output_payload") or {}
        md = (payload.get("renderings") or {}).get("markdown") or ""
        if md.strip():
            return md
        sections = (payload.get("enriched_article") or {}).get("article") or payload.get("sections") or []
        parts = []
        for s in sections:
            if isinstance(s, dict):
                h = s.get("heading") or s.get("title")
                if h:
                    parts.append(f"## {h}")
                parts.append(s.get("content") or s.get("text") or "")
        joined = "\n\n".join(p for p in parts if p)
        return joined or None
    except Exception:
        return None


def _run_keyword(run_id: str) -> Optional[str]:
    try:
        rows = (
            get_supabase().table("runs").select("keyword").eq("id", run_id).limit(1).execute()
        ).data
        return (rows[0].get("keyword") if rows else None) or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The review itself
# ---------------------------------------------------------------------------
async def run_qa_review_job(job: dict) -> None:
    payload = job.get("payload") or {}
    task_id = payload.get("task_id")
    trigger = payload.get("trigger") or "status"
    if not task_id:
        raise ValueError("qa_review: missing task_id")

    supabase = get_supabase()
    rows = supabase.table("tasks").select("*").eq("id", task_id).limit(1).execute().data
    if not rows:
        logger.warning("qa_review_task_gone", extra={"task_id": task_id})
        return
    task = rows[0]
    client = None
    if task.get("client_id"):
        crows = (
            supabase.table("clients").select("id, name, website_url, gbp, page_structures")
            .eq("id", task["client_id"]).limit(1).execute()
        ).data
        client = crows[0] if crows else None
    fields = _client_fields(client)

    rubric = sig.rubric_for(task)
    checks: list[dict] = []
    urls: list[str] = []
    composite: Optional[float] = None

    if rubric == sig.RUBRIC_SKIP:
        verdict = {"verdict": sig.SKIPPED, "failed": [], "unverified": [], "advisories": []}
        narrative = "QA skipped — this deliverable type is not QA-checked (owner ruling)."
    elif rubric == sig.RUBRIC_HANDOFF:
        verdict = {"verdict": sig.SKIPPED, "failed": [], "unverified": [], "advisories": []}
        narrative = ("QA skipped — silo plans are a strategy judgement, not a presence check. "
                     "Ask SerMaStr for a review (QA_Checklists §Service Silo).")
    elif rubric == sig.RUBRIC_GENERIC:
        verdict = {"verdict": sig.NEEDS_HUMAN, "failed": [],
                   "unverified": ["No QA checklist covers this deliverable type"], "advisories": []}
        narrative = "QA needs a human — no checklist covers this task type (QA_Checklists Group C)."
    else:
        checks, urls, composite = await _run_rubric(rubric, task, fields, client)
        verdict = sig.build_verdict(checks)
        narrative = sig.narrative_of(rubric, verdict, urls)

    review = (
        supabase.table("qa_reviews")
        .insert({
            "task_id": str(task_id),
            "client_id": task.get("client_id"),
            "rubric": rubric,
            "verdict": verdict["verdict"],
            "composite": composite,
            "checks": checks,
            "issues": verdict["failed"],
            "urls": urls,
            "narrative": narrative,
            "trigger": trigger,
        })
        .execute()
    ).data[0]

    _apply_outcome(task, review, verdict)
    logger.info("qa_review_done", extra={
        "task_id": task_id, "rubric": rubric, "verdict": verdict["verdict"],
    })


async def _run_rubric(
    rubric: str, task: dict, fields: dict, client: Optional[dict]
) -> tuple[list[dict], list[str], Optional[float]]:
    """Gather material + run the rubric's pure checks. Returns
    (checks, urls_examined, composite_or_none)."""
    supabase = get_supabase()
    subtasks = (
        supabase.table("tasks").select("name, description")
        .eq("parent_task_id", task["id"]).is_("deleted_at", "null").execute()
    ).data or []
    keyword = sig.keyword_from_task(task)
    composite: Optional[float] = None

    if rubric == sig.RUBRIC_BLOG:
        md = _blog_markdown(task.get("source_ref") or "")
        kw = keyword or _run_keyword(task.get("source_ref") or "")
        if md is None:
            return ([sig._check("article", "Finished article located", None,
                                note="no completed sources_cited output for this run")], [], None)
        return (sig.check_blog_markdown(md, kw), [], None)

    raw_urls = _deliverable_urls(task, subtasks, _txt_attachments_text(task["id"]))

    if rubric == sig.RUBRIC_GBP_POSTS:
        # Post copy lives on the task: deliverable subtask description first,
        # else the task description.
        text = "\n".join(
            s.get("description") or "" for s in subtasks if sig.is_deliverable_subtask(s.get("name"))
        ).strip() or (task.get("description") or "").strip() or None
        return (sig.check_gbp_post(text, keyword), [], None)

    # Everything below examines external placements.
    pages, blocked = await _resolve_sheet_urls(raw_urls)
    if not pages:
        note = ("no deliverable URLs on the task — add a 'Deliverable links' subtask "
                "(QA_Checklists cross-cutting #1)")
        if blocked:
            note = f"deliverable sheet unreachable ({blocked[0]})"
        return ([sig._check("deliverable", "Deliverable link(s) located", None, note=note)],
                raw_urls, None)

    checks: list[dict] = []
    examined: list[str] = []

    if rubric == sig.RUBRIC_CITATIONS:
        sample = sig.sample_spread(pages, settings.qa_citation_sample)
        for url in sample:
            examined.append(url)
            html = await _fetch(url)
            if html is None:
                checks.append(sig._check("nap", f"NAP matches the client card ({url})", None,
                                         note="page unreachable/blocked"))
                continue
            checks.append(sig.check_citation_page(
                sig.visible_text_of(html), fields["business_name"],
                fields["address"], fields["phone"], url=url,
            ))
        return (checks, examined, None)

    if rubric in (sig.RUBRIC_GUEST_POST, sig.RUBRIC_NICHE_EDIT):
        url = pages[0]
        examined.append(url)
        html = await _fetch(url)
        if html is None:
            return ([sig._check("link_back", "Link back to the client's site", None,
                                note="page unreachable/blocked")], examined, None)
        return (sig.check_link_back(html, fields["domain"]), examined, None)

    if rubric == sig.RUBRIC_PRESS_RELEASE:
        url = pages[0]
        examined.append(url)
        html = await _fetch(url)
        if html is None:
            return ([sig._check("page", "Press release page reachable", None,
                                note="page unreachable/blocked")], examined, None)
        return (sig.check_press_release(
            html, keyword, fields["business_name"], fields["address"],
            fields["phone"], client_domain=fields["domain"],
        ), examined, None)

    if rubric == sig.RUBRIC_MAP_EMBEDS:
        for url in pages[: settings.qa_max_urls_per_review]:
            examined.append(url)
            html = await _fetch(url)
            if html is None:
                checks.append(sig._check("page", f"Embed page reachable ({url})", None,
                                         note="page unreachable/blocked"))
                continue
            assertion_ok, assertion_note = await _judge_assertion(
                sig.visible_text_of(html), fields["business_name"] or "", fields["service"],
            )
            page_checks = sig.check_map_embed_page(
                html, fields["business_name"], fields["address"], fields["phone"],
                assertion_ok=assertion_ok, assertion_note=assertion_note,
            )
            for c in page_checks:
                c["label"] = f"{c['label']} ({url})"
            checks.extend(page_checks)
        return (checks, examined, None)

    if rubric == sig.RUBRIC_PAGE:
        url = pages[0]
        examined.append(url)
        html = await _fetch(url)
        if html is None:
            return ([sig._check("page", "Posted page reachable", None,
                                note="page unreachable/blocked")], examined, None)
        checks = sig.check_website_page(html, fields["domain"], fields["business_name"])
        # Structural design fit vs the stored reference (QA_Checklists §Website
        # Pages Posted, "design fit — structural"). Page-type attribution is
        # heuristic, so a low score reads needs_human, never an auto-bounce.
        structural = _structural_fit(html, client)
        if structural is not None:
            composite, note = structural
            ok: Optional[bool] = True if composite >= settings.qa_structural_threshold else None
            checks.append(sig._check(
                "structural_fit", "Design fit (structural) vs reference page", ok,
                note=f"fidelity {composite:.0f}/100 — {note}",
            ))
        return (checks, examined, composite)

    return ([], [], None)


def _structural_fit(html: str, client: Optional[dict]) -> Optional[tuple[float, str]]:
    """Structural fidelity vs the client's stored reference page structure
    (service reference first — the most common posted type). None when no
    reference is stored."""
    try:
        from services import page_structure_eval as pse

        structures = (client or {}).get("page_structures") or {}
        ref = structures.get("service") or structures.get("local_landing") or structures.get("location")
        if not ref:
            return None
        outline = pse.extract_outline_from_html(html)
        result = pse.score_structural_fidelity(ref, outline)
        return float(result.get("composite") or 0.0), "; ".join(result.get("notes") or [])[:300]
    except Exception as exc:
        logger.warning("qa_structural_fit_failed", extra={"error": str(exc)})
        return None


# ---------------------------------------------------------------------------
# Outcome application
# ---------------------------------------------------------------------------
def _apply_outcome(task: dict, review: dict, verdict: dict) -> None:
    """Board effects per QA_Checklists: fail bounces + rework subtasks; pass
    stays (or advances when configured); needs_human/skipped stay put. Every
    outcome lands on the activity feed; notifications per severity."""
    v = verdict["verdict"]
    task_id = task["id"]
    try:
        task_service.record_activity(task_id, "qa_result", detail={
            "verdict": v, "rubric": review["rubric"], "review_id": review["id"],
            "issues": verdict.get("failed") or [],
        })
    except Exception as exc:
        logger.warning("qa_activity_failed", extra={"task_id": task_id, "error": str(exc)})

    try:
        if v == sig.FAIL:
            if settings.qa_fail_creates_subtasks and verdict.get("failed"):
                # Dedupe vs OPEN subtasks so repeated fails on the same check
                # never stack duplicate "QA fix" rows (hardening #1).
                open_names = [
                    s.get("name") or ""
                    for s in (
                        get_supabase().table("tasks").select("name, completed")
                        .eq("parent_task_id", task_id).is_("deleted_at", "null").execute()
                    ).data or []
                    if not s.get("completed")
                ]
                names = sig.new_rework_names(verdict["failed"], open_names)
                if names:
                    task_service.create_subtasks(task, names)
            if settings.qa_fail_status:
                task_service.update_task(task_id, {"status_key": settings.qa_fail_status})
        elif v == sig.PASS and settings.qa_pass_status:
            task_service.update_task(task_id, {"status_key": settings.qa_pass_status})
    except Exception as exc:
        logger.warning("qa_outcome_move_failed", extra={"task_id": task_id, "error": str(exc)})

    notify = (
        v == sig.FAIL
        or v == sig.NEEDS_HUMAN
        or (v == sig.PASS and settings.qa_notify_on_pass)
    )
    if not notify:
        return
    try:
        from services import notifications

        link = (
            f"/clients/{task['client_id']}/tasks?task={task_id}"
            if task.get("client_id") else "/my-tasks"
        )
        titles = {
            sig.FAIL: f"QA failed: '{task.get('name')}'",
            sig.NEEDS_HUMAN: f"QA needs a human: '{task.get('name')}'",
            sig.PASS: f"QA passed: '{task.get('name')}'",
        }
        # One notification per task+verdict+day (hardening #2): a task failing
        # three times in an afternoon is one Slack ping, not three. The unique
        # notifications.dedupe_key makes the duplicate insert a clean no-op.
        from datetime import datetime, timezone

        day = datetime.now(timezone.utc).date().isoformat()
        notifications.emit(
            client_id=task.get("client_id"),
            kind="qa_result",
            title=titles[v],
            summary=review.get("narrative"),
            severity="warning" if v in (sig.FAIL, sig.NEEDS_HUMAN) else "info",
            payload={"link": link, "task_id": task_id, "review_id": review["id"]},
            dedupe_key=f"qa:{task_id}:{v}:{day}",
        )
    except Exception as exc:
        logger.warning("qa_notify_failed", extra={"task_id": task_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Reads (router)
# ---------------------------------------------------------------------------
def list_reviews(task_id: str, limit: int = 20) -> list[dict]:
    return (
        get_supabase().table("qa_reviews").select("*")
        .eq("task_id", task_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []
