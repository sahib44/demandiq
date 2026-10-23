"""Synthetic tests for training-only preprocessing and reproducible model artifacts."""

import hashlib
from copy import deepcopy
from dataclasses import replace

import joblib
import numpy as np
import pandas as pd
import pytest

from ml.models.training import (
    feature_importance,
    fit_model,
    load_model,
    model_candidates,
    predict_model,
    save_model,
)

NAMES = (
    "stock_code",
    "demand_lag1",
    "rolling_mean4",
    "previous_week_average_price",
    "recent_return_rate",
)


def training_rows():
    """Invented rows, with one partially and one entirely missing feature."""
    blocks = []
    for code, offset in (("SYNTH-A", 0), ("SYNTH-B", 10)):
        values = np.arange(1, 9, dtype=float)
        lag = values.copy()
        lag[2] = np.nan
        blocks.append(
            pd.DataFrame(
                {
                    "stock_code": code,
                    "week": pd.date_range("2024-01-01", periods=8, freq="W-MON"),
                    "gross_units": 5 + values * 2 + offset,
                    "demand_lag1": lag,
                    "rolling_mean4": values + 1,
                    "previous_week_average_price": 2 + offset / 10,
                    "recent_return_rate": np.nan,
                }
            )
        )
    return pd.concat(blocks, ignore_index=True)


def prediction_rows():
    rows = training_rows().groupby("stock_code", sort=True).tail(1).copy()
    rows["week"] += pd.Timedelta(weeks=1)
    rows["demand_lag1"] += 1
    rows["rolling_mean4"] += 1
    return rows.reset_index(drop=True)


def first_candidates():
    return {candidate["family"]: candidate for candidate in model_candidates()}


@pytest.fixture(scope="module")
def fitted():
    return {
        family: fit_model(training_rows(), candidate, feature_names=NAMES)
        for family, candidate in first_candidates().items()
    }


def test_declared_grid_contains_two_candidates_per_family_and_deterministic_seeds():
    candidates = model_candidates()
    assert candidates == model_candidates(42)
    assert len(candidates) == len({candidate["id"] for candidate in candidates}) == 6
    assert sorted(candidate["family"] for candidate in candidates) == [
        "random_forest",
        "random_forest",
        "ridge",
        "ridge",
        "xgboost",
        "xgboost",
    ]
    assert {
        row["parameters"]["alpha"] for row in candidates if row["family"] == "ridge"
    } == {1, 100}
    for candidate in candidates:
        assert candidate["parameters"]["random_state"] == 42
        if candidate["family"] != "ridge":
            assert candidate["parameters"]["n_jobs"] == 1
    assert all(row["parameters"]["random_state"] == 7 for row in model_candidates(7))
    candidates[0]["parameters"]["alpha"] = -123
    assert model_candidates()[0]["parameters"]["alpha"] == 1


@pytest.mark.parametrize("seed", [-1, 2**32, True, 1.5, "42"])
def test_invalid_seeds_are_rejected(seed):
    with pytest.raises(ValueError, match="seed"):
        model_candidates(seed)


@pytest.mark.parametrize("candidate", model_candidates(), ids=lambda row: row["id"])
def test_every_declared_model_trains_and_predicts(candidate):
    source = training_rows()
    original = source.copy(deep=True)
    model = fit_model(source, candidate, feature_names=NAMES)
    predicted = predict_model(model, prediction_rows())
    assert predicted.shape == (2,)
    assert predicted.dtype == np.dtype("float64")
    assert np.isfinite(predicted).all() and (predicted >= 0).all()
    assert model.training_row_count == len(source)
    assert model.training_end == pd.Timestamp("2024-02-19")
    assert tuple(model.pipeline.feature_names_in_) == NAMES
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_preprocessing_is_fitted_on_training_only_and_unknown_products_are_supported(
    fitted, family
):
    model = fitted[family]
    preprocessor = model.pipeline.named_steps["preprocessor"]
    numeric = preprocessor.named_transformers_["numeric"]
    imputer = numeric.named_steps["imputer"]
    assert imputer.statistics_.tolist() == [5.0, 5.5, 2.5, 0.0]
    assert imputer.indicator_.features_.tolist() == [0, 3]
    assert preprocessor.named_transformers_["product"].categories_[0].tolist() == [
        "SYNTH-A",
        "SYNTH-B",
    ]
    before_imputation = imputer.statistics_.copy()
    before_categories = (
        preprocessor.named_transformers_["product"].categories_[0].copy()
    )
    future = prediction_rows()
    future.loc[0, "stock_code"] = "SYNTH-UNSEEN"
    future["previous_week_average_price"] = 1_000_000.0
    future["gross_units"] = 999999999999.0
    assert np.isfinite(predict_model(model, future)).all()
    np.testing.assert_array_equal(imputer.statistics_, before_imputation)
    np.testing.assert_array_equal(
        preprocessor.named_transformers_["product"].categories_[0], before_categories
    )
    if family == "ridge":
        scaler = numeric.named_steps["scaler"]
        assert scaler.n_samples_seen_ == 16
        np.testing.assert_allclose(scaler.mean_, [4.75, 5.5, 2.5, 0.0, 0.125, 1.0])
    else:
        assert "scaler" not in numeric.named_steps


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_target_and_unselected_columns_never_enter_prediction_features(fitted, family):
    future = prediction_rows()
    expected = predict_model(fitted[family], future.drop(columns="gross_units"))
    future["gross_units"] = "This column is deliberately ignored during prediction."
    future["current_week_revenue"] = np.inf
    np.testing.assert_array_equal(predict_model(fitted[family], future), expected)


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_repeat_seed_and_training_permutation_preserve_predictions(fitted, family):
    repeated = fit_model(
        training_rows().sample(frac=1, random_state=91),
        first_candidates()[family],
        feature_names=NAMES,
    )
    np.testing.assert_array_equal(
        predict_model(repeated, prediction_rows()),
        predict_model(fitted[family], prediction_rows()),
    )


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_prediction_preserves_input_row_order(fitted, family):
    source = prediction_rows()
    expected = predict_model(fitted[family], source)
    np.testing.assert_array_equal(
        predict_model(fitted[family], source.iloc[::-1]), expected[::-1]
    )


def test_ridge_negative_raw_predictions_are_clipped_to_zero(fitted):
    future = prediction_rows()
    future["demand_lag1"] = -1_000_000.0
    future["rolling_mean4"] = -1_000_000.0
    raw = fitted["ridge"].pipeline.predict(future.loc[:, list(NAMES)])
    assert (raw < 0).all()
    np.testing.assert_array_equal(predict_model(fitted["ridge"], future), np.zeros(2))


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_native_feature_importance_has_names_and_honest_method_labels(fitted, family):
    rows = feature_importance(fitted[family])
    transformed = (
        fitted[family].pipeline.named_steps["preprocessor"].get_feature_names_out()
    )
    assert len(rows) == len(transformed)
    assert {row["feature"] for row in rows} == set(transformed)
    assert all(
        row["importance"] >= 0 and np.isfinite(row["importance"]) for row in rows
    )
    assert rows == sorted(rows, key=lambda row: (-row["importance"], row["feature"]))
    assert len({row["method"] for row in rows}) == 1
    assert not any(
        "gross_units" in row["feature"] or "week" == row["feature"] for row in rows
    )
    if family != "ridge":
        assert sum(row["importance"] for row in rows) == pytest.approx(1)


@pytest.mark.parametrize("family", ["ridge", "random_forest", "xgboost"])
def test_model_serialization_is_deterministic_and_roundtrips(fitted, family, tmp_path):
    original = fitted[family]
    path = tmp_path / f"{family}.joblib"
    digest = save_model(original, path)
    repeated_path = tmp_path / f"{family}-again.joblib"
    assert save_model(original, repeated_path) == digest
    assert path.read_bytes() == repeated_path.read_bytes()
    loaded = load_model(path, digest)
    assert loaded.candidate == original.candidate
    assert loaded.feature_names == original.feature_names
    assert loaded.training_end == original.training_end
    np.testing.assert_array_equal(
        predict_model(loaded, prediction_rows()),
        predict_model(original, prediction_rows()),
    )


def test_tampered_hash_fails_before_joblib_load(fitted, tmp_path, monkeypatch):
    path = tmp_path / "tampered.joblib"
    digest = save_model(fitted["ridge"], path)
    path.write_bytes(path.read_bytes() + b"deliberate synthetic corruption")

    def forbidden(*args, **kwargs):
        pytest.fail("A hash mismatch must be rejected before unpickling.")

    monkeypatch.setattr("ml.models.training.joblib.load", forbidden)
    with pytest.raises(ValueError, match="SHA-256"):
        load_model(path, digest)


def test_load_uses_verified_bytes_if_path_is_replaced(fitted, tmp_path, monkeypatch):
    path = tmp_path / "replaced.joblib"
    digest = save_model(fitted["ridge"], path)
    real_load = joblib.load

    def replace_then_load(source):
        path.write_bytes(b"Replaced after digest verification.")
        return real_load(source)

    monkeypatch.setattr("ml.models.training.joblib.load", replace_then_load)
    loaded = load_model(path, digest)
    assert loaded.candidate == fitted["ridge"].candidate


def test_save_failure_preserves_existing_artifact_and_cleans_staging(
    fitted, tmp_path, monkeypatch
):
    path = tmp_path / "previous.joblib"
    path.write_bytes(b"Previous artifact must remain untouched.")

    def fail(model, staging, **kwargs):
        staging.write_bytes(b"partial")
        raise OSError("Synthetic write failure")

    monkeypatch.setattr("ml.models.training.joblib.dump", fail)
    with pytest.raises(OSError, match="Synthetic"):
        save_model(fitted["ridge"], path)
    assert path.read_bytes() == b"Previous artifact must remain untouched."
    assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("digest", ["", "A" * 64, "invalid", None])
def test_invalid_expected_hash_is_rejected(tmp_path, digest):
    with pytest.raises(ValueError, match="expected_sha256"):
        load_model(tmp_path / "missing.joblib", digest)


def test_missing_and_wrong_type_model_artifacts_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="missing or unreadable"):
        load_model(tmp_path / "missing.joblib", "a" * 64)
    path = tmp_path / "wrong-type.joblib"
    joblib.dump({"synthetic": "not a model"}, path, compress=3)
    with pytest.raises(ValueError, match="FittedDemandModel"):
        load_model(path, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize(
    "names",
    [
        ("stock_code", "gross_units"),
        ("stock_code", "week"),
        ("stock_code", "actual"),
        ("stock_code", "demand_lag1", "demand_lag1"),
        ("demand_lag1",),
        list(NAMES),
    ],
)
def test_target_or_invalid_feature_lists_are_rejected(names):
    with pytest.raises(ValueError, match="feature"):
        fit_model(training_rows(), model_candidates()[0], feature_names=names)


@pytest.mark.parametrize(
    "candidate",
    [
        {},
        {"id": "unsafe id", "family": "ridge", "parameters": {}},
        {"id": "synthetic", "family": "unknown", "parameters": {}},
        {"id": "synthetic", "family": [], "parameters": {}},
        {"id": "synthetic", "family": "ridge", "parameters": {"alpha": np.inf}},
        {"id": "synthetic", "family": "ridge", "parameters": {"unsupported": 1}},
    ],
)
def test_invalid_candidates_are_rejected(candidate):
    with pytest.raises(ValueError, match="candidate"):
        fit_model(training_rows(), candidate, feature_names=NAMES)


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "missing_feature",
        "missing_target",
        "duplicate_column",
        "duplicate_row",
        "target_nan",
        "target_negative",
        "target_infinite",
        "target_boolean",
        "feature_infinite",
        "feature_string",
        "feature_boolean",
        "invalid_product",
        "non_monday",
        "aware_date",
    ],
)
def test_invalid_training_input_is_rejected(kind):
    rows = training_rows()
    if kind == "empty":
        rows = rows.iloc[:0]
    elif kind == "missing_feature":
        rows = rows.drop(columns="demand_lag1")
    elif kind == "missing_target":
        rows = rows.drop(columns="gross_units")
    elif kind == "duplicate_column":
        rows = pd.concat([rows, rows[["gross_units"]]], axis=1)
    elif kind == "duplicate_row":
        rows = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    elif kind == "target_nan":
        rows["gross_units"] = np.nan
    elif kind == "target_negative":
        rows["gross_units"] = -1
    elif kind == "target_infinite":
        rows["gross_units"] = np.inf
    elif kind == "target_boolean":
        rows["gross_units"] = True
    elif kind == "feature_infinite":
        rows["demand_lag1"] = np.inf
    elif kind == "feature_string":
        rows["demand_lag1"] = "1"
    elif kind == "feature_boolean":
        rows["demand_lag1"] = True
    elif kind == "invalid_product":
        rows["stock_code"] = " "
    elif kind == "non_monday":
        rows["week"] += pd.Timedelta(days=1)
    elif kind == "aware_date":
        rows["week"] = rows.week.dt.tz_localize("UTC")
    with pytest.raises(ValueError):
        fit_model(rows, model_candidates()[0], feature_names=NAMES)


@pytest.mark.parametrize("delta", [0, -1])
def test_public_predictions_reject_training_or_earlier_dates(fitted, delta):
    rows = prediction_rows()
    rows["week"] = fitted["ridge"].training_end + pd.Timedelta(weeks=delta)
    with pytest.raises(ValueError, match="strictly after"):
        predict_model(fitted["ridge"], rows)


def test_prediction_validation_and_model_metadata_consistency(fitted):
    with pytest.raises(ValueError, match="missing required"):
        predict_model(fitted["ridge"], prediction_rows().drop(columns="rolling_mean4"))
    invalid = prediction_rows()
    invalid["recent_return_rate"] = np.inf
    with pytest.raises(ValueError, match="finite"):
        predict_model(fitted["ridge"], invalid)
    with pytest.raises(ValueError, match="contradict"):
        predict_model(
            replace(fitted["ridge"], feature_names=NAMES[:-1]), prediction_rows()
        )
    with pytest.raises(ValueError, match="family"):
        predict_model(
            replace(fitted["ridge"], candidate=deepcopy(first_candidates()["xgboost"])),
            prediction_rows(),
        )
