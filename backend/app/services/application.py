"""Application queries and validated submission; calculations run in workers."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import (
    DataQualityReport,
    Dataset,
    ForecastBatch,
    ForecastValue,
    Job,
    ModelArtifact,
    Product,
    SimulationResult,
    SimulationScenario,
    TrainingRun,
    WeeklyDemand,
)
from backend.app.services.errors import ServiceError
from backend.app.services.jobs import IdempotencyConflict, enqueue_job
from ml.data.acquisition import sha256_file
from ml.pipelines.artifacts import verify_run

OFFICIAL_ARCHIVE_SHA256 = (
    "f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b"
)
RESOURCE_MODELS = {
    "datasets": Dataset,
    "products": Product,
    "training-runs": TrainingRun,
    "models": ModelArtifact,
    "forecasts": ForecastBatch,
    "inventory/scenarios": SimulationScenario,
    "jobs": Job,
}
PUBLIC_FIELDS = {
    Dataset: (
        "dataset_id",
        "source_sha256",
        "cleaning_version",
        "status",
        "original_rows",
        "cleaned_rows",
        "config",
        "created_at",
    ),
    Product: ("dataset_id", "stock_code", "description"),
    TrainingRun: (
        "run_id",
        "dataset_id",
        "config",
        "metrics",
        "manifest_sha256",
        "created_at",
    ),
    ModelArtifact: (
        "model_id",
        "run_id",
        "family",
        "sha256",
        "metadata_json",
        "created_at",
    ),
    ForecastBatch: ("forecast_id", "run_id", "scope", "metadata_json", "created_at"),
    SimulationScenario: (
        "scenario_id",
        "forecast_id",
        "configuration_id",
        "summary",
        "created_at",
    ),
    Job: (
        "job_id",
        "kind",
        "status",
        "attempts",
        "max_attempts",
        "available_at",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "result",
        "error_code",
    ),
}


def public_row(row: Any) -> dict[str, Any]:
    return {name: getattr(row, name) for name in PUBLIC_FIELDS[type(row)]}


def bounded_path(root: Path, relative: str) -> Path:
    """Resolve symlinks as well as traversal before any local artifact access."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ServiceError(
            422, "invalid_path", "The file must be under its configured data root"
        )
    return path


def _csv(rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            # Prevent spreadsheet formula execution in untrusted product text.
            writer.writerow(
                {
                    key: (
                        "'" + value
                        if isinstance(value, str)
                        and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                        else value
                    )
                    for key, value in row.items()
                }
            )
    return stream.getvalue().encode("utf-8")


class ApplicationService:
    def __init__(self, settings: Settings, engine: Any):
        self.settings, self.engine = settings, engine

    def _require(self, session: Session, model: Any, identifier: Any) -> Any:
        row = session.get(model, identifier)
        if row is None:
            raise ServiceError(
                404, "not_found", "The requested resource does not exist"
            )
        return row

    def submit(self, kind: str, payload: dict, *, idempotency_key=None) -> dict:
        if self.engine is None:
            raise ServiceError(
                503, "database_unavailable", "The database is unavailable"
            )
        # Validate again for CLI/direct callers; importing here avoids route coupling.
        from backend.app.schemas.requests import (
            DatasetImportRequest,
            ForecastRequest,
            InventoryScenarioRequest,
            TrainingRunRequest,
        )

        schemas = {
            "dataset_import": DatasetImportRequest,
            "training": TrainingRunRequest,
            "forecasting": ForecastRequest,
            "inventory": InventoryScenarioRequest,
        }
        if kind not in schemas:
            raise ServiceError(422, "invalid_input", "Unsupported job kind")
        payload = schemas[kind].model_validate(payload).model_dump(exclude_none=True)
        with Session(self.engine) as session:
            if kind == "dataset_import":
                if payload["source"] == "file":
                    path = bounded_path(
                        self.settings.data_dir / "raw", payload["input_file"]
                    )
                    if not path.is_file():
                        raise ServiceError(
                            422,
                            "source_missing",
                            "The input file is unavailable under the raw-data root",
                        )
                    digest = sha256_file(path)
                    if payload.get("expected_sha256", digest) != digest:
                        raise ServiceError(
                            422, "source_checksum", "The source checksum does not match"
                        )
                    payload["expected_sha256"] = digest
                elif payload["source"] == "official":
                    if (
                        payload.get("expected_sha256", OFFICIAL_ARCHIVE_SHA256)
                        != OFFICIAL_ARCHIVE_SHA256
                    ):
                        raise ServiceError(
                            422,
                            "source_checksum",
                            "Official acquisition uses the documented archive checksum",
                        )
                    payload["expected_sha256"] = OFFICIAL_ARCHIVE_SHA256
            elif kind == "training":
                self._require(session, Dataset, payload["dataset_id"])
            elif kind == "forecasting":
                self._require(session, TrainingRun, payload["run_id"])
            else:
                forecast = self._require(session, ForecastBatch, payload["forecast_id"])
                if forecast.scope != "retrospective":
                    raise ServiceError(
                        422,
                        "forecast_scope",
                        "Inventory simulation requires completed retrospective forecasts",
                    )
        try:
            return enqueue_job(
                self.engine,
                kind,
                payload,
                idempotency_key=idempotency_key,
                max_attempts=self.settings.max_attempts,
            )
        except IdempotencyConflict as exc:
            raise ServiceError(
                409,
                "idempotency_conflict",
                "This idempotency key was used for a different request",
            ) from exc

    def list_resources(self, kind, *, limit, offset, filters=None):
        model = RESOURCE_MODELS[kind]
        query = select(model)
        filters = filters or {}
        if model in (ForecastBatch, ModelArtifact) and filters.get("dataset_id"):
            query = query.join(TrainingRun, model.run_id == TrainingRun.run_id).where(
                TrainingRun.dataset_id == filters["dataset_id"]
            )
        for name, value in filters.items():
            if value is not None and hasattr(model, name):
                query = query.where(getattr(model, name) == value)
        order = list(model.__table__.primary_key.columns)
        if hasattr(model, "created_at"):
            order = [model.created_at.desc(), *order]
        with Session(self.engine) as session:
            return [
                public_row(row)
                for row in session.scalars(
                    query.order_by(*order).limit(limit).offset(offset)
                )
            ]

    def get_resource(self, kind, identifier, *, dataset_id=None):
        with Session(self.engine) as session:
            key = (dataset_id, identifier) if kind == "products" else identifier
            return public_row(self._require(session, RESOURCE_MODELS[kind], key))

    def quality(self, dataset_id):
        with Session(self.engine) as session:
            return self._require(session, DataQualityReport, dataset_id).report

    def history(self, stock_code, *, dataset_id, run_id=None, limit=1000, offset=0):
        with Session(self.engine) as session:
            self._require(session, Product, (dataset_id, stock_code))
            if run_id is None:
                run_id = session.scalar(
                    select(TrainingRun.run_id)
                    .where(TrainingRun.dataset_id == dataset_id)
                    .order_by(TrainingRun.created_at.desc(), TrainingRun.run_id)
                    .limit(1)
                )
            if run_id is None:
                return {
                    "dataset_id": dataset_id,
                    "run_id": None,
                    "stock_code": stock_code,
                    "scope": "pretest_training_facts",
                    "total": 0,
                    "rows": [],
                }
            run = self._require(session, TrainingRun, run_id)
            if run.dataset_id != dataset_id:
                raise ServiceError(
                    404, "not_found", "The training run does not belong to this dataset"
                )
            query = select(WeeklyDemand).where(
                WeeklyDemand.run_id == run_id, WeeklyDemand.stock_code == stock_code
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = [
                {c.name: getattr(row, c.name) for c in WeeklyDemand.__table__.columns}
                for row in session.scalars(
                    query.order_by(WeeklyDemand.week).limit(limit).offset(offset)
                )
            ]
            return {
                "dataset_id": dataset_id,
                "run_id": run_id,
                "stock_code": stock_code,
                "scope": "pretest_training_facts",
                "total": total,
                "rows": rows,
            }

    def training_metrics(self, run_id):
        return self.get_resource("training-runs", run_id)["metrics"]

    def forecast_rows(
        self, forecast_id, *, stock_code=None, method=None, limit=1000, offset=0
    ):
        with Session(self.engine) as session:
            self._require(session, ForecastBatch, forecast_id)
            query = select(ForecastValue).where(
                ForecastValue.forecast_id == forecast_id
            )
            if stock_code is not None:
                query = query.where(ForecastValue.stock_code == stock_code)
            if method is not None:
                query = query.where(ForecastValue.method == method)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = [
                {c.name: getattr(row, c.name) for c in ForecastValue.__table__.columns}
                for row in session.scalars(
                    query.order_by(
                        ForecastValue.week,
                        ForecastValue.stock_code,
                        ForecastValue.method,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ]
            return {"forecast_id": forecast_id, "total": total, "rows": rows}

    def scenario_results(self, scenario_id, *, limit=1000, offset=0):
        with Session(self.engine) as session:
            self._require(session, SimulationScenario, scenario_id)
            query = select(SimulationResult).where(
                SimulationResult.scenario_id == scenario_id
            )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = [
                {
                    **row.details,
                    **{
                        c.name: getattr(row, c.name)
                        for c in SimulationResult.__table__.columns
                        if c.name != "details"
                    },
                }
                for row in session.scalars(
                    query.order_by(
                        SimulationResult.week,
                        SimulationResult.policy,
                        SimulationResult.stock_code,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ]
            return {
                "scenario_id": scenario_id,
                "scope": "retrospective_simulation",
                "total": total,
                "rows": rows,
            }

    def export_forecasts(self, forecast_id):
        # Full exports are intentionally separate from bounded interactive reads.
        with Session(self.engine) as session:
            self._require(session, ForecastBatch, forecast_id)
            rows = [
                {c.name: getattr(row, c.name) for c in ForecastValue.__table__.columns}
                for row in session.scalars(
                    select(ForecastValue)
                    .where(ForecastValue.forecast_id == forecast_id)
                    .order_by(
                        ForecastValue.week,
                        ForecastValue.stock_code,
                        ForecastValue.method,
                    )
                )
            ]
        return _csv(rows), f"forecasts-{forecast_id[:12]}.csv"

    def export_scenario(self, scenario_id, *, kind="recommendations"):
        if kind not in {"recommendations", "summary", "weekly_results"}:
            raise ServiceError(422, "invalid_export", "Unsupported scenario export")
        with Session(self.engine) as session:
            scenario = self._require(session, SimulationScenario, scenario_id)
            directory = bounded_path(self.settings.artifact_dir, scenario.artifact_dir)
            expected = scenario.manifest_sha256
        if sha256_file(directory / "manifest.json") != expected:
            raise ServiceError(
                409, "artifact_integrity", "The scenario artifact has changed"
            )
        verify_run(directory, required={f"exports/{kind}.csv"})
        # Typed source rows preserve negative numeric outcomes while text is escaped.
        if kind == "summary":
            rows = json.loads((directory / "summary.json").read_text())["policies"]
        else:
            import pandas as pd

            from backend.app.services.operations import _records

            rows = _records(pd.read_parquet(directory / f"{kind}.parquet"))
        return _csv(rows), f"{kind}-{scenario_id[:12]}.csv"
