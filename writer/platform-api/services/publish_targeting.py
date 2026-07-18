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


def client_known_places(client: dict) -> list[str]:
    """The client's known place names (business location + target cities + GBP
    service-area places), de-duped case-insensitively, order preserved."""
    places: list[str] = []
    bl = client.get("business_location")
    if isinstance(bl, str) and bl.strip():
        places.append(bl.strip())
    for c in client.get("target_cities") or []:
        if isinstance(c, str) and c.strip():
            places.append(c.strip())
    gbp = client.get("gbp")
    if isinstance(gbp, dict):
        for p in gbp.get("service_area_places") or []:
            if isinstance(p, str) and p.strip():
                places.append(p.strip())
    seen: set[str] = set()
    out: list[str] = []
    for p in places:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
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


def _page_type_and_parts(content_type: str | None, keyword: str, places: list[str]) -> tuple[str, dict]:
    """Map a run content_type + keyword to an SOP page type + build_page_path
    parts. location_page splits into local_landing / top_level_location via the
    client's known places."""
    ct = content_type or "blog_post"
    if ct == "service_page":
        return "top_level_service", {"service": keyword}
    if ct == "location_page":
        place, remainder = extract_place(keyword, places)
        if place and remainder:
            return "local_landing", {"location": place, "service": remainder}
        if place:
            return "top_level_location", {"location": place}
        return "top_level_location", {"location": keyword}
    if ct in ("product", "ecom_page", "ecommerce_page"):
        return "product", {"product": keyword}
    return "blog_post", {"keyword": keyword}


def resolve_publish_target(
    content_type: str | None,
    source: str | None,
    *,
    client: dict,
    taken: object = (),
) -> dict[str, Any]:
    """Resolve the commit target for one piece of content. `source` is the run's
    keyword (falls back to the title upstream)."""
    keyword = (source or "").strip()
    separator, prefixes, trailing = _inferred_url(client)
    places = client_known_places(client)
    page_type, parts = _page_type_and_parts(content_type, keyword, places)

    nested = slug_rules.build_page_slug(page_type, separator=separator, **parts)
    if not nested:  # empty source → a safe, non-empty fallback file name
        nested = slug_rules.build_slug(keyword, separator=separator) or "page"

    content_path = resolve_github_path(client, content_type)

    # Deterministic, automatic collision handling on the leaf segment (SOP).
    segments = nested.split("/")
    leaf = slug_rules.apply_collision(
        segments[-1],
        identity=(page_type, keyword, content_path),
        taken=taken,
    )
    segments[-1] = leaf
    nested = "/".join(segments)

    file_path = f"{content_path}/{nested}.md" if content_path else f"{nested}.md"
    public_url = slug_rules.build_page_path(
        page_type, prefixes=prefixes, separator=separator, trailing_slash=trailing, **parts
    )
    return {
        "page_type": page_type,
        "content_path": content_path,
        "nested_slug": nested,
        "file_path": file_path,
        "public_url": public_url,
    }
