"""
DhanRaksha Risk Engine.

The ML model answers one question: how likely is this transaction to be fraud?
The Risk Engine answers a different one: what should be done about it? Keeping
them separate means the scoring policy can change without retraining, and every
decision can be explained to a reviewer.

Design rules:
  * Deterministic. Same input, same output, no randomness, no LLM involvement.
  * Explainable. Every point of risk score traces to a named rule.
  * Data-derived. Rule thresholds come from `risk_reference` in
    model_metadata.json, measured on the training split - not invented.
  * Extensible. `behavioural_signals` is an empty seam today; the Kaggle dataset
    is anonymised so there is no real customer history to use. Milestone 3 can
    populate it without changing the engine's contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"

# Fallback bounds, used only if model_metadata.json carries no risk_reference.
FALLBACK_REFERENCE: dict[str, Any] = {
    "amount_percentiles": {"p99": 1017.97, "p999": 3600.0},
    "elevated_risk_hours": [2, 3],
    "pca_legit_bounds": {},
}


@dataclass
class RiskRule:
    """A single deterministic rule."""

    name: str
    description: str
    weight: float
    triggered: bool = False
    detail: str = ""


@dataclass
class RiskAssessment:
    risk_level: str
    risk_score: float
    model_probability: float
    signals: list[str] = field(default_factory=list)
    triggered_rules: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 4),
            "model_probability": round(self.model_probability, 6),
            "signals": self.signals,
            "triggered_rules": self.triggered_rules,
            "explanation": self.explanation,
        }


class RiskEngine:
    """Combines model probability with deterministic transaction-level rules."""

    def __init__(
        self,
        high_threshold: float = 0.70,
        medium_threshold: float = 0.40,
        reference: dict[str, Any] | None = None,
    ) -> None:
        self.high_threshold = float(high_threshold)
        self.medium_threshold = float(medium_threshold)
        self.reference = reference or FALLBACK_REFERENCE

    # ------------------------------------------------------------------ API
    def assess(
        self,
        model_probability: float,
        amount: float,
        hour: int,
        v_features: dict[str, float] | None = None,
        behavioural_signals: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        probability = max(0.0, min(1.0, float(model_probability)))
        rules = self._evaluate_rules(probability, float(amount), int(hour), v_features or {})

        # Rules can only add risk on top of the model, never subtract it. The
        # model stays the dominant term; rules contribute at most 0.25.
        rule_contribution = min(0.25, sum(r.weight for r in rules if r.triggered))
        risk_score = min(1.0, probability + rule_contribution)

        # Behavioural seam for Milestone 3. No data exists today, so nothing is
        # invented here - an empty dict simply contributes nothing.
        if behavioural_signals:
            rules.extend(self._evaluate_behavioural(behavioural_signals))
            rule_contribution = min(0.25, sum(r.weight for r in rules if r.triggered))
            risk_score = min(1.0, probability + rule_contribution)

        level = self._classify(risk_score)
        triggered = [r for r in rules if r.triggered]

        return RiskAssessment(
            risk_level=level,
            risk_score=risk_score,
            model_probability=probability,
            signals=[r.name for r in triggered],
            triggered_rules=[
                {
                    "rule": r.name,
                    "description": r.description,
                    "weight": r.weight,
                    "detail": r.detail,
                }
                for r in triggered
            ],
            explanation=self._explain(level, probability, triggered),
        )

    def _classify(self, score: float) -> str:
        if score >= self.high_threshold:
            return HIGH
        if score >= self.medium_threshold:
            return MEDIUM
        return LOW

    # ---------------------------------------------------------------- rules
    def _evaluate_rules(
        self,
        probability: float,
        amount: float,
        hour: int,
        v_features: dict[str, float],
    ) -> list[RiskRule]:
        percentiles = self.reference.get("amount_percentiles", {})
        p99 = float(percentiles.get("p99", 1017.97))
        p999 = float(percentiles.get("p999", 3600.0))
        elevated_hours = set(self.reference.get("elevated_risk_hours", []))
        pca_bounds = self.reference.get("pca_legit_bounds", {})

        rules = [
            RiskRule(
                name="high_model_probability",
                description=(
                    f"Model fraud probability at or above {self.high_threshold:.2f}"
                ),
                weight=0.10,
                triggered=probability >= self.high_threshold,
                detail=f"probability={probability:.4f}",
            ),
            RiskRule(
                name="elevated_model_probability",
                description=(
                    f"Model fraud probability between {self.medium_threshold:.2f} "
                    f"and {self.high_threshold:.2f}"
                ),
                weight=0.05,
                triggered=self.medium_threshold <= probability < self.high_threshold,
                detail=f"probability={probability:.4f}",
            ),
            RiskRule(
                name="very_high_value_transaction",
                description=(
                    "Amount above the 99.9th percentile of the training data "
                    f"({p999:.2f})"
                ),
                weight=0.08,
                triggered=amount >= p999,
                detail=f"amount={amount:.2f} >= p99.9={p999:.2f}",
            ),
            RiskRule(
                name="high_value_transaction",
                description=(
                    f"Amount above the 99th percentile of the training data ({p99:.2f})"
                ),
                weight=0.04,
                triggered=p99 <= amount < p999,
                detail=f"amount={amount:.2f} >= p99={p99:.2f}",
            ),
            RiskRule(
                name="zero_amount_probe",
                description=(
                    "Zero-value transaction, a pattern associated with card testing"
                ),
                weight=0.05,
                triggered=amount == 0,
                detail="amount=0.00",
            ),
            RiskRule(
                name="elevated_risk_hour",
                description=(
                    "Hour of day whose fraud rate in the training data is more "
                    "than twice the overall rate"
                ),
                weight=0.05,
                triggered=hour in elevated_hours,
                detail=f"hour={hour}, elevated_hours={sorted(elevated_hours)}",
            ),
        ]

        rules.extend(self._evaluate_pca_outliers(v_features, pca_bounds))
        return rules

    def _evaluate_pca_outliers(
        self, v_features: dict[str, float], bounds: dict[str, Any]
    ) -> list[RiskRule]:
        """
        Flag PCA components that fall outside the range of legitimate traffic.

        Bounds are the 0.5th/99.5th percentile of the legitimate class in the
        training split, so a trigger means "this value is outside where 99% of
        legitimate transactions sit".
        """
        outliers: list[str] = []
        for column, bound in bounds.items():
            value = v_features.get(column)
            if value is None:
                continue
            if value < float(bound["low"]) or value > float(bound["high"]):
                outliers.append(f"{column}={value:.3f}")

        if not outliers:
            return []

        return [
            RiskRule(
                name="anomalous_pca_components",
                description=(
                    "One or more PCA components fall outside the range of 99% of "
                    "legitimate transactions in the training data"
                ),
                weight=0.04 * min(len(outliers), 3),
                triggered=True,
                detail=", ".join(outliers[:6]),
            )
        ]

    def _evaluate_behavioural(self, signals: dict[str, Any]) -> list[RiskRule]:
        """
        Milestone 3 seam.

        The Kaggle dataset carries no customer identity, device, geography or
        history, so no behavioural rule can be evaluated honestly in Milestone 1.
        Callers that later supply real signals get them scored here.
        """
        rules: list[RiskRule] = []
        if signals.get("new_device") is True:
            rules.append(
                RiskRule(
                    name="unrecognised_device",
                    description="Transaction from a device not seen for this account",
                    weight=0.05,
                    triggered=True,
                    detail="new_device=true",
                )
            )
        if signals.get("velocity_count") and int(signals["velocity_count"]) > 5:
            rules.append(
                RiskRule(
                    name="high_transaction_velocity",
                    description="Unusually many transactions in a short window",
                    weight=0.06,
                    triggered=True,
                    detail=f"velocity_count={signals['velocity_count']}",
                )
            )
        return rules

    # ------------------------------------------------------------ narrative
    @staticmethod
    def _explain(level: str, probability: float, triggered: list[RiskRule]) -> str:
        head = (
            f"Model scored this transaction at {probability:.1%} fraud probability. "
        )
        if not triggered:
            return head + f"No additional rules fired. Risk classified {level}."
        names = ", ".join(rule.name for rule in triggered)
        return head + f"Rules fired: {names}. Risk classified {level}."

    def describe(self) -> dict[str, Any]:
        """Configuration snapshot for /model-info and the docs."""
        return {
            "risk_high_threshold": self.high_threshold,
            "risk_medium_threshold": self.medium_threshold,
            "reference_source": self.reference.get(
                "derived_from", "fallback defaults (no risk_reference in artifacts)"
            ),
            "amount_percentiles": self.reference.get("amount_percentiles", {}),
            "elevated_risk_hours": self.reference.get("elevated_risk_hours", []),
            "pca_components_monitored": sorted(
                self.reference.get("pca_legit_bounds", {}).keys()
            ),
            "behavioural_signals": "not available in Milestone 1 (dataset is anonymised)",
        }
