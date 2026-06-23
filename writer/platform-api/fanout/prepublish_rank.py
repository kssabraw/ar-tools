"""Pre-publish ranking check (per client).

Before a client accepts a session's final content map, determine whether they
already rank in the top 10 for each planned article's target keyword, so they
can skip / refresh-existing instead of commissioning a new article.

Data sources, in priority order (spec: docs/pre-publish-ranking-check-spec.md in
the source repo):
  1. GSC  — the client's Google Search Console data already in AR Tools
            (public.gsc_properties -> gsc_query_page_daily). Free, real
            positions + the ranking page URL. One bulk read, matched in memory.
  2. DataForSEO SERP — location-aware organic SERP (the vendored Fanout client)
            for the residue GSC didn't cover; "ranked" if the client domain
            appears on any page in the top 10.

This module is the pure data-source layer (normalization + the two lookups).
Gathering the session's target keywords, persistence, the background job, and the
API/UI live alongside it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

TOP_N = 10  # "already ranking" = best position <= 10
GSC_WINDOW_DAYS = 90  # recent GSC window to read best position over
_IN_CHUNK = 80  # keep the PostgREST `in.(...)` filter under URL length limits


# ---- normalization --------------------------------------------------------
def norm_keyword(s: str) -> str:
    """Lowercase, trim, collapse internal whitespace. GSC stores queries
    lowercased, so this lines session keywords up with GSC `query` values."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def registrable_domain(value: str | None) -> str | None:
    """Best-effort registrable domain from a URL or bare host: drop scheme,
    `www.`, path, and a leading subdomain so `https://www.blog.acme.com/x` and
    `acme.com` compare equal. Not a public-suffix-list parse — good enough for
    "does the client domain appear in the SERP"."""
    if not value:
        return None
    raw = value.strip().lower()
    if "//" not in raw:
        raw = "//" + raw
    host = (urlparse(raw).hostname or "").strip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    # Keep the last two labels (acme.com); for multi-label TLDs (co.uk) keep
    # three so we don't collapse to "co.uk".
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _host_matches(result_url: str | None, client_domain: str | None) -> bool:
    rd = registrable_domain(result_url)
    return bool(rd and client_domain and rd == client_domain)


def client_domain(client_id: str | None) -> str | None:
    """Registrable domain for the AR Tools client (from public.clients.website_url),
    via the host suite's public-schema client. Used for the DataForSEO SERP
    domain match. None when there's no client or no website on file."""
    if not client_id:
        return None
    try:
        from db.supabase_client import get_supabase

        resp = (
            get_supabase()
            .table("clients")
            .select("website_url")
            .eq("id", client_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            return registrable_domain(resp.data[0].get("website_url"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "prepublish_client_domain_failed",
            extra={"event": "prepublish_client_domain_failed",
                   "client_id": client_id, "reason": repr(exc)},
        )
    return None


# ---- GSC lookup (source 1) ------------------------------------------------
def gsc_lookup(client_id: str, keywords: list[str]) -> dict[str, dict]:
    """Map normalized keyword -> {position, url, source:'gsc'} for the client's
    keywords that appear in their GSC query history within the recent window and
    rank top-10. Reads public.gsc_* via the host suite's public-schema client
    (the Fanout client is scoped to the `fanout` schema). Best (lowest) position
    over the window wins; the page at that position is the ranking URL.

    Returns only top-10 matches — a keyword absent from the result dict is "not
    found in GSC (covered elsewhere or not ranking)"."""
    wanted = {norm_keyword(k) for k in keywords if k and k.strip()}
    if not client_id or not wanted:
        return {}
    try:
        from db.supabase_client import get_supabase

        client = get_supabase()
        props = (
            client.table("gsc_properties")
            .select("id, access_status")
            .eq("client_id", client_id)
            .execute()
            .data
        )
        property_ids = [p["id"] for p in props if p.get("access_status") == "ok"] or [
            p["id"] for p in props
        ]
        if not property_ids:
            return {}

        since = (date.today() - timedelta(days=GSC_WINDOW_DAYS)).isoformat()
        # best position (and its page) per query, across matched queries only.
        best: dict[str, dict] = {}
        wanted_list = sorted(wanted)
        for start in range(0, len(wanted_list), _IN_CHUNK):
            chunk = wanted_list[start : start + _IN_CHUNK]
            rows = (
                client.table("gsc_query_page_daily")
                .select("query, page, position")
                .in_("property_id", property_ids)
                .in_("query", chunk)
                .gte("date", since)
                .execute()
                .data
            )
            for r in rows:
                q = norm_keyword(r.get("query", ""))
                pos = r.get("position")
                if q not in wanted or pos is None:
                    continue
                cur = best.get(q)
                if cur is None or pos < cur["position"]:
                    best[q] = {"position": pos, "url": r.get("page")}

        out: dict[str, dict] = {}
        for q, v in best.items():
            if v["position"] is not None and v["position"] <= TOP_N:
                out[q] = {
                    "position": int(round(v["position"])),
                    "url": v["url"],
                    "source": "gsc",
                }
        return out
    except Exception as exc:  # noqa: BLE001 - degrade to "GSC uncovered", fall through to DataForSEO
        logger.warning(
            "prepublish_gsc_lookup_failed",
            extra={"event": "prepublish_gsc_lookup_failed",
                   "client_id": client_id, "reason": repr(exc)},
        )
        return {}


# ---- DataForSEO SERP fallback (source 2) ----------------------------------
def dataforseo_lookup(dfs, client_domain: str | None, keywords: list[str]) -> dict[str, dict]:
    """Map normalized keyword -> {position, url, source:'dataforseo'} for the
    residue keywords GSC didn't cover, by reading the location-aware top-10
    organic SERP and checking whether the client domain appears on any page.
    `dfs` is a per-session DataForSEO client (get_dataforseo(location_code)).

    Synchronous + sequential here; the caller batches/bounds it and runs it in a
    background job (one SERP call per keyword ~ real money, so the residue is
    swept off the request path)."""
    cd = registrable_domain(client_domain)
    if not cd or not keywords:
        return {}
    out: dict[str, dict] = {}
    for kw in keywords:
        nk = norm_keyword(kw)
        if not nk or nk in out:
            continue
        try:
            results = dfs.serp_top_results(kw, depth=TOP_N)
        except Exception as exc:  # noqa: BLE001 - one bad keyword shouldn't sink the sweep
            logger.warning(
                "prepublish_serp_failed",
                extra={"event": "prepublish_serp_failed", "keyword": kw, "reason": repr(exc)},
            )
            continue
        for item in results:
            if item.get("type") != "organic":
                continue
            rank = item.get("rank_absolute") or item.get("rank")
            if rank is None or rank > TOP_N:
                continue
            if _host_matches(item.get("url"), cd):
                out[nk] = {"position": int(rank), "url": item.get("url"), "source": "dataforseo"}
                break
    return out
