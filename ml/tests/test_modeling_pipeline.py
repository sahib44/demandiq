"""Synthetic full training/evaluation checks; never access the official test block."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.evaluation.splits import Phase2Config
from ml.models.config import Phase3Config
from ml.pipelines import modeling
from ml.pipelines.ingestion import ArtifactError, ingest_dataset


def config():
    return Phase3Config(
        timeline=Phase2Config(
            start_week="2011-01-03",
            train_end="2011-04-18",
            validation_end="2011-05-30",
            test_end="2011-06-27",
            top_products=2,
            min_history_weeks=12,
        )
    )


def make_source(tmp_path, heldout=10, calibration=5, suffix=""):
    rows = []
    for index, week in enumerate(
        pd.date_range("2011-01-03", "2011-07-04", freq="W-MON")
    ):
        for code, base in (("SYNTH-A", 5), ("SYNTH-B", 3), ("SYNTH-C", 1)):
            units = base + index % 4
            if week >= pd.Timestamp("2011-06-06"):
                units = heldout
            elif week >= pd.Timestamp("2011-05-23"):
                units = calibration
            rows.append(
                {
                    "InvoiceNo": f"TEST-{index}-{code}",
                    "StockCode": code,
                    "Description": "SYNTHETIC",
                    "Quantity": units,
                    "InvoiceDate": week.isoformat(),
                    "UnitPrice": 1,
                    "CustomerID": None,
                    "Country": "Testland",
                }
            )
    path = tmp_path / f"synthetic{suffix}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return ingest_dataset(path, tmp_path / "sources").dataset_dir


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("models")
    source = make_source(root)
    trained = modeling.train_phase3(
        source,
        root / "trained",
        config=config(),
        phase2_root=root / "phase2",
        ledger_root=root / "ledger",
    )
    return root, source, trained


def test_selection_calibration_and_saved_artifacts_are_separate(completed):
    _, _, result = completed
    plan = json.loads((result.run_dir / "plan.json").read_text())
    selection = pd.read_parquet(result.run_dir / "selection_predictions.parquet")
    calibration = pd.read_parquet(result.run_dir / "calibration_predictions.parquet")
    assert selection.week.max() < calibration.week.min()
    assert selection.week.max() == pd.Timestamp("2011-05-16")
    assert calibration.week.min() == pd.Timestamp("2011-05-23")
    assert calibration.week.max() < config().timeline.test_start
    assert set(selection.model) == set(plan["test_methods"])
    assert len(plan["selected_candidates"]) == 3
    assert result.metrics["evaluation_scope"] == "selection_validation"
    assert all(row["n_observations"] == 8 for row in result.metrics["overall"])
    assert all(
        (result.run_dir / "models" / f"{family}.joblib").exists()
        for family in modeling.FAMILIES
    )
    assert set(
        pd.read_parquet(result.run_dir / "pretest_forecasts.parquet").columns
    ).isdisjoint({"actual"})


def test_heldout_perturbation_cannot_change_training_or_selection(completed):
    root, _, a = completed
    source_b = make_source(root, heldout=999999, suffix="future")
    b = modeling.train_phase3(
        source_b,
        root / "replica",
        config=config(),
        phase2_root=root / "phase2",
        ledger_root=root / "other-ledger",
    )
    assert a.metrics == b.metrics
    plan_a = json.loads((a.run_dir / "plan.json").read_text())
    plan_b = json.loads((b.run_dir / "plan.json").read_text())
    assert plan_a["selected_candidates"] == plan_b["selected_candidates"]
    assert plan_a["best_ml_family"] == plan_b["best_ml_family"]
    for filename in (
        "selection_predictions.parquet",
        "calibration_predictions.parquet",
        "pretest_forecasts.parquet",
    ):
        pd.testing.assert_frame_equal(
            pd.read_parquet(a.run_dir / filename), pd.read_parquet(b.run_dir / filename)
        )


def test_calibration_targets_do_not_select_candidates(completed):
    root, _, a = completed
    source_b = make_source(root, calibration=999, suffix="calibration")
    b = modeling.train_phase3(
        source_b,
        root / "calib",
        config=config(),
        phase2_root=root / "phase2",
        ledger_root=root / "calib-ledger",
    )
    assert a.metrics == b.metrics
    selected_a = json.loads((a.run_dir / "plan.json").read_text())[
        "selected_candidates"
    ]
    selected_b = json.loads((b.run_dir / "plan.json").read_text())[
        "selected_candidates"
    ]
    assert selected_a == selected_b
    assert json.loads((a.run_dir / "calibration.json").read_text()) != json.loads(
        (b.run_dir / "calibration.json").read_text()
    )


def test_full_final_evaluation_is_claimed_before_reads_and_reused_without_targets(
    completed, monkeypatch
):
    root, source, train = completed
    real_reader = modeling.pd.read_parquet
    test_reads = []

    def guarded(path, **kwargs):
        if Path(path).parent == source:
            ledger = root / "ledger" / f"{source.name}.json"
            assert ledger.exists()
            assert json.loads(ledger.read_text())["status"] == "running"
            test_reads.append(str(path))
        return real_reader(path, **kwargs)

    monkeypatch.setattr(modeling.pd, "read_parquet", guarded)
    result = modeling.evaluate_phase3(
        train.run_dir, source, ledger_root=root / "ledger"
    )
    assert len(test_reads) == 3
    assert result.metrics["evaluation_scope"] == "test"
    assert len(result.metrics["overall"]) == 6
    assert all(row["n_observations"] == 8 for row in result.metrics["overall"])
    predictions = real_reader(result.run_dir / "predictions.parquet")
    assert (predictions.lower >= 0).all()
    assert (predictions.upper >= predictions.prediction).all()
    assert predictions.week.min() == config().timeline.test_start
    assert predictions.week.max() == pd.Timestamp(config().timeline.test_end)
    assert all(
        (result.run_dir / "plots" / name).exists()
        for name in modeling.MODEL_PLOT_FILENAMES
    )
    monkeypatch.setattr(
        modeling.pd,
        "read_parquet",
        lambda *args, **kwargs: pytest.fail(
            "Completed final test must not reload targets"
        ),
    )
    cached = modeling.evaluate_phase3(
        train.run_dir, source, ledger_root=root / "ledger"
    )
    assert cached.metrics == result.metrics
    assert cached.timings["cache_reused"] == 1


def test_post_test_alternative_training_refused(completed):
    root, source, _ = completed
    # Independent marker ensures this test is order-independent.
    marker = root / "locked-ledger"
    marker.mkdir(exist_ok=True)
    from ml.evaluation.final_test import claim_final_evaluation

    claim_final_evaluation(marker, source.name, "a" * 64, "b" * 64)
    with pytest.raises(ValueError, match="already reserved"):
        modeling.train_phase3(
            source,
            root / "forbidden",
            config=replace(config(), seed=7),
            phase2_root=root / "phase2",
            ledger_root=marker,
        )


def test_changed_code_identity_fails_before_test_claim(completed, monkeypatch):
    root, source, train = completed
    monkeypatch.setattr(modeling, "PHASE3_VERSION", "changed-protocol")
    with pytest.raises(ArtifactError, match="differs"):
        modeling.evaluate_phase3(
            train.run_dir, source, ledger_root=root / "untouched-ledger"
        )
    assert not (root / "untouched-ledger").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": True},
        {"warmup_weeks": 0},
        {"interval_coverage": 1},
        {"interval_scale_floor": 0},
        {"timeline": {"n_folds": 2}},
    ],
)
def test_invalid_config_rejected(changes):
    with pytest.raises(ValueError):
        Phase3Config(**changes)


def test_rank_selection_does_not_prefer_ml_unconditionally():
    rows = [
        {"model": "ridge", "wape": 20, "mae": 2},
        {"model": "moving_average_4", "wape": 10, "mae": 1},
    ]
    assert min(rows, key=modeling._rank)["model"] == "moving_average_4"
    assert np.isfinite(modeling._rank({"model": "zero", "wape": None, "mae": 0})[0])


@pytest.mark.parametrize(
    "field", ["test_methods", "best_ml_family", "recommended_method"]
)
def test_incomplete_plan_refused_before_final_claim(completed, tmp_path, field):
    import shutil

    from ml.data.acquisition import sha256_file
    from ml.pipelines.artifacts import inventory, write_json

    _, source, trained = completed
    copied = tmp_path / "training"
    shutil.copytree(trained.run_dir, copied)
    plan = json.loads((copied / "plan.json").read_text())
    plan.pop(field)
    write_json(copied / "plan.json", plan)
    manifest = json.loads((copied / "manifest.json").read_text())
    manifest["artifacts"] = inventory(copied)
    manifest["plan_sha256"] = sha256_file(copied / "plan.json")
    write_json(copied / "manifest.json", manifest)
    with pytest.raises(ArtifactError, match="plan"):
        modeling.evaluate_phase3(copied, source, ledger_root=tmp_path / "ledger")
    assert not (tmp_path / "ledger").exists()
