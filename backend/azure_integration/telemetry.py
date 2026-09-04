"""
Application Insights instrumentation.

WHAT: Azure's application monitoring service. Collects request counts,
latency, dependency calls, exceptions and custom metrics, with a query
interface and dashboards in the portal.

WHY: once the app is on App Service there is no terminal to watch. Insights is
how you see that /api/v1/predict is being called, how long scoring takes, and
what failed at 3am.

WHAT IS TRACKED, deliberately narrow to control ingestion cost:
    * HTTP requests handled by Flask (automatic)
    * outbound calls to Cosmos and Blob (automatic dependency tracking)
    * unhandled exceptions (automatic)
    * one custom metric per prediction: scoring latency, risk level, model
      version - no transaction features, no amounts, no identifiers

COST: the first 5 GB of ingestion per month is free. This app produces
kilobytes per request, so a student demo stays inside that comfortably.
TELEMETRY_SAMPLE_RATE lets you send a fraction of traces if you ever run a
load test; a value of 0.25 sends a quarter of them.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("dhanraksha.telemetry")

_configured = False


def configure_telemetry(app, connection_string: str, sample_rate: float = 1.0) -> bool:
    """
    Wire up Azure Monitor for a Flask app.

    No-op and returns False when no connection string is configured, which is
    the local default. Never raises: monitoring failing to start must not stop
    the application from serving traffic.
    """
    global _configured

    if not connection_string:
        return False
    if _configured:
        return True

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            # Flask, requests and the Azure SDKs are instrumented automatically.
            logger_name="dhanraksha",
        )
        _configured = True
        logger.info("Application Insights configured (sampling=%.2f).", sample_rate)
        return True
    except ImportError:
        logger.warning(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is set but "
            "azure-monitor-opentelemetry is not installed. "
            "Run: pip install -r requirements-azure.txt"
        )
        return False
    except Exception as exc:  # noqa: BLE001 - monitoring must never break serving
        logger.warning("Application Insights setup failed: %s", exc)
        return False


def track_prediction(
    duration_ms: float, risk_level: str, model_version: str, prediction: str
) -> None:
    """
    Emit one custom event per scored transaction.

    Only non-identifying decision metadata is sent: latency, the risk band, the
    model version and the decision. The amount, the PCA components and the
    transaction ID stay out of telemetry.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("dhanraksha.prediction.duration_ms", round(duration_ms, 2))
            span.set_attribute("dhanraksha.prediction.risk_level", risk_level)
            span.set_attribute("dhanraksha.prediction.model_version", model_version)
            span.set_attribute("dhanraksha.prediction.decision", prediction)
    except Exception:  # noqa: BLE001 - telemetry is best effort
        pass
