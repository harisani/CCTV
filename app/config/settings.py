from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration loaded exclusively from environment variables/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CCTV People Flow"
    app_env: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:5173"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "cctv"
    postgres_user: str = "cctv_user"
    postgres_password: str = Field(repr=False)
    database_pool_size: int = Field(default=5, gt=0)
    database_max_overflow: int = Field(default=10, ge=0)

    storage_path: Path = Path("storage")
    snapshot_jpeg_quality: int = Field(default=95, ge=1, le=100)
    rtsp_url: str = ""
    yolo_model: str = "yolo11n.pt"
    confidence_threshold: float = Field(default=0.45, ge=0, le=1)
    yolo_device: str = "auto"
    yolo_image_size: int = Field(default=640, gt=0)
    yolo_max_detections: int = Field(default=100, gt=0)
    yolo_half_precision: bool = True

    bytetrack_frame_rate: int = Field(default=10, gt=0)
    bytetrack_track_high_threshold: float = Field(default=0.5, ge=0, le=1)
    bytetrack_track_low_threshold: float = Field(default=0.1, ge=0, le=1)
    bytetrack_new_track_threshold: float = Field(default=0.6, ge=0, le=1)
    bytetrack_match_threshold: float = Field(default=0.8, ge=0, le=1)
    bytetrack_track_buffer: int = Field(default=30, gt=0)
    bytetrack_history_size: int = Field(default=30, gt=1)
    bytetrack_direction_min_pixels: float = Field(default=3.0, ge=0)
    bytetrack_max_inactive_frames: int = Field(default=300, gt=0)

    crossing_line_id: str = "main-door"
    crossing_line_type: Literal["horizontal", "vertical", "polygon"] = "horizontal"
    crossing_line_position: float = 360.0
    crossing_enter_direction: Literal["up", "down", "left", "right"] = "down"
    crossing_polygon_points: str = ""
    crossing_max_inactive_frames: int = Field(default=300, gt=0)
    crossing_hysteresis_ratio: float = Field(default=0.01, ge=0, le=0.25)
    crossing_event_cooldown_frames: int = Field(default=3, ge=0)

    reid_model: str = "osnet_x1_0"
    reid_device: str = "auto"
    reid_image_width: int = Field(default=128, gt=0)
    reid_image_height: int = Field(default=256, gt=0)
    reid_embedding_dimension: int = Field(default=512, gt=0)
    reid_similarity_threshold: float = Field(default=0.78, ge=0, le=1)
    reid_match_margin: float = Field(default=0.05, ge=0, le=1)
    reid_candidate_limit: int = Field(default=50, gt=1, le=1000)
    reid_min_quality_score: float = Field(default=0.45, ge=0, le=1)
    reid_sharpness_reference: float = Field(default=150.0, gt=0)
    reid_embedding_retention_days: int = Field(default=90, gt=0)
    reid_min_embeddings_per_person: int = Field(default=3, gt=0)
    reid_max_embeddings_per_person: int = Field(default=20, gt=0)
    reid_retention_interval_hours: int = Field(default=24, gt=0)
    enable_reid_retention: bool = True

    jwt_secret: str = Field(repr=False)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, gt=0)
    evidence_signing_secret: str = Field(
        default="development-only-evidence-key-change-this-before-production",
        repr=False,
    )
    evidence_access_token_expire_seconds: int = Field(default=60, ge=10, le=300)
    api_admin_username: str = "admin"
    api_admin_password: str = Field(repr=False)
    login_max_failed_attempts: int = Field(default=5, gt=0)
    login_lock_minutes: int = Field(default=15, gt=0)

    presence_timezone: str = "Asia/Jakarta"
    presence_reconcile_interval_seconds: float = Field(default=30.0, ge=5)

    enable_backup_scheduler: bool = True
    backup_schedule_time: str = Field(
        default="00:15", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    backup_timezone: str = "Asia/Jakarta"
    backup_retention_days: int = Field(default=30, gt=0)
    backup_include_snapshots: bool = True
    backup_max_upload_mb: int = Field(default=2048, gt=0)
    backup_max_members: int = Field(default=100_000, gt=0)
    backup_max_expansion_ratio: int = Field(default=100, ge=1)

    # Full disaster recovery: encrypted PostgreSQL dump + storage files.
    enable_dr_scheduler: bool = False
    dr_schedule_time: str = Field(
        default="02:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    dr_retention_days: int = Field(default=14, gt=0)
    dr_encryption_passphrase: str = Field(default="", repr=False)
    dr_include_storage: bool = True
    dr_offsite_path: str = ""
    dr_offsite_required: bool = False
    dr_restore_database_suffix: str = Field(
        default="_restore", pattern=r"^_[a-zA-Z0-9_]+$"
    )
    dr_allow_in_place_restore: bool = False
    dr_command_timeout_seconds: int = Field(default=3600, gt=0)

    camera_read_fps: float = Field(default=10.0, gt=0, le=120)
    camera_frame_width: int = Field(default=1280, gt=0)
    camera_frame_height: int = Field(default=720, gt=0)
    camera_reconnect_delay_seconds: float = Field(default=3.0, gt=0)
    camera_stale_timeout_seconds: float = Field(default=5.0, gt=0)
    camera_sync_interval_seconds: float = Field(default=5.0, gt=0)
    dashboard_stream_fps: float = Field(default=2.0, gt=0, le=10)
    dashboard_jpeg_quality: int = Field(default=70, ge=30, le=95)
    camera_health_update_seconds: float = Field(default=30.0, gt=0)
    enable_camera_runtime: bool = True
    enable_ai_pipeline: bool = True
    ai_pipeline_fps: float = Field(default=5.0, gt=0, le=60)
    ai_max_concurrent_inferences: int = Field(default=1, gt=0, le=16)
    ai_person_class_id: int = Field(default=0, ge=0)
    ai_tracking_persist_interval_seconds: float = Field(default=1.0, gt=0)
    ai_track_inactive_frames: int = Field(default=60, gt=0)
    ai_event_retry_queue_size: int = Field(default=1000, gt=0)
    reid_min_crop_width: int = Field(default=32, gt=0)
    reid_min_crop_height: int = Field(default=64, gt=0)
    torch_num_threads: int = Field(default=0, ge=0)
    opencv_num_threads: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.app_env.strip().lower() != "production":
            return self

        errors: list[str] = []
        weak_markers = ("replace", "change-this", "cctv_user", "changeme", "example")

        def weak(value: str, *, minimum: int) -> bool:
            normalized = value.strip().lower()
            return len(value.strip()) < minimum or any(
                marker in normalized for marker in weak_markers
            )

        if self.debug:
            errors.append("DEBUG must be false in production")
        if self.jwt_algorithm != "HS256":
            errors.append("JWT_ALGORITHM must be HS256")
        if weak(self.jwt_secret, minimum=32):
            errors.append("JWT_SECRET must be a non-placeholder value of at least 32 characters")
        if weak(self.evidence_signing_secret, minimum=32):
            errors.append(
                "EVIDENCE_SIGNING_SECRET must be a non-placeholder value of at least 32 characters"
            )
        if weak(self.postgres_password, minimum=16):
            errors.append(
                "POSTGRES_PASSWORD must be a non-placeholder value of at least 16 characters"
            )
        if weak(self.api_admin_password, minimum=16):
            errors.append(
                "API_ADMIN_PASSWORD must be a non-placeholder value of at least 16 characters"
            )
        if "*" in self.cors_origins:
            errors.append("CORS_ALLOWED_ORIGINS must not contain * in production")
        if self.enable_dr_scheduler and len(self.dr_encryption_passphrase) < 16:
            errors.append(
                "DR_ENCRYPTION_PASSPHRASE must contain at least 16 characters when DR is enabled"
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def cors_origins(self) -> list[str]:
        """Return configured browser origins as a list."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @computed_field
    @property
    def database_url(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
