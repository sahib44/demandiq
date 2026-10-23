"""Hand-calculated historical uncertainty fixtures; no performance claims."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from ml.evaluation.uncertainty import (
    add_intervals,
    calibrate_intervals,
    interval_metrics,
)


def calibration_fixture():
    return pd.DataFrame(
        {
            "stock_code": "SYNTH-A",
            "model": "ridge",
            "week": pd.date_range("2011-09-12", periods=4, freq="W-MON"),
            "actual": [0, 10, 20, 30],
            "prediction": 0,
            "scale": 0,
        }
    )


def forecast_fixture():
    return pd.DataFrame(
        {
            "stock_code": ["SYNTH-A", "SYNTH-B"],
            "model": "ridge",
            "week": pd.to_datetime(["2011-10-10", "2011-10-17"]),
            "prediction": [5, 40],
            "scale": [20, 0],
            "actual": [12, 40],
        }
    )


def test_higher_finite_sample_quantile_scaling_and_metadata():
    calibration = calibrate_intervals(
        calibration_fixture(), coverage=0.8, scale_floor=10
    )
    row = calibration["ridge"]
    assert row["normalized_radius"] == 3
    assert row["requested_rank"] == row["quantile_rank"] == 4
    assert row["n_calibration"] == 4
    assert row["nominal_coverage"] == 0.8
    assert row["scale_floor"] == 10
    assert row["calibration_start"] == "2011-09-12T00:00:00"
    assert row["calibration_end"] == "2011-10-03T00:00:00"
    assert row["insufficient_samples"] is False
    assert "not a coverage guarantee" in row["warning"]
    shorter = calibrate_intervals(calibration_fixture().iloc[1:], coverage=0.5)
    assert shorter["ridge"]["quantile_rank"] == 2
    assert shorter["ridge"]["normalized_radius"] == 2


def test_small_calibration_sample_flag_and_zero_residuals():
    calibration = calibrate_intervals(calibration_fixture().iloc[:1])
    row = calibration["ridge"]
    assert row["insufficient_samples"] is True
    assert row["requested_rank"] == 2
    assert row["quantile_rank"] == 1
    assert "maximum observed score" in row["warning"]
    bounded = add_intervals(forecast_fixture(), calibration)
    assert bounded.lower.tolist() == bounded.upper.tolist() == [5, 40]


def test_intervals_clip_only_lower_bound_preserve_inputs_and_never_read_future_actuals():
    calibration = calibrate_intervals(calibration_fixture())
    original_calibration = deepcopy(calibration)
    predictions = forecast_fixture()
    predictions.index = [9, 9]
    before = predictions.copy(deep=True)
    bounded = add_intervals(predictions, calibration)
    assert_frame_equal(predictions, before)
    assert bounded.index.tolist() == [9, 9]
    assert bounded.lower.tolist() == [0, 10]
    assert bounded.upper.tolist() == [65, 70]
    assert bounded.nominal_coverage.tolist() == [0.8, 0.8]
    assert bounded.uncertainty_label.str.contains("empirical").all()
    assert calibration == original_calibration
    changed = predictions.assign(actual=[999999, 0])
    changed_bounded = add_intervals(changed, calibration)
    assert_frame_equal(
        bounded[["lower", "upper", "nominal_coverage"]],
        changed_bounded[["lower", "upper", "nominal_coverage"]],
    )
    no_actuals = add_intervals(predictions.drop(columns="actual"), calibration)
    assert_frame_equal(bounded[["lower", "upper"]], no_actuals[["lower", "upper"]])


@pytest.mark.parametrize("date", ["2011-10-03", "2011-09-12"])
def test_calibration_cannot_overlap_or_follow_forecast_period(date):
    calibration = calibrate_intervals(calibration_fixture())
    forecasts = forecast_fixture()
    forecasts.loc[0, "week"] = pd.Timestamp(date)
    with pytest.raises(ValueError, match="strictly after"):
        add_intervals(forecasts, calibration)


@pytest.mark.parametrize(
    "coverage,floor", [(0, 10), (1, 10), (True, 10), (0.8, 0), (0.8, -1), (0.8, np.inf)]
)
def test_invalid_calibration_configuration_rejected(coverage, floor):
    with pytest.raises(ValueError):
        calibrate_intervals(calibration_fixture(), coverage=coverage, scale_floor=floor)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual", -1),
        ("prediction", np.nan),
        ("scale", np.inf),
        ("scale", True),
        ("week", "wrong"),
    ],
)
def test_invalid_calibration_observations_rejected(field, value):
    frame = calibration_fixture().astype({field: "object"})
    frame.loc[0, field] = value
    with pytest.raises(ValueError):
        calibrate_intervals(frame)


def test_empty_duplicate_and_unknown_model_calibration_rejected():
    with pytest.raises(ValueError, match="nonempty"):
        calibrate_intervals(calibration_fixture().iloc[:0])
    with pytest.raises(ValueError, match="duplicate"):
        calibrate_intervals(
            pd.concat([calibration_fixture(), calibration_fixture().iloc[:1]])
        )
    with pytest.raises(ValueError, match="missing or unsupported"):
        add_intervals(forecast_fixture(), {})


def test_hand_calculated_interval_coverage_width_and_segments():
    frame = pd.DataFrame(
        {
            "model": "ridge",
            "actual": [0, 12, 2],
            "prediction": 5,
            "lower": [0, 0, 3],
            "upper": [10, 10, 7],
            "nominal_coverage": 0.8,
            "segment": ["high", "low", "low"],
        }
    )
    report = interval_metrics(frame)
    row = report["overall"][0]
    assert row["coverage"] == pytest.approx(1 / 3)
    assert row["below_rate"] == row["above_rate"] == pytest.approx(1 / 3)
    assert row["mean_width"] == pytest.approx(8)
    assert row["nominal_coverage"] == 0.8
    assert row["n_observations"] == 3
    assert len(report["by_segment"]) == 2
    assert report["scope"] == "caller_labeled"
    assert (
        interval_metrics(frame.drop(columns="nominal_coverage"))["overall"][0][
            "nominal_coverage"
        ]
        is None
    )


def test_interval_validation_and_inclusive_zero_width_coverage():
    frame = pd.DataFrame(
        {
            "model": ["ridge"],
            "actual": [0],
            "prediction": [0],
            "lower": [0],
            "upper": [0],
        }
    )
    assert interval_metrics(frame)["overall"][0]["coverage"] == 1
    for changed in [
        frame.assign(lower=1),
        frame.assign(upper=-1),
        frame.assign(actual=np.inf),
    ]:
        with pytest.raises(ValueError):
            interval_metrics(changed)
