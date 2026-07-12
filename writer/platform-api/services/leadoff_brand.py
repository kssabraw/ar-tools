"""LeadOff brand footprint — site size + the three mention signals.

Owner refinement 2026-07-12: brand strength isn't one number. Per top-5
competitor we carry:

  * **Site size** — Google's indexed-page estimate (`site:domain` live/regular
    SERP `se_results_count`, ~$0.002/domain).
  * **citations** — TOTAL web mentions from the DataForSEO Content Analysis
    index. A content index, not a link index — this already counts unlinked
    mentions; the split below is what distinguishes them.
  * **unlinked_mentions** — mentioning domains MINUS linking domains (Content
    Analysis `search` domains ∖ Backlinks referring-domains list). Deep tier.
  * **nap_citations** — mentions of the business PHONE NUMBER (globally
    unique → immune to generic-name inflation; ≈ structured NAP citations).

Generic names ("Pest Control KC" — category+city+stopword tokens) never trust
a bare-name count: their mention rows are fetched via `search` and kept only
when the snippet co-occurs with the city or phone (pure Python filter, free).

Two tiers, matching first-pass vs Pass-2 economics:
  * **light** (tryout): summary count per distinctive brand (~$0.03);
    generic brands get search+filter (~$0.06) + phone-NAP (~$0.03).
  * **deep** (scout): every brand gets search (+domains for the unlinked
    split, ~$0.06) + referring-domains list (~$0.05) + phone-NAP (~$0.03),
    plus one Maps SERP for the top-5 phones (~$0.004/market).

Caches in app-owned public tables (migrations 20260712210000/220000), 90-day
freshness; a light row is upgraded by the next deep pull (missing
unlinked_mentions = deep-tier cache miss). Misses ride the scout estimate +
the daily budget guard. Context only — never a grade input.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

COST_SITE_QUERY = 0.002            # serp/google/organic/live/regular, per domain
COST_MENTIONS_LIGHT = 0.03         # content_analysis/summary/live, per brand
COST_MENTIONS_SEARCH = 0.06        # content_analysis/search/live w/ rows
COST_NAP_QUERY = 0.03              # phone-number summary, per brand
COST_UNLINKED_LIST = 0.05          # backlinks/referring_domains/live w/ rows
COST_PHONE_SERP = 0.004            # one maps SERP for the top-5 phones (scout)
_SEARCH_LIMIT = 1000               # content-analysis rows per brand (cap)


# ── Pure helpers (unit-tested in tests/test_leadoff_brand.py) ─────────────────

def brand_key(name: str) -> str:
    """Global cache key for a brand's mention footprint — the scanner's norm()
    WITHOUT the |city_id suffix (mentions are name-global; franchises dedupe)."""
    from services.leadoff import _norm
    return _norm(name or "")


def digits(phone: Optional[str]) -> str:
    return re.sub(r"\D", "", phone or "")


def is_generic_name(name: str, category_name: str, city_name: str) -> bool:
    """True when every word of the business name is a category word, a city
    word, the city's initials ("KC"), or a field-generic stopword — i.e. the
    name carries no distinctive brand token, so a bare-name mention count
    would count the *topic*, not the business."""
    from services.leadoff_actions import STOP

    name_tokens = re.findall(r"[a-z]+", (name or "").lower())
    if not name_tokens:
        return True
    city_words = re.findall(r"[a-z]+", (city_name or "").lower())
    initials = "".join(w[0] for w in city_words if w)
    allowed = (set(re.findall(r"[a-z]+", (category_name or "").lower()))
               | set(city_words) | set(STOP)
               | {"best", "top", "pro", "pros", "local", "expert",
                  "experts", "quality", "affordable"})
    if initials:
        allowed.add(initials)
    return all(t in allowed or len(t) <= 1 for t in name_tokens)


def text_of_row(row: dict[str, Any]) -> str:
    """Searchable text of one content-analysis search row (defensive across
    shape drift: known fields first, nested content_info supported)."""
    parts = []
    info = row.get("content_info") or {}
    for v in (info.get("title"), info.get("snippet"), info.get("content"),
              row.get("title"), row.get("snippet"), row.get("main_title"),
              row.get("url")):
        if v:
            parts.append(str(v))
    return " ".join(parts).lower()


def filter_rows_by_locale(rows: list[dict[str, Any]], city_name: str,
                          phone: Optional[str]) -> list[dict[str, Any]]:
    """Generic-name rescue: keep only mention rows whose text co-occurs with
    the city name or the phone number — a page saying 'Pest Control KC' that
    never mentions Kansas City or the phone is counting the topic."""
    city = (city_name or "").lower().strip()
    ph = digits(phone)
    out = []
    for r in rows:
        text = text_of_row(r)
        if (city and city in text) or (ph and ph in digits(text)):
            out.append(r)
    return out


def _norm_domain(d: Optional[str]) -> str:
    d = (d or "").strip().lower()
    if "//" in d:
        d = urlparse(d).netloc or d
    return d[4:] if d.startswith("www.") else d


def mention_domains_from_rows(rows: list[dict[str, Any]]) -> set[str]:
    out = set()
    for r in rows:
        d = _norm_domain(r.get("domain") or r.get("url"))
        if d:
            out.add(d)
    return out


def unlinked_count(mention_domains: set[str], referring_domains: set[str],
                   own_domain: Optional[str]) -> int:
    """Domains that mention the brand but do NOT link to it (and aren't the
    brand's own site) — the unlinked-mention footprint."""
    own = _norm_domain(own_domain)
    refs = {_norm_domain(d) for d in referring_domains}
    return len({d for d in mention_domains if d and d != own} - refs)


def parse_site_count(task: dict[str, Any]) -> Optional[int]:
    """`se_results_count` from a live/regular SERP task — Google's indexed-page
    estimate for a site: query. None when the task carried no result."""
    result = (task.get("result") or [{}])[0] or {}
    count = result.get("se_results_count")
    return int(count) if count is not None else None


def parse_mentions_summary(task: dict[str, Any]) -> Optional[dict[str, Any]]:
    """{citations, positive, negative} from a content_analysis summary task.
    Defensive: missing keys read as None rather than raising."""
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


def parse_search_rows(task: dict[str, Any]) -> tuple[Optional[int], list[dict]]:
    """(total_count, rows) from a content_analysis search task."""
    result = (task.get("result") or [{}])[0] or {}
    total = result.get("total_count")
    return (int(total) if total is not None else None,
            list(result.get("items") or []))


def parse_referring_domains(task: dict[str, Any]) -> set[str]:
    result = (task.get("result") or [{}])[0] or {}
    return {r.get("domain") for r in (result.get("items") or [])
            if r.get("domain")}


def mention_cost(generic: bool, deep: bool, has_phone: bool) -> float:
    """Planning cost for one brand's mention pull at a tier."""
    if deep:
        return round(COST_MENTIONS_SEARCH + COST_UNLINKED_LIST
                     + (COST_NAP_QUERY if has_phone else 0), 3)
    if generic:
        return round(COST_MENTIONS_SEARCH
                     + (COST_NAP_QUERY if has_phone else 0), 3)
    return COST_MENTIONS_LIGHT


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
    """(business_name, domain, phone) for the top-5 organic maps entries —
    the same field the scanner's serp_top5 keeps, plus the phone the NAP
    query needs. Pure."""
    out = []
    for it in items or []:
        rank = it.get("rank_group") or it.get("rank_absolute")
        if rank is None or rank > 5:
            continue
        name = (it.get("title") or "").strip()
        if not name:
            continue
        out.append({"business_name": name,
                    "domain": (it.get("domain") or "").strip() or None,
                    "phone": (it.get("phone") or "").strip() or None})
        if len(out) >= 5:
            break
    return out


# ── Cache state + fetch (impure; plumbing borrowed lazily from leadoff_actions
#    to avoid a top-level import cycle — actions imports this module) ──────────

def footprint_state(rows: list[dict[str, Any]], now: datetime, *,
                    city_name: str = "", deep: bool = False) -> dict[str, Any]:
    """Which footprint pieces are cache-misses. Input rows carry
    business_name + domain (+ phone, + category_name for the generic check).
    A fresh light row still misses at the deep tier when it has no
    unlinked_mentions (the deep pull upgrades it)."""
    from db.supabase_client import get_supabase
    from services.leadoff_actions import _fresh_cutoff

    supabase = get_supabase()
    cutoff = _fresh_cutoff(now)
    domains = sorted({(r.get("domain") or "").strip()
                      for r in rows if (r.get("domain") or "").strip()})
    brands: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = (r.get("business_name") or "").strip()
        k = brand_key(name)
        if not name or not k or k in brands:
            continue
        brands[k] = {
            "name": name,
            "domain": (r.get("domain") or "").strip() or None,
            "phone": (r.get("phone") or "").strip() or None,
            "generic": is_generic_name(name, r.get("category_name") or "",
                                       city_name),
        }

    fresh_sites = (supabase.table("domain_site_size").select("domain")
                   .in_("domain", domains).gte("pulled_at", cutoff)
                   .execute().data or []) if domains else []
    site_misses = [d for d in domains
                   if d not in {r["domain"] for r in fresh_sites}]

    fresh_rows = (supabase.table("brand_mentions")
                  .select("brand_key, unlinked_mentions")
                  .in_("brand_key", list(brands)).gte("pulled_at", cutoff)
                  .execute().data or []) if brands else []
    fresh_deep = {r["brand_key"] for r in fresh_rows
                  if r.get("unlinked_mentions") is not None}
    fresh_any = {r["brand_key"] for r in fresh_rows}
    mention_misses = {k: v for k, v in brands.items()
                      if k not in (fresh_deep if deep else fresh_any)}

    est = (len(site_misses) * COST_SITE_QUERY
           + sum(mention_cost(v["generic"], deep, bool(v["phone"]))
                 for v in mention_misses.values())
           + (COST_PHONE_SERP if deep and mention_misses else 0))
    return {"site_misses": site_misses, "mention_misses": mention_misses,
            "est_cost": round(est, 2)}


async def _batched_tasks(client, path: str, payloads: list[dict]) -> list[dict]:
    """One POST *per task*, bounded concurrency, results in payload order.

    Originally one POST with N task objects — but the live endpoints only
    honored the FIRST task per request (KC validation 2026-07-12: in every
    batch exactly the first item returned data, the rest came back empty),
    so each payload now gets its own request. Billing is per task either
    way; money-limit checked per response (scanner lesson #2)."""
    import asyncio

    from services.leadoff_actions import _check_money_limit, _dfs_post, _task0

    if not payloads:
        return []
    sem = asyncio.Semaphore(4)

    async def one(p: dict) -> dict:
        async with sem:
            env = await _dfs_post(client, path, [p])
            t = _task0(env)
            _check_money_limit(t)
            return t

    return list(await asyncio.gather(*(one(p) for p in payloads)))


async def fetch_footprint(client, site_misses: list[str],
                          mention_misses: dict[str, dict[str, Any]],
                          now: datetime, *, city_name: str = "",
                          deep: bool = False) -> dict[str, int]:
    """Pull the missing pieces and upsert the caches. Best-effort per signal
    group — a failed group is skipped (retried on the next pull); the
    daily-money-limit abort propagates (scanner lesson #2)."""
    from db.supabase_client import get_supabase

    supabase = get_supabase()
    pulled = {"sites": 0, "mentions": 0}

    # site sizes — one live/regular SERP per domain, one batched POST
    if site_misses:
        try:
            tasks = await _batched_tasks(
                client, "/serp/google/organic/live/regular",
                [{"keyword": f"site:{d}", "language_code": "en",
                  "location_code": 2840, "depth": 10} for d in site_misses])
            rows = [{"domain": site_misses[i],
                     "indexed_pages": parse_site_count(t),
                     "pulled_at": now.isoformat()}
                    for i, t in enumerate(tasks)]
            if rows:
                supabase.table("domain_site_size").upsert(rows).execute()
                pulled["sites"] = len(rows)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("leadoff_brand.site_size_failed", extra={"error": str(exc)})

    if not mention_misses:
        return pulled

    keys = list(mention_misses)
    upserts: dict[str, dict[str, Any]] = {
        k: {"brand_key": k, "business_name": mention_misses[k]["name"],
            "phone": mention_misses[k]["phone"],
            "generic_name": mention_misses[k]["generic"],
            "pulled_at": now.isoformat()}
        for k in keys}

    # mention counts: search (rows+domains) for deep or generic; summary
    # (count only) for light distinctive brands
    search_keys = [k for k in keys if deep or mention_misses[k]["generic"]]
    summary_keys = [k for k in keys if k not in set(search_keys)]
    search_domains: dict[str, set[str]] = {}
    try:
        tasks = await _batched_tasks(
            client, "/content_analysis/search/live",
            [{"keyword": f'"{mention_misses[k]["name"].lower()}"',
              "limit": _SEARCH_LIMIT} for k in search_keys])
        for i, t in enumerate(tasks):
            k = search_keys[i]
            total, rows = parse_search_rows(t)
            if mention_misses[k]["generic"]:
                kept = filter_rows_by_locale(rows, city_name,
                                             mention_misses[k]["phone"])
                # filtered count is honest but floor-bounded by the row cap;
                # total stays None-safe when the search returned nothing
                upserts[k]["citations"] = len(kept) if total is not None else None
                search_domains[k] = mention_domains_from_rows(kept)
            else:
                upserts[k]["citations"] = total
                search_domains[k] = mention_domains_from_rows(rows)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("leadoff_brand.mentions_search_failed",
                       extra={"error": str(exc)})
    try:
        tasks = await _batched_tasks(
            client, "/content_analysis/summary/live",
            [{"keyword": f'"{mention_misses[k]["name"].lower()}"'}
             for k in summary_keys])
        for i, t in enumerate(tasks):
            summary = parse_mentions_summary(t)
            if summary:
                upserts[summary_keys[i]]["citations"] = summary["citations"]
                upserts[summary_keys[i]]["positive_connotations"] = summary["positive"]
                upserts[summary_keys[i]]["negative_connotations"] = summary["negative"]
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("leadoff_brand.mentions_summary_failed",
                       extra={"error": str(exc)})

    # NAP citations — phone-number mention count (deep: everyone with a
    # phone; light: generic brands only, where the bare name can't be trusted)
    nap_keys = [k for k in keys if mention_misses[k]["phone"]
                and (deep or mention_misses[k]["generic"])]
    try:
        tasks = await _batched_tasks(
            client, "/content_analysis/summary/live",
            [{"keyword": f'"{mention_misses[k]["phone"]}"'} for k in nap_keys])
        for i, t in enumerate(tasks):
            summary = parse_mentions_summary(t)
            if summary:
                upserts[nap_keys[i]]["nap_citations"] = summary["citations"]
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("leadoff_brand.nap_failed", extra={"error": str(exc)})

    # unlinked split (deep only) — mentioning domains ∖ referring domains
    if deep:
        link_keys = [k for k in search_keys
                     if mention_misses[k]["domain"] and k in search_domains]
        try:
            tasks = await _batched_tasks(
                client, "/backlinks/referring_domains/live",
                [{"target": mention_misses[k]["domain"], "limit": 1000}
                 for k in link_keys])
            for i, t in enumerate(tasks):
                k = link_keys[i]
                refs = parse_referring_domains(t)
                upserts[k]["unlinked_mentions"] = unlinked_count(
                    search_domains[k], refs, mention_misses[k]["domain"])
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("leadoff_brand.unlinked_failed",
                           extra={"error": str(exc)})

    rows = [u for u in upserts.values()
            if any(u.get(f) is not None for f in
                   ("citations", "nap_citations", "unlinked_mentions"))]
    if rows:
        supabase.table("brand_mentions").upsert(rows).execute()
        pulled["mentions"] = len(rows)
    return pulled


async def fetch_top5_phones(client, category_name: str,
                            city: dict[str, Any]) -> dict[str, str]:
    """{brand_key: phone} for a market's top-5 via one Maps SERP (13z) —
    scout's phone source (serp_top5 never stored phones). Best-effort."""
    from services.leadoff_actions import _check_money_limit, _dfs_post, _task0

    try:
        d = await _dfs_post(
            client, "/serp/google/maps/live/advanced",
            [{"keyword": category_name,
              "location_coordinate": f"{city['latitude']},{city['longitude']},13z",
              "language_code": "en", "device": "desktop", "os": "windows",
              "depth": 20}])
        t0 = _task0(d)
        _check_money_limit(t0)
        items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
        return {brand_key(b["business_name"]): b["phone"]
                for b in top5_from_items(items) if b.get("phone")}
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("leadoff_brand.phones_failed", extra={"error": str(exc)})
        return {}


def footprint_lookups(names_domains: list[dict[str, Any]]) -> tuple[dict, dict]:
    """{domain: indexed_pages} + {brand_key: mention row} for these
    businesses, from the caches (whatever is there — reads are free)."""
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
                    .select("brand_key, citations, unlinked_mentions, "
                            "nap_citations, generic_name")
                    .in_("brand_key", keys).execute().data or []) if keys else []
    return ({r["domain"]: r.get("indexed_pages") for r in site_rows},
            {r["brand_key"]: r for r in mention_rows})
