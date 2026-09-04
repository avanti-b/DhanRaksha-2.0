"""
Microsoft Entra ID authentication.

WHAT: Entra ID (formerly Azure Active Directory) is Microsoft's identity
service. It issues signed JWT access tokens carrying the caller's identity and
their assigned application roles.

WHY: once DhanRaksha is on a public App Service URL, anyone who finds it can
score transactions and modify fraud cases. Entra gives real authentication
without this project building and storing passwords.

HOW IT WORKS HERE:
    1. The caller signs in against Entra and receives an access token.
    2. They send it as `Authorization: Bearer <token>`.
    3. This module validates the signature against the tenant's published
       public keys (JWKS), checks issuer, audience and expiry, and reads the
       `roles` claim.
    4. Route decorators enforce which roles may reach which endpoint.

ROLES (defined as App Roles on the Entra app registration):
    USER     - submit transactions, view their own results
    ANALYST  - USER, plus all transactions, analytics and fraud cases
    ADMIN    - everything, including case resolution and model information

AUTH IS OFF BY DEFAULT. With AUTH_ENABLED=false (the local default) every
decorator becomes a pass-through and no token is required, so local development
and the test suite need no tenant. Turn it on only for the Azure deployment.

Validation is done locally against cached JWKS. No secret is stored by the API:
it verifies tokens, it does not issue them, so it needs no client secret.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from flask import current_app, g, jsonify, request

logger = logging.getLogger("dhanraksha.auth")

ROLE_USER = "USER"
ROLE_ANALYST = "ANALYST"
ROLE_ADMIN = "ADMIN"

# Higher roles inherit the permissions of lower ones.
ROLE_HIERARCHY = {
    ROLE_USER: {ROLE_USER},
    ROLE_ANALYST: {ROLE_USER, ROLE_ANALYST},
    ROLE_ADMIN: {ROLE_USER, ROLE_ANALYST, ROLE_ADMIN},
}

# JWKS keys are cached for an hour. Entra rotates signing keys infrequently and
# refetching per request would add latency and hammer the endpoint.
_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0, "tenant": None}


class AuthError(Exception):
    """Authentication or authorization failure. Rendered as 401/403 JSON."""

    def __init__(self, message: str, status: int = 401, code: str = "UNAUTHORIZED"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _config():
    return current_app.extensions["dhanraksha"].config


def _fetch_jwks(tenant_id: str) -> list[dict]:
    """Fetch and cache the tenant's JSON Web Key Set."""
    now = time.time()
    if (
        _jwks_cache["keys"] is not None
        and _jwks_cache["tenant"] == tenant_id
        and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]

    import requests

    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    keys = response.json().get("keys", [])

    _jwks_cache.update({"keys": keys, "fetched_at": now, "tenant": tenant_id})
    logger.info("Fetched %d Entra signing keys.", len(keys))
    return keys


def validate_token(token: str) -> dict[str, Any]:
    """
    Verify a bearer token and return its claims.

    Checks the RS256 signature against the tenant JWKS, plus audience, issuer
    and expiry. Raises AuthError on any failure.
    """
    config = _config()

    try:
        from jose import jwt
        from jose.exceptions import JWTError
    except ImportError as exc:
        raise AuthError(
            "Authentication is enabled but python-jose is not installed.",
            status=500,
            code="AUTH_MISCONFIGURED",
        ) from exc

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AuthError("Malformed access token.") from exc

    keys = _fetch_jwks(config.entra_tenant_id)
    key = next((k for k in keys if k.get("kid") == unverified_header.get("kid")), None)
    if key is None:
        raise AuthError("Token signing key is not recognised for this tenant.")

    audience = config.entra_audience or config.entra_client_id
    issuer = f"https://login.microsoftonline.com/{config.entra_tenant_id}/v2.0"

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        # The specific reason stays in the log; the caller gets a generic
        # message so token probing reveals nothing.
        logger.info("Token rejected: %s", exc)
        raise AuthError("Access token is invalid or has expired.") from exc

    return claims


def _identity_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    roles = claims.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return {
        "subject": claims.get("sub"),
        "name": claims.get("name"),
        "username": claims.get("preferred_username"),
        "roles": [str(role).upper() for role in roles],
        "tenant_id": claims.get("tid"),
    }


def current_identity() -> dict[str, Any]:
    """
    The authenticated caller for this request.

    When auth is disabled this returns a local development identity holding all
    roles, so every endpoint stays reachable without a tenant.
    """
    identity = getattr(g, "identity", None)
    if identity is not None:
        return identity
    return {
        "subject": "local-development",
        "name": "Local Developer",
        "username": "local@dhanraksha.dev",
        "roles": [ROLE_USER, ROLE_ANALYST, ROLE_ADMIN],
        "tenant_id": None,
        "authenticated": False,
    }


def _authenticate() -> dict[str, Any]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("An 'Authorization: Bearer <token>' header is required.")

    claims = validate_token(header[7:].strip())
    identity = _identity_from_claims(claims)
    identity["authenticated"] = True
    g.identity = identity
    return identity


def require_auth(view: Callable) -> Callable:
    """Require a valid token. A pass-through when AUTH_ENABLED is false."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _config().auth_enabled:
            return view(*args, **kwargs)
        _authenticate()
        return view(*args, **kwargs)

    return wrapper


def require_role(*required_roles: str) -> Callable:
    """
    Require a valid token carrying at least one of the given roles.

    Roles are hierarchical: ADMIN satisfies a requirement for ANALYST or USER.
    A pass-through when AUTH_ENABLED is false.
    """

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if not _config().auth_enabled:
                return view(*args, **kwargs)

            identity = _authenticate()

            granted: set[str] = set()
            for role in identity["roles"]:
                granted |= ROLE_HIERARCHY.get(role, {role})

            if not granted & set(required_roles):
                raise AuthError(
                    "Your account does not have permission for this operation. "
                    f"Required: {' or '.join(required_roles)}.",
                    status=403,
                    code="FORBIDDEN",
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def register_auth_handlers(app) -> None:
    @app.errorhandler(AuthError)
    def _handle_auth_error(exc: AuthError):
        response = jsonify({"error": exc.code, "message": exc.message})
        response.status_code = exc.status
        if exc.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response
