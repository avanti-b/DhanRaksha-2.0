"""
Repository interfaces.

Services depend on these abstractions, never on SQLite directly. Milestone 2
adds CosmosTransactionRepository / CosmosCaseRepository implementing the same
protocols; no service or route code has to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TransactionRepository(ABC):
    @abstractmethod
    def add(self, record: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get(self, transaction_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def count(
        self,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int: ...

    @abstractmethod
    def aggregate(self) -> dict[str, Any]: ...


class CaseRepository(ABC):
    @abstractmethod
    def add(self, record: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def get(self, case_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_by_transaction(self, transaction_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    def update(self, case_id: str, changes: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def status_counts(self) -> dict[str, int]: ...
