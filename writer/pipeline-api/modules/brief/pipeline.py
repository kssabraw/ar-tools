"""Brief Generator pipeline orchestrator — v2.0 transitional stub.

This file is a placeholder during the v2.0 staged rollout. The full
v2.0 orchestrator is built in Stage 9 of the implementation plan; until
then `run_brief` raises a 503-equivalent error and the legacy v1.8
modules in this directory (clustering.py, silos.py, scoring.py, etc.)
are orphaned reference code awaiting rewrite in Stages 2–8.

DO NOT add v1.8 imports here — the v1.8 schema has been replaced by
v2.0 in models/brief.py.
"""

from __future__ import annotations

from models.brief import BriefRequest, BriefResponse


class BriefError(Exception):
    """Raised when the pipeline cannot produce a valid brief."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def run_brief(req: BriefRequest) -> BriefResponse:
    raise BriefError(
        "v2_pipeline_not_implemented",
        "Brief Generator v2.0 pipeline is being rolled out in stages; "
        "this endpoint is temporarily unavailable. See "
        "docs/modules/content-brief-generator-prd-v2_0.md.",
    )
