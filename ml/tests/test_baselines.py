"""Synthetic examples proving one-step baselines use only available history."""

import numpy as np
import pandas as pd
import pytest

from ml.models.baselines import predict_baselines


def history(values=(1, 2, 7, 10), *, product="SYNTHETIC-A", start="2024-01-01"):
    return pd.DataFrame(
        {
            "stock_code": product,
            "week": pd.date_range(start, periods=len(values), freq="W-MON"),
            "gross_units": list(values),
        }
    )


def test_baselines_match_hand_calculated_forecasts_for_each_product():
    source = pd.concat(
        [history(), history((20, 0, 0, 0), product="SYNTHETIC-B")], ignore_index=True
    )
    result = predict_baselines(source, "2024-01-29")
    assert list(result.columns) == ["stock_code", "week", "model", "prediction"]
    assert result["week"].eq(pd.Timestamp("2024-01-29")).all()
    expected = {
        ("SYNTHETIC-A", "naive"): 10,
        ("SYNTHETIC-A", "moving_average_4"): 5,
        ("SYNTHETIC-A", "seasonal_naive_4"): 1,
        ("SYNTHETIC-B", "naive"): 0,
        ("SYNTHETIC-B", "moving_average_4"): 5,
        ("SYNTHETIC-B", "seasonal_naive_4"): 20,
    }
    assert result.set_index(["stock_code", "model"])["prediction"].to_dict() == expected


def test_configurable_windows_have_explicit_names_and_observed_lags():
    result = predict_baselines(
        history(), "2024-01-29", moving_window=2, seasonal_period=3
    )
    assert result.set_index("model")["prediction"].to_dict() == {
        "naive": 10,
        "moving_average_2": 8.5,
        "seasonal_naive_3": 2,
    }


def test_zero_demand_and_single_week_configuration():
    result = predict_baselines(
        history((0,)), "2024-01-08", moving_window=1, seasonal_period=1
    )
    assert result.prediction.eq(0).all()
    assert set(result.model) == {"naive", "moving_average_1", "seasonal_naive_1"}


def test_input_permutation_and_input_preservation():
    source = pd.concat(
        [history(), history((11, 12, 13, 14), product="SYNTHETIC-B")], ignore_index=True
    )
    original = source.copy(deep=True)
    expected = predict_baselines(source, "2024-01-29")
    actual = predict_baselines(source.sample(frac=1, random_state=13), "2024-01-29")
    pd.testing.assert_frame_equal(expected, actual)
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("future_week", ["2024-01-29", "2024-02-05"])
def test_current_or_future_rows_are_rejected_instead_of_silently_filtered(future_week):
    source = pd.concat(
        [
            history(),
            pd.DataFrame(
                {
                    "stock_code": ["SYNTHETIC-A"],
                    "week": [pd.Timestamp(future_week)],
                    "gross_units": [999999],
                }
            ),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValueError):
        predict_baselines(source, "2024-01-29")


def test_only_preceding_actual_week_may_be_revealed_for_rolling_evaluation():
    earlier = predict_baselines(history(), "2024-01-29")
    later = predict_baselines(history((1, 2, 7, 10, 50)), "2024-02-05")
    assert earlier.set_index("model").loc["naive", "prediction"] == 10
    assert later.set_index("model").loc["naive", "prediction"] == 50
    assert later.set_index("model").loc["moving_average_4", "prediction"] == 17.25
    assert later.set_index("model").loc["seasonal_naive_4", "prediction"] == 2


def test_observations_before_all_required_windows_cannot_change_forecasts():
    original = history((5000, 1, 2, 7, 10))
    changed = history((1, 1, 2, 7, 10))
    pd.testing.assert_frame_equal(
        predict_baselines(original, "2024-02-05"),
        predict_baselines(changed, "2024-02-05"),
    )


def test_short_history_is_explicit_including_unsupported_annual_period():
    with pytest.raises(ValueError, match="at least 4"):
        predict_baselines(history((1, 2, 3)), "2024-01-22")
    with pytest.raises(ValueError, match="at least 52"):
        predict_baselines(history(), "2024-01-29", seasonal_period=52)
    source = pd.concat(
        [history(), history((2, 3, 4), product="SYNTHETIC-B", start="2024-01-08")],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="SYNTHETIC-B"):
        predict_baselines(source, "2024-01-29")


@pytest.mark.parametrize(
    "arguments",
    [
        {"moving_window": 0},
        {"moving_window": -1},
        {"moving_window": 1.5},
        {"moving_window": True},
        {"seasonal_period": 0},
        {"seasonal_period": "4"},
        {"seasonal_period": False},
    ],
)
def test_invalid_window_arguments_are_rejected(arguments):
    with pytest.raises(ValueError, match="positive integer"):
        predict_baselines(history(), "2024-01-29", **arguments)


@pytest.mark.parametrize(
    "target",
    ["invalid", "2024-01-30", "2024-01-29 00:01:00", "2024-01-29T00:00:00Z", pd.NaT, 0],
)
def test_invalid_forecast_weeks_are_rejected(target):
    with pytest.raises(ValueError, match="target_week"):
        predict_baselines(history(), target)


@pytest.mark.parametrize(
    "kind", ["gap", "duplicate", "stale", "nan", "negative", "infinite", "empty"]
)
def test_invalid_or_stale_histories_are_rejected(kind):
    source = history()
    if kind == "gap":
        source = source.drop(index=1)
    elif kind == "duplicate":
        source = pd.concat([source, source.iloc[[0]]], ignore_index=True)
    elif kind == "stale":
        source["week"] -= pd.Timedelta(weeks=1)
    elif kind == "nan":
        source["gross_units"] = np.nan
    elif kind == "negative":
        source["gross_units"] = -1
    elif kind == "infinite":
        source["gross_units"] = np.inf
    elif kind == "empty":
        source = source.iloc[:0]
    with pytest.raises(ValueError):
        predict_baselines(source, "2024-01-29")
