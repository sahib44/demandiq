"""Temporal ML selection, disjoint residual calibration and frozen final testing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.data.acquisition import canonical_json, sha256_file
from ml.data.weekly import aggregate_weekly, select_top_products
from ml.evaluation.final_test import (
    claim_final_evaluation,
    complete_final_evaluation,
    read_final_evaluation,
    verify_cached_evaluation,
)
from ml.evaluation.metrics import evaluate_predictions
from ml.evaluation.model_diagnostics import FILENAMES as DIAGNOSTIC_FILENAMES
from ml.evaluation.model_diagnostics import render_diagnostics
from ml.evaluation.model_plots import PLOT_FILENAMES as MODEL_PLOT_FILENAMES
from ml.evaluation.model_plots import render_model_plots
from ml.evaluation.splits import expanding_folds, monday
from ml.evaluation.uncertainty import (
    add_intervals,
    calibrate_intervals,
    interval_metrics,
)
from ml.features.weekly import feature_columns, generate_features
from ml.models.config import Phase3Config
from ml.models.training import (
    feature_importance,
    fit_model,
    load_model,
    model_candidates,
    predict_model,
    save_model,
)
from ml.pipelines.artifacts import inventory, verify_run, write_json
from ml.pipelines.forecasting_foundation import run_phase2
from ml.pipelines.ingestion import ArtifactError, verify_dataset

PHASE3_VERSION = "1.0.0"
FAMILIES = ("ridge", "random_forest", "xgboost")
TRAIN_REQUIRED = {
    "calibration_metrics.json",
    "candidate_predictions.parquet",
    "selection_training_volumes.parquet",
    "config.json",
    "plan.json",
    "selection_metrics.json",
    "candidate_metrics.json",
    "selection_predictions.parquet",
    "calibration_predictions.parquet",
    "calibration.json",
    "cohort.json",
    "pretest_forecasts.parquet",
    "pretest_weekly.parquet",
    "importance.json",
    "training_metadata.json",
} | {f"models/{family}.joblib" for family in FAMILIES}
TEST_REQUIRED = {
    "predictions.parquet",
    "metrics.json",
    "interval_metrics.json",
    "training_volumes.parquet",
    "evaluation_metadata.json",
} | {f"plots/{name}" for name in (*MODEL_PLOT_FILENAMES, *DIAGNOSTIC_FILENAMES)}


@dataclass(frozen=True)
class ModelingResult:
    run_dir: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    timings: dict[str, float]


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _scoped_metrics(
    predictions: pd.DataFrame, volumes: pd.DataFrame, scope: str
) -> dict[str, Any]:
    result = evaluate_predictions(predictions, training_volumes=volumes)
    result["evaluation_scope"] = scope
    result["metric_definitions"][
        "evaluation_scope"
    ] = f"{scope}; settings frozen using selection validation only."
    return result


def _identity(
    source_id: str, config: Phase3Config, candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    import ml.data.weekly as weekly_module
    import ml.evaluation.final_test as ledger_module
    import ml.evaluation.metrics as metrics_module
    import ml.evaluation.model_diagnostics as diagnostics_module
    import ml.evaluation.model_plots as plots_module
    import ml.evaluation.splits as splits_module
    import ml.evaluation.uncertainty as uncertainty_module
    import ml.features.weekly as feature_module
    import ml.models.baselines as baselines_module
    import ml.models.config as config_module
    import ml.models.training as training_module

    return {
        "phase3_version": PHASE3_VERSION,
        "dataset_id": source_id,
        "config": config.to_dict(),
        "candidates": candidates,
        "runtime": {
            name: version(name)
            for name in (
                "numpy",
                "pandas",
                "pyarrow",
                "scikit-learn",
                "scipy",
                "xgboost",
                "joblib",
                "matplotlib",
            )
        },
        "code_hashes": {
            name: sha256_file(Path(module.__file__))
            for name, module in (
                ("training", training_module),
                ("features", feature_module),
                ("uncertainty", uncertainty_module),
                ("weekly", weekly_module),
                ("metrics", metrics_module),
                ("splits", splits_module),
                ("baselines", baselines_module),
                ("configuration", config_module),
                ("ledger", ledger_module),
                ("model_plots", plots_module),
                ("diagnostics", diagnostics_module),
            )
        },
        "pipeline_sha256": sha256_file(Path(__file__)),
    }


def _training_rows(
    features: pd.DataFrame, end: Any, config: Phase3Config
) -> pd.DataFrame:
    first = monday(config.timeline.start_week) + pd.Timedelta(weeks=config.warmup_weeks)
    result = features.loc[features.week.between(first, monday(end))].copy()
    if result.empty:
        raise ValueError("No supervised rows remain after the configured warm-up")
    return result


def _baseline_rows(
    panel: pd.DataFrame,
    features: pd.DataFrame,
    weeks: Any,
    config: Phase3Config,
    fold: str,
) -> pd.DataFrame:
    from ml.models.baselines import predict_baselines

    parts = []
    for week in weeks:
        predicted = predict_baselines(
            panel.loc[panel.week < week, ["stock_code", "week", "gross_units"]],
            week,
            seasonal_period=config.timeline.seasonal_period,
            moving_window=config.timeline.moving_window,
        )
        truth = features.loc[
            features.week == week,
            ["stock_code", "week", "gross_units", "rolling_mean4"],
        ].rename(columns={"gross_units": "actual", "rolling_mean4": "scale"})
        scored = predicted.merge(
            truth, on=["stock_code", "week"], validate="many_to_one"
        )
        scored["fold"] = fold
        parts.append(scored)
    return pd.concat(parts, ignore_index=True)


def _ml_rows(model: Any, features: pd.DataFrame, name: str, fold: str) -> pd.DataFrame:
    result = (
        features[["stock_code", "week", "gross_units", "rolling_mean4"]]
        .rename(columns={"gross_units": "actual", "rolling_mean4": "scale"})
        .copy()
    )
    result["prediction"] = predict_model(model, features)
    result["model"], result["fold"] = name, fold
    return result


def _rank(row: dict[str, Any]) -> tuple[float, float, str]:
    return (
        row["wape"] if row["wape"] is not None else row["mae"],
        row["mae"],
        row["model"],
    )


def _next_week_features(panel: pd.DataFrame, config: Phase3Config) -> pd.DataFrame:
    template = panel.loc[panel.week == monday(config.timeline.validation_end)].copy()
    template["week"] = config.timeline.test_start
    for column in (
        "gross_units",
        "returned_units",
        "cancellation_units",
        "net_units",
        "revenue",
        "transactions",
        "unique_customers",
    ):
        template[column] = 0
    template["average_price"] = np.nan
    # Current dummy labels/covariates never enter shifted predictors.
    expanded = pd.concat([panel, template], ignore_index=True)
    features = generate_features(
        expanded, seasonal_indicators=config.timeline.seasonal_indicators
    )
    return features.loc[features.week == config.timeline.test_start].copy()


def train_phase3(
    dataset_dir: Path,
    output_root: Path,
    *,
    config: Phase3Config | None = None,
    phase2_root: Path = Path("data/phase2"),
    ledger_root: Path = Path("data/evaluation-ledger"),
) -> ModelingResult:
    started = time.perf_counter()
    if config is None:
        config = Phase3Config()
    if not isinstance(config, Phase3Config):
        raise ValueError("config must be Phase3Config")
    config = Phase3Config(**config.to_dict())
    source = verify_dataset(Path(dataset_dir))
    candidates = model_candidates(config.seed)
    identity = _identity(source.manifest["dataset_id"], config, candidates)
    experiment_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    expected = {**identity, "experiment_id": experiment_id, "state": "frozen_pretest"}
    output_root, ledger_root = Path(output_root), Path(ledger_root)
    final = output_root / experiment_id
    if final.exists():
        manifest = verify_run(final, required=TRAIN_REQUIRED, expected=expected)
        return ModelingResult(
            final,
            manifest,
            _json(final / "selection_metrics.json"),
            {"total_seconds": time.perf_counter() - started, "cache_reused": 1.0},
        )
    if (ledger_root / f"{source.manifest['dataset_id']}.json").exists():
        prior = read_final_evaluation(ledger_root, source.manifest["dataset_id"])
        raise ValueError(
            f"Final test already reserved/evaluated for {prior['experiment_id']}; only verified existing training artifacts may be reused"
        )
    phase2 = run_phase2(Path(dataset_dir), Path(phase2_root), config.timeline)
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".training-", dir=output_root))
    fits, selection_parts, volumes = [], [], []
    names = feature_columns(config.timeline.seasonal_indicators)
    folds = expanding_folds(config.timeline)
    try:
        for fold in folds[:-1]:
            features = pd.read_parquet(
                phase2.run_dir / f"features_fold_{fold.fold}.parquet"
            )
            panel = pd.read_parquet(phase2.run_dir / "weekly.parquet")
            panel = panel.loc[
                panel.stock_code.isin(features.stock_code.unique())
                & (panel.week <= fold.validation_end)
            ].copy()
            train = _training_rows(features, fold.train_end, config)
            validation = features.loc[
                features.week.between(fold.validation_start, fold.validation_end)
            ].copy()
            for candidate in candidates:
                tick = time.perf_counter()
                fitted = fit_model(train, candidate, feature_names=names)
                fits.append(
                    {
                        "stage": "selection",
                        "fold": fold.fold,
                        "candidate": candidate["id"],
                        "rows": len(train),
                        "seconds": time.perf_counter() - tick,
                    }
                )
                selection_parts.append(
                    _ml_rows(fitted, validation, candidate["id"], str(fold.fold))
                )
            selection_parts.append(
                _baseline_rows(
                    panel,
                    features,
                    pd.date_range(
                        fold.validation_start, fold.validation_end, freq="W-MON"
                    ),
                    config,
                    str(fold.fold),
                )
            )
            cohort = select_top_products(
                panel,
                train_end=fold.train_end,
                top_n=config.timeline.top_products,
                min_history_weeks=config.timeline.min_history_weeks,
            )[["stock_code", "training_units"]]
            cohort["fold"] = str(fold.fold)
            volumes.append(cohort)
        all_selection = pd.concat(selection_parts, ignore_index=True)
        training_volumes = pd.concat(volumes, ignore_index=True)
        candidate_metrics = _scoped_metrics(
            all_selection, training_volumes, "selection_validation"
        )
        by_id = {row["model"]: row for row in candidate_metrics["overall"]}
        chosen = {
            family: min(
                [
                    candidate
                    for candidate in candidates
                    if candidate["family"] == family
                ],
                key=lambda candidate: _rank(by_id[candidate["id"]]),
            )
            for family in FAMILIES
        }
        renaming = {candidate["id"]: family for family, candidate in chosen.items()}
        baseline_names = sorted(
            set(all_selection.model) - {candidate["id"] for candidate in candidates}
        )
        selection = all_selection.loc[
            all_selection.model.isin([*renaming, *baseline_names])
        ].copy()
        selection["model"] = selection.model.replace(renaming)
        selection_metrics = _scoped_metrics(
            selection, training_volumes, "selection_validation"
        )
        best_ml = min(
            [row for row in selection_metrics["overall"] if row["model"] in FAMILIES],
            key=_rank,
        )["model"]
        recommended = min(selection_metrics["overall"], key=_rank)["model"]
        selection.to_parquet(
            staging / "selection_predictions.parquet", index=False, compression="zstd"
        )
        all_selection.to_parquet(
            staging / "candidate_predictions.parquet", index=False, compression="zstd"
        )
        training_volumes.to_parquet(
            staging / "selection_training_volumes.parquet",
            index=False,
            compression="zstd",
        )
        write_json(staging / "candidate_metrics.json", candidate_metrics)
        write_json(staging / "selection_metrics.json", selection_metrics)
        last = folds[-1]
        calibration_features = pd.read_parquet(
            phase2.run_dir / f"features_fold_{last.fold}.parquet"
        )
        weekly = pd.read_parquet(phase2.run_dir / "weekly.parquet")
        calibration_panel = weekly.loc[
            weekly.stock_code.isin(calibration_features.stock_code.unique())
            & (weekly.week <= last.validation_end)
        ].copy()
        calibration_targets = calibration_features.loc[
            calibration_features.week.between(
                last.validation_start, last.validation_end
            )
        ].copy()
        calibration_parts = []
        for family, candidate in chosen.items():
            tick = time.perf_counter()
            train = _training_rows(calibration_features, last.train_end, config)
            fitted = fit_model(train, candidate, feature_names=names)
            fits.append(
                {
                    "stage": "calibration",
                    "fold": last.fold,
                    "candidate": candidate["id"],
                    "rows": len(train),
                    "seconds": time.perf_counter() - tick,
                }
            )
            calibration_parts.append(
                _ml_rows(fitted, calibration_targets, family, str(last.fold))
            )
        calibration_parts.append(
            _baseline_rows(
                calibration_panel,
                calibration_features,
                pd.date_range(last.validation_start, last.validation_end, freq="W-MON"),
                config,
                str(last.fold),
            )
        )
        calibration_predictions = pd.concat(calibration_parts, ignore_index=True)
        calibration = calibrate_intervals(
            calibration_predictions,
            coverage=config.interval_coverage,
            scale_floor=config.interval_scale_floor,
        )
        calibration_predictions.to_parquet(
            staging / "calibration_predictions.parquet", index=False, compression="zstd"
        )
        write_json(staging / "calibration.json", calibration)
        calibration_volumes = select_top_products(
            calibration_panel,
            train_end=last.train_end,
            top_n=config.timeline.top_products,
            min_history_weeks=config.timeline.min_history_weeks,
        )[["stock_code", "training_units"]]
        calibration_volumes["fold"] = str(last.fold)
        write_json(
            staging / "calibration_metrics.json",
            _scoped_metrics(
                calibration_predictions,
                calibration_volumes,
                "calibration_only_not_selection",
            ),
        )
        cohort = select_top_products(
            weekly,
            train_end=config.timeline.validation_end,
            top_n=config.timeline.top_products,
            min_history_weeks=config.timeline.min_history_weeks,
        )
        pretest_panel = weekly.loc[weekly.stock_code.isin(cohort.stock_code)].copy()
        pretest_features = generate_features(
            pretest_panel, seasonal_indicators=config.timeline.seasonal_indicators
        )
        final_training = _training_rows(
            pretest_features, config.timeline.validation_end, config
        )
        next_features = _next_week_features(pretest_panel, config)
        next_parts, model_hashes, importance = [], {}, {}
        (staging / "models").mkdir()
        for family, candidate in chosen.items():
            tick = time.perf_counter()
            fitted = fit_model(final_training, candidate, feature_names=names)
            fits.append(
                {
                    "stage": "final_refit",
                    "candidate": candidate["id"],
                    "rows": len(final_training),
                    "seconds": time.perf_counter() - tick,
                }
            )
            model_hashes[family] = save_model(
                fitted, staging / "models" / f"{family}.joblib"
            )
            reloaded = load_model(
                staging / "models" / f"{family}.joblib", model_hashes[family]
            )
            if not np.allclose(
                predict_model(fitted, next_features),
                predict_model(reloaded, next_features),
                atol=1e-9,
                rtol=1e-12,
            ):
                raise ValueError("Model reload changed predictions")
            next_parts.append(_ml_rows(reloaded, next_features, family, "test"))
            importance[family] = feature_importance(fitted)
        next_parts.append(
            _baseline_rows(
                pretest_panel,
                next_features,
                [config.timeline.test_start],
                config,
                "test",
            )
        )
        next_predictions = pd.concat(next_parts, ignore_index=True).drop(
            columns="actual"
        )
        add_intervals(next_predictions, calibration).to_parquet(
            staging / "pretest_forecasts.parquet", index=False, compression="zstd"
        )
        pretest_panel.to_parquet(
            staging / "pretest_weekly.parquet", index=False, compression="zstd"
        )
        write_json(staging / "cohort.json", cohort.to_dict(orient="records"))
        write_json(staging / "importance.json", importance)
        write_json(staging / "config.json", config.to_dict())
        plan = {
            "experiment_id": experiment_id,
            "dataset_id": source.manifest["dataset_id"],
            "roles": config.roles(),
            "selected_candidates": chosen,
            "best_ml_family": best_ml,
            "recommended_method": recommended,
            "test_methods": sorted([*FAMILIES, *baseline_names]),
            "selection_rule": "minimum selection-validation WAPE, then MAE, then identifier; MAE fallback when WAPE undefined",
            "model_hashes": model_hashes,
            "calibration_sha256": sha256_file(staging / "calibration.json"),
            "cohort_sha256": sha256_file(staging / "cohort.json"),
            "features": list(names),
            "seed": config.seed,
            "horizon_weeks": 1,
            "refit_end": config.timeline.validation_end,
            "test_refitting": False,
            "test_product_reselection": False,
        }
        write_json(staging / "plan.json", plan)
        git = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        )
        metadata = {
            "training_timestamp_utc": datetime.now(UTC).isoformat(),
            "git_commit": git.stdout.strip() if git.returncode == 0 else None,
            "fits": fits,
            "phase2_run_id": phase2.manifest["run_id"],
            "final_training_rows": len(final_training),
            "final_training_end": config.timeline.validation_end,
            "total_seconds": time.perf_counter() - started,
            "model_artifacts": {
                family: f"models/{family}.joblib" for family in FAMILIES
            },
            "uncertainty_method": "separate-chronological-calibration normalized absolute residuals",
            "tracking": "local JSON/Parquet; MLflow optional and deferred",
        }
        write_json(staging / "training_metadata.json", metadata)
        manifest = {
            **expected,
            "artifacts": inventory(staging),
            "plan_sha256": sha256_file(staging / "plan.json"),
        }
        write_json(staging / "manifest.json", manifest)
        os.rename(staging, final)
        manifest = verify_run(final, required=TRAIN_REQUIRED, expected=expected)
        return ModelingResult(
            final,
            manifest,
            selection_metrics,
            {
                "total_seconds": time.perf_counter() - started,
                "fit_seconds": sum(row["seconds"] for row in fits),
            },
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _validate_plan(
    run_dir: Path, manifest: dict[str, Any], plan: dict[str, Any], config: Phase3Config
) -> dict[str, Any]:
    """Check every frozen choice and load models before consuming test access."""
    try:
        baseline_names = [
            "naive",
            f"moving_average_{config.timeline.moving_window}",
            f"seasonal_naive_{config.timeline.seasonal_period}",
        ]
        methods = sorted([*FAMILIES, *baseline_names])
        fixed = {
            "experiment_id": manifest["experiment_id"],
            "dataset_id": manifest["dataset_id"],
            "roles": config.roles(),
            "test_methods": methods,
            "features": list(feature_columns(config.timeline.seasonal_indicators)),
            "seed": config.seed,
            "horizon_weeks": 1,
            "refit_end": config.timeline.validation_end,
            "test_refitting": False,
            "test_product_reselection": False,
        }
        required = set(fixed) | {
            "selected_candidates",
            "best_ml_family",
            "recommended_method",
            "selection_rule",
            "model_hashes",
            "calibration_sha256",
            "cohort_sha256",
        }
        if (
            not isinstance(plan, dict)
            or set(plan) != required
            or any(plan.get(key) != value for key, value in fixed.items())
            or plan["best_ml_family"] not in FAMILIES
            or plan["recommended_method"] not in methods
            or set(plan["selected_candidates"]) != set(FAMILIES)
            or set(plan["model_hashes"]) != set(FAMILIES)
        ):
            raise ArtifactError("Frozen evaluation plan is incomplete or inconsistent")
        candidate_metrics = {
            row["model"]: row
            for row in _json(run_dir / "candidate_metrics.json")["overall"]
        }
        selected = {
            family: min(
                [
                    candidate
                    for candidate in manifest["candidates"]
                    if candidate["family"] == family
                ],
                key=lambda candidate: _rank(candidate_metrics[candidate["id"]]),
            )
            for family in FAMILIES
        }
        selection_metrics = _json(run_dir / "selection_metrics.json")
        best_ml = min(
            [row for row in selection_metrics["overall"] if row["model"] in FAMILIES],
            key=_rank,
        )["model"]
        recommended = min(selection_metrics["overall"], key=_rank)["model"]
        if (
            plan["selected_candidates"] != selected
            or plan["best_ml_family"] != best_ml
            or plan["recommended_method"] != recommended
        ):
            raise ArtifactError(
                "Frozen choices contradict selection-validation metrics"
            )
        calibration = _json(run_dir / "calibration.json")
        if set(calibration) != set(methods) or any(
            pd.Timestamp(row["calibration_end"])
            != monday(config.timeline.validation_end)
            or row["nominal_coverage"] != config.interval_coverage
            or row["scale_floor"] != config.interval_scale_floor
            for row in calibration.values()
        ):
            raise ArtifactError("Frozen calibration contradicts the declared protocol")
        cohort = pd.DataFrame(_json(run_dir / "cohort.json"))
        if (
            cohort.empty
            or len(cohort) > config.timeline.top_products
            or not {"stock_code", "training_units", "active_training_weeks"}.issubset(
                cohort
            )
            or cohort.stock_code.duplicated().any()
        ):
            raise ArtifactError("Frozen product cohort is invalid")
        fitted = {
            family: load_model(
                run_dir / "models" / f"{family}.joblib", plan["model_hashes"][family]
            )
            for family in FAMILIES
        }
        if any(
            model.training_end != monday(config.timeline.validation_end)
            or list(model.feature_names) != fixed["features"]
            or model.candidate != selected[family]
            for family, model in fitted.items()
        ):
            raise ArtifactError(
                "Fitted model boundary/features contradict the frozen plan"
            )
        return fitted
    except (KeyError, TypeError, IndexError) as exc:
        raise ArtifactError("Frozen evaluation plan/artifacts are malformed") from exc


def evaluate_phase3(
    run_dir: Path,
    dataset_dir: Path,
    *,
    ledger_root: Path = Path("data/evaluation-ledger"),
) -> ModelingResult:
    started = time.perf_counter()
    run_dir, dataset_dir, ledger_root = (
        Path(run_dir),
        Path(dataset_dir),
        Path(ledger_root),
    )
    manifest = verify_run(
        run_dir, required=TRAIN_REQUIRED, expected={"state": "frozen_pretest"}
    )
    plan = _json(run_dir / "plan.json")
    if (
        manifest["plan_sha256"] != sha256_file(run_dir / "plan.json")
        or plan["experiment_id"] != manifest["experiment_id"]
    ):
        raise ArtifactError(
            "Frozen plan identity/hash does not match training metadata"
        )
    source = verify_dataset(dataset_dir)
    if source.manifest["dataset_id"] != plan["dataset_id"]:
        raise ArtifactError("Evaluation source differs from the frozen training source")
    config = Phase3Config(**_json(run_dir / "config.json"))
    current_identity = _identity(
        source.manifest["dataset_id"], config, model_candidates(config.seed)
    )
    if any(manifest.get(key) != value for key, value in current_identity.items()):
        raise ArtifactError(
            "Code/runtime/configuration differs from the frozen experiment; do not evaluate changed settings"
        )
    if (
        plan["calibration_sha256"] != sha256_file(run_dir / "calibration.json")
        or plan["cohort_sha256"] != sha256_file(run_dir / "cohort.json")
        or any(
            plan["model_hashes"][family]
            != sha256_file(run_dir / "models" / f"{family}.joblib")
            for family in FAMILIES
        )
    ):
        raise ArtifactError(
            "Frozen model/calibration/cohort hashes do not match artifacts"
        )
    expected = {
        "experiment_id": plan["experiment_id"],
        "dataset_id": plan["dataset_id"],
        "plan_sha256": manifest["plan_sha256"],
        "evaluation_scope": "test",
    }
    fitted_models = _validate_plan(run_dir, manifest, plan, config)
    status = claim_final_evaluation(
        ledger_root, plan["dataset_id"], plan["experiment_id"], manifest["plan_sha256"]
    )
    if status == "complete":
        ledger = verify_cached_evaluation(
            ledger_root,
            plan["dataset_id"],
            plan["experiment_id"],
            manifest["plan_sha256"],
        )
        result_dir = Path(ledger["results_dir"])
        result_manifest = verify_run(
            result_dir, required=TEST_REQUIRED, expected=expected
        )
        return ModelingResult(
            result_dir,
            result_manifest,
            _json(result_dir / "metrics.json"),
            {"total_seconds": time.perf_counter() - started, "cache_reused": 1.0},
        )
    staging = Path(tempfile.mkdtemp(prefix=".test-", dir=run_dir.parent))
    try:
        # FIRST semantic target access: the atomic ledger was claimed above.
        transactions = {
            name: pd.read_parquet(
                dataset_dir / f"{name}.parquet",
                filters=[
                    ("invoice_date", ">=", monday(config.timeline.start_week)),
                    (
                        "invoice_date",
                        "<",
                        monday(config.timeline.test_end) + pd.Timedelta(weeks=1),
                    ),
                ],
            )
            for name in ("purchases", "cancellations", "returns")
        }
        cohort = pd.DataFrame(_json(run_dir / "cohort.json"))
        panel = aggregate_weekly(
            transactions["purchases"],
            transactions["cancellations"],
            transactions["returns"],
            start_week=config.timeline.start_week,
            end_week=config.timeline.test_end,
            products=cohort.stock_code.tolist(),
        )
        features = generate_features(
            panel, seasonal_indicators=config.timeline.seasonal_indicators
        )
        test_features = features.loc[features.week >= config.timeline.test_start].copy()
        parts = []
        prediction_started = time.perf_counter()
        for family in FAMILIES:
            fitted = fitted_models[family]
            parts.append(_ml_rows(fitted, test_features, family, "test"))
        parts.append(
            _baseline_rows(
                panel,
                features,
                pd.date_range(
                    config.timeline.test_start, config.timeline.test_end, freq="W-MON"
                ),
                config,
                "test",
            )
        )
        predictions = add_intervals(
            pd.concat(parts, ignore_index=True), _json(run_dir / "calibration.json")
        )
        prediction_seconds = time.perf_counter() - prediction_started
        earlier = pd.read_parquet(run_dir / "pretest_forecasts.parquet").sort_values(
            ["stock_code", "model"]
        )
        first = predictions.loc[
            predictions.week == config.timeline.test_start
        ].sort_values(["stock_code", "model"])
        if not np.allclose(
            earlier[["prediction", "lower", "upper"]].to_numpy(),
            first[["prediction", "lower", "upper"]].to_numpy(),
            rtol=1e-12,
            atol=1e-9,
        ):
            raise ValueError(
                "First test-origin predictions differ from the frozen pre-test forecasts"
            )
        volumes = cohort[["stock_code", "training_units"]].copy()
        volumes["fold"] = "test"
        metrics = _scoped_metrics(predictions, volumes, "test")
        intervals = interval_metrics(predictions)
        intervals["scope"] = "test"
        predictions.to_parquet(
            staging / "predictions.parquet", index=False, compression="zstd"
        )
        volumes.to_parquet(
            staging / "training_volumes.parquet", index=False, compression="zstd"
        )
        write_json(staging / "metrics.json", metrics)
        write_json(staging / "interval_metrics.json", intervals)
        render_model_plots(
            predictions,
            metrics,
            _json(run_dir / "selection_metrics.json"),
            _json(run_dir / "importance.json")[plan["best_ml_family"]],
            staging / "plots",
            selected_model=plan["best_ml_family"],
            selected_product=str(cohort.iloc[0].stock_code),
        )
        render_diagnostics(predictions, metrics, staging / "plots")
        write_json(
            staging / "evaluation_metadata.json",
            {
                **expected,
                "evaluated_at_utc": datetime.now(UTC).isoformat(),
                "selected_before_test": plan["best_ml_family"],
                "recommended_before_test": plan["recommended_method"],
                "horizon_weeks": 1,
                "test_refitting": False,
                "batch_forecasting_seconds": prediction_seconds,
                "total_seconds": time.perf_counter() - started,
                "test_methods": plan["test_methods"],
                "all_models_frozen_before_test": True,
            },
        )
        result_manifest = {**expected, "artifacts": inventory(staging)}
        write_json(staging / "manifest.json", result_manifest)
        final = run_dir.parent / "evaluations" / plan["experiment_id"]
        final.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, final)
        result_manifest = verify_run(final, required=TEST_REQUIRED, expected=expected)
        complete_final_evaluation(
            ledger_root,
            plan["dataset_id"],
            plan["experiment_id"],
            manifest["plan_sha256"],
            results_dir=final,
            results_manifest_sha256=sha256_file(final / "manifest.json"),
        )
        return ModelingResult(
            final,
            result_manifest,
            metrics,
            {
                "total_seconds": time.perf_counter() - started,
                "batch_forecasting_seconds": prediction_seconds,
            },
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
