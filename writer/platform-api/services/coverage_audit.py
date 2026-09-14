"""Coverage Audit — whole-site location & service gap finder (pure core).

Phase 0 foundations. This module INVERTS the seed-based Plan Silo: instead of
starting from a seed you type, it derives both axes from the client's site AS IT
STANDS, diffs the ideal coverage universe (service × location) against what
exists, and demand-ranks the gaps so the recommendations are worth building.

Design authority: ``docs/modules/coverage-audit-module-plan-v1_0.md`` (owner
decisions §0; reuse map §2; the four load-bearing constraints from the
adversarial-review §8).

This module is PURE — no external calls, no I/O. Callers (Phase 1+) pass in the
already-scanned site index + already-fetched market data; this module only
classifies, builds the report grid, diffs, and ranks. The paid scanning
(`discover_site_urls`), the city/CDP/neighborhood universe, and the demand
fetch live in the impure runner layer built in later phases.

AXES-ONLY contract (plan §0.5 / §8 Major #1 — do NOT regress):
    The coverage grid this module builds feeds the demand-ranked gap **report**
    only. It is NEVER written back onto Service×Location Matrix cells — the Matrix
    owns per-cell present/absent through its own ``mark_coverage`` (which re-scans
    the live site on seed/reconcile). Two coverage sources would silently
    diverge. To keep that contract mechanical rather than a comment, the grid
    deliberately does NOT emit any Matrix cell-state shape (no
    ``coverage``/``cell_id``/``page_id``/…); ``MATRIX_CELL_STATE_KEYS`` names the
    forbidden keys and a unit test asserts none ever appear on a grid row.

The site classification reuses the platform-side ``content_tokens`` +
``is_blog_url`` from ``site_page_index`` (NOT nlp-api's cross-service
``classify_page_type`` — plan §8). The demand ranking reuses the
keyword-research ``opportunity_score`` and the keyword-market
``estimate_monthly_value`` so the audit ranks gaps exactly like the rest of the
suite.
"""

from __future__ import annotations

from typing import Iterable, Optional

from services.keyword_market import estimate_monthly_value
from services.keyword_research import opportunity_score
from services.site_page_index import (
    content_tokens,
    is_blog_url,
    match_site_location_page,
    match_site_page_for_keyword,
    url_path_slugs,
)

# ── classification buckets ────────────────────────────────────────────────────
BUCKET_SERVICE_ONLY = "service_only"
BUCKET_LOCATION_ONLY = "location_only"
BUCKET_SERVICE_LOCATION = "service_location"
BUCKET_OTHER = "other"

# Keys the Service×Location Matrix uses for its persisted per-cell coverage state
# (`local_seo_matrix_store` — `coverage` holds found/on_site/missing, cells carry
# `cell_id`/`page_id`/`released_at`/`link_coverage`). The audit grid must never
# carry any of these: it represents presence as a plain boolean, a report artifact
# distinct from the Matrix's own state. Enforced by a unit test.
MATRIX_CELL_STATE_KEYS = frozenset(
    {
        "coverage",
        "cell_id",
        "matrix_id",
        "matrix_cell_id",
        "page_id",
        "released_at",
        "link_coverage",
        "state",
    }
)

# Competition band → a keyword-difficulty proxy so the reused `opportunity_score`
# (which weights by ease = 100 − KD) has a meaningful ease signal from the only
# competition figure `keyword_market` returns (a LOW/MEDIUM/HIGH band, not a KD).
_COMPETITION_DIFFICULTY = {"low": 20.0, "medium": 50.0, "high": 80.0}

# The SERP position a newly-built gap page is assumed to target, for the est-value
# forecast (a top-of-page-1 local page). This is a FORECAST used to size the
# opportunity, never a measurement; Phase 1 can calibrate it from live outcomes.
_GAP_TARGET_POSITION = 3


# ── pure helpers ──────────────────────────────────────────────────────────────
def _place_token_set(place_vocab: Optional[Iterable[str]]) -> frozenset[str]:
    """Union of content-word tokens across the location-universe names — the
    vocabulary that marks a URL token as a *place* token. Multi-word places are
    handled by tokenizing each name ("San Francisco" → {san, francisco})."""
    tokens: set[str] = set()
    for name in place_vocab or []:
        tokens |= set(content_tokens(name or ""))
    return frozenset(tokens)


def _url_content_tokens(url: str) -> frozenset[str]:
    """All distinguishing content words across a URL's path segments (generic
    wrapper/connector words dropped, per `content_tokens`)."""
    toks: set[str] = set()
    for slug in url_path_slugs(url):
        toks |= set(content_tokens(slug))
    return frozenset(toks)


def _axis_names(axis: Optional[Iterable]) -> list[str]:
    """Normalize an axis (list of names, or of dicts) to a deduped, order-preserving
    list of name strings. Accepts plain strings or dicts carrying
    name/label/service/location — so Phase 1 can pass either shape."""
    out: list[str] = []
    seen: set[str] = set()
    for item in axis or []:
        if isinstance(item, dict):
            name = (
                item.get("name")
                or item.get("label")
                or item.get("service")
                or item.get("location")
                or ""
            )
        else:
            name = item
        name = str(name or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _normalize_index(index: Optional[dict]) -> dict:
    """Coerce a site index to ``{"token_index": {...}, "location_index": {...}}``.

    Accepts the structured form, an empty/None (→ empty indices), or a bare
    content-word-set token index (frozenset → url) which is treated as the
    ``token_index`` with no location index. Keeps callers forgiving."""
    if not index:
        return {"token_index": {}, "location_index": {}}
    if isinstance(index, dict) and ("token_index" in index or "location_index" in index):
        return {
            "token_index": index.get("token_index") or {},
            "location_index": index.get("location_index") or {},
        }
    return {"token_index": index, "location_index": {}}


def _competition_to_difficulty(competition) -> Optional[float]:
    """Map a `keyword_market` competition value to a 0–100 keyword-difficulty
    proxy. A LOW/MEDIUM/HIGH band maps to 20/50/80; a numeric index is passed
    through (a 0–1 fraction is scaled to 0–100); anything unknown → None (so
    `opportunity_score` falls back to its neutral 50)."""
    if competition is None:
        return None
    if isinstance(competition, bool):
        return None
    if isinstance(competition, (int, float)):
        value = float(competition)
        return value * 100.0 if value <= 1.0 else value
    return _COMPETITION_DIFFICULTY.get(str(competition).strip().lower())


# ── classify the client's site as it stands ───────────────────────────────────
def classify_site_pages(
    urls: Optional[Iterable[str]], place_vocab: Optional[Iterable[str]]
) -> dict[str, list[dict]]:
    """Bucket each site URL into ``service_only`` / ``location_only`` /
    ``service_location`` / ``other``.

    A URL's content tokens are split into place-tokens (the intersection with the
    resolved location universe, ``place_vocab``) and service-tokens (the rest):

      * both present  → ``service_location`` (a "<service> <city>" landing page)
      * only place    → ``location_only``    (a bare place-name hub, ``/melbourne/``)
      * only service  → ``service_only``      (a city-less service page, ``/roofing/``)
      * blog/news/product/taxonomy/system, or no content tokens (the homepage) →
        ``other`` (excluded from both axes; carries a ``reason``).

    Deliberately LEXICAL: a non-service page that carries service-shaped tokens
    but no place tokens (``/about/``, ``/contact/``) lands in ``service_only`` —
    the derived service axis is confirmed/edited by the team before the diff runs
    (Phase 1), which is where such pages are filtered. Pure, no I/O."""
    place_tokens = _place_token_set(place_vocab)
    buckets: dict[str, list[dict]] = {
        BUCKET_SERVICE_ONLY: [],
        BUCKET_LOCATION_ONLY: [],
        BUCKET_SERVICE_LOCATION: [],
        BUCKET_OTHER: [],
    }
    seen: set[str] = set()
    for url in urls or []:
        if not url or url in seen:
            continue
        seen.add(url)
        if is_blog_url(url):
            buckets[BUCKET_OTHER].append({"url": url, "reason": "non_page"})
            continue
        toks = _url_content_tokens(url)
        if not toks:
            buckets[BUCKET_OTHER].append({"url": url, "reason": "no_content"})
            continue
        place = toks & place_tokens
        service = toks - place_tokens
        entry = {
            "url": url,
            "service_tokens": sorted(service),
            "place_tokens": sorted(place),
        }
        if place and service:
            buckets[BUCKET_SERVICE_LOCATION].append(entry)
        elif place:
            buckets[BUCKET_LOCATION_ONLY].append(entry)
        else:
            buckets[BUCKET_SERVICE_ONLY].append(entry)
    return buckets


# ── ideal-vs-actual coverage grid (report only — never matrix cell state) ──────
def build_coverage_grid(
    service_axis: Optional[Iterable],
    location_axis: Optional[Iterable],
    site_index: Optional[dict],
    in_tool_index: Optional[dict] = None,
) -> dict:
    """Mark each service, location, and service×location cell ``present`` /
    ``absent`` for the demand-ranked gap REPORT.

    A row is ``present`` when a live-site page matches OR an in-tool
    (`local_seo_pages`/matrix) page matches:

      * service (city-less service page) — keyword = the service name, matched by
        content-word-set equality (`match_site_page_for_keyword`);
      * location (bare location hub, ``/melbourne/``) — matched by the generic
        place-name matcher (`match_site_location_page`). The location-hub *keyword*
        definition (plan §7 open item) is deferred to Phase 1; Phase 0 detects the
        generic place-name page, which is exactly the hub a local business uses;
      * cell — keyword = ``"<service> <location>"`` (matching the Matrix's own
        `build_matrix_silos` composition), matched by content-word-set equality.

    AXES-ONLY: the returned grid is a report artifact. It carries ``present`` as a
    boolean and MUST NOT be written onto Matrix cells — the Matrix recomputes
    coverage itself on seed (§8 Major #1). No `match_site_service_page`
    national-page fallback is applied to cells here: that #953 "national page
    covers the seed-city cell only" nuance needs the seed city, which arrives in
    Phase 1; omitting it can only OVER-report a gap (never miss one), the safe
    direction for a report. Pure, no I/O."""
    site = _normalize_index(site_index)
    intool = _normalize_index(in_tool_index)
    services = _axis_names(service_axis)
    locations = _axis_names(location_axis)

    def _resolve(match_site, match_tool) -> tuple[bool, Optional[str], Optional[str]]:
        url = match_site()
        if url:
            return True, url, "site"
        url = match_tool()
        if url:
            return True, url, "in_tool"
        return False, None, None

    svc_rows: list[dict] = []
    for s in services:
        present, url, source = _resolve(
            lambda s=s: match_site_page_for_keyword(s, site["token_index"]),
            lambda s=s: match_site_page_for_keyword(s, intool["token_index"]),
        )
        svc_rows.append(
            {"service": s, "keyword": s, "present": present, "match_url": url, "source": source}
        )

    loc_rows: list[dict] = []
    for loc in locations:
        present, url, source = _resolve(
            lambda loc=loc: match_site_location_page(loc, site["location_index"]),
            lambda loc=loc: match_site_location_page(loc, intool["location_index"]),
        )
        loc_rows.append(
            {"location": loc, "keyword": loc, "present": present, "match_url": url, "source": source}
        )

    cell_rows: list[dict] = []
    for s in services:
        for loc in locations:
            keyword = f"{s} {loc}".strip()
            present, url, source = _resolve(
                lambda keyword=keyword: match_site_page_for_keyword(keyword, site["token_index"]),
                lambda keyword=keyword: match_site_page_for_keyword(keyword, intool["token_index"]),
            )
            cell_rows.append(
                {
                    "service": s,
                    "location": loc,
                    "keyword": keyword,
                    "present": present,
                    "match_url": url,
                    "source": source,
                }
            )

    counts = {
        "services_present": sum(1 for r in svc_rows if r["present"]),
        "services_absent": sum(1 for r in svc_rows if not r["present"]),
        "locations_present": sum(1 for r in loc_rows if r["present"]),
        "locations_absent": sum(1 for r in loc_rows if not r["present"]),
        "cells_present": sum(1 for r in cell_rows if r["present"]),
        "cells_absent": sum(1 for r in cell_rows if not r["present"]),
        "cells_total": len(cell_rows),
    }
    return {"services": svc_rows, "locations": loc_rows, "cells": cell_rows, "counts": counts}


def diff_coverage(grid: Optional[dict]) -> dict:
    """The absent entries of a coverage grid, per gap kind:
    ``{missing_services, missing_locations, missing_cells}``. Each gap carries its
    ``keyword`` so `rank_gaps` can attach demand. Pure."""
    grid = grid or {}
    missing_services = [
        {"service": r["service"], "keyword": r["keyword"]}
        for r in grid.get("services", [])
        if not r.get("present")
    ]
    missing_locations = [
        {"location": r["location"], "keyword": r["keyword"]}
        for r in grid.get("locations", [])
        if not r.get("present")
    ]
    missing_cells = [
        {"service": r["service"], "location": r["location"], "keyword": r["keyword"]}
        for r in grid.get("cells", [])
        if not r.get("present")
    ]
    return {
        "missing_services": missing_services,
        "missing_locations": missing_locations,
        "missing_cells": missing_cells,
    }


# ── demand ranking + the minimum-demand floor ─────────────────────────────────
def rank_gaps(
    gaps: Optional[Iterable[dict]],
    market: Optional[dict],
    min_volume: int = 0,
) -> list[dict]:
    """Enrich gaps with demand (volume / CPC / competition / est-value) + an
    ``opportunity_score``, apply the minimum-demand floor, and sort best-first.

    ``market`` is keyed by lowercased keyword → ``{search_volume, cpc, competition,
    ...}`` (the `keyword_market.parse_market_items` shape). Scoring reuses the
    suite's `opportunity_score` (competition band → a KD proxy) and est-value
    reuses `estimate_monthly_value` at an assumed top-of-page-1 target position.

    THE FLOOR (plan §8 Major #4): when ``min_volume`` > 0, a gap whose volume is
    below the floor is DROPPED, not merely ranked last — this is what tames the
    zero-demand cross-product tail (Tier 3/4 CDP × subservice), which ranking
    alone cannot. A gap with unknown volume (no market data / DataForSEO returned
    none) counts as 0 and is dropped under any positive floor — an unknown-demand
    cell is exactly the noise the floor exists to hide. ``min_volume`` = 0 (the
    default) disables the floor, so callers can rank service/location gaps
    unfloored while flooring cells. Pure, no I/O."""
    market = market or {}
    ranked: list[dict] = []
    for gap in gaps or []:
        keyword = (gap.get("keyword") or "").strip()
        m = market.get(keyword.lower(), {}) if keyword else {}
        volume = m.get("search_volume")
        cpc = m.get("cpc")
        competition = m.get("competition")
        if min_volume and (volume or 0) < min_volume:
            continue
        kd = _competition_to_difficulty(competition)
        row = dict(gap)
        row.update(
            {
                "volume": volume,
                "cpc_usd": cpc,
                "competition": competition,
                "est_value": estimate_monthly_value(volume, _GAP_TARGET_POSITION, cpc),
                "opportunity_score": opportunity_score(volume, cpc, kd, None),
            }
        )
        ranked.append(row)
    ranked.sort(
        key=lambda r: (
            -(r.get("opportunity_score") or 0.0),
            -(r.get("volume") or 0),
            r.get("keyword") or "",
        )
    )
    return ranked
