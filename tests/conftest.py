"""
Shared test fixtures.

Tests run against the real trained artifacts (so model loading and inference
are genuinely exercised) but against a throwaway SQLite file, so a test run
never touches the development database.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.app import create_app
from backend.config import Config

ARTIFACTS_PRESENT = os.path.exists(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ml",
        "artifacts",
        "fraud_model.pkl",
    )
)

requires_model = pytest.mark.skipif(
    not ARTIFACTS_PRESENT,
    reason="model artifacts missing; run 'python -m ml.train' first",
)


@pytest.fixture()
def config(tmp_path) -> Config:
    configuration = Config()
    configuration.database_path = str(tmp_path / "test.db")
    configuration.env = "test"
    return configuration


@pytest.fixture()
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    yield application
    application.extensions["dhanraksha"].database.close()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def container(app):
    return app.extensions["dhanraksha"]


@pytest.fixture()
def sample_payload() -> dict:
    """A modest, clearly ordinary transaction."""
    payload = {"amount": 42.50, "hour": 14}
    for index in range(1, 29):
        payload[f"v{index}"] = 0.0
    return payload


@pytest.fixture()
def known_fraud_payload() -> dict:
    """
    A real confirmed-fraud row from the Kaggle dataset (Class == 1).

    Copied verbatim so the case-management test does not need the 144 MB CSV
    present. Using a genuine record rather than hand-made numbers keeps the
    test honest: the model has to actually recognise real fraud.
    """
    return {
        "amount": 529.0,
        "hour": 0,
        "v1": -3.043541, "v2": -3.157307, "v3": 1.088463, "v4": 2.288644,
        "v5": 1.359805, "v6": -1.064823, "v7": 0.325574, "v8": -0.067794,
        "v9": -0.270953, "v10": -0.838587, "v11": -0.414575, "v12": -0.503141,
        "v13": 0.676502, "v14": -1.692029, "v15": 2.000635, "v16": 0.66678,
        "v17": 0.599717, "v18": 1.725321, "v19": 0.283345, "v20": 2.102339,
        "v21": 0.661696, "v22": 0.435477, "v23": 1.375966, "v24": -0.293803,
        "v25": 0.279798, "v26": -0.145362, "v27": -0.252773, "v28": 0.035764,
    }


@pytest.fixture()
def temp_db_path():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    yield path
    if os.path.exists(path):
        os.remove(path)
