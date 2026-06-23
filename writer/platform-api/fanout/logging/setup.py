"""Structured JSON logging to stderr (Railway captures stderr).

Implements the log shape from PRD §16.3: every entry carries a `correlation_id`
and (when inside a pipeline run) a `session_id`, so logs can be traced per
session. Pipeline-specific fields (`step`, `cost_usd`, `external_calls`, ...)
are passed per call via `logger.info(..., extra={...})` once the pipeline lands
in later milestones; the boilerplate is established here from day one.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from pythonjsonlogger import jsonlogger

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)

# Reserved keys that should never leak secrets into logs (PRD "Never" rules).
_REDACT_KEYS = {"authorization", "api_key", "apikey", "service_role_key", "password", "token"}


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def bind_correlation_id(correlation_id: str) -> None:
    _correlation_id.set(correlation_id)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def bind_session_id(session_id: str | None) -> None:
    _session_id.set(session_id)


def get_session_id() -> str | None:
    return _session_id.get()


class _ContextFilter(logging.Filter):
    """Inject correlation/session ids onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get()
        record.session_id = _session_id.get()
        return True


class _Formatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        log_record["level"] = record.levelname
        log_record.setdefault("correlation_id", getattr(record, "correlation_id", None))
        log_record.setdefault("session_id", getattr(record, "session_id", None))
        for key in list(log_record.keys()):
            if key.lower() in _REDACT_KEYS:
                log_record[key] = "***redacted***"


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_Formatter("%(level)s %(message)s"))
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Route uvicorn through our handler so access/error logs share the shape.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
