"""Step 2 - Superscript injection with stacked-marker ascending sort.

Per sources-cited-module-prd-v1_1.md §7 Step 2:
- Each {{cit_N}} marker → <sup><a href="#sources-cited-{n}" id="ref-{cit_id}-{instance}">[{n}]</a></sup>
- Stacked markers (consecutive, no prose between) sort ASCENDING by citation number.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .markers import MARKER_RE


def _build_sup(cite_number: int, citation_id: str, instance: int) -> str:
    return (
        f'<sup><a href="#sources-cited-{cite_number}" '
        f'id="ref-{citation_id}-{instance}">[{cite_number}]</a></sup>'
    )


def inject_superscripts(
    body: str,
    number_map: dict[str, int],
    instance_counter: dict[str, int],
) -> str:
    """Replace markers in a body string. Stacked markers are sorted by
    citation number ascending. instance_counter is mutated across calls
    so per-citation instance IDs increment globally."""
    if not body:
        return body

    # Find all stacked groups (markers with no intervening characters)
    groups = _find_stacked_groups(body)
    if not groups:
        return body

    # Replace from the back to keep positions stable
    out = body
    for start, end, ids in reversed(groups):
        # Sort ascending by citation number
        ids_sorted = sorted(ids, key=lambda cid: number_map.get(cid, 0))
        replacement = ""
        for cid in ids_sorted:
            instance_counter[cid] = instance_counter.get(cid, 0) + 1
            replacement += _build_sup(
                cite_number=number_map.get(cid, 0),
                citation_id=cid,
                instance=instance_counter[cid],
            )
        out = out[:start] + replacement + out[end:]
    return out


def _find_stacked_groups(body: str) -> list[tuple[int, int, list[str]]]:
    """Return [(start, end, [cit_ids in source order]), ...] where each
    group is a maximal run of adjacent markers (zero characters between
    consecutive marker matches)."""
    matches = list(MARKER_RE.finditer(body))
    if not matches:
        return []

    groups: list[tuple[int, int, list[str]]] = []
    current_start = matches[0].start()
    current_end = matches[0].end()
    current_ids = [matches[0].group(1)]

    for m in matches[1:]:
        if m.start() == current_end:
            # Adjacent - extend current group
            current_end = m.end()
            current_ids.append(m.group(1))
        else:
            groups.append((current_start, current_end, current_ids))
            current_start = m.start()
            current_end = m.end()
            current_ids = [m.group(1)]
    groups.append((current_start, current_end, current_ids))
    return groups


def inject_into_article(
    article: list[dict[str, Any]],
    number_map: dict[str, int],
) -> list[dict[str, Any]]:
    """Mutate body fields in place. Returns the same list for chaining."""
    instance_counter: dict[str, int] = defaultdict(int)
    sorted_sections = sorted(
        [(i, s) for i, s in enumerate(article) if isinstance(s, dict)],
        key=lambda pair: pair[1].get("order", 0),
    )
    for _, section in sorted_sections:
        body = section.get("body") or ""
        if not body:
            continue
        section["body"] = inject_superscripts(body, number_map, instance_counter)
    return article
