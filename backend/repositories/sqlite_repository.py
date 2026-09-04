"""SQLite implementations of the repository interfaces."""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.errors import NotFoundError, StorageError
from backend.repositories.base import CaseRepository, TransactionRepository
from backend.repositories.database import Database, dumps, loads


def _tx_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "transaction_id": row["transaction_id"],
        "timestamp": row["created_at"],
        "amount": float(row["amount"]),
        "hour": int(row["hour"]),
        "prediction": row["prediction"],
        "is_fraud": bool(row["is_fraud"]),
        "fraud_probability": float(row["fraud_probability"]),
        "risk_level": row["risk_level"],
        "risk_score": float(row["risk_score"]),
        "risk_signals": loads(row["risk_signals"], []),
        "triggered_rules": loads(row["triggered_rules"], []),
        "model_version": row["model_version"],
        "threshold_used": float(row["threshold_used"]),
        "features": loads(row["features"], {}),
        "source": row["source"],
    }


def _case_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "transaction_id": row["transaction_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "risk_level": row["risk_level"],
        "risk_score": float(row["risk_score"]),
        "signals": loads(row["signals"], []),
        "reviewer": row["reviewer"],
        "resolution": row["resolution"],
        "notes": row["notes"],
    }


class SqliteTransactionRepository(TransactionRepository):
    def __init__(self, database: Database) -> None:
        self.db = database

    def add(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.db.execute(
                """
                INSERT INTO transactions (
                    transaction_id, created_at, amount, hour, prediction, is_fraud,
                    fraud_probability, risk_level, risk_score, risk_signals,
                    triggered_rules, model_version, threshold_used, features, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record["transaction_id"],
                    record["timestamp"],
                    float(record["amount"]),
                    int(record["hour"]),
                    record["prediction"],
                    1 if record["is_fraud"] else 0,
                    float(record["fraud_probability"]),
                    record["risk_level"],
                    float(record["risk_score"]),
                    dumps(record.get("risk_signals", [])),
                    dumps(record.get("triggered_rules", [])),
                    record["model_version"],
                    float(record["threshold_used"]),
                    dumps(record.get("features", {})),
                    record.get("source", "api"),
                ),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - defensive
            raise StorageError("Transaction could not be stored.") from exc
        return record

    def get(self, transaction_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
        )
        return _tx_row_to_dict(row) if row else None

    def _filters(
        self,
        risk_level: str | None,
        prediction: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if risk_level:
            clauses.append("risk_level = ?")
            params.append(risk_level.upper())
        if prediction:
            clauses.append("prediction = ?")
            params.append(prediction.lower())
        if start_date:
            clauses.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("created_at <= ?")
            params.append(end_date)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._filters(risk_level, prediction, start_date, end_date)
        rows = self.db.query(
            f"SELECT * FROM transactions{where} "
            "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        )
        return [_tx_row_to_dict(row) for row in rows]

    def count(
        self,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        where, params = self._filters(risk_level, prediction, start_date, end_date)
        row = self.db.query_one(
            f"SELECT COUNT(*) AS total FROM transactions{where}", tuple(params)
        )
        return int(row["total"]) if row else 0

    def aggregate(self) -> dict[str, Any]:
        """Everything the analytics endpoint needs, computed in the store."""
        totals = self.db.query_one(
            """
            SELECT COUNT(*)                       AS total,
                   COALESCE(SUM(is_fraud), 0)     AS fraud,
                   COALESCE(AVG(amount), 0)       AS avg_amount,
                   COALESCE(SUM(amount), 0)       AS total_amount,
                   COALESCE(MAX(amount), 0)       AS max_amount,
                   COALESCE(AVG(fraud_probability), 0) AS avg_probability
            FROM transactions
            """
        )
        risk_rows = self.db.query(
            "SELECT risk_level, COUNT(*) AS n FROM transactions GROUP BY risk_level"
        )
        hour_rows = self.db.query(
            """
            SELECT hour,
                   COUNT(*) AS n,
                   COALESCE(SUM(is_fraud), 0) AS fraud
            FROM transactions GROUP BY hour ORDER BY hour
            """
        )
        day_rows = self.db.query(
            """
            SELECT substr(created_at, 1, 10) AS day,
                   COUNT(*) AS n,
                   COALESCE(SUM(is_fraud), 0) AS fraud
            FROM transactions GROUP BY day ORDER BY day DESC LIMIT 14
            """
        )
        band_rows = self.db.query(
            """
            SELECT CASE
                     WHEN amount < 10   THEN '<10'
                     WHEN amount < 100  THEN '10-100'
                     WHEN amount < 500  THEN '100-500'
                     WHEN amount < 2000 THEN '500-2000'
                     ELSE '2000+'
                   END AS band,
                   COUNT(*) AS n,
                   COALESCE(SUM(is_fraud), 0) AS fraud
            FROM transactions GROUP BY band
            """
        )
        return {
            "total": int(totals["total"]) if totals else 0,
            "fraud": int(totals["fraud"]) if totals else 0,
            "average_amount": float(totals["avg_amount"]) if totals else 0.0,
            "total_amount": float(totals["total_amount"]) if totals else 0.0,
            "max_amount": float(totals["max_amount"]) if totals else 0.0,
            "average_probability": float(totals["avg_probability"]) if totals else 0.0,
            "risk_distribution": {
                row["risk_level"]: int(row["n"]) for row in risk_rows
            },
            "by_hour": [
                {"hour": int(r["hour"]), "count": int(r["n"]), "fraud": int(r["fraud"])}
                for r in hour_rows
            ],
            "by_day": [
                {"day": r["day"], "count": int(r["n"]), "fraud": int(r["fraud"])}
                for r in day_rows
            ],
            "by_amount_band": [
                {"band": r["band"], "count": int(r["n"]), "fraud": int(r["fraud"])}
                for r in band_rows
            ],
        }


class SqliteCaseRepository(CaseRepository):
    def __init__(self, database: Database) -> None:
        self.db = database

    def add(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            self.db.execute(
                """
                INSERT INTO cases (
                    case_id, transaction_id, created_at, updated_at, status,
                    risk_level, risk_score, signals, reviewer, resolution, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record["case_id"],
                    record["transaction_id"],
                    record["created_at"],
                    record["updated_at"],
                    record["status"],
                    record["risk_level"],
                    float(record["risk_score"]),
                    dumps(record.get("signals", [])),
                    record.get("reviewer"),
                    record.get("resolution"),
                    record.get("notes"),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                "Case could not be stored; the transaction may not exist."
            ) from exc
        return record

    def get(self, case_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM cases WHERE case_id = ?", (case_id,))
        return _case_row_to_dict(row) if row else None

    def get_by_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM cases WHERE transaction_id = ? ORDER BY created_at LIMIT 1",
            (transaction_id,),
        )
        return _case_row_to_dict(row) if row else None

    def list(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[dict[str, Any]]:
        where, params = ("", [])
        if status:
            where, params = (" WHERE status = ?", [status.upper()])
        rows = self.db.query(
            f"SELECT * FROM cases{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        )
        return [_case_row_to_dict(row) for row in rows]

    def update(self, case_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"status", "reviewer", "resolution", "notes", "updated_at"}
        fields = {k: v for k, v in changes.items() if k in allowed}
        if not fields:
            existing = self.get(case_id)
            if existing is None:
                raise NotFoundError(f"Case '{case_id}' was not found.")
            return existing
        assignments = ", ".join(f"{key} = ?" for key in fields)
        cursor = self.db.execute(
            f"UPDATE cases SET {assignments} WHERE case_id = ?",
            (*fields.values(), case_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Case '{case_id}' was not found.")
        updated = self.get(case_id)
        if updated is None:  # pragma: no cover - defensive
            raise NotFoundError(f"Case '{case_id}' was not found.")
        return updated

    def status_counts(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM cases GROUP BY status")
        return {row["status"]: int(row["n"]) for row in rows}
