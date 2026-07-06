"""Client Reporting Phase 5 — per-client report settings, schedules + delivery.

Settings (`client_report_settings`, one row per client) carry the AM recipient
list, a monthly/weekly schedule (self-clocked via next_run_at on the shared
gsc_scheduler — same pattern as brand_scan_schedules; the cadence clock reuses
brand_schedule.compute_next_run_at), and per-channel delivery toggles.

Delivery (`deliver_report`) runs after a report renders, best-effort per
channel — a delivery failure never fails the report itself:
  * email — SMTP (Gmail/Workspace, same creds as the notifications service)
    with the PDF attached + a signed link, to the client's recipients (NOT
    the agency-level notify_email_to). Skipped until SMTP creds are set.
  * drive — a PDF copy in the client's Drive folder via the Apps Script
    webhook (`type: "pdf"` — needs the redeployed webhook; an old deployment
    fails loudly with pdf_not_supported rather than recording a phantom copy).
Outcomes land on client_reports.delivery ({email, drive} → ok/failed/skipped),
mirroring notifications.channels_sent.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services.brand_schedule import compute_next_run_at

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT = 30.0
# Weekly scheduled reports cover the last 7 days; monthly the builder's default (30).
_WEEKLY_PERIOD_DAYS = 7

_SETTINGS_COLS = (
    "client_id, recipients, cadence, day_of_week, day_of_month, hour_utc, "
    "email_enabled, drive_enabled, last_run_at, next_run_at"
)


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def parse_recipients(raw: object) -> list[str]:
    """Normalize a recipients input (list or comma-separated string) to a clean
    list of addresses; drops blanks, de-dupes case-insensitively, keeps order."""
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = [str(r) for r in raw]
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        addr = item.strip()
        if addr and "@" in addr and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def format_report_email(client_name: Optional[str], title: str, pdf_url: Optional[str]) -> tuple[str, str]:
    """(subject, plain-text body) for a delivered report. Pure."""
    subject = f"[{client_name}] SEO report ready" if client_name else "SEO report ready"
    lines = [
        f"The latest report for {client_name or 'your client'} is attached.",
        "",
        title,
        "",
    ]
    if pdf_url:
        lines += [f"Download (link expires): {pdf_url}", ""]
    lines.append("— AR Tools")
    return subject, "\n".join(lines)


def _default_settings(client_id: str) -> dict:
    return {
        "client_id": client_id,
        "recipients": [],
        "cadence": "disabled",
        "day_of_week": None,
        "day_of_month": None,
        "hour_utc": 8,
        "email_enabled": True,
        "drive_enabled": True,
        "last_run_at": None,
        "next_run_at": None,
    }


# ----------------------------------------------------------------------------
# Settings CRUD.
# ----------------------------------------------------------------------------
def get_settings(client_id: str) -> dict:
    rows = (
        get_supabase().table("client_report_settings")
        .select(_SETTINGS_COLS).eq("client_id", client_id).limit(1).execute()
    ).data
    return rows[0] if rows else _default_settings(client_id)


def upsert_settings(
    client_id: str,
    recipients: object,
    cadence: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    hour_utc: int,
    email_enabled: bool,
    drive_enabled: bool,
) -> dict:
    """Save settings and (re)compute the schedule clock. Raises HTTPException on
    an invalid cadence (via compute_next_run_at)."""
    now = datetime.now(timezone.utc)
    next_run = compute_next_run_at(now, cadence, day_of_week, day_of_month, hour_utc)
    row = {
        "client_id": client_id,
        "recipients": parse_recipients(recipients),
        "cadence": cadence,
        "day_of_week": day_of_week,
        "day_of_month": day_of_month,
        "hour_utc": hour_utc,
        "email_enabled": email_enabled,
        "drive_enabled": drive_enabled,
        "next_run_at": next_run.isoformat() if next_run else None,
        "updated_at": now.isoformat(),
    }
    res = (
        get_supabase().table("client_report_settings")
        .upsert(row, on_conflict="client_id").execute()
    )
    return res.data[0] if res.data else row


# ----------------------------------------------------------------------------
# Scheduler tick.
# ----------------------------------------------------------------------------
def _has_pending_report(supabase, client_id: str) -> bool:
    rows = (
        supabase.table("client_reports").select("id")
        .eq("client_id", client_id).in_("status", ["pending", "running"])
        .limit(1).execute()
    ).data
    return bool(rows)


def enqueue_due_report_schedules() -> int:
    """Scheduler tick: enqueue a client_report (with delivery) for each schedule
    whose next_run_at is due, then advance its clock. Returns the count."""
    from services.client_report import enqueue_client_report

    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    due = (
        supabase.table("client_report_settings")
        .select(_SETTINGS_COLS)
        .neq("cadence", "disabled")
        .lte("next_run_at", now.isoformat())
        .execute().data or []
    )
    enqueued = 0
    for sched in due:
        client_id = sched["client_id"]
        next_run = compute_next_run_at(
            now, sched["cadence"], sched.get("day_of_week"),
            sched.get("day_of_month"), sched["hour_utc"],
        )
        # Always advance the clock so an in-flight client doesn't re-fire every tick.
        supabase.table("client_report_settings").update({
            "last_run_at": now.isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        }).eq("client_id", client_id).execute()

        if _has_pending_report(supabase, client_id):
            continue
        report_type = "weekly" if sched["cadence"] == "weekly" else "monthly"
        period_start = (now.date() - timedelta(days=_WEEKLY_PERIOD_DAYS)) if report_type == "weekly" else None
        try:
            enqueue_client_report(
                client_id, report_type,
                period_start=period_start, period_end=now.date(),
                deliver=True,
            )
            enqueued += 1
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("report_schedule.enqueue_failed", extra={"client_id": client_id, "error": str(exc)})
    if enqueued:
        logger.info("report_schedule.enqueued", extra={"clients": enqueued})
    return enqueued


# ----------------------------------------------------------------------------
# Delivery (post-render, best-effort per channel).
# ----------------------------------------------------------------------------
def _send_report_email_sync(
    recipients: list[str], subject: str, body: str, pdf: bytes, filename: str
) -> None:
    """Blocking SMTP send with the PDF attached (run via asyncio.to_thread)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=_SMTP_TIMEOUT) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def deliver_report(report_id: str) -> dict:
    """Deliver one completed report per its client's settings. Best-effort per
    channel; records {email, drive} outcomes on client_reports.delivery and
    returns them. Never raises (the report itself already succeeded)."""
    from services.client_report import _REPORTS_BUCKET, _signed_url
    from services.google_docs import GoogleDocError, resolve_drive_folder, upload_pdf

    supabase = get_supabase()
    channels: dict[str, str] = {"email": "skipped", "drive": "skipped"}
    try:
        rows = (
            supabase.table("client_reports").select("*").eq("id", report_id).limit(1).execute()
        ).data
        if not rows or rows[0].get("status") != "complete" or not rows[0].get("storage_path"):
            return channels
        report = rows[0]
        client_id = report["client_id"]
        sched = get_settings(client_id)
        client_rows = (
            supabase.table("clients").select("id, name, google_drive_folder_id, drive_folders")
            .eq("id", client_id).limit(1).execute()
        ).data
        client = client_rows[0] if client_rows else {}
        title = report.get("title") or "SEO report"
        filename = f"{title}.pdf".replace("/", "-")

        pdf: Optional[bytes] = None

        def _download() -> bytes:
            return supabase.storage.from_(_REPORTS_BUCKET).download(report["storage_path"])

        recipients = parse_recipients(sched.get("recipients"))
        if sched.get("email_enabled") and recipients and smtp_configured():
            try:
                pdf = await asyncio.to_thread(_download)
                subject, body = format_report_email(
                    client.get("name"), title, _signed_url(report["storage_path"])
                )
                await asyncio.to_thread(_send_report_email_sync, recipients, subject, body, pdf, filename)
                channels["email"] = "ok"
            except Exception as exc:
                channels["email"] = "failed"
                logger.warning("report_email_failed", extra={"report_id": report_id, "error": str(exc)})

        folder_id = resolve_drive_folder(client, "report")
        if sched.get("drive_enabled") and folder_id:
            try:
                if pdf is None:
                    pdf = await asyncio.to_thread(_download)
                drive = await upload_pdf(folder_id, title, pdf)
                channels["drive"] = "ok"
                supabase.table("client_reports").update(
                    {"drive_doc_id": drive.get("file_id")}
                ).eq("id", report_id).execute()
            except GoogleDocError as exc:
                channels["drive"] = "failed"
                logger.warning("report_drive_failed", extra={"report_id": report_id, "error": str(exc)})
            except Exception as exc:
                channels["drive"] = "failed"
                logger.warning("report_drive_failed", extra={"report_id": report_id, "error": str(exc)})

        supabase.table("client_reports").update({"delivery": channels}).eq("id", report_id).execute()
    except Exception as exc:  # never break the report over delivery bookkeeping
        logger.warning("report_delivery_failed", extra={"report_id": report_id, "error": str(exc)})
    return channels
