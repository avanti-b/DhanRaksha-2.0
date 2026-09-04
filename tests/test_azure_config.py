"""
Azure configuration and backend switching.

These tests need no Azure account. They verify that configuration is validated
correctly, that the SQLite path is untouched by the Azure work, and that Azure
code paths stay dormant unless explicitly switched on.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from backend.config import BACKEND_COSMOS, BACKEND_SQLITE, Config


def _config(**env) -> Config:
    with mock.patch.dict(os.environ, env, clear=False):
        return Config()


def test_local_defaults_need_no_azure():
    config = _config()
    assert config.storage_backend == BACKEND_SQLITE
    assert config.auth_enabled is False
    assert config.blob_enabled is False
    assert config.async_processing_enabled is False
    assert config.key_vault_url == ""
    assert config.validate() == []


def test_cosmos_backend_requires_endpoint_and_key():
    problems = _config(STORAGE_BACKEND="cosmos").validate()
    assert any("COSMOS_ENDPOINT" in problem for problem in problems)
    assert any("COSMOS_KEY" in problem for problem in problems)


def test_fully_configured_cosmos_validates_cleanly():
    config = _config(
        STORAGE_BACKEND="cosmos",
        COSMOS_ENDPOINT="https://example.documents.azure.com:443/",
        COSMOS_KEY="not-a-real-key",
    )
    assert config.validate() == []
    assert config.uses_cosmos is True


def test_unknown_backend_is_rejected():
    problems = _config(STORAGE_BACKEND="postgres").validate()
    assert any("STORAGE_BACKEND" in problem for problem in problems)


def test_auth_requires_tenant_and_client():
    problems = _config(AUTH_ENABLED="true").validate()
    assert any("ENTRA_TENANT_ID" in problem for problem in problems)
    assert any("ENTRA_CLIENT_ID" in problem for problem in problems)


def test_blob_artifact_loading_requires_a_connection_string():
    problems = _config(LOAD_ARTIFACTS_FROM_BLOB="true").validate()
    assert any("STORAGE_CONNECTION_STRING" in problem for problem in problems)


def test_async_processing_requires_a_connection_string():
    problems = _config(ASYNC_PROCESSING_ENABLED="true").validate()
    assert any("STORAGE_CONNECTION_STRING" in problem for problem in problems)


def test_production_rejects_the_default_secret_key():
    problems = _config(APP_ENV="production").validate()
    assert any("SECRET_KEY" in problem for problem in problems)


def test_public_config_never_leaks_a_secret():
    config = _config(
        STORAGE_BACKEND="cosmos",
        COSMOS_ENDPOINT="https://example.documents.azure.com:443/",
        COSMOS_KEY="super-secret-value",
        STORAGE_CONNECTION_STRING="AccountKey=super-secret-value",
        SECRET_KEY="super-secret-value",
    )
    serialised = str(config.as_public_dict())
    assert "super-secret-value" not in serialised
    # It should still report *whether* things are configured.
    assert config.as_public_dict()["storage_backend"] == BACKEND_COSMOS
    assert config.as_public_dict()["blob_enabled"] is True


def test_health_reports_azure_components(client):
    body = client.get("/api/v1/health").get_json()
    components = body["components"]
    for name in (
        "model",
        "database",
        "key_vault",
        "blob_storage",
        "async_queue",
        "telemetry",
        "authentication",
    ):
        assert name in components
    # Local run: SQLite, nothing Azure switched on.
    assert components["database"]["engine"] == "sqlite"
    assert components["authentication"]["enabled"] is False


def test_secret_helper_falls_back_to_environment_without_key_vault():
    from backend.config import secret

    with mock.patch.dict(os.environ, {"KEY_VAULT_URL": "", "MY_TEST_VALUE": "from-env"}):
        assert secret("MY_TEST_VALUE") == "from-env"


def test_telemetry_is_a_noop_without_a_connection_string():
    from backend.azure_integration.telemetry import configure_telemetry, track_prediction

    assert configure_telemetry(None, "") is False
    # Must not raise when no span is active.
    track_prediction(12.3, "LOW", "rf-v1", "legitimate")
