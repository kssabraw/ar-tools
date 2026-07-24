"""Per-page RD imbalance — the Link Building SOP's entity-balance health check
("no inner page should carry far more RD than the home page"; §Risk Monitoring
health checks + §SEO NEO entity-balance caution).

Monthly, per client: fetch **page-level** DataForSEO Backlinks summaries
(`serp_snapshot.fetch_backlinks_summary`) for the homepage + the client's money
pages — the distinct canonical URLs on tracked keywords (capped) — store them in
`page_backlink_profiles`, and open an `rd_imbalance` offpage alert when an
inner page's RD exceeds the homepage's by the imbalance ratio. Non-escalating
hygiene by design (the SOP: the SEO NEO assignee self-corrects by building RD
to the home page or easing off the inner page) — a warning notification + an
Action Plan action, never a freeze or senior escalation.

The paid calls are a handful per client per month (homepage + ≤PAGE_MAX money
pages), on the same Backlinks summary endpoint the domain-level intel uses.

Pure helpers (`money_page_urls`, `detect_imbalance`) are unit-tested.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

CAPTURE_INTERVAL_DAYS = 28
PAGE_MAX = 5                   # money pages per capture (besides the homepage)
IMBALANCE_RATIO = 1.5          # inner page RD > homepage RD × this → imbalance
IMBALANCE_MIN_RD = 20          # …and at least this many RD (small-profile noise floor)


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested)
# ─────────────────────────────────────────────────────────────────────────────
def _norm(url: str) -> str:
    return (url or "").split("#")[0].split("?")[0].rstrip("/").lower()


def money_page_urls(website_url: str, canonical_urls: list[str], cap: int = PAGE_MAX) -> list[str]:
    """The inner pages worth a paid read: distinct canonical URLs on the
    client's own domain, homepage excluded, order-preserving, capped. Pure."""
    home = _norm(website_url)
    home_host = urlparse(website_url if "//" in website_url else "http://" + website_url).netloc.lower().removeprefix("www.")
    seen: set[str] = set()
    out: list[str] = []
    for u in canonical_urls:
        if not u:
            continue
        key = _norm(u)
        host = urlparse(u if "//" in u else "http://" + u).netloc.lower().removeprefix("www.")
        if not key or key == home or key in seen or (home_host and host != home_host):
            continue
        seen.add(key)
        out.append(u)
        if len(out) >= cap:
            break
    return out


def detect_imbalance(homepage_rd: Optional[int], pages: list[dict]) -> list[dict]:
    """Inner pages out-RD'ing the homepage past the ratio + noise floor. Pure.
    Each offender: {url, referring_domains, homepage_rd}."""
    if homepage_rd is None:
        return []
    offenders = []
    for p in pages:
        rd = p.get("referring_domains")
        if rd is None or rd < IMBALANCE_MIN_RD:
            continue
        if rd > max(homepage_rd, 1) * IMBALANCE_RATIO:
            offenders.append({"url": p.get("url"), "referring_domains": rd, "homepage_rd": homepage_rd})
    return offenders


def build_page_view(rows: list[dict]) -> dict:
    """Shape stored ``page_backlink_profiles`` rows into the read payload for the
    Backlink Explorer's per-page monitor. Pure.

    Returns the latest capture's pages (homepage first, then referring-domains
    desc) plus a per-URL history series (ascending by capture) for a trend line.
    ``latest_captured_at`` is None when there are no rows yet."""
    rows = [r for r in rows if r.get("captured_at")]
    if not rows:
        return {"latest_captured_at": None, "pages": [], "history": {}}
    latest = max(r["captured_at"] for r in rows)
    latest_pages = [r for r in rows if r["captured_at"] == latest]
    latest_pages.sort(key=lambda r: (not r.get("is_homepage"), -(r.get("referring_domains") or 0)))
    history: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["captured_at"]):
        history.setdefault(r.get("url"), []).append(
            {k: r.get(k) for k in ("captured_at", "referring_domains", "backlinks", "url_rating")}
        )
    return {"latest_captured_at": latest, "pages": latest_pages, "history": history}


# ─────────────────────────────────────────────────────────────────────────────
# The capture job (monthly, interval-gated)
# ─────────────────────────────────────────────────────────────────────────────
async def run_page_backlink_job(job: dict) -> None:
    from services import backlinks_api, serp_snapshot
    from services.dataforseo_rank import extract_domain

    supabase = get_supabase()
    job_id = job["id"]
    client_id = (job.get("payload") or {}).get("client_id") or job.get("entity_id")
    try:
        client = (
            supabase.table("clients").select("website_url").eq("id", client_id).single().execute()
        ).data or {}
        website = (client.get("website_url") or "").strip()
        if not website:
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"skipped": "no_website"}, "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return

        # Money pages: the team's canonical money pages FIRST, then the site's
        # highest-RD inner pages from the domain_pages breakdown. domain_pages is
        # a single call that already CARRIES per-page RD/backlinks/UR, so pages it
        # covers need no extra per-page summary call — and it makes the capture
        # populate for every client, not just the few with canonical_urls set on
        # their tracked keywords (which is why this table used to be homepage-only).
        kw_rows = (
            supabase.table("tracked_keywords")
            .select("canonical_url")
            .eq("client_id", client_id)
            .not_.is_("canonical_url", "null")
            .execute()
        ).data or []
        canonical = [r["canonical_url"] for r in kw_rows]

        domain = extract_domain(website) or website
        try:
            dp = await backlinks_api.fetch_domain_pages(domain, "domain", limit=settings.backlink_pages_limit)
        except Exception as exc:  # best-effort — fall back to canonical-only
            logger.warning("page_backlinks.domain_pages_failed",
                           extra={"client_id": client_id, "domain": domain, "error": str(exc)})
            dp = []
        dp_sorted = sorted(dp, key=lambda p: (p.get("referring_domains") or 0), reverse=True)
        dp_map = {_norm(p["url"]): p for p in dp if p.get("url")}
        inner = money_page_urls(website, canonical + [p["url"] for p in dp_sorted if p.get("url")])

        captured_at = datetime.now(timezone.utc).isoformat()
        rows: list[dict] = []
        homepage_rd: Optional[int] = None
        page_reads: list[dict] = []

        # Homepage — an authoritative summary call (the imbalance baseline).
        try:
            hs = await serp_snapshot.fetch_backlinks_summary(website)
            rows.append({
                "client_id": client_id, "url": website, "is_homepage": True,
                "url_rating": hs.get("url_rating"), "referring_domains": hs.get("referring_domains"),
                "backlinks": hs.get("backlinks"), "captured_at": captured_at,
            })
            homepage_rd = hs.get("referring_domains")
        except Exception as exc:
            logger.warning("page_backlinks.fetch_failed",
                           extra={"client_id": client_id, "url": website, "error": str(exc)})

        # Inner pages — reuse the domain_pages numbers when present (no extra call),
        # else one summary call for a canonical money page outside the top pages.
        for url in inner:
            try:
                dpp = dp_map.get(_norm(url))
                if dpp is not None:
                    ur, rd, bl = dpp.get("page_rating"), dpp.get("referring_domains"), dpp.get("backlinks")
                else:
                    s = await serp_snapshot.fetch_backlinks_summary(url)
                    ur, rd, bl = s.get("url_rating"), s.get("referring_domains"), s.get("backlinks")
                row = {
                    "client_id": client_id, "url": url, "is_homepage": False,
                    "url_rating": ur, "referring_domains": rd, "backlinks": bl, "captured_at": captured_at,
                }
                rows.append(row)
                page_reads.append(row)
            except Exception as exc:  # one bad target must not abort the capture
                logger.warning("page_backlinks.fetch_failed",
                               extra={"client_id": client_id, "url": url, "error": str(exc)})

        if rows:
            supabase.table("page_backlink_profiles").insert(rows).execute()

        offenders = detect_imbalance(homepage_rd, page_reads)
        _sync_imbalance_alert(supabase, client_id, offenders)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"captured": len(rows), "offenders": len(offenders)},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("page_backlinks.job_failed", extra={"job_id": job_id, "client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _sync_imbalance_alert(supabase, client_id: str, offenders: list[dict]) -> None:
    open_alert = (
        supabase.table("offpage_alerts")
        .select("id")
        .eq("client_id", client_id)
        .eq("alert_type", "rd_imbalance")
        .is_("resolved_at", "null")
        .limit(1)
        .execute()
    ).data or []

    if not offenders:
        if open_alert:
            supabase.table("offpage_alerts").update({"resolved_at": "now()"}).eq(
                "id", open_alert[0]["id"]
            ).execute()
        return
    if open_alert:
        return

    worst = max(offenders, key=lambda o: o["referring_domains"])
    message = (
        f"{len(offenders)} inner page{'s' if len(offenders) != 1 else ''} carry more referring "
        f"domains than the home page (worst: {worst['url']} at {worst['referring_domains']:,} RD "
        f"vs homepage {worst['homepage_rd']:,})."
    )
    supabase.table("offpage_alerts").insert(
        {
            "client_id": client_id,
            "alert_type": "rd_imbalance",
            "from_rd": worst["homepage_rd"],
            "to_rd": worst["referring_domains"],
            "message": message,
            "details": {"offenders": offenders},
        }
    ).execute()
    try:  # refresh the Action Plan silently so the rebalance action shows now
        from services.reopt_planner import enqueue_reopt_plan

        enqueue_reopt_plan(client_id, trigger="offpage")
    except Exception:
        logger.warning("page_backlinks.plan_refresh_enqueue_failed", extra={"client_id": client_id})
    notifications.emit(
        client_id,
        kind="offpage_rd_imbalance",
        title="RD imbalance: inner page out-linking the home page",
        summary=message + " Rebalance per the Link Building SOP health check: build RD to the "
        "home page or ease off the inner page (SEO NEO assignee self-corrects — non-escalating).",
        severity="info",
        payload={"link": f"clients/{client_id}/action-plan"},
    )


def get_page_backlinks(client_id: str) -> dict:
    """The per-page backlink monitor read for a client — the latest capture's
    pages + each page's history. Pure DB read, no paid calls."""
    rows = (
        get_supabase().table("page_backlink_profiles").select("*")
        .eq("client_id", client_id).order("captured_at", desc=True).execute()
    ).data or []
    return build_page_view(rows)


def enqueue_page_backlinks(client_id: str) -> bool:
    """Enqueue a one-off per-page capture for a client (dedup against in-flight).
    On-demand: NOT gated on the scheduled-enabled flag, so a user can populate
    the monitor now instead of waiting for the monthly tick. Returns True if a
    job was enqueued, False if one was already pending/running."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "page_backlink_intel").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data
    if existing:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "page_backlink_intel", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()
    return True


def enqueue_due_page_backlinks() -> int:
    """Daily due-check: one page_backlink_intel job per client with tracked
    keywords whose last capture is older than CAPTURE_INTERVAL_DAYS (or absent).
    Gated on DataForSEO creds."""
    if not (settings.page_backlink_intel_enabled and settings.dataforseo_login and settings.dataforseo_password):
        return 0
    supabase = get_supabase()
    try:
        clients = (
            supabase.table("tracked_keywords").select("client_id").execute()
        ).data or []
        client_ids = sorted({r["client_id"] for r in clients})
        if not client_ids:
            return 0
        captures = (
            supabase.table("page_backlink_profiles")
            .select("client_id, captured_at")
            .order("captured_at", desc=True)
            .execute()
        ).data or []
        latest: dict[str, str] = {}
        for c in captures:
            latest.setdefault(c["client_id"], c["captured_at"])
        pending = (
            supabase.table("async_jobs")
            .select("entity_id")
            .eq("job_type", "page_backlink_intel")
            .in_("status", ["pending", "running"])
            .execute()
        ).data or []
        queued = {p.get("entity_id") for p in pending}
    except Exception as exc:
        logger.error("page_backlinks.enqueue_read_failed", extra={"error": str(exc)})
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=CAPTURE_INTERVAL_DAYS)
    count = 0
    for cid in client_ids:
        if cid in queued:
            continue
        ts = latest.get(cid)
        if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) > cutoff:
            continue
        try:
            supabase.table("async_jobs").insert(
                {"job_type": "page_backlink_intel", "entity_id": cid, "payload": {"client_id": cid}}
            ).execute()
            count += 1
        except Exception as exc:
            logger.error("page_backlinks.enqueue_failed", extra={"client_id": cid, "error": str(exc)})
    if count:
        logger.info("page_backlinks.enqueued", extra={"count": count})
    return count
