"""Microsoft Entra ID authentication and role-based authorization."""

from backend.auth.entra import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_USER,
    current_identity,
    require_auth,
    require_role,
)

__all__ = [
    "ROLE_ADMIN",
    "ROLE_ANALYST",
    "ROLE_USER",
    "current_identity",
    "require_auth",
    "require_role",
]
