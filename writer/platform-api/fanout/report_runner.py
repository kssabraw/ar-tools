"""Keyword Research report — orchestration (fetch → LLM summary → PDF → deliver).

Ties the pure builders (fanout/report.py) to I/O: read a session's rows, write a
best-effort Claude executive summary, render the HTML to a PDF (reusing the
suite's WeasyPrint renderer), save it to the private `reports` storage bucket for
download, upload a copy to the client's Google Drive folder (when the session is
client-linked), and record a `fanout.keyword_reports` row.

Synchronous, like the CSV export (fanout/api/exports.py): one Claude call + a
WeasyPrint render + two uploads finish in well under the request budget, so no
background job is needed. Every delivery step is best-effort — a failed Drive
upload or storage write degrades that channel but still returns the report.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fanout import report as builders
from fanout.config import get_settings
from fanout.storage import silo as store
from fanout.storage.supabase_client import get_service_client

logger = logging.getLogger(__name__)

_REPORTS_BUCKET = "reports"
_SIGNED_URL_TTL = 7 * 24 * 3600  # 7 days

_SUMMARY_SYSTEM = (
    "You are an SEO strategist writing the opening of a client-facing keyword "
    "research report. Write ONE tight paragraph (3-5 sentences), plain and "
    "upbeat, no jargon, no bullet points, no headings. Summarize what the "
    "research found and the opportunity — grounded ONLY in the figures given. "
    "Do not invent numbers."
)


def _exec_summary(stats: dict) -> str:
    """Best-effort Claude executive summary; deterministic fallback on any
    failure or when the key is unset."""
    s = get_settings()
    if not s.anthropic_api_key:
        return builders.fallback_summary(stats)
    try:
        from fanout.llm.anthropic_client import AnthropicLLM

        cp = stats["content_plan"]
        facts = (
            f'Seed topic: "{stats["seed"]}"\n'
            f'Target keywords: {stats["total_keywords"]}\n'
            f'Topic silos: {stats["total_silos"]} '
            f'({", ".join(s2["name"] for s2 in stats["silos"][:8])})\n'
            f'Total monthly searches: {stats["total_volume"] if stats["metrics_present"] else "not measured"}\n'
            f'Average difficulty (0-100): {round(stats["avg_difficulty"]) if stats["avg_difficulty"] is not None else "n/a"}\n'
            f'Planned pages: {stats["planned_pages"]} '
            f'({cp["pillar_count"]} pillars, {cp["article_count"]} supporting articles)\n'
            f'Top opportunities: '
            + ", ".join(o["keyword"] for o in stats["top_opportunities"][:6])
        )
        llm = AnthropicLLM(
            s.anthropic_api_key, s.keyword_report_model,
            max_tokens=s.keyword_report_max_tokens, timeout_s=60,
        )
        text = llm.complete_text(
            system=_SUMMARY_SYSTEM,
            user=f"Write the executive summary from these figures:\n\n{facts}",
            purpose="keyword_report_summary",
            temperature=0.4,
        )
        return text.strip() or builders.fallback_summary(stats)
    except Exception as exc:  # noqa: BLE001 — narrative is best-effort
        logger.warning("kw_report.summary_failed", extra={"error": str(exc)})
        return builders.fallback_summary(stats)


def _suite_client(session: dict) -> Optional[dict]:
    """The public.clients row for a client-linked session (for the Drive folder +
    display name). None when the session isn't client-linked or the lookup
    fails — the report still generates, just download-only."""
    client_id = session.get("client_id")
    if not client_id:
        return None
    try:
        from db.supabase_client import get_supabase

        res = (
            get_supabase().table("clients")
            .select("id, name, google_drive_folder_id, drive_folders")
            .eq("id", client_id).limit(1).execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("kw_report.client_lookup_failed", extra={"error": str(exc)})
        return None


def _store_pdf(session_id: str, report_id: str, pdf: bytes) -> tuple[Optional[str], Optional[str]]:
    """Upload the PDF to the private `reports` bucket; return (path, signed_url).
    Best-effort — a storage failure just means no in-app download link."""
    try:
        from db.supabase_client import get_supabase

        sb = get_supabase()
        path = f"fanout/{session_id}/{report_id}.pdf"
        sb.storage.from_(_REPORTS_BUCKET).upload(
            path, pdf, {"content-type": "application/pdf", "upsert": "true"}
        )
        res = sb.storage.from_(_REPORTS_BUCKET).create_signed_url(path, _SIGNED_URL_TTL)
        url = (res.get("signedURL") or res.get("signedUrl")) if isinstance(res, dict) else None
        return path, url
    except Exception as exc:  # noqa: BLE001
        logger.warning("kw_report.storage_failed", extra={"error": str(exc)})
        return None, None


def _upload_to_drive(client: Optional[dict], title: str, pdf: bytes) -> Optional[str]:
    """Upload a copy to the client's Drive folder; return the file URL or None.
    Best-effort — no client / no folder / webhook failure just skips this copy."""
    if not client:
        return None
    try:
        from services.google_docs import resolve_drive_folder, upload_pdf

        folder = resolve_drive_folder(client, "keyword_research") or client.get("google_drive_folder_id")
        if not folder:
            return None
        result = asyncio.run(upload_pdf(folder, title, pdf))
        return result.get("file_url")
    except Exception as exc:  # noqa: BLE001
        logger.warning("kw_report.drive_failed", extra={"error": str(exc)})
        return None


def generate_report(session_id: str, user_id: Optional[str]) -> dict:
    """Build + deliver the report for a session. Raises ValueError('no_keywords')
    when the session has nothing to report on."""
    session = store.get_session(session_id)
    if not session:
        raise ValueError("session_not_found")

    topics = store.list_topics(session_id)
    keywords = store.list_surviving_keywords(session_id)
    clusters = store.list_clusters(session_id)
    arch_row = store.get_architecture(session_id)
    architecture_json = (arch_row or {}).get("architecture_json")

    stats = builders.build_report_stats(
        session=session, topics=topics, keywords=keywords,
        clusters=clusters, architecture_json=architecture_json,
    )
    if stats["total_keywords"] == 0:
        raise ValueError("no_keywords")

    client = _suite_client(session)
    from config import settings as suite_settings

    agency_name = suite_settings.client_report_agency_name
    client_name = (client or {}).get("name")
    exec_summary = _exec_summary(stats)
    generated_on = datetime.now(timezone.utc).strftime("%b %d, %Y")

    html = builders.render_report_html(
        stats=stats, exec_summary=exec_summary, agency_name=agency_name,
        client_name=client_name, generated_on=generated_on,
    )

    from services.client_report import render_pdf

    pdf = render_pdf(html)
    title = f"Keyword Research — {stats['seed'] or 'Report'}"

    svc = get_service_client()
    row = (
        svc.table("keyword_reports")
        .insert({"session_id": session_id, "created_by": user_id, "title": title, "status": "complete"})
        .execute()
    ).data[0]
    report_id = row["id"]

    storage_path, download_url = _store_pdf(session_id, report_id, pdf)
    drive_url = _upload_to_drive(client, title, pdf)

    svc.table("keyword_reports").update(
        {"storage_path": storage_path, "drive_url": drive_url}
    ).eq("id", report_id).execute()

    logger.info(
        "kw_report_created",
        extra={"event": "kw_report_created", "session_id": session_id,
               "keywords": stats["total_keywords"], "drive": bool(drive_url)},
    )
    return {
        "report_id": report_id,
        "session_id": session_id,
        "title": title,
        "download_url": download_url,
        "drive_url": drive_url,
        "generated_at": row["generated_at"],
    }


def signed_download_url(storage_path: str) -> Optional[str]:
    """Re-issue a fresh signed URL for a stored report PDF (past reports may have
    an expired link)."""
    if not storage_path:
        return None
    try:
        from db.supabase_client import get_supabase

        res = get_supabase().storage.from_(_REPORTS_BUCKET).create_signed_url(storage_path, _SIGNED_URL_TTL)
        return (res.get("signedURL") or res.get("signedUrl")) if isinstance(res, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("kw_report.resign_failed", extra={"error": str(exc)})
        return None
