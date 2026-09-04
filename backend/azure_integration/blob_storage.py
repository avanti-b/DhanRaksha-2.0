"""
Azure Blob Storage client.

WHAT: object storage for files. Cheap, durable, unrelated to the database.

WHY DhanRaksha uses it, precisely:

  1. Model artifacts (~4.3 MB). fraud_model.pkl, feature_pipeline.pkl and
     model_metadata.json live in Blob Storage so a retrained model can be
     published without rebuilding and redeploying the application. Set
     LOAD_ARTIFACTS_FROM_BLOB=true and App Service downloads them at startup.

  2. Analytics reports (a few KB each). The scheduled Azure Function writes a
     daily JSON summary of scored volume and risk distribution, giving an audit
     trail that survives independently of the database.

What is deliberately NOT stored here: the 144 MB creditcard.csv. Training runs
locally, so the cloud never needs the dataset. Uploading it would add roughly
150 MB of storage plus egress every time it were read, for no benefit.

Expected footprint: well under 50 MB, which is a few cents a month at Hot LRS
rates and inside the 5 GB free allowance of a student subscription.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("dhanraksha.blob")

ARTIFACT_FILES = (
    "fraud_model.pkl",
    "feature_pipeline.pkl",
    "model_metadata.json",
)


class BlobStorageClient:
    """Thin wrapper over the Azure Blob SDK, importing it lazily."""

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self._service = None

    @property
    def service(self):
        if self._service is None:
            from azure.storage.blob import BlobServiceClient

            self._service = BlobServiceClient.from_connection_string(
                self.connection_string
            )
        return self._service

    def ensure_container(self, container: str) -> None:
        """Create the container if absent. Safe to call repeatedly."""
        try:
            self.service.create_container(container)
            logger.info("Created blob container '%s'.", container)
        except Exception as exc:  # noqa: BLE001 - already exists is the norm
            if "ContainerAlreadyExists" not in str(exc):
                logger.debug("create_container('%s'): %s", container, exc)

    # -- upload / download --------------------------------------------------
    def upload_file(self, container: str, blob_name: str, local_path: str) -> None:
        self.ensure_container(container)
        with open(local_path, "rb") as handle:
            self.service.get_blob_client(container, blob_name).upload_blob(
                handle, overwrite=True
            )
        logger.info("Uploaded %s -> %s/%s", local_path, container, blob_name)

    def download_file(self, container: str, blob_name: str, local_path: str) -> bool:
        """Download one blob. Returns False when it does not exist."""
        try:
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
            downloader = self.service.get_blob_client(container, blob_name).download_blob()
            with open(local_path, "wb") as handle:
                handle.write(downloader.readall())
            logger.info("Downloaded %s/%s -> %s", container, blob_name, local_path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not download %s/%s: %s", container, blob_name, exc)
            return False

    def upload_json(self, container: str, blob_name: str, payload: Any) -> None:
        self.ensure_container(container)
        self.service.get_blob_client(container, blob_name).upload_blob(
            json.dumps(payload, indent=2).encode("utf-8"), overwrite=True
        )
        logger.info("Wrote report %s/%s", container, blob_name)

    def list_blobs(self, container: str, prefix: str = "") -> list[str]:
        try:
            client = self.service.get_container_client(container)
            return [blob.name for blob in client.list_blobs(name_starts_with=prefix)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list '%s': %s", container, exc)
            return []


# -- convenience helpers ----------------------------------------------------
def upload_artifacts(
    connection_string: str, container: str, artifact_dir: str
) -> list[str]:
    """Publish the three local model artifacts. Used by scripts/upload_artifacts.py."""
    client = BlobStorageClient(connection_string)
    uploaded = []
    for filename in ARTIFACT_FILES:
        path = os.path.join(artifact_dir, filename)
        if os.path.exists(path):
            client.upload_file(container, filename, path)
            uploaded.append(filename)
        else:
            logger.warning("Artifact missing, skipped: %s", path)
    return uploaded


def download_artifacts(
    connection_string: str, container: str, artifact_dir: str
) -> bool:
    """
    Fetch artifacts into artifact_dir at startup.

    Returns True only when all three arrived, so ModelService can fall back to
    whatever shipped in the image rather than starting with a partial set.
    """
    client = BlobStorageClient(connection_string)
    results = [
        client.download_file(container, name, os.path.join(artifact_dir, name))
        for name in ARTIFACT_FILES
    ]
    return all(results)
