"""Authority reports (RD / DR / UR) for the rank trackers.

An on-demand comparison of link authority between the client and the
competitors each tracker already knows about:

  * **Organic** — per tracked keyword: the latest competitive SERP snapshot
    names who ranks (top-10 URLs + domains + the client's own position); this
    report re-pulls FRESH DR (domain), UR (ranking page) and RD (domain) for
    every ranking party via the DataForSEO bulk endpoints.
  * **Maps** — per client: the latest completed geo-grid scan's local-pack
    leaderboard names the competitors (with websites); this report pulls DR /
    homepage UR / RD for each competitor domain vs the client.

Cost: TWO billed calls per report (one bulk_ranks over all domains+URLs, one
bulk_referring_domains over the domains), budget-reserved against the shared
daily backlink budget. Pure assembly helpers are unit-tested; the builders are
thin I/O over them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from db.supabase_client import get_supabase
from services import backlinks_api
from services.backlink_explorer import _reserve_budget  # shared daily budget
from services.dataforseo_rank import extract_domain

logger = logging.getLogger(__name__)

_MAPS_MAX_COMPETITORS = 10
_REPORT_CALL_COST = 2  # bulk_ranks + bulk_referring_domains


# ----------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ----------------------------------------------------------------------------
def homepage_url(domain: Optional[str]) -> Optional[str]:
    """The canonical homepage target for a bare domain (UR lookups)."""
    return f"https://{domain}/" if domain else None


def organic_rows(results: list[dict], client_domain: Optional[str],
                 client_position, client_url: Optional[str]) -> list[dict]:
    """Row skeletons for the organic report from SERP-snapshot results
    ({position, url, domain} each). The client is flagged by domain match; when
    the client ranks nowhere in the fetched set, an unranked client row is
    appended so the comparison always includes them."""
    cd = (client_domain or "").lower()
    rows: list[dict] = []
    client_seen = False
    for r in sorted(results, key=lambda x: (x.get("position") is None, x.get("position") or 0)):
        domain = (r.get("domain") or "").lower() or None
        is_client = bool(cd) and domain is not None and (domain == cd or domain.endswith("." + cd))
        client_seen = client_seen or is_client
        rows.append({
            "position": r.get("position"),
            "url": r.get("url"),
            "domain": domain,
            "is_client": is_client,
        })
    if cd and not client_seen:
        rows.append({
            "position": client_position,
            "url": client_url or homepage_url(cd),
            "domain": cd,
            "is_client": True,
        })
    return rows


def maps_rows(leaderboard: list[dict], client_domain: Optional[str],
              client_name: Optional[str], limit: int = _MAPS_MAX_COMPETITORS) -> list[dict]:
    """Row skeletons for the maps report from geo-grid leaderboard entries
    ({place_id, name, website, top3_pins, found_pins} — repeated per keyword, so
    aggregate by place_id). Sorted by pack presence; the client leads."""
    by_place: dict = {}
    for c in leaderboard:
        pid = c.get("place_id") or c.get("name")
        if not pid:
            continue
        agg = by_place.setdefault(pid, {"name": c.get("name"), "website": None,
                                        "top3_pins": 0, "found_pins": 0})
        agg["top3_pins"] += c.get("top3_pins") or 0
        agg["found_pins"] += c.get("found_pins") or 0
        agg["website"] = agg["website"] or c.get("website")
    cd = (client_domain or "").lower()
    competitors = []
    for agg in by_place.values():
        domain = extract_domain(agg.get("website") or "")
        if cd and domain and (domain == cd or domain.endswith("." + cd)):
            continue  # the client shows up in its own leaderboard — rendered as the client row
        competitors.append({
            "name": agg.get("name"),
            "domain": domain or None,
            "top3_pins": agg["top3_pins"],
            "found_pins": agg["found_pins"],
            "is_client": False,
        })
    competitors.sort(key=lambda r: (r["top3_pins"], r["found_pins"]), reverse=True)
    rows = [{"name": client_name or "You", "domain": cd or None,
             "top3_pins": None, "found_pins": None, "is_client": True}]
    rows.extend(competitors[:limit])
    return rows


def merge_authority(rows: list[dict], ranks: dict, rds: dict) -> list[dict]:
    """Attach dr / ur / rd onto row skeletons. DR + RD key on the row's domain;
    UR keys on the row's page URL (organic) or homepage convention (maps)."""
    out = []
    for r in rows:
        domain = r.get("domain")
        url = r.get("url") or homepage_url(domain)
        out.append({
            **r,
            "dr": ranks.get(domain) if domain else None,
            "ur": ranks.get(url) if url else None,
            "rd": rds.get(domain) if domain else None,
        })
    return out


def collect_targets(rows: list[dict]) -> tuple[list[str], list[str]]:
    """(rank_targets, rd_targets) for the two bulk calls: domains + page URLs
    for ranks (DR + UR in one call), domains only for RD. Deduped, ordered."""
    domains, urls = [], []
    for r in rows:
        d = r.get("domain")
        if d and d not in domains:
            domains.append(d)
        u = r.get("url") or homepage_url(d)
        if u and u not in urls:
            urls.append(u)
    return domains + urls, list(domains)


# ----------------------------------------------------------------------------
# Builders (I/O)
# ----------------------------------------------------------------------------
async def _fetch_and_merge(rows: list[dict]) -> list[dict]:
    rank_targets, rd_targets = collect_targets(rows)
    if not rank_targets:
        return merge_authority(rows, {}, {})
    _reserve_budget(_REPORT_CALL_COST)
    ranks_r, rds_r = await asyncio.gather(
        backlinks_api.fetch_bulk_ranks(rank_targets),
        backlinks_api.fetch_bulk_referring_domains(rd_targets),
        return_exceptions=True,
    )
    ranks = ranks_r if isinstance(ranks_r, dict) else {}
    rds = rds_r if isinstance(rds_r, dict) else {}
    for label, res in (("bulk_ranks", ranks_r), ("bulk_rd", rds_r)):
        if isinstance(res, Exception):
            logger.warning("authority_report_partial", extra={"call": label, "error": str(res)})
    return merge_authority(rows, ranks, rds)


async def build_organic_authority(client_id: str, keyword_id: str) -> dict:
    """Fresh RD/DR/UR for everyone in a keyword's latest SERP snapshot."""
    sb = get_supabase()
    snaps = (
        sb.table("serp_snapshots").select("id, captured_at, keyword, client_rank, client_url")
        .eq("keyword_id", keyword_id).order("captured_at", desc=True).limit(1).execute()
    ).data or []
    if not snaps:
        return {"needs_snapshot": True, "rows": []}
    snap = snaps[0]
    results = (
        sb.table("serp_snapshot_results").select("position, url, domain")
        .eq("snapshot_id", snap["id"]).order("position").execute()
    ).data or []
    client = (sb.table("clients").select("website_url").eq("id", client_id).limit(1).execute()).data
    client_domain = extract_domain((client or [{}])[0].get("website_url") or "")
    rows = organic_rows(results, client_domain, snap.get("client_rank"), snap.get("client_url"))
    return {
        "kind": "organic",
        "keyword": snap.get("keyword"),
        "snapshot_captured_at": snap.get("captured_at"),
        "rows": await _fetch_and_merge(rows),
    }


async def build_maps_authority(client_id: str) -> dict:
    """Fresh RD/DR/homepage-UR for the latest geo-grid scan's local-pack
    leaderboard vs the client."""
    from services.competitor_intel import _latest_maps_leaderboard

    sb = get_supabase()
    leaderboard = _latest_maps_leaderboard(sb, client_id)
    if not leaderboard:
        return {"needs_scan": True, "rows": []}
    client = (sb.table("clients").select("name, website_url").eq("id", client_id).limit(1).execute()).data
    crow = (client or [{}])[0]
    client_domain = extract_domain(crow.get("website_url") or "")
    rows = maps_rows(leaderboard, client_domain, crow.get("name"))
    return {"kind": "maps", "rows": await _fetch_and_merge(rows)}
