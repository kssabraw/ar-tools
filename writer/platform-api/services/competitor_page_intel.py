"""Competitor page-generation targeting analysis.

The content watch (``competitor_intel``) already captures competitors' newly
published page URLs (``competitor_pages`` → a profile's ``recent_pages``). But
nothing turned those raw URLs into *targeting intelligence* — so the
conversational strategist (SerMaStr) knew a competitor had "17 new pages" yet
had to improvise a live ``site:`` search mid-conversation to learn *which*
pages, then reason by hand about whether they were being built in the client's
weak coverage areas. This module makes that analysis proactive and
deterministic:

  * ``extract_page_target(url)`` → a cleaned human label for what a page
    targets (its terminal, non-generic path segment, de-hyphenated, with
    trailing state / postcode tokens stripped):
    ``"/services/east-melbourne-vic-3002/"`` → ``"East Melbourne"``.
  * ``match_pages_to_places(pages, places)`` → which competitor pages target
    one of the client's own priority places (weak grid zones / Action-Plan
    create-page targets) = the *contested* set, vs which places are still open.
  * ``summarize_targeting(profiles, priority_places)`` → the per-competitor
    "what they're building" list plus the contested / open split, ready to drop
    into the strategist digest, the chat context, and the notification.

Everything here is pure + unit-tested (no LLM, no network, no DB). The impure
callers (the digest / chat context providers, the reopt-planner land-grab
action, the content-watch notification) load the stored URLs + the client's
weak zones and feed them in.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

# Silo / structural path words that are never a "target" on their own.
_GENERIC_SLUG_TOKENS = {
    "services", "service", "areas", "area", "locations", "location",
    "service-areas", "our-services", "pages", "page",
}
# 3–5 digit run = a postcode/zip token in a slug ("...-vic-3002").
_POSTCODE_RE = re.compile(r"^\d{3,5}$")
# State / territory abbreviations that trail a place in a location-page slug
# ("port-melbourne-vic-3207", "austin-tx"). Used ONLY to clean the display
# label and place tokens — never to reject a match. AU + US + CA + generic.
_STATE_ABBRS = {
    # Australia
    "act", "nsw", "nt", "qld", "sa", "tas", "vic", "wa", "au", "aus",
    # United States
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wv", "wi",
    "wy", "us", "usa",
    # Canada
    "ab", "bc", "mb", "nb", "nl", "ns", "on", "pe", "qc", "sk",
}


def _tokens(text: Optional[str]) -> list[str]:
    """Lowercased alphanumeric tokens (splits on hyphens, slashes, punctuation)."""
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _path(url: Optional[str]) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "//" in raw:
        return urlparse(raw).path
    # A bare path/slug was passed rather than a full URL.
    return raw if raw.startswith("/") else "/" + raw


def _segments(url: Optional[str]) -> list[str]:
    return [s for s in _path(url).split("/") if s]


def page_slug_tokens(url: Optional[str]) -> set[str]:
    """Every alphanumeric token in a URL's path — the set a place is matched
    against. Postcodes are dropped (noise); generic silo words are kept but are
    harmless since a place only matches when its OWN tokens are all present."""
    return {t for t in _tokens(_path(url)) if not _POSTCODE_RE.match(t)}


def extract_page_target(url: Optional[str]) -> str:
    """A human-readable label for what a page targets: the last non-generic path
    segment, de-hyphenated, trailing state + postcode tokens stripped,
    Title-Cased. ``"/services/east-melbourne-vic-3002/"`` → ``"East Melbourne"``;
    ``"/blog/how-to-clean-gutters"`` → ``"How To Clean Gutters"``. Best-effort:
    a segment that reduces to nothing (pure postcode/state) → ``""``."""
    seg = ""
    for s in reversed(_segments(url)):
        if s.lower() not in _GENERIC_SLUG_TOKENS and _tokens(s):
            seg = s
            break
    toks = [t for t in _tokens(seg) if not _POSTCODE_RE.match(t)]
    # Strip trailing state abbreviations ("...-vic", "...-tx"); a leading real
    # word keeps the place intact ("port-melbourne-vic" → "port melbourne").
    while len(toks) > 1 and toks[-1] in _STATE_ABBRS:
        toks.pop()
    if len(toks) == 1 and toks[0] in _STATE_ABBRS:
        return ""
    return " ".join(w.capitalize() for w in toks)


def place_tokens(place: Optional[str]) -> list[str]:
    """Match tokens for a client priority place: its city name only (drop the
    ``", ADMIN"`` suffix, state abbreviations and postcodes).
    ``"Port Melbourne, VIC"`` → ``["port", "melbourne"]``."""
    city = (place or "").split(",")[0]
    return [t for t in _tokens(city) if t not in _STATE_ABBRS and not _POSTCODE_RE.match(t)]


def page_targets_place(url: Optional[str], place: Optional[str]) -> bool:
    """True when a competitor page's slug contains ALL of a place's tokens
    (token-level, never substring — ``"kew"`` matches the ``kew`` segment of
    ``kew-vic-3121`` but not the ``kew`` inside ``kewell``). A place must carry
    at least one real token."""
    ptoks = place_tokens(place)
    if not ptoks:
        return False
    slug = page_slug_tokens(url)
    return all(t in slug for t in ptoks)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = (it or "").casefold()
        if it and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def match_pages_to_places(pages: list[dict], places: list[str]) -> list[dict]:
    """Cross-reference competitor pages against the client's priority places.

    ``pages``: ``[{"competitor", "url", "first_seen"}]`` (a flattened list of
    every competitor's recent pages). ``places``: the client's own priority
    place strings (weak grid zones / Action-Plan create-page targets).

    Returns one ``{"place", "competitor", "url", "first_seen"}`` row per
    (place, page) hit, place order preserved (weakest-first from the caller).
    Deterministic."""
    out: list[dict] = []
    for pl in places or []:
        for pg in pages or []:
            if page_targets_place(pg.get("url"), pl):
                out.append({
                    "place": pl,
                    "competitor": pg.get("competitor") or pg.get("name"),
                    "url": pg.get("url"),
                    "first_seen": pg.get("first_seen"),
                })
    return out


def flatten_recent_pages(profiles: list[dict]) -> list[dict]:
    """Flatten build_profiles' per-competitor ``recent_pages`` into the
    ``match_pages_to_places`` input shape. Pure."""
    pages: list[dict] = []
    for p in profiles or []:
        name = p.get("name")
        for rp in p.get("recent_pages") or []:
            pages.append({
                "competitor": name,
                "url": rp.get("url"),
                "first_seen": rp.get("first_seen"),
            })
    return pages


def summarize_targeting(profiles: list[dict], priority_places: Optional[list[str]] = None) -> dict:
    """Turn competitor profiles (build_profiles output) + the client's priority
    places into a proactive targeting read.

    Returns::

        {
          "competitor_targets": [{"name", "targets": [label, ...], "count"}],
          "contested": [{"place", "competitor", "url", "first_seen"}],
          "contested_places": [place, ...],   # priority places a rival built for
          "open_places": [place, ...],         # priority places still uncontested
        }

    ``competitor_targets`` is present whenever any competitor has recent pages
    (so "what are they building" is answerable even with no priority places on
    file); the contested/open split is empty until priority places exist. Pure."""
    per_comp: list[dict] = []
    for p in profiles or []:
        labels = _dedupe(
            extract_page_target(rp.get("url"))
            for rp in (p.get("recent_pages") or [])
        )
        labels = [l for l in labels if l]
        if labels:
            per_comp.append({"name": p.get("name"), "targets": labels, "count": len(labels)})

    places = priority_places or []
    matches = match_pages_to_places(flatten_recent_pages(profiles), places)
    contested_places = _dedupe(m["place"] for m in matches)
    contested_lower = {p.casefold() for p in contested_places}
    open_places = [pl for pl in places if pl.casefold() not in contested_lower]
    return {
        "competitor_targets": per_comp,
        "contested": matches,
        "contested_places": contested_places,
        "open_places": open_places,
    }


def contested_by_place(matches: list[dict]) -> dict[str, list[dict]]:
    """Group ``match_pages_to_places`` output by place (casefolded key) →
    ``[{"competitor", "url", "first_seen"}]``. Pure. Used by the reopt planner
    to upgrade a weak-area action into a land-grab action."""
    out: dict[str, list[dict]] = {}
    for m in matches:
        key = (m.get("place") or "").casefold()
        if not key:
            continue
        out.setdefault(key, []).append({
            "competitor": m.get("competitor"),
            "url": m.get("url"),
            "first_seen": m.get("first_seen"),
        })
    return out
