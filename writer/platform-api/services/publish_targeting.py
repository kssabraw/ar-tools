"""Resolve where a run's content commits in the client's repo and its nested
collection slug — SOP "URL & Slug Construction Rules" + "Importing an Existing
Site" (site always wins) with full per-type deep nesting.

Pure (no I/O). Maps a run's `content_type` + keyword to an SOP page type, splits
a geo keyword into location + service using the client's known places, and
produces:
  - content_path : the repo collection dir (resolve_github_path — inferred >
    override > default);
  - nested_slug  : the collection-relative nested slug (Astro content-collection
    `slug`; the collection route supplies any /blog//shop/ prefix), e.g. a local
    landing → "los-angeles/plumbing";
  - file_path    : content_path + nested_slug + ".md" (nested to mirror the URL);
  - public_url   : the full intended public URL (build_page_path — honors the
    inferred site prefixes/separator), for logging + the reconcile check.
"""
from __future__ import annotations

import re
from typing import Any

from services import slug_rules
from services.github_publish import resolve_github_path


def _expand_place(place: str) -> list[str]:
    """A stored place plus its bare-city alias. Stored locations often carry the
    region/country ("Los Angeles,California,United States", "Los Angeles, CA") —
    which never appears verbatim in a keyword — so we also emit the first
    comma-separated token ("Los Angeles"), which is what a keyword contains."""
    p = place.strip()
    out = [p]
    bare = p.split(",")[0].strip()
    if bare and bare.lower() != p.lower():
        out.append(bare)
    return out


def client_known_places(client: dict) -> list[str]:
    """The client's known place names (business location + target cities + GBP
    service-area places), each expanded to its bare-city alias, de-duped
    case-insensitively, order preserved."""
    raw: list[str] = []
    bl = client.get("business_location")
    if isinstance(bl, str) and bl.strip():
        raw.append(bl.strip())
    for c in client.get("target_cities") or []:
        if isinstance(c, str) and c.strip():
            raw.append(c.strip())
    gbp = client.get("gbp")
    if isinstance(gbp, dict):
        for p in gbp.get("service_area_places") or []:
            if isinstance(p, str) and p.strip():
                raw.append(p.strip())
    seen: set[str] = set()
    out: list[str] = []
    for place in raw:
        for alias in _expand_place(place):
            k = alias.lower()
            if k not in seen:
                seen.add(k)
                out.append(alias)
    return out


def extract_place(keyword: str, known_places: list[str]) -> tuple[str | None, str]:
    """Find a known place inside `keyword` and split it off. Returns
    (place, remainder) — the longest place matched first, on word boundaries.
    remainder is the keyword minus the place (the service). No match → (None, keyword)."""
    kw = keyword or ""
    for place in sorted((p for p in known_places if p and p.strip()), key=len, reverse=True):
        m = re.search(r"\b" + re.escape(place.strip()) + r"\b", kw, flags=re.IGNORECASE)
        if m:
            remainder = (kw[: m.start()] + " " + kw[m.end() :]).strip()
            return place, remainder
    return None, kw


def _inferred_url(client: dict) -> tuple[str, dict, bool]:
    """(separator, prefixes, trailing_slash) from the inferred site pattern, with
    the SOP house defaults when absent."""
    inferred = client.get("github_inferred_patterns")
    url = inferred.get("url") if isinstance(inferred, dict) else None
    if not isinstance(url, dict):
        url = {}
    separator = url.get("separator") if url.get("separator") in ("-", "_") else "-"
    prefixes = url.get("prefixes") if isinstance(url.get("prefixes"), dict) else {}
    trailing = url.get("trailing_slash")
    trailing = True if trailing is None else bool(trailing)
    return separator, prefixes, trailing


def _page_type_and_parts(
    content_type: str | None, keyword: str, places: list[str], *, location: str | None = None
) -> tuple[str, dict]:
    """Map a run content_type + keyword to an SOP page type + build_page_path
    parts. A location/local-SEO page uses an explicit `location` when the caller
    has one (Local SEO pages carry a location column), else splits the keyword
    into local_landing / top_level_location via the client's known places."""
    ct = content_type or "blog_post"
    if ct == "service_page":
        return "top_level_service", {"service": keyword}
    if ct in ("location_page", "local_seo_page"):
        loc = (location or "").strip()
        if loc:
            svc = keyword.strip()
            if svc:
                return "local_landing", {"location": loc, "service": svc}
            return "top_level_location", {"location": loc}
        place, remainder = extract_place(keyword, places)
        if place and remainder:
            return "local_landing", {"location": place, "service": remainder}
        if place:
            return "top_level_location", {"location": place}
        return "top_level_location", {"location": keyword}
    if ct in ("product", "ecom_page", "ecommerce_page"):
        return "product", {"product": keyword}
    return "blog_post", {"keyword": keyword}


def _inferred_nesting(client: dict) -> dict:
    inferred = client.get("github_inferred_patterns")
    nesting = inferred.get("nesting") if isinstance(inferred, dict) else None
    return nesting if isinstance(nesting, dict) else {}


def _reconcile_lookup(client: dict, content_path: str, slug: str) -> dict | None:
    """An existing repo file for `slug` in `content_path` (from the discovery-built
    reconcile index), or None. Returns {path, slug} — the file to overwrite in
    place and its actual slug (to preserve the live URL)."""
    inferred = client.get("github_inferred_patterns")
    index = inferred.get("reconcile_index") if isinstance(inferred, dict) else None
    if not isinstance(index, dict):
        return None
    bucket = index.get(content_path)
    if not isinstance(bucket, dict):
        return None
    entry = bucket.get(slug)
    if isinstance(entry, dict) and entry.get("path"):
        return entry
    return None


def resolve_publish_target(
    content_type: str | None,
    source: str | None,
    *,
    client: dict,
    taken: object = (),
    location: str | None = None,
) -> dict[str, Any]:
    """Resolve the commit target for one piece of content. `source` is the run's
    keyword (falls back to the title upstream); `location` is an explicit place
    for callers that carry one (e.g. Local SEO pages).

    Returns `file_path` (where to commit), `frontmatter_slug` (the Astro
    collection slug to write), `nested_slug` (the computed slug), `public_url`,
    and `reconciled` (True when overwriting an existing page in place)."""
    keyword = (source or "").strip()
    separator, prefixes, trailing = _inferred_url(client)
    places = client_known_places(client)
    page_type, parts = _page_type_and_parts(content_type, keyword, places, location=location)

    # 2a: clamp nesting to the site's detected depth for this page's family.
    family = slug_rules.family_for_page_type(page_type)
    depth = _inferred_nesting(client).get(family)
    max_depth = depth if isinstance(depth, int) and depth >= 1 else None

    nested = slug_rules.build_page_slug(page_type, separator=separator, max_depth=max_depth, **parts)
    if not nested:  # empty source → a safe, non-empty fallback file name
        nested = slug_rules.build_slug(keyword, separator=separator) or "page"

    content_path = resolve_github_path(client, content_type)
    public_url = slug_rules.build_page_path(
        page_type, prefixes=prefixes, separator=separator, max_depth=max_depth, trailing_slash=trailing, **parts
    )

    # 2b: reconcile — if the page already exists (possibly at a date-nested or
    # slug-overridden path), overwrite it in place, preserving its live URL.
    existing = _reconcile_lookup(client, content_path, nested)
    if existing:
        return {
            "page_type": page_type,
            "content_path": content_path,
            "nested_slug": nested,
            "frontmatter_slug": existing.get("slug") or nested,
            "file_path": existing["path"],
            "public_url": public_url,
            "reconciled": True,
        }

    # New page: deterministic, automatic collision handling on the leaf segment.
    segments = nested.split("/")
    leaf = slug_rules.apply_collision(
        segments[-1],
        identity=(page_type, keyword, content_path),
        taken=taken,
        separator=separator,
    )
    segments[-1] = leaf
    nested = "/".join(segments)

    file_path = f"{content_path}/{nested}.md" if content_path else f"{nested}.md"
    return {
        "page_type": page_type,
        "content_path": content_path,
        "nested_slug": nested,
        "frontmatter_slug": nested,
        "file_path": file_path,
        "public_url": public_url,
        "reconciled": False,
    }
