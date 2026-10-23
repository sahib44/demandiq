"""Strictly chronological one-step baselines with complete-history requirements."""

from datetime import date, datetime

import pandas as pd

from ml.features.weekly import validate_weekly_panel


def predict_baselines(
    history: pd.DataFrame,
    target_week: pd.Timestamp | str | date | datetime,
    *,
    seasonal_period: int = 4,
    moving_window: int = 4,
) -> pd.DataFrame:
    """Forecast each product using only history before target_week.

    The seasonal period defaults to a predeclared four-week recurrence comparator;
    it is not evidence that retail demand has a true four-week season. A 52-week
    comparator requires 52 observed weeks and is never silently substituted.
    One-step rolling evaluation may reveal a preceding actual week only after
    that week has occurred. Never pass an entire held-out block as history.
    """
    for name, value in (
        ("seasonal_period", seasonal_period),
        ("moving_window", moving_window),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if isinstance(target_week, int | float | bool):
        raise ValueError("target_week must be a naive Monday date.")
    try:
        target = pd.Timestamp(target_week)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("target_week must be a valid naive Monday date.") from exc
    if pd.isna(target) or target.tzinfo is not None:
        raise ValueError("target_week must be a timezone-naive Monday date.")
    if target.dayofweek != 0 or target != target.normalize():
        raise ValueError("target_week must be Monday at 00:00.")
    frame = validate_weekly_panel(history)
    if frame["week"].ge(target).any():
        raise ValueError("History must contain only weeks strictly before target_week.")
    minimum = max(seasonal_period, moving_window)
    rows = []
    for stock_code, group in frame.groupby("stock_code", sort=False, observed=True):
        if group["week"].iloc[-1] != target - pd.Timedelta(weeks=1):
            raise ValueError(
                "Every product history must end exactly one week before target_week."
            )
        if len(group) < minimum:
            raise ValueError(
                f"Product {stock_code!r} has {len(group)} weeks; at least {minimum} are required."
            )
        values = group["gross_units"]
        predictions = (
            ("naive", float(values.iloc[-1])),
            (
                f"moving_average_{moving_window}",
                float(values.iloc[-moving_window:].mean()),
            ),
            (f"seasonal_naive_{seasonal_period}", float(values.iloc[-seasonal_period])),
        )
        rows.extend(
            {
                "stock_code": stock_code,
                "week": target,
                "model": model,
                "prediction": prediction,
            }
            for model, prediction in predictions
        )
    return pd.DataFrame(rows, columns=["stock_code", "week", "model", "prediction"])
