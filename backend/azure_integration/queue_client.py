"""
Azure Storage Queue producer.

WHAT: a simple message queue inside the same storage account used for blobs.
Chosen over Service Bus or Event Hubs because it needs no extra resource, has
no fixed monthly cost, and the free storage allowance covers a demo.

WHY: the synchronous path already returns a scored decision in milliseconds.
The queue exists for work that should not block the caller - enriching a case,
recomputing daily aggregates, notifying a reviewer. A message is enqueued after
the transaction is persisted, and an Azure Function picks it up.

FLOW:
    POST /api/v1/predict -> score -> persist -> enqueue message
                                                     |
                                          Azure Function (queue trigger)
                                                     |
                                        enrichment written back to Cosmos

Enqueueing is best effort by design. If the queue is unreachable, the
prediction has already been persisted and returned; the async enrichment is
simply skipped rather than failing the request.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger("dhanraksha.queue")


class TransactionQueueClient:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        self.connection_string = connection_string
        self.queue_name = queue_name
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from azure.storage.queue import QueueClient

            self._client = QueueClient.from_connection_string(
                self.connection_string, self.queue_name
            )
            try:
                self._client.create_queue()
            except Exception:  # noqa: BLE001 - already exists is normal
                pass
        return self._client

    def enqueue(self, message: dict[str, Any]) -> bool:
        """
        Queue one message. Returns False on failure; never raises.

        The payload carries identifiers and decision metadata only - enough for
        the Function to look the record up in Cosmos. Feature values are not
        duplicated into the queue.
        """
        try:
            body = json.dumps(message, separators=(",", ":"))
            # The Python Functions queue trigger expects base64 by default.
            encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
            self.client.send_message(encoded)
            logger.info("Queued %s", message.get("transaction_id"))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue message: %s", exc)
            return False
