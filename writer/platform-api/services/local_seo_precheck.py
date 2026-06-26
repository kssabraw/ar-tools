"""Existing-page precheck for the Local SEO "New Page" flow (#2).

Before the writer creates a brand-new page, this detects whether the client
already has a page for that topic — so the user can reoptimize the existing page
instead of silently producing a duplicate. It mirrors the Plan Silo flow's
existing-page logic, but for a single on-demand keyword, and adds a ranking
signal the silo planner doesn't use.

Three best-effort sources are merged (any one failing degrades to a note, never
an error):

  1. **In-tool pages** — rows in ``local_seo_pages`` for this client whose
     keyword matches the input *or a close variant* (plural / word-order), so a
     near-duplicate generated page is caught. The actionable handle is the
     page's id (open it → Score & Improve).
  2. **Live site** — the nlp ``/find-page-for-keyword`` scan (sitemap + site
     search + Haiku selection, with blog-post detection) returns the best live
     page targeting the keyword. The handle is its URL (score → reoptimize).
  3. **Ranking** — is the client already ranking for the keyword? Prefers a
     verified GSC property (live query×page pull, all of the client's URLs for
     a matching query); falls back to a DataForSEO live SERP that finds every
     ranking URL on the client's domain. Either can surface *several* pages
     (cannibalization), each offered as a reoptimize target.

Matches are deduped by URL (signals merged) and ordered ranking → in-tool →
live-site. "Close variants" is deliberately cheap (token-set comparison, no LLM,
no geocoding) so the precheck adds seconds, not minutes, to the New Page flow.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import gsc_service, locations_service, rank_materialize
from services.dataforseo_rank import extract_domain, fetch_serp_rank_urls, location_code_for

logger = logging.getLogger(__name__)

# Organic position cutoff for "already ranking" — a page beyond this isn't worth
# flagging as an existing ranker to reoptimize.
_RANK_CUTOFF = 30
# GSC lookback for the ranking signal — same ~90-day window the GSC Research
# module uses for its live query×page pull.
_GSC_LOOKBACK_DAYS = 90


def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


# ── pure helpers (no I/O) — unit-tested ──────────────────────────────────────

# Tiny words that carry no matching signal between keyword variants.
_STOPWORDS = frozenset({"a", "an", "the", "in", "of", "for", "and", "to", "near", "my"})


def normalize_tokens(keyword: str) -> frozenset[str]:
    """A keyword's significant tokens, lowercased and singularized.

    Strips a trailing plural ``s`` (``plumbers`` → ``plumber``) and drops
    stopwords, so word-order and singular/plural variants compare equal. Returns
    a set — order-independent by construction.
    """
    tokens: set[str] = set()
    for raw in re.split(r"[^a-z0-9]+", (keyword or "").lower()):
        if not raw or raw in _STOPWORDS:
            continue
        # Singularize a simple plural (keep short words like "gas" intact).
        if len(raw) > 3 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        tokens.add(raw)
    return frozenset(tokens)


def keywords_match(a: str, b: str) -> bool:
    """True when two keywords are the same topic up to a *close variant*.

    Equal significant-token sets (after singularizing + dropping stopwords) —
    catches plurals and word-order ("emergency plumber melbourne" vs "melbourne
    emergency plumbers"), without matching merely-overlapping different topics.
    """
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    return bool(ta) and ta == tb


def canonical_url_key(url: Optional[str]) -> str:
    """Dedup key for a page URL: host + path, lowercased, scheme/www/trailing-slash
    and query/fragment stripped. ``https://www.x.com/Roof/`` ≡ ``http://x.com/roof``.
    """
    if not url:
        return ""
    raw = url if "//" in url else f"//{url}"
    try:
        parsed = urlparse(raw)
    except ValueError:
        return url.strip().lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/").lower()
    return f"{host}{path}"


# ── ranking signal ───────────────────────────────────────────────────────────

async def _gsc_ranking_urls(
    supabase, client_id: str, variants: list[str],
) -> Optional[list[dict]]:
    """Ranking URLs from a verified GSC property, or None when GSC is unavailable.

    Live query×page pull over the lookback window; keeps rows whose query matches
    the keyword (or a close variant) and that rank within the cutoff. Returns
    ``[{url, position}]`` (possibly empty) when GSC *is* available, else None so
    the caller falls back to DataForSEO.
    """
    if not gsc_service.is_configured():
        return None
    property = rank_materialize._verified_property(supabase, client_id)
    if not property:
        return None

    from datetime import date, timedelta

    from services import gsc_research

    today = date.today()
    date_from = today - timedelta(days=_GSC_LOOKBACK_DAYS)
    try:
        rows = await asyncio.to_thread(
            gsc_research._fetch_live_page_rows, property["site_url"], date_from, today
        )
    except Exception as exc:  # noqa: BLE001 — degrade to DataForSEO fallback
        logger.warning("local_seo_precheck.gsc_failed", extra={"client_id": client_id, "error": str(exc)})
        return None

    best: dict[str, dict] = {}
    for row in rows:
        if not any(keywords_match(row.get("query", ""), v) for v in variants):
            continue
        pos = row.get("position")
        if pos is None or pos > _RANK_CUTOFF:
            continue
        page = row.get("page")
        if not page:
            continue
        key = canonical_url_key(page)
        prev = best.get(key)
        if prev is None or pos < prev["position"]:
            best[key] = {"url": page, "position": int(round(pos))}
    return sorted(best.values(), key=lambda r: r["position"])


async def _dataforseo_ranking_urls(client: dict, keyword: str, location_code: Optional[int]) -> list[dict]:
    """Ranking URLs from a live DataForSEO SERP (the fallback rank source).

    Finds every URL on the client's domain ranking for the keyword, within the
    cutoff. Best-effort — returns [] if the client has no domain or the SERP call
    errors.
    """
    domain = extract_domain(client.get("website_url") or (client.get("gbp") or {}).get("website") or "")
    if not domain:
        return []
    if not settings.dataforseo_login:
        return []
    code = location_code or location_code_for(client)
    try:
        ranks = await fetch_serp_rank_urls(keyword, domain, code)
    except Exception as exc:  # noqa: BLE001 — ranking is an enhancement, not a gate
        logger.warning("local_seo_precheck.dataforseo_failed", extra={"keyword": keyword, "error": str(exc)})
        return []
    return [r for r in ranks if r.get("position") is not None and r["position"] <= _RANK_CUTOFF]


# ── orchestration ────────────────────────────────────────────────────────────

def _build_variants(keyword: str) -> list[str]:
    """The keyword plus its close variants to check against. The token-set match
    is variant-agnostic, so this is mostly the seed itself; kept as a list so the
    surfaced ``checked_variants`` is meaningful and future variants slot in."""
    kw = (keyword or "").strip()
    return [kw] if kw else []


async def detect_existing_pages(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    user_id: str,
) -> dict:
    """Detect existing/ranking pages for a keyword before the writer creates a new
    one. Returns ``{matches, rank_source, checked_variants, degraded_notes}``;
    ``matches`` is empty when nothing pre-exists (the caller then generates).
    """
    client = _get_client(client_id)
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    variants = _build_variants(keyword)
    notes: list[str] = []

    # matches keyed for dedup: a URL by canonical key, an in-tool page by id.
    matches: dict[str, dict] = {}

    def _merge(key: str, data: dict, signal: str) -> None:
        existing = matches.get(key)
        if existing is None:
            existing = {
                "url": None, "page_id": None, "title": None, "is_blog_post": False,
                "rank_position": None, "rank_source": None, "matched_keyword": None,
                "signals": [],
            }
            matches[key] = existing
        for field, value in data.items():
            if value is not None and existing.get(field) in (None, "", False):
                existing[field] = value
        if signal not in existing["signals"]:
            existing["signals"].append(signal)

    # 1. In-tool pages (free) — close-variant token match.
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("local_seo_pages")
            .select("id, keyword, page_title, published_doc_url, mode")
            .eq("client_id", client_id)
            .execute()
            .data
            or []
        )
        for r in rows:
            if not any(keywords_match(r.get("keyword", ""), v) for v in variants):
                continue
            url = r.get("published_doc_url")
            key = canonical_url_key(url) if url else f"intool:{r['id']}"
            _merge(
                key,
                {
                    "page_id": r["id"], "url": url, "title": r.get("page_title"),
                    "matched_keyword": r.get("keyword"),
                },
                "in_tool",
            )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("local_seo_precheck.intool_failed", extra={"client_id": client_id, "error": str(exc)})
        notes.append("Couldn't check this client's already-generated pages.")

    # 2. Live site — nlp find-page-for-keyword (best single live match + blog flag).
    website = (client.get("gbp") or {}).get("website") or client.get("website_url")
    if website:
        try:
            from services import local_seo_service

            found = await local_seo_service.find_page(client_id, keyword, location)
            page = (found or {}).get("page") if (found or {}).get("found") else None
            if page and page.get("url"):
                _merge(
                    canonical_url_key(page["url"]),
                    {
                        "url": page["url"],
                        "title": page.get("title"),
                        "is_blog_post": bool(found.get("is_blog_post")),
                        "matched_keyword": keyword,
                    },
                    "live_site",
                )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("local_seo_precheck.live_site_failed", extra={"client_id": client_id, "error": str(exc)})
            notes.append("Couldn't scan the client's live site for an existing page.")
    else:
        notes.append("No website on file — skipped the live-site existing-page check.")

    # 3. Ranking — GSC if a verified property exists, else DataForSEO.
    rank_source = "none"
    ranking: list[dict] = []
    try:
        gsc = await _gsc_ranking_urls(supabase, client_id, variants)
        if gsc is not None:
            rank_source, ranking = "gsc", gsc
        else:
            df = await _dataforseo_ranking_urls(client, keyword, location_code)
            if df:
                rank_source, ranking = "dataforseo", df
            elif extract_domain(client.get("website_url") or (client.get("gbp") or {}).get("website") or ""):
                rank_source = "dataforseo"  # checked, nothing ranking
    except Exception as exc:  # noqa: BLE001 — ranking is an enhancement
        logger.warning("local_seo_precheck.ranking_failed", extra={"client_id": client_id, "error": str(exc)})
        notes.append("Couldn't check whether the client is already ranking for this keyword.")

    for r in ranking:
        _merge(
            canonical_url_key(r["url"]),
            {"url": r["url"], "rank_position": r.get("position"), "rank_source": rank_source,
             "matched_keyword": keyword},
            "ranking",
        )

    def _sort_key(m: dict) -> tuple:
        is_ranking = "ranking" in m["signals"]
        pos = m["rank_position"] if m["rank_position"] is not None else 999
        # ranking (by position) → in_tool → live-site only.
        tier = 0 if is_ranking else (1 if "in_tool" in m["signals"] else 2)
        return (tier, pos)

    ordered = sorted(matches.values(), key=_sort_key)
    return {
        "matches": ordered,
        "rank_source": rank_source,
        "checked_variants": variants,
        "degraded_notes": notes,
    }
