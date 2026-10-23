"""Hand-calculated synthetic feature and temporal leakage checks."""

import numpy as np
import pandas as pd
import pytest

from ml.features.weekly import FEATURE_COLUMNS, feature_columns, generate_features


def panel(size=13, *, start="2024-01-01", product="SYNTHETIC-A", offset=0):
    gross = np.arange(1, size + 1, dtype=float) + offset
    return pd.DataFrame(
        {
            "stock_code": product,
            "week": pd.date_range(start, periods=size, freq="W-MON"),
            "gross_units": gross,
            "returned_units": 1.0,
            "cancellation_units": 2.0,
            "net_units": gross - 3,
            "revenue": gross * 2,
            "transactions": np.arange(1, size + 1),
            "unique_customers": np.arange(1, size + 1),
            "average_price": 2.0,
        }
    )


def test_features_match_hand_calculations_and_warmup_boundaries():
    result = generate_features(panel())
    assert result.loc[0, list(FEATURE_COLUMNS[1:-3])].isna().all()
    assert result.loc[8, "demand_lag1"] == 8
    assert result.loc[8, "demand_lag2"] == 7
    assert result.loc[8, "demand_lag4"] == 5
    assert result.loc[8, "demand_lag8"] == 1
    assert pd.isna(result.loc[3, "rolling_mean4"])
    assert result.loc[4, "rolling_mean4"] == 2.5
    assert result.loc[8, "rolling_mean8"] == 4.5
    assert pd.isna(result.loc[11, "rolling_mean12"])
    assert result.loc[12, "rolling_mean12"] == 6.5
    assert result.loc[4, "rolling_std4"] == pytest.approx(np.sqrt(1.25))
    assert result.loc[8, "rolling_std8"] == pytest.approx(
        np.std(np.arange(1, 9), ddof=0)
    )
    assert pd.isna(result.loc[7, "recent_trend"])
    assert result.loc[8, "recent_trend"] == 4
    assert result.loc[4, "previous_week_revenue"] == 8
    assert result.loc[4, "previous_week_average_price"] == 2
    assert result.loc[4, "previous_week_transactions"] == 4
    assert result.loc[4, "previous_week_unique_customers"] == 4
    assert result.loc[4, "recent_return_rate"] == pytest.approx(4 / 10)
    assert result.loc[4, "recent_cancellation_rate"] == pytest.approx(8 / 10)
    assert result.loc[0, "month"] == 1
    assert result.loc[0, "iso_week"] == 1
    assert result.loc[0, "quarter"] == 1
    assert list(result.columns) == [
        "stock_code",
        "week",
        "gross_units",
        *FEATURE_COLUMNS[1:],
    ]


def test_product_boundaries_order_invariance_and_input_preservation():
    source = pd.concat(
        [panel(), panel(product="SYNTHETIC-B", offset=100)], ignore_index=True
    )
    original = source.copy(deep=True)
    expected = generate_features(source)
    actual = generate_features(
        source.sample(frac=1, random_state=19).reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(expected, actual)
    pd.testing.assert_frame_equal(source, original)
    second = actual.loc[actual.stock_code.eq("SYNTHETIC-B")].reset_index(drop=True)
    assert pd.isna(second.loc[0, "demand_lag1"])
    assert second.loc[4, "rolling_mean4"] == 102.5
    assert second.loc[8, "recent_trend"] == 4


@pytest.mark.parametrize("cutoff", [0, 4, 8, 12])
def test_current_and_future_actuals_cannot_change_available_features(cutoff):
    source = panel(16)
    original_features = generate_features(source)
    changed = source.copy(deep=True)
    for column in (
        "gross_units",
        "returned_units",
        "cancellation_units",
        "revenue",
        "transactions",
        "unique_customers",
        "average_price",
    ):
        changed.loc[cutoff:, column] = changed.loc[cutoff:, column] * 37 + 11
    changed.loc[cutoff:, "net_units"] = -999
    changed_features = generate_features(changed)
    pd.testing.assert_frame_equal(
        original_features.loc[:cutoff, list(FEATURE_COLUMNS)],
        changed_features.loc[:cutoff, list(FEATURE_COLUMNS)],
    )
    if cutoff + 1 < len(source):
        assert (
            changed_features.loc[cutoff + 1, "demand_lag1"]
            != original_features.loc[cutoff + 1, "demand_lag1"]
        )


def test_zero_demand_keeps_undefined_rates_and_missing_prices():
    source = panel()
    for column in (
        "gross_units",
        "returned_units",
        "cancellation_units",
        "net_units",
        "revenue",
    ):
        source[column] = 0.0
    source["average_price"] = np.nan
    result = generate_features(source)
    assert result.loc[4, "rolling_mean4"] == 0
    assert result.loc[4, "rolling_std4"] == 0
    assert result["recent_return_rate"].isna().all()
    assert result["recent_cancellation_rate"].isna().all()
    assert result["previous_week_average_price"].isna().all()


def test_calendar_indicators_are_known_in_advance_and_handle_iso_week_53():
    source = panel(2, start="2020-12-28")
    indicators = {"year_start": [1], "year_end": [52, 53, 53], "empty": []}
    result = generate_features(source, seasonal_indicators=indicators)
    assert result["iso_week"].tolist() == [53, 1]
    assert result["seasonal_year_end"].tolist() == [1, 0]
    assert result["seasonal_year_start"].tolist() == [0, 1]
    assert result["seasonal_empty"].tolist() == [0, 0]
    assert feature_columns(indicators)[-3:] == (
        "seasonal_empty",
        "seasonal_year_end",
        "seasonal_year_start",
    )
    pd.testing.assert_frame_equal(
        result,
        generate_features(
            source, seasonal_indicators=dict(reversed(list(indicators.items())))
        ),
    )


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "missing_column",
        "duplicate_column",
        "duplicate_row",
        "gap",
        "tuesday",
        "time",
        "timezone",
        "missing_date",
        "numeric_date",
        "negative",
        "infinite",
        "missing_target",
        "boolean",
        "numeric_stock_code",
        "missing_stock_code",
    ],
)
def test_invalid_panels_are_rejected(kind):
    source = panel()
    if kind == "empty":
        source = source.iloc[:0]
    elif kind == "missing_column":
        source = source.drop(columns="returned_units")
    elif kind == "duplicate_column":
        source = pd.concat([source, source[["gross_units"]]], axis=1)
    elif kind == "duplicate_row":
        source = pd.concat([source, source.iloc[[0]]], ignore_index=True)
    elif kind == "gap":
        source = source.drop(index=4)
    elif kind == "tuesday":
        source["week"] += pd.Timedelta(days=1)
    elif kind == "time":
        source["week"] += pd.Timedelta(hours=1)
    elif kind == "timezone":
        source["week"] = source["week"].dt.tz_localize("UTC")
    elif kind == "missing_date":
        source.loc[0, "week"] = pd.NaT
    elif kind == "numeric_date":
        source["week"] = source["week"].astype("int64")
    elif kind == "negative":
        source.loc[0, "gross_units"] = -1
    elif kind == "infinite":
        source.loc[0, "gross_units"] = np.inf
    elif kind == "missing_target":
        source.loc[0, "gross_units"] = np.nan
    elif kind == "boolean":
        source["gross_units"] = True
    elif kind == "numeric_stock_code":
        source["stock_code"] = 123
    elif kind == "missing_stock_code":
        source.loc[0, "stock_code"] = None
    with pytest.raises(ValueError):
        generate_features(source)


@pytest.mark.parametrize(
    "indicators",
    [
        [],
        {"Unsafe Name": [1]},
        {"x.y": [1]},
        {"": [1]},
        {"x": [0]},
        {"x": [54]},
        {"x": [True]},
        {"x": ["1"]},
        {"x": (1, 2)},
    ],
)
def test_invalid_seasonal_indicator_configuration_is_rejected(indicators):
    with pytest.raises(ValueError):
        generate_features(panel(), seasonal_indicators=indicators)


def test_iso_date_strings_are_supported_without_changing_input():
    source = panel()
    source["week"] = source["week"].dt.strftime("%Y-%m-%d")
    result = generate_features(source)
    assert pd.api.types.is_datetime64_dtype(result["week"])
    assert isinstance(source.loc[0, "week"], str)
