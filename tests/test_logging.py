from __future__ import annotations

import json
import logging
from io import StringIO

from app.api.request_context import bind_correlation_id, reset_correlation_id
from app.utils.logging import JsonFormatter, configure_logging, redact_sensitive


def test_redaction_removes_supported_credentials() -> None:
    value = (
        "Authorization: Bearer secret-token "
        "rtsp://camera-user:camera-pass@10.0.0.2/live "
        "password=plain-value"
    )
    redacted = redact_sensitive(value)
    assert "secret-token" not in redacted
    assert "camera-pass" not in redacted
    assert "plain-value" not in redacted
    assert "[REDACTED]" in redacted


def test_redaction_removes_sensitive_urls_and_evidence_paths() -> None:
    value = (
        "rtsp://camera-user:camera-pass@10.0.0.2/live "
        "https://cctv.example/api/events?token=request-token "
        "/var/lib/cctv/storage/2026/07/24/snapshot.jpg "
        "storage/2026/07/24/snapshot.json"
    )

    redacted = redact_sensitive(value)

    assert "camera-user" not in redacted
    assert "camera-pass" not in redacted
    assert "10.0.0.2" not in redacted
    assert "cctv.example" not in redacted
    assert "request-token" not in redacted
    assert "snapshot.jpg" not in redacted
    assert "snapshot.json" not in redacted


def test_redaction_removes_snake_case_credentials() -> None:
    value = (
        "access_token=access-token "
        "postgres_password=postgres-password "
        "jwt_secret=jwt-secret"
    )

    redacted = redact_sensitive(value)

    assert "access-token" not in redacted
    assert "postgres-password" not in redacted
    assert "jwt-secret" not in redacted


def test_redaction_removes_custom_evidence_paths() -> None:
    value = (
        "Snapshot saved for ENTER: /private/cameras/2026/07/24/saved.jpg "
        "Snapshot file missing or outside storage root: camera-data/2026/07/24/missing.jpg"
    )

    redacted = redact_sensitive(value)

    assert "saved.jpg" not in redacted
    assert "missing.jpg" not in redacted


def test_json_formatter_adds_context_and_http_fields() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("phase1-json-test")
    original_handlers = logger.handlers[:]
    original_propagate = logger.propagate
    original_level = logger.level
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    token = bind_correlation_id("request-json-1")
    try:
        logger.info(
            "request complete",
            extra={"http_method": "GET", "http_path": "/health", "http_status": 200},
        )
    finally:
        reset_correlation_id(token)
        logger.handlers = original_handlers
        logger.propagate = original_propagate
        logger.setLevel(original_level)

    payload = json.loads(stream.getvalue())
    assert payload["message"] == "request complete"
    assert payload["correlation_id"] == "request-json-1"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/health"
    assert payload["http_status"] == 200


def test_text_logging_redacts_sensitive_message_content(capsys) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    original_access_level = access_logger.level
    try:
        configure_logging("INFO", "development", "auto")
        logging.getLogger("phase1-text-test").error(
            "Authorization: Bearer secret-token "
            "rtsp://camera-user:camera-pass@10.0.0.2/live "
            "snapshot=/var/lib/cctv/storage/snapshot.jpg"
        )
        output = capsys.readouterr().err
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        access_logger.setLevel(original_access_level)

    assert "secret-token" not in output
    assert "camera-user" not in output
    assert "camera-pass" not in output
    assert "10.0.0.2" not in output
    assert "snapshot.jpg" not in output
    assert "[REDACTED]" in output
