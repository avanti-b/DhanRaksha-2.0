"""
SQLite connection handling and schema bootstrap.

SQLite is the Milestone 1 store. Records are written in a document-friendly
shape (JSON columns for feature payloads and risk signals) so that swapping in
Azure Cosmos DB during Milestone 2 is a repository change, not a rewrite.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id     TEXT PRIMARY KEY,
    created_at         TEXT NOT NULL,
    amount             REAL NOT NULL,
    hour               INTEGER NOT NULL,
    prediction         TEXT NOT NULL,
    is_fraud           INTEGER NOT NULL,
    fraud_probability  REAL NOT NULL,
    risk_level         TEXT NOT NULL,
    risk_score         REAL NOT NULL,
    risk_signals       TEXT NOT NULL,
    triggered_rules    TEXT NOT NULL,
    model_version      TEXT NOT NULL,
    threshold_used     REAL NOT NULL,
    features           TEXT NOT NULL,
    source             TEXT NOT NULL DEFAULT 'api'
);

CREATE INDEX IF NOT EXISTS idx_tx_created_at ON transactions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_risk_level ON transactions (risk_level);
CREATE INDEX IF NOT EXISTS idx_tx_is_fraud   ON transactions (is_fraud);

CREATE TABLE IF NOT EXISTS cases (
    case_id        TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    risk_level     TEXT NOT NULL,
    risk_score     REAL NOT NULL,
    signals        TEXT NOT NULL,
    reviewer       TEXT,
    resolution     TEXT,
    notes          TEXT,
    FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_case_status ON cases (status);
CREATE INDEX IF NOT EXISTS idx_case_tx     ON cases (transaction_id);
"""


class Database:
    """Thin thread-safe wrapper around a SQLite file."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._shared: sqlite3.Connection | None = None
        if path == ":memory:":
            self._shared = self._new_connection()
        self.initialise()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=10.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @property
    def connection(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        existing = getattr(self._local, "connection", None)
        if existing is None:
            existing = self._new_connection()
            self._local.connection = existing
        return existing

    def initialise(self) -> None:
        with self.connection as conn:
            conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.connection as conn:
            return conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, params).fetchone()

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            existing.close()
            self._local.connection = None


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
