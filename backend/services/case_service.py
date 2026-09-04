"""
Fraud case management.

A case is always anchored to a transaction that this system actually scored.
Cases are created automatically for HIGH-risk transactions (configurable via
AUTO_CREATE_CASES) and can be created manually by an analyst for any stored
transaction. No case is ever fabricated.

Status lifecycle:

    OPEN -> UNDER_REVIEW -> CONFIRMED_FRAUD | MARKED_LEGITIMATE -> CLOSED

Any transition is permitted (an analyst may reopen or close directly), but the
status value itself is validated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from backend.errors import ConflictError, NotFoundError, ValidationError
from backend.repositories.base import CaseRepository, TransactionRepository

STATUSES = (
    "OPEN",
    "UNDER_REVIEW",
    "CONFIRMED_FRAUD",
    "MARKED_LEGITIMATE",
    "CLOSED",
)
TERMINAL_STATUSES = ("CONFIRMED_FRAUD", "MARKED_LEGITIMATE", "CLOSED")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_case_id() -> str:
    return f"CASE-{uuid.uuid4().hex[:8].upper()}"


class CaseService:
    def __init__(
        self,
        case_repository: CaseRepository,
        transaction_repository: TransactionRepository,
        max_page_size: int = 200,
    ) -> None:
        self.cases = case_repository
        self.transactions = transaction_repository
        self.max_page_size = max_page_size

    # ------------------------------------------------------------- creation
    def open_case_for_transaction(
        self, transaction: dict[str, Any], notes: str | None = None
    ) -> dict[str, Any]:
        existing = self.cases.get_by_transaction(transaction["transaction_id"])
        if existing:
            return existing

        now = _now()
        record = {
            "case_id": new_case_id(),
            "transaction_id": transaction["transaction_id"],
            "created_at": now,
            "updated_at": now,
            "status": "OPEN",
            "risk_level": transaction["risk_level"],
            "risk_score": float(transaction["risk_score"]),
            "signals": transaction.get("risk_signals", []),
            "reviewer": None,
            "resolution": None,
            "notes": notes,
        }
        return self.cases.add(record)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Analyst-initiated case creation for an existing transaction."""
        transaction_id = payload.get("transaction_id")
        if not transaction_id:
            raise ValidationError("transaction_id is required to open a case.")

        transaction = self.transactions.get(str(transaction_id))
        if transaction is None:
            raise NotFoundError(
                f"Transaction '{transaction_id}' was not found; a case must "
                "reference a scored transaction."
            )

        existing = self.cases.get_by_transaction(str(transaction_id))
        if existing:
            raise ConflictError(
                f"A case already exists for transaction '{transaction_id}'.",
                {"case_id": existing["case_id"]},
            )

        return self.open_case_for_transaction(transaction, notes=payload.get("notes"))

    # ---------------------------------------------------------------- reads
    def get(self, case_id: str, include_transaction: bool = True) -> dict[str, Any]:
        case = self.cases.get(case_id)
        if case is None:
            raise NotFoundError(f"Case '{case_id}' was not found.")
        if include_transaction:
            case = dict(case)
            case["transaction"] = self.transactions.get(case["transaction_id"])
        return case

    def list(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> dict[str, Any]:
        if status and status.upper() not in STATUSES:
            raise ValidationError(
                f"status must be one of {', '.join(STATUSES)}.",
                {"received": status},
            )
        limit = max(1, min(int(limit), self.max_page_size))
        offset = max(0, int(offset))
        items = self.cases.list(limit=limit, offset=offset, status=status)
        counts = self.cases.status_counts()
        return {
            "items": items,
            "status_counts": {status_name: counts.get(status_name, 0) for status_name in STATUSES},
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(items),
                "total": sum(counts.values()) if not status else counts.get(status.upper(), 0),
            },
        }

    # -------------------------------------------------------------- updates
    def update(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        changes: dict[str, Any] = {}

        if "status" in payload and payload["status"] is not None:
            status = str(payload["status"]).upper()
            if status not in STATUSES:
                raise ValidationError(
                    f"status must be one of {', '.join(STATUSES)}.",
                    {"received": payload["status"]},
                )
            changes["status"] = status

        for field in ("reviewer", "resolution", "notes"):
            if field in payload:
                value = payload[field]
                if value is not None and not isinstance(value, str):
                    raise ValidationError(f"{field} must be a string.")
                if isinstance(value, str) and len(value) > 2000:
                    raise ValidationError(f"{field} must be 2000 characters or fewer.")
                changes[field] = value

        if not changes:
            raise ValidationError(
                "Provide at least one of: status, reviewer, resolution, notes."
            )

        changes["updated_at"] = _now()
        return self.cases.update(case_id, changes)

    def summary(self) -> dict[str, int]:
        counts = self.cases.status_counts()
        summary = {status: counts.get(status, 0) for status in STATUSES}
        summary["total"] = sum(counts.values())
        summary["open_or_review"] = summary["OPEN"] + summary["UNDER_REVIEW"]
        return summary
