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
- ``fail``        → bounce to ``qa_fail_status`` + "Rework: …" rework subtasks.
                    The "Rework:" prefix is deliberate — "QA fix:" would trip
                    task_service's marker classifier (the "qa" token) and make
                    these NOT work items. As "Rework:" they ARE work items, so
                    ticking them ALL auto-advances the task back to In QA — the
                    rework loop re-QAs itself with no human dispatch.
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
    def _live_job_id() -> Optional[str]:
        jobs = (
            supabase.table("async_jobs").select("id")
            .eq("job_type", "qa_review").eq("entity_id", str(task_id))
            .in_("status", ["pending", "running"]).limit(1).execute()
        ).data or []
        return jobs[0]["id"] if jobs else None

    existing = _live_job_id()
    if existing:
        return existing
    try:
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
    except Exception:
        # The partial unique index (one LIVE qa_review per entity_id) is the
        # race arbiter — a concurrent enqueue won; return its job.
        return _live_job_id()


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


async def _broken_assets(asset_urls: list[str]) -> list[str]:
    """The subset of asset URLs that are HARD-dead (404/410) — the free half
    of the visual design-fit check. Mirrors citation_check's fail-open
    philosophy: bot-blocks/timeouts/5xx are NOT counted as broken (a CDN
    that dislikes our UA must not bounce a fine page); HEAD falls back to GET
    for servers that reject HEAD."""
    broken: list[str] = []
    try:
        async with httpx.AsyncClient(
            timeout=settings.qa_fetch_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            for url in asset_urls:
                try:
                    resp = await client.head(url)
                    if resp.status_code in (405, 501):
                        resp = await client.get(url)
                    if resp.status_code in (404, 410):
                        broken.append(url)
                except Exception:
                    continue  # unreachable ≠ dead — fail-open
    except Exception:
        return []
    return broken


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
    """URLs from the first-class 'Page URL to review' field, then the
    'Deliverable links' subtask(s) (name + description), any .txt attachment
    content, then the task description — deduped, capped. The explicit field is
    first so it wins for single-URL rubrics."""
    chunks: list[str] = []
    if (task.get("deliverable_url") or "").strip():
        chunks.append(task["deliverable_url"])
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
        # A Google Doc/Slides/Forms link is a draft container, not a live
        # placement — grading its JS-shell HTML would false-fail legit work,
        # so it routes to needs-human instead of the page checks.
        if sig.is_google_doc_url(url):
            blocked.append(url)
            continue
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
    if not (business_name or "").strip():
        return None, "no business name on file to assert against"
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


async def _synthesize_narrative(
    task_name: str, rubric: str, verdict: dict, checks: list[dict]
) -> Optional[str]:
    """SOP-grounded phrasing of a fail/needs_human review (Phase 3): one cheap
    call that explains what failed and what to do, citing the QA_Checklists /
    On-Page-Criteria section it's grounded in. The verdict and the check
    results are inputs it must restate, never recompute. Best-effort → None."""
    try:
        import anthropic

        from services.sop_library import qa_sops_text

        sops = qa_sops_text(settings.qa_sop_budget_chars)
        if not sops:
            return None
        check_lines = "\n".join(
            f"- [{'OK' if c.get('ok') else 'UNVERIFIED' if c.get('ok') is None else 'FAILED'}"
            f"{'' if c.get('blocking') else ', advisory'}] {c.get('label')}"
            + (f" — {c['note']}" if c.get("note") else "")
            for c in checks
        )
        api = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0)
        msg = await api.messages.create(
            model=settings.qa_narrative_model,
            max_tokens=settings.qa_narrative_max_tokens,
            system=(
                "You are the QA reviewer's writer. Given a deliverable's verdict and its "
                "deterministic check results, write a 2–4 sentence summary for the team: "
                "what failed (or couldn't be verified), what to do about it, and cite the "
                "SOP doc + section the standard comes from (e.g. 'QA_Checklists §GBP Posts'). "
                "NEVER change, soften, or second-guess the verdict or any check result — "
                "they are computed deterministically. No preamble, no markdown headings."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"TASK: {task_name}\nRUBRIC: {rubric}\n"
                    f"VERDICT: {verdict['verdict']}\nCHECKS:\n{check_lines}\n\n"
                    f"GROUNDING SOPS:\n{sops}"
                ),
            }],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception as exc:
        logger.warning("qa_narrative_failed", extra={"error": str(exc)})
        return None


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
    # The enqueue guard ran at transition time; the task may have been
    # completed or trashed while the job sat in the queue. Reviewing it then
    # would bounce a completed task's status (completed=true + In Progress on
    # the board) or grow subtasks under a trashed one — skip instead.
    if task.get("completed") or task.get("deleted_at"):
        logger.info("qa_review_task_closed_before_run", extra={"task_id": task_id})
        return
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
        # Phase 3: SOP-grounded phrasing for fail/needs_human — cites the
        # QA_Checklists / On-Page-Criteria standard so the rework guidance
        # names its source. Best-effort; the deterministic narrative stands
        # on any failure, and the verdict is NEVER the LLM's to change.
        # Gathering-only outcomes (no deliverable links / unreachable page)
        # skip the call — "add the links" needs no phrasing help, and that's
        # the most common result until the conventions stick.
        if (
            settings.qa_narrative_enabled
            and checks
            and verdict["verdict"] in (sig.FAIL, sig.NEEDS_HUMAN)
            and not sig.gathering_only(checks)
        ):
            llm_text = await _synthesize_narrative(task.get("name") or "", rubric, verdict, checks)
            if llm_text:
                narrative = llm_text

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
            note = (
                f"deliverable link can't be graded automatically ({blocked[0]}) — "
                "a Google Doc draft or an unreachable sheet; link the LIVE placement"
            )
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
        checks, composite = await _website_page_checks(
            html, url, fields, client, keyword=keyword, page_type=task.get("qa_page_type"),
        )
        return (checks, examined, composite)

    return ([], [], None)


async def _website_page_checks(
    html: str, url: str, fields: dict, client: Optional[dict],
    keyword: Optional[str] = None, page_type: Optional[str] = None,
) -> tuple[list[dict], Optional[float]]:
    """The website-page QA checks (QA_Checklists §Website Pages Posted) for a
    fetched page — shared by the ``website_page`` rubric (task deliverable, which
    supplies ``keyword`` + an optional ``page_type``) and the bare-URL
    ``review_url`` path. Returns (checks, composite_or_none)."""
    checks = sig.check_website_page(
        html, fields["domain"], fields["business_name"], keyword=keyword, url=url,
    )
    composite: Optional[float] = None
    # Structural design fit vs the stored reference. ``page_type`` (the task's
    # 'Page type' dropdown) picks the matching reference; unset falls back to
    # the service → local_landing → location priority. Attribution is heuristic,
    # so a low score reads needs_human, never an auto-bounce.
    structural = _structural_fit(html, client, page_type)
    if structural is not None:
        composite, note = structural
        ok: Optional[bool] = True if composite >= settings.qa_structural_threshold else None
        checks.append(sig._check(
            "structural_fit", "Design fit (structural) vs reference page", ok,
            note=f"fidelity {composite:.0f}/100 — {note}",
        ))
    else:
        # No usable reference page structure on file (none stored, or a thin one
        # with zero captured sections — scoring against which yields a
        # meaningless ~50/100 artifact). Report the real situation + the fix, as
        # an ADVISORY so it never bounces the page. Capturing a reference page
        # URL for this page type on the client form enables the check.
        checks.append(sig._check(
            "structural_fit", "Design fit (structural) vs reference page", None,
            blocking=False,
            note="no reference page structure on file for this page type — add a "
                 "reference page URL on the client form to enable this check",
        ))
    # Design fit — VISUAL. Two layers:
    # 1. Asset integrity (free, deterministic): a 404'd stylesheet or image
    #    breaks the render without needing a screenshot to prove it.
    assets = sig.asset_urls_of(html, url, cap=settings.qa_asset_check_cap)
    asset_list = assets["stylesheets"] + assets["images"]
    if asset_list:
        dead = await _broken_assets(asset_list)
        checks.append(sig._check(
            "asset_integrity", "Page assets load (CSS + images)", not dead,
            note=("dead: " + ", ".join(dead[:3]) + (" …" if len(dead) > 3 else ""))
            if dead else f"{len(asset_list)} asset(s) OK",
        ))
    # 2. Rendered screenshot judged by vision (DataForSEO capture — no Chromium
    #    in the image; only HIGH-confidence breakage bounces, everything
    #    uncertain is fail-open needs_human).
    if settings.qa_visual_enabled:
        from services import qa_visual

        checks.append(await qa_visual.visual_check(url))
    return checks, composite


def _structural_fit(
    html: str, client: Optional[dict], page_type: Optional[str] = None
) -> Optional[tuple[float, str]]:
    """Structural fidelity vs the client's stored reference page structure.

    ``page_type`` (the task's 'Page type' dropdown) selects which reference to
    compare against; when unset/invalid it falls back to service →
    local_landing → location priority. None when no usable reference is stored."""
    try:
        from services import page_structure_eval as pse

        structures = (client or {}).get("page_structures") or {}
        if page_type and page_type in sig.WEBSITE_PAGE_TYPES:
            ref = structures.get(page_type)
        else:
            ref = structures.get("service") or structures.get("local_landing") or structures.get("location")
        if not ref:
            return None
        # A reference with zero captured sections is not a usable baseline:
        # scoring against it produces a meaningless ~50/100 (the section &
        # heading-order dimensions score 0 for lack of anything to compare, the
        # rest default to full credit). Treat it as "no reference" so QA reports
        # the real situation (capture a reference) rather than a phantom score.
        if pse._section_count(pse._analysis_of(ref)) <= 0:
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
                # "Rework:" subtasks (new_rework_names), deduped vs still-open
                # ones so repeated fails don't stack duplicates (hardening #1).
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


# ---------------------------------------------------------------------------
# Readiness — plain-English "can QA run yet?" for the task drawer (no LLM)
# ---------------------------------------------------------------------------
_READINESS_LABELS = {
    sig.RUBRIC_PAGE: "Website page", sig.RUBRIC_BLOG: "Blog article",
    sig.RUBRIC_GBP_POSTS: "GBP post", sig.RUBRIC_CITATIONS: "Citations",
    sig.RUBRIC_GUEST_POST: "Guest post", sig.RUBRIC_NICHE_EDIT: "Niche edit",
    sig.RUBRIC_PRESS_RELEASE: "Press release", sig.RUBRIC_MAP_EMBEDS: "Map embeds",
    sig.RUBRIC_SKIP: "Not QA-checked", sig.RUBRIC_HANDOFF: "SerMaStr territory",
    sig.RUBRIC_GENERIC: "No checklist for this type",
}
# Public alias — the plain-English name of a rubric, reused by the /qa persona.
RUBRIC_LABELS = _READINESS_LABELS
_URL_RUBRICS = {
    sig.RUBRIC_PAGE, sig.RUBRIC_CITATIONS, sig.RUBRIC_GUEST_POST,
    sig.RUBRIC_NICHE_EDIT, sig.RUBRIC_PRESS_RELEASE, sig.RUBRIC_MAP_EMBEDS,
}


def assess_readiness(task_id: str) -> dict:
    """Can QA actually run on this task yet, and if not, what's missing — in
    plain English for an untrained VA. Resolves the rubric + inputs exactly as
    the review does (explicit fields → conventions → source auto-detect) and
    returns {rubric, rubric_label, ready, have, missing, autodetected, notes}."""
    supabase = get_supabase()
    rows = supabase.table("tasks").select("*").eq("id", task_id).limit(1).execute().data
    if not rows:
        return {"ready": False, "rubric": None, "rubric_label": "", "have": [],
                "missing": ["task not found"], "autodetected": {}, "notes": []}
    task = rows[0]
    rubric = sig.rubric_for(task)
    out = {"rubric": rubric, "rubric_label": _READINESS_LABELS.get(rubric, rubric),
           "ready": True, "have": [], "missing": [], "autodetected": {}, "notes": []}

    if rubric == sig.RUBRIC_SKIP:
        out["notes"].append("This deliverable type isn't QA-checked — nothing to set up.")
        return out
    if rubric == sig.RUBRIC_HANDOFF:
        out["ready"] = False
        out["notes"].append("This is a strategy judgement — ask SerMaStr, not QA.")
        return out
    if rubric == sig.RUBRIC_GENERIC:
        out["ready"] = False
        out["missing"].append("a rubric — pick one from the Rubric dropdown")
        out["notes"].append("No checklist matches this task yet. Pick a rubric so QA knows what to check.")
        return out

    if rubric in _URL_RUBRICS:
        url, src = _readiness_deliverable(task)
        if url:
            out["have"].append("page URL")
            if src == "auto":
                out["autodetected"]["url"] = url
        else:
            out["missing"].append("the page URL to review")

    if rubric == sig.RUBRIC_PAGE:
        kw, src = _readiness_keyword(task)
        if kw:
            out["have"].append("target keyword")
            if src == "auto":
                out["autodetected"]["keyword"] = kw
        else:
            out["missing"].append("the target keyword")
        # Client prerequisites (admin-set, once): flag rather than block.
        fields = _client_fields(_readiness_client(task))
        if not fields.get("business_name"):
            out["notes"].append(
                "No business name on file for this client — the name check can't run "
                "(an admin can set it on the client form)."
            )

    if rubric == sig.RUBRIC_BLOG:
        if task.get("source") == "content_run" and task.get("source_ref"):
            out["have"].append("the finished article")
        else:
            out["missing"].append("a linked content run (blog QA runs on a generated article)")

    if rubric == sig.RUBRIC_GBP_POSTS:
        subtasks = _readiness_subtasks(task["id"])
        copy = "\n".join(
            s.get("description") or "" for s in subtasks if sig.is_deliverable_subtask(s.get("name"))
        ).strip() or (task.get("description") or "").strip()
        if copy:
            out["have"].append("post copy")
        else:
            out["missing"].append("the post copy (in the task description or a 'Deliverable' subtask)")

    out["ready"] = not out["missing"]
    return out


def _readiness_subtasks(task_id: str) -> list[dict]:
    return (
        get_supabase().table("tasks").select("name, description")
        .eq("parent_task_id", task_id).is_("deleted_at", "null").execute()
    ).data or []


def _readiness_deliverable(task: dict) -> tuple[Optional[str], str]:
    """Resolve the deliverable URL + where it came from ('field' | 'scan' |
    'auto'). Explicit field → conventions (subtask/desc/attachments)."""
    if (task.get("deliverable_url") or "").strip():
        urls = sig.extract_urls(task["deliverable_url"])
        if urls:
            return urls[0], "field"
    subtasks = _readiness_subtasks(task["id"])
    urls = _deliverable_urls(task, subtasks, _txt_attachments_text(task["id"]))
    if urls:
        return urls[0], "scan"
    return None, ""


def _readiness_keyword(task: dict) -> tuple[Optional[str], str]:
    """Resolve the target keyword + where it came from ('set' via field/marker/
    name, or 'auto' from a linked content run)."""
    kw = sig.keyword_from_task(task)
    if kw:
        return kw, "set"
    if task.get("source") == "content_run" and task.get("source_ref"):
        run_kw = _run_keyword(task["source_ref"])
        if run_kw:
            return run_kw, "auto"
    return None, ""


def _readiness_client(task: dict) -> Optional[dict]:
    cid = task.get("client_id")
    if not cid:
        return None
    rows = (
        get_supabase().table("clients").select("id, name, website_url, gbp")
        .eq("id", cid).limit(1).execute()
    ).data
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Bare-URL QA (no task) — the "QA this page" path for the /qa chat surface
# ---------------------------------------------------------------------------
# The URL rubrics: a bare live URL can only be graded by a rubric that examines
# an external page (the blog/GBP-post rubrics read task/run content, not a URL).
# Ordered longest-phrase-first so "niche edit" beats "edit"-style partials.
_URL_RUBRIC_WORDS: list[tuple[str, str]] = [
    ("press release", sig.RUBRIC_PRESS_RELEASE),
    ("guest post", sig.RUBRIC_GUEST_POST),
    ("niche edit", sig.RUBRIC_NICHE_EDIT),
    ("map embed", sig.RUBRIC_MAP_EMBEDS),
    ("citation", sig.RUBRIC_CITATIONS),
    ("landing page", sig.RUBRIC_PAGE),
    ("service page", sig.RUBRIC_PAGE),
    ("location page", sig.RUBRIC_PAGE),
    ("website page", sig.RUBRIC_PAGE),
    ("web page", sig.RUBRIC_PAGE),
    ("page", sig.RUBRIC_PAGE),
]
_URL_RUBRICS = {
    sig.RUBRIC_PAGE, sig.RUBRIC_GUEST_POST, sig.RUBRIC_NICHE_EDIT,
    sig.RUBRIC_PRESS_RELEASE, sig.RUBRIC_CITATIONS, sig.RUBRIC_MAP_EMBEDS,
}


def resolve_url_rubric(text: Optional[str]) -> str:
    """Pick a URL rubric from free text ("QA this page", "check the guest post").
    Falls back to the configured default (``website_page``). Pure — accepts an
    explicit rubric key verbatim when the caller already resolved one."""
    t = (text or "").strip().casefold()
    if t in _URL_RUBRICS:
        return t
    for needle, rubric in _URL_RUBRIC_WORDS:
        if needle in t:
            return rubric
    return settings.qa_url_default_rubric


async def review_url(
    url: str, client: Optional[dict] = None, rubric: Optional[str] = None,
    keyword: Optional[str] = None,
) -> dict:
    """Run a QA review against a bare URL — no task, nothing persisted, no board
    effects. The "QA this page" path for the /qa chat. Returns the same shape a
    persisted ``qa_reviews`` row carries (rubric/verdict/composite/checks/issues/
    urls/narrative) so callers format it identically.

    ``client`` (optional) supplies NAP/domain/business-name for the NAP,
    link-back, and assertion checks; without it those read "could not verify"
    (needs_human), never a false pass. ``keyword`` (optional) enables the
    keyword-placement checks on the website-page/press-release rubrics.
    Unreachable page → needs_human."""
    rub = rubric if rubric in _URL_RUBRICS else resolve_url_rubric(rubric)
    fields = _client_fields(client)
    html = await _fetch(url)
    if html is None:
        checks = [sig._check("page", "Page reachable", None, note="page unreachable/blocked")]
        verdict = sig.build_verdict(checks)
        return _url_review_payload(rub, verdict, checks, [url], None,
                                   "The page couldn't be fetched (unreachable or bot-blocked) — "
                                   "a human should open it directly.")

    composite: Optional[float] = None
    if rub == sig.RUBRIC_PAGE:
        checks, composite = await _website_page_checks(html, url, fields, client, keyword=keyword)
    elif rub in (sig.RUBRIC_GUEST_POST, sig.RUBRIC_NICHE_EDIT):
        checks = sig.check_link_back(html, fields["domain"])
    elif rub == sig.RUBRIC_PRESS_RELEASE:
        checks = sig.check_press_release(
            html, keyword, fields["business_name"], fields["address"],
            fields["phone"], client_domain=fields["domain"],
        )
    elif rub == sig.RUBRIC_CITATIONS:
        checks = [sig.check_citation_page(
            sig.visible_text_of(html), fields["business_name"],
            fields["address"], fields["phone"], url=url,
        )]
    elif rub == sig.RUBRIC_MAP_EMBEDS:
        assertion_ok, assertion_note = await _judge_assertion(
            sig.visible_text_of(html), fields["business_name"] or "", fields["service"],
        )
        checks = sig.check_map_embed_page(
            html, fields["business_name"], fields["address"], fields["phone"],
            assertion_ok=assertion_ok, assertion_note=assertion_note,
        )
    else:  # defensive — resolve_url_rubric only yields URL rubrics
        checks, composite = await _website_page_checks(html, url, fields, client)

    verdict = sig.build_verdict(checks)
    narrative = sig.narrative_of(rub, verdict, [url])
    return _url_review_payload(rub, verdict, checks, [url], composite, narrative)


def _url_review_payload(rubric: str, verdict: dict, checks: list[dict],
                        urls: list[str], composite: Optional[float],
                        narrative: str) -> dict:
    return {
        "task_id": None,
        "rubric": rubric,
        "verdict": verdict["verdict"],
        "composite": composite,
        "checks": checks,
        "issues": verdict["failed"],
        "urls": urls,
        "narrative": narrative,
    }
