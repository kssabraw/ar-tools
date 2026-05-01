"""Step 1 — marker discovery + first-appearance numbering.

Per sources-cited-module-prd-v1_1.md §7 Step 1.
Marker pattern is `\\{\\{(cit_[0-9]+)\\}\\}` per the v1.1 PRD constraint.
"""

from __future__ import annotations

import re
from typing import Any

MARKER_RE = re.compile(r"\{\{(cit_[0-9]+)\}\}")
CITATION_ID_RE = re.compile(r"^cit_[0-9]+$")


def scan_markers(article: list[dict[str, Any]]) -> tuple[dict[str, int], list[str]]:
    """Walk article in ascending order index, find every {{cit_N}} marker
    in body fields, and assign sequential citation numbers by first
    appearance.

    Returns (citation_number_map, ordered_used_citations).
    """
    sorted_sections = sorted(
        [s for s in article if isinstance(s, dict)],
        key=lambda s: s.get("order", 0),
    )

    number_map: dict[str, int] = {}
    next_number = 1
    for section in sorted_sections:
        body = section.get("body") or ""
        for match in MARKER_RE.finditer(body):
            cid = match.group(1)
            if cid in number_map:
                continue
            number_map[cid] = next_number
            next_number += 1

    ordered = sorted(number_map.keys(), key=lambda cid: number_map[cid])
    return (number_map, ordered)


def find_markers_in_headings(article: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Returns list of (order, heading_text) where heading contains a marker.
    Per PRD: markers in heading fields cause an abort."""
    out = []
    for s in article:
        if not isinstance(s, dict):
            continue
        heading = s.get("heading") or ""
        if MARKER_RE.search(heading):
            out.append((s.get("order", 0), heading))
    return out


def all_marker_ids_in_body(article: list[dict[str, Any]]) -> set[str]:
    """All distinct citation IDs found in body markers across the article."""
    out: set[str] = set()
    for s in article:
        if not isinstance(s, dict):
            continue
        body = s.get("body") or ""
        out.update(MARKER_RE.findall(body))
    return out


def is_valid_citation_id(cid: str) -> bool:
    return bool(CITATION_ID_RE.match(cid or ""))
