"""Shared exception types for the Brief Generator pipeline.

Lives in its own module so individual step modules (title_scope, etc.)
can raise BriefError without taking a circular dependency on pipeline.py.
"""

from __future__ import annotations


class BriefError(Exception):
    """Raised when the pipeline cannot produce a valid brief.

    `code` is a stable string identifier (e.g. "title_generation_failed",
    "serp_no_results") that callers and tests pin against. `message` is
    the human-readable detail.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
