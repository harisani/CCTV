from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def secure_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "cors_allowed_origins": "https://security.example.test",
        "postgres_password": "postgres-production-password-2026",
        "jwt_secret": "jwt-signing-secret-with-at-least-32-characters",
        "api_admin_password": "admin-production-password-2026",
        "evidence_signing_secret": "evidence-signing-secret-with-at-least-32-characters",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("debug", True),
        ("jwt_secret", "replace_with_a_long_random_secret"),
        ("evidence_signing_secret", "short"),
        ("postgres_password", "cctv_user"),
        ("api_admin_password", "change-this-admin-password"),
        ("cors_allowed_origins", "*"),
        ("jwt_algorithm", "none"),
    ],
)
def test_production_rejects_unsafe_configuration(field: str, value: object) -> None:
    values = secure_values()
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)


def test_production_accepts_explicit_secure_configuration() -> None:
    settings = Settings(**secure_values())

    assert settings.app_env == "production"
    assert settings.jwt_algorithm == "HS256"
    assert settings.evidence_access_token_expire_seconds == 60


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Development ", "development"),
        ("TEST", "test"),
        (" Production ", "production"),
    ],
)
def test_application_environment_is_normalized(value: str, expected: str) -> None:
    values = secure_values()
    values["app_env"] = value

    assert Settings(**values).app_env == expected


@pytest.mark.parametrize("value", ["prod", "staging", "produciton", ""])
def test_application_environment_rejects_unknown_values(value: str) -> None:
    values = secure_values()
    values["app_env"] = value

    with pytest.raises(ValidationError):
        Settings(**values)


def test_production_rejects_shared_jwt_and_evidence_signing_secret() -> None:
    values = secure_values()
    values["evidence_signing_secret"] = values["jwt_secret"]

    with pytest.raises(ValidationError, match="must differ"):
        Settings(**values)


@pytest.mark.parametrize("seconds", [9, 301])
def test_evidence_access_expiry_is_bounded(seconds: int) -> None:
    values = secure_values()
    values["evidence_access_token_expire_seconds"] = seconds
    with pytest.raises(ValidationError):
        Settings(**values)


def test_ai_worker_heartbeat_must_be_shorter_than_lease() -> None:
    values = secure_values()
    values["ai_job_lease_seconds"] = 10
    values["ai_job_heartbeat_seconds"] = 10

    with pytest.raises(ValidationError, match="must be lower"):
        Settings(**values)


def test_ai_retry_base_delay_must_not_exceed_maximum() -> None:
    values = secure_values()
    values["ai_retry_base_delay_seconds"] = 20
    values["ai_retry_max_delay_seconds"] = 10

    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(**values)
