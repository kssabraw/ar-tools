"""PAA → SEO Neo v1 — pure helpers for the content half.

The methodology's atomic unit is the **PAA string as a universal join key**
(reference §3): one exact-match "People Also Ask" buyer question, filed
*identically* as the blog title/an H2, the GBP post, and the syndication title,
and linking HIGH to the client's service page. This module holds the PURE
(no-I/O) helpers that make that discipline enforceable — everything here is
independently unit-testable, and the I/O (the SERP pull, market enrichment, the
site-URL discovery, the DB) lives in ``services/paa_sets_service.py``.

The three writing rules (reference §4, PRD §4.2), all reused seams:

  1. **One question → one post** — structural (one blog ``run`` per chosen PAA).
  2. **Exact-match everywhere** — ``compose_writer_notes`` tells the writer the
     PAA string must be the title/an H2; ``check_exact_match`` verifies it
     deterministically (an LLM can be talked out of it; a check cannot).
  3. **Link HIGH to the service page** — ``compose_writer_notes`` names the
     service-page URL as the primary internal link; ``service_link_verdict``
     reuses ``local_seo_matrix.check_internal_links`` to verify it.

Confidence tags carried from the reference into user-facing copy:
  * exact-match-everywhere + link-high are **[BELIEF]** (the source group's
    working model, not confirmed Google behaviour) — strong defaults, not laws.
  * the ~1,000-neighborhood-pages cannibalization failure is **[PROVEN]**.

Reuse (PRD §7 — don't rebuild): ``website_plan.slugify`` for the cannibalization
slug key; ``local_seo_matrix.check_internal_links`` / ``scale_gates`` /
``MATRIX_SIGNOFF_THRESHOLD`` for the service-page link check + the scale
sign-off; ``site_page_index`` (in the impure layer) for existing-page matching.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from services.local_seo_matrix import (
    MATRIX_SIGNOFF_THRESHOLD,
    check_internal_links,
    scale_gates,
)
from services.website_plan import slugify

# One immediate "create PAA posts" batch stays small — a PAA set is ~4 questions
# (reference §5, SOP 05), so this is a guard against a runaway create, not a real
# ceiling. Over it trips a human sign-off (reused scale-gate pattern).
PAA_MAX_PER_RUN = 12

__all__ = [
    "PAA_MAX_PER_RUN",
    "MATRIX_SIGNOFF_THRESHOLD",
    "normalize_text",
    "geo_query",
    "slugify_question",
    "build_paa_candidates",
    "compose_writer_notes",
    "check_exact_match",
    "service_link_verdict",
    "verify_item_checks",
    "resolve_service_page_url",
    "find_slug_collisions",
    "cannibalization_gates",
]


# ── text normalization ──────────────────────────────────────────────────────


def normalize_text(value: Optional[str]) -> str:
    """Casefold + collapse whitespace, for exact-match comparison. Pure."""
    return " ".join((value or "").split()).strip().lower()


def _strip_trailing_punct(value: str) -> str:
    """Drop trailing ?/./! and surrounding quotes so "exact match" is judged on
    the words, not a headline's punctuation choice. Pure."""
    return value.strip().strip("\"'").rstrip("?.!").strip()


# ── the geo-modified PAA query (geo_mode) ─────────────────────────────────────


def geo_query(service_keyword: str, location: Optional[str], geo_mode: str) -> str:
    """The seed string the PAA pull searches for.

    ``geo`` (default) appends the city — a local page ranks on "<service>
    <city>", and the source's local-SEO grain is geo-modified (PRD §8.4). Mirrors
    ``local_seo_precheck._ranking_queries``: the city is only appended when it
    isn't already in the keyword. ``naked`` searches the bare service keyword (the
    contested-but-surfaced alternative, reference §9). Pure."""
    kw = (service_keyword or "").strip()
    if not kw:
        return ""
    # Geo is the default: only an explicit 'naked' searches the bare keyword; any
    # other value (incl. the normalized default) is geo-modified.
    if (geo_mode or "geo").strip().lower() == "naked":
        return kw
    city = (location or "").split(",")[0].strip()
    if city and city.lower() not in kw.lower():
        return f"{kw} {city}"
    return kw


# ── candidate assembly ────────────────────────────────────────────────────────


def slugify_question(question: str) -> str:
    """The cannibalization-guard slug for a PAA string (reuses website_plan)."""
    return slugify(question or "")


def build_paa_candidates(
    paa_strings: Iterable[str],
    market: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """Assemble candidate paa_item dicts from pulled PAA questions + reused
    DataForSEO market enrichment.

    ``market`` is ``{keyword_lower: {search_volume, cpc, competition}}`` from
    ``keyword_market.parse_market_items`` (a dict keyed by lower-cased keyword).
    Dedupes case-insensitively, drops blanks + any question that slugifies to
    nothing (all-generic, no usable slug), preserves first-seen order. Pure."""
    market = market or {}
    out: list[dict] = []
    seen: set[str] = set()
    for raw in paa_strings or []:
        q = " ".join(str(raw or "").split()).strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        slug = slugify_question(q)
        if not slug:
            continue
        seen.add(key)
        m = market.get(key) or {}
        out.append(
            {
                "question": q,
                "slug": slug,
                "volume": m.get("search_volume"),
                "cpc_usd": m.get("cpc"),
                "competition": m.get("competition"),
            }
        )
    return out


# ── the three writing rules → writer_notes ────────────────────────────────────


def compose_writer_notes(
    question: str,
    service_page_url: Optional[str],
    *,
    service_keyword: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """The per-run editorial guidance that carries the three PAA writing rules
    into the Blog Writer via the existing ``writer_notes`` → ``user_notes`` seam.

    The rules are stated as hard constraints (the writer honours them; a
    deterministic post-check verifies exact-match + the service-page link). No
    Writer output-schema change — this rides on the same ``writer_notes`` seam the
    "Write this post" handoff already uses. Pure."""
    q = " ".join((question or "").split()).strip()
    lines: list[str] = [
        "PAA CONTENT RULES (follow exactly — these are the entity-resolution "
        "mechanism, not style):",
        f'1. This post answers exactly ONE buyer question: "{q}". Do not blend in '
        "any other question or topic — one question, one post.",
        f'2. Use that exact question, verbatim, as the article title AND as an H2 '
        f'heading: "{q}". Same wording in both, no paraphrase.',
        "3. Answer the question directly and completely, up top, in the reader's "
        "own words before expanding.",
    ]
    if service_page_url:
        anchor = (service_keyword or "").strip()
        anchor_hint = f' (anchor text like "{anchor}")' if anchor else ""
        lines.append(
            f"4. The PRIMARY internal link is the service page: {service_page_url}"
            f"{anchor_hint}. Link HIGH — within the first section, from the "
            "answer itself — not from a footer. This is the money page; do not "
            "link the homepage or a blog index as the primary link."
        )
    else:
        lines.append(
            "4. Link HIGH to the client's service (money) page from the first "
            "section — not the homepage, not a blog index."
        )
    if location:
        lines.append(
            f"5. This is a local page for {location} — keep the geography natural "
            "and specific, never stuffed."
        )
    return "\n".join(lines)


# ── deterministic verification (enforcement made visible) ─────────────────────


def check_exact_match(
    question: str,
    *,
    title: Optional[str] = None,
    h1: Optional[str] = None,
    headings: Optional[Iterable[str]] = None,
) -> dict:
    """Did the finished post state the PAA string verbatim as its title / an H2?

    Returns ``{ok, match, found_in, question}`` where ``match`` is ``"exact"``
    (a title/H1/heading equals the PAA, whitespace+case+trailing-punctuation
    normalized), ``"contains"`` (the PAA appears verbatim inside one), or
    ``"none"``. ``ok`` is True for exact OR contains — the string is present and
    stated identically, which is the rule; ``match`` distinguishes them so the UI
    can nudge toward a clean exact title. Pure."""
    target = _strip_trailing_punct(normalize_text(question))
    if not target:
        return {"ok": False, "match": "none", "found_in": None, "question": question}

    candidates: list[tuple[str, str]] = []
    if title:
        candidates.append(("title", title))
    if h1:
        candidates.append(("h1", h1))
    for h in headings or []:
        if h:
            candidates.append(("h2", h))

    # Exact wins (strongest signal); fall back to verbatim containment.
    contains_hit: Optional[str] = None
    for where, text in candidates:
        norm = _strip_trailing_punct(normalize_text(text))
        if norm == target:
            return {"ok": True, "match": "exact", "found_in": where, "question": question}
        if contains_hit is None and target in norm:
            contains_hit = where
    if contains_hit is not None:
        return {"ok": True, "match": "contains", "found_in": contains_hit, "question": question}
    return {"ok": False, "match": "none", "found_in": None, "question": question}


def service_link_verdict(html: str, service_page_url: Optional[str]) -> dict:
    """Does the finished article link to the service page? Reuses
    ``local_seo_matrix.check_internal_links`` (URL-path matching over the HTML).

    Returns ``{ok, expected, present, service_page_url}``. When no service-page
    URL was resolved for the set, returns ``{ok: None, ...}`` (not applicable —
    the "link high" rule can't be verified without a target). Pure."""
    if not service_page_url:
        return {"ok": None, "expected": 0, "present": [], "service_page_url": None}
    coverage = check_internal_links(html or "", [{"url": service_page_url}])
    return {
        "ok": not coverage["missing"],
        "expected": coverage["expected"],
        "present": coverage["present"],
        "service_page_url": service_page_url,
    }


def verify_item_checks(
    question: str,
    html: str,
    service_page_url: Optional[str],
    *,
    title: Optional[str] = None,
    h1: Optional[str] = None,
    headings: Optional[Iterable[str]] = None,
) -> dict:
    """Bundle the two deterministic post-generation checks for one PAA post:
    exact-match (rule 2) + the service-page link (rule 3). Rule 1 (one question →
    one post) is structural — guaranteed by creating one run per PAA — so it
    isn't re-checked here. Pure."""
    return {
        "exact_match": check_exact_match(
            question, title=title, h1=h1, headings=headings
        ),
        "service_link": service_link_verdict(html, service_page_url),
    }


# ── service-page URL resolution (PRD §8.3) ────────────────────────────────────


def resolve_service_page_url(
    explicit: Optional[str], auto_matched: Optional[str]
) -> dict:
    """Resolve the "link high" target: explicit field → auto-matched live page →
    prompt the user. Never a silent guess (PRD §8.3). Pure — the impure layer
    supplies ``auto_matched`` (from ``site_page_index``).

    Returns ``{url, source, needs_prompt}`` with source ``"explicit"`` |
    ``"auto"`` | ``"none"``."""
    e = (explicit or "").strip()
    if e:
        return {"url": e, "source": "explicit", "needs_prompt": False}
    a = (auto_matched or "").strip()
    if a:
        return {"url": a, "source": "auto", "needs_prompt": False}
    return {"url": None, "source": "none", "needs_prompt": True}


# ── the cannibalization guard (PRD §4.3, reference §10) ───────────────────────


def find_slug_collisions(
    candidate_slugs: Iterable[str], existing_items: Iterable[dict]
) -> list[dict]:
    """Cross-set slug collisions: a candidate PAA whose slug is already used by
    one of this client's OTHER PAA items (a different set / a different city) —
    "never reuse an identical PAA slug across cities" (reference §10). Pure.

    ``existing_items`` is a list of the client's other paa_items (dicts with
    ``slug`` + context). Returns ``[{slug, existing}]`` per collision."""
    by_slug: dict[str, list[dict]] = {}
    for it in existing_items or []:
        s = (it.get("slug") or "").strip()
        if s:
            by_slug.setdefault(s, []).append(it)
    out: list[dict] = []
    seen: set[str] = set()
    for slug in candidate_slugs or []:
        s = (slug or "").strip()
        if not s or s in seen:
            continue
        if s in by_slug:
            seen.add(s)
            out.append({"slug": s, "existing": by_slug[s]})
    return out


def cannibalization_gates(
    *,
    create_count: int,
    total_client_paa_pages: int,
    slug_collisions: Optional[list[dict]] = None,
    existing_site_matches: Optional[list[dict]] = None,
    signoff_acknowledged: bool = False,
    max_per_run: int = PAA_MAX_PER_RUN,
    signoff_threshold: int = MATRIX_SIGNOFF_THRESHOLD,
) -> list[dict]:
    """Blocking / acknowledgeable issues before a "create PAA posts" batch,
    mirroring ``local_seo_matrix.scale_gates`` (PRD §4.3). Pure.

    Layers, most-specific first:
      * ``paa_slug_collision`` — a chosen PAA reuses a slug the client already has
        elsewhere; acknowledgeable (the ~1,000-page failure guard, reference §10).
      * ``paa_existing_page`` — the client's live site already answers this PAA;
        acknowledgeable (don't cannibalize your own ranking page).
      * ``matrix_signoff_required`` / ``matrix_cell_limit`` — the reused scale
        gates over the client's TOTAL PAA-page footprint + this run's size."""
    issues: list[dict] = []
    slug_collisions = slug_collisions or []
    existing_site_matches = existing_site_matches or []

    if slug_collisions and not signoff_acknowledged:
        slugs = ", ".join(sorted({c["slug"] for c in slug_collisions}))
        issues.append(
            {
                "kind": "paa_slug_collision",
                "message": (
                    f"{len(slug_collisions)} chosen question(s) reuse a PAA slug this "
                    f"client already has on another set/city ({slugs}). Reusing an "
                    "identical PAA slug across cities cannibalizes — rename or drop "
                    "before creating."
                ),
                "blocking": True,
                "acknowledgeable": True,
            }
        )
    if existing_site_matches and not signoff_acknowledged:
        issues.append(
            {
                "kind": "paa_existing_page",
                "message": (
                    f"{len(existing_site_matches)} chosen question(s) look already "
                    "answered by a live page on the client's site — creating a new "
                    "post would compete with it. Reoptimize the existing page instead, "
                    "or acknowledge to proceed."
                ),
                "blocking": True,
                "acknowledgeable": True,
                "matches": existing_site_matches,
            }
        )
    # Reused scale gates: TOTAL footprint over the sign-off line + this run's size.
    issues.extend(
        scale_gates(
            total_client_paa_pages,
            create_count,
            max_per_run=max_per_run,
            signoff_threshold=signoff_threshold,
            signoff_acknowledged=signoff_acknowledged,
        )
    )
    return issues
