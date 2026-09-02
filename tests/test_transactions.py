"""Transaction history: listing, filtering and pagination."""

from __future__ import annotations

import pytest

from tests.conftest import requires_model

pytestmark = requires_model


@pytest.fixture()
def seeded(client, sample_payload):
    """Score a handful of genuinely different transactions."""
    created = []
    cases = [
        {"amount": 5.0, "hour": 13},
        {"amount": 120.0, "hour": 9},
        {"amount": 4000.0, "hour": 2, "v14": -9.0, "v10": -7.0, "v12": -8.0},
    ]
    for overrides in cases:
        payload = {**sample_payload, **overrides}
        created.append(client.post("/api/v1/predict", json=payload).get_json())
    return created


def test_list_returns_everything_scored(client, seeded):
    body = client.get("/api/v1/transactions").get_json()
    assert body["pagination"]["total"] == 3
    assert len(body["items"]) == 3


def test_list_is_newest_first(client, seeded):
    items = client.get("/api/v1/transactions").get_json()["items"]
    timestamps = [item["timestamp"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)


def test_pagination_limits_and_offsets(client, seeded):
    first = client.get("/api/v1/transactions?limit=2").get_json()
    assert len(first["items"]) == 2
    assert first["pagination"]["has_more"] is True

    second = client.get("/api/v1/transactions?limit=2&offset=2").get_json()
    assert len(second["items"]) == 1
    assert second["pagination"]["has_more"] is False


def test_filter_by_risk_level(client, seeded):
    body = client.get("/api/v1/transactions?risk_level=LOW").get_json()
    assert all(item["risk_level"] == "LOW" for item in body["items"])
    assert body["filters"]["risk_level"] == "LOW"


def test_filter_by_prediction(client, seeded):
    body = client.get("/api/v1/transactions?prediction=legitimate").get_json()
    assert all(item["prediction"] == "legitimate" for item in body["items"])


def test_invalid_filter_is_rejected(client, seeded):
    response = client.get("/api/v1/transactions?risk_level=SEVERE")
    assert response.status_code == 400
    assert response.get_json()["error"] == "VALIDATION_ERROR"


def test_stored_record_carries_full_decision_context(client, seeded):
    record = client.get(f"/api/v1/transactions/{seeded[0]['transaction_id']}").get_json()[
        "transaction"
    ]
    for field in (
        "amount",
        "hour",
        "prediction",
        "fraud_probability",
        "risk_level",
        "risk_score",
        "risk_signals",
        "model_version",
        "threshold_used",
        "features",
        "timestamp",
    ):
        assert field in record
    assert len(record["features"]) == 30
