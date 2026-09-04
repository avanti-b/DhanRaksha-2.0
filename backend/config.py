"""
Configuration for DhanRaksha.

Every value is read from the environment with a safe local default, so the same
code runs locally on SQLite and on Azure against Cosmos DB with no source
changes. Nothing secret is committed - see .env.example.

Resolution order for any setting (first hit wins):

    1. Azure Key Vault          (only when KEY_VAULT_URL is set)
    2. Environment variable     (locally from .env; on Azure from App Settings)
    3. Built-in default         (local-development friendly)

Key Vault sits first so that on Azure the secret never has to exist as a
literal App Setting. Locally, KEY_VAULT_URL is unset, the lookup is skipped
entirely, and no Azure SDK is imported.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("dhanraksha.config")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Storage backends. STORAGE_BACKEND selects which repository implementation
# build_container() wires up.
BACKEND_SQLITE = "sqlite"
BACKEND_COSMOS = "cosmos"


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


def secret(env_key: str, default: str = "") -> str:
    """
    Read a value that may be a secret.

    When KEY_VAULT_URL is configured, Key Vault is consulted first using the
    env key lowercased with underscores turned into hyphens, which is the only
    naming Key Vault accepts (COSMOS_KEY -> cosmos-key). Falls back to the
    environment variable, so local development never needs Azure.
    """
    vault_url = os.environ.get("KEY_VAULT_URL", "").strip()
    if vault_url:
        from backend.azure_integration.key_vault import get_secret

        value = get_secret(vault_url, env_key.lower().replace("_", "-"))
        if value:
            return value
    return os.environ.get(env_key, default)


@dataclass
class Config:
    """Application configuration resolved at startup."""

    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: _bool("FLASK_DEBUG", False))
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    # Azure App Service injects PORT; locally this stays 5000.
    port: int = field(default_factory=lambda: int(os.environ.get("PORT", 5000)))
    secret_key: str = field(
        default_factory=lambda: secret("SECRET_KEY", "dev-only-not-a-secret")
    )

    # -- storage ------------------------------------------------------------
    # "sqlite" for local development, "cosmos" on Azure. Selected by
    # configuration alone; no code path is Azure-only.
    storage_backend: str = field(
        default_factory=lambda: os.environ.get("STORAGE_BACKEND", BACKEND_SQLITE)
        .strip()
        .lower()
    )
    database_path: str = field(
        default_factory=lambda: _path("DATABASE_PATH", "data/dhanraksha.db")
    )

    # -- Cosmos DB (only read when storage_backend == "cosmos") -------------
    cosmos_endpoint: str = field(
        default_factory=lambda: os.environ.get("COSMOS_ENDPOINT", "")
    )
    cosmos_key: str = field(default_factory=lambda: secret("COSMOS_KEY", ""))
    cosmos_database: str = field(
        default_factory=lambda: os.environ.get("COSMOS_DATABASE", "dhanraksha")
    )
    cosmos_transactions_container: str = field(
        default_factory=lambda: os.environ.get(
            "COSMOS_TRANSACTIONS_CONTAINER", "transactions"
        )
    )
    cosmos_cases_container: str = field(
        default_factory=lambda: os.environ.get("COSMOS_CASES_CONTAINER", "cases")
    )

    # -- Blob Storage (optional everywhere) ---------------------------------
    storage_connection_string: str = field(
        default_factory=lambda: secret("STORAGE_CONNECTION_STRING", "")
    )
    blob_artifacts_container: str = field(
        default_factory=lambda: os.environ.get(
            "BLOB_ARTIFACTS_CONTAINER", "model-artifacts"
        )
    )
    blob_reports_container: str = field(
        default_factory=lambda: os.environ.get("BLOB_REPORTS_CONTAINER", "reports")
    )
    # When true, ModelService downloads artifacts from Blob Storage at startup
    # instead of reading ml/artifacts/ from the image.
    load_artifacts_from_blob: bool = field(
        default_factory=lambda: _bool("LOAD_ARTIFACTS_FROM_BLOB", False)
    )

    # -- Async processing queue (Azure Functions trigger) -------------------
    async_queue_name: str = field(
        default_factory=lambda: os.environ.get("ASYNC_QUEUE_NAME", "transaction-queue")
    )
    async_processing_enabled: bool = field(
        default_factory=lambda: _bool("ASYNC_PROCESSING_ENABLED", False)
    )

    # -- Key Vault ----------------------------------------------------------
    key_vault_url: str = field(
        default_factory=lambda: os.environ.get("KEY_VAULT_URL", "")
    )

    # -- Microsoft Entra ID -------------------------------------------------
    # Authentication is OFF by default so local development and the test suite
    # need no tenant. Turn it on only for the Azure deployment.
    auth_enabled: bool = field(default_factory=lambda: _bool("AUTH_ENABLED", False))
    entra_tenant_id: str = field(
        default_factory=lambda: os.environ.get("ENTRA_TENANT_ID", "")
    )
    entra_client_id: str = field(
        default_factory=lambda: os.environ.get("ENTRA_CLIENT_ID", "")
    )
    entra_audience: str = field(
        default_factory=lambda: os.environ.get("ENTRA_AUDIENCE", "")
    )

    # -- Application Insights -----------------------------------------------
    appinsights_connection_string: str = field(
        default_factory=lambda: secret("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    )
    # Fraction of telemetry sent, 0.0-1.0. Kept below 1.0 on Azure so a demo
    # cannot burn through the 5 GB/month free ingestion allowance.
    telemetry_sample_rate: float = field(
        default_factory=lambda: _float("TELEMETRY_SAMPLE_RATE", 1.0)
    )

    # -- ML artifacts -------------------------------------------------------
    artifact_dir: str = field(
        default_factory=lambda: _path("ARTIFACT_DIR", "ml/artifacts")
    )
    dataset_path: str = field(
        default_factory=lambda: _path("DATASET_PATH", "data/creditcard.csv")
    )

    # -- decision thresholds ------------------------------------------------
    fraud_threshold: float = field(
        default_factory=lambda: _float("FRAUD_THRESHOLD", 0.5)
    )
    risk_high_threshold: float = field(
        default_factory=lambda: _float("RISK_HIGH_THRESHOLD", 0.70)
    )
    risk_medium_threshold: float = field(
        default_factory=lambda: _float("RISK_MEDIUM_THRESHOLD", 0.40)
    )

    # -- case management ----------------------------------------------------
    auto_create_cases: bool = field(
        default_factory=lambda: _bool("AUTO_CREATE_CASES", True)
    )

    # -- api ----------------------------------------------------------------
    cors_origins: str = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "*")
    )
    max_page_size: int = field(
        default_factory=lambda: int(os.environ.get("MAX_PAGE_SIZE", 200))
    )

    # -- derived paths ------------------------------------------------------
    @property
    def model_path(self) -> str:
        return os.path.join(self.artifact_dir, "fraud_model.pkl")

    @property
    def pipeline_path(self) -> str:
        return os.path.join(self.artifact_dir, "feature_pipeline.pkl")

    @property
    def metadata_path(self) -> str:
        return os.path.join(self.artifact_dir, "model_metadata.json")

    @property
    def uses_cosmos(self) -> bool:
        return self.storage_backend == BACKEND_COSMOS

    @property
    def blob_enabled(self) -> bool:
        return bool(self.storage_connection_string)

    # -- validation ---------------------------------------------------------
    def validate(self) -> list[str]:
        """
        Return a list of configuration problems, empty when consistent.

        Called at startup so a misconfigured Azure deployment fails with a
        readable message rather than an SDK stack trace on the first request.
        """
        problems: list[str] = []

        if self.storage_backend not in (BACKEND_SQLITE, BACKEND_COSMOS):
            problems.append(
                f"STORAGE_BACKEND must be '{BACKEND_SQLITE}' or '{BACKEND_COSMOS}', "
                f"got '{self.storage_backend}'."
            )

        if self.uses_cosmos:
            if not self.cosmos_endpoint:
                problems.append("STORAGE_BACKEND=cosmos requires COSMOS_ENDPOINT.")
            if not self.cosmos_key:
                problems.append(
                    "STORAGE_BACKEND=cosmos requires COSMOS_KEY "
                    "(or a 'cosmos-key' secret in Key Vault)."
                )

        if self.auth_enabled:
            if not self.entra_tenant_id:
                problems.append("AUTH_ENABLED=true requires ENTRA_TENANT_ID.")
            if not self.entra_client_id:
                problems.append("AUTH_ENABLED=true requires ENTRA_CLIENT_ID.")

        if self.load_artifacts_from_blob and not self.storage_connection_string:
            problems.append(
                "LOAD_ARTIFACTS_FROM_BLOB=true requires STORAGE_CONNECTION_STRING."
            )

        if self.async_processing_enabled and not self.storage_connection_string:
            problems.append(
                "ASYNC_PROCESSING_ENABLED=true requires STORAGE_CONNECTION_STRING "
                "(the queue lives in the same storage account)."
            )

        if self.env == "production" and self.secret_key == "dev-only-not-a-secret":
            problems.append("SECRET_KEY must be set outside development.")

        return problems

    def as_public_dict(self) -> dict:
        """Configuration safe to expose over the API. Never includes a secret."""
        return {
            "env": self.env,
            "storage_backend": self.storage_backend,
            "fraud_threshold": self.fraud_threshold,
            "risk_high_threshold": self.risk_high_threshold,
            "risk_medium_threshold": self.risk_medium_threshold,
            "auto_create_cases": self.auto_create_cases,
            "auth_enabled": self.auth_enabled,
            "async_processing_enabled": self.async_processing_enabled,
            "blob_enabled": self.blob_enabled,
            "key_vault_enabled": bool(self.key_vault_url),
            "telemetry_enabled": bool(self.appinsights_connection_string),
        }


def load_config() -> Config:
    configuration = Config()
    for problem in configuration.validate():
        logger.error("Configuration problem: %s", problem)
    return configuration
