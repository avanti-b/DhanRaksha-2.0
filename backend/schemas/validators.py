"""
Request validation.

Hand-written rather than pulled from a validation library: the payload shapes
are small and fixed, and keeping the dependency list short matters for the
Azure container image later. Every failure raises ValidationError, which the
error handler renders as a clean JSON body.
"""

from __future__ import annotations

import math
from typing import Any

from backend.errors import ValidationError
from ml.preprocessing import V_COLUMNS

MAX_AMOUNT = 1_000_000.0
# The PCA components in the source dataset lie roughly within +/-120. Anything
# far outside that is a malformed request rather than a real transaction.
PCA_ABS_LIMIT = 200.0
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
VALID_PREDICTIONS = {"fraud", "legitimate"}


def _as_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{field} must be a number.")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValidationError(f"{field} must be a number.")
        try:
            value = float(stripped)
        except ValueError:
            raise ValidationError(f"{field} must be a number.") from None
    if not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number.")
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise ValidationError(f"{field} must be a finite number.")
    return number


def validate_prediction_payload(payload: Any) -> dict[str, Any]:
    """
    Validate a POST /api/v1/predict body.

    Required : amount (>= 0), hour (0-23)
    Optional : v1..v28 (or V1..V28) PCA components, transaction_id,
               behavioural_signals
    Missing PCA components default to 0.0, the mean of a centred component.
    """
    if payload is None or not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    missing = [field for field in ("amount", "hour") if field not in payload]
    if missing:
        raise ValidationError(
            f"Missing required field(s): {', '.join(missing)}.",
            {"required": ["amount", "hour"]},
        )

    amount = _as_number(payload["amount"], "amount")
    if amount < 0:
        raise ValidationError("Amount must be a non-negative number.")
    if amount > MAX_AMOUNT:
        raise ValidationError(f"Amount must not exceed {MAX_AMOUNT:,.0f}.")

    hour_value = _as_number(payload["hour"], "hour")
    if hour_value != int(hour_value):
        raise ValidationError("Hour must be a whole number between 0 and 23.")
    hour = int(hour_value)
    if not 0 <= hour <= 23:
        raise ValidationError("Hour must be between 0 and 23.")

    v_features: dict[str, float] = {}
    supplied = 0
    for index, column in enumerate(V_COLUMNS, start=1):
        key = column if column in payload else f"v{index}"
        if key in payload and payload[key] is not None:
            number = _as_number(payload[key], column)
            if abs(number) > PCA_ABS_LIMIT:
                raise ValidationError(
                    f"{column} is outside the plausible range "
                    f"(+/-{PCA_ABS_LIMIT:.0f})."
                )
            v_features[column] = number
            supplied += 1
        else:
            v_features[column] = 0.0

    transaction_id = payload.get("transaction_id")
    if transaction_id is not None:
        transaction_id = str(transaction_id).strip()
        if not transaction_id or len(transaction_id) > 64:
            raise ValidationError(
                "transaction_id must be 1-64 characters when supplied."
            )

    behavioural = payload.get("behavioural_signals")
    if behavioural is not None and not isinstance(behavioural, dict):
        raise ValidationError("behavioural_signals must be an object when supplied.")

    return {
        "amount": amount,
        "hour": hour,
        "v_features": v_features,
        "v_features_supplied": supplied,
        "transaction_id": transaction_id,
        "behavioural_signals": behavioural,
        "source": "api",
    }


def validate_list_query(args: Any, max_page_size: int = 200) -> dict[str, Any]:
    """Validate query parameters for the transaction listing."""
    limit_raw = args.get("limit", 50)
    offset_raw = args.get("offset", 0)
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ValidationError("limit and offset must be integers.") from None
    if limit < 1 or limit > max_page_size:
        raise ValidationError(f"limit must be between 1 and {max_page_size}.")
    if offset < 0:
        raise ValidationError("offset must be zero or greater.")

    risk_level = args.get("risk_level")
    if risk_level:
        risk_level = str(risk_level).upper()
        if risk_level not in VALID_RISK_LEVELS:
            raise ValidationError(
                f"risk_level must be one of {', '.join(sorted(VALID_RISK_LEVELS))}."
            )

    prediction = args.get("prediction")
    if prediction:
        prediction = str(prediction).lower()
        if prediction not in VALID_PREDICTIONS:
            raise ValidationError(
                f"prediction must be one of {', '.join(sorted(VALID_PREDICTIONS))}."
            )

    return {
        "limit": limit,
        "offset": offset,
        "risk_level": risk_level or None,
        "prediction": prediction or None,
        "start_date": args.get("start_date") or None,
        "end_date": args.get("end_date") or None,
    }
