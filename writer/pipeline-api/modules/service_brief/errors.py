"""Error types for the Service Page Brief Generator."""

from __future__ import annotations


class ServiceBriefError(Exception):
    """Raised on a non-recoverable failure in the service-brief pipeline.

    Stage 1 (SERP composition) gates the rest of the pipeline: if the SERP
    can't be fetched at all, there is no market truth to build a brief from
    and we surface a 422 to the caller. Per-page competitor failures are NOT
    fatal — they degrade gracefully (PRD §8.5).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
