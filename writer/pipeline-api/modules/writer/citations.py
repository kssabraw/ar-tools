"""Step 7 — Citation usage reconciliation.

Walk every section's body, collect {{cit_N}} markers, and produce the
CitationUsage block.
"""

from __future__ import annotations

import re
from typing import Any

from models.writer import ArticleSection, CitationUsage, CitationUsageEntry

MARKER_RE = re.compile(r"\{\{(cit_\d+)\}\}")


def reconcile_citation_usage(
    article: list[ArticleSection],
    available_citations: list[dict[str, Any]],
) -> CitationUsage:
    """Returns a CitationUsage block summarizing per-citation usage."""
    available_ids = [c.get("citation_id") for c in available_citations if c.get("citation_id")]
    sections_by_citation: dict[str, list[int]] = {}

    for section in article:
        body = section.body or ""
        ids_in_section = MARKER_RE.findall(body)
        for cid in set(ids_in_section):
            sections_by_citation.setdefault(cid, []).append(section.order)
        # Update section's citations_referenced to the deduped list
        section.citations_referenced = list(dict.fromkeys(ids_in_section))

    usage_entries: list[CitationUsageEntry] = []
    for cid in available_ids:
        used_in = sections_by_citation.get(cid, [])
        usage_entries.append(CitationUsageEntry(
            citation_id=cid,
            used=bool(used_in),
            sections_used_in=sorted(set(used_in)),
            marker_placed=bool(used_in),
        ))

    used = sum(1 for u in usage_entries if u.used)
    return CitationUsage(
        total_citations_available=len(available_ids),
        citations_used=used,
        citations_unused=len(available_ids) - used,
        usage=usage_entries,
    )
