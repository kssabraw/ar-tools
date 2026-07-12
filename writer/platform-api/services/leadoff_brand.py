"""LeadOff brand footprint — site size + brand mentions (first-pass context).

Two more "how big are the incumbents" signals attached to every tryout and
scout pull (owner request 2026-07-12):

  * **Site size** — Google's indexed-page estimate per competitor domain:
    one `site:domain` organic SERP (live/regular), read `se_results_count`.
    ~$0.002/domain.
  * **Brand mentions** — web mention footprint per business name via the
    DataForSEO **Content Analysis** summary endpoint (purpose-built citation
    index, with sentiment connotations). ~$0.03/brand. Quoted-phrase match;
    generic names ("Pest Control KC") inflate counts — the honest caveat is
    carried in the UI copy, and mentions stay context, never a grade input.

Both cache into app-owned public tables (migration 20260712210000) on the
same 90-day freshness the other LeadOff caches use. Mentions key on the
normalized name GLOBALLY, so franchises hit cache across every market.

Cost discipline: misses are estimated pre-spend (rides the scout estimate +
tryout est_cost through the existing leadoff_spend budget guard).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

COST_SITE_QUERY = 0.002          # serp/google/organic/live/regular, per domain
COST_MENTIONS_PER_BRAND = 0.03   # content_analysis/summary/live, per brand


# ── Pure helpers (unit-tested in tests/test_leadoff_brand.py) ─────────────────

def brand_key(name: str) -> str:
    """Global cache key for a brand's mention footprint — the scanner's norm()
    WITHOUT the |city_id suffix (mentions are name-global; franchises dedupe)."""
    from services.leadoff import _norm
    return _norm(name or "")


def parse_site_count(task: dict[str, Any]) -> Optional[int]:
    """`se_results_count` from a live/regular SERP task — Google's indexed-page
    estimate for a site: query. None when the task carried no result."""
    result = (task.get("result") or [{}])[0] or {}
    count = result.get("se_results_count")
    return int(count) if count is not None else None


def parse_mentions_summary(task: dict[str, Any]) -> Optional[dict[str, Any]]:
    """{citations, positive, negative} from a content_analysis summary task.
    Defensive: the summary's shape has drifted before — missing keys read as
    None rather than raising."""
    result = (task.get("result") or [{}])[0] or {}
    if not result:
        return None
    total = result.get("total_count")
    conn = result.get("connotation_types") or {}
    return {
        "citations": int(total) if total is not None else None,
        "positive": conn.get("positive"),
        "negative": conn.get("negative"),
    }


def footprint_estimate(site_misses: int, mention_misses: int) -> float:
    return round(site_misses * COST_SITE_QUERY
                 + mention_misses * COST_MENTIONS_PER_BRAND, 2)


def median(values: list[float]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    return float(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2)


def attach_footprint(rows: list[dict[str, Any]],
                     top5_by_cat: dict[str, list[dict[str, Any]]],
                     site_lookup: dict[str, Optional[int]],
                     mention_lookup: dict[str, Optional[int]]) -> list[dict[str, Any]]:
    """Decorate tryout category rows with the field's median site size +
    median mention count (from that category's top-5). Pure; rows without
    footprint data pass through unchanged."""
    out = []
    for row in rows:
        top5 = top5_by_cat.get(row.get("category") or "", [])
        pages = [site_lookup.get((c.get("domain") or "").strip())
                 for c in top5 if (c.get("domain") or "").strip()]
        mentions = [mention_lookup.get(brand_key(c.get("business_name") or ""))
                    for c in top5 if (c.get("business_name") or "").strip()]
        decorated = dict(row)
        decorated["field_pages_med"] = median([p for p in pages if p is not None])
        decorated["field_mentions_med"] = median([m for m in mentions if m is not None])
        out.append(decorated)
    return out


def top5_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(business_name, domain) for the top-5 organic maps entries — the same
    field the scanner's serp_top5 keeps. Pure."""
    out = []
    for it in items or []:
        if it.get("type") not in (None, "maps_search", "maps_paid_item"):
            pass  # keep permissive — rank_group filter below is the real gate
        rank = it.get("rank_group") or it.get("rank_absolute")
        if rank is None or rank > 5:
            continue
        name = (it.get("title") or "").strip()
        if not name:
            continue
        domain = (it.get("domain") or "").strip() or None
        out.append({"business_name": name, "domain": domain})
        if len(out) >= 5:
            break
    return out


# ── Cache state + fetch (impure; plumbing borrowed lazily from leadoff_actions
#    to avoid a top-level import cycle — actions imports this module) ──────────

def footprint_state(names_domains: list[dict[str, Any]],
                    now: datetime) -> dict[str, Any]:
    """Which of these businesses' footprint pieces are cache-misses (90-day
    freshness). Input rows carry business_name + domain (domain optional)."""
    from db.supabase_client import get_supabase
    from services.leadoff_actions import _fresh_cutoff

    supabase = get_supabase()
    cutoff = _fresh_cutoff(now)
    domains = sorted({(r.get("domain") or "").strip()
                      for r in names_domains if (r.get("domain") or "").strip()})
    brands = {brand_key(r.get("business_name") or ""): r.get("business_name")
              for r in names_domains if (r.get("business_name") or "").strip()}
    brands.pop("", None)

    fresh_sites = (supabase.table("domain_site_size").select("domain")
                   .in_("domain", domains).gte("pulled_at", cutoff)
                   .execute().data or []) if domains else []
    site_misses = [d for d in domains
                   if d not in {r["domain"] for r in fresh_sites}]
    fresh_mentions = (supabase.table("brand_mentions").select("brand_key")
                      .in_("brand_key", list(brands)).gte("pulled_at", cutoff)
                      .execute().data or []) if brands else []
    mention_misses = {k: v for k, v in brands.items()
                      if k not in {r["brand_key"] for r in fresh_mentions}}
    return {"site_misses": site_misses, "mention_misses": mention_misses,
            "est_cost": footprint_estimate(len(site_misses), len(mention_misses))}


async def fetch_footprint(client, site_misses: list[str],
                          mention_misses: dict[str, str],
                          now: datetime) -> dict[str, int]:
    """Pull the missing pieces and upsert the caches. Best-effort per item —
    a failed domain/brand is skipped (retried on the next pull), except the
    daily-money-limit abort which propagates (scanner lesson #2)."""
    from db.supabase_client import get_supabase
    from services.leadoff_actions import _check_money_limit, _dfs_post

    supabase = get_supabase()
    pulled = {"sites": 0, "mentions": 0}

    # site sizes — one live/regular SERP per domain, batched into one POST
    # (each array element is its own billed task; iterate ALL tasks).
    if site_misses:
        try:
            env = await _dfs_post(client, "/serp/google/organic/live/regular",
                                  [{"keyword": f"site:{d}", "language_code": "en",
                                    "location_code": 2840, "depth": 10}
                                   for d in site_misses])
            rows = []
            for i, task in enumerate(env.get("tasks") or []):
                _check_money_limit(task)
                count = parse_site_count(task)
                rows.append({"domain": site_misses[i], "indexed_pages": count,
                             "pulled_at": now.isoformat()})
            if rows:
                supabase.table("domain_site_size").upsert(rows).execute()
                pulled["sites"] = len(rows)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("leadoff_brand.site_size_failed", extra={"error": str(exc)})

    # brand mentions — one content_analysis summary per brand, batched POST
    if mention_misses:
        keys = list(mention_misses)
        try:
            env = await _dfs_post(client, "/content_analysis/summary/live",
                                  [{"keyword": f'"{(mention_misses[k] or "").lower()}"',
                                    "page_type": ["organization", "blogs", "news",
                                                  "message-boards", "ecommerce"]}
                                   for k in keys])
            rows = []
            for i, task in enumerate(env.get("tasks") or []):
                _check_money_limit(task)
                summary = parse_mentions_summary(task)
                if summary is None:
                    continue
                rows.append({"brand_key": keys[i],
                             "business_name": mention_misses[keys[i]],
                             "citations": summary["citations"],
                             "positive_connotations": summary["positive"],
                             "negative_connotations": summary["negative"],
                             "pulled_at": now.isoformat()})
            if rows:
                supabase.table("brand_mentions").upsert(rows).execute()
                pulled["mentions"] = len(rows)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("leadoff_brand.mentions_failed", extra={"error": str(exc)})
    return pulled


def footprint_lookups(names_domains: list[dict[str, Any]]) -> tuple[dict, dict]:
    """{domain: indexed_pages} + {brand_key: citations} for these businesses,
    from the caches (whatever is there — fresh or stale, reads are free)."""
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    domains = sorted({(r.get("domain") or "").strip()
                      for r in names_domains if (r.get("domain") or "").strip()})
    keys = sorted({brand_key(r.get("business_name") or "")
                   for r in names_domains
                   if (r.get("business_name") or "").strip()} - {""})
    site_rows = (supabase.table("domain_site_size")
                 .select("domain, indexed_pages").in_("domain", domains)
                 .execute().data or []) if domains else []
    mention_rows = (supabase.table("brand_mentions")
                    .select("brand_key, citations, positive_connotations, "
                            "negative_connotations").in_("brand_key", keys)
                    .execute().data or []) if keys else []
    return ({r["domain"]: r.get("indexed_pages") for r in site_rows},
            {r["brand_key"]: r.get("citations") for r in mention_rows})
