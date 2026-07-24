from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
import re
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


def test_redaction_removes_standalone_bearer_and_whitespace_values() -> None:
    value = (
        "upstream sent Bearer standalone-secret "
        "password whitespace-secret "
        "embedding [0.11, -0.22] "
        "ReID result array([0.33, -0.44]) "
        "embeddings [[0.51]] vectors=(-0.61,) "
        "reid_embedding: [0.71] face_embedding=[0.81] "
        "periocular_embedding array([0.91]) "
        "samples [1, 2]"
    )

    redacted = redact_sensitive(value)

    for sensitive_value in (
        "standalone-secret",
        "whitespace-secret",
        "0.11",
        "-0.22",
        "0.33",
        "-0.44",
        "0.51",
        "-0.61",
        "0.71",
        "0.81",
        "0.91",
    ):
        assert sensitive_value not in redacted
    assert "[1, 2]" in redacted


def test_redaction_preserves_exact_key_lookalikes() -> None:
    value = (
        "tokenizer: wordpiece passwordless=enabled "
        "vector_count: [1, 2] secretary='Alice' "
        "diagnostic=https://cctv.example/health?"
        "tokenizer=wordpiece&passwordless=enabled&vector_count=2&secretary=Alice"
    )

    assert redact_sensitive(value) == value


def test_redaction_removes_project_specific_sensitive_suffixes() -> None:
    value = (
        "payload={'api_admin_password': 'admin-value', "
        "'dr_encryption_passphrase': 'recovery-value', "
        "'evidence_signing_secret': 'signing-value', "
        "'evidence_access_token': 'access-value'} "
        "api admin password: spaced-admin-value "
        "backup credential=backup-value "
        "model embedding: [0.101, -0.202] "
        "tracking_vector: (0.303, -0.404) "
        "callback=https://cctv.example/callback?"
        "view=summary&evidence_access_token=query-value "
        "admin=https://cctv.example/admin?api_key=api-key-value"
    )

    redacted = redact_sensitive(value)

    for sensitive_value in (
        "admin-value",
        "recovery-value",
        "signing-value",
        "access-value",
        "spaced-admin-value",
        "backup-value",
        "0.101",
        "-0.202",
        "0.303",
        "-0.404",
        "query-value",
        "api-key-value",
    ):
        assert sensitive_value not in redacted
    assert "cctv.example" not in redacted


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
        "'access token': 'normalized-secret', "
        "'face_embedding': [[0.12, -0.08], [0.14, -0.16]], "
        "'biometric_vector': array([0.21, -0.23]), "
        "vector: (0.31, -0.33), 'safe': [1, 2]}"
    )

    redacted = redact_sensitive(value)

    assert "repr-secret" not in redacted
    assert "json-token" not in redacted
    assert "normalized-secret" not in redacted
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
            "configuration": {
                "api_admin_password": "admin-config",
                "dr_encryption_passphrase": "recovery-config",
                "evidence_signing_secret": "signing-config",
                "evidence_access_token": "access-config",
            },
            "metrics": {"samples": [1, 2, 3]},
            "diagnostics": {
                "tokenizer": "osnet",
                "passwordless": True,
                "vector_count": [4, 5],
                "secretary": "Alice",
            },
        }
        try:
            raise RuntimeError(
                "worker failed: Bearer exception-bearer "
                "ReID result array([0.7, -0.8]) "
                "evidence_signing_secret: exception-signing"
            )
        except RuntimeError:
            logging.getLogger("phase1-json-redaction-test").exception(
                "password %s embedding %s details=%s",
                "message-secret",
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
        "exception-bearer",
        "message-secret",
        "admin-config",
        "recovery-config",
        "signing-config",
        "access-config",
        "exception-signing",
        "0.12",
        "-0.08",
        "0.31",
        "-0.42",
        "0.7",
        "-0.8",
    ):
        assert sensitive_value not in rendered
    assert "[1, 2, 3]" in rendered
    assert "[4, 5]" in rendered
    for safe_value in ("osnet", "passwordless", "vector_count", "secretary", "Alice"):
        assert safe_value in rendered
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
            "configuration": {
                "api_admin_password": "admin-config",
                "dr_encryption_passphrase": "recovery-config",
                "evidence_signing_secret": "signing-config",
                "evidence_access_token": "access-config",
            },
            "metrics": {"samples": [1, 2, 3]},
            "diagnostics": {
                "tokenizer": "osnet",
                "passwordless": True,
                "vector_count": [4, 5],
                "secretary": "Alice",
            },
        }
        try:
            raise RuntimeError(
                "worker failed: Bearer exception-bearer "
                "ReID result array([0.7, -0.8]) "
                "evidence_signing_secret: exception-signing"
            )
        except RuntimeError:
            logging.getLogger("phase1-text-redaction-test").exception(
                "password %s embedding %s details=%s",
                "message-secret",
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
        "exception-bearer",
        "message-secret",
        "admin-config",
        "recovery-config",
        "signing-config",
        "access-config",
        "exception-signing",
        "0.12",
        "-0.08",
        "0.31",
        "-0.42",
        "0.7",
        "-0.8",
    ):
        assert sensitive_value not in output
    assert "[1, 2, 3]" in output
    assert "[4, 5]" in output
    for safe_value in ("osnet", "passwordless", "vector_count", "secretary", "Alice"):
        assert safe_value in output
    assert "[REDACTED]" in output


def test_app_logging_calls_do_not_pass_unlabeled_raw_embeddings() -> None:
    sensitive_context = re.compile(
        r"(?i)(?<![a-z0-9_])(?:embedding|embeddings|vector|vectors|"
        r"reid_embedding|face_embedding|periocular_embedding)(?![a-z0-9_])|"
        r"\breid\s+result\b"
    )
    violations: list[str] = []

    def is_raw_embedding_name(name: str) -> bool:
        normalized = name.casefold()
        return any(
            normalized == suffix or normalized.endswith(f"_{suffix}")
            for suffix in ("embedding", "embeddings", "vector", "vectors")
        )

    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr
                not in {"debug", "info", "warning", "error", "exception", "critical"}
            ):
                continue
            logged_values = [*node.args, *(keyword.value for keyword in node.keywords)]
            argument_names = {
                child.id if isinstance(child, ast.Name) else child.attr
                for argument in logged_values
                for child in ast.walk(argument)
                if isinstance(child, (ast.Name, ast.Attribute))
            }
            if not any(is_raw_embedding_name(name) for name in argument_names):
                continue
            if not node.args:
                violations.append(f"{path}:{node.lineno}")
                continue
            if isinstance(node.args[0], ast.Constant):
                template = node.args[0].value
            elif isinstance(node.args[0], ast.JoinedStr):
                template = "".join(
                    item.value
                    for item in node.args[0].values
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
            else:
                template = ""
            if not isinstance(template, str) or sensitive_context.search(template) is None:
                violations.append(f"{path}:{node.lineno}")

    assert violations == []


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
