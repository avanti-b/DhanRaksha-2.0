"""
Configuration for DhanRaksha.

Every value is read from the environment with a safe local default, so the same
image runs locally today and against Azure-managed settings later (Milestone 2)
without code changes. Nothing secret is ever committed - see .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(env_key: str, default_relative: str) -> str:
    value = os.environ.get(env_key)
    if value:
        return value if os.path.isabs(value) else os.path.join(BASE_DIR, value)
    return os.path.join(BASE_DIR, default_relative)


def _float(env_key: str, default: float) -> float:
    try:
        return float(os.environ.get(env_key, default))
    except (TypeError, ValueError):
        return default


def _bool(env_key: str, default: bool = False) -> bool:
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    """Application configuration resolved at startup."""

    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: _bool("FLASK_DEBUG", False))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", 5000)))
    secret_key: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "dev-only-not-a-secret")
    )

    # --- storage -----------------------------------------------------------
    # DATABASE_URL keeps the shape of a connection string so the repository
    # layer can later point at Cosmos DB without touching the services.
    database_path: str = field(
        default_factory=lambda: _path("DATABASE_PATH", "data/dhanraksha.db")
    )

    # --- ML artifacts ------------------------------------------------------
    artifact_dir: str = field(
        default_factory=lambda: _path("ARTIFACT_DIR", "ml/artifacts")
    )
    dataset_path: str = field(
        default_factory=lambda: _path("DATASET_PATH", "data/creditcard.csv")
    )

    # --- decision thresholds ----------------------------------------------
    # 0.5 is a default, not a truth. See docs/ml-pipeline.md threshold analysis.
    fraud_threshold: float = field(
        default_factory=lambda: _float("FRAUD_THRESHOLD", 0.5)
    )
    risk_high_threshold: float = field(
        default_factory=lambda: _float("RISK_HIGH_THRESHOLD", 0.70)
    )
    risk_medium_threshold: float = field(
        default_factory=lambda: _float("RISK_MEDIUM_THRESHOLD", 0.40)
    )

    # --- case management ---------------------------------------------------
    auto_create_cases: bool = field(
        default_factory=lambda: _bool("AUTO_CREATE_CASES", True)
    )

    # --- api ---------------------------------------------------------------
    cors_origins: str = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "*")
    )
    max_page_size: int = field(
        default_factory=lambda: int(os.environ.get("MAX_PAGE_SIZE", 200))
    )

    @property
    def model_path(self) -> str:
        return os.path.join(self.artifact_dir, "fraud_model.pkl")

    @property
    def pipeline_path(self) -> str:
        return os.path.join(self.artifact_dir, "feature_pipeline.pkl")

    @property
    def metadata_path(self) -> str:
        return os.path.join(self.artifact_dir, "model_metadata.json")

    def as_public_dict(self) -> dict:
        """Configuration safe to expose over the API (no secrets)."""
        return {
            "env": self.env,
            "fraud_threshold": self.fraud_threshold,
            "risk_high_threshold": self.risk_high_threshold,
            "risk_medium_threshold": self.risk_medium_threshold,
            "auto_create_cases": self.auto_create_cases,
        }


def load_config() -> Config:
    return Config()
