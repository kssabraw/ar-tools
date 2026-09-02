"""User-supplied Plan Silo targets — matrices and combinations, via paste or CSV.

The AI silo planner researches a seed service + area and *discovers* candidate
pages. This module instead lets the team supply their OWN page targets two ways:

  1. **Matrix** — a list of services × a list of locations → every
     "<service> <location>" combination, grouped into one silo per service.
  2. **List** — an explicit list of page targets, one per line, or a CSV with
     optional `group`/`location`/`supporting` columns.

Both parse to the SAME silo/page shape the AI planner produces, then run through
the identical existing-page marking (`local_seo_silo._to_items` +
`_build_site_url_list`) so uploaded targets are flagged found / on_site / missing
and are selectable in the same bulk-create flow.

Deliberately trust-the-user: no LLM, no geocoding verification, no demand
research — what you paste is what you get (deduped). The pure parsers are
unit-tested; the marking is reused wholesale from `local_seo_silo`.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Optional

from services import local_seo_silo

# CSV header aliases → our canonical column names. A header row lets the user name
# a group/silo, a location (for the on_site place check), and supporting keywords;
# without a header, columns are positional (keyword, group).
_KEYWORD_HEADERS = {"keyword", "keywords", "page", "target", "topic", "page target"}
_GROUP_HEADERS = {"group", "silo", "category", "section", "cluster"}
_LOCATION_HEADERS = {"location", "location_name", "area", "city", "suburb", "place", "neighborhood"}
_SUPPORTING_HEADERS = {"supporting", "supporting_keywords", "secondary", "variants", "also"}

_DEFAULT_LIST_GROUP = "Custom targets"

# Hard ceiling on how many targets one upload can mark in a single (synchronous)
# request. The AI plan is bounded by the LLM; a user-supplied matrix is bounded
# only by what's pasted (a 500×500 matrix is 250k combos), so cap it to keep the
# response + any subsequent bulk-create sane. Generous enough for real use
# (e.g. 30 services × 100 suburbs), a guard against pathological input.
_MAX_TARGETS = 3000


# ── pure helpers (no I/O) — unit-tested ──────────────────────────────────────

def _clean_lines(text: str) -> list[str]:
    """Non-empty, trimmed lines of `text`, deduped case-insensitively (first
    occurrence wins, order preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        value = raw.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def build_matrix_silos(services_text: str, locations_text: str) -> list[dict]:
    """Cartesian product of services × locations → one silo per service, each
    holding "<service> <location>" page targets.

    Each page carries the bare `location_name` so the on_site check matches a
    generic location page for the place, exactly like the AI planner's
    Neighborhoods silo. Empty when either axis is empty. Composed keywords are
    deduped globally (first wins)."""
    services = _clean_lines(services_text)
    locations = _clean_lines(locations_text)
    if not services or not locations:
        return []
    silos: list[dict] = []
    seen: set[str] = set()
    for service in services:
        pages: list[dict] = []
        for location in locations:
            keyword = f"{service} {location}".strip()
            key = keyword.lower()
            if not keyword or key in seen:
                continue
            seen.add(key)
            pages.append(
                {"keyword": keyword, "supporting_keywords": [], "location_name": location}
            )
        if pages:
            silos.append({"silo": service, "pages": pages})
    return silos


def parse_list_rows(text: str) -> list[dict]:
    """Parse a pasted list / CSV of page targets into
    ``[{keyword, group?, location_name?, supporting_keywords}]`` (deduped by
    keyword, case-insensitive; order preserved).

    Forgiving by design:
      - a plain one-keyword-per-line paste → each line is a keyword;
      - a **header** row (a cell named keyword/page/target/…) maps columns by name
        — `group`/`silo`, `location`/`area`/`city`, `supporting` (``;``/``,``-split);
      - otherwise columns are **positional**: col 0 = keyword, col 1 = group.

    Rows with an empty keyword are skipped."""
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text or ""))
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        return []

    header = [cell.lower() for cell in rows[0]]
    col: dict[str, int]
    if any(h in _KEYWORD_HEADERS for h in header):
        col = {}
        for idx, h in enumerate(header):
            if h in _KEYWORD_HEADERS:
                col.setdefault("keyword", idx)
            elif h in _GROUP_HEADERS:
                col.setdefault("group", idx)
            elif h in _LOCATION_HEADERS:
                col.setdefault("location_name", idx)
            elif h in _SUPPORTING_HEADERS:
                col.setdefault("supporting", idx)
        data = rows[1:]
    else:
        # No header → keyword, then an optional group column.
        col = {"keyword": 0, "group": 1}
        data = rows

    def cell(row: list[str], name: str) -> str:
        idx = col.get(name)
        return row[idx] if (idx is not None and idx < len(row)) else ""

    out: list[dict] = []
    seen: set[str] = set()
    for row in data:
        keyword = cell(row, "keyword")
        if not keyword:
            continue
        key = keyword.lower()
        if key in seen:
            continue
        seen.add(key)
        supporting: list[str] = []
        sup_seen: set[str] = {key}
        for part in re.split(r"[;,]", cell(row, "supporting")):
            s = part.strip()
            if s and s.lower() not in sup_seen:
                sup_seen.add(s.lower())
                supporting.append(s)
        parsed: dict = {"keyword": keyword, "supporting_keywords": supporting}
        group = cell(row, "group")
        if group:
            parsed["group"] = group
        location = cell(row, "location_name")
        if location:
            parsed["location_name"] = location
        out.append(parsed)
    return out


def build_list_silos(text: str, default_group: str = _DEFAULT_LIST_GROUP) -> list[dict]:
    """Group a parsed target list into silos by its `group` column (falling back to
    `default_group`), preserving first-seen group order → the AI-planner page
    shape."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in parse_list_rows(text):
        group = row.pop("group", "") or default_group
        if group not in groups:
            groups[group] = []
            order.append(group)
        groups[group].append(row)
    return [{"silo": group, "pages": groups[group]} for group in order]


def build_silos(
    input_mode: str, services: str, locations: str, targets: str
) -> list[dict]:
    """Dispatch to the matrix or list builder by `input_mode`."""
    if input_mode == "matrix":
        return build_matrix_silos(services, locations)
    return build_list_silos(targets)


def cap_silos(per_silo: list[dict], cap: int = _MAX_TARGETS) -> tuple[list[dict], Optional[str]]:
    """Trim the total page count across all silos to `cap`, preserving silo + page
    order. Returns ``(capped_silos, note)`` — `note` is set only when trimming
    happened. Silos emptied by the trim are dropped."""
    total = sum(len(silo.get("pages") or []) for silo in per_silo)
    if total <= cap:
        return per_silo, None
    capped: list[dict] = []
    remaining = cap
    for silo in per_silo:
        pages = silo.get("pages") or []
        if remaining <= 0:
            break
        kept = pages[:remaining]
        remaining -= len(kept)
        if kept:
            capped.append({**silo, "pages": kept})
    note = (
        f"Only the first {cap} of {total} targets were checked — narrow your "
        "matrix / list to see the rest."
    )
    return capped, note


# ── orchestration (marks against the client's site + in-tool pages) ───────────

async def plan_custom_targets(
    client_id: str,
    input_mode: str,
    services: str,
    locations: str,
    targets: str,
    location: str,
    location_code: Optional[int],
) -> dict:
    """Parse the user's matrix/list, then mark every target found / on_site /
    missing against the client's live site + in-tool pages — the same marking the
    AI plan uses — so uploaded targets drop straight into the bulk-create flow.

    Returns ``{"items": [...], "degraded_notes": [...]}``. No LLM / no paid calls
    beyond the site-discovery the marking already does (sitemap first, one
    DataForSEO ``site:`` fallback)."""
    per_silo = build_silos(input_mode, services, locations, targets)
    if not per_silo:
        return {"items": [], "degraded_notes": ["No targets were provided."]}
    per_silo, cap_note = cap_silos(per_silo)

    site_urls, site_note = await local_seo_silo._build_site_url_list(client_id, location_code)
    seed_city = local_seo_silo._parse_area(location)[0] or (location or "").strip()
    items = local_seo_silo._to_items(per_silo, client_id, site_urls, seed_city)
    notes = [n for n in (cap_note, site_note) if n]
    return {"items": items, "degraded_notes": notes}
