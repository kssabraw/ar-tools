"""Organic Rank Analysis report — orchestration + narrative + Doc publish.

The per-keyword deep-dive deliverable (the organic analogue of the Maps Local
Rank Analysis report). Wraps the deterministic assembler in
`services/rank_analysis.py` with:
  - a Claude Sonnet narrative that follows a strict observational template
    (analyze only — never prescribe; the actionable layer is deterministic),
  - the deterministically-computed gap-to-close **work order**, rendered from
    `report_analytics` (the organic analog of the geo-grid octant pins — data we
    present, not advice the LLM invents),
  - persistence to `rank_keyword_reports` + a per-keyword Google Doc.

Triggered as an `async_jobs` job ('rank_keyword_report'): on-demand per keyword,
automatically when a rank-drop alert opens, and weekly per keyword. Reuses the
latest stored SERP snapshot — no fresh capture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import rank_analysis
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# LLM snapshot + prompt (mirrors maps_report's observational discipline)
# ----------------------------------------------------------------------------
def build_llm_snapshot(analysis: dict) -> dict:
    """The trimmed view of the deterministic analysis handed to the LLM. Drops
    the work order (rendered deterministically, not narrated) and clips the
    top-10 to the fields the narrative tables need."""
    landscape = analysis.get("landscape") or {}
    top = [
        {k: r.get(k) for k in (
            "position", "domain", "is_client", "targeted", "topical_focus",
            "url_rating", "referring_domains")}
        for r in (landscape.get("top_results") or [])
    ]
    return {
        "keyword": analysis.get("keyword"),
        "client_name": analysis.get("client_name"),
        "canonical_url": analysis.get("canonical_url"),
        "index_status": analysis.get("index_status"),
        "market": analysis.get("market"),
        "trajectory": analysis.get("trajectory"),
        "winnability": analysis.get("winnability"),
        "forecast": {k: (analysis.get("forecast") or {}).get(k) for k in (
            "current_position", "trend_per_week", "projected_position_30d",
            "projected_position_90d", "confidence", "clicks_per_month_now",
            "clicks_per_month_90d", "clicks_source", "value_per_month_now",
            "value_per_month_90d")},
        "authority_gap": analysis.get("authority_gap"),
        "landscape": {
            "has_snapshot": landscape.get("has_snapshot"),
            "client_rank": landscape.get("client_rank"),
            "client_page_count": landscape.get("client_page_count"),
            "query_intent": landscape.get("query_intent"),
            "local_intent": landscape.get("local_intent"),
            "aio_present": landscape.get("aio_present"),
            "aio_sources": [s.get("domain") for s in (landscape.get("aio_sources") or []) if s.get("domain")][:8],
            "targeted_count": landscape.get("targeted_count"),
            "generalist_count": landscape.get("generalist_count"),
            "client_topical_focus": landscape.get("client_topical_focus"),
            "top_results": top,
        },
        "competitor_breakdown": analysis.get("competitor_breakdown"),
        "what_changed": _trim_what_changed(analysis.get("what_changed")),
        "drop_classification": analysis.get("drop_classification"),
    }


def _trim_what_changed(wc: Optional[dict]) -> Optional[dict]:
    if not wc:
        return None
    return {k: wc.get(k) for k in (
        "captured_at", "signals_added", "signals_removed", "client_rank_delta",
        "client_rd_delta", "client_dr_delta", "aio_present")}


SYSTEM_PROMPT = (
    "You are an expert organic SEO analyst. You produce a concise, data-driven, "
    "client-friendly diagnostic of a single keyword's organic search performance "
    "from a rank trajectory and a competitive SERP snapshot. You ANALYZE ONLY — "
    "never prescribe fixes, recommendations, or next steps (a separate, "
    "deterministic work order handles actions). Use ONLY the numbers present in "
    "the provided JSON; if a figure is missing show “—” and state “insufficient "
    "data” briefly. Lower position = better (1 = top). Round to 1–2 decimals."
)


def build_user_prompt(snap: dict) -> str:
    data = json.dumps(snap, indent=2, default=str)
    name = snap.get("client_name")
    keyword = snap.get("keyword")
    return f"""Generate an Organic Rank Analysis report for the client below.

DATA (use only these numbers):
{data}

Return the ENTIRE report as Markdown in the `summary` field of the emit_report
tool, following EXACTLY this structure and order:

# Organic Rank Analysis — {name}

**Keyword:** “{keyword}”  ·  **Ranking URL:** the canonical_url (or “— (not ranking)”).

## Overview
2–3 plain-English sentences for a non-technical reader: where the keyword stands, which direction it's trending, and the single biggest competitive pressure. No jargon, no numbers-dump.

## Key Strengths Recap
Bullets of the positives grounded in the data (current position/trend, any authority the client has, topical fit, click/impression signals). Then a short summarizing paragraph.

## Executive Summary
* **Current position** (trajectory.current_position) and **trend** (trajectory.velocity, trend_per_week /wk).
* **Projected** 30-day / 90-day position (forecast).
* **Winnability** — the rankability band + score (winnability.band / winnability.score).
* **Estimated monthly value** at top-3 (market.est_value) and current traffic (forecast.clicks_per_month_now).
* **Top competitive pressure** — the strongest 1–2 competitors above the client and why.

📈 **Trajectory Callout:** one line stating whether the keyword is climbing, holding, or declining and how fast.

## Position Trajectory
A table: Window | Avg. Position | — with rows Today (current_position), 7-day (avg_7), 30-day (avg_30), 60-day (avg_60), 90-day (avg_90). Note clicks_30d / impressions_30d / ctr_30d if present (GSC source only). Then 3–5 sentences on the trajectory and the forecast (projected 30/90 + confidence). If primary_source is DataForSEO, say the numbers are live-rank checks, not GSC averages.

## Competitive Landscape
A table of the top-10: Pos | Domain | UR | DR | Ref. Domains | Targeted? | Focus (from landscape.top_results; mark the client's row). If aio_present, add one line naming the AI Overview and its cited domains (aio_sources). 2–4 sentences on how authority-rich / tightly-targeted the SERP is.

## Who Beats You & Why
For each competitor in competitor_breakdown (those ranking above the client), a bullet: “#{{position}} {{domain}} — {{primary_reason}}” with the concrete number (e.g. ref-domain gap). Then 3–5 sentences tying the pattern together (authority vs targeting vs topical). If competitor_breakdown is empty and the client ranks #1–3, say so.

## Winnability & Diagnosis
State winnability.band + score, then the 2–3 winnability.factors as bullets. Then the authority gap: the client needs ~authority_gap.rd_to_match referring domains to reach the median top-10 page (median_competitor_rd vs client_rd). Observational only — describe the gap, don't prescribe.

## Forecast & Opportunity
Restate the projected 30/90 position + confidence, the current vs projected clicks/value (label ctr_model rows as estimates, gsc rows as actual Search Console clicks), and the linear-extrapolation caveat (direction/magnitude guidance, not a promise).

## What Changed
If what_changed is present: the signals_added / signals_removed since the previous snapshot and the client_rank / client_rd / client_dr deltas, as 2–4 sentences. If drop_classification is present, state its classification + one-line reason. If nothing changed or there's only one snapshot, say “No prior snapshot to compare” briefly.

Also populate:
- `headline`: one plain-English sentence a client could read — the state of this keyword and its trajectory.
- `top_blockers`: an array of up to 5 short strings, one per key blocker between the client and top-3 (authority gap, targeting, topical, AIO, cannibalization), in plain words.
"""


_EMIT_TOOL = {
    "name": "emit_report",
    "description": "Emit the finished Organic Rank Analysis report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "The full report in Markdown."},
            "headline": {"type": "string", "description": "One-line executive headline."},
            "top_blockers": {
                "type": "array", "items": {"type": "string"},
                "description": "Up to 5 short blocker lines.",
            },
        },
        "required": ["summary", "headline", "top_blockers"],
    },
}


def _report_model() -> str:
    return (settings.rank_analysis_openai_model
            if settings.rank_analysis_provider == "openai" else settings.rank_analysis_model)


def _is_transient(exc: Exception) -> bool:
    from services import report_llm

    if isinstance(exc, RuntimeError) and "rank_analysis_empty_summary" in str(exc):
        return True
    return report_llm.is_transient_llm_error(exc)


async def _call_llm_once(snap: dict) -> dict:
    """One forced tool-use call on the configured provider; raises on
    empty/truncated output."""
    from services import report_llm

    out = await report_llm.run_forced_tool(
        provider=settings.rank_analysis_provider,
        model=_report_model(),
        system=SYSTEM_PROMPT,
        user=build_user_prompt(snap),
        tool_name="emit_report",
        tool_description=_EMIT_TOOL["description"],
        input_schema=_EMIT_TOOL["input_schema"],
        max_tokens=settings.rank_analysis_max_tokens,
    )
    if not (out.get("summary") or "").strip():
        raise RuntimeError("rank_analysis_empty_summary")
    return out


async def _call_llm(snap: dict) -> dict:
    """Run the configured provider with forced tool-use; returns {summary,
    headline, top_blockers}. Retries transient failures (429 / 5xx / connection
    drops / truncation) with exponential backoff + jitter."""
    max_retries = settings.rank_analysis_max_retries
    base = settings.rank_analysis_retry_base_seconds
    attempt = 0
    while True:
        try:
            return await _call_llm_once(snap)
        except Exception as exc:  # noqa: BLE001 — classify then re-raise if terminal
            if attempt >= max_retries or not _is_transient(exc):
                raise
            delay = base * (2 ** attempt) * (0.5 + secrets.randbelow(1000) / 1000.0)
            logger.warning(
                "rank_analysis_llm_retry",
                extra={"attempt": attempt + 1, "delay_s": round(delay, 1), "error": str(exc)[:200]},
            )
            await asyncio.sleep(delay)
            attempt += 1


# ----------------------------------------------------------------------------
# Deterministic work-order rendering (the actionable layer — not LLM-authored)
# ----------------------------------------------------------------------------
_CTA_LABELS = {
    "link_building": "Build links (Recipe Engine / Link Building)",
    "create_page": "Create a page (Local SEO / Content)",
    "reoptimize_page": "Reoptimize the ranking page",
    "consolidate": "Consolidate competing pages (GSC Research)",
}


def render_work_order_md(work_order: list[dict]) -> str:
    """Render the ranked gap-to-close list as a Markdown section — the
    deterministic actionable layer appended to the Doc (never narrated)."""
    if not work_order:
        return ""
    lines = ["## Recommended Focus (Work Order)", "",
             "Ranked by leverage — the deterministic gaps between this keyword and the top 3:", ""]
    for i, item in enumerate(work_order, 1):
        cta = _CTA_LABELS.get(item.get("cta"), item.get("cta") or "")
        lines.append(f"{i}. **{item.get('headline')}** — {item.get('detail')}  \n"
                     f"   _Leverage {item.get('leverage')}/100 · {cta}_")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Per-keyword generation
# ----------------------------------------------------------------------------
async def generate_report_for_keyword(client_id: str, keyword_id: str) -> dict:
    """Assemble the analysis, run the LLM, and return the column values to
    persist on the rank_keyword_reports row (does not write)."""
    analysis = rank_analysis.build_keyword_analysis(client_id, keyword_id)
    if analysis is None:
        raise RuntimeError("keyword_not_found")

    snap = build_llm_snapshot(analysis)
    llm = await _call_llm(snap)

    return {
        "status": "complete",
        "error": None,
        "snapshot_id": (analysis.get("landscape") or {}).get("snapshot_id"),
        "report_md": llm.get("summary"),
        "report_headline": llm.get("headline"),
        "report_analytics": analysis,
        "report_work_order": analysis.get("work_order"),
        "priority": analysis.get("priority"),
        "generated_at": "now()",
        "_top_blockers": llm.get("top_blockers"),  # transient (for the Doc), stripped before write
    }


# ----------------------------------------------------------------------------
# Job + enqueue
# ----------------------------------------------------------------------------
def enqueue_rank_keyword_report(
    client_id: str, keyword_id: str, keyword: str, trigger: str = "on_demand",
) -> Optional[str]:
    """Create a pending report row + enqueue the job (deduped on the pending
    row). Returns the report row id, or None if one is already in flight."""
    supabase = get_supabase()
    existing = (
        supabase.table("rank_keyword_reports").select("id")
        .eq("keyword_id", keyword_id).eq("status", "pending").limit(1).execute()
    )
    if existing.data:
        return None
    row = (
        supabase.table("rank_keyword_reports").insert({
            "client_id": client_id, "keyword_id": keyword_id, "keyword": keyword,
            "trigger": trigger, "status": "pending",
        }).execute()
    ).data
    report_id = row[0]["id"] if row else None
    if report_id:
        supabase.table("async_jobs").insert({
            "job_type": "rank_keyword_report", "entity_id": report_id,
            "payload": {"report_id": report_id, "client_id": client_id,
                        "keyword_id": keyword_id, "trigger": trigger},
        }).execute()
    return report_id


def enqueue_drop_reports(client_id: str, keyword_ids: list[str]) -> int:
    """Enqueue a drop-triggered Organic Rank Analysis report for each just-dropped
    keyword that has a SERP snapshot to analyze. Called from rank_materialize's
    drop-detection path (alongside the drop-triggered snapshot + reopt plan). A
    keyword with no snapshot is skipped — the report's competitive half needs one,
    and a fresh drop-triggered capture will make the next run eligible. Deduped by
    the pending-row guard in enqueue_rank_keyword_report. Returns the count."""
    if not keyword_ids:
        return 0
    supabase = get_supabase()
    with_snap = {
        r["keyword_id"] for r in (
            supabase.table("serp_snapshots").select("keyword_id")
            .in_("keyword_id", keyword_ids)
            .in_("status", ["complete", "partial"]).execute()
        ).data or []
    }
    if not with_snap:
        return 0
    names = {
        r["id"]: r["keyword"] for r in (
            supabase.table("tracked_keywords").select("id, keyword")
            .in_("id", list(with_snap)).execute()
        ).data or []
    }
    count = 0
    for kid in keyword_ids:
        if kid in with_snap and kid in names:
            if enqueue_rank_keyword_report(client_id, kid, names[kid], trigger="drop"):
                count += 1
    return count


async def _maybe_publish_doc(
    client: dict, keyword: str, report_md: str, work_order: list[dict],
    top_blockers: Optional[list[str]],
) -> Optional[str]:
    """Publish a per-keyword Google Doc (narrative + deterministic work order) if
    the client has a Drive folder + the webhook is configured. Returns doc_url."""
    folder_id = client.get("google_drive_folder_id")
    if not folder_id or not settings.google_apps_script_url or not report_md:
        return None
    title = f"Organic Rank Analysis — {client.get('name')} — {keyword}".strip(" —")
    body = report_md
    wo = render_work_order_md(work_order or [])
    if wo:
        body += "\n\n---\n\n" + wo
    try:
        result = await create_google_doc(folder_id, title, body)
        return result.get("doc_url")
    except GoogleDocError as exc:
        logger.warning("rank_analysis_doc_publish_failed", extra={"keyword": keyword, "error": str(exc)})
        return None


async def run_rank_keyword_report_job(job: dict) -> None:
    """async_jobs handler for 'rank_keyword_report' — generate one per-keyword
    report, persist it, and publish a Doc (best-effort)."""
    payload = job.get("payload") or {}
    report_id = payload.get("report_id")
    client_id = payload.get("client_id")
    keyword_id = payload.get("keyword_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        fields = await generate_report_for_keyword(client_id, keyword_id)
        top_blockers = fields.pop("_top_blockers", None)

        client = (
            supabase.table("clients").select("id, name, google_drive_folder_id")
            .eq("id", client_id).single().execute()
        ).data or {}
        keyword = (fields.get("report_analytics") or {}).get("keyword") or ""
        doc_url = await _maybe_publish_doc(
            client, keyword, fields.get("report_md"), fields.get("report_work_order"), top_blockers,
        )
        if doc_url:
            fields["doc_url"] = doc_url

        supabase.table("rank_keyword_reports").update(fields).eq("id", report_id).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("rank_analysis_report_complete", extra={"report_id": report_id, "keyword": keyword})
    except Exception as exc:
        logger.error("rank_analysis_report_job_failed", extra={"report_id": report_id, "error": str(exc)})
        if report_id:
            supabase.table("rank_keyword_reports").update(
                {"status": "failed", "error": str(exc)[:500], "generated_at": "now()"}
            ).eq("id", report_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
