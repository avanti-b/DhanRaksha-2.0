"""
Publish local model artifacts to Azure Blob Storage.

Run after retraining, so App Service can pick up a new model without a
redeploy:

    python scripts/upload_artifacts.py

Requires STORAGE_CONNECTION_STRING in the environment or .env. Uploads three
files totalling roughly 4.3 MB. The 144 MB dataset is never uploaded.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.azure_integration.blob_storage import upload_artifacts  # noqa: E402
from backend.config import load_config  # noqa: E402


def main() -> int:
    config = load_config()

    if not config.storage_connection_string:
        print(
            "STORAGE_CONNECTION_STRING is not set.\n"
            "Get it from: Azure Portal -> Storage account -> Security + networking\n"
            "             -> Access keys -> key1 -> Connection string\n"
            "Then put it in .env as STORAGE_CONNECTION_STRING=..."
        )
        return 1

    print(f"Uploading from {config.artifact_dir}")
    print(f"Container:      {config.blob_artifacts_container}")

    uploaded = upload_artifacts(
        config.storage_connection_string,
        config.blob_artifacts_container,
        config.artifact_dir,
    )

    if not uploaded:
        print("Nothing uploaded. Train the model first: python -m ml.train")
        return 1

    for name in uploaded:
        print(f"  uploaded {name}")
    print(
        "\nDone. To make App Service use these, set LOAD_ARTIFACTS_FROM_BLOB=true "
        "in its Application settings and restart."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
