"""Fraud case management: creation, lifecycle and integrity."""

from __future__ import annotations

import pytest

from tests.conftest import requires_model

pytestmark = requires_model


@pytest.fixture()
def transaction(client, sample_payload):
    return client.post("/api/v1/predict", json={**sample_payload, "amount": 60.0}).get_json()


def test_a_case_must_reference_a_real_transaction(client):
    response = client.post("/api/v1/cases", json={"transaction_id": "TXN-IMAGINARY"})
    assert response.status_code == 404
    assert response.get_json()["error"] == "NOT_FOUND"


def test_case_creation_requires_a_transaction_id(client):
    response = client.post("/api/v1/cases", json={})
    assert response.status_code == 400


def test_analyst_can_open_a_case_for_a_scored_transaction(client, transaction):
    response = client.post(
        "/api/v1/cases",
        json={"transaction_id": transaction["transaction_id"], "notes": "manual review"},
    )
    body = response.get_json()
    assert response.status_code == 201
    assert body["case_id"].startswith("CASE-")
    assert body["status"] == "OPEN"
    assert body["transaction_id"] == transaction["transaction_id"]


def test_duplicate_case_for_one_transaction_is_a_conflict(client, transaction):
    payload = {"transaction_id": transaction["transaction_id"]}
    client.post("/api/v1/cases", json=payload)
    response = client.post("/api/v1/cases", json=payload)
    assert response.status_code == 409
    assert response.get_json()["error"] == "CONFLICT"


def test_case_can_be_moved_through_its_lifecycle(client, transaction):
    case = client.post(
        "/api/v1/cases", json={"transaction_id": transaction["transaction_id"]}
    ).get_json()

    updated = client.patch(
        f"/api/v1/cases/{case['case_id']}",
        json={"status": "UNDER_REVIEW", "reviewer": "analyst-1"},
    ).get_json()
    assert updated["status"] == "UNDER_REVIEW"
    assert updated["reviewer"] == "analyst-1"

    resolved = client.patch(
        f"/api/v1/cases/{case['case_id']}",
        json={"status": "CONFIRMED_FRAUD", "resolution": "chargeback raised"},
    ).get_json()
    assert resolved["status"] == "CONFIRMED_FRAUD"
    assert resolved["resolution"] == "chargeback raised"
    assert resolved["updated_at"] >= resolved["created_at"]


def test_invalid_status_is_rejected(client, transaction):
    case = client.post(
        "/api/v1/cases", json={"transaction_id": transaction["transaction_id"]}
    ).get_json()
    response = client.patch(f"/api/v1/cases/{case['case_id']}", json={"status": "ESCALATED"})
    assert response.status_code == 400


def test_empty_patch_is_rejected(client, transaction):
    case = client.post(
        "/api/v1/cases", json={"transaction_id": transaction["transaction_id"]}
    ).get_json()
    assert client.patch(f"/api/v1/cases/{case['case_id']}", json={}).status_code == 400


def test_updating_an_unknown_case_returns_404(client):
    response = client.patch("/api/v1/cases/CASE-NOPE", json={"status": "CLOSED"})
    assert response.status_code == 404


def test_case_detail_includes_its_transaction(client, transaction):
    case = client.post(
        "/api/v1/cases", json={"transaction_id": transaction["transaction_id"]}
    ).get_json()
    body = client.get(f"/api/v1/cases/{case['case_id']}").get_json()
    assert body["transaction"]["transaction_id"] == transaction["transaction_id"]


def test_case_listing_reports_status_counts(client, transaction):
    client.post("/api/v1/cases", json={"transaction_id": transaction["transaction_id"]})
    body = client.get("/api/v1/cases").get_json()
    assert body["status_counts"]["OPEN"] >= 1
    assert len(body["items"]) >= 1


def test_case_listing_can_filter_by_status(client, transaction):
    client.post("/api/v1/cases", json={"transaction_id": transaction["transaction_id"]})
    body = client.get("/api/v1/cases?status=CLOSED").get_json()
    assert body["items"] == []


def test_real_fraud_row_is_scored_high_and_opens_a_case(client, container, known_fraud_payload):
    """
    A genuine fraud record from the dataset should be flagged and should open a
    case without an analyst asking for one.
    """
    if not container.config.auto_create_cases:
        pytest.skip("auto case creation disabled by configuration")

    result = client.post("/api/v1/predict", json=known_fraud_payload).get_json()
    assert result["prediction"] == "fraud"
    assert result["risk_level"] == "HIGH"
    assert result["case_id"] is not None

    case = client.get(f"/api/v1/cases/{result['case_id']}").get_json()
    assert case["status"] == "OPEN"
    assert case["transaction_id"] == result["transaction_id"]
    assert case["signals"]


def test_low_risk_transaction_does_not_open_a_case(client, sample_payload):
    result = client.post("/api/v1/predict", json={**sample_payload, "amount": 30.0}).get_json()
    if result["risk_level"] == "HIGH":
        pytest.skip("this transaction scored HIGH; not a low-risk example")
    assert result["case_id"] is None
