"""Compute immutable outputs, then return short transaction-only registration.

The worker invokes persistence only inside the queue's token-fenced completion.
No callback commits, creates engines, computes models or publishes files.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import (
    DataQualityReport,
    Dataset,
    ForecastBatch,
    ForecastValue,
    InventoryConfiguration,
    ModelArtifact,
    Product,
    SimulationResult,
    SimulationScenario,
    TrainingRun,
    WeeklyDemand,
)
from backend.app.db.repository import DatasetConflictError, _validated_payload
from backend.app.services.application import bounded_path
from backend.app.services.configuration import phase3_config
from backend.app.services.errors import ServiceError
from ml.data.acquisition import canonical_json, download_official, sha256_file
from ml.pipelines.artifacts import verify_run
from ml.pipelines.ingestion import (
    ArtifactError,
    ingest_dataset,
    product_catalog,
    verify_dataset,
)


@dataclass(frozen=True)
class PreparedOperation:
    result: dict[str, Any]
    persist: Callable[[Session], None]


def identity(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _lock(session: Session, kind: str, key: str) -> None:
    digest = bytes.fromhex(identity({"kind": kind, "key": key}))
    session.execute(
        select(
            func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True))
        )
    )


def _same(existing: Any, values: dict) -> bool:
    if existing is None:
        return False
    if any(getattr(existing, key) != value for key, value in values.items()):
        raise ArtifactError("An immutable resource has different registered metadata")
    return True


def _records(frame: pd.DataFrame) -> list[dict]:
    # Preserve full floating-point precision; undefined prices become SQL NULL.
    def native(value):
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, list | tuple):
            return [native(item) for item in value]
        return None if pd.isna(value) else value

    return [
        {key: native(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _dates(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["week"] = pd.Timestamp(row["week"]).date()
    return rows


def _dataset(settings: Settings, payload: dict) -> PreparedOperation:
    source = payload["source"]
    if source == "existing":
        result = verify_dataset(
            bounded_path(settings.data_dir / "processed", payload["dataset_id"])
        )
        if result.manifest["dataset_id"] != payload["dataset_id"]:
            raise ArtifactError(
                "Requested dataset identity does not match its artifacts"
            )
    else:
        if source == "official":
            path = download_official(
                settings.data_dir / "raw",
                expected_archive_sha256=payload["expected_sha256"],
            ).workbook_path
        else:
            path = bounded_path(settings.data_dir / "raw", payload["input_file"])
            if sha256_file(path) != payload["expected_sha256"]:
                raise ArtifactError("Queued input changed after submission")
        result = ingest_dataset(path, settings.data_dir / "processed")
        if (
            source == "file"
            and result.manifest["source_sha256"] != payload["expected_sha256"]
        ):
            raise ArtifactError("Ingested source differs from the queued checksum")
    manifest, report, catalog = _validated_payload(
        result.manifest, result.report, product_catalog(result.dataset_dir)
    )
    dataset_id = manifest["dataset_id"]

    def persist(session):
        # Share the original Phase 1 import's advisory lock domain.
        lock_key = int.from_bytes(bytes.fromhex(dataset_id)[:8], "big", signed=True)
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        existing = session.get(Dataset, dataset_id)
        if existing is not None:
            quality = session.get(DataQualityReport, dataset_id)
            stored = sorted(
                [
                    {"stock_code": row.stock_code, "description": row.description}
                    for row in session.scalars(
                        select(Product).where(Product.dataset_id == dataset_id)
                    )
                ],
                key=lambda item: item["stock_code"],
            )
            if (
                existing.manifest != manifest
                or quality is None
                or quality.report != report
                or stored != catalog
            ):
                raise DatasetConflictError("Conflicting dataset metadata")
            return
        session.add(
            Dataset(
                dataset_id=dataset_id,
                source_sha256=manifest["source_sha256"],
                cleaning_version=manifest["cleaning_version"],
                status="ready",
                original_rows=manifest["original_rows"],
                cleaned_rows=manifest["cleaned_rows"],
                config=manifest["config"],
                artifacts=manifest["artifacts"],
                artifact_dir=manifest["artifact_dir"],
                manifest=manifest,
            )
        )
        session.flush()
        session.add(DataQualityReport(dataset_id=dataset_id, report=report))
        session.execute(
            insert(Product),
            [{"dataset_id": dataset_id, **product} for product in catalog],
        )

    return PreparedOperation(
        {
            "dataset_id": dataset_id,
            "cleaned_rows": manifest["cleaned_rows"],
            "products": len(catalog),
        },
        persist,
    )


def _training(settings: Settings, payload: dict) -> PreparedOperation:
    from ml.pipelines.modeling import TRAIN_REQUIRED, train_phase3

    if payload["mode"] == "existing":
        directory = bounded_path(settings.artifact_dir / "phase3", payload["run_id"])
    else:
        result = train_phase3(
            bounded_path(settings.data_dir / "processed", payload["dataset_id"]),
            settings.artifact_dir / "phase3",
            config=phase3_config(payload.get("config")),
            phase2_root=settings.data_dir / "phase2",
            ledger_root=settings.ledger_dir,
        )
        directory = result.run_dir
    manifest = verify_run(
        directory,
        required=TRAIN_REQUIRED,
        expected={"dataset_id": payload["dataset_id"], "state": "frozen_pretest"},
    )
    run_id = manifest["experiment_id"]
    if payload["mode"] == "existing" and run_id != payload["run_id"]:
        raise ArtifactError("Requested training identity does not match its artifacts")
    if directory.name != run_id:
        raise ArtifactError("Training run directory does not match its identity")
    plan = json.loads((directory / "plan.json").read_text())
    if (
        manifest["plan_sha256"] != sha256_file(directory / "plan.json")
        or plan["experiment_id"] != run_id
        or plan["dataset_id"] != payload["dataset_id"]
    ):
        raise ArtifactError("Training plan identity mismatch")
    metadata = json.loads((directory / "training_metadata.json").read_text())
    metrics = {
        scope: json.loads((directory / f"{scope}_metrics.json").read_text())
        for scope in ("selection", "calibration")
    }
    metrics["test"] = {
        "status": "available_only_in_completed_retrospective_forecast",
        "recomputed": False,
    }
    values = {
        "dataset_id": payload["dataset_id"],
        "config": manifest["config"],
        "metrics": metrics,
        "artifact_dir": directory.relative_to(settings.artifact_dir).as_posix(),
        "manifest_sha256": sha256_file(directory / "manifest.json"),
    }
    panel = pd.read_parquet(directory / "pretest_weekly.parquet")
    weekly = _dates(_records(panel))
    weekly = [
        {"run_id": run_id, "dataset_id": payload["dataset_id"], **row} for row in weekly
    ]
    models = []
    for family, digest in plan["model_hashes"].items():
        if manifest["artifacts"][f"models/{family}.joblib"]["sha256"] != digest:
            raise ArtifactError("Model hash disagrees with the frozen plan")
        models.append(
            {
                "model_id": identity(
                    {"run_id": run_id, "family": family, "sha256": digest}
                ),
                "run_id": run_id,
                "family": family,
                "artifact_key": f"{values['artifact_dir']}/models/{family}.joblib",
                "sha256": digest,
                "metadata_json": {
                    "candidate": plan["selected_candidates"][family],
                    "features": plan["features"],
                    "training_end": plan["refit_end"],
                    "training_timestamp_utc": metadata["training_timestamp_utc"],
                    "selected_before_test": family == plan["best_ml_family"],
                    "intended_use": "historical one-week demand decision support",
                },
            }
        )

    def persist(session):
        _lock(session, "training", run_id)
        if _same(session.get(TrainingRun, run_id), values):
            return
        session.add(TrainingRun(run_id=run_id, **values))
        session.flush()
        session.execute(insert(ModelArtifact), models)
        session.execute(
            insert(WeeklyDemand).execution_options(render_nulls=True), weekly
        )

    return PreparedOperation(
        {
            "run_id": run_id,
            "models": len(models),
            "weekly_rows": len(weekly),
            "selected_ml_family": plan["best_ml_family"],
        },
        persist,
    )


def _forecast(settings: Settings, engine, payload: dict) -> PreparedOperation:
    from backend.app.services.forecasting import prepare_forecast

    with Session(engine) as session:
        run = session.get(TrainingRun, payload["run_id"])
        if run is None:
            raise ValueError("Training run not registered")
        source_dir = bounded_path(settings.artifact_dir, run.artifact_dir)
        if sha256_file(source_dir / "manifest.json") != run.manifest_sha256:
            raise ArtifactError("Registered training artifacts have changed")
    forecast_id, directory, metadata, frame = prepare_forecast(
        settings, payload["run_id"], payload["scope"]
    )
    values = {
        "run_id": payload["run_id"],
        "scope": payload["scope"],
        "metadata_json": metadata,
        "artifact_dir": directory.relative_to(settings.artifact_dir).as_posix(),
    }
    rows = []
    for row in _dates(_records(frame)):
        rows.append(
            {
                "forecast_id": forecast_id,
                "stock_code": row["stock_code"],
                "week": row["week"],
                "method": row["model"],
                "point": row["prediction"],
                "lower": row["lower"],
                "upper": row["upper"],
                "actual": row.get("actual"),
                "nominal_coverage": row["nominal_coverage"],
                "uncertainty_label": row["uncertainty_label"],
            }
        )

    def persist(session):
        _lock(session, "forecast", forecast_id)
        if _same(session.get(ForecastBatch, forecast_id), values):
            return
        session.add(ForecastBatch(forecast_id=forecast_id, **values))
        session.flush()
        session.execute(
            insert(ForecastValue).execution_options(render_nulls=True), rows
        )

    return PreparedOperation(
        {"forecast_id": forecast_id, "scope": payload["scope"], "rows": len(rows)},
        persist,
    )


def _inventory(settings: Settings, engine, payload: dict) -> PreparedOperation:
    from backend.app.services.forecasting import prepare_forecast
    from ml.inventory.config import ScenarioConfig
    from ml.pipelines.inventory import run_inventory_scenario

    with Session(engine) as session:
        forecast = session.get(ForecastBatch, payload["forecast_id"])
        if forecast is None or forecast.scope != "retrospective":
            raise ValueError("Completed retrospective forecast required")
        run_id = forecast.run_id
        run = session.get(TrainingRun, run_id)
        if (
            run is None
            or sha256_file(
                bounded_path(settings.artifact_dir, run.artifact_dir) / "manifest.json"
            )
            != run.manifest_sha256
        ):
            raise ArtifactError("Registered training artifacts have changed")
        registered_forecast = (
            forecast.forecast_id,
            forecast.artifact_dir,
            forecast.metadata_json,
        )
    verified_id, verified_dir, verified_metadata, _ = prepare_forecast(
        settings, run_id, "retrospective"
    )
    if registered_forecast != (
        verified_id,
        verified_dir.relative_to(settings.artifact_dir).as_posix(),
        verified_metadata,
    ):
        raise ArtifactError(
            "Requested forecast does not match the frozen simulation inputs"
        )
    config = ScenarioConfig.from_dict(payload["config"])
    result = run_inventory_scenario(
        bounded_path(settings.artifact_dir / "phase3", run_id),
        config=config,
        output_root=settings.artifact_dir / "phase4",
        ledger_root=settings.ledger_dir,
    )
    inventory_run_id = result.manifest["run_id"]
    scenario_id = identity(
        {"forecast_id": payload["forecast_id"], "inventory_run_id": inventory_run_id}
    )
    configuration_id = identity(config.to_dict())
    config_values = {"config": config.to_dict(), "currency": config.currency}
    values = {
        "forecast_id": payload["forecast_id"],
        "configuration_id": configuration_id,
        "artifact_dir": result.run_dir.relative_to(settings.artifact_dir).as_posix(),
        "summary": result.summary,
        "manifest_sha256": sha256_file(result.run_dir / "manifest.json"),
    }
    rows = []
    core = {
        "policy",
        "stock_code",
        "week",
        "actual",
        "fulfilled_units",
        "lost_units",
        "ending_inventory",
    }
    for row in _dates(
        _records(pd.read_parquet(result.run_dir / "weekly_results.parquet"))
    ):
        rows.append(
            {
                "scenario_id": scenario_id,
                **{key: row[key] for key in core},
                "details": {
                    key: value for key, value in row.items() if key not in core
                },
            }
        )

    def persist(session):
        _lock(session, "configuration", configuration_id)
        if not _same(
            session.get(InventoryConfiguration, configuration_id), config_values
        ):
            session.add(
                InventoryConfiguration(
                    configuration_id=configuration_id, **config_values
                )
            )
            session.flush()
        _lock(session, "inventory", scenario_id)
        if _same(session.get(SimulationScenario, scenario_id), values):
            return
        session.add(SimulationScenario(scenario_id=scenario_id, **values))
        session.flush()
        session.execute(insert(SimulationResult), rows)

    return PreparedOperation(
        {
            "scenario_id": scenario_id,
            "inventory_run_id": inventory_run_id,
            "configuration_id": configuration_id,
            "scope": "retrospective_simulation",
            "weekly_rows": len(rows),
        },
        persist,
    )


def execute_operation(settings: Settings, engine, job: dict) -> PreparedOperation:
    """Dispatch validated durable payload; exceptions are redacted by the worker."""
    kind, payload = job["kind"], job["payload"]
    if kind == "dataset_import":
        return _dataset(settings, payload)
    if kind == "training":
        return _training(settings, payload)
    if kind == "forecasting":
        return _forecast(settings, engine, payload)
    if kind == "inventory":
        return _inventory(settings, engine, payload)
    raise ServiceError(422, "invalid_input", "Unsupported operation")
