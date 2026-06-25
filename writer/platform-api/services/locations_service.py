"""DataForSEO location lookup for the Local SEO module.

Provides typeahead suggestions and server-side validation so a mistyped
location can't silently degrade a generate/analyze run (DataForSEO returns
HTTP 200 with zero results for an unresolvable `location_name`, which otherwise
looks identical to an empty SERP).

The suite has no DataForSEO location table, so the per-country location list is
fetched from DataForSEO's `serp/google/locations/{country}` endpoint and cached
in memory — locations are near-static, so a long TTL is fine.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

_LOCATIONS_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/locations"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # locations change rarely
_FETCH_TIMEOUT = 30.0
_DEFAULT_COUNTRY = "US"

# ccTLD → ISO-2, for inferring a client's target country from its website host.
_CCTLD_TO_ISO = {
    "au": "AU", "nz": "NZ", "uk": "GB", "ca": "CA", "ie": "IE", "za": "ZA",
    "in": "IN", "sg": "SG", "ph": "PH", "my": "MY", "hk": "HK", "id": "ID",
    "th": "TH", "vn": "VN", "de": "DE", "fr": "FR", "es": "ES", "it": "IT",
    "nl": "NL", "se": "SE", "no": "NO", "dk": "DK", "fi": "FI", "ch": "CH",
    "at": "AT", "be": "BE", "pt": "PT", "pl": "PL", "br": "BR", "mx": "MX",
    "ar": "AR", "jp": "JP", "kr": "KR", "ae": "AE", "tr": "TR", "gr": "GR",
    "us": "US",
}

# location_type ranking for suggestions (lower sorts first).
_TYPE_PRIORITY = {"City": 0, "Municipality": 0, "Town": 0, "Region": 1,
                  "State": 1, "Province": 1, "County": 2}

# DataForSEO/Google COUNTRY-level location codes (geo target IDs). Used as a
# fallback for `resolve_country_code` when the fetched location list has no
# Country-typed row. Stable Google codes — extend as new client countries appear.
_COUNTRY_LOCATION_CODE = {
    "US": 2840, "AU": 2036, "GB": 2826, "CA": 2124, "NZ": 2554, "IE": 2372,
    "ZA": 2710, "IN": 2356, "SG": 2702, "PH": 2608, "MY": 2458, "HK": 2344,
    "AE": 2784, "DE": 2276, "FR": 2250, "ES": 2724, "IT": 2380, "NL": 2528,
    "SE": 2752, "NO": 2578, "DK": 2208, "FI": 2246, "CH": 2756, "AT": 2040,
    "BE": 2056, "PT": 2620, "PL": 2616, "BR": 2076, "MX": 2484, "JP": 2392,
}

# country_iso → (fetched_at, slim_locations)
_cache: dict[str, tuple[float, list[dict]]] = {}


def infer_country_iso(client: dict) -> str:
    """Best-effort country for a client, from its website host's ccTLD.

    Local-SEO targets are in the client's own country, so the website TLD is a
    reliable signal (e.g. `*.com.au` → AU). Falls back to the default."""
    website = (client.get("website_url") or "") or ((client.get("gbp") or {}).get("website") or "")
    host = urlparse(website if "//" in website else f"//{website}").hostname or ""
    last_label = host.lower().rsplit(".", 1)[-1] if host else ""
    return _CCTLD_TO_ISO.get(last_label, _DEFAULT_COUNTRY)


async def _fetch_country_locations(country_iso: str) -> list[dict]:
    """Fetch (and cache) the slim location list for one country. Returns [] on
    any failure so callers degrade gracefully (free-text, no validation)."""
    country_iso = country_iso.upper()
    cached = _cache.get(country_iso)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    if not settings.dataforseo_login or not settings.dataforseo_password:
        logger.warning("locations.no_credentials")
        return []

    creds = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    ).decode()
    url = f"{_LOCATIONS_ENDPOINT}/{country_iso}"
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Basic {creds}"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("locations.fetch_failed", extra={"country": country_iso, "error": str(exc)})
        return []

    slim: list[dict] = []
    tasks = data.get("tasks") or []
    for task in tasks:
        for loc in (task.get("result") or []):
            name = loc.get("location_name")
            code = loc.get("location_code")
            if not name or code is None:
                continue
            slim.append({
                "location_name": name,
                "location_code": code,
                "location_type": loc.get("location_type") or "",
                "country_iso_code": loc.get("country_iso_code") or country_iso,
            })
    if slim:
        _cache[country_iso] = (time.monotonic(), slim)
    else:
        # 200 but nothing parsed — surface DataForSEO's task status + the shape we
        # actually got, so a wrong response assumption is diagnosable from logs.
        statuses = [(t.get("status_code"), t.get("status_message"), len(t.get("result") or [])) for t in tasks]
        logger.warning(f"locations.empty country={country_iso} tasks={len(tasks)} statuses={statuses} top_keys={list(data.keys())}")
    logger.info(f"locations.fetched country={country_iso} count={len(slim)}")
    return slim


def _rank_key(loc: dict, q: str) -> Optional[tuple]:
    """Sort key for a candidate against query `q` (already lowercased), or None
    if it doesn't match. Prefix matches on the city segment rank first."""
    name = loc["location_name"]
    first_seg = name.split(",")[0].lower()
    name_l = name.lower()
    if first_seg.startswith(q):
        match_rank = 0
    elif q in first_seg:
        match_rank = 1
    elif q in name_l:
        match_rank = 2
    else:
        return None
    type_rank = _TYPE_PRIORITY.get(loc.get("location_type", ""), 3)
    return (match_rank, type_rank, len(name), name_l)


async def search_locations(
    client: dict, query: str, country: Optional[str] = None, limit: int = 10
) -> list[dict]:
    """Return up to `limit` location suggestions matching `query` within the
    client's (or overridden) country. Empty list if nothing matches or the
    lookup is unavailable."""
    q = query.strip().lower()
    if len(q) < 2:
        return []
    iso = (country or infer_country_iso(client)).upper()
    locations = await _fetch_country_locations(iso)
    ranked = []
    for loc in locations:
        key = _rank_key(loc, q)
        if key is not None:
            ranked.append((key, loc))
    ranked.sort(key=lambda x: x[0])
    logger.info(f"locations.search country={iso} query={q!r} pool={len(locations)} matched={len(ranked)}")
    return [loc for _, loc in ranked[:limit]]


async def resolve_country_code(client: dict, country_iso: Optional[str] = None) -> Optional[int]:
    """The DataForSEO COUNTRY-level `location_code` for the client's (or given)
    country.

    DataForSEO **Labs** keyword endpoints (keyword_ideas / suggestions / related /
    ranked_keywords) only accept country-level location codes — a city/region SERP
    code (e.g. Sydney `1000286`) is rejected with a task error and degrades the
    whole expansion. The silo planner therefore drives its Labs calls with this
    country code (the city stays in the seed/SERP). Resolved from the fetched
    location list (the row whose `location_type == "Country"`), falling back to the
    static `_COUNTRY_LOCATION_CODE` map, then None when the country is unknown."""
    iso = (country_iso or infer_country_iso(client)).upper()
    for loc in await _fetch_country_locations(iso):
        if (loc.get("location_type") or "").strip().lower() == "country":
            return loc["location_code"]
    return _COUNTRY_LOCATION_CODE.get(iso)


async def resolve_location(
    client: dict,
    location: str,
    location_code: Optional[int],
    country: Optional[str] = None,
) -> tuple[str, Optional[int]]:
    """Validation backstop for the action endpoints.

    - If `location_code` is supplied (the VA picked a suggestion) it's trusted
      as-is — the happy path is never blocked.
    - Otherwise the typed `location` is resolved against the client's country
      list (the same list the autocomplete uses, so anything the typeahead
      would have shown resolves). A confident exact/prefix match returns its
      canonical name + code; no match raises 400 `location_not_recognized` with
      suggestions, so a mistype fails loudly instead of silently degrading.
    - If the location list can't be fetched (no creds / provider down) we can't
      validate, so we pass the typed location through unchanged rather than
      block generation.
    """
    if location_code is not None:
        return location, location_code

    iso = (country or infer_country_iso(client)).upper()
    locations = await _fetch_country_locations(iso)
    if not locations:
        return location, None  # can't validate → don't block

    q = location.strip().lower()
    q_compact = q.replace(" ", "")
    # Exact match (space-insensitive) on the full canonical name wins.
    for loc in locations:
        if loc["location_name"].lower().replace(" ", "") == q_compact:
            return loc["location_name"], loc["location_code"]

    # Otherwise fall back to ranked suggestions; accept a unique strong (city
    # prefix) match, else reject with options.
    suggestions = await search_locations(client, location, country=iso, limit=5)
    strong = [s for s in suggestions if s["location_name"].split(",")[0].lower() == q.split(",")[0].strip()]
    if len(strong) == 1:
        return strong[0]["location_name"], strong[0]["location_code"]

    options = ", ".join(s["location_name"] for s in suggestions[:5])
    detail = f"location_not_recognized: '{location}' didn't match a known location in {iso}."
    if options:
        detail += f" Did you mean: {options}?"
    raise HTTPException(status_code=400, detail=detail)
