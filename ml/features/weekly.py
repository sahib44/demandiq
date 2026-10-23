"""Features available before each forecasted Monday begins.

Historical windows always end at the preceding week. Warm-up NaNs remain NaN;
encoding, imputation and other fitted preprocessing belong inside future training
folds. The product identifier remains categorical text. Calendar indicators are
known in advance and describe ISO week numbers, not observed holiday effects.
"""

import re
from collections.abc import Sequence

import numpy as np
import pandas as pd

PANEL_COLUMNS = (
    "stock_code",
    "week",
    "gross_units",
    "returned_units",
    "cancellation_units",
    "net_units",
    "revenue",
    "transactions",
    "unique_customers",
    "average_price",
)

FEATURE_COLUMNS = (
    "stock_code",
    "demand_lag1",
    "demand_lag2",
    "demand_lag4",
    "demand_lag8",
    "rolling_mean4",
    "rolling_mean8",
    "rolling_mean12",
    "rolling_std4",
    "rolling_std8",
    "recent_trend",
    "previous_week_revenue",
    "previous_week_average_price",
    "previous_week_transactions",
    "previous_week_unique_customers",
    "recent_return_rate",
    "recent_cancellation_rate",
    "month",
    "iso_week",
    "quarter",
)


def validate_weekly_panel(
    panel: pd.DataFrame, *, required_columns: Sequence[str] = ("gross_units",)
) -> pd.DataFrame:
    """Return a sorted copy; reject missing/duplicate/gapped product-week rows.

    This shared structural check also supports baseline histories containing only
    the product, week and target. It does not fill missing weeks or estimate data.
    """
    if not isinstance(panel, pd.DataFrame):
        raise ValueError("Weekly panel must be a pandas DataFrame.")
    if panel.columns.duplicated().any():
        raise ValueError("Weekly panel must not contain duplicate column names.")
    required = {"stock_code", "week", "gross_units", *required_columns}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(
            f"Weekly panel is missing required columns: {', '.join(missing)}."
        )
    if panel.empty:
        raise ValueError("Weekly panel must contain at least one product-week row.")
    result = panel.copy(deep=True)
    if (
        result["stock_code"].isna().any()
        or not result["stock_code"]
        .map(lambda value: isinstance(value, str) and bool(value.strip()))
        .all()
    ):
        raise ValueError("stock_code must contain nonempty string identifiers.")
    if pd.api.types.is_numeric_dtype(result["week"].dtype):
        raise ValueError(
            "week must contain naive Monday dates, not numeric timestamps."
        )
    try:
        weeks = pd.to_datetime(result["week"], errors="raise")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("week must contain valid naive Monday dates.") from exc
    if not pd.api.types.is_datetime64_any_dtype(weeks.dtype) or isinstance(
        weeks.dtype, pd.DatetimeTZDtype
    ):
        raise ValueError("week must contain timezone-naive Monday dates.")
    if (
        weeks.isna().any()
        or not (weeks.dt.dayofweek.eq(0) & weeks.eq(weeks.dt.normalize())).all()
    ):
        raise ValueError("week must be Monday at 00:00 with no missing dates.")
    result["week"] = weeks
    for column in required - {"stock_code", "week"}:
        series = result[column]
        if series.map(lambda value: isinstance(value, bool | np.bool_)).any():
            raise ValueError(f"{column} must contain numeric values, not booleans.")
        try:
            numeric = pd.to_numeric(series, errors="raise")
            values = numeric.to_numpy(dtype=float, na_value=np.nan)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{column} must contain numeric values.") from exc
        allow_missing = column == "average_price"
        valid = np.isfinite(values) | (np.isnan(values) if allow_missing else False)
        if not valid.all() or (column != "net_units" and (values < 0).any()):
            raise ValueError(f"{column} must contain finite nonnegative values.")
        result[column] = numeric
    if result.duplicated(["stock_code", "week"]).any():
        raise ValueError("Weekly panel contains duplicate product-week rows.")
    result = result.sort_values(["stock_code", "week"], kind="stable").reset_index(
        drop=True
    )
    deltas = result.groupby("stock_code", sort=False, observed=True)["week"].diff()
    if not (deltas.isna() | deltas.eq(pd.Timedelta(weeks=1))).all():
        raise ValueError(
            "Each product must have contiguous weekly rows; fill gaps upstream."
        )
    return result


def _seasonal_config(
    seasonal_indicators: dict[str, list[int]] | None,
) -> dict[str, list[int]]:
    if seasonal_indicators is None:
        return {}
    if not isinstance(seasonal_indicators, dict):
        raise ValueError(
            "seasonal_indicators must map safe names to lists of ISO weeks."
        )
    result = {}
    for name, weeks in seasonal_indicators.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name):
            raise ValueError("Seasonal names must match [a-z][a-z0-9_]{0,47}.")
        if not isinstance(weeks, list) or any(
            type(week) is not int or not 1 <= week <= 53 for week in weeks
        ):
            raise ValueError(
                "Seasonal indicators must contain integer ISO weeks from 1 to 53."
            )
        result[name] = sorted(set(weeks))
    return dict(sorted(result.items()))


def feature_columns(
    seasonal_indicators: dict[str, list[int]] | None = None,
) -> tuple[str, ...]:
    """Return feature names, including configured seasonal_<name> columns."""
    indicators = _seasonal_config(seasonal_indicators)
    return (*FEATURE_COLUMNS, *(f"seasonal_{name}" for name in indicators))


def generate_features(
    panel: pd.DataFrame,
    *,
    seasonal_indicators: dict[str, list[int]] | None = None,
) -> pd.DataFrame:
    """Generate unfitted one-week-ahead features without reading current actuals.

    ``recent_trend`` is the previous four-week mean minus the mean of the four
    weeks immediately before that. Return/cancellation rates are separate ratios
    of preceding four-week unit sums to preceding four-week gross unit sums;
    a zero denominator yields NaN. Rates may exceed one because credits need not
    match purchases in the same period. Standard deviations use ``ddof=0``.
    """
    frame = validate_weekly_panel(panel, required_columns=PANEL_COLUMNS)
    indicators = _seasonal_config(seasonal_indicators)
    result = frame[["stock_code", "week", "gross_units"]].copy()
    grouped = frame.groupby("stock_code", sort=False, observed=True)
    demand = grouped["gross_units"]
    for lag in (1, 2, 4, 8):
        result[f"demand_lag{lag}"] = demand.shift(lag)
    for window in (4, 8, 12):
        result[f"rolling_mean{window}"] = demand.transform(
            lambda series, size=window: series.shift(1)
            .rolling(size, min_periods=size)
            .mean()
        )
    for window in (4, 8):
        result[f"rolling_std{window}"] = demand.transform(
            lambda series, size=window: series.shift(1)
            .rolling(size, min_periods=size)
            .std(ddof=0)
        )
    result["recent_trend"] = result["rolling_mean4"] - demand.transform(
        lambda series: series.shift(5).rolling(4, min_periods=4).mean()
    )
    for source, destination in (
        ("revenue", "previous_week_revenue"),
        ("average_price", "previous_week_average_price"),
        ("transactions", "previous_week_transactions"),
        ("unique_customers", "previous_week_unique_customers"),
    ):
        result[destination] = grouped[source].shift(1)
    previous_gross = demand.transform(
        lambda series: series.shift(1).rolling(4, min_periods=4).sum()
    ).replace(0, np.nan)
    for source, destination in (
        ("returned_units", "recent_return_rate"),
        ("cancellation_units", "recent_cancellation_rate"),
    ):
        previous_credits = grouped[source].transform(
            lambda series: series.shift(1).rolling(4, min_periods=4).sum()
        )
        result[destination] = previous_credits / previous_gross
    result["month"] = frame["week"].dt.month
    result["iso_week"] = frame["week"].dt.isocalendar().week.astype("int64")
    result["quarter"] = frame["week"].dt.quarter
    for name, weeks in indicators.items():
        result[f"seasonal_{name}"] = result["iso_week"].isin(weeks).astype("int8")
    ordered = ["stock_code", "week", "gross_units", *feature_columns(indicators)[1:]]
    return result.loc[:, ordered]
