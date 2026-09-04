"""
DhanRaksha Azure Functions - asynchronous and scheduled processing.

WHAT: Azure Functions runs small pieces of code in response to events, with no
server to manage. On the Consumption plan you pay per execution and it scales
to zero when idle.

WHY DhanRaksha uses it: the synchronous API already returns a scored decision
in milliseconds, and it should stay that way. Work that does not need to block
the caller belongs here.

TWO FUNCTIONS, deliberately only two:

  1. process_transaction  (queue trigger)
     Fires when the API enqueues a scored transaction. Enriches the stored
     record with a review priority and an SLA due date, writing the result back
     to Cosmos DB. This is the asynchronous branch of the architecture:

         API -> score -> persist -> queue -> Function -> enrich -> Cosmos

  2. daily_report  (timer trigger, 06:00 UTC)
     Aggregates the day's scored volume and risk distribution and writes a
     small JSON report to Blob Storage. One execution per day.

COST: the Consumption plan includes a monthly free grant of 1,000,000
executions and 400,000 GB-s per subscription. This app produces one execution
per scored transaction plus one per day, so a demo uses a negligible fraction
of that. The associated storage account is billed normally but holds only
kilobytes.

IMPORTANT: the Function does NOT re-score fraud and does NOT make a fraud
decision. Scoring belongs to the model and the risk engine inside the API. This
Function only annotates a decision that was already made, so there is one
source of truth for what is fraudulent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import azure.functions as func

app = func.FunctionApp()

logger = logging.getLogger("dhanraksha.functions")

COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.environ.get("COSMOS_KEY", "")
COSMOS_DATABASE = os.environ.get("COSMOS_DATABASE", "dhanraksha")
TRANSACTIONS_CONTAINER = os.environ.get("COSMOS_TRANSACTIONS_CONTAINER", "transactions")
REPORTS_CONTAINER = os.environ.get("BLOB_REPORTS_CONTAINER", "reports")
STORAGE_CONNECTION = os.environ.get("AzureWebJobsStorage", "")

# Review turnaround targets by risk band, in hours. Deterministic policy, not a
# model output.
SLA_HOURS = {"HIGH": 4, "MEDIUM": 24, "LOW": 72}
PRIORITY = {"HIGH": "P1", "MEDIUM": "P2", "LOW": "P3"}


def _transactions_container():
    """Cosmos container client, or None when Cosmos is not configured."""
    if not (COSMOS_ENDPOINT and COSMOS_KEY):
        logger.warning("Cosmos is not configured; skipping database work.")
        return None
    from azure.cosmos import CosmosClient

    client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
    return client.get_database_client(COSMOS_DATABASE).get_container_client(
        TRANSACTIONS_CONTAINER
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. Queue-triggered enrichment
# ══════════════════════════════════════════════════════════════════════════
@app.function_name(name="process_transaction")
@app.queue_trigger(
    arg_name="message",
    queue_name="%ASYNC_QUEUE_NAME%",
    connection="AzureWebJobsStorage",
)
def process_transaction(message: func.QueueMessage) -> None:
    """
    Enrich a scored transaction after the API has already responded.

    The queue message carries identifiers and decision metadata only; the full
    record is read from Cosmos. Feature values are never duplicated into the
    queue.
    """
    try:
        payload = json.loads(message.get_body().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.error("Unparseable queue message; discarding.")
        return

    transaction_id = payload.get("transaction_id")
    risk_level = str(payload.get("risk_level", "LOW")).upper()
    logger.info("Enriching %s (risk=%s)", transaction_id, risk_level)

    container = _transactions_container()
    if container is None:
        return

    try:
        results = list(
            container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": transaction_id}],
                enable_cross_partition_query=True,
            )
        )
        if not results:
            logger.warning("Transaction %s not found in Cosmos.", transaction_id)
            return

        document = results[0]
        now = datetime.now(timezone.utc)

        # Deterministic annotations. No re-scoring, no model, no LLM.
        document["async_processing"] = {
            "processed_at": now.isoformat(timespec="seconds"),
            "review_priority": PRIORITY.get(risk_level, "P3"),
            "review_due_by": (
                now + timedelta(hours=SLA_HOURS.get(risk_level, 72))
            ).isoformat(timespec="seconds"),
            "requires_manual_review": risk_level in ("HIGH", "MEDIUM"),
            "processor_version": "func-v1",
        }

        container.replace_item(item=document["id"], body=document)
        logger.info("Enriched %s with priority %s", transaction_id, PRIORITY.get(risk_level))

    except Exception as exc:  # noqa: BLE001
        # Raising would make the runtime retry, and after five attempts the
        # message lands in the poison queue. Enrichment is not critical enough
        # for that, so failures are logged and the message is consumed.
        logger.error("Enrichment failed for %s: %s", transaction_id, exc)


# ══════════════════════════════════════════════════════════════════════════
# 2. Scheduled daily report
# ══════════════════════════════════════════════════════════════════════════
@app.function_name(name="daily_report")
@app.timer_trigger(
    schedule="0 0 6 * * *",  # 06:00 UTC daily
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daily_report(timer: func.TimerRequest) -> None:
    """
    Write a JSON summary of the previous day to Blob Storage.

    One execution per day, reading a projection of the day's documents. Gives
    an audit trail that outlives the database and costs a fraction of a cent.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    logger.info("Building daily report for %s", yesterday)

    container = _transactions_container()
    if container is None:
        return

    try:
        rows = list(
            container.query_items(
                query=(
                    "SELECT c.amount, c.is_fraud, c.risk_level, c.fraud_probability "
                    "FROM c WHERE STARTSWITH(c.timestamp, @day)"
                ),
                parameters=[{"name": "@day", "value": yesterday}],
                enable_cross_partition_query=True,
            )
        )

        total = len(rows)
        fraud = sum(1 for row in rows if row.get("is_fraud"))
        distribution: dict[str, int] = {}
        for row in rows:
            level = row.get("risk_level", "LOW")
            distribution[level] = distribution.get(level, 0) + 1

        report = {
            "report_date": yesterday,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_transactions": total,
            "fraud_flagged": fraud,
            "fraud_rate_percent": round(fraud / total * 100, 4) if total else 0.0,
            "risk_distribution": distribution,
            "total_amount": round(sum(float(r.get("amount", 0)) for r in rows), 2),
            "average_fraud_probability": (
                round(sum(float(r.get("fraud_probability", 0)) for r in rows) / total, 6)
                if total
                else 0.0
            ),
            "note": "Aggregated from transactions scored by DhanRaksha in this deployment.",
        }

        if STORAGE_CONNECTION:
            from azure.storage.blob import BlobServiceClient

            service = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
            try:
                service.create_container(REPORTS_CONTAINER)
            except Exception:  # noqa: BLE001 - already exists
                pass
            service.get_blob_client(
                REPORTS_CONTAINER, f"daily/{yesterday}.json"
            ).upload_blob(json.dumps(report, indent=2).encode("utf-8"), overwrite=True)
            logger.info("Report written: daily/%s.json (%d transactions)", yesterday, total)
        else:
            logger.warning("No storage connection; report not persisted.")

    except Exception as exc:  # noqa: BLE001
        logger.error("Daily report failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════
# 3. Health probe
# ══════════════════════════════════════════════════════════════════════════
@app.function_name(name="function_health")
@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def function_health(req: func.HttpRequest) -> func.HttpResponse:
    """Confirms the Function App is running and what it can reach."""
    return func.HttpResponse(
        json.dumps(
            {
                "status": "ok",
                "service": "dhanraksha-functions",
                "cosmos_configured": bool(COSMOS_ENDPOINT and COSMOS_KEY),
                "storage_configured": bool(STORAGE_CONNECTION),
                "functions": ["process_transaction", "daily_report", "function_health"],
            }
        ),
        mimetype="application/json",
        status_code=200,
    )
