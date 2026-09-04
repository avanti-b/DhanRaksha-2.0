"""
Transaction service: persistence-facing operations and analytics.

Every number returned here is computed from rows actually stored by the
prediction flow. There are no seeded, sample or placeholder statistics: an
empty database honestly reports zeros.
"""

from __future__ import annotations

from typing import Any

from backend.errors import NotFoundError
from backend.repositories.base import TransactionRepository

VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
VALID_PREDICTIONS = {"fraud", "legitimate"}


class TransactionService:
    def __init__(self, repository: TransactionRepository, max_page_size: int = 200):
        self.repository = repository
        self.max_page_size = max_page_size

    def record(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.repository.add(record)

    def get(self, transaction_id: str) -> dict[str, Any]:
        record = self.repository.get(transaction_id)
        if record is None:
            raise NotFoundError(f"Transaction '{transaction_id}' was not found.")
        return record

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), self.max_page_size))
        offset = max(0, int(offset))
        items = self.repository.list(
            limit=limit,
            offset=offset,
            risk_level=risk_level,
            prediction=prediction,
            start_date=start_date,
            end_date=end_date,
        )
        total = self.repository.count(
            risk_level=risk_level,
            prediction=prediction,
            start_date=start_date,
            end_date=end_date,
        )
        return {
            "items": items,
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "returned": len(items),
                "has_more": offset + len(items) < total,
            },
            "filters": {
                "risk_level": risk_level,
                "prediction": prediction,
                "start_date": start_date,
                "end_date": end_date,
            },
        }

    def analytics(self) -> dict[str, Any]:
        aggregate = self.repository.aggregate()
        total = aggregate["total"]
        fraud = aggregate["fraud"]
        distribution = {
            level: int(aggregate["risk_distribution"].get(level, 0))
            for level in ("LOW", "MEDIUM", "HIGH")
        }

        return {
            "totals": {
                "total_transactions": total,
                "fraud_detected": fraud,
                "legitimate": total - fraud,
                "fraud_rate_percent": round((fraud / total * 100), 4) if total else 0.0,
            },
            "amounts": {
                "average_amount": round(aggregate["average_amount"], 2),
                "total_amount": round(aggregate["total_amount"], 2),
                "max_amount": round(aggregate["max_amount"], 2),
            },
            "risk_distribution": distribution,
            "average_fraud_probability": round(aggregate["average_probability"], 6),
            "by_hour": aggregate["by_hour"],
            "by_day": aggregate["by_day"],
            "by_amount_band": aggregate["by_amount_band"],
            "recent_transactions": self.repository.list(limit=10, offset=0),
            "data_source": "persisted predictions from this deployment only",
        }
