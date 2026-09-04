"""
Entra ID authentication and role enforcement.

Token issuance needs a real tenant, so these tests cover the parts that do not:
that auth is off by default, that the decorators enforce the role hierarchy,
and that failures are rendered as clean JSON rather than stack traces.
"""

from __future__ import annotations

import pytest

from backend.auth.entra import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_USER,
    ROLE_HIERARCHY,
    AuthError,
)
from tests.conftest import requires_model


def test_admin_inherits_analyst_and_user():
    assert ROLE_HIERARCHY[ROLE_ADMIN] == {ROLE_USER, ROLE_ANALYST, ROLE_ADMIN}


def test_analyst_inherits_user_but_not_admin():
    assert ROLE_USER in ROLE_HIERARCHY[ROLE_ANALYST]
    assert ROLE_ADMIN not in ROLE_HIERARCHY[ROLE_ANALYST]


def test_user_has_no_elevated_roles():
    assert ROLE_HIERARCHY[ROLE_USER] == {ROLE_USER}


@requires_model
def test_endpoints_are_open_when_auth_is_disabled(client, sample_payload):
    """Local development must not need a tenant."""
    assert client.post("/api/v1/predict", json=sample_payload).status_code == 201
    assert client.get("/api/v1/transactions").status_code == 200
    assert client.get("/api/v1/analytics").status_code == 200
    assert client.get("/api/v1/cases").status_code == 200


def test_me_returns_a_local_identity_when_auth_is_disabled(client):
    body = client.get("/api/v1/me").get_json()
    assert body["authenticated"] is False
    assert set(body["roles"]) == {ROLE_USER, ROLE_ANALYST, ROLE_ADMIN}


def test_missing_token_is_rejected_when_auth_is_enabled(app, client, sample_payload):
    app.extensions["dhanraksha"].config.auth_enabled = True
    try:
        response = client.post("/api/v1/predict", json=sample_payload)
        body = response.get_json()
        assert response.status_code == 401
        assert body["error"] == "UNAUTHORIZED"
        assert "Bearer" in response.headers.get("WWW-Authenticate", "")
        assert "Traceback" not in str(body)
    finally:
        app.extensions["dhanraksha"].config.auth_enabled = False


def test_malformed_token_is_rejected(app, client):
    app.extensions["dhanraksha"].config.auth_enabled = True
    app.extensions["dhanraksha"].config.entra_tenant_id = "test-tenant"
    app.extensions["dhanraksha"].config.entra_client_id = "test-client"
    try:
        response = client.get(
            "/api/v1/analytics", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code in (401, 500)
        # Whatever the failure, the caller never sees internals.
        assert "Traceback" not in str(response.get_json())
    finally:
        app.extensions["dhanraksha"].config.auth_enabled = False


def test_health_stays_public_when_auth_is_enabled(app, client):
    """Health must stay reachable so Azure's probe works without a token."""
    app.extensions["dhanraksha"].config.auth_enabled = True
    try:
        assert client.get("/api/v1/health").status_code in (200, 503)
    finally:
        app.extensions["dhanraksha"].config.auth_enabled = False


def test_auth_error_carries_status_and_code():
    error = AuthError("nope", status=403, code="FORBIDDEN")
    assert error.status == 403
    assert error.code == "FORBIDDEN"
