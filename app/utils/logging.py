from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.api.request_context import get_correlation_id

_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_URL = re.compile(
    r"(?i)\b(?:https?|rtsp|postgresql(?:\+asyncpg)?):\/\/[^\s,;]+"
)
_ASSIGNMENT = re.compile(
    r"(?i)(?<![A-Za-z0-9])(password|passwd|token|secret|passphrase)=([^&\s,;]+)"
)
_EVIDENCE_PATH = re.compile(
    r"(?i)(?<![\w/])(?:(?:[a-z]:[\\/]|/)[^\s,;]*(?:storage|evidence|snapshot)[^\s,;]*|"
    r"(?:\./|\.\./)?(?:storage|evidence|snapshots?)/[^\s,;]+)"
)
_EVIDENCE_VALUE = re.compile(
    r"(?i)(\b(?:snapshot|evidence)(?:\s+\w+){0,6}\s*:\s*)[^\s,;]+"
)
_EXTRA_FIELDS = (
    "http_method",
    "http_path",
    "http_status",
    "duration_ms",
    "user_id",
    "exception_type",
)


def redact_sensitive(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _URL.sub("[REDACTED]", value)
    value = _ASSIGNMENT.sub(r"\1=[REDACTED]", value)
    value = _EVIDENCE_VALUE.sub(r"\1[REDACTED]", value)
    return _EVIDENCE_PATH.sub("[REDACTED]", value)


class CorrelationContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None)
            or get_correlation_id(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = redact_sensitive(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact_sensitive(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, default=str)


class _RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive(super().format(record))


def configure_logging(level: str, environment: str, format_mode: str) -> None:
    selected = "json" if format_mode == "auto" and environment == "production" else format_mode
    if selected == "auto":
        selected = "text"
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationContextFilter())
    handler.setFormatter(
        JsonFormatter()
        if selected == "json"
        else _RedactingTextFormatter(
            "%(asctime)s | %(levelname)s | %(name)s | "
            "%(correlation_id)s | %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
