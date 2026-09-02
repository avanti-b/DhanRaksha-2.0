"""
Fraud service: the one place where a prediction is orchestrated end to end.

    validated input -> preprocessing -> model -> risk engine -> persistence
                    -> optional case creation -> response

Routes call this and nothing else, so the same flow can later be triggered by
an Azure Function or a queue consumer without duplicating logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.services.case_service import CaseService
from backend.services.model_service import ModelService
from backend.services.risk_engine import HIGH, RiskEngine
from backend.services.transaction_service import TransactionService
from ml.preprocessing import RawTransaction


def new_transaction_id() -> str:
    return f"TXN-{uuid.uuid4().hex[:10].upper()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FraudService:
    def __init__(
        self,
        model_service: ModelService,
        risk_engine: RiskEngine,
        transaction_service: TransactionService,
        case_service: CaseService,
        fraud_threshold: float = 0.5,
        auto_create_cases: bool = True,
    ) -> None:
        self.model_service = model_service
        self.risk_engine = risk_engine
        self.transaction_service = transaction_service
        self.case_service = case_service
        self.fraud_threshold = float(fraud_threshold)
        self.auto_create_cases = auto_create_cases

    def predict(self, payload: dict) -> dict:
        """
        Score one validated transaction payload and persist the result.

        `payload` must already have passed schemas.validators.validate_prediction_payload.
        """
        raw = RawTransaction(
            amount=float(payload["amount"]),
            hour=int(payload["hour"]),
            v_features=payload["v_features"],
        )

        probability, scaled_features = self.model_service.predict_probability(raw)

        assessment = self.risk_engine.assess(
            model_probability=probability,
            amount=raw.amount,
            hour=raw.hour,
            v_features=raw.v_features,
            behavioural_signals=payload.get("behavioural_signals"),
        )

        is_fraud = probability >= self.fraud_threshold
        record = {
            "transaction_id": payload.get("transaction_id") or new_transaction_id(),
            "timestamp": utc_now(),
            "amount": raw.amount,
            "hour": raw.hour,
            "prediction": "fraud" if is_fraud else "legitimate",
            "is_fraud": is_fraud,
            "fraud_probability": round(probability, 6),
            "risk_level": assessment.risk_level,
            "risk_score": round(assessment.risk_score, 4),
            "risk_signals": assessment.signals,
            "triggered_rules": assessment.triggered_rules,
            "model_version": self.model_service.model_version,
            "threshold_used": self.fraud_threshold,
            # Stored features are the scaled model inputs (PCA components plus
            # scaled Time/Amount). The dataset carries no cardholder identity,
            # card number or merchant, so nothing personally identifying is
            # persisted.
            "features": scaled_features,
            "source": payload.get("source", "api"),
        }

        self.transaction_service.record(record)

        case = None
        if self.auto_create_cases and assessment.risk_level == HIGH:
            case = self.case_service.open_case_for_transaction(record)

        return {
            "transaction_id": record["transaction_id"],
            "prediction": record["prediction"],
            "fraud_probability": record["fraud_probability"],
            "fraud_probability_percent": round(probability * 100, 2),
            "threshold_used": self.fraud_threshold,
            "risk_level": assessment.risk_level,
            "risk_score": record["risk_score"],
            "risk_signals": assessment.signals,
            "triggered_rules": assessment.triggered_rules,
            "explanation": assessment.explanation,
            "model_version": record["model_version"],
            "timestamp": record["timestamp"],
            "case_id": case["case_id"] if case else None,
        }
