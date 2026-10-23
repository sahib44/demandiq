"""Read-only, verified dashboard projections and stateless inventory previews.

These projections never train, deserialize a model, evaluate the forecasting
test, publish an artifact, or change PostgreSQL. The preview reuses Phase 4's
planner; its separately labeled normal approximation is decision support.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import (
    Dataset,
    ForecastBatch,
    ForecastValue,
    InventoryConfiguration,
    Product,
    SimulationResult,
    SimulationScenario,
    TrainingRun,
)
from backend.app.schemas.dashboard import InventoryPreviewRequest
from backend.app.services.application import _csv, bounded_path, public_row
from backend.app.services.errors import ServiceError
from backend.app.services.forecasting import _source, _validated_frame
from ml.data.acquisition import canonical_json, sha256_file
from ml.features.weekly import PANEL_COLUMNS, feature_columns, generate_features
from ml.inventory.planning import recommend_inventory
from ml.models.config import Phase3Config
from ml.pipelines.artifacts import verify_run
from ml.pipelines.ingestion import ArtifactError

MAX_PRODUCTS = 500
MAX_ROWS = 100_000
MAX_HISTORY_WEEKS = 1040
_TRAIN_FILES = {
    "importance.json",
    "selection_metrics.json",
    "calibration_metrics.json",
    "training_metadata.json",
    "calibration_predictions.parquet",
}
_FORECAST_COLUMNS = (
    "stock_code",
    "week",
    "method",
    "point",
    "lower",
    "upper",
    "actual",
    "nominal_coverage",
    "uncertainty_label",
)
_PUBLIC_TRAIN_METADATA = (
    "training_timestamp_utc",
    "git_commit",
    "final_training_rows",
    "final_training_end",
    "uncertainty_method",
    "tracking",
)


def _guard(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ServiceError:
            raise
        except (
            ArtifactError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as exc:
            raise ServiceError(
                409,
                "artifact_integrity",
                "The registered dashboard artifacts are incomplete or inconsistent",
            ) from exc

    return guarded


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _identity(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _json(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple | np.ndarray):
        return [_json(item) for item in value]
    if isinstance(value, pd.Timestamp | datetime | date):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return None
        raise ArtifactError("Nonfinite dashboard value")
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    if len(frame) > MAX_ROWS:
        raise ServiceError(
            422,
            "projection_limit",
            "This artifact exceeds the bounded dashboard row limit",
        )
    return _json(frame.to_dict(orient="records"))


def _required(session, model, identifier):
    row = session.get(model, identifier)
    if row is None:
        raise ServiceError(
            404, "not_found", "The requested dashboard resource does not exist"
        )
    return row


def _forecast_ref(row):
    if row is None:
        return None
    fields = (
        "selected_ml_family",
        "forecast_start",
        "forecast_end",
        "product_count",
        "row_count",
        "horizon_weeks",
        "origin_convention",
        "actuals_available",
    )
    return {
        "forecast_id": row.forecast_id,
        "run_id": row.run_id,
        "scope": row.scope,
        "created_at": row.created_at,
        "metadata_json": {key: row.metadata_json.get(key) for key in fields},
    }


def _next_features(panel: pd.DataFrame, config: Phase3Config, stock_code: str):
    """Inspect causal features without importing model/native training runtimes."""
    history = panel.loc[panel.stock_code.eq(stock_code)].sort_values("week").copy()
    weeks = pd.date_range(
        config.timeline.start_week, config.timeline.validation_end, freq="W-MON"
    )
    if len(weeks) > MAX_HISTORY_WEEKS or history.week.tolist() != list(weeks):
        raise ArtifactError("Pre-test history has an invalid date grid")
    template = history.tail(1).copy()
    template["week"] = config.timeline.test_start
    for name in PANEL_COLUMNS[2:]:
        template[name] = np.nan if name == "average_price" else 0
    expanded = pd.concat([history, template], ignore_index=True)
    features = generate_features(
        expanded, seasonal_indicators=config.timeline.seasonal_indicators
    )
    row = features.iloc[-1]
    names = feature_columns(config.timeline.seasonal_indicators)
    return history, {
        "week": config.timeline.test_start.date().isoformat(),
        "scope": "causal_first_post_refit_origin",
        "history_end": config.timeline.validation_end,
        "values": {name: _json(row[name]) for name in names},
        "label": "Every historical lag/window ends before this forecast week; no current target is included.",
    }


def normal_preview(forecast: float, sigma: float, available: int) -> dict[str, float]:
    """Moments of max(0, Normal(forecast,sigma)), never calibrated guarantees."""
    if not all(
        math.isfinite(value) and value >= 0 for value in (forecast, sigma, available)
    ):
        raise ValueError("Preview inputs must be finite and nonnegative")
    if sigma == 0:
        lost = max(0.0, forecast - available)
        fulfilled = min(float(available), forecast)
        return {
            "stockout_probability": float(forecast > available),
            "expected_demand": forecast,
            "expected_lost_units": lost,
            "expected_fulfilled_units": fulfilled,
            "expected_ending_inventory": available - fulfilled,
        }
    standard = NormalDist()

    # erfc keeps upper-tail probabilities accurate without 1-CDF cancellation.
    def tail(z):
        return 0.5 * math.erfc(z / math.sqrt(2.0))

    location = forecast / sigma
    expected = forecast * standard.cdf(location) + sigma * standard.pdf(location)
    z = (available - forecast) / sigma
    probability = tail(z)
    lost = max(0.0, sigma * standard.pdf(z) + (forecast - available) * probability)
    fulfilled = min(float(available), max(0.0, expected - lost))
    return {
        "stockout_probability": probability,
        "expected_demand": expected,
        "expected_lost_units": lost,
        "expected_fulfilled_units": fulfilled,
        "expected_ending_inventory": max(0.0, available - fulfilled),
    }


class DashboardService:
    def __init__(self, settings: Settings, engine):
        self.settings, self.engine = settings, engine

    def _training(self, session, run_id):
        run = _required(session, TrainingRun, run_id)
        directory, manifest, plan, products = _source(self.settings, run_id)
        for name in _TRAIN_FILES:
            bounded_path(directory, name)
        if (
            len(products) > MAX_PRODUCTS
            or bounded_path(self.settings.artifact_dir, run.artifact_dir) != directory
            or sha256_file(directory / "manifest.json") != run.manifest_sha256
            or manifest["dataset_id"] != run.dataset_id
            or manifest["config"] != run.config
            or not _TRAIN_FILES.issubset(manifest["artifacts"])
        ):
            raise ArtifactError("Registered training identity changed")
        cohort = _read(directory / "cohort.json")
        if len(cohort) != len(products):
            raise ArtifactError("Invalid frozen cohort")
        return run, directory, manifest, plan, products, cohort

    def _forecast(self, session, forecast_id):
        row = _required(session, ForecastBatch, forecast_id)
        run, source, training, plan, products, cohort = self._training(
            session, row.run_id
        )
        directory = bounded_path(self.settings.artifact_dir, row.artifact_dir)
        for name in ("manifest.json", "metadata.json", "forecasts.parquet"):
            bounded_path(directory, name)
        manifest = verify_run(
            directory,
            required={"metadata.json", "forecasts.parquet"},
            expected={
                "forecast_id": forecast_id,
                "run_id": run.run_id,
                "scope": row.scope,
                "state": "complete",
            },
        )
        identity = {
            key: value
            for key, value in manifest.items()
            if key not in {"forecast_id", "state", "artifacts"}
        }
        metadata = _read(directory / "metadata.json")
        if (
            _identity(identity) != forecast_id
            or metadata != row.metadata_json
            or metadata["dataset_id"] != run.dataset_id
            or metadata["source"]["training_manifest_sha256"] != run.manifest_sha256
            or metadata["source"]["plan_sha256"] != training["plan_sha256"]
            or manifest["source"] != metadata["source"]
        ):
            raise ArtifactError("Registered forecast lineage changed")
        if row.scope == "retrospective":
            from ml.pipelines.inventory import load_frozen_inputs

            completed_plan, lineage, evaluation = load_frozen_inputs(
                source, self.settings.ledger_dir
            )
            if not evaluation.resolve().is_relative_to(self.settings.artifact_dir):
                raise ArtifactError(
                    "Completed evaluation is outside its configured artifact root"
                )
            if completed_plan != plan or any(
                metadata["source"].get(key) != value for key, value in lineage.items()
            ):
                raise ArtifactError("Forecast ledger lineage changed")
            point, uncertainty = _read(evaluation / "metrics.json"), _read(
                evaluation / "interval_metrics.json"
            )
            if (
                point.get("evaluation_scope") != "test"
                or uncertainty.get("scope") != "test"
                or metadata.get("evaluation_metrics")
                != {"point": point, "uncertainty": uncertainty}
            ):
                raise ArtifactError("Forecast test metrics changed")
        frame = _validated_frame(
            pd.read_parquet(directory / "forecasts.parquet"), plan, row.scope, products
        )
        if len(frame) > MAX_ROWS:
            raise ServiceError(
                422,
                "projection_limit",
                "Forecast batch exceeds the bounded dashboard row limit",
            )
        renamed = frame.rename(columns={"model": "method", "prediction": "point"})
        file_rows = _records(renamed.loc[:, list(_FORECAST_COLUMNS)])
        db_rows = [
            {key: _json(getattr(value, key)) for key in _FORECAST_COLUMNS}
            for value in session.scalars(
                select(ForecastValue)
                .where(ForecastValue.forecast_id == forecast_id)
                .order_by(
                    ForecastValue.week, ForecastValue.stock_code, ForecastValue.method
                )
                .limit(MAX_ROWS + 1)
            )
        ]
        if db_rows != file_rows:
            raise ArtifactError("Persisted forecasts disagree with verified artifacts")
        return row, run, source, plan, cohort, frame

    def _scenario(self, session, scenario_id):
        scenario = _required(session, SimulationScenario, scenario_id)
        forecast, run, _, _, _, _ = self._forecast(session, scenario.forecast_id)
        configuration = _required(
            session, InventoryConfiguration, scenario.configuration_id
        )
        directory = bounded_path(self.settings.artifact_dir, scenario.artifact_dir)
        if sha256_file(directory / "manifest.json") != scenario.manifest_sha256:
            raise ArtifactError("Registered simulation manifest changed")
        required = {
            "config.json",
            "summary.json",
            "lineage.json",
            "weekly_results.parquet",
            "recommendations.parquet",
            "product_inputs.json",
        }
        for name in required:
            bounded_path(directory, name)
        manifest = verify_run(
            directory, required=required, expected={"state": "complete"}
        )
        config, summary, lineage = (
            _read(directory / "config.json"),
            _read(directory / "summary.json"),
            _read(directory / "lineage.json"),
        )
        if (
            forecast.scope != "retrospective"
            or config != configuration.config
            or summary != scenario.summary
            or _identity(config) != scenario.configuration_id
            or config["currency"] != configuration.currency
            or _identity(
                {
                    "forecast_id": scenario.forecast_id,
                    "inventory_run_id": manifest["run_id"],
                }
            )
            != scenario_id
            or manifest["source"] != lineage
            or lineage["experiment_id"] != run.run_id
            or any(
                forecast.metadata_json["source"].get(key) != value
                for key, value in lineage.items()
            )
        ):
            raise ArtifactError("Registered simulation lineage changed")
        frame = pd.read_parquet(directory / "weekly_results.parquet")
        records = _records(frame)
        persisted = []
        for row in session.scalars(
            select(SimulationResult)
            .where(SimulationResult.scenario_id == scenario_id)
            .order_by(
                SimulationResult.policy,
                SimulationResult.stock_code,
                SimulationResult.week,
            )
            .limit(MAX_ROWS + 1)
        ):
            persisted.append(
                _json(
                    {
                        **row.details,
                        **{
                            name: getattr(row, name)
                            for name in (
                                "policy",
                                "stock_code",
                                "week",
                                "actual",
                                "fulfilled_units",
                                "lost_units",
                                "ending_inventory",
                            )
                        },
                    }
                )
            )
        if (
            sorted(
                records,
                key=lambda item: (item["policy"], item["stock_code"], item["week"]),
            )
            != persisted
        ):
            raise ArtifactError("Persisted simulation facts disagree with artifacts")
        return scenario, directory, config, summary, frame

    @_guard
    def context(self, *, dataset_id=None, run_id=None):
        with Session(self.engine) as session:
            if run_id is not None:
                run = _required(session, TrainingRun, run_id)
                if dataset_id is not None and run.dataset_id != dataset_id:
                    raise ServiceError(
                        404, "not_found", "The run does not belong to this dataset"
                    )
                dataset_id = run.dataset_id
            else:
                run = None
            dataset = (
                _required(session, Dataset, dataset_id)
                if dataset_id
                else session.scalar(
                    select(Dataset)
                    .order_by(Dataset.created_at.desc(), Dataset.dataset_id)
                    .limit(1)
                )
            )
            if dataset is not None and run is None:
                run = session.scalar(
                    select(TrainingRun)
                    .where(TrainingRun.dataset_id == dataset.dataset_id)
                    .order_by(TrainingRun.created_at.desc(), TrainingRun.run_id)
                    .limit(1)
                )
            result = {
                "dataset": public_row(dataset) if dataset else None,
                "run": None,
                "one_week_forecast": None,
                "retrospective_forecast": None,
                "scenario": None,
                "products": [],
                "overview": None,
                "scope": {
                    "forecast": "historical_first_post_refit_origin",
                    "inventory": "retrospective_simulated_estimates_under_illustrative_assumptions",
                    "stock": "No live company inventory is available",
                },
            }
            if run is None:
                return result
            _, _, _, plan, _, cohort = self._training(session, run.run_id)
            descriptions = dict(
                session.execute(
                    select(Product.stock_code, Product.description).where(
                        Product.dataset_id == run.dataset_id
                    )
                ).all()
            )
            result["run"] = {
                "run_id": run.run_id,
                "dataset_id": run.dataset_id,
                "created_at": run.created_at,
                "selected_ml_family": plan["best_ml_family"],
            }
            result["products"] = [
                {**item, "description": descriptions.get(item["stock_code"])}
                for item in cohort
            ]
            batches = {}
            for scope in ("one_week", "retrospective"):
                batch = session.scalar(
                    select(ForecastBatch)
                    .where(
                        ForecastBatch.run_id == run.run_id, ForecastBatch.scope == scope
                    )
                    .order_by(
                        ForecastBatch.created_at.desc(), ForecastBatch.forecast_id
                    )
                    .limit(1)
                )
                if batch:
                    self._forecast(session, batch.forecast_id)
                    batches[scope] = batch
                result[f"{scope}_forecast"] = _forecast_ref(batch)
            overview = {
                "forecast_units": None,
                "forecast_week": None,
                "forecast_scope": None,
                "selected_ml_family": plan["best_ml_family"],
                "scenario_policy": None,
                "comparison": None,
                "products_with_simulated_stockouts": None,
                "risk_products": [],
            }
            selected = batches.get("one_week") or batches.get("retrospective")
            if selected:
                _, _, _, _, _, frame = self._forecast(session, selected.forecast_id)
                first = frame.loc[
                    frame.week.eq(frame.week.min())
                    & frame.model.eq(plan["best_ml_family"])
                ]
                overview.update(
                    forecast_units=float(first.prediction.sum()),
                    forecast_week=first.week.min().date().isoformat(),
                    forecast_scope=selected.scope,
                )
            if "retrospective" in batches:
                scenario = session.scalar(
                    select(SimulationScenario)
                    .where(
                        SimulationScenario.forecast_id
                        == batches["retrospective"].forecast_id
                    )
                    .order_by(
                        SimulationScenario.created_at.desc(),
                        SimulationScenario.scenario_id,
                    )
                    .limit(1)
                )
                if scenario:
                    self._scenario(session, scenario.scenario_id)
                    summary = scenario.summary
                    risk = self._risk_products(summary)
                    overview.update(
                        scenario_policy=next(
                            item
                            for item in summary["policies"]
                            if item["policy"] == "ml_safety_stock"
                        ),
                        comparison=next(
                            (
                                item
                                for item in summary["comparisons"]
                                if item["baseline_policy"]
                                == "moving_average_safety_stock"
                            ),
                            None,
                        ),
                        products_with_simulated_stockouts=sum(
                            item["stockout_events"] > 0 for item in risk
                        ),
                        risk_products=risk[:10],
                    )
                    result["scenario"] = {
                        "scenario_id": scenario.scenario_id,
                        "forecast_id": scenario.forecast_id,
                        "configuration_id": scenario.configuration_id,
                        "summary": {
                            key: value
                            for key, value in summary.items()
                            if key != "products"
                        },
                        "created_at": scenario.created_at,
                    }
            result["overview"] = overview
            return result

    @_guard
    def run(self, run_id):
        with Session(self.engine) as session:
            run, directory, _, plan, _, cohort = self._training(session, run_id)
            selection, calibration = _read(directory / "selection_metrics.json"), _read(
                directory / "calibration_metrics.json"
            )
            if (
                selection != run.metrics["selection"]
                or calibration != run.metrics["calibration"]
            ):
                raise ArtifactError("Registered training metrics changed")
            test, intervals = None, None
            retro = session.scalar(
                select(ForecastBatch)
                .where(
                    ForecastBatch.run_id == run_id,
                    ForecastBatch.scope == "retrospective",
                )
                .order_by(ForecastBatch.created_at.desc(), ForecastBatch.forecast_id)
                .limit(1)
            )
            if retro:
                batch, _, _, _, _, _ = self._forecast(session, retro.forecast_id)
                test = batch.metadata_json["evaluation_metrics"]["point"]
                intervals = batch.metadata_json["evaluation_metrics"]["uncertainty"]
            metadata = _read(directory / "training_metadata.json")
            return {
                "run_id": run_id,
                "dataset_id": run.dataset_id,
                "plan": plan,
                "cohort": cohort,
                "importance": _read(directory / "importance.json"),
                "metrics": {
                    "selection": selection,
                    "calibration": calibration,
                    "test": test,
                },
                "interval_metrics": intervals,
                "training_metadata": {
                    name: metadata.get(name) for name in _PUBLIC_TRAIN_METADATA
                },
                "test_status": (
                    "completed_cached_evaluation" if test else "not_registered"
                ),
            }

    def _product(self, session, source, plan, cohort, run, stock_code):
        products = {item["stock_code"] for item in cohort}
        code = stock_code or cohort[0]["stock_code"]
        if code not in products:
            raise ServiceError(
                404, "not_found", "The product is outside this frozen training cohort"
            )
        config = Phase3Config(**_read(source / "config.json"))
        if (
            list(feature_columns(config.timeline.seasonal_indicators))
            != plan["features"]
        ):
            raise ArtifactError("Frozen feature schema changed")
        panel = pd.read_parquet(source / "pretest_weekly.parquet")
        if len(panel) > MAX_ROWS or set(panel.stock_code) != products:
            raise ArtifactError("Frozen history cohort changed")
        history, features = _next_features(panel, config, code)
        product = _required(session, Product, (run.dataset_id, code))
        return (
            code,
            history,
            features,
            {"stock_code": code, "description": product.description},
        )

    @_guard
    def forecast(self, forecast_id, *, stock_code=None):
        with Session(self.engine) as session:
            batch, run, source, plan, cohort, frame = self._forecast(
                session, forecast_id
            )
            code, history, features, product = self._product(
                session, source, plan, cohort, run, stock_code
            )
            renamed = frame.loc[frame.stock_code.eq(code)].rename(
                columns={"model": "method", "prediction": "point"}
            )
            evaluation = batch.metadata_json.get("evaluation_metrics", {}).get(
                "point", {}
            )
            errors = [
                item
                for item in evaluation.get("by_product", [])
                if item["stock_code"] == code
            ]
            return {
                "forecast_id": forecast_id,
                "run_id": run.run_id,
                "dataset_id": run.dataset_id,
                "scope": batch.scope,
                "selected_ml_family": plan["best_ml_family"],
                "product": product,
                "history": _records(history.loc[:, list(PANEL_COLUMNS)]),
                "forecasts": _records(renamed.loc[:, list(_FORECAST_COLUMNS)]),
                "features": features,
                "product_errors": errors,
                "planner_defaults": {
                    "on_hand": math.ceil(2 * float(history.gross_units.mean())),
                    "on_order": 0,
                    "backordered_units": 0,
                    "label": "Illustrative opening stock: ceiling of two pre-test mean demand weeks; replace with your assumptions.",
                },
            }

    @staticmethod
    def _risk_products(summary):
        return sorted(
            [
                dict(item)
                for item in summary["products"]
                if item["policy"] == "ml_safety_stock"
            ],
            key=lambda item: (
                -item["lost_units"],
                -item["stockout_events"],
                item["stock_code"],
            ),
        )

    @_guard
    def scenario(self, scenario_id):
        with Session(self.engine) as session:
            scenario, directory, config, summary, frame = self._scenario(
                session, scenario_id
            )
        inputs = {
            item["stock_code"]: item["parameters"]
            for item in _read(directory / "product_inputs.json")
        }
        frame = frame.copy()
        frame["net_inventory_cost"] = [
            row.fulfilled_units * inputs[row.stock_code]["unit_purchase_cost"]
            + row.holding_cost
            + row.stockout_cost
            + row.order_cost
            for row in frame.itertuples(index=False)
        ]
        columns = [
            "actual",
            "fulfilled_units",
            "lost_units",
            "ending_inventory",
            "outstanding_units",
            "ordered_units",
            "purchase_cost",
            "holding_cost",
            "stockout_cost",
            "order_cost",
            "gross_cash_cost",
            "net_inventory_cost",
            "revenue",
            "estimated_lost_margin",
        ]
        weekly = (
            frame.groupby(["policy", "week"], sort=True, observed=True)[columns]
            .sum()
            .reset_index()
        )
        recommendations = pd.read_parquet(directory / "recommendations.parquet")
        recommendations = (
            recommendations.loc[
                recommendations.policy.eq("ml_safety_stock")
                & recommendations.review_due
            ]
            .sort_values(["stock_code", "week"])
            .groupby("stock_code", sort=True, observed=True)
            .tail(1)
        )
        return {
            "scenario_id": scenario_id,
            "forecast_id": scenario.forecast_id,
            "configuration_id": scenario.configuration_id,
            "config": config,
            "summary": summary,
            "weekly": _records(weekly),
            "risk_products": self._risk_products(summary),
            "recommendations": _records(recommendations),
            "scope": "retrospective_simulated_estimates_under_stated_assumptions",
        }

    @_guard
    def preview(self, request: InventoryPreviewRequest):
        with Session(self.engine) as session:
            batch, run, source, plan, cohort, frame = self._forecast(
                session, request.forecast_id
            )
            code, _, features, _ = self._product(
                session, source, plan, cohort, run, request.stock_code
            )
        method = plan["best_ml_family"]
        origin = frame.week.min()
        issued = frame.loc[
            frame.stock_code.eq(code) & frame.model.eq(method) & frame.week.eq(origin)
        ].iloc[0]
        calibration = pd.read_parquet(source / "calibration_predictions.parquet")
        rows = calibration.loc[calibration.model.eq(method)].copy()
        start, end = pd.Timestamp(plan["roles"]["calibration_start"]), pd.Timestamp(
            plan["roles"]["calibration_end"]
        )
        if (
            rows.empty
            or rows.week.min() != start
            or rows.week.max() != end
            or not rows.week.between(start, end).all()
            or end >= origin
        ):
            raise ArtifactError("Calibration error chronology changed")
        values = rows[["actual", "prediction", "scale"]].to_numpy(dtype="float64")
        if not np.isfinite(values).all() or (values < 0).any():
            raise ArtifactError("Calibration error inputs are invalid")
        normalized = (values[:, 0] - values[:, 1]) / np.maximum(values[:, 2], 10.0)
        multiplier = math.sqrt(float(np.mean(normalized**2)))
        scale = max(float(features["values"]["rolling_mean4"]), 10.0)
        sigma = multiplier * scale
        state, parameters = (
            request.inventory_state(),
            request.parameters.inventory_parameters(),
        )
        try:
            recommendation = recommend_inventory(
                float(issued.prediction), sigma, state, parameters
            )
        except ValueError as exc:
            raise ServiceError(
                422,
                "invalid_inventory",
                "The supplied inventory assumptions exceed supported constraints",
            ) from exc
        available = max(0, state.on_hand - state.backordered_units)
        moments = normal_preview(float(issued.prediction), sigma, available)
        purchase = (
            recommendation.recommended_order_quantity * parameters.unit_purchase_cost
        )
        ordering = (
            parameters.order_cost if recommendation.recommended_order_quantity else 0.0
        )
        holding = (
            moments["expected_ending_inventory"] * parameters.holding_cost_per_unit_week
        )
        penalty = moments["expected_lost_units"] * parameters.stockout_penalty_per_unit
        costs = {
            **{
                key: value
                for key, value in moments.items()
                if key != "stockout_probability"
            },
            "purchase_cost": purchase,
            "order_cost": ordering,
            "holding_cost": holding,
            "stockout_cost": penalty,
            "estimated_lost_margin": moments["expected_lost_units"]
            * max(0.0, parameters.unit_selling_price - parameters.unit_purchase_cost),
            "total_cost": math.fsum([purchase, ordering, holding, penalty]),
            "scope": "illustrative_order_cash_plus_approximate_next_week_operating_cost",
            "label": "New-order cash plus next-week holding/stockout estimates; not a simulated horizon total or realized saving. Lost margin is separate and excluded from total_cost.",
        }
        if not all(
            math.isfinite(value) for value in costs.values() if isinstance(value, float)
        ):
            raise ServiceError(
                422,
                "invalid_inventory",
                "The supplied costs exceed the supported numeric range",
            )
        return {
            "forecast_id": request.forecast_id,
            "stock_code": code,
            "method": method,
            "week": origin.date().isoformat(),
            "scope": "stateless_assumption_driven_preview",
            "state": asdict(state),
            "parameters": asdict(parameters),
            "recommendation": _json(asdict(recommendation)),
            "risk": {
                "probability": moments["stockout_probability"],
                "available_next_week": available,
                "scope": "next_week_normal_approximation",
                "label": "Approximation using max(0, Normal(point, pre-test error magnitude)); not calibrated stockout probability or a guarantee. On-order/new units are excluded because their arrival dates are unspecified; current backorders reduce on-hand availability.",
            },
            "cost_preview": costs,
            "error_estimate": {
                "method": "pooled_pretest_normalized_calibration_RMSE_times_max_rolling_mean4_10",
                "normalized_rmse": multiplier,
                "scale": scale,
                "error_std": sigma,
                "calibration_start": start.date().isoformat(),
                "calibration_end": end.date().isoformat(),
                "n_observations": len(rows),
                "test_residuals_used": False,
            },
        }

    def export_preview(self, request: InventoryPreviewRequest):
        result = self.preview(request)
        row = {
            "forecast_id": result["forecast_id"],
            "stock_code": result["stock_code"],
            "week": result["week"],
            "method": result["method"],
            "scope": result["scope"],
            **result["state"],
            **result["parameters"],
            **result["recommendation"],
            "approximate_stockout_probability": result["risk"]["probability"],
            **{
                f"preview_{key}": value for key, value in result["cost_preview"].items()
            },
        }
        return _csv([row]), "inventory-preview.csv"

    def export_risk(self, scenario_id):
        result = self.scenario(scenario_id)
        rows = [
            {"scenario_id": scenario_id, "scope": result["scope"], **row}
            for row in result["risk_products"]
        ]
        return _csv(rows), f"simulated-product-risk-{scenario_id[:12]}.csv"
