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

from backend.config import BASE_DIR, Config, load_config
from backend.errors import register_error_handlers
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

API_PREFIX = "/api/v1"
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@dataclass
class ServiceContainer:
    config: Config
    database: Database
    model_service: ModelService
    risk_engine: RiskEngine
    transaction_service: TransactionService
    case_service: CaseService
    fraud_service: FraudService


def build_container(config: Config) -> ServiceContainer:
    database = Database(config.database_path)

    transaction_repository = SqliteTransactionRepository(database)
    case_repository = SqliteCaseRepository(database)

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
    fraud_service = FraudService(
        model_service=model_service,
        risk_engine=risk_engine,
        transaction_service=transaction_service,
        case_service=case_service,
        fraud_threshold=config.fraud_threshold,
        auto_create_cases=config.auto_create_cases,
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

    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    app.secret_key = config.secret_key
    CORS(app, resources={r"/api/*": {"origins": config.cors_origins}})

    app.extensions["dhanraksha"] = build_container(config)

    for blueprint in (
        prediction.bp,
        transactions.bp,
        analytics.bp,
        cases.bp,
        system.bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

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
