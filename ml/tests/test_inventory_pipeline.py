"""Synthetic frozen-forecast workflow; never retrain or read official source rows."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ml.data.acquisition import sha256_file
from ml.evaluation.final_test import (
    claim_final_evaluation,
    complete_final_evaluation,
)
from ml.inventory.config import ScenarioConfig
from ml.inventory.plots import PLOT_FILENAMES, render_inventory_plots
from ml.inventory.simulation import POLICIES
from ml.pipelines.artifacts import inventory, write_json
from ml.pipelines.ingestion import ArtifactError
from ml.pipelines.inventory import (
    METHODS,
    REQUIRED,
    load_frozen_inputs,
    prepare_simulation_inputs,
    run_inventory_scenario,
)

DATASET = "a" * 64
EXPERIMENT = "b" * 64
OTHER = "c" * 64
PRODUCTS = ("SYNTH-A", "SYNTH-B")


def build_frozen_fixture(
    root, *, plan_changes=None, metadata_changes=None, evaluation_changes=None
):
    """Publish an internally checksummed, completed, entirely synthetic experiment."""
    train = root / "frozen" / EXPERIMENT
    evaluation = root / "evaluated" / EXPERIMENT
    ledger = root / "ledger"
    train.mkdir(parents=True)
    evaluation.mkdir(parents=True)
    history_weeks = pd.date_range("2010-12-06", "2011-10-03", freq="W-MON")
    test_weeks = pd.date_range("2011-10-10", "2011-11-28", freq="W-MON")
    calibration_weeks = pd.date_range("2011-09-12", "2011-10-03", freq="W-MON")
    history_values = {
        "SYNTH-A": [0] * 36 + [2, 4, 6, 8, 10, 12, 14, 16],
        "SYNTH-B": [1] * 44,
    }
    weekly = pd.DataFrame(
        [
            {
                "stock_code": code,
                "week": week,
                "gross_units": quantity,
                "returned_units": 0,
                "cancellation_units": 0,
                "net_units": quantity,
                "revenue": float(2 * quantity),
                "transactions": int(quantity > 0),
                "unique_customers": int(quantity > 0),
                "average_price": 2.0 if quantity else np.nan,
            }
            for code, quantities in history_values.items()
            for week, quantity in zip(history_weeks, quantities, strict=True)
        ]
    )
    calibration = []
    for code in ("SYNTH-A", "SYNTH-CALIBRATION-ONLY"):
        for week in calibration_weeks:
            if code == "SYNTH-A":
                offset = history_weeks.get_loc(week)
                actual = history_values[code][offset]
                scale = float(np.mean(history_values[code][offset - 4 : offset]))
                predicted = actual - max(scale, 10.0)
            else:
                actual, scale, predicted = 30, 10.0, 10.0
            calibration.extend(
                {
                    "stock_code": code,
                    "week": week,
                    "actual": actual,
                    "prediction": predicted,
                    "scale": scale,
                    "model": model,
                    "fold": "3",
                }
                for model in sorted(METHODS)
            )
    calibration = pd.DataFrame(calibration)
    actuals = {
        "SYNTH-A": [18, 4, 20, 6, 25, 2, 15, 8],
        "SYNTH-B": [1, 2, 0, 1, 3, 0, 2, 1],
    }
    predictions = []
    for code in PRODUCTS:
        prior = list(history_values[code])
        for week, actual in zip(test_weeks, actuals[code], strict=True):
            scale = float(np.mean(prior[-4:]))
            values = {
                "naive": float(prior[-1]),
                "moving_average_4": scale,
                "seasonal_naive_4": float(prior[-4]),
                "ridge": 0.9 * scale + 1.0,
                "random_forest": 1.1 * scale,
                "xgboost": 0.95 * scale + 0.5,
            }
            for model, predicted in sorted(values.items()):
                predictions.append(
                    {
                        "stock_code": code,
                        "week": week,
                        "actual": actual,
                        "prediction": predicted,
                        "scale": scale,
                        "model": model,
                        "fold": "test",
                        "lower": max(0.0, predicted - 2.0),
                        "upper": predicted + 2.0,
                        "nominal_coverage": 0.8,
                        "uncertainty_label": "synthetic empirical estimate",
                    }
                )
            prior.append(actual)
    predictions = pd.DataFrame(predictions)
    issued = (
        predictions.loc[predictions.week == test_weeks[0]].drop(columns="actual").copy()
    )
    for name, frame in (
        ("pretest_weekly", weekly),
        ("calibration_predictions", calibration),
        ("pretest_forecasts", issued),
    ):
        frame.to_parquet(train / f"{name}.parquet", index=False, compression="zstd")
    predictions.to_parquet(
        evaluation / "predictions.parquet", index=False, compression="zstd"
    )
    plan = {
        "dataset_id": DATASET,
        "experiment_id": EXPERIMENT,
        "horizon_weeks": 1,
        "best_ml_family": "ridge",
        "test_methods": sorted(METHODS),
        "refit_end": "2011-10-03",
        "roles": {
            "calibration_start": "2011-09-12",
            "calibration_end": "2011-10-03",
            "test_start": "2011-10-10",
            "test_end": "2011-11-28",
        },
    } | (plan_changes or {})
    write_json(train / "plan.json", plan)
    plan_hash = sha256_file(train / "plan.json")
    write_json(
        train / "config.json",
        {
            "timeline": {
                "start_week": "2010-12-06",
                "train_end": "2011-07-11",
                "validation_end": "2011-10-03",
                "test_end": "2011-11-28",
                "top_products": 2,
                "n_folds": 3,
                "min_history_weeks": 12,
                "seasonal_period": 4,
                "moving_window": 4,
                "seasonal_indicators": {},
            }
        },
    )
    write_json(
        train / "cohort.json",
        [
            {
                "stock_code": code,
                "training_units": sum(history_values[code]),
                "active_training_weeks": sum(
                    value > 0 for value in history_values[code]
                ),
            }
            for code in PRODUCTS
        ],
    )
    metadata = {
        "dataset_id": DATASET,
        "experiment_id": EXPERIMENT,
        "plan_sha256": plan_hash,
        "evaluation_scope": "test",
        "all_models_frozen_before_test": True,
        "test_refitting": False,
        "selected_before_test": "ridge",
    } | (metadata_changes or {})
    write_json(evaluation / "evaluation_metadata.json", metadata)
    write_json(
        train / "manifest.json",
        {
            "state": "frozen_pretest",
            "dataset_id": DATASET,
            "experiment_id": EXPERIMENT,
            "plan_sha256": plan_hash,
            "artifacts": inventory(train),
        },
    )
    write_json(
        evaluation / "manifest.json",
        {
            "dataset_id": DATASET,
            "experiment_id": EXPERIMENT,
            "plan_sha256": plan_hash,
            "evaluation_scope": "test",
            "artifacts": inventory(evaluation),
        }
        | (evaluation_changes or {}),
    )
    claim_final_evaluation(ledger, DATASET, EXPERIMENT, plan_hash)
    complete_final_evaluation(
        ledger,
        DATASET,
        EXPERIMENT,
        plan_hash,
        results_dir=evaluation,
        results_manifest_sha256=sha256_file(evaluation / "manifest.json"),
    )
    return SimpleNamespace(
        train=train,
        evaluation=evaluation,
        ledger=ledger,
        plan=plan,
        history=weekly,
        calibration=calibration,
        predictions=predictions,
        issued=issued,
    )


@pytest.fixture
def frozen(tmp_path):
    return build_frozen_fixture(tmp_path)


def snapshot(frozen):
    return {
        str(path): sha256_file(path)
        for directory in (frozen.train, frozen.evaluation, frozen.ledger)
        for path in directory.rglob("*")
        if path.is_file()
    }


def prepared(frozen, config=None):
    return prepare_simulation_inputs(
        frozen.train, frozen.evaluation, frozen.plan, config or ScenarioConfig()
    )


def overwrite(path, frame):
    frame.to_parquet(path, index=False, compression="zstd")


def test_frozen_lineage_and_hand_calculated_pretest_assumptions(frozen):
    before = snapshot(frozen)
    plan, lineage, evaluation_dir = load_frozen_inputs(frozen.train, frozen.ledger)
    assert plan == frozen.plan
    assert evaluation_dir == frozen.evaluation.resolve()
    assert lineage["dataset_id"] == DATASET
    assert lineage["experiment_id"] == EXPERIMENT
    assert lineage["selected_ml_family_before_test"] == "ridge"
    demand, forecasts, inputs = prepared(frozen)
    assert set(demand.columns) == {"stock_code", "week", "actual"}
    assert set(forecasts.columns) == {
        "stock_code",
        "week",
        "model",
        "prediction",
        "scale",
    }
    assert demand.shape[0] == 16
    assert not demand.duplicated(["stock_code", "week"]).any()
    assert inputs["SYNTH-A"].fixed_forecast == pytest.approx(72 / 44)
    assert inputs["SYNTH-A"].initial_on_hand == 4
    assert inputs["SYNTH-B"].initial_on_hand == 2
    expected = math.sqrt(2.5)
    for item in inputs.values():
        assert set(item.error_multipliers) == METHODS
        assert all(
            value == pytest.approx(expected)
            for value in item.error_multipliers.values()
        )
    assert inputs["SYNTH-A"].fixed_error_std == pytest.approx(expected * 13)
    assert inputs["SYNTH-B"].fixed_error_std == pytest.approx(expected * 10)
    # Calibration includes a different cohort, and is not filtered by final products.
    assert "SYNTH-CALIBRATION-ONLY" not in inputs
    assert snapshot(frozen) == before


def test_test_residuals_and_future_forecasts_cannot_change_pretest_assumptions(frozen):
    _, _, original = prepared(frozen)
    changed = frozen.predictions.copy()
    changed.loc[changed.week >= "2011-11-07", "actual"] += 100
    changed.loc[changed.week >= "2011-11-07", "prediction"] += 250
    overwrite(frozen.evaluation / "predictions.parquet", changed)
    _, _, later = prepared(frozen)
    assert later == original


@pytest.mark.parametrize(
    "kind", ["duplicate", "missing", "leak", "fractional", "negative", "boolean"]
)
def test_pretest_grid_and_demand_validation(frozen, kind):
    frame = frozen.history.copy()
    if kind == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif kind == "missing":
        frame = frame.iloc[1:]
    elif kind == "leak":
        row = frame.iloc[-1:].copy()
        row["week"] = pd.Timestamp("2011-10-10")
        frame = pd.concat([frame, row], ignore_index=True)
    elif kind == "fractional":
        frame["gross_units"] = frame.gross_units.astype(float)
        frame.loc[0, "gross_units"] = 0.5
    elif kind == "negative":
        frame.loc[0, "gross_units"] = -1
    else:
        frame["gross_units"] = True
    overwrite(frozen.train / "pretest_weekly.parquet", frame)
    with pytest.raises(ValueError):
        prepared(frozen)


@pytest.mark.parametrize("artifact", ["calibration_predictions", "predictions"])
@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "missing",
        "methods",
        "actual_mismatch",
        "scale_mismatch",
        "nan",
        "negative",
    ],
)
def test_calibration_and_forecast_grid_alignment(frozen, artifact, kind):
    frame = (
        frozen.calibration
        if artifact == "calibration_predictions"
        else frozen.predictions
    ).copy()
    if kind == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif kind == "missing":
        frame = frame.iloc[1:]
    elif kind == "methods":
        frame.loc[frame.model == "xgboost", "model"] = "unknown"
    elif kind == "actual_mismatch":
        frame.loc[0, "actual"] += 1
    elif kind == "scale_mismatch":
        frame.loc[0, "scale"] += 1
    elif kind == "nan":
        frame.loc[0, "prediction"] = np.nan
    else:
        frame.loc[0, "prediction"] = -1
    directory = (
        frozen.train if artifact == "calibration_predictions" else frozen.evaluation
    )
    overwrite(directory / f"{artifact}.parquet", frame)
    with pytest.raises(ValueError):
        prepared(frozen)


def test_calibration_cannot_overlap_test_period(frozen):
    plan = dict(frozen.plan)
    plan["roles"] = dict(plan["roles"], calibration_end="2011-10-10")
    with pytest.raises(ValueError, match="Calibration/refit"):
        prepare_simulation_inputs(
            frozen.train, frozen.evaluation, plan, ScenarioConfig()
        )


def test_first_origin_prediction_must_equal_preissued_forecast(frozen):
    changed = frozen.issued.copy()
    changed.loc[0, "prediction"] += 0.25
    overwrite(frozen.train / "pretest_forecasts.parquet", changed)
    with pytest.raises(ArtifactError, match="First-origin"):
        prepared(frozen)


def test_unknown_override_product_rejected_before_simulation(frozen):
    config = ScenarioConfig.from_dict(
        {"products": {"SYNTH-UNKNOWN": {"initial_on_hand": 0}}}
    )
    with pytest.raises(ValueError, match="frozen-cohort"):
        prepared(frozen, config)


def test_per_product_override_does_not_change_other_product(frozen):
    config = ScenarioConfig.from_dict(
        {
            "products": {
                "SYNTH-A": {
                    "initial_on_hand": 7,
                    "parameters": {"service_level": 0.8, "case_pack_size": 2},
                    "initial_orders": [{"week": "2011-10-24", "quantity": 2}],
                }
            }
        }
    )
    _, _, inputs = prepared(frozen, config)
    assert inputs["SYNTH-A"].initial_on_hand == 7
    assert inputs["SYNTH-A"].parameters.service_level == 0.8
    assert inputs["SYNTH-A"].parameters.case_pack_size == 2
    assert inputs["SYNTH-A"].initial_orders[0].quantity == 2
    assert inputs["SYNTH-B"].initial_on_hand == 2
    assert inputs["SYNTH-B"].parameters.service_level == 0.95


@pytest.mark.parametrize(
    "changes",
    [
        {"all_models_frozen_before_test": False},
        {"test_refitting": True},
        {"selected_before_test": "xgboost"},
        {"evaluation_scope": "validation"},
        {"plan_sha256": OTHER},
        {"dataset_id": OTHER},
        {"experiment_id": OTHER},
    ],
)
def test_inconsistent_completed_evaluation_metadata_fails_preflight(tmp_path, changes):
    frozen = build_frozen_fixture(tmp_path, metadata_changes=changes)
    with pytest.raises(ArtifactError):
        load_frozen_inputs(frozen.train, frozen.ledger)


@pytest.mark.parametrize(
    "changes",
    [{"dataset_id": OTHER}, {"plan_sha256": OTHER}, {"evaluation_scope": "validation"}],
)
def test_completed_result_manifest_identity_must_match_frozen_plan(tmp_path, changes):
    frozen = build_frozen_fixture(tmp_path, evaluation_changes=changes)
    with pytest.raises(ArtifactError):
        load_frozen_inputs(frozen.train, frozen.ledger)


@pytest.mark.parametrize(
    "changes",
    [{"horizon_weeks": 2}, {"best_ml_family": "unknown"}, {"test_methods": ["ridge"]}],
)
def test_unsupported_frozen_plan_refused(tmp_path, changes):
    frozen = build_frozen_fixture(tmp_path, plan_changes=changes)
    with pytest.raises(ValueError, match="frozen one-week"):
        load_frozen_inputs(frozen.train, frozen.ledger)


def test_corrupted_source_artifact_fails_before_any_parquet_read(frozen, monkeypatch):
    path = frozen.train / "cohort.json"
    path.write_text(path.read_text() + " ")
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *args, **kwargs: pytest.fail(
            "Data must not load before source integrity verification"
        ),
    )
    with pytest.raises(ArtifactError, match="integrity"):
        load_frozen_inputs(frozen.train, frozen.ledger)


def test_missing_completed_ledger_refuses_inventory_workflow(frozen):
    (frozen.ledger / f"{DATASET}.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        load_frozen_inputs(frozen.train, frozen.ledger)


def test_full_synthetic_pipeline_exports_and_preserves_frozen_files(
    frozen, tmp_path, monkeypatch
):
    original_read = pd.read_parquet
    allowed = {
        frozen.train / "pretest_weekly.parquet",
        frozen.train / "calibration_predictions.parquet",
        frozen.train / "pretest_forecasts.parquet",
        frozen.evaluation / "predictions.parquet",
    }

    def read_only_frozen(path, *args, **kwargs):
        assert (
            path in allowed
        ), "Phase 4 may not read raw transactions or other source tables"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", read_only_frozen)
    before = snapshot(frozen)
    result = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=tmp_path / "inventory"
    )
    assert snapshot(frozen) == before
    assert (
        result.summary["scope"]
        == "retrospective_assumption_driven_inventory_simulation"
    )
    assert result.summary["selected_ml_before_test"] == "ridge"
    assert result.summary["primary_metric"] == "net_inventory_cost"
    assert {row["policy"] for row in result.summary["policies"]} == set(POLICIES)
    assert REQUIRED.issubset(result.manifest["artifacts"])
    assert inventory(result.run_dir) == result.manifest["artifacts"]
    weekly = original_read(result.run_dir / "weekly_results.parquet")
    recommendations = original_read(result.run_dir / "recommendations.parquet")
    assert len(weekly) == len(POLICIES) * len(PRODUCTS) * 8
    assert len(recommendations) == len(weekly)
    assert len(pd.read_csv(result.run_dir / "exports/weekly_results.csv")) == len(
        weekly
    )
    assert len(pd.read_csv(result.run_dir / "exports/recommendations.csv")) == len(
        recommendations
    )
    assert pd.read_csv(result.run_dir / "exports/summary.csv").policy.tolist() == [
        row["policy"] for row in result.summary["policies"]
    ]
    costs = {
        row["policy"]: row["net_inventory_cost"] for row in result.summary["policies"]
    }
    for comparison in result.summary["comparisons"]:
        assert comparison["simulated_savings"] == pytest.approx(
            costs[comparison["baseline_policy"]] - costs["ml_safety_stock"]
        )
    for filename in PLOT_FILENAMES:
        assert (
            (result.run_dir / "plots" / filename)
            .read_bytes()
            .startswith(b"\x89PNG\r\n\x1a\n")
        )
    assert "No real company savings" in (result.run_dir / "report.md").read_text()


def test_completed_inventory_cache_does_not_read_parquet_or_change_inputs(
    frozen, tmp_path, monkeypatch
):
    root = tmp_path / "inventory"
    first = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=root
    )
    before = snapshot(frozen)
    output_bytes = {
        path.relative_to(first.run_dir): path.read_bytes()
        for path in first.run_dir.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *args, **kwargs: pytest.fail(
            "Verified inventory cache must not read transaction/forecast data"
        ),
    )
    second = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=root
    )
    assert second.run_dir == first.run_dir
    assert second.summary == first.summary
    assert second.timings["cache_reused"] == 1.0
    assert snapshot(frozen) == before
    assert {
        path.relative_to(second.run_dir): path.read_bytes()
        for path in second.run_dir.rglob("*")
        if path.is_file()
    } == output_bytes


def test_two_cold_outputs_are_byte_identical_and_config_changes_only_scenario(
    frozen, tmp_path
):
    before = snapshot(frozen)
    first = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=tmp_path / "one"
    )
    second = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=tmp_path / "two"
    )
    assert first.manifest["run_id"] == second.manifest["run_id"]
    assert {
        path.relative_to(first.run_dir): path.read_bytes()
        for path in first.run_dir.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second.run_dir): path.read_bytes()
        for path in second.run_dir.rglob("*")
        if path.is_file()
    }
    changed = run_inventory_scenario(
        frozen.train,
        config=ScenarioConfig.from_dict(
            {"name": "synthetic_sensitivity", "defaults": {"service_level": 0.8}}
        ),
        ledger_root=frozen.ledger,
        output_root=tmp_path / "three",
    )
    assert changed.manifest["run_id"] != first.manifest["run_id"]
    assert changed.manifest["source"] == first.manifest["source"]
    assert snapshot(frozen) == before


@pytest.mark.parametrize("protected", ["training", "evaluation", "ledger"])
def test_outputs_cannot_be_nested_under_frozen_artifacts_or_ledger(frozen, protected):
    root = {
        "training": frozen.train,
        "evaluation": frozen.evaluation,
        "ledger": frozen.ledger,
    }[protected]
    before = snapshot(frozen)
    with pytest.raises(ValueError, match="outside frozen"):
        run_inventory_scenario(
            frozen.train, ledger_root=frozen.ledger, output_root=root / "inventory"
        )
    assert snapshot(frozen) == before


def test_failed_simulation_does_not_publish_partial_run_or_mutate_source(
    frozen, tmp_path, monkeypatch
):
    from ml.pipelines import inventory as module

    before = snapshot(frozen)
    destination = tmp_path / "inventory"

    def fail(*args, **kwargs):
        raise ValueError("synthetic simulation failure")

    monkeypatch.setattr(module, "run_simulation", fail)
    with pytest.raises(ValueError, match="synthetic simulation failure"):
        run_inventory_scenario(
            frozen.train, ledger_root=frozen.ledger, output_root=destination
        )
    assert not destination.exists() or list(destination.iterdir()) == []
    assert snapshot(frozen) == before


def test_plot_failure_cleans_staging_without_publishing_partial_outputs(
    frozen, tmp_path, monkeypatch
):
    from ml.pipelines import inventory as module

    before = snapshot(frozen)
    destination = tmp_path / "inventory"

    def fail(*args, **kwargs):
        raise ValueError("synthetic plotting failure")

    monkeypatch.setattr(module, "render_inventory_plots", fail)
    with pytest.raises(ValueError, match="synthetic plotting failure"):
        run_inventory_scenario(
            frozen.train, ledger_root=frozen.ledger, output_root=destination
        )
    assert destination.is_dir()
    assert list(destination.iterdir()) == []
    assert snapshot(frozen) == before


def test_corrupted_inventory_cache_fails_without_rebuilding(
    frozen, tmp_path, monkeypatch
):
    root = tmp_path / "inventory"
    result = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=root
    )
    path = result.run_dir / "summary.json"
    path.write_text(path.read_text() + " ")
    before = snapshot(frozen)
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *args, **kwargs: pytest.fail(
            "Corrupt cache must fail instead of rebuilding"
        ),
    )
    with pytest.raises(ArtifactError, match="integrity"):
        run_inventory_scenario(
            frozen.train, ledger_root=frozen.ledger, output_root=root
        )
    assert snapshot(frozen) == before


def test_plot_validation_rejects_empty_or_unreconciled_results(frozen, tmp_path):
    with pytest.raises(ValueError, match="measured"):
        render_inventory_plots(pd.DataFrame(), {}, tmp_path / "empty", currency="GBP")
    result = run_inventory_scenario(
        frozen.train, ledger_root=frozen.ledger, output_root=tmp_path / "inventory"
    )
    records = pd.read_parquet(result.run_dir / "weekly_results.parquet")
    changed = json.loads(json.dumps(result.summary))
    changed["policies"][0]["lost_units"] += 1
    with pytest.raises(ValueError, match="reconcile"):
        render_inventory_plots(records, changed, tmp_path / "bad-plots", currency="GBP")


def test_prepare_inputs_is_deterministic_and_does_not_mutate_config(frozen):
    config = ScenarioConfig.from_dict({"products": {"SYNTH-A": {"initial_on_hand": 4}}})
    before = config.to_dict()
    first = prepared(frozen, config)
    second = prepared(frozen, config)
    assert_frame_equal(first[0], second[0])
    assert_frame_equal(first[1], second[1])
    assert first[2] == second[2]
    assert config.to_dict() == before


def test_explicit_initial_stock_skips_unused_overflowing_coverage(frozen):
    config = ScenarioConfig.from_dict(
        {
            "initial_coverage_weeks": np.finfo("float64").max,
            "products": {code: {"initial_on_hand": 1} for code in PRODUCTS},
        }
    )
    _, _, inputs = prepared(frozen, config)
    assert all(item.initial_on_hand == 1 for item in inputs.values())


def test_unoverridden_product_still_validates_derived_initial_stock(frozen):
    config = ScenarioConfig.from_dict(
        {
            "initial_coverage_weeks": np.finfo("float64").max,
            "products": {"SYNTH-B": {"initial_on_hand": 1}},
        }
    )
    with pytest.raises(ValueError, match="coverage overflows"):
        prepared(frozen, config)
