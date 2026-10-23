"""Phase 2: auditable weekly facts and rolling-origin baseline validation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from ml.data.acquisition import canonical_json, sha256_file
from ml.data.weekly import aggregate_weekly, select_top_products
from ml.evaluation.metrics import evaluate_predictions
from ml.evaluation.plots import PLOT_FILENAMES, render_phase2_plots
from ml.evaluation.splits import Phase2Config, expanding_folds, monday, split_manifest
from ml.features.weekly import feature_columns, generate_features
from ml.models.baselines import predict_baselines
from ml.pipelines.ingestion import ArtifactError, verify_dataset

PHASE2_VERSION = "1.0.1"


@dataclass(frozen=True)
class Phase2Result:
    run_dir: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    timings: dict[str, float]


def _read_allowed_transactions(
    dataset_dir: Path, config: Phase2Config
) -> dict[str, pd.DataFrame]:
    # This filter is the test-data boundary, not a filter applied after loading.
    return {
        name: pd.read_parquet(
            dataset_dir / f"{name}.parquet",
            filters=[
                ("invoice_date", ">=", monday(config.start_week)),
                ("invoice_date", "<", config.test_start),
            ],
        )
        for name in ("purchases", "cancellations", "returns")
    }


def _verify_run(run_dir: Path, expected: dict[str, Any]) -> dict[str, Any]:
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text())
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in expected.items()
        ):
            raise ArtifactError("Phase 2 manifest does not match the requested run")
        artifacts = manifest["artifacts"]
        required = (
            {
                "weekly.parquet",
                "validation_predictions.parquet",
                "training_volumes.parquet",
                "metrics.json",
                "config.json",
                "splits.json",
                "selected_products.json",
                "fold_products.json",
                "report.md",
            }
            | {f"plots/{name}" for name in PLOT_FILENAMES}
            | {
                f"features_fold_{i}.parquet"
                for i in range(1, expected["config"]["n_folds"] + 1)
            }
        )
        if not isinstance(artifacts, dict) or not required.issubset(artifacts):
            raise ArtifactError("Phase 2 artifact inventory is incomplete")
        observed = {
            str(path.relative_to(run_dir))
            for path in run_dir.rglob("*")
            if path.is_file()
        } - {"manifest.json"}
        if observed != set(artifacts):
            raise ArtifactError("Phase 2 artifact inventory does not match files")
        for name, info in artifacts.items():
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not isinstance(info, dict)
                or sha256_file(run_dir / name) != info["sha256"]
            ):
                raise ArtifactError("Phase 2 artifact integrity verification failed")
            if name.endswith(".parquet") and pq.read_metadata(
                run_dir / name
            ).num_rows != info.get("rows"):
                raise ArtifactError("Phase 2 artifact row counts do not match")
        metrics = json.loads((run_dir / "metrics.json").read_text())
        if metrics["evaluation_scope"] != "validation":
            raise ArtifactError("Phase 2 cache must contain validation results only")
        if any(
            type(manifest.get(key)) is not int
            or manifest[key] != artifacts[name]["rows"]
            for key, name in (
                ("weekly_rows", "weekly.parquet"),
                ("validation_prediction_rows", "validation_predictions.parquet"),
            )
        ):
            raise ArtifactError("Phase 2 manifest row counts contradict artifacts")
        fold_records = json.loads((run_dir / "fold_products.json").read_text())
        if (
            not isinstance(fold_records, list)
            or len(fold_records) != expected["config"]["n_folds"]
            or manifest.get("selected_products_per_fold")
            != [len(fold["products"]) for fold in fold_records]
            or manifest.get("requested_products") != expected["config"]["top_products"]
        ):
            raise ArtifactError("Phase 2 cohort metadata contradicts configured folds")
        if manifest.get("feature_columns") != list(
            feature_columns(expected["config"]["seasonal_indicators"])
        ):
            raise ArtifactError("Phase 2 feature metadata contradicts configuration")
        return manifest
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ArtifactError("Phase 2 run is incomplete or unreadable") from exc


def _markdown_report(
    config: Phase2Config,
    metrics: dict[str, Any],
    folds: list[dict[str, Any]],
    source_id: str,
) -> str:
    lines = [
        "# Phase 2 baseline validation",
        "",
        f"Dataset: `{source_id}`",
        "",
        "Evaluation: one-week-ahead rolling origins in validation only. The reserved test block was not loaded or evaluated.",
        "",
        "| Model | MAE (units) | RMSE (units) | WAPE (%) | sMAPE (%) | Bias (units) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in metrics["overall"]:

        def display(key: str, row: dict[str, Any] = row) -> str:
            return "undefined" if row[key] is None else f"{row[key]:.4f}"

        lines.append(
            f"| {row['model']} | {display('mae')} | {display('rmse')} | {display('wape')} | {display('smape')} | {display('bias')} |"
        )
    lines += [
        "",
        "## Training-only cohorts",
        "",
        "| Fold | Training end | Validation start | Validation end | Eligible selected |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for fold in folds:
        lines.append(
            f"| {fold['fold']} | {fold['train_end']} | {fold['validation_start']} | {fold['validation_end']} | {len(fold['products'])} |"
        )
    lines += [
        "",
        "All methods share each fold's cohort; cohorts may change between folds. Rank/segment inputs use training gross units only. Previous completed validation weeks may inform the next one-week forecast; they cannot inform earlier forecasts.",
        "",
        f"Seasonal recurrence period: {config.seasonal_period} weeks (configured assumption, not established seasonality). No annual-seasonality claim, fitted ML model, business result or test-set score is made.",
        "",
        "The gross-unit target is independent from net accounting movements. Zero weeks mean no recorded purchases, not evidence of availability or unconstrained demand. Missing selling price/rate/feature warm-up remains null.",
        "",
        "## Plots",
        "",
        "![Validation metric comparison](plots/baseline_metrics.png)",
        "",
        "![Validation demand and error over time](plots/validation_demand.png)",
        "",
        "![Residuals and forecast direction](plots/residuals_and_bias.png)",
        "",
        "![Errors for products selected by training volume](plots/product_errors.png)",
        "",
    ]
    return "\n".join(lines)


def run_phase2(
    dataset_dir: Path, output_root: Path, config: Phase2Config | None = None
) -> Phase2Result:
    """Build immutable analytical artifacts with no test targets and no fitted ML.

    Files are private local outputs. Version/config/source/runtime identities
    determine a run; measured durations appear only in returned/log metadata.
    """
    started = time.perf_counter()
    if config is None:
        config = Phase2Config()
    if not isinstance(config, Phase2Config):
        raise ValueError("config must be a validated Phase2Config")
    # Frozen dataclasses can contain mutable maps. Revalidate a detached snapshot.
    config = Phase2Config(**config.to_dict())
    dataset_dir, output_root = Path(dataset_dir), Path(output_root)
    source = verify_dataset(dataset_dir)
    coverage = source.report["date_range"]
    if (
        coverage["start"] is None
        or monday(config.start_week) < pd.Timestamp(coverage["start"])
        or monday(config.test_end) + pd.Timedelta(weeks=1)
        > pd.Timestamp(coverage["end"])
    ):
        raise ValueError(
            "Source coverage does not contain all configured complete weeks; supply explicit valid split dates"
        )
    identity = {
        "phase2_version": PHASE2_VERSION,
        "dataset_id": source.manifest["dataset_id"],
        "config": config.to_dict(),
        "dependency_versions": {
            name: version(name) for name in ("pandas", "numpy", "pyarrow", "matplotlib")
        },
    }
    run_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    expected = {
        **identity,
        "run_id": run_id,
        "test_status": "reserved_unread_unevaluated",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / run_id
    if final.exists():
        manifest = _verify_run(final, expected)
        metrics = json.loads((final / "metrics.json").read_text())
        return Phase2Result(
            final,
            manifest,
            metrics,
            {
                "total_seconds": round(time.perf_counter() - started, 6),
                "cache_reused": 1.0,
            },
        )

    staging = Path(tempfile.mkdtemp(prefix=".phase2-", dir=output_root))
    timings: dict[str, float] = {}
    try:
        tick = time.perf_counter()
        transactions = _read_allowed_transactions(dataset_dir, config)
        panel = aggregate_weekly(
            transactions["purchases"],
            transactions["cancellations"],
            transactions["returns"],
            start_week=config.start_week,
            end_week=config.validation_end,
        )
        timings["weekly_aggregation_seconds"] = round(time.perf_counter() - tick, 6)
        panel.to_parquet(staging / "weekly.parquet", index=False, compression="zstd")
        folds = expanding_folds(config)
        fold_records, forecasts, training_volumes = [], [], []
        feature_seconds = baseline_seconds = 0.0
        for fold in folds:
            # Product selection is bounded by this fold, never by all validation.
            selected = select_top_products(
                panel,
                train_end=fold.train_end,
                top_n=config.top_products,
                min_history_weeks=config.min_history_weeks,
            )
            if selected.empty:
                raise ValueError(
                    "No eligible products at a configured training boundary"
                )
            products = selected.to_dict(orient="records")
            fold_records.append({**fold.to_dict(), "products": products})
            volume = selected[["stock_code", "training_units"]].copy()
            volume["fold"] = str(fold.fold)
            training_volumes.append(volume)
            cohort = panel.loc[
                panel.stock_code.isin(selected.stock_code)
                & (panel.week <= fold.validation_end)
            ].copy()
            tick = time.perf_counter()
            features = generate_features(
                cohort, seasonal_indicators=config.seasonal_indicators
            )
            feature_seconds += time.perf_counter() - tick
            features.to_parquet(
                staging / f"features_fold_{fold.fold}.parquet",
                index=False,
                compression="zstd",
            )
            for target_week in pd.date_range(
                fold.validation_start, fold.validation_end, freq="W-MON"
            ):
                history = cohort.loc[
                    cohort.week < target_week, ["stock_code", "week", "gross_units"]
                ]
                tick = time.perf_counter()
                predicted = predict_baselines(
                    history,
                    target_week,
                    seasonal_period=config.seasonal_period,
                    moving_window=config.moving_window,
                )
                baseline_seconds += time.perf_counter() - tick
                actual = cohort.loc[
                    cohort.week == target_week, ["stock_code", "week", "gross_units"]
                ].rename(columns={"gross_units": "actual"})
                scored = predicted.merge(
                    actual, on=["stock_code", "week"], validate="many_to_one"
                )
                if len(scored) != len(selected) * 3:
                    raise ValueError(
                        "Baselines did not return three aligned predictions per product"
                    )
                scored["fold"] = str(fold.fold)
                forecasts.append(scored)
        timings["feature_generation_seconds"] = round(feature_seconds, 6)
        timings["baseline_prediction_seconds"] = round(baseline_seconds, 6)
        predictions = (
            pd.concat(forecasts, ignore_index=True)
            .sort_values(["fold", "week", "stock_code", "model"], kind="stable")
            .reset_index(drop=True)
        )
        volumes = pd.concat(training_volumes, ignore_index=True)
        metrics = evaluate_predictions(predictions, training_volumes=volumes)
        predictions.to_parquet(
            staging / "validation_predictions.parquet", index=False, compression="zstd"
        )
        volumes.to_parquet(
            staging / "training_volumes.parquet", index=False, compression="zstd"
        )
        splits = split_manifest(config)
        for name, value in {
            "config.json": config.to_dict(),
            "splits.json": splits,
            "selected_products.json": fold_records[0]["products"],
            "fold_products.json": fold_records,
            "metrics.json": metrics,
        }.items():
            (staging / name).write_text(canonical_json(value), encoding="utf-8")
        tick = time.perf_counter()
        render_phase2_plots(predictions, metrics, staging / "plots")
        timings["plot_generation_seconds"] = round(time.perf_counter() - tick, 6)
        (staging / "report.md").write_text(
            _markdown_report(
                config, metrics, fold_records, source.manifest["dataset_id"]
            ),
            encoding="utf-8",
        )
        artifacts = {}
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                info: dict[str, Any] = {"sha256": sha256_file(path)}
                if path.suffix == ".parquet":
                    info["rows"] = pq.read_metadata(path).num_rows
                artifacts[str(path.relative_to(staging))] = info
        manifest = {
            **expected,
            "artifacts": artifacts,
            "feature_columns": feature_columns(config.seasonal_indicators),
            "weekly_rows": len(panel),
            "validation_prediction_rows": len(predictions),
            "requested_products": config.top_products,
            "selected_products_per_fold": [
                len(fold["products"]) for fold in fold_records
            ],
        }
        (staging / "manifest.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
        try:
            os.rename(staging, final)
        except OSError:
            if not final.exists():
                raise
        manifest = _verify_run(final, expected)
        timings["total_seconds"] = round(time.perf_counter() - started, 6)
        return Phase2Result(final, manifest, metrics, timings)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
