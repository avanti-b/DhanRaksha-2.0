"""
Azure Key Vault secret retrieval.

WHAT: a managed store for secrets, with access controlled by Azure identity
rather than by who can read a config file.

WHY: on Azure the Cosmos key, storage connection string and Flask secret key
must not sit in App Settings as plain text where anyone with portal read access
can see them. Key Vault holds the value; App Service authenticates with its
managed identity and never stores a credential of its own.

HOW: config.secret() calls get_secret() first for any sensitive setting. If
KEY_VAULT_URL is unset (the local default) this module is never imported.

Authentication uses DefaultAzureCredential, which resolves in this order:
    * App Service managed identity   (how it works when deployed)
    * Azure CLI login                (how it works on your machine, az login)
    * environment service principal  (CI, if you ever add it)

No credential is ever written to a file.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger("dhanraksha.keyvault")

# Secrets are read once at startup. Key Vault bills per 10,000 operations, so
# caching keeps a restart-heavy demo comfortably inside the free allowance and
# also avoids a network round trip on every config read.
_cache: dict[str, str] = {}


@lru_cache(maxsize=4)
def _client(vault_url: str):
    """Build a SecretClient. Cached so one credential is reused per vault."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())


def get_secret(vault_url: str, secret_name: str) -> str:
    """
    Fetch a secret, returning "" when unavailable.

    A missing secret is not an error: config.secret() falls back to the
    environment variable, so a partially configured vault degrades to App
    Settings rather than breaking startup.
    """
    cache_key = f"{vault_url}:{secret_name}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        value = _client(vault_url).get_secret(secret_name).value or ""
        _cache[cache_key] = value
        logger.info("Loaded secret '%s' from Key Vault.", secret_name)
        return value
    except Exception as exc:  # noqa: BLE001 - fall back to env, never crash
        # The secret name is safe to log; the value never is.
        logger.warning(
            "Key Vault lookup for '%s' failed (%s). Falling back to environment.",
            secret_name,
            type(exc).__name__,
        )
        _cache[cache_key] = ""
        return ""


def clear_cache() -> None:
    """Drop cached secrets. Used by tests."""
    _cache.clear()
    _client.cache_clear()
