"""Verified frozen-forecast inputs to reproducible retrospective inventory scenarios."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.data.acquisition import canonical_json, sha256_file
from ml.evaluation.final_test import verify_cached_evaluation
from ml.inventory.config import ScenarioConfig, week_start
from ml.inventory.planning import MAX_UNITS, validate_units
from ml.inventory.plots import PLOT_FILENAMES, render_inventory_plots
from ml.inventory.simulation import ProductSimulationInput, run_simulation
from ml.pipelines.artifacts import inventory, verify_run, write_json
from ml.pipelines.ingestion import ArtifactError

PHASE4_VERSION = "1.0.0"
METHODS = {
    "naive",
    "moving_average_4",
    "seasonal_naive_4",
    "ridge",
    "random_forest",
    "xgboost",
}
REQUIRED = {
    "config.json",
    "lineage.json",
    "product_inputs.json",
    "demand.parquet",
    "weekly_results.parquet",
    "orders.parquet",
    "recommendations.parquet",
    "summary.json",
    "report.md",
    "exports/summary.csv",
    "exports/recommendations.csv",
    "exports/weekly_results.csv",
} | {f"plots/{name}" for name in PLOT_FILENAMES}


@dataclass(frozen=True)
class InventoryRunResult:
    run_dir: Path
    manifest: dict[str, Any]
    summary: dict[str, Any]
    timings: dict[str, float]


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if not {"stock_code", "week"}.issubset(result):
        raise ValueError("Frozen input requires stock_code and week")
    if result.stock_code.map(
        lambda x: not isinstance(x, str) or not x.strip() or x != x.strip()
    ).any():
        raise ValueError("Frozen product codes must be nonempty text")
    result["week"] = result.week.map(week_start)
    return result


def _nonnegative(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        if column not in frame:
            raise ValueError(f"Frozen input missing {column}")
        values = frame[column]
        if values.map(
            lambda x: isinstance(x, bool | np.bool_) or not isinstance(x, Real)
        ).any():
            raise ValueError(f"{column} cannot contain boolean values")
        try:
            numbers = values.to_numpy(dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{column} must be numeric") from exc
        if (
            not np.isfinite(numbers).all()
            or (numbers < 0).any()
            or (numbers > MAX_UNITS).any()
        ):
            raise ValueError(f"{column} must contain finite nonnegative values")


def _grid(
    frame: pd.DataFrame,
    products: set[str],
    weeks: pd.DatetimeIndex,
    *,
    methods: set[str] | None = None,
) -> None:
    if methods and "model" not in frame:
        raise ValueError("Frozen forecasts require model identifiers")
    keys = ["stock_code", "week"] + (["model"] if methods else [])
    expected = len(products) * len(weeks) * (len(methods) if methods else 1)
    if (
        frame.duplicated(keys).any()
        or len(frame) != expected
        or set(frame.stock_code) != products
        or set(frame.week) != set(weeks)
    ):
        raise ValueError("Frozen input must have a complete unique product-week grid")
    if methods and set(frame.model) != methods:
        raise ValueError(
            "Frozen forecast methods do not match the declared six methods"
        )
    # Count each product/method separately; total counts alone cannot prove coverage.
    for _, group in frame.groupby(["stock_code"] + (["model"] if methods else [])):
        if set(group.week) != set(weeks):
            raise ValueError("Frozen input has missing product weeks")


def _aligned(frame: pd.DataFrame) -> None:
    if (
        (
            frame.groupby(["stock_code", "week"])[["actual", "scale"]].nunique(
                dropna=False
            )
            != 1
        )
        .any()
        .any()
    ):
        raise ValueError(
            "Actual demand and known scale must agree across forecast methods"
        )
    for value in frame.actual:
        validate_units(value, "historical demand")


def load_frozen_inputs(
    run_dir: Path, ledger_root: Path
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Verify completed lineage without loading models or source transactions."""
    training = verify_run(
        run_dir,
        required={
            "plan.json",
            "config.json",
            "cohort.json",
            "pretest_weekly.parquet",
            "calibration_predictions.parquet",
            "pretest_forecasts.parquet",
        },
        expected={"state": "frozen_pretest"},
    )
    plan = _read(run_dir / "plan.json")
    if (
        not isinstance(plan, dict)
        or plan.get("horizon_weeks") != 1
        or set(plan.get("test_methods", [])) != METHODS
        or plan.get("best_ml_family") not in {"ridge", "random_forest", "xgboost"}
    ):
        raise ValueError("Phase 4 requires a frozen one-week six-method Phase 3 plan")
    if (
        training.get("experiment_id") != plan.get("experiment_id")
        or training.get("dataset_id") != plan.get("dataset_id")
        or training.get("plan_sha256") != sha256_file(run_dir / "plan.json")
    ):
        raise ArtifactError(
            "Frozen plan identity/hash does not match its training manifest"
        )
    entry = verify_cached_evaluation(
        ledger_root,
        plan["dataset_id"],
        plan["experiment_id"],
        sha256_file(run_dir / "plan.json"),
    )
    evaluation_dir = Path(entry["results_dir"])
    verify_run(
        evaluation_dir,
        required={"predictions.parquet", "evaluation_metadata.json"},
        expected={
            "experiment_id": plan["experiment_id"],
            "dataset_id": plan["dataset_id"],
            "plan_sha256": sha256_file(run_dir / "plan.json"),
            "evaluation_scope": "test",
        },
    )
    metadata = _read(evaluation_dir / "evaluation_metadata.json")
    if (
        metadata.get("dataset_id") != plan["dataset_id"]
        or metadata.get("experiment_id") != plan["experiment_id"]
        or metadata.get("plan_sha256") != sha256_file(run_dir / "plan.json")
        or metadata.get("evaluation_scope") != "test"
        or metadata.get("all_models_frozen_before_test") is not True
        or metadata.get("test_refitting") is not False
        or metadata.get("selected_before_test") != plan["best_ml_family"]
    ):
        raise ArtifactError(
            "Completed forecast evaluation does not match the frozen plan"
        )
    lineage = {
        "dataset_id": plan["dataset_id"],
        "experiment_id": plan["experiment_id"],
        "training_manifest_sha256": sha256_file(run_dir / "manifest.json"),
        "evaluation_manifest_sha256": sha256_file(evaluation_dir / "manifest.json"),
        "plan_sha256": sha256_file(run_dir / "plan.json"),
        "evaluation_ledger_sha256": sha256_file(
            ledger_root / f"{plan['dataset_id']}.json"
        ),
        "scope": "retrospective inventory simulation using already-evaluated frozen forecasts",
        "selected_ml_family_before_test": plan["best_ml_family"],
    }
    return plan, lineage, evaluation_dir


def prepare_simulation_inputs(
    run_dir: Path, evaluation_dir: Path, plan: dict[str, Any], config: ScenarioConfig
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, ProductSimulationInput]]:
    """Derive stock/error assumptions exclusively from pre-test facts/calibration."""
    cohort = _read(run_dir / "cohort.json")
    if (
        not isinstance(cohort, list)
        or not cohort
        or any(
            not isinstance(r, dict) or not isinstance(r.get("stock_code"), str)
            for r in cohort
        )
    ):
        raise ValueError("Frozen cohort must contain product records")
    products = {r["stock_code"] for r in cohort}
    if len(products) != len(cohort) or set(config.products) - products:
        raise ValueError(
            "Scenario overrides must reference unique frozen-cohort products"
        )
    roles = plan["roles"]
    test_weeks = pd.date_range(
        week_start(roles["test_start"]), week_start(roles["test_end"]), freq="W-MON"
    )
    calibration_weeks = pd.date_range(
        week_start(roles["calibration_start"]),
        week_start(roles["calibration_end"]),
        freq="W-MON",
    )
    if (
        test_weeks.empty
        or calibration_weeks.empty
        or calibration_weeks[-1] >= test_weeks[0]
        or week_start(plan["refit_end"]) != calibration_weeks[-1]
    ):
        raise ValueError("Calibration/refit must end before the simulation horizon")
    timeline = _read(run_dir / "config.json")["timeline"]
    history_weeks = pd.date_range(
        week_start(timeline["start_week"]), week_start(plan["refit_end"]), freq="W-MON"
    )
    if (
        len(history_weeks) < 4
        or history_weeks[-1] + pd.Timedelta(weeks=1) != test_weeks[0]
    ):
        raise ValueError("Pre-test history must end immediately before testing")
    history = _dates(pd.read_parquet(run_dir / "pretest_weekly.parquet"))
    _nonnegative(history, ("gross_units",))
    _grid(history, products, history_weeks)
    for value in history.gross_units:
        validate_units(value, "pre-test demand")
    calibration = _dates(pd.read_parquet(run_dir / "calibration_predictions.parquet"))
    _nonnegative(calibration, ("actual", "prediction", "scale"))
    _grid(calibration, set(calibration.stock_code), calibration_weeks, methods=METHODS)
    _aligned(calibration)
    calibration["normalized_squared_error"] = (
        (calibration.actual - calibration.prediction)
        / calibration.scale.clip(lower=10.0)
    ) ** 2
    if not np.isfinite(calibration.normalized_squared_error).all():
        raise ValueError("Calibration error estimate overflow")
    multipliers = {
        str(name): math.sqrt(float(rows.normalized_squared_error.mean()))
        for name, rows in calibration.groupby("model")
    }
    forecasts = _dates(pd.read_parquet(evaluation_dir / "predictions.parquet"))
    _nonnegative(forecasts, ("actual", "prediction", "scale"))
    _grid(forecasts, products, test_weeks, methods=METHODS)
    _aligned(forecasts)
    # Validate previously-issued first forecasts; bounds are not inventory inputs.
    issued = _dates(pd.read_parquet(run_dir / "pretest_forecasts.parquet"))
    _nonnegative(issued, ("prediction", "scale"))
    _grid(issued, products, test_weeks[:1], methods=METHODS)
    key = ["stock_code", "week", "model"]
    first = forecasts.loc[forecasts.week == test_weeks[0]].sort_values(key)
    old = issued.sort_values(key)
    if not np.allclose(
        first[["prediction", "scale"]], old[["prediction", "scale"]], rtol=0, atol=1e-9
    ):
        raise ArtifactError(
            "First-origin forecasts differ from frozen pre-test issuance"
        )
    inputs = {}
    for code, group in history.groupby("stock_code", sort=True):
        group = group.sort_values("week")
        mean = float(group.gross_units.mean())
        override = config.products.get(str(code), {})
        if "initial_on_hand" in override:
            derived = override["initial_on_hand"]
        else:
            initial = mean * config.initial_coverage_weeks
            if not math.isfinite(initial):
                raise ValueError("Initial inventory coverage overflows")
            derived = math.ceil(initial)
        validate_units(derived, "derived initial inventory")
        inputs[str(code)] = config.product_input(
            str(code),
            derived_on_hand=derived,
            fixed_forecast=mean,
            fixed_error_std=multipliers["moving_average_4"]
            * max(float(group.gross_units.tail(4).mean()), 10.0),
            error_multipliers=multipliers,
        )
    demand = (
        forecasts[["stock_code", "week", "actual"]]
        .drop_duplicates()
        .sort_values(["stock_code", "week"])
        .reset_index(drop=True)
    )
    return (
        demand,
        forecasts[["stock_code", "week", "model", "prediction", "scale"]].copy(),
        inputs,
    )


def _identity(lineage: dict[str, Any], config: ScenarioConfig) -> dict[str, Any]:
    import ml.inventory.config as config_module
    import ml.inventory.planning as planning_module
    import ml.inventory.plots as plots_module
    import ml.inventory.simulation as simulation_module

    return {
        "phase4_version": PHASE4_VERSION,
        "source": lineage,
        "config": config.to_dict(),
        "runtime": {
            name: version(name) for name in ("numpy", "pandas", "pyarrow", "matplotlib")
        },
        "code_hashes": {
            name: sha256_file(Path(module.__file__))
            for name, module in (
                ("configuration", config_module),
                ("planning", planning_module),
                ("simulation", simulation_module),
                ("plots", plots_module),
            )
        },
        "pipeline_sha256": sha256_file(Path(__file__)),
    }


def _serialize_inputs(
    inputs: dict[str, ProductSimulationInput],
) -> list[dict[str, Any]]:
    return [
        {
            "stock_code": code,
            "parameters": asdict(item.parameters),
            "initial_on_hand": item.initial_on_hand,
            "fixed_forecast": item.fixed_forecast,
            "fixed_error_std": item.fixed_error_std,
            "error_multipliers": dict(item.error_multipliers),
            "initial_orders": [
                {
                    "week": pd.Timestamp(order.week).date().isoformat(),
                    "quantity": order.quantity,
                }
                for order in item.initial_orders
            ],
        }
        for code, item in sorted(inputs.items())
    ]


def _report(summary: dict[str, Any], run_id: str, lineage: dict[str, Any]) -> str:
    lines = [
        "# Retrospective simulated inventory comparison",
        "",
        f"Scenario: {summary['scenario']}; currency: {summary['currency']} (illustrative).",
        f"Run: `{run_id}`; frozen forecast experiment: `{lineage['experiment_id']}`.",
        "",
        "Historical purchases supply simulated demand; forecasts were already evaluated in Phase 3. Costs, stock and supplier parameters are assumptions, not observed business facts. No policy or model was selected from these outcomes. Primary metric is terminal-adjusted net inventory cost; cash cost is reported separately. No real company savings are claimed.",
        "",
        "| Policy | Net inventory cost | Gross cash cost | Fill rate | Weekly no-stockout service | Lost units | Average on-hand |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["policies"]:
        lines.append(
            f"| {row['policy']} | {row['net_inventory_cost']:.4f} | {row['gross_cash_cost']:.4f} | {row['fill_rate']:.4%} | {row['service_level']:.4%} | {row['lost_units']} | {row['average_inventory']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Signed simulated ML savings",
            "",
            "Positive means ML has lower assumed cost; negative means ML is more expensive. These compare complete policies, with moving_average_safety_stock providing a matched controller.",
            "",
            "| Baseline | Baseline net cost minus ML net cost | Percent of baseline |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in summary["comparisons"]:
        pct = (
            "undefined (zero baseline cost)"
            if row["simulated_savings_percent"] is None
            else f"{row['simulated_savings_percent']:.4f}%"
        )
        lines.append(
            f"| {row['baseline_policy']} | {row['simulated_savings']:.4f} | {pct} |"
        )
    lines.extend(
        [
            "",
            "## Timing and limitations",
            "",
            "End-week orders wait L complete future demand weeks and arrive before demand in t+L+1. Only the forecast for t+1 is available at review; flat carry-forward approximates all lead/review weeks. No final-week orders are placed; late pipeline remains valued. Full terminal recoverability at purchase cost is assumed. Fill rate and weekly service are distinct from the Gaussian service input. The eight-week experiment is truncated and historical, not steady-state or future operational evidence.",
            "",
            "See docs/INVENTORY_METHODOLOGY.md for formulas/defaults, CSV exports for real generated records and summary.json for complete product/policy costs and accounting definitions.",
            "",
        ]
    )
    return "\n".join(lines)


def run_inventory_scenario(
    run_dir: Path,
    *,
    config: ScenarioConfig | None = None,
    output_root: Path = Path("artifacts/phase4"),
    ledger_root: Path = Path("data/evaluation-ledger"),
) -> InventoryRunResult:
    start = time.perf_counter()
    if config is None:
        config = ScenarioConfig()
    if not isinstance(config, ScenarioConfig):
        raise ValueError("config must be a validated ScenarioConfig or None")
    config = ScenarioConfig.from_dict(config.to_dict())
    plan, lineage, evaluation_dir = load_frozen_inputs(run_dir, ledger_root)
    for protected in (run_dir.parent, evaluation_dir.parent, ledger_root):
        if output_root.resolve().is_relative_to(protected.resolve()):
            raise ValueError(
                "Inventory outputs must be outside frozen Phase 3 and ledger directories"
            )
    identity = _identity(lineage, config)
    run_id = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    destination = output_root / run_id
    expected = {**identity, "run_id": run_id, "state": "complete"}
    if destination.exists():
        manifest = verify_run(destination, required=REQUIRED, expected=expected)
        return InventoryRunResult(
            destination,
            manifest,
            _read(destination / "summary.json"),
            {"cache_reused": 1.0, "total_seconds": time.perf_counter() - start},
        )
    demand, forecasts, inputs = prepare_simulation_inputs(
        run_dir, evaluation_dir, plan, config
    )
    simulation_start = time.perf_counter()
    result = run_simulation(
        demand, forecasts, inputs, selected_model=plan["best_ml_family"]
    )
    simulation_seconds = time.perf_counter() - simulation_start
    summary = dict(result.summary)
    summary.update(
        {
            "scenario": config.name,
            "currency": config.currency,
            "primary_metric": "net_inventory_cost",
            "scope": "retrospective_assumption_driven_inventory_simulation",
            "source_forecast_experiment": plan["experiment_id"],
            "selected_ml_before_test": plan["best_ml_family"],
        }
    )
    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".inventory-", dir=output_root))
    try:
        write_json(stage / "config.json", config.to_dict())
        write_json(stage / "lineage.json", lineage)
        write_json(stage / "product_inputs.json", _serialize_inputs(inputs))
        write_json(stage / "summary.json", summary)
        demand.to_parquet(stage / "demand.parquet", index=False, compression="zstd")
        for name, frame in (
            ("weekly_results", result.records),
            ("orders", result.orders),
            ("recommendations", result.recommendations),
        ):
            frame.to_parquet(stage / f"{name}.parquet", index=False, compression="zstd")
        (stage / "exports").mkdir()
        pd.DataFrame(summary["policies"]).to_csv(
            stage / "exports/summary.csv", index=False
        )
        result.records.to_csv(stage / "exports/weekly_results.csv", index=False)
        result.recommendations.to_csv(
            stage / "exports/recommendations.csv", index=False
        )
        (stage / "report.md").write_text(_report(summary, run_id, lineage))
        render_inventory_plots(
            result.records, summary, stage / "plots", currency=config.currency
        )
        manifest = {**expected, "artifacts": inventory(stage)}
        write_json(stage / "manifest.json", manifest)
        verify_run(stage, required=REQUIRED, expected=expected)
        try:
            stage.rename(destination)
        except OSError:
            if not destination.exists():
                raise
            manifest = verify_run(destination, required=REQUIRED, expected=expected)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return InventoryRunResult(
        destination,
        manifest,
        summary,
        {
            "simulation_seconds": simulation_seconds,
            "total_seconds": time.perf_counter() - start,
        },
    )
