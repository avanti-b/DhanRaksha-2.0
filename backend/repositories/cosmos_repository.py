"""
Azure Cosmos DB implementations of the repository interfaces.

These implement exactly the same abstract methods as the SQLite repositories in
sqlite_repository.py. Services, routes and tests are unchanged - the swap
happens in one place, build_container() in backend/app.py, driven by
STORAGE_BACKEND.

═══════════════════════════════════════════════════════════════════════════
DATA MODEL
═══════════════════════════════════════════════════════════════════════════

Database: dhanraksha          (one shared-throughput database, 400 RU/s)
  ├── container: transactions   partition key: /risk_level
  └── container: cases          partition key: /status

Throughput is provisioned at the DATABASE level and shared by both containers.
This matters for cost: the Cosmos free tier covers the first 1000 RU/s per
account, and dedicated per-container throughput would reserve a minimum of
400 RU/s each. Sharing one 400 RU/s allocation keeps the whole application
inside the free tier with room to spare.

── Why /risk_level partitions transactions ──
Partition key choice trades cardinality against query locality.

  * The dominant reads are "recent transactions" and "transactions filtered by
    risk level". Partitioning on risk_level makes the filtered query
    single-partition, which is the cheapest kind in RU terms.
  * Only three values exist (LOW, MEDIUM, HIGH), so there are three logical
    partitions. Low cardinality is normally a warning sign because a logical
    partition caps at 20 GB - but each transaction document is roughly 2 KB,
    so 20 GB is about 10 million transactions per risk band. A student project
    will not approach that.
  * /transaction_id would give perfect distribution but make every listing a
    cross-partition fan-out, which is more expensive for the query pattern
    this application actually has.

If this were heading for real volume, the right key would be a synthetic
composite such as /yyyymm_risk to bound partition growth over time. That is
noted rather than implemented, because at demo scale it would be
over-engineering.

── Why /status partitions cases ──
Cases are almost always read as "the open queue" or "cases under review", so
partitioning on status makes the analyst's primary view single-partition.
Status changes mean a document moves partition, which Cosmos handles as a
delete plus insert - acceptable given cases are updated a handful of times
each, and are far fewer than transactions.

── Document shape ──
Identical to the SQLite row shape, so the same service code reads both. Cosmos
requires an `id` field, which is set to the transaction_id or case_id. Fields
that SQLite stored as JSON strings (signals, rules, features) are stored as
native objects here, which is the natural document representation.

── What is not stored ──
The source dataset carries no cardholder name, card number, merchant or
location, and none is invented. Persisted `features` are the scaled model
inputs. Nothing personally identifying reaches Cosmos.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.errors import NotFoundError, StorageError
from backend.repositories.base import CaseRepository, TransactionRepository

logger = logging.getLogger("dhanraksha.cosmos")

TRANSACTIONS_PARTITION_KEY = "/risk_level"
CASES_PARTITION_KEY = "/status"

# Shared across both containers. 400 RU/s is the minimum for a shared-throughput
# database and sits inside the 1000 RU/s free tier.
DATABASE_THROUGHPUT = 400


class CosmosConnection:
    """
    Owns the Cosmos client and guarantees the database and containers exist.

    Creation is idempotent, so a fresh deployment provisions its own schema on
    first start and later starts are a no-op.
    """

    def __init__(
        self,
        endpoint: str,
        key: str,
        database_name: str,
        transactions_container: str = "transactions",
        cases_container: str = "cases",
        provision: bool = True,
    ) -> None:
        self.endpoint = endpoint
        self.database_name = database_name
        self.transactions_container_name = transactions_container
        self.cases_container_name = cases_container

        try:
            from azure.cosmos import CosmosClient
        except ImportError as exc:  # pragma: no cover - dependency guidance
            raise StorageError(
                "azure-cosmos is not installed. Run: pip install -r requirements-azure.txt"
            ) from exc

        self.client = CosmosClient(endpoint, credential=key)

        if provision:
            self._provision()
        else:
            self.database = self.client.get_database_client(database_name)
            self.transactions = self.database.get_container_client(transactions_container)
            self.cases = self.database.get_container_client(cases_container)

    def _provision(self) -> None:
        from azure.cosmos import PartitionKey, exceptions

        try:
            # offer_throughput applies at the database level, shared by both
            # containers. If the database already exists the existing
            # throughput is kept.
            self.database = self.client.create_database_if_not_exists(
                id=self.database_name, offer_throughput=DATABASE_THROUGHPUT
            )
            self.transactions = self.database.create_container_if_not_exists(
                id=self.transactions_container_name,
                partition_key=PartitionKey(path=TRANSACTIONS_PARTITION_KEY),
            )
            self.cases = self.database.create_container_if_not_exists(
                id=self.cases_container_name,
                partition_key=PartitionKey(path=CASES_PARTITION_KEY),
            )
            logger.info(
                "Cosmos ready: %s/%s and %s/%s",
                self.database_name,
                self.transactions_container_name,
                self.database_name,
                self.cases_container_name,
            )
        except exceptions.CosmosHttpResponseError as exc:
            raise StorageError(
                f"Could not provision Cosmos DB ({exc.status_code}). "
                "Check COSMOS_ENDPOINT and COSMOS_KEY."
            ) from exc

    def close(self) -> None:
        """Present for parity with the SQLite Database class."""
        return None


def _strip_system_fields(document: dict[str, Any]) -> dict[str, Any]:
    """Remove Cosmos bookkeeping fields (_rid, _ts, _etag, id) from a document."""
    return {
        key: value
        for key, value in document.items()
        if not key.startswith("_") and key != "id"
    }


class CosmosTransactionRepository(TransactionRepository):
    def __init__(self, connection: CosmosConnection) -> None:
        self.connection = connection
        self.container = connection.transactions

    def add(self, record: dict[str, Any]) -> dict[str, Any]:
        from azure.cosmos import exceptions

        document = dict(record)
        document["id"] = record["transaction_id"]
        try:
            self.container.create_item(body=document)
        except exceptions.CosmosResourceExistsError as exc:
            raise StorageError(
                f"Transaction '{record['transaction_id']}' already exists."
            ) from exc
        except exceptions.CosmosHttpResponseError as exc:
            logger.error("Cosmos write failed: %s", exc)
            raise StorageError("Transaction could not be stored.") from exc
        return record

    def get(self, transaction_id: str) -> dict[str, Any] | None:
        # The partition key is not known from the ID alone, so this is a
        # cross-partition point read. With three partitions the cost is
        # negligible; a query is simpler than storing a lookup index.
        results = list(
            self.container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": transaction_id}],
                enable_cross_partition_query=True,
            )
        )
        return _strip_system_fields(results[0]) if results else None

    def _where(
        self,
        risk_level: str | None,
        prediction: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        clauses: list[str] = []
        parameters: list[dict[str, Any]] = []
        if risk_level:
            clauses.append("c.risk_level = @risk_level")
            parameters.append({"name": "@risk_level", "value": risk_level.upper()})
        if prediction:
            clauses.append("c.prediction = @prediction")
            parameters.append({"name": "@prediction", "value": prediction.lower()})
        if start_date:
            clauses.append("c.timestamp >= @start_date")
            parameters.append({"name": "@start_date", "value": start_date})
        if end_date:
            clauses.append("c.timestamp <= @end_date")
            parameters.append({"name": "@end_date", "value": end_date})
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, parameters

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        where, parameters = self._where(risk_level, prediction, start_date, end_date)
        query = (
            f"SELECT * FROM c{where} ORDER BY c.timestamp DESC "
            f"OFFSET {int(offset)} LIMIT {int(limit)}"
        )
        items = self.container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        )
        return [_strip_system_fields(item) for item in items]

    def count(
        self,
        risk_level: str | None = None,
        prediction: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        where, parameters = self._where(risk_level, prediction, start_date, end_date)
        results = list(
            self.container.query_items(
                query=f"SELECT VALUE COUNT(1) FROM c{where}",
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )
        return int(results[0]) if results else 0

    def aggregate(self) -> dict[str, Any]:
        """
        Analytics aggregates.

        SQLite pushed GROUP BY into the engine. Cosmos supports aggregates but
        charges RUs per grouping query, and running six of them on every
        dashboard load is wasteful at this scale. Instead one projection query
        pulls the small set of fields needed and the grouping happens in
        Python. At demo volumes this is both cheaper and simpler; if the
        collection grew past tens of thousands of documents the right move
        would be a materialised summary document updated by the Function.
        """
        rows = list(
            self.container.query_items(
                query=(
                    "SELECT c.amount, c.hour, c.is_fraud, c.risk_level, "
                    "c.fraud_probability, c.timestamp FROM c"
                ),
                enable_cross_partition_query=True,
            )
        )

        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "fraud": 0,
                "average_amount": 0.0,
                "total_amount": 0.0,
                "max_amount": 0.0,
                "average_probability": 0.0,
                "risk_distribution": {},
                "by_hour": [],
                "by_day": [],
                "by_amount_band": [],
            }

        amounts = [float(row.get("amount", 0.0)) for row in rows]
        fraud = sum(1 for row in rows if row.get("is_fraud"))

        risk_distribution: dict[str, int] = {}
        by_hour: dict[int, dict[str, int]] = {}
        by_day: dict[str, dict[str, int]] = {}
        by_band: dict[str, dict[str, int]] = {}

        for row in rows:
            is_fraud = 1 if row.get("is_fraud") else 0

            level = row.get("risk_level", "LOW")
            risk_distribution[level] = risk_distribution.get(level, 0) + 1

            hour = int(row.get("hour", 0))
            bucket = by_hour.setdefault(hour, {"count": 0, "fraud": 0})
            bucket["count"] += 1
            bucket["fraud"] += is_fraud

            day = str(row.get("timestamp", ""))[:10]
            day_bucket = by_day.setdefault(day, {"count": 0, "fraud": 0})
            day_bucket["count"] += 1
            day_bucket["fraud"] += is_fraud

            amount = float(row.get("amount", 0.0))
            if amount < 10:
                band = "<10"
            elif amount < 100:
                band = "10-100"
            elif amount < 500:
                band = "100-500"
            elif amount < 2000:
                band = "500-2000"
            else:
                band = "2000+"
            band_bucket = by_band.setdefault(band, {"count": 0, "fraud": 0})
            band_bucket["count"] += 1
            band_bucket["fraud"] += is_fraud

        return {
            "total": total,
            "fraud": fraud,
            "average_amount": sum(amounts) / total,
            "total_amount": sum(amounts),
            "max_amount": max(amounts),
            "average_probability": sum(
                float(row.get("fraud_probability", 0.0)) for row in rows
            )
            / total,
            "risk_distribution": risk_distribution,
            "by_hour": [
                {"hour": hour, "count": data["count"], "fraud": data["fraud"]}
                for hour, data in sorted(by_hour.items())
            ],
            "by_day": [
                {"day": day, "count": data["count"], "fraud": data["fraud"]}
                for day, data in sorted(by_day.items(), reverse=True)[:14]
            ],
            "by_amount_band": [
                {"band": band, "count": data["count"], "fraud": data["fraud"]}
                for band, data in by_band.items()
            ],
        }


class CosmosCaseRepository(CaseRepository):
    def __init__(self, connection: CosmosConnection) -> None:
        self.connection = connection
        self.container = connection.cases

    def add(self, record: dict[str, Any]) -> dict[str, Any]:
        from azure.cosmos import exceptions

        document = dict(record)
        document["id"] = record["case_id"]
        try:
            self.container.create_item(body=document)
        except exceptions.CosmosHttpResponseError as exc:
            logger.error("Cosmos case write failed: %s", exc)
            raise StorageError("Case could not be stored.") from exc
        return record

    def get(self, case_id: str) -> dict[str, Any] | None:
        results = list(
            self.container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": case_id}],
                enable_cross_partition_query=True,
            )
        )
        return _strip_system_fields(results[0]) if results else None

    def get_by_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        results = list(
            self.container.query_items(
                query=(
                    "SELECT * FROM c WHERE c.transaction_id = @tx "
                    "ORDER BY c.created_at OFFSET 0 LIMIT 1"
                ),
                parameters=[{"name": "@tx", "value": transaction_id}],
                enable_cross_partition_query=True,
            )
        )
        return _strip_system_fields(results[0]) if results else None

    def list(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[dict[str, Any]]:
        where, parameters = "", []
        if status:
            where = " WHERE c.status = @status"
            parameters = [{"name": "@status", "value": status.upper()}]
        items = self.container.query_items(
            query=(
                f"SELECT * FROM c{where} ORDER BY c.created_at DESC "
                f"OFFSET {int(offset)} LIMIT {int(limit)}"
            ),
            parameters=parameters,
            enable_cross_partition_query=True,
        )
        return [_strip_system_fields(item) for item in items]

    def update(self, case_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        from azure.cosmos import exceptions

        existing = self.get(case_id)
        if existing is None:
            raise NotFoundError(f"Case '{case_id}' was not found.")

        allowed = {"status", "reviewer", "resolution", "notes", "updated_at"}
        updated = {**existing, **{k: v for k, v in changes.items() if k in allowed}}
        updated["id"] = case_id

        old_status = existing["status"]
        new_status = updated["status"]

        try:
            if old_status != new_status:
                # status is the partition key, so a change means the document
                # moves partition. Cosmos has no cross-partition update, so
                # this is a create in the new partition followed by a delete
                # from the old one. Create first: if the delete fails, a
                # duplicate is recoverable, whereas a lost case is not.
                self.container.create_item(body=updated)
                try:
                    self.container.delete_item(item=case_id, partition_key=old_status)
                except exceptions.CosmosHttpResponseError as exc:
                    logger.error(
                        "Case %s copied to partition '%s' but the old copy in "
                        "'%s' could not be removed: %s",
                        case_id,
                        new_status,
                        old_status,
                        exc,
                    )
            else:
                self.container.replace_item(item=case_id, body=updated)
        except exceptions.CosmosHttpResponseError as exc:
            logger.error("Cosmos case update failed: %s", exc)
            raise StorageError("Case could not be updated.") from exc

        return _strip_system_fields(updated)

    def status_counts(self) -> dict[str, int]:
        rows = list(
            self.container.query_items(
                query="SELECT c.status FROM c",
                enable_cross_partition_query=True,
            )
        )
        counts: dict[str, int] = {}
        for row in rows:
            status = row.get("status", "OPEN")
            counts[status] = counts.get(status, 0) + 1
        return counts
