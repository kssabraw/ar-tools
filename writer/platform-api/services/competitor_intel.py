"""Unified competitive intelligence (strategist roadmap phase 2).

Competitor data already exists per-module — maps leaderboards (place_id),
SERP snapshots + backlink profiles (domain), AI-visibility competitors
(name), competitor GBP + review time-series (place_id) — but nothing ties
"Bob's Roofing" together across them. This module adds:

  * the REGISTRY (`client_competitors`): auto-discovered from the maps
    leaderboard, recurring organic top-10 domains and the AI-visibility list,
    plus manual adds. Auto rows are never auto-removed — curation is human.
  * PROFILES (`build_profiles`): one assembled read per competitor joining
    every module — local-pack presence, GBP rating/reviews, DR/RD vs the
    client, organic top-10 appearances across tracked keywords, review
    velocity, new content — all deterministic, all from stored data (the
    weekly job's only network calls are the content-watch sitemap reads).
  * CONTENT WATCH (`run_content_watch`): per-competitor site URL index
    (sitemap → DataForSEO site: fallback, reusing site_page_index) diffed
    against `competitor_pages`. The first index is a baseline (never "new");
    later syncs surface genuinely new URLs → the "competitor published new
    content" signal + an info notification.

Runs as the weekly `competitor_intel` async job per client (shared
scheduler). Pure helpers (domain normalization, discovery, velocity) are
unit-tested; everything degrades per-competitor, never fatally.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_MAX_AUTO_MAPS = 5        # top local-pack competitors auto-registered per sync
_MAX_AUTO_ORGANIC = 5     # top recurring organic domains auto-registered per sync
_MIN_ORGANIC_KEYWORDS = 2  # a domain must rank top-10 for >= this many tracked keywords
_RECENT_PAGES_DAYS = 30
_PROFILE_KEYWORD_CAP = 8  # keywords listed per competitor in a profile


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def normalize_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Bare registrable host: no scheme, no www, no path, casefolded. Pure."""
    raw = (url_or_domain or "").strip().lower()
    if not raw:
        return None
    if "//" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def discover_from_maps(scan_competitors: list[dict], limit: int = _MAX_AUTO_MAPS) -> list[dict]:
    """Top local-pack competitors from a scan's leaderboard(s), by pack
    presence. Input rows: {place_id, name, website, top3_pins, found_pins}.
    Aggregates across keywords (max pins per place_id). Pure."""
    by_place: dict[str, dict] = {}
    for c in scan_competitors:
        pid = c.get("place_id")
        if not pid or not c.get("name"):
            continue
        cur = by_place.get(pid)
        if not cur or (c.get("top3_pins") or 0) > (cur.get("top3_pins") or 0):
            by_place[pid] = c
    ranked = sorted(
        by_place.values(),
        key=lambda c: ((c.get("top3_pins") or 0), (c.get("found_pins") or 0)),
        reverse=True,
    )
    return [
        {
            "name": c["name"],
            "place_id": c.get("place_id"),
            "domain": normalize_domain(c.get("website")),
            "source": "maps",
        }
        for c in ranked[:limit]
    ]


def discover_from_serp(
    rows: list[dict], client_domain: Optional[str],
    min_keywords: int = _MIN_ORGANIC_KEYWORDS, limit: int = _MAX_AUTO_ORGANIC,
) -> list[dict]:
    """Domains recurring in the organic top-10 across tracked keywords.
    Input rows: {keyword, domain, is_client, position}. A domain must appear
    for >= min_keywords distinct keywords; the client's own domain (and any
    is_client row) never qualifies. Pure."""
    client_domain = normalize_domain(client_domain)
    per_domain: dict[str, set] = {}
    best_pos: dict[str, float] = {}
    for r in rows:
        if r.get("is_client"):
            continue
        dom = normalize_domain(r.get("domain"))
        if not dom or dom == client_domain:
            continue
        pos = r.get("position")
        if pos is None or pos > 10:
            continue
        per_domain.setdefault(dom, set()).add((r.get("keyword") or "").casefold())
        if dom not in best_pos or pos < best_pos[dom]:
            best_pos[dom] = pos
    ranked = sorted(
        ((dom, kws) for dom, kws in per_domain.items() if len(kws) >= min_keywords),
        key=lambda item: (-len(item[1]), best_pos.get(item[0], 99)),
    )
    return [
        {"name": dom, "place_id": None, "domain": dom, "source": "organic"}
        for dom, _ in ranked[:limit]
    ]


def review_velocity(review_dates: list[Optional[str]], today: date, days: int = 90) -> float:
    """Reviews per 30 days over the trailing window. Pure."""
    cutoff = date.fromordinal(today.toordinal() - days)
    n = 0
    for d in review_dates:
        try:
            if d and date.fromisoformat(str(d)[:10]) >= cutoff:
                n += 1
        except ValueError:
            continue
    return round(n * 30.0 / days, 1)


# ---------------------------------------------------------------------------
# Registry sync (auto-discovery; DB-only reads)
# ---------------------------------------------------------------------------
def _existing_competitors(supabase, client_id: str, include_inactive: bool = True) -> list[dict]:
    q = supabase.table("client_competitors").select("*").eq("client_id", client_id)
    if not include_inactive:
        q = q.eq("active", True)
    return q.execute().data or []


def _latest_maps_leaderboard(supabase, client_id: str) -> list[dict]:
    scans = (
        supabase.table("maps_scans").select("id")
        .eq("client_id", client_id).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data
    if not scans:
        return []
    results = (
        supabase.table("maps_scan_results").select("competitors")
        .eq("scan_id", scans[0]["id"]).execute()
    ).data or []
    out: list[dict] = []
    for r in results:
        out.extend(r.get("competitors") or [])
    return out


def _latest_serp_rows(supabase, client_id: str) -> list[dict]:
    """Top-10 rows of each tracked keyword's LATEST snapshot."""
    snaps = (
        supabase.table("serp_snapshots").select("id, keyword_id, keyword, captured_at")
        .eq("client_id", client_id).eq("status", "complete")
        .order("captured_at", desc=True).limit(200).execute()
    ).data or []
    latest_per_kw: dict[str, dict] = {}
    for s in snaps:
        kid = s.get("keyword_id")
        if kid and kid not in latest_per_kw:
            latest_per_kw[kid] = s
    rows: list[dict] = []
    for s in latest_per_kw.values():
        results = (
            supabase.table("serp_snapshot_results")
            .select("domain, position, is_client, url")
            .eq("snapshot_id", s["id"]).lte("position", 10).execute()
        ).data or []
        for r in results:
            rows.append({**r, "keyword": s.get("keyword")})
    return rows


def sync_registry(client_id: str) -> dict:
    """Auto-discover competitors from every module and upsert the registry.

    Existing rows only gain sources / identity fields — auto-discovery never
    deactivates or renames a manually curated row."""
    supabase = get_supabase()
    client = (
        supabase.table("clients").select("website_url").eq("id", client_id).limit(1).execute()
    ).data
    client_domain = normalize_domain((client or [{}])[0].get("website_url"))

    candidates: list[dict] = []
    try:
        candidates += discover_from_maps(_latest_maps_leaderboard(supabase, client_id))
    except Exception as exc:
        logger.warning("competitor_intel.maps_discovery_failed", extra={"client_id": client_id, "error": str(exc)})
    try:
        candidates += discover_from_serp(_latest_serp_rows(supabase, client_id), client_domain)
    except Exception as exc:
        logger.warning("competitor_intel.serp_discovery_failed", extra={"client_id": client_id, "error": str(exc)})
    try:
        for b in (
            supabase.table("brand_tracked_competitors")
            .select("competitor_name, competitor_website, google_place_id")
            .eq("client_id", client_id).execute()
        ).data or []:
            candidates.append({
                "name": b.get("competitor_name"),
                "domain": normalize_domain(b.get("competitor_website")),
                "place_id": b.get("google_place_id"),
                "source": "ai_visibility",
            })
    except Exception as exc:
        logger.warning("competitor_intel.brand_discovery_failed", extra={"client_id": client_id, "error": str(exc)})

    existing = _existing_competitors(supabase, client_id)
    by_domain = {c["domain"]: c for c in existing if c.get("domain")}
    by_place = {c["place_id"]: c for c in existing if c.get("place_id")}
    by_name = {(c.get("name") or "").casefold(): c for c in existing}

    added = 0
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for cand in candidates:
        if not cand.get("name"):
            continue
        if cand.get("domain") and cand["domain"] == client_domain:
            continue
        match = (
            (cand.get("place_id") and by_place.get(cand["place_id"]))
            or (cand.get("domain") and by_domain.get(cand["domain"]))
            or by_name.get(cand["name"].casefold())
        )
        try:
            if match:
                changes: dict = {"last_seen": now}
                sources = list(match.get("sources") or [])
                if cand["source"] not in sources:
                    changes["sources"] = sources + [cand["source"]]
                # Fill identity gaps (a maps row learns its domain, etc.) —
                # never overwrite an existing value.
                if cand.get("domain") and not match.get("domain") and cand["domain"] not in by_domain:
                    changes["domain"] = cand["domain"]
                if cand.get("place_id") and not match.get("place_id") and cand["place_id"] not in by_place:
                    changes["place_id"] = cand["place_id"]
                supabase.table("client_competitors").update(changes).eq("id", match["id"]).execute()
                match.update(changes)
                updated += 1
            else:
                row = {
                    "client_id": client_id,
                    "name": cand["name"],
                    "domain": cand.get("domain"),
                    "place_id": cand.get("place_id"),
                    "sources": [cand["source"]],
                }
                inserted = (supabase.table("client_competitors").insert(row).execute()).data[0]
                added += 1
                if inserted.get("domain"):
                    by_domain[inserted["domain"]] = inserted
                if inserted.get("place_id"):
                    by_place[inserted["place_id"]] = inserted
                by_name[inserted["name"].casefold()] = inserted
        except Exception as exc:  # a dup race / bad row must not abort the sync
            logger.warning(
                "competitor_intel.upsert_failed",
                extra={"client_id": client_id, "candidate": cand.get("name"), "error": str(exc)},
            )
    return {"added": added, "updated": updated, "candidates": len(candidates)}


# ---------------------------------------------------------------------------
# Content watch (the only network calls — per-competitor sitemap reads)
# ---------------------------------------------------------------------------
async def run_content_watch(client_id: str) -> dict:
    """Index each active competitor's site and record genuinely new URLs."""
    from services.site_page_index import discover_site_urls

    supabase = get_supabase()
    client = (
        supabase.table("clients").select("rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ).data
    location_code = (client or [{}])[0].get("rank_tracking_location_code") or 2840

    competitors = [
        c for c in _existing_competitors(supabase, client_id, include_inactive=False)
        if c.get("domain")
    ]
    now = datetime.now(timezone.utc).isoformat()
    new_by_competitor: dict[str, list[str]] = {}
    for comp in competitors:
        try:
            urls, source = await discover_site_urls(f"https://{comp['domain']}", location_code)
            urls = urls[: settings.competitor_watch_max_pages]
            if not urls:
                continue
            known = {
                r["url"] for r in (
                    supabase.table("competitor_pages").select("url")
                    .eq("competitor_id", comp["id"]).execute()
                ).data or []
            }
            fresh = [u for u in urls if u not in known]
            is_baseline = not known  # first index of this competitor
            for i in range(0, len(fresh), 200):
                supabase.table("competitor_pages").insert([
                    {
                        "competitor_id": comp["id"],
                        "client_id": client_id,
                        "url": u,
                        "is_baseline": is_baseline,
                    }
                    for u in fresh[i : i + 200]
                ]).execute()
            if fresh and not is_baseline:
                new_by_competitor[comp["name"]] = fresh
            supabase.table("client_competitors").update({"last_synced_at": now}).eq(
                "id", comp["id"]
            ).execute()
        except Exception as exc:  # one dead site must not abort the watch
            logger.warning(
                "competitor_intel.watch_failed",
                extra={"client_id": client_id, "competitor": comp.get("name"), "error": str(exc)},
            )
    # Competitors without a domain still get their sync clock advanced so the
    # due-check doesn't re-enqueue the client daily for them.
    for comp in _existing_competitors(supabase, client_id, include_inactive=False):
        if not comp.get("domain"):
            supabase.table("client_competitors").update({"last_synced_at": now}).eq(
                "id", comp["id"]
            ).execute()

    if new_by_competitor:
        from services import notifications

        total = sum(len(v) for v in new_by_competitor.values())
        lines = [
            f"{name}: {len(urls)} new page{'s' if len(urls) != 1 else ''}"
            for name, urls in sorted(new_by_competitor.items())
        ]
        notifications.emit(
            client_id,
            "competitor_content",
            f"Competitors published {total} new page{'s' if total != 1 else ''}",
            summary="; ".join(lines)[:500],
            severity="info",
            payload={"new_pages": {k: v[:20] for k, v in new_by_competitor.items()}},
        )
    return {"competitors_watched": len(competitors), "new_pages": {k: len(v) for k, v in new_by_competitor.items()}}


# ---------------------------------------------------------------------------
# Profile assembly (deterministic, stored data only)
# ---------------------------------------------------------------------------
def build_profiles(client_id: str, today: Optional[date] = None) -> dict:
    """Every active competitor profiled across all modules, plus the client's
    own comparison values. Each module join is isolated best-effort."""
    supabase = get_supabase()
    today = today or date.today()
    competitors = _existing_competitors(supabase, client_id, include_inactive=False)
    if not competitors:
        return {"competitors": [], "client": {}}

    # Client-side comparison values.
    client_row = (
        supabase.table("clients").select("website_url, gbp").eq("id", client_id).limit(1).execute()
    ).data or [{}]
    gbp = client_row[0].get("gbp") or {}
    client_ctx: dict = {
        "domain": normalize_domain(client_row[0].get("website_url")),
        "gbp_rating": gbp.get("rating"),
        "gbp_review_count": gbp.get("review_count") or gbp.get("reviews_count"),
    }
    try:
        from services import backlink_intel

        intel = backlink_intel.get_backlink_intel(client_id)
        client_ctx["domain_rating"] = (intel.get("client") or {}).get("domain_rating")
        client_ctx["referring_domains"] = (intel.get("client") or {}).get("referring_domains")
        backlinks_by_domain = {
            normalize_domain(c.get("domain")): c for c in intel.get("competitors") or []
        }
    except Exception:
        backlinks_by_domain = {}

    # Maps leaderboard (latest scan) by place_id and by normalized name.
    maps_by_place: dict[str, dict] = {}
    maps_by_name: dict[str, dict] = {}
    try:
        for c in _latest_maps_leaderboard(supabase, client_id):
            if c.get("place_id"):
                cur = maps_by_place.get(c["place_id"])
                if not cur or (c.get("top3_pins") or 0) > (cur.get("top3_pins") or 0):
                    maps_by_place[c["place_id"]] = c
            if c.get("name"):
                maps_by_name.setdefault(c["name"].casefold(), c)
    except Exception:
        pass

    # Latest GBP capture per place_id.
    gbp_by_place: dict[str, dict] = {}
    try:
        for r in (
            supabase.table("competitor_gbp_profiles")
            .select("place_id, name, rating, review_count, primary_category, captured_at")
            .eq("client_id", client_id).order("captured_at", desc=True).limit(400).execute()
        ).data or []:
            gbp_by_place.setdefault(r["place_id"], r)
    except Exception:
        pass

    # Organic top-10 appearances per domain (latest snapshot per keyword).
    organic_by_domain: dict[str, dict] = {}
    try:
        for r in _latest_serp_rows(supabase, client_id):
            dom = normalize_domain(r.get("domain"))
            if not dom or r.get("is_client"):
                continue
            entry = organic_by_domain.setdefault(dom, {"keywords": [], "best_position": None})
            if r.get("keyword") and r["keyword"] not in entry["keywords"]:
                entry["keywords"].append(r["keyword"])
            pos = r.get("position")
            if pos is not None and (entry["best_position"] is None or pos < entry["best_position"]):
                entry["best_position"] = pos
    except Exception:
        pass

    # Review velocity per place_id (trailing 90d, incl. the client's own).
    velocity_by_place: dict[str, float] = {}
    client_velocity: Optional[float] = None
    try:
        rows = (
            supabase.table("reviews").select("place_id, is_client, review_date")
            .eq("client_id", client_id)
            .gte("review_date", date.fromordinal(today.toordinal() - 90).isoformat())
            .execute()
        ).data or []
        dates_by_place: dict[str, list] = {}
        client_dates: list = []
        for r in rows:
            (client_dates if r.get("is_client") else dates_by_place.setdefault(r.get("place_id"), [])).append(
                r.get("review_date")
            )
        velocity_by_place = {p: review_velocity(d, today) for p, d in dates_by_place.items()}
        client_velocity = review_velocity(client_dates, today) if client_dates else None
    except Exception:
        pass
    client_ctx["review_velocity_30d"] = client_velocity

    # New content (non-baseline pages, trailing window) per competitor.
    new_pages_by_comp: dict[str, list[dict]] = {}
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_RECENT_PAGES_DAYS)).isoformat()
        for r in (
            supabase.table("competitor_pages").select("competitor_id, url, first_seen")
            .eq("client_id", client_id).eq("is_baseline", False)
            .gte("first_seen", cutoff).order("first_seen", desc=True).limit(400).execute()
        ).data or []:
            new_pages_by_comp.setdefault(r["competitor_id"], []).append(
                {"url": r["url"], "first_seen": r["first_seen"]}
            )
    except Exception:
        pass

    profiles: list[dict] = []
    for comp in competitors:
        dom = normalize_domain(comp.get("domain"))
        maps_row = (
            (comp.get("place_id") and maps_by_place.get(comp["place_id"]))
            or maps_by_name.get((comp.get("name") or "").casefold())
        ) or {}
        gbp_row = (comp.get("place_id") and gbp_by_place.get(comp["place_id"])) or {}
        bl_row = (dom and backlinks_by_domain.get(dom)) or {}
        organic = (dom and organic_by_domain.get(dom)) or {}
        profiles.append({
            "id": comp["id"],
            "name": comp.get("name"),
            "domain": dom,
            "place_id": comp.get("place_id"),
            "sources": comp.get("sources") or [],
            "notes": comp.get("notes"),
            "local_pack": {
                "found_pins": maps_row.get("found_pins"),
                "top3_pins": maps_row.get("top3_pins"),
                "avg_rank": maps_row.get("avg_rank"),
            } if maps_row else None,
            "gbp": {
                "rating": gbp_row.get("rating"),
                "review_count": gbp_row.get("review_count"),
                "primary_category": gbp_row.get("primary_category"),
                "captured_at": gbp_row.get("captured_at"),
            } if gbp_row else None,
            "backlinks": {
                "domain_rating": bl_row.get("domain_rating"),
                "referring_domains": bl_row.get("referring_domains"),
            } if bl_row else None,
            "organic": {
                "top10_keyword_count": len(organic.get("keywords") or []),
                "keywords": (organic.get("keywords") or [])[:_PROFILE_KEYWORD_CAP],
                "best_position": organic.get("best_position"),
            } if organic else None,
            "review_velocity_30d": velocity_by_place.get(comp.get("place_id")),
            "new_pages_30d": len(new_pages_by_comp.get(comp["id"], [])),
            "recent_pages": new_pages_by_comp.get(comp["id"], [])[:10],
            "last_synced_at": comp.get("last_synced_at"),
        })
    # Most threatening first: organic breadth, then pack presence, then DR.
    profiles.sort(key=lambda p: (
        -((p.get("organic") or {}).get("top10_keyword_count") or 0),
        -((p.get("local_pack") or {}).get("top3_pins") or 0),
        -((p.get("backlinks") or {}).get("domain_rating") or 0),
    ))
    return {"competitors": profiles, "client": client_ctx}


# ---------------------------------------------------------------------------
# Job + scheduler plumbing
# ---------------------------------------------------------------------------
def enqueue_competitor_intel(client_id: str) -> Optional[str]:
    """Enqueue a sync+watch job (deduped against an in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "competitor_intel").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    row = (
        supabase.table("async_jobs").insert({
            "job_type": "competitor_intel",
            "entity_id": client_id,
            "payload": {"client_id": client_id},
        }).execute()
    ).data[0]
    return row["id"]


async def run_competitor_intel_job(job: dict) -> None:
    """async_jobs handler: registry sync (DB reads) + content watch (network)."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id") or job.get("entity_id")
    supabase = get_supabase()
    try:
        sync = sync_registry(client_id)
        watch = await run_content_watch(client_id)
        result = {"sync": sync, "watch": watch}
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:
        logger.warning("competitor_intel.job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()


def enqueue_due_competitor_intel() -> int:
    """Weekly due-check (daily tick): enqueue one job per client whose
    registry hasn't synced in competitor_intel_interval_days — plus a first
    sync for clients with signals (a maps scan or SERP snapshots) but no
    registry yet."""
    if not settings.competitor_intel_enabled:
        return 0
    supabase = get_supabase()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.competitor_intel_interval_days)
    due: set[str] = set()
    try:
        rows = (
            supabase.table("client_competitors").select("client_id, last_synced_at").execute()
        ).data or []
        latest: dict[str, Optional[str]] = {}
        for r in rows:
            cid = r["client_id"]
            ts = r.get("last_synced_at")
            if cid not in latest or (ts or "") > (latest[cid] or ""):
                latest[cid] = ts
        for cid, ts in latest.items():
            if ts is None or datetime.fromisoformat(ts.replace("Z", "+00:00")) <= cutoff:
                due.add(cid)
        # Bootstrap: clients with a completed maps scan but no registry rows.
        seeded = {r["client_id"] for r in rows}
        for s in (
            supabase.table("maps_scans").select("client_id")
            .eq("status", "complete").execute()
        ).data or []:
            if s["client_id"] not in seeded:
                due.add(s["client_id"])
    except Exception as exc:
        logger.error("competitor_intel.due_check_failed", extra={"error": str(exc)})
        return 0
    if not due:
        return 0
    try:
        pending = {
            r["entity_id"] for r in (
                supabase.table("async_jobs").select("entity_id")
                .eq("job_type", "competitor_intel")
                .in_("status", ["pending", "running"]).execute()
            ).data or []
        }
    except Exception:
        pending = set()
    count = 0
    for cid in due - pending:
        try:
            enqueue_competitor_intel(cid)
            count += 1
        except Exception as exc:
            logger.warning("competitor_intel.enqueue_failed", extra={"client_id": cid, "error": str(exc)})
    if count:
        logger.info("competitor_intel.enqueued", extra={"count": count})
    return count
