"""
DhanRaksha 2.0 - application factory.

Run locally:
    python -m backend.app

The factory wires a small service container onto app.extensions["dhanraksha"].
Routes reach services only through that container, so swapping the SQLite
repositories for Cosmos DB repositories in Milestone 2 is a change in exactly
one function.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from backend.auth.entra import register_auth_handlers
from backend.azure_integration.telemetry import configure_telemetry
from backend.config import BASE_DIR, Config, load_config
from backend.errors import register_error_handlers
from backend.repositories.base import CaseRepository, TransactionRepository
from backend.repositories.database import Database
from backend.repositories.sqlite_repository import (
    SqliteCaseRepository,
    SqliteTransactionRepository,
)
from backend.routes import analytics, cases, prediction, system, transactions
from backend.services.case_service import CaseService
from backend.services.fraud_service import FraudService
from backend.services.model_service import ModelService
from backend.services.risk_engine import RiskEngine
from backend.services.transaction_service import TransactionService

logger = logging.getLogger("dhanraksha.app")

API_PREFIX = "/api/v1"
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@dataclass
class ServiceContainer:
    config: Config
    database: object
    model_service: ModelService
    risk_engine: RiskEngine
    transaction_service: TransactionService
    case_service: CaseService
    fraud_service: FraudService


def build_repositories(
    config: Config,
) -> tuple[object, TransactionRepository, CaseRepository]:
    """
    Select the storage implementation.

    This is the entire Milestone 2 database migration: one branch. Services,
    routes and tests are identical either way, because both implementations
    satisfy the same abstract interfaces from repositories/base.py.
    """
    if config.uses_cosmos:
        from backend.repositories.cosmos_repository import (
            CosmosCaseRepository,
            CosmosConnection,
            CosmosTransactionRepository,
        )

        connection = CosmosConnection(
            endpoint=config.cosmos_endpoint,
            key=config.cosmos_key,
            database_name=config.cosmos_database,
            transactions_container=config.cosmos_transactions_container,
            cases_container=config.cosmos_cases_container,
        )
        logger.info("Storage backend: Azure Cosmos DB (%s)", config.cosmos_database)
        return (
            connection,
            CosmosTransactionRepository(connection),
            CosmosCaseRepository(connection),
        )

    database = Database(config.database_path)
    logger.info("Storage backend: SQLite (%s)", config.database_path)
    return (
        database,
        SqliteTransactionRepository(database),
        SqliteCaseRepository(database),
    )


def build_container(config: Config) -> ServiceContainer:
    database, transaction_repository, case_repository = build_repositories(config)

    # Optionally pull model artifacts from Blob Storage before the model loads,
    # so a retrained model can be published without redeploying the app.
    if config.load_artifacts_from_blob:
        from backend.azure_integration.blob_storage import download_artifacts

        if download_artifacts(
            config.storage_connection_string,
            config.blob_artifacts_container,
            config.artifact_dir,
        ):
            logger.info("Model artifacts downloaded from Blob Storage.")
        else:
            logger.warning(
                "Blob artifact download incomplete; falling back to artifacts "
                "shipped in the image."
            )

    model_service = ModelService(
        model_path=config.model_path,
        pipeline_path=config.pipeline_path,
        metadata_path=config.metadata_path,
    )
    risk_engine = RiskEngine(
        high_threshold=config.risk_high_threshold,
        medium_threshold=config.risk_medium_threshold,
        reference=model_service.risk_reference,
    )
    transaction_service = TransactionService(
        transaction_repository, max_page_size=config.max_page_size
    )
    case_service = CaseService(
        case_repository, transaction_repository, max_page_size=config.max_page_size
    )
    # Async enrichment queue. Absent locally, so predictions stay synchronous.
    queue_client = None
    if config.async_processing_enabled:
        from backend.azure_integration.queue_client import TransactionQueueClient

        queue_client = TransactionQueueClient(
            config.storage_connection_string, config.async_queue_name
        )
        logger.info("Async processing enabled via queue '%s'.", config.async_queue_name)

    fraud_service = FraudService(
        model_service=model_service,
        risk_engine=risk_engine,
        transaction_service=transaction_service,
        case_service=case_service,
        fraud_threshold=config.fraud_threshold,
        auto_create_cases=config.auto_create_cases,
        queue_client=queue_client,
    )

    return ServiceContainer(
        config=config,
        database=database,
        model_service=model_service,
        risk_engine=risk_engine,
        transaction_service=transaction_service,
        case_service=case_service,
        fraud_service=fraud_service,
    )


def create_app(config: Config | None = None) -> Flask:
    config = config or load_config()

    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    for problem in config.validate():
        logger.error("Configuration problem: %s", problem)

    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    app.secret_key = config.secret_key
    CORS(app, resources={r"/api/*": {"origins": config.cors_origins}})

    app.extensions["dhanraksha"] = build_container(config)

    # Application Insights. No-op when no connection string is configured.
    configure_telemetry(
        app, config.appinsights_connection_string, config.telemetry_sample_rate
    )

    for blueprint in (
        prediction.bp,
        transactions.bp,
        analytics.bp,
        cases.bp,
        system.bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    register_auth_handlers(app)
    register_error_handlers(app)

    # ---------------------------------------------------------- static site
    # The frontend is served by Flask so the whole stack is one container and
    # one origin. Opening frontend/index.html from disk still works too, since
    # the JS falls back to an absolute API base.
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(FRONTEND_DIR, filename)

    @app.get("/api")
    def api_root():
        return jsonify(
            {
                "service": "DhanRaksha 2.0",
                "api_version": "v1",
                "endpoints": [
                    f"{API_PREFIX}/health",
                    f"{API_PREFIX}/model-info",
                    f"{API_PREFIX}/predict",
                    f"{API_PREFIX}/transactions",
                    f"{API_PREFIX}/transactions/<id>",
                    f"{API_PREFIX}/analytics",
                    f"{API_PREFIX}/cases",
                    f"{API_PREFIX}/cases/<id>",
                    f"{API_PREFIX}/sample-transactions",
                ],
            }
        )

    return app


app = create_app()


if __name__ == "__main__":
    configuration = app.extensions["dhanraksha"].config
    print(f"DhanRaksha 2.0 on http://localhost:{configuration.port}")
    print(f"API base: http://localhost:{configuration.port}{API_PREFIX}")
    app.run(host=configuration.host, port=configuration.port, debug=configuration.debug)
