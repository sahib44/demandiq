"""Synthetic, self-contained application forecast inference and cache checks."""

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.core.config import Settings
from backend.app.services import forecasting
from backend.app.services.errors import ServiceError
from ml.data.acquisition import sha256_file
from ml.evaluation.final_test import claim_final_evaluation, complete_final_evaluation
from ml.evaluation.splits import Phase2Config
from ml.evaluation.uncertainty import add_intervals, calibrate_intervals
from ml.features.weekly import feature_columns, generate_features
from ml.models.baselines import predict_baselines
from ml.models.config import Phase3Config
from ml.pipelines.artifacts import inventory, write_json
from ml.pipelines.ingestion import ArtifactError


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    from ml.models.training import (
        fit_model,
        model_candidates,
        predict_model,
        save_model,
    )
    from ml.pipelines.modeling import _next_week_features

    root = tmp_path_factory.mktemp("application-forecast")
    settings = Settings(data_dir=root / "data", artifact_dir=root / "artifacts")
    run_id, dataset_id = "a" * 64, "b" * 64
    source = settings.artifact_dir / "phase3" / run_id
    (source / "models").mkdir(parents=True)
    config = Phase3Config(
        timeline=Phase2Config(
            start_week="2024-01-01",
            train_end="2024-04-01",
            validation_end="2024-04-22",
            test_end="2024-05-06",
            top_products=2,
            min_history_weeks=4,
        )
    )
    parts = []
    for stock_code, offset in (("SYNTH-A", 0), ("SYNTH-B", 5)):
        weeks = pd.date_range(
            config.timeline.start_week, config.timeline.validation_end, freq="W-MON"
        )
        units = np.arange(len(weeks), dtype="int64") % 4 + 2 + offset
        parts.append(
            pd.DataFrame(
                {
                    "stock_code": stock_code,
                    "week": weeks,
                    "gross_units": units,
                    "returned_units": 0,
                    "cancellation_units": 0,
                    "net_units": units,
                    "revenue": units * 2.0,
                    "transactions": 1,
                    "unique_customers": 1,
                    "average_price": 2.0,
                }
            )
        )
    panel = pd.concat(parts, ignore_index=True)
    panel.to_parquet(source / "pretest_weekly.parquet", index=False)
    names = feature_columns()
    features = generate_features(panel)
    training = features.loc[
        features.week.ge(
            pd.Timestamp(config.timeline.start_week) + pd.Timedelta(weeks=12)
        )
    ]
    next_features = _next_week_features(panel, config)
    predicted, hashes = [], {}
    for family in forecasting.FAMILIES:
        candidate = next(row for row in model_candidates() if row["family"] == family)
        model = fit_model(training, candidate, feature_names=names)
        hashes[family] = save_model(model, source / "models" / f"{family}.joblib")
        frame = (
            next_features[["stock_code", "week", "rolling_mean4"]]
            .rename(columns={"rolling_mean4": "scale"})
            .copy()
        )
        frame["prediction"] = predict_model(model, next_features)
        frame["model"] = family
        predicted.append(frame)
    baseline = predict_baselines(
        panel[["stock_code", "week", "gross_units"]], config.timeline.test_start
    )
    baseline = baseline.merge(
        next_features[["stock_code", "week", "rolling_mean4"]].rename(
            columns={"rolling_mean4": "scale"}
        ),
        on=["stock_code", "week"],
    )
    predicted.append(baseline)
    issued = pd.concat(predicted, ignore_index=True)
    issued["fold"] = "test"
    calibration_rows = issued.copy()
    calibration_rows["week"] = pd.Timestamp(config.timeline.validation_end)
    calibration_rows["actual"] = 4
    calibration = calibrate_intervals(calibration_rows)
    calibration_rows.to_parquet(source / "calibration_predictions.parquet", index=False)
    write_json(source / "calibration.json", calibration)
    issued = add_intervals(issued, calibration)
    issued.to_parquet(source / "pretest_forecasts.parquet", index=False)
    write_json(source / "config.json", config.to_dict())
    write_json(
        source / "cohort.json",
        [
            {"stock_code": code, "training_units": 100}
            for code in ("SYNTH-A", "SYNTH-B")
        ],
    )
    plan = {
        "experiment_id": run_id,
        "dataset_id": dataset_id,
        "horizon_weeks": 1,
        "best_ml_family": "ridge",
        "features": list(names),
        "model_hashes": hashes,
        "calibration_sha256": sha256_file(source / "calibration.json"),
        "cohort_sha256": sha256_file(source / "cohort.json"),
        "test_methods": sorted(issued.model.unique().tolist()),
        "roles": config.roles(),
        "refit_end": config.timeline.validation_end,
    }
    write_json(source / "plan.json", plan)
    write_json(
        source / "manifest.json",
        {
            "experiment_id": run_id,
            "dataset_id": dataset_id,
            "state": "frozen_pretest",
            "plan_sha256": sha256_file(source / "plan.json"),
            "artifacts": inventory(source),
        },
    )
    # A completed fixture evaluation is separate from real/official data and
    # exists solely to exercise retrospective verification, not model metrics.
    evaluation = settings.artifact_dir / "phase3" / "evaluations" / run_id
    evaluation.mkdir(parents=True)
    retrospective = []
    for week in pd.date_range(
        config.timeline.test_start, config.timeline.test_end, freq="W-MON"
    ):
        frame = issued.copy()
        frame["week"] = week
        frame["actual"] = 4
        retrospective.append(frame)
    pd.concat(retrospective, ignore_index=True).to_parquet(
        evaluation / "predictions.parquet", index=False
    )
    plan_digest = sha256_file(source / "plan.json")
    write_json(
        evaluation / "evaluation_metadata.json",
        {
            "dataset_id": dataset_id,
            "experiment_id": run_id,
            "plan_sha256": plan_digest,
            "evaluation_scope": "test",
            "all_models_frozen_before_test": True,
            "test_refitting": False,
            "selected_before_test": "ridge",
        },
    )
    write_json(evaluation / "metrics.json", {"evaluation_scope": "test", "overall": []})
    write_json(evaluation / "interval_metrics.json", {"scope": "test", "overall": []})
    write_json(
        evaluation / "manifest.json",
        {
            "experiment_id": run_id,
            "dataset_id": dataset_id,
            "plan_sha256": plan_digest,
            "evaluation_scope": "test",
            "artifacts": inventory(evaluation),
        },
    )
    assert (
        claim_final_evaluation(settings.ledger_dir, dataset_id, run_id, plan_digest)
        == "claimed"
    )
    complete_final_evaluation(
        settings.ledger_dir,
        dataset_id,
        run_id,
        plan_digest,
        results_dir=evaluation,
        results_manifest_sha256=sha256_file(evaluation / "manifest.json"),
    )
    return settings, run_id, source, evaluation


def independent(frozen, tmp_path):
    settings, run_id, source, _ = frozen
    local = Settings(
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        ledger_dir=settings.ledger_dir,
    )
    target = local.artifact_dir / "phase3" / run_id
    shutil.copytree(source, target)
    return local, run_id, target


@pytest.mark.parametrize(
    "run_id,scope",
    [
        ("bad", "one_week"),
        ("a" * 64, "invalid"),
        ("a" * 64, []),
        ("A" * 64, "one_week"),
    ],
)
def test_invalid_requests_fail_without_artifact_access(tmp_path, run_id, scope):
    with pytest.raises(ServiceError) as error:
        forecasting.prepare_forecast(Settings(artifact_dir=tmp_path), run_id, scope)
    assert error.value.status_code == 422


def test_missing_training_run_is_a_safe_not_found(tmp_path):
    with pytest.raises(ServiceError, match="unavailable") as error:
        forecasting.prepare_forecast(
            Settings(artifact_dir=tmp_path), "a" * 64, "one_week"
        )
    assert error.value.status_code == 404


def test_real_one_week_inference_uses_no_test_targets_or_training(
    frozen, tmp_path, monkeypatch
):
    settings, run_id, source = independent(frozen, tmp_path)
    from ml.models import training
    from ml.pipelines import modeling

    loads, predictions = [], []
    real_load, real_predict = training.load_model, training.predict_model

    def checked_load(path, digest):
        loads.append(Path(path).name)
        return real_load(path, digest)

    def checked_predict(model, frame):
        predictions.append(model.candidate["family"])
        return real_predict(model, frame)

    def forbidden(*args, **kwargs):
        pytest.fail(
            "Application inference must never train, evaluate or read raw/test sources."
        )

    monkeypatch.setattr(training, "load_model", checked_load)
    monkeypatch.setattr(training, "predict_model", checked_predict)
    monkeypatch.setattr(modeling, "train_phase3", forbidden)
    monkeypatch.setattr(modeling, "evaluate_phase3", forbidden)
    # No ledger is necessary for reissuing the first pre-test forecast.
    settings = Settings(
        data_dir=settings.data_dir,
        artifact_dir=settings.artifact_dir,
        ledger_dir=tmp_path / "no-ledger",
    )
    forecast_id, output, metadata, frame = forecasting.prepare_forecast(
        settings, run_id, "one_week"
    )
    assert sorted(loads) == sorted(f"{name}.joblib" for name in forecasting.FAMILIES)
    assert set(predictions) == set(forecasting.FAMILIES)
    assert len(frame) == 12 and frame.actual.isna().all()
    assert frame.week.eq(pd.Timestamp("2024-04-29")).all()
    assert set(frame.model) == set(metadata["methods"])
    assert metadata["generation"] == "real_inference_from_frozen_models"
    assert not metadata["actuals_available"]
    assert metadata["forecast_id"] == forecast_id
    assert output == settings.artifact_dir / "backend" / "forecasts" / forecast_id
    expected = pd.read_parquet(source / "pretest_forecasts.parquet").sort_values(
        ["week", "stock_code", "model"]
    )
    np.testing.assert_allclose(frame.prediction, expected.prediction, atol=1e-9)
    assert not settings.ledger_dir.exists()


def test_cache_reuse_is_verified_and_skips_native_inference(
    frozen, tmp_path, monkeypatch
):
    settings, run_id, _ = independent(frozen, tmp_path)
    first = forecasting.prepare_forecast(settings, run_id, "one_week")
    monkeypatch.setattr(
        forecasting,
        "_one_week",
        lambda *args: pytest.fail("A complete cache must avoid model inference."),
    )
    second = forecasting.prepare_forecast(settings, run_id, "one_week")
    assert first[:3] == second[:3]
    pd.testing.assert_frame_equal(first[3], second[3])
    (first[1] / "metadata.json").write_text("{}")
    with pytest.raises(ArtifactError, match="integrity"):
        forecasting.prepare_forecast(settings, run_id, "one_week")


def test_independent_cold_runs_have_identical_forecast_bytes(frozen, tmp_path):
    first_settings, run_id, _ = independent(frozen, tmp_path / "one")
    second_settings, _, _ = independent(frozen, tmp_path / "two")
    first = forecasting.prepare_forecast(first_settings, run_id, "one_week")
    second = forecasting.prepare_forecast(second_settings, run_id, "one_week")
    assert first[0] == second[0] and first[2] == second[2]
    for name in ("forecasts.parquet", "metadata.json", "manifest.json"):
        assert (first[1] / name).read_bytes() == (second[1] / name).read_bytes()


def test_retrospective_only_loads_the_existing_verified_evaluation(
    frozen, tmp_path, monkeypatch
):
    settings, run_id, _ = independent(frozen, tmp_path)
    monkeypatch.setattr(
        forecasting,
        "_one_week",
        lambda *args: pytest.fail("Retrospective requests must not infer models."),
    )
    forecast_id, output, metadata, frame = forecasting.prepare_forecast(
        settings, run_id, "retrospective"
    )
    assert len(frame) == 24 and frame.actual.notna().all()
    assert metadata["actuals_available"]
    assert metadata["generation"] == "verified_completed_retrospective_forecasts"
    assert metadata["source"]["evaluation_manifest_sha256"]
    assert metadata["evaluation_metrics"] == {
        "point": {"evaluation_scope": "test", "overall": []},
        "uncertainty": {"scope": "test", "overall": []},
    }
    assert frame.actual.dtype == np.dtype("int64")
    assert len(forecast_id) == 64 and output.exists()
    # The cached response keeps the same verified final metrics.
    second = forecasting.prepare_forecast(settings, run_id, "retrospective")
    assert second[:3] == (forecast_id, output, metadata)
    pd.testing.assert_frame_equal(second[3], frame)


@pytest.mark.parametrize(
    "invalid", [0.5, -1, float("inf"), float("nan"), True, "4", 2**63]
)
def test_retrospective_actuals_require_nonnegative_int64_counts(frozen, invalid):
    _, _, source, evaluation = frozen
    frame = pd.read_parquet(evaluation / "predictions.parquet")
    frame["actual"] = frame.actual.astype(object)
    frame.at[0, "actual"] = invalid
    plan = json.loads((source / "plan.json").read_text())
    with pytest.raises(ArtifactError, match="values or bounds"):
        forecasting._validated_frame(
            frame, plan, "retrospective", {"SYNTH-A", "SYNTH-B"}
        )


def test_retrospective_actual_is_identical_for_every_method(frozen):
    _, _, source, evaluation = frozen
    frame = pd.read_parquet(evaluation / "predictions.parquet")
    frame.at[0, "actual"] = 5
    plan = json.loads((source / "plan.json").read_text())
    with pytest.raises(ArtifactError, match="values or bounds"):
        forecasting._validated_frame(
            frame, plan, "retrospective", {"SYNTH-A", "SYNTH-B"}
        )


def test_forecast_cohort_must_equal_the_frozen_training_cohort(frozen):
    _, _, source, evaluation = frozen
    frame = pd.read_parquet(evaluation / "predictions.parquet")
    frame.loc[frame.stock_code.eq("SYNTH-B"), "stock_code"] = "DIFFERENT-PRODUCT"
    plan = json.loads((source / "plan.json").read_text())
    with pytest.raises(ArtifactError, match="complete product-week-method grid"):
        forecasting._validated_frame(
            frame, plan, "retrospective", {"SYNTH-A", "SYNTH-B"}
        )


def test_retrospective_requires_a_matching_completed_ledger(frozen, tmp_path):
    settings, run_id, _ = independent(frozen, tmp_path)
    no_ledger = Settings(
        data_dir=settings.data_dir,
        artifact_dir=settings.artifact_dir,
        ledger_dir=tmp_path / "missing-ledger",
    )
    with pytest.raises(ValueError, match="ledger"):
        forecasting.prepare_forecast(no_ledger, run_id, "retrospective")


def test_corrupt_models_are_rejected_before_unpickling(frozen, tmp_path, monkeypatch):
    settings, run_id, source = independent(frozen, tmp_path)
    (source / "models/ridge.joblib").write_bytes(b"synthetic corruption")
    monkeypatch.setattr(
        forecasting,
        "_one_week",
        lambda *args: pytest.fail("Corruption must fail before inference."),
    )
    with pytest.raises(ArtifactError, match="integrity"):
        forecasting.prepare_forecast(settings, run_id, "one_week")


def test_source_and_output_symlinks_cannot_escape_artifact_root(frozen, tmp_path):
    settings, run_id, source, _ = frozen
    local = Settings(artifact_dir=tmp_path / "artifacts", data_dir=tmp_path / "data")
    (local.artifact_dir / "phase3").mkdir(parents=True)
    (local.artifact_dir / "phase3" / run_id).symlink_to(
        source, target_is_directory=True
    )
    with pytest.raises(ArtifactError, match="escapes"):
        forecasting.prepare_forecast(local, run_id, "one_week")


def test_failed_publication_cleans_staging_and_publishes_no_completed_run(
    frozen, tmp_path, monkeypatch
):
    settings, run_id, _ = independent(frozen, tmp_path)
    real_write = forecasting.write_json

    def failed_write(path, value):
        if path.name == "manifest.json":
            raise OSError("Synthetic publication failure")
        return real_write(path, value)

    monkeypatch.setattr(forecasting, "write_json", failed_write)
    with pytest.raises(OSError, match="Synthetic"):
        forecasting.prepare_forecast(settings, run_id, "one_week")
    assert list((settings.artifact_dir / "backend" / "forecasts").iterdir()) == []
