"""Immutable application forecasts from verified frozen Phase 3 artifacts.

One-week inference is anchored immediately after the run's historical refit end,
not today's date. It loads trusted local models and pre-test aggregate history;
it never reads raw transactions, test actuals or invokes final evaluation.
Retrospective scope reuses only an already-completed, ledger-verified evaluation.
Neither operation fits a model, selects a method or recalibrates uncertainty.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tempfile
from importlib.metadata import version
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import Settings
from backend.app.services.errors import ServiceError
from ml.data.acquisition import canonical_json, sha256_file
from ml.evaluation.splits import monday
from ml.evaluation.uncertainty import add_intervals
from ml.features.weekly import feature_columns
from ml.models.baselines import predict_baselines
from ml.models.config import Phase3Config
from ml.pipelines.artifacts import inventory, verify_run, write_json
from ml.pipelines.ingestion import ArtifactError

FORECAST_SERVICE_VERSION = "1.0.0"
FAMILIES = ("ridge", "random_forest", "xgboost")
REQUIRED = {"forecasts.parquet", "metadata.json"}
_SOURCE_REQUIRED = {
    "plan.json",
    "config.json",
    "cohort.json",
    "pretest_weekly.parquet",
    "calibration.json",
    "pretest_forecasts.parquet",
} | {f"models/{family}.joblib" for family in FAMILIES}
_COLUMNS = (
    "stock_code",
    "week",
    "actual",
    "scale",
    "prediction",
    "model",
    "fold",
    "lower",
    "upper",
    "nominal_coverage",
    "uncertainty_label",
)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError(
            "Frozen forecasting metadata is incomplete or unreadable."
        ) from exc


def _within(root: Path, relative: str) -> Path:
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise ArtifactError("Forecast artifact path escapes its configured root.")
    return resolved


def _source(
    settings: Settings, run_id: str
) -> tuple[Path, dict[str, Any], dict[str, Any], set[str]]:
    source = _within(settings.artifact_dir, f"phase3/{run_id}")
    if not source.is_dir():
        raise ServiceError(
            404, "not_found", "The frozen training artifacts are unavailable."
        )
    for name in _SOURCE_REQUIRED:
        _within(source, name)
    manifest = verify_run(
        source,
        required=_SOURCE_REQUIRED,
        expected={"experiment_id": run_id, "state": "frozen_pretest"},
    )
    plan = _read(source / "plan.json")
    try:
        valid = (
            isinstance(plan, dict)
            and plan["experiment_id"] == run_id
            and plan["dataset_id"] == manifest["dataset_id"]
            and plan["horizon_weeks"] == 1
            and plan["best_ml_family"] in FAMILIES
            and isinstance(plan["features"], list)
            and bool(plan["features"])
            and isinstance(plan["test_methods"], list)
            and bool(plan["test_methods"])
            and all(
                isinstance(method, str) and bool(method)
                for method in plan["test_methods"]
            )
            and isinstance(plan["roles"], dict)
            and isinstance(plan["roles"]["test_start"], str)
            and isinstance(plan["roles"]["test_end"], str)
            and isinstance(plan["refit_end"], str)
            and manifest["plan_sha256"] == sha256_file(source / "plan.json")
            and plan["calibration_sha256"] == sha256_file(source / "calibration.json")
            and plan["cohort_sha256"] == sha256_file(source / "cohort.json")
            and set(plan["model_hashes"]) == set(FAMILIES)
            and all(
                plan["model_hashes"][family]
                == manifest["artifacts"][f"models/{family}.joblib"]["sha256"]
                for family in FAMILIES
            )
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ArtifactError(
            "Frozen forecast plan contradicts its training artifact identity."
        )
    cohort = _read(source / "cohort.json")
    if (
        not isinstance(cohort, list)
        or not cohort
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("stock_code"), str)
            or not row["stock_code"]
            or row["stock_code"] != row["stock_code"].strip()
            for row in cohort
        )
    ):
        raise ArtifactError("Frozen product cohort is invalid.")
    products = {row["stock_code"] for row in cohort}
    if len(products) != len(cohort):
        raise ArtifactError("Frozen product cohort contains duplicate identifiers.")
    return source, manifest, plan, products


def _one_week(source: Path, plan: dict[str, Any]) -> pd.DataFrame:
    # These imports load the native model runtime only for actual inference.
    from ml.models.training import load_model, predict_model
    from ml.pipelines.modeling import _next_week_features

    try:
        config = Phase3Config(**_read(source / "config.json"))
        names = feature_columns(config.timeline.seasonal_indicators)
        if list(names) != plan["features"] or monday(plan["refit_end"]) != monday(
            config.timeline.validation_end
        ):
            raise ArtifactError(
                "Frozen feature list or refit boundary is inconsistent."
            )
        panel = pd.read_parquet(source / "pretest_weekly.parquet")
        cohort = _read(source / "cohort.json")
        products = {row["stock_code"] for row in cohort}
        weeks = pd.date_range(
            config.timeline.start_week, config.timeline.validation_end, freq="W-MON"
        )
        if (
            len(products) != len(cohort)
            or set(panel.stock_code) != products
            or len(panel) != len(products) * len(weeks)
        ):
            raise ArtifactError(
                "Frozen pre-test panel does not match its product cohort."
            )
        for _, rows in panel.groupby("stock_code", sort=True, observed=True):
            if sorted(rows.week.tolist()) != list(weeks):
                raise ArtifactError(
                    "Frozen pre-test panel must stop at the refit boundary without gaps."
                )
        features = _next_week_features(panel, config)
        if (
            len(features) != len(products)
            or not features.week.eq(config.timeline.test_start).all()
        ):
            raise ArtifactError(
                "One-week features do not cover the next frozen origin."
            )
        parts = []
        for family in FAMILIES:
            model = load_model(
                _within(source, f"models/{family}.joblib"), plan["model_hashes"][family]
            )
            if (
                model.training_end != monday(plan["refit_end"])
                or model.feature_names != names
                or model.candidate["family"] != family
            ):
                raise ArtifactError(
                    "A fitted model contradicts the frozen training boundary or features."
                )
            rows = (
                features[["stock_code", "week", "rolling_mean4"]]
                .rename(columns={"rolling_mean4": "scale"})
                .copy()
            )
            rows["prediction"] = predict_model(model, features)
            rows["model"] = family
            parts.append(rows)
        baseline = predict_baselines(
            panel[["stock_code", "week", "gross_units"]],
            config.timeline.test_start,
            seasonal_period=config.timeline.seasonal_period,
            moving_window=config.timeline.moving_window,
        )
        baseline = baseline.merge(
            features[["stock_code", "week", "rolling_mean4"]].rename(
                columns={"rolling_mean4": "scale"}
            ),
            on=["stock_code", "week"],
            validate="many_to_one",
        )
        parts.append(baseline)
        predicted = pd.concat(parts, ignore_index=True)
        predicted["fold"] = "one_week"
        predicted["actual"] = None
        bounded = add_intervals(predicted, _read(source / "calibration.json"))
        # Verify true inference against the forecast issued before test access.
        issued = pd.read_parquet(source / "pretest_forecasts.parquet")
        keys = ["stock_code", "week", "model"]
        new, old = bounded.sort_values(keys), issued.sort_values(keys)
        numeric = ["prediction", "scale", "lower", "upper", "nominal_coverage"]
        if new[keys].reset_index(drop=True).equals(
            old[keys].reset_index(drop=True)
        ) is False or not np.allclose(
            new[numeric], old[numeric], rtol=1e-12, atol=1e-8
        ):
            raise ArtifactError(
                "Generated one-week forecasts differ from frozen pre-test issuance."
            )
        return bounded.loc[:, list(_COLUMNS)]
    except ArtifactError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ArtifactError(
            "Frozen inputs cannot produce a valid one-week forecast."
        ) from exc


def _validated_frame(
    frame: pd.DataFrame,
    plan: dict[str, Any],
    scope: str,
    expected_products: set[str],
) -> pd.DataFrame:
    if (
        not isinstance(frame, pd.DataFrame)
        or frame.empty
        or frame.columns.has_duplicates
        or not set(_COLUMNS).issubset(frame)
    ):
        raise ArtifactError("Forecast output schema is incomplete.")
    result = frame.loc[:, list(_COLUMNS)].copy()
    expected_methods = set(plan["test_methods"])
    if (
        set(result.model) != expected_methods
        or result.duplicated(["stock_code", "week", "model"]).any()
    ):
        raise ArtifactError(
            "Forecast output methods or observation keys are inconsistent."
        )
    dates = pd.date_range(
        plan["roles"]["test_start"],
        (
            plan["roles"]["test_start"]
            if scope == "one_week"
            else plan["roles"]["test_end"]
        ),
        freq="W-MON",
    )
    products = set(result.stock_code)
    if products != expected_products or len(result) != len(products) * len(dates) * len(
        expected_methods
    ):
        raise ArtifactError(
            "Forecast output does not cover a complete product-week-method grid."
        )
    for _, group in result.groupby(["stock_code", "model"], sort=True, observed=True):
        if sorted(group.week.tolist()) != list(dates):
            raise ArtifactError("Forecast output dates contradict the frozen horizon.")
    try:
        numeric = result[
            ["scale", "prediction", "lower", "upper", "nominal_coverage"]
        ].to_numpy(dtype="float64")
        if (
            not np.isfinite(numeric).all()
            or (numeric[:, :4] < 0).any()
            or ((numeric[:, 4] <= 0) | (numeric[:, 4] >= 1)).any()
        ):
            raise ValueError
        if not (
            result.lower.le(result.prediction) & result.prediction.le(result.upper)
        ).all():
            raise ValueError
        if scope == "one_week":
            if result.actual.notna().any():
                raise ValueError
            result["actual"] = None
        else:
            for value in result.actual:
                if (
                    isinstance(value, bool | np.bool_)
                    or not isinstance(value, Real)
                    or not math.isfinite(value)
                    or value != int(value)
                    or not 0 <= int(value) <= np.iinfo(np.int64).max
                ):
                    raise ValueError
            result["actual"] = result.actual.map(int).astype("int64")
            if (
                not result.groupby(["stock_code", "week"], observed=True)
                .actual.nunique()
                .eq(1)
                .all()
            ):
                raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ArtifactError(
            "Forecast values or bounds are invalid for their declared scope."
        ) from exc
    return result.sort_values(
        ["week", "stock_code", "model"], kind="stable"
    ).reset_index(drop=True)


def _cached(
    destination: Path,
    expected: dict[str, Any],
    plan: dict[str, Any],
    scope: str,
    products: set[str],
    evaluation_metrics: dict[str, Any] | None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    verify_run(destination, required=REQUIRED, expected=expected)
    metadata = _read(destination / "metadata.json")
    frame = _validated_frame(
        pd.read_parquet(destination / "forecasts.parquet"), plan, scope, products
    )
    if (
        not isinstance(metadata, dict)
        or any(
            metadata.get(name) != expected[name]
            for name in ("forecast_id", "run_id", "scope")
        )
        or metadata.get("row_count") != len(frame)
        or metadata.get("product_count") != frame.stock_code.nunique()
        or metadata.get("actuals_available") != (scope == "retrospective")
        or metadata.get("evaluation_metrics") != evaluation_metrics
    ):
        raise ArtifactError(
            "Cached forecast metadata contradicts its verified observations."
        )
    return metadata, frame


def prepare_forecast(
    settings: Settings,
    run_id: str,
    scope: str,
) -> tuple[str, Path, dict[str, Any], pd.DataFrame]:
    """Prepare verified local forecast files without database writes or evaluation."""
    if not isinstance(settings, Settings):
        raise ValueError("settings must be validated application Settings.")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{64}", run_id):
        raise ServiceError(
            422, "invalid_input", "run_id must be a lowercase SHA-256 identifier."
        )
    if not isinstance(scope, str) or scope not in {"one_week", "retrospective"}:
        raise ServiceError(
            422, "invalid_input", "Forecast scope must be one_week or retrospective."
        )
    source, training_manifest, plan, products = _source(settings, run_id)
    lineage = {
        "training_manifest_sha256": sha256_file(source / "manifest.json"),
        "plan_sha256": training_manifest["plan_sha256"],
        "calibration_sha256": plan["calibration_sha256"],
        "cohort_sha256": plan["cohort_sha256"],
        "model_hashes": dict(plan["model_hashes"]),
    }
    evaluation = None
    evaluation_metrics = None
    if scope == "retrospective":
        from ml.pipelines.inventory import load_frozen_inputs

        completed_plan, completed_lineage, evaluation = load_frozen_inputs(
            source, settings.ledger_dir
        )
        if completed_plan != plan:
            raise ArtifactError("Completed evaluation refers to another frozen plan.")
        lineage.update(completed_lineage)
        verify_run(
            evaluation,
            required={
                "predictions.parquet",
                "evaluation_metadata.json",
                "metrics.json",
                "interval_metrics.json",
            },
            expected={
                "experiment_id": run_id,
                "dataset_id": plan["dataset_id"],
                "plan_sha256": training_manifest["plan_sha256"],
                "evaluation_scope": "test",
            },
        )
        point = _read(evaluation / "metrics.json")
        uncertainty = _read(evaluation / "interval_metrics.json")
        if (
            not isinstance(point, dict)
            or point.get("evaluation_scope") != "test"
            or not isinstance(uncertainty, dict)
            or uncertainty.get("scope") != "test"
            or sha256_file(evaluation / "manifest.json")
            != lineage["evaluation_manifest_sha256"]
        ):
            raise ArtifactError("Completed metrics contradict the verified test scope.")
        evaluation_metrics = {"point": point, "uncertainty": uncertainty}
    identity = {
        "forecast_service_version": FORECAST_SERVICE_VERSION,
        "run_id": run_id,
        "dataset_id": plan["dataset_id"],
        "scope": scope,
        "source": lineage,
        "runtime": {
            name: version(name)
            for name in (
                "numpy",
                "pandas",
                "pyarrow",
                "scikit-learn",
                "xgboost",
                "joblib",
            )
        },
        "service_sha256": sha256_file(Path(__file__)),
    }
    forecast_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    root = _within(settings.artifact_dir, "backend/forecasts")
    destination = _within(root, forecast_id)
    expected = {**identity, "forecast_id": forecast_id, "state": "complete"}
    if destination.exists():
        metadata, frame = _cached(
            destination, expected, plan, scope, products, evaluation_metrics
        )
        return forecast_id, destination, metadata, frame
    frame = (
        _one_week(source, plan)
        if scope == "one_week"
        else pd.read_parquet(evaluation / "predictions.parquet")
    )
    frame = _validated_frame(frame, plan, scope, products)
    if sha256_file(source / "manifest.json") != lineage["training_manifest_sha256"]:
        raise ArtifactError("Frozen training identity changed during inference.")
    verify_run(
        source,
        required=_SOURCE_REQUIRED,
        expected={"experiment_id": run_id, "state": "frozen_pretest"},
    )
    metadata = {
        "forecast_id": forecast_id,
        "run_id": run_id,
        "dataset_id": plan["dataset_id"],
        "scope": scope,
        "horizon_weeks": 1,
        "history_end": plan["refit_end"],
        "forecast_start": frame.week.min().date().isoformat(),
        "forecast_end": frame.week.max().date().isoformat(),
        "product_count": int(frame.stock_code.nunique()),
        "row_count": len(frame),
        "methods": sorted(frame.model.unique().tolist()),
        "selected_ml_family": plan["best_ml_family"],
        "actuals_available": scope == "retrospective",
        "source": lineage,
        "generation": (
            "real_inference_from_frozen_models"
            if scope == "one_week"
            else "verified_completed_retrospective_forecasts"
        ),
        "origin_convention": (
            "Historical first post-refit one-week origin; not a forecast for the current calendar date."
            if scope == "one_week"
            else "Already-observed rolling one-week origins from the completed frozen evaluation; no new forecasting test."
        ),
    }
    if evaluation_metrics is not None:
        metadata["evaluation_metrics"] = evaluation_metrics
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".forecast-", dir=root))
    try:
        frame.to_parquet(staging / "forecasts.parquet", index=False, compression="zstd")
        write_json(staging / "metadata.json", metadata)
        write_json(
            staging / "manifest.json", {**expected, "artifacts": inventory(staging)}
        )
        _cached(staging, expected, plan, scope, products, evaluation_metrics)
        try:
            staging.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            metadata, frame = _cached(
                destination, expected, plan, scope, products, evaluation_metrics
            )
        return forecast_id, destination, metadata, frame
    finally:
        if staging.exists():
            shutil.rmtree(staging)
