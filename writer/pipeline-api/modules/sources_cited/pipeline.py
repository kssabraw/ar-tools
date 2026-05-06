"""Sources Cited orchestrator (schema v1.1).

5 steps from the PRD:
0. Validate writer + research inputs (schema, keyword, marker resolvability,
   citation_id format, integrity check between prose markers and
   citation_usage record)
1. Marker discovery + first-appearance numbering
2. Superscript injection (with ascending sort for stacked markers)
3. MLA-derived entry generation (no LLM)
4. Sources Cited section assembly (header + body appended after conclusion)
5. Output assembly with sources_cited_metadata block
"""

from __future__ import annotations

import copy
import logging
import re
import time
from typing import Any

from models.sources_cited import (
    SourcesCitedMetadata,
    SourcesCitedRequest,
    SourcesCitedResponse,
)

from .entries import build_sources_cited_sections
from .markers import (
    MARKER_RE,
    all_marker_ids_in_body,
    find_markers_in_headings,
    is_valid_citation_id,
    scan_markers,
)
from .superscripts import inject_into_article

logger = logging.getLogger(__name__)


class SourcesCitedError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_WRITER_MIN_VERSION_RE = re.compile(r"^1\.(?:[4-9]|\d{2,})")


def _validate(req: SourcesCitedRequest) -> tuple[dict, dict]:
    writer = req.writer_output
    research = req.research_output

    if not isinstance(writer, dict):
        raise SourcesCitedError("invalid_writer", "writer_output must be a dict")
    if not isinstance(research, dict):
        raise SourcesCitedError("invalid_research", "research_output must be a dict")

    writer_kw = (writer.get("keyword") or "").strip()
    research_kw = (
        research.get("keyword")
        or (research.get("enriched_brief") or {}).get("keyword")
        or ""
    ).strip()
    if not writer_kw or writer_kw.lower() != research_kw.lower():
        raise SourcesCitedError(
            "keyword_mismatch",
            f"writer.keyword='{writer_kw}' vs research.keyword='{research_kw}'",
        )

    schema_version = (writer.get("metadata") or {}).get("schema_version", "")
    if not _WRITER_MIN_VERSION_RE.match(schema_version):
        raise SourcesCitedError(
            "writer_schema_too_old",
            f"writer schema_version='{schema_version}' must be 1.4 or newer",
        )

    article = writer.get("article") or []
    if not isinstance(article, list) or not article:
        raise SourcesCitedError("empty_article", "writer.article is empty or missing")

    return (writer, research)


def _get_citations_by_id(research: dict) -> dict[str, dict]:
    citations_list = (
        research.get("citations")
        or (research.get("enriched_brief") or {}).get("citations")
        or []
    )
    return {
        c.get("citation_id"): c
        for c in citations_list
        if isinstance(c, dict) and c.get("citation_id")
    }


def _used_citation_ids_from_writer(writer: dict) -> set[str]:
    """Set of citation_ids the Writer reports as used:true."""
    usage = (writer.get("citation_usage") or {}).get("usage") or []
    out: set[str] = set()
    for entry in usage:
        if isinstance(entry, dict) and entry.get("used") and entry.get("citation_id"):
            out.add(entry["citation_id"])
    return out


def _all_citation_ids_in_usage(writer: dict) -> set[str]:
    """All citation_ids appearing in the Writer's citation_usage.usage[]."""
    usage = (writer.get("citation_usage") or {}).get("usage") or []
    return {
        entry.get("citation_id")
        for entry in usage
        if isinstance(entry, dict) and entry.get("citation_id")
    }


def _conclusion_order(article: list[dict]) -> int:
    """Return the highest `order` in the article - the order AFTER which
    Sources Cited sections should be inserted.

    The historical name (`_conclusion_order`) reflected an earlier
    layout where the conclusion was always the last numbered section.
    After the writer's article-structure refactor (commit d80e4bd) the
    layout became `body → conclusion → FAQ`, so the conclusion is
    no longer last. Returning conclusion.order + 1/+2 then collided
    with FAQ orders, causing Sources Cited to render INSIDE the FAQ
    section after stable-sort.

    Fix: return max(order) regardless of where the conclusion sits.
    The function name is preserved to avoid an API change in
    build_sources_cited_sections; semantically it now means "the
    insertion anchor for Sources Cited."
    """
    return max(
        (s.get("order", 0) for s in article if isinstance(s, dict)),
        default=0,
    )


def _strip_marker_ids_from_article(article: list[dict], invalid_ids: set[str]) -> None:
    """Remove every {{cit_NNN}} marker whose id is in `invalid_ids` from
    every section body in `article`. Mutates in place. Cleans up
    surrounding whitespace and orphaned punctuation so the prose remains
    readable after removal."""
    if not invalid_ids:
        return

    def _sub(match: re.Match) -> str:
        return "" if match.group(1) in invalid_ids else match.group(0)

    for s in article:
        if not isinstance(s, dict):
            continue
        body = s.get("body")
        if not isinstance(body, str) or not body:
            continue
        cleaned = MARKER_RE.sub(_sub, body)
        if cleaned != body:
            cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
            cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
            s["body"] = cleaned

        # Also clean any per-section citations_referenced list so the
        # section's own bookkeeping doesn't keep dangling IDs.
        listed = s.get("citations_referenced")
        if isinstance(listed, list):
            s["citations_referenced"] = [c for c in listed if c not in invalid_ids]


def _section_marker_reconciliation_warnings(article: list[dict]) -> list[str]:
    """Per-section: if `citations_referenced` lists an ID not actually
    present as a marker in that section's body, flag a warning string."""
    from .markers import MARKER_RE
    warnings: list[str] = []
    for s in article:
        if not isinstance(s, dict):
            continue
        listed = set(s.get("citations_referenced") or [])
        body = s.get("body") or ""
        actual = set(MARKER_RE.findall(body))
        missing = listed - actual
        if missing:
            warnings.append(
                f"section order={s.get('order', 0)} lists {sorted(missing)} but body has no markers for them"
            )
    return warnings


def run_sources_cited(req: SourcesCitedRequest) -> SourcesCitedResponse:
    started = time.perf_counter()
    writer, research = _validate(req)

    article: list[dict] = copy.deepcopy(writer.get("article") or [])
    citations_by_id = _get_citations_by_id(research)

    # Step 0 (continued): heading marker check, ID format, marker resolvability
    heading_hits = find_markers_in_headings(article)
    if heading_hits:
        raise SourcesCitedError(
            "marker_in_heading",
            f"Markers found in heading at order(s): {[h[0] for h in heading_hits]}",
        )

    body_marker_ids = all_marker_ids_in_body(article)
    for cid in body_marker_ids:
        if not is_valid_citation_id(cid):
            raise SourcesCitedError(
                "invalid_citation_id",
                f"citation_id '{cid}' does not match ^cit_[0-9]+$",
            )

    # Marker resolvability: every body marker SHOULD exist in research.citations.
    # Historically we aborted with HTTP 422 when an unresolvable marker showed
    # up; that was too strict - a Writer that hallucinates IDs (e.g. cit_001..
    # cit_009 mimicking the prompt example) now blocks every Resume of the
    # affected run. Strip unknown markers in place, log loudly, and proceed.
    unresolvable_markers_stripped: list[str] = sorted(
        body_marker_ids - set(citations_by_id.keys())
    )
    if unresolvable_markers_stripped:
        logger.warning(
            "sources_cited.unresolvable_markers_stripped",
            extra={
                "stripped_ids": unresolvable_markers_stripped,
                "stripped_count": len(unresolvable_markers_stripped),
                "valid_id_count": len(citations_by_id),
            },
        )
        _strip_marker_ids_from_article(article, set(unresolvable_markers_stripped))
        body_marker_ids = all_marker_ids_in_body(article)

    # Integrity check: every body marker SHOULD appear in writer's citation_usage.
    # Same reasoning - log + proceed rather than abort. The marker references a
    # real citation; the writer just didn't record it in citation_usage.
    usage_ids = _all_citation_ids_in_usage(writer)
    integrity_violations = sorted(body_marker_ids - usage_ids)
    if integrity_violations:
        logger.warning(
            "sources_cited.writer_integrity_violation",
            extra={
                "missing_from_usage": integrity_violations,
                "violation_count": len(integrity_violations),
            },
        )

    # Step 1: discover + number citations by first appearance
    number_map, ordered_used = scan_markers(article)

    # Orphaned usage records (used:true but no marker in prose)
    used_in_writer = _used_citation_ids_from_writer(writer)
    orphans = sorted(used_in_writer - set(number_map.keys()))

    # Step 2: superscript injection
    inject_into_article(article, number_map)

    # Per-section reconciliation warnings
    warnings = _section_marker_reconciliation_warnings(article)

    # Step 3 + 4: build entries + section pair
    conclusion_order = _conclusion_order(article)
    new_sections, flags = build_sources_cited_sections(
        ordered_used_citations=ordered_used,
        citations_by_id=citations_by_id,
        conclusion_order=conclusion_order,
    )
    article.extend(new_sections)

    # Step 5: assemble enriched output
    enriched = copy.deepcopy(writer)
    enriched["article"] = article

    # Pass through metadata; note the sources_cited module version
    enriched_metadata = dict(enriched.get("metadata") or {})
    enriched_metadata["sources_cited_module_version"] = "1.1"
    enriched["metadata"] = enriched_metadata

    sc_metadata = SourcesCitedMetadata(
        total_citations_in_sources_cited=len(ordered_used),
        citation_number_map=number_map,
        orphaned_usage_records=orphans,
        marker_reconciliation_warnings=warnings,
        entries_with_missing_publication=flags.get("entries_with_missing_publication", []),
        entries_with_placeholder=flags.get("entries_with_placeholder", []),
        unresolvable_markers_stripped=unresolvable_markers_stripped,
        integrity_violations=integrity_violations,
        writer_schema_version=(writer.get("metadata") or {}).get("schema_version", "1.7"),
        generation_time_ms=int((time.perf_counter() - started) * 1000),
    )
    enriched["sources_cited_metadata"] = sc_metadata.model_dump(mode="json")

    return SourcesCitedResponse(
        enriched_article=enriched,
        sources_cited_metadata=sc_metadata,
    )
