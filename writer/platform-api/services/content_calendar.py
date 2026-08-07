"""Content calendar — a per-DAY view of the individual content items scheduled
across the suite, so the team can see exactly what content is set to generate on
which day.

Unlike services/content_schedule_feed.py (which returns batch-level *progress*
rows for the "Scheduled Content" card), this flattens both schedulers down to ONE
row per scheduled item, each carrying a concrete `scheduled_at`, so a calendar UI
can place every piece of content on the exact day it will run:

  - the suite Content Scheduler   (`content_batch_items`, joined to `content_batches`), and
  - the Topic Fanout scheduler    (`fanout.scheduled_article_runs`, joined to
                                    `fanout.content_schedules` + `clusters`).

Two scopes: `client_calendar` (one client's workspace view) and `agency_calendar`
(every client at once). Read-only aggregation — no writes, no generation. The
Fanout half is best-effort: any failure reading the `fanout` schema degrades to
suite-only rather than breaking the calendar (mirrors content_schedule_feed).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Cancelled items never generate, so they're excluded from "what runs when".
# Everything else (scheduled / queued / running / complete / failed) is placed on
# its day so the calendar shows both what's coming and what already ran.
_EXCLUDED_STATUSES = ("cancelled",)

# A hard ceiling per source so an unbounded month across every client can't blow
# up the response. A calendar month is far below this; when it's hit the caller
# logs a truncation warning.
_MAX_ITEMS = 5000


# ── pure helpers (no DB — unit tested) ───────────────────────────────────────


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Accept 'YYYY-MM-DD' (or a longer ISO string, first 10 chars); None/garbage
    -> None so the caller falls back to a default."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def resolve_range(
    start: Optional[str], end: Optional[str], *, now: datetime
) -> tuple[str, str]:
    """Resolve the [start, end] query window into padded UTC ISO bounds for the
    `scheduled_at` filter.

    - `start` defaults to the first of the current month; `end` to ~2 months out,
      so an un-parameterised call still returns a useful window.
    - The bounds are padded by a day on each side because the frontend buckets
      items by the *viewer's local* date: an item at 2026-08-01T00:30Z can render
      on Jul 31 in a western timezone, so the query must reach a day earlier/later
      than the visible grid or edge cells drop items.
    """
    today = now.date()
    s = _parse_date(start) or today.replace(day=1)
    e = _parse_date(end) or (s + timedelta(days=62))
    if e < s:
        e = s
    lo = datetime.combine(s - timedelta(days=1), time.min, tzinfo=timezone.utc)
    hi = datetime.combine(e + timedelta(days=1), time.max, tzinfo=timezone.utc)
    return lo.isoformat(), hi.isoformat()


def suite_row(item: dict, batch: Optional[dict], client_name: Optional[str]) -> dict:
    """Normalize one `content_batch_items` row (+ its parent batch) to a calendar
    row."""
    b = batch or {}
    return {
        "source": "content_scheduler",
        "parent_id": item.get("batch_id"),
        "item_id": item.get("id"),
        "client_id": item.get("client_id"),
        "client_name": client_name,
        "content_type": b.get("content_type") or "blog_post",
        "mode": b.get("mode"),
        "label": (item.get("keyword") or "").strip() or "Untitled page",
        "location": item.get("location"),
        "scheduled_at": item.get("scheduled_at"),
        "status": item.get("status"),
    }


def fanout_row(
    run: dict,
    schedule: Optional[dict],
    label: Optional[str],
    client_id: Optional[str],
    client_name: Optional[str],
) -> dict:
    """Normalize one `scheduled_article_runs` row (+ its schedule + resolved
    cluster label) to a calendar row."""
    s = schedule or {}
    return {
        "source": "fanout",
        "parent_id": run.get("content_schedule_id"),
        "item_id": run.get("id"),
        "client_id": client_id,
        "client_name": client_name,
        "content_type": s.get("content_type") or "blog_post",
        "mode": s.get("mode"),
        "label": (label or "").strip() or "Untitled article",
        "location": s.get("location"),
        "scheduled_at": run.get("scheduled_at"),
        "status": run.get("status"),
    }


def _sort_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r.get("scheduled_at") or "", r.get("label") or ""))
    return rows


# ── suite Content Scheduler (content_batch_items) ────────────────────────────


def _batch_map(client, batch_ids: list[str]) -> dict[str, dict]:
    """batch_id -> {content_type, mode} for the batches referenced by a set of
    items (one `in_` query, no N+1)."""
    ids = [b for b in dict.fromkeys(batch_ids) if b]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for start in range(0, len(ids), 500):
        rows = (client.table("content_batches").select("id, content_type, mode")
                .in_("id", ids[start:start + 500]).execute().data or [])
        for r in rows:
            out[r["id"]] = r
    return out


def _suite_rows(
    *, client_id: Optional[str], start_iso: str, end_iso: str,
    client_names: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Suite Content Scheduler items in the window. `client_id` scopes to one
    client; None spans every client (agency view). `client_names` supplies the
    id->name map for the agency view (the per-client view passes a single name in
    via the caller instead)."""
    client = get_supabase()
    q = (client.table("content_batch_items")
         .select("id, batch_id, client_id, keyword, location, status, scheduled_at")
         .gte("scheduled_at", start_iso).lte("scheduled_at", end_iso))
    if client_id:
        q = q.eq("client_id", client_id)
    items = (q.order("scheduled_at").limit(_MAX_ITEMS).execute().data or [])
    items = [it for it in items if it.get("status") not in _EXCLUDED_STATUSES]
    if len(items) >= _MAX_ITEMS:
        logger.warning("content_calendar.suite_truncated", extra={"limit": _MAX_ITEMS})
    if not items:
        return []
    batches = _batch_map(client, [it["batch_id"] for it in items])
    names = client_names or {}
    return [
        suite_row(it, batches.get(it.get("batch_id")), names.get(it.get("client_id")))
        for it in items
    ]


# ── Fanout scheduler (scheduled_article_runs) ────────────────────────────────


def _cluster_labels(fc, cluster_ids: list[str]) -> dict[str, str]:
    """cluster_id -> human label. Prefer the cluster's editorial `name`; fall back
    to its primary keyword's text (what the worker generates the article from)."""
    ids = [c for c in dict.fromkeys(cluster_ids) if c]
    if not ids:
        return {}
    labels: dict[str, str] = {}
    pk_needed: dict[str, str] = {}          # cluster_id -> primary_keyword_id
    for start in range(0, len(ids), 500):
        rows = (fc.table("clusters").select("id, name, primary_keyword_id")
                .in_("id", ids[start:start + 500]).execute().data or [])
        for r in rows:
            if (r.get("name") or "").strip():
                labels[r["id"]] = r["name"]
            elif r.get("primary_keyword_id"):
                pk_needed[r["id"]] = r["primary_keyword_id"]
    if pk_needed:
        try:
            from fanout.storage.silo import get_keyword_texts

            kw = get_keyword_texts(list(pk_needed.values()))
            for cid, pkid in pk_needed.items():
                if kw.get(pkid):
                    labels[cid] = kw[pkid]
        except Exception as exc:  # noqa: BLE001 — labels are cosmetic; degrade to the fallback text
            logger.warning("content_calendar.cluster_label_failed", extra={"error": str(exc)})
    return labels


def _schedule_map(fc, schedule_ids: list[str]) -> dict[str, dict]:
    ids = [s for s in dict.fromkeys(schedule_ids) if s]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for start in range(0, len(ids), 500):
        rows = (fc.table("content_schedules").select("id, content_type, mode, location")
                .in_("id", ids[start:start + 500]).execute().data or [])
        for r in rows:
            out[r["id"]] = r
    return out


def _fanout_rows(
    *, client_id: Optional[str], start_iso: str, end_iso: str,
) -> list[dict]:
    """Fanout scheduled article runs in the window. `client_id` scopes to that
    client's linked sessions; None spans every client-linked session (agency
    view). Best-effort: any failure reading the `fanout` schema returns [] so the
    suite rows still render."""
    try:
        from fanout.storage.supabase_client import get_service_client

        fc = get_service_client()

        # session_id -> client_id for the sessions in scope, dropping any session
        # not linked to a client (an un-linked Fanout session isn't "client
        # content" and has no place on a client/agency calendar).
        sq = fc.table("sessions").select("id, client_id")
        if client_id:
            sq = sq.eq("client_id", client_id)
        else:
            sq = sq.not_.is_("client_id", "null")
        sessions = (sq.execute().data or [])
        session_client = {s["id"]: s.get("client_id") for s in sessions if s.get("client_id")}
        if not session_client:
            return []

        session_ids = list(session_client)
        runs: list[dict] = []
        for start in range(0, len(session_ids), 200):     # keep the `in_` list bounded
            chunk = session_ids[start:start + 200]
            rows = (fc.table("scheduled_article_runs")
                    .select("id, content_schedule_id, session_id, cluster_id, "
                            "scheduled_at, status")
                    .in_("session_id", chunk)
                    .gte("scheduled_at", start_iso).lte("scheduled_at", end_iso)
                    .order("scheduled_at").limit(_MAX_ITEMS).execute().data or [])
            runs.extend(rows)
            if len(runs) >= _MAX_ITEMS:
                logger.warning("content_calendar.fanout_truncated", extra={"limit": _MAX_ITEMS})
                break
        runs = [r for r in runs if r.get("status") not in _EXCLUDED_STATUSES][:_MAX_ITEMS]
        if not runs:
            return []

        schedules = _schedule_map(fc, [r.get("content_schedule_id") for r in runs])
        labels = _cluster_labels(fc, [r.get("cluster_id") for r in runs])

        # Resolve client names (public schema — the Fanout service client is
        # scoped to `fanout`, so this uses the platform service-role client).
        client_ids = list({cid for cid in session_client.values() if cid})
        names = _client_names(client_ids)

        out = []
        for r in runs:
            cid = session_client.get(r.get("session_id"))
            out.append(fanout_row(
                r, schedules.get(r.get("content_schedule_id")),
                labels.get(r.get("cluster_id")), cid, names.get(cid),
            ))
        return out
    except Exception as exc:  # noqa: BLE001 — the Fanout half is additive; degrade cleanly
        logger.warning("content_calendar.fanout_read_failed",
                       extra={"client_id": client_id, "error": str(exc)})
        return []


def _client_names(client_ids: list[str]) -> dict[str, str]:
    ids = [c for c in dict.fromkeys(client_ids) if c]
    if not ids:
        return {}
    client = get_supabase()
    out: dict[str, str] = {}
    for start in range(0, len(ids), 500):
        rows = (client.table("clients").select("id, name")
                .in_("id", ids[start:start + 500]).execute().data or [])
        for r in rows:
            out[r["id"]] = r.get("name")
    return out


# ── public entry points ──────────────────────────────────────────────────────


def client_calendar(client_id: str, start_iso: str, end_iso: str) -> list[dict]:
    """Every scheduled content item for one client in the window — suite batches +
    the client's Fanout runs — flattened and sorted by scheduled_at."""
    name = (_client_names([client_id]) or {}).get(client_id)
    rows = (
        _suite_rows(client_id=client_id, start_iso=start_iso, end_iso=end_iso,
                    client_names={client_id: name})
        + _fanout_rows(client_id=client_id, start_iso=start_iso, end_iso=end_iso)
    )
    return _sort_rows(rows)


def agency_calendar(start_iso: str, end_iso: str) -> list[dict]:
    """Every scheduled content item across all clients in the window — suite
    batches + all client-linked Fanout runs — each row carrying its client's id +
    name, flattened and sorted by scheduled_at."""
    # Names for the suite half: gather the client_ids present, then resolve once.
    suite = _suite_rows(client_id=None, start_iso=start_iso, end_iso=end_iso)
    names = _client_names([r["client_id"] for r in suite if r.get("client_id")])
    for r in suite:
        r["client_name"] = names.get(r.get("client_id"))
    rows = suite + _fanout_rows(client_id=None, start_iso=start_iso, end_iso=end_iso)
    return _sort_rows(rows)
