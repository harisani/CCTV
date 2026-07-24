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


def test_redaction_removes_colon_delimited_sensitive_values() -> None:
    value = (
        "payload={'postgres_password': 'repr-secret', \"access_token\": \"json-token\", "
        "'face_embedding': [[0.12, -0.08], [0.14, -0.16]], "
        "'biometric_vector': array([0.21, -0.23]), "
        "vector: (0.31, -0.33), 'safe': [1, 2]}"
    )

    redacted = redact_sensitive(value)

    assert "repr-secret" not in redacted
    assert "json-token" not in redacted
    for sensitive_value in (
        "0.12",
        "-0.08",
        "0.14",
        "-0.16",
        "0.21",
        "-0.23",
        "0.31",
        "-0.33",
    ):
        assert sensitive_value not in redacted
    assert "[1, 2]" in redacted


def test_redaction_preserves_safe_diagnostic_url_and_numeric_list() -> None:
    value = "diagnostic=https://cctv.example/health?view=summary metrics=[1, 2, 3]"

    assert redact_sensitive(value) == value


def test_redaction_removes_sensitive_urls_but_preserves_safe_diagnostic_urls() -> None:
    value = (
        "stream=https://camera-user:camera-pass@cctv.example/live "
        "callback=https://cctv.example/events?view=summary&access_token=request-token "
        "diagnostic=https://cctv.example/health?view=summary"
    )

    redacted = redact_sensitive(value)

    assert "camera-user" not in redacted
    assert "camera-pass" not in redacted
    assert "request-token" not in redacted
    assert "https://cctv.example/health?view=summary" in redacted


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


def test_configured_json_logging_redacts_nested_exception_vectors(capsys) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    original_access_level = access_logger.level
    try:
        configure_logging("INFO", "production", "auto")
        try:
            raise RuntimeError(
                "upstream returned "
                "{'biometric_vector': array([0.71, -0.82]), 'samples': [4, 5]}"
            )
        except RuntimeError:
            logging.getLogger("phase1-json-nested-exception-test").exception(
                "request failed with details=%r",
                {"face_embedding": [[0.11, -0.12], [0.13, -0.14]], "samples": [1, 2, 3]},
            )
        output = capsys.readouterr().err
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        access_logger.setLevel(original_access_level)

    payload = json.loads(output)
    rendered = json.dumps(payload)
    for sensitive_value in ("0.11", "-0.12", "0.13", "-0.14", "0.71", "-0.82"):
        assert sensitive_value not in rendered
    assert "[1, 2, 3]" in rendered
    assert "[4, 5]" in rendered


def test_configured_text_logging_redacts_nested_exception_vectors(capsys) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    original_access_level = access_logger.level
    try:
        configure_logging("INFO", "development", "auto")
        try:
            raise RuntimeError(
                "upstream returned "
                "{'biometric_vector': array([0.71, -0.82]), 'samples': [4, 5]}"
            )
        except RuntimeError:
            logging.getLogger("phase1-text-nested-exception-test").exception(
                "request failed with details=%r",
                {"face_embedding": [[0.11, -0.12], [0.13, -0.14]], "samples": [1, 2, 3]},
            )
        output = capsys.readouterr().err
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        access_logger.setLevel(original_access_level)

    for sensitive_value in ("0.11", "-0.12", "0.13", "-0.14", "0.71", "-0.82"):
        assert sensitive_value not in output
    assert "[1, 2, 3]" in output
    assert "[4, 5]" in output


def test_configured_json_logging_redacts_nested_sensitive_values(capsys) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    original_access_level = access_logger.level
    try:
        configure_logging("INFO", "production", "auto")
        details = {
            "identity": {
                "postgres_password": "nested-secret",
                "reid_embedding": [0.12, -0.08],
            },
            "metrics": {"samples": [1, 2, 3]},
        }
        try:
            raise RuntimeError(
                "worker failed: {'jwt_secret': 'exception-secret', 'vector': [0.7, -0.8]}"
            )
        except RuntimeError:
            logging.getLogger("phase1-json-redaction-test").exception(
                "embedding=%s details=%s",
                [0.31, -0.42],
                details,
            )
        output = capsys.readouterr().err
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        access_logger.setLevel(original_access_level)

    payload = json.loads(output)
    rendered = json.dumps(payload)
    for sensitive_value in (
        "nested-secret",
        "exception-secret",
        "0.12",
        "-0.08",
        "0.31",
        "-0.42",
        "0.7",
        "-0.8",
    ):
        assert sensitive_value not in rendered
    assert "[1, 2, 3]" in rendered
    assert "[REDACTED]" in rendered


def test_configured_text_logging_redacts_nested_sensitive_values(capsys) -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    access_logger = logging.getLogger("uvicorn.access")
    original_access_level = access_logger.level
    try:
        configure_logging("INFO", "development", "auto")
        details = {
            "identity": {
                "postgres_password": "nested-secret",
                "reid_embedding": [0.12, -0.08],
            },
            "metrics": {"samples": [1, 2, 3]},
        }
        try:
            raise RuntimeError(
                "worker failed: {'jwt_secret': 'exception-secret', 'vector': [0.7, -0.8]}"
            )
        except RuntimeError:
            logging.getLogger("phase1-text-redaction-test").exception(
                "embedding=%s details=%s",
                [0.31, -0.42],
                details,
            )
        output = capsys.readouterr().err
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)
        access_logger.setLevel(original_access_level)

    for sensitive_value in (
        "nested-secret",
        "exception-secret",
        "0.12",
        "-0.08",
        "0.31",
        "-0.42",
        "0.7",
        "-0.8",
    ):
        assert sensitive_value not in output
    assert "[1, 2, 3]" in output
    assert "[REDACTED]" in output


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
