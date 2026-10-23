"""Hand-calculated metrics and training-only segment tests; synthetic fixtures."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from ml.evaluation.metrics import evaluate_predictions, forecast_metrics


def validation_fixture():
    rows = []
    observations = [
        ("fold_1", "SYNTH-A", "2011-01-03", 4, 2, 6),
        ("fold_1", "SYNTH-B", "2011-01-03", 0, 0, 2),
        ("fold_2", "SYNTH-A", "2011-01-10", 6, 8, 6),
        ("fold_2", "SYNTH-B", "2011-01-10", 2, 1, 4),
    ]
    for fold, code, week, actual, naive, average in observations:
        for model, prediction in [("naive", naive), ("moving_average_4", average)]:
            rows.append(
                {
                    "fold": fold,
                    "stock_code": code,
                    "week": week,
                    "actual": actual,
                    "model": model,
                    "prediction": prediction,
                }
            )
    volumes = pd.DataFrame(
        [
            {"fold": fold, "stock_code": code, "training_units": units}
            for fold in ("fold_1", "fold_2")
            for code, units in [("SYNTH-A", 30), ("SYNTH-B", 10)]
        ]
    )
    return pd.DataFrame(rows), volumes


def test_hand_calculated_metrics_and_bias_direction():
    metrics = forecast_metrics([0, 10, 20], [0, 15, 10])
    assert metrics["n_observations"] == 3
    assert metrics["mae"] == pytest.approx(5)
    assert metrics["rmse"] == pytest.approx(math.sqrt(125 / 3))
    assert metrics["wape"] == pytest.approx(50)
    assert metrics["wape_status"] == "defined"
    assert metrics["smape"] == pytest.approx((0 + 40 + 200 / 3) / 3)
    assert metrics["bias"] == pytest.approx(-5 / 3)
    assert forecast_metrics([1], [4])["wape"] == 300
    assert forecast_metrics([1], [4])["smape"] == 120


@pytest.mark.parametrize("prediction,smape", [([0, 0], 0), ([0, 5], 100)])
def test_zero_actual_wape_is_explicitly_undefined_even_when_perfect(prediction, smape):
    metrics = forecast_metrics([0, 0], prediction)
    assert metrics["wape"] is None
    assert metrics["wape_status"] == "undefined_zero_actual"
    assert metrics["smape"] == smape
    json.dumps(metrics, allow_nan=False)


@pytest.mark.parametrize(
    "actual,prediction",
    [
        ([], []),
        ([[1]], [[1]]),
        ([1], [1, 2]),
        ([np.nan], [1]),
        ([1], [np.inf]),
        ([-1], [1]),
        ([1], [-1]),
        (["wrong"], [1]),
        ([1j], [1]),
        ([True], [1]),
        ([1], [False]),
        ([True, 2], [1, 2]),
    ],
)
def test_invalid_metric_arrays_fail_usefully(actual, prediction):
    with pytest.raises(ValueError, match="must"):
        forecast_metrics(actual, prediction)


def test_series_alignment_and_large_unit_reductions():
    with pytest.raises(ValueError, match="aligned indexes"):
        forecast_metrics(
            pd.Series([1, 2], index=[1, 2]), pd.Series([1, 2], index=[2, 1])
        )
    result = forecast_metrics([1e300, 1e300], [0, 0])
    assert result["mae"] == result["rmse"] == 1e300
    assert result["wape"] == 100
    assert result["smape"] == 200
    assert result["bias"] == -1e300


def test_report_groupings_counts_directions_and_json_serialization():
    predictions, volumes = validation_fixture()
    report = evaluate_predictions(predictions, training_volumes=volumes)
    overall = {row["model"]: row for row in report["overall"]}
    naive = overall["naive"]
    assert naive["n_observations"] == 4
    assert naive["mae"] == 1.25
    assert naive["rmse"] == 1.5
    assert naive["wape"] == pytest.approx(100 * 5 / 12)
    assert naive["bias"] == -0.25
    assert overall["moving_average_4"]["mae"] == 1.5
    assert overall["moving_average_4"]["bias"] == 1.5
    direction = {row["model"]: row for row in report["error_direction"]}["naive"]
    assert direction == {
        "model": "naive",
        "underforecast_count": 2,
        "overforecast_count": 1,
        "exact_count": 1,
        "underforecast_units": 3.0,
        "overforecast_units": 2.0,
    }
    assert (
        len(report["by_fold"])
        == len(report["by_product"])
        == len(report["by_week"])
        == 4
    )
    assert all(row["n_observations"] == 2 for row in report["by_fold"])
    assert report["by_week"][0]["week"] == "2011-01-03T00:00:00"
    assert report["evaluation_scope"] == "validation"
    assert "training_units" in report["metric_definitions"]["segments"]
    json.dumps(report, allow_nan=False)
    shuffled = evaluate_predictions(
        predictions.sample(frac=1, random_state=17),
        training_volumes=volumes.sample(frac=1, random_state=18),
    )
    assert shuffled == report


def test_segments_use_fold_training_rank_and_deterministic_ties_never_actual_volume():
    predictions = pd.DataFrame(
        [
            {
                "fold": fold,
                "stock_code": f"SYNTH-{code}",
                "week": "2011-01-03",
                "actual": rank,
                "prediction": rank,
                "model": "naive",
            }
            for fold in ("fold_1", "fold_2")
            for rank, code in enumerate("ABCDEF", start=1)
        ]
    )
    volumes = pd.DataFrame(
        [
            {
                "fold": fold,
                "stock_code": f"SYNTH-{code}",
                "training_units": 5 if fold == "fold_1" else rank,
            }
            for fold in ("fold_1", "fold_2")
            for rank, code in enumerate("ABCDEF", start=1)
        ]
    )
    report = evaluate_predictions(predictions, training_volumes=volumes)
    segments = {
        (row["fold"], row["stock_code"]): row["segment"]
        for row in report["training_segments"]
    }
    assert [segments[("fold_1", f"SYNTH-{code}")] for code in "ABCDEF"] == [
        "high",
        "high",
        "medium",
        "medium",
        "low",
        "low",
    ]
    assert [segments[("fold_2", f"SYNTH-{code}")] for code in "ABCDEF"] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
    ]
    changed = predictions.copy()
    changed["actual"] = changed.actual * 1000
    changed_report = evaluate_predictions(changed, training_volumes=volumes)
    assert changed_report["training_segments"] == report["training_segments"]
    assert {row["segment"]: row["n_observations"] for row in report["by_segment"]} == {
        "high": 4,
        "medium": 4,
        "low": 4,
    }


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing_model", "same fold/product/week"),
        ("different_actual", "Actual demand must agree"),
        ("duplicate", "duplicate"),
        ("missing_value", "missing"),
        ("missing_column", "required columns"),
        ("invalid_date", "dates"),
        ("timezone", "timezone-naive"),
    ],
)
def test_reports_reject_misaligned_or_invalid_observations(change, match):
    predictions, volumes = validation_fixture()
    if change == "missing_model":
        predictions = predictions.iloc[1:]
    elif change == "different_actual":
        predictions.loc[0, "actual"] = 99
    elif change == "duplicate":
        predictions = pd.concat([predictions, predictions.iloc[:1]])
    elif change == "missing_value":
        predictions.loc[0, "prediction"] = np.nan
    elif change == "missing_column":
        predictions = predictions.drop(columns="actual")
    elif change == "invalid_date":
        predictions.loc[0, "week"] = "wrong"
    elif change == "timezone":
        predictions["week"] = pd.to_datetime(predictions.week).dt.tz_localize("UTC")
    with pytest.raises(ValueError, match=match):
        evaluate_predictions(predictions, training_volumes=volumes)


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing", "cover every"),
        ("duplicate", "duplicate"),
        ("negative", "nonnegative"),
        ("nonfinite", "nonnegative"),
    ],
)
def test_training_volumes_are_complete_unique_and_nonnegative(change, match):
    predictions, volumes = validation_fixture()
    if change == "missing":
        volumes = volumes.iloc[1:]
    elif change == "duplicate":
        volumes = pd.concat([volumes, volumes.iloc[:1]])
    elif change == "negative":
        volumes.loc[0, "training_units"] = -1
    else:
        volumes["training_units"] = np.inf
    with pytest.raises(ValueError, match=match):
        evaluate_predictions(predictions, training_volumes=volumes)


def test_zero_demand_report_is_json_safe_and_integer_folds_are_canonical():
    predictions, volumes = validation_fixture()
    predictions["actual"] = predictions["prediction"] = 0
    predictions["fold"] = predictions.fold.map({"fold_1": 1, "fold_2": 2})
    volumes["fold"] = volumes.fold.map({"fold_1": 1, "fold_2": 2})
    report = evaluate_predictions(predictions, training_volumes=volumes)
    assert all(row["wape"] is None for row in report["overall"])
    assert {row["fold"] for row in report["by_fold"]} == {"1", "2"}
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mixed_float", [False, True])
def test_training_integer_ranks_preserve_int64_boundary_and_serialized_counts(
    mixed_float,
):
    maximum = 2**63 - 1
    codes = ["SYNTH-A", "SYNTH-Z"]
    units = [maximum - 1, maximum]
    if mixed_float:
        codes.append("SYNTH-M")
        units.append(0.5)
    predictions = pd.DataFrame(
        [
            {
                "fold": "fold_1",
                "stock_code": code,
                "week": "2011-01-03",
                "actual": 1,
                "prediction": 1,
                "model": "naive",
            }
            for code in codes
        ]
    )
    volumes = pd.DataFrame({"fold": "fold_1", "stock_code": codes})
    # Object dtype is necessary to represent mixed float / exact int inputs.
    volumes["training_units"] = pd.Series(units, dtype=object)
    report = evaluate_predictions(predictions, training_volumes=volumes)
    ranked = report["training_segments"]
    assert ranked[0]["stock_code"] == "SYNTH-Z"
    assert ranked[0]["segment"] == "high"
    assert ranked[0]["training_units"] == maximum
    assert ranked[1]["stock_code"] == "SYNTH-A"
    assert ranked[1]["training_units"] == maximum - 1
    assert type(ranked[0]["training_units"]) is int
    assert type(ranked[1]["training_units"]) is int
    assert (
        json.loads(json.dumps(report))["training_segments"][0]["training_units"]
        == maximum
    )


def test_boolean_training_volumes_are_rejected():
    predictions, volumes = validation_fixture()
    volumes["training_units"] = True
    with pytest.raises(ValueError, match="finite nonnegative numbers"):
        evaluate_predictions(predictions, training_volumes=volumes)
