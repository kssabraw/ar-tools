"""Error types for the Service Page Writer."""

from __future__ import annotations


class ServiceWriterError(Exception):
    """Raised on a non-recoverable failure in the service-writer pipeline."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
