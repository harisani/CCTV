from __future__ import annotations

from collections.abc import Mapping
from copy import copy
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.api.request_context import get_correlation_id

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "auth_token",
        "authorization",
        "bearer_token",
        "biometric_embedding",
        "biometric_vector",
        "camera_password",
        "client_secret",
        "credential",
        "database_password",
        "db_password",
        "embedding",
        "embeddings",
        "face_embedding",
        "id_token",
        "jwt_secret",
        "jwt_token",
        "passphrase",
        "passwd",
        "password",
        "periocular_embedding",
        "postgres_password",
        "postgresql_password",
        "refresh_token",
        "reid_embedding",
        "secret",
        "secret_key",
        "token",
        "vector",
        "vectors",
    }
)
_SENSITIVE_LABEL_KEY_PATTERN = "(?:" + "|".join(
    re.escape(key).replace("_", r"[\s_-]+")
    for key in sorted(_SENSITIVE_KEYS, key=len, reverse=True)
) + ")"
_SENSITIVE_QUERY_KEY_PATTERN = "(?:" + "|".join(
    re.escape(key).replace("_", "[_-]")
    for key in sorted(_SENSITIVE_KEYS, key=len, reverse=True)
) + ")"
_BEARER = re.compile(r"(?i)(\bbearer\s+)[^\s,;]+")
_CREDENTIAL_URL = re.compile(
    r"(?i)\b(?:https?|rtsp|postgresql(?:\+asyncpg)?):\/\/[^:/@\s]+:[^@\s]+@[^\s,;]+"
)
_SENSITIVE_QUERY_URL = re.compile(
    rf"(?i)\bhttps?:\/\/[^\s,;]*\?(?:[^&\s,;]*&)*"
    rf"{_SENSITIVE_QUERY_KEY_PATTERN}=[^\s,;]+"
)
_SENSITIVE_LABEL = re.compile(
    rf"(?i)(?<![A-Za-z0-9_-])(?P<quote>['\"]?)"
    rf"(?P<key>{_SENSITIVE_LABEL_KEY_PATTERN})(?P=quote)"
    r"(?:\s*[:=]\s*|\s+)"
)
_REID_RESULT_LABEL = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])reid\s+result(?:\s*[:=]\s*|\s+)"
    r"(?=(?:array\s*\(|\[|\(|\{|[-+]?(?:\d+(?:\.\d*)?|\.\d)))"
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


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _quoted_value_end(value: str, start: int, quote: str) -> int:
    escaped = False
    for index in range(start + 1, len(value)):
        character = value[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return index + 1
    return len(value)


def _sensitive_value_end(value: str, start: int) -> int:
    if start >= len(value):
        return start
    if value[start] in {"'", '"'}:
        return _quoted_value_end(value, start, value[start])

    closing_for = {"[": "]", "(": ")", "{": "}"}
    stack: list[str] = []
    index = start
    while index < len(value):
        character = value[index]
        if character in {"'", '"'}:
            index = _quoted_value_end(value, index, character)
            continue
        if character in closing_for:
            stack.append(closing_for[character])
        elif stack and character == stack[-1]:
            stack.pop()
            if not stack:
                return index + 1
        elif not stack and (character.isspace() or character in ",;}]"):
            return index
        index += 1
    return len(value)


def _redact_labeled_values(value: str, label: re.Pattern[str]) -> str:
    parts: list[str] = []
    cursor = 0
    while match := label.search(value, cursor):
        value_end = _sensitive_value_end(value, match.end())
        parts.extend((value[cursor : match.end()], "[REDACTED]"))
        cursor = value_end
    parts.append(value[cursor:])
    return "".join(parts)


def redact_sensitive(value: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _CREDENTIAL_URL.sub("[REDACTED]", value)
    value = _SENSITIVE_QUERY_URL.sub("[REDACTED]", value)
    value = _redact_labeled_values(value, _SENSITIVE_LABEL)
    value = _redact_labeled_values(value, _REID_RESULT_LABEL)
    value = _EVIDENCE_VALUE.sub(r"\1[REDACTED]", value)
    return _EVIDENCE_PATH.sub("[REDACTED]", value)


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _normalize_key(key) in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            item_key: _sanitize_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive(value)
    return value


def _sanitized_record(record: logging.LogRecord) -> logging.LogRecord:
    sanitized = copy(record)
    sanitized.msg = record.msg if isinstance(record.msg, str) else _sanitize_value(record.msg)
    sanitized.args = _sanitize_value(record.args)
    return sanitized


class CorrelationContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sanitized_record = _sanitized_record(record)
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive(sanitized_record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None)
            or get_correlation_id(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = _sanitize_value(value)
        if record.exc_info:
            payload["exception"] = redact_sensitive(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False, default=str)


class _RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive(super().format(_sanitized_record(record)))


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
