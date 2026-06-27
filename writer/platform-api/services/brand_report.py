"""AI Visibility — visibility report → Google Doc.

Assembles the latest scan into a shareable report (per-engine visibility, the
keyword×engine matrix, where the brand is invisible, competitor comparison) +
a short Claude narrative, and publishes it as a Google Doc in the client's Drive
folder (shared services/google_docs, like the Maps Local Rank Analysis report).

Runs as an `async_jobs` job ('brand_report'). The data-assembly + markdown
helpers are pure (unit-tested); only the narrative + publish touch the network.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import settings
from db.supabase_client import get_supabase
from services.brand_scan import ENGINE_ORDER
from services.google_docs import GoogleDocError, create_google_doc

logger = logging.getLogger("brand_report")

ENGINE_LABELS = {
    "chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini",
    "perplexity": "Perplexity", "google_ai_overview": "Google AI Overview",
    "google_ai_mode": "Google AI Mode",
}


# ── pure data assembly ───────────────────────────────────────────────────────
def build_snapshot(rows: list[dict], keyword_labels: dict[str, str]) -> dict:
    """Roll a batch's brand-mention rows into report figures. Pure."""
    engines: dict[str, dict] = {e: {"total": 0, "found": 0} for e in ENGINE_ORDER}
    competitors: dict[str, dict] = {}
    by_keyword: dict[str, dict] = {}
    overall_total = overall_found = 0

    for r in rows:
        if r.get("status") != "completed":
            continue
        engine = r.get("engine")
        kid = r.get("keyword_id")
        label = keyword_labels.get(kid, "(removed keyword)")
        found = bool(r.get("mention_found"))
        if engine in engines:
            engines[engine]["total"] += 1
            engines[engine]["found"] += 1 if found else 0
        overall_total += 1
        overall_found += 1 if found else 0
        kw = by_keyword.setdefault(label, {})
        kw[engine] = "found" if found else "not"
        for comp in r.get("competitor_results") or []:
            name = comp.get("name")
            if not name:
                continue
            agg = competitors.setdefault(name, {"total": 0, "found": 0})
            agg["total"] += 1
            agg["found"] += 1 if comp.get("found") else 0

    def _pct(found, total):
        return round(100.0 * found / total, 1) if total else 0.0

    invisible = [
        {"keyword": kw, "engine": eng}
        for kw, cells in by_keyword.items()
        for eng in ENGINE_ORDER
        if cells.get(eng) == "not"
    ]
    return {
        "overall": {"total": overall_total, "found": overall_found, "pct": _pct(overall_found, overall_total)},
        "engines": {e: {**v, "pct": _pct(v["found"], v["total"])} for e, v in engines.items()},
        "by_keyword": by_keyword,
        "invisible": invisible,
        "competitors": {n: {**v, "pct": _pct(v["found"], v["total"])} for n, v in competitors.items()},
    }


def render_markdown(client_name: str, date_str: str, snapshot: dict, narrative: str = "") -> str:
    """Render the snapshot as the Google Doc's Markdown body. Pure."""
    o = snapshot["overall"]
    lines = [
        f"# AI Visibility Report — {client_name}",
        f"_{date_str}_",
        "",
        f"**Overall visibility: {o['pct']}%** — the brand appeared in {o['found']} of "
        f"{o['total']} AI answers checked.",
        "",
    ]
    if narrative:
        lines += ["## Summary", narrative, ""]

    lines += ["## Visibility by engine", "", "| Engine | Visible | Checked | Rate |", "|---|---|---|---|"]
    for e in ENGINE_ORDER:
        s = snapshot["engines"][e]
        lines.append(f"| {ENGINE_LABELS[e]} | {s['found']} | {s['total']} | {s['pct']}% |")
    lines.append("")

    # Keyword × engine matrix
    header = "| Keyword | " + " | ".join(ENGINE_LABELS[e] for e in ENGINE_ORDER) + " |"
    sep = "|---|" + "|".join(["---"] * len(ENGINE_ORDER)) + "|"
    lines += ["## Keyword detail", "", header, sep]
    for kw, cells in snapshot["by_keyword"].items():
        marks = []
        for e in ENGINE_ORDER:
            v = cells.get(e)
            marks.append("✅" if v == "found" else "❌" if v == "not" else "—")
        lines.append(f"| {kw} | " + " | ".join(marks) + " |")
    lines.append("")

    if snapshot["invisible"]:
        lines += ["## Where you're invisible", ""]
        for item in snapshot["invisible"]:
            lines.append(f"- **{item['keyword']}** — not shown by {ENGINE_LABELS.get(item['engine'], item['engine'])}")
        lines.append("")

    if snapshot["competitors"]:
        lines += ["## Competitor comparison", "", "| Competitor | Visibility |", "|---|---|"]
        lines.append(f"| **{client_name} (you)** | {o['pct']}% |")
        for name, s in sorted(snapshot["competitors"].items(), key=lambda kv: -kv[1]["pct"]):
            lines.append(f"| {name} | {s['pct']}% |")
        lines.append("")

    return "\n".join(lines)


# ── narrative (best-effort) ──────────────────────────────────────────────────
async def _narrative(client_name: str, snapshot: dict) -> str:
    if not settings.anthropic_api_key:
        return ""
    import anthropic

    engine_lines = "\n".join(
        f"- {ENGINE_LABELS[e]}: {snapshot['engines'][e]['pct']}%" for e in ENGINE_ORDER
    )
    comp_lines = "\n".join(f"- {n}: {s['pct']}%" for n, s in snapshot["competitors"].items()) or "none tracked"
    prompt = (
        f"Write a concise executive summary (max 130 words) for an AI-search visibility "
        f"report for the business \"{client_name}\". Overall the brand appeared in "
        f"{snapshot['overall']['pct']}% of AI answers checked.\n\n"
        f"Per-engine visibility:\n{engine_lines}\n\nCompetitor visibility:\n{comp_lines}\n\n"
        f"Cover: how visible the brand is in AI assistants, the weakest engines, how it "
        f"compares to competitors, and 2-3 prioritized recommendations. Plain prose, no headings."
    )
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.brand_report_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.get("text", "") for b in resp.model_dump().get("content") or []).strip()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("brand_report.narrative_failed", extra={"error": str(exc)})
        return ""


# ── enqueue + job ────────────────────────────────────────────────────────────
def enqueue_brand_report(client_id: str) -> str:
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .insert({"job_type": "brand_report", "entity_id": client_id, "payload": {"client_id": client_id}})
        .execute()
    )
    return res.data[0]["id"]


def _latest_batch_id(supabase, client_id: str) -> str | None:
    rows = (
        supabase.table("brand_mention_history")
        .select("scan_batch_id, created_at")
        .eq("client_id", client_id)
        .eq("is_competitor_scan", False)
        .order("created_at", desc=True)
        .limit(1)
        .execute().data
    )
    return rows[0]["scan_batch_id"] if rows else None


async def run_brand_report_job(job: dict) -> None:
    """async_jobs handler for job_type='brand_report'. Builds + publishes the doc."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        client_rows = (
            supabase.table("clients").select("name, google_drive_folder_id")
            .eq("id", client_id).limit(1).execute().data
        )
        if not client_rows:
            raise GoogleDocError("client_not_found")
        client = client_rows[0]

        batch_id = _latest_batch_id(supabase, client_id)
        if not batch_id:
            raise GoogleDocError("no_scans_to_report")
        from services.brand_service import list_history
        rows = list_history(client_id, limit=2000, scan_batch_id=batch_id)
        kw_rows = (
            supabase.table("brand_tracked_keywords").select("id, keyword")
            .eq("client_id", client_id).execute().data or []
        )
        labels = {k["id"]: k["keyword"] for k in kw_rows}

        snapshot = build_snapshot(rows, labels)
        narrative = await _narrative(client.get("name") or "", snapshot)
        date_str = datetime.now(timezone.utc).strftime("%-d %b %Y")
        markdown = render_markdown(client.get("name") or "Client", date_str, snapshot, narrative)

        doc = await create_google_doc(
            client.get("google_drive_folder_id"),
            f"AI Visibility Report — {client.get('name')} — {date_str}".strip(" —"),
            markdown,
        )
        supabase.table("async_jobs").update({
            "status": "complete",
            "result": {"doc_url": doc.get("doc_url"), "doc_id": doc.get("doc_id")},
            "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("brand_report.complete", extra={"job_id": job_id, "client_id": client_id})
    except Exception as exc:
        logger.warning("brand_report.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
