"""Pydantic models for the Sources Cited module — schema v1.1.

Per docs/modules/sources-cited-module-prd-v1_1.md.
The output extends the Writer v1.5 schema with marker-substituted bodies,
two appended sections (sources-cited-header + sources-cited-body), and a
sources_cited_metadata block.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SourcesCitedRequest(BaseModel):
    run_id: str
    attempt: int = 1
    writer_output: dict[str, Any]
    research_output: dict[str, Any]


class SourcesCitedMetadata(BaseModel):
    total_citations_in_sources_cited: int = 0
    citation_number_map: dict[str, int] = {}
    orphaned_usage_records: list[str] = []
    marker_reconciliation_warnings: list[str] = []
    entries_with_missing_publication: list[str] = []
    entries_with_placeholder: list[str] = []
    unresolvable_markers_stripped: list[str] = []
    integrity_violations: list[str] = []
    schema_version: Literal["1.1"] = "1.1"
    writer_schema_version: str = "1.7"
    generation_time_ms: int = 0


class SourcesCitedResponse(BaseModel):
    """Final article with citations rendered.

    The full enriched JSON is the upstream Writer payload with mutations
    applied. We expose it as a dict (`enriched_article`) plus the typed
    metadata block separately so callers can introspect either.
    """

    enriched_article: dict[str, Any]
    sources_cited_metadata: SourcesCitedMetadata
