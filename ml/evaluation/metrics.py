"""JSON-safe forecast evaluation with training-only demand-volume segments."""

from __future__ import annotations

import math
from datetime import date, datetime
from numbers import Integral, Real
from typing import Any

import numpy as np
import pandas as pd

PREDICTION_COLUMNS = frozenset(
    {"stock_code", "week", "model", "prediction", "actual", "fold"}
)
OBSERVATION_KEYS = ["fold", "stock_code", "week"]
METRIC_DEFINITIONS = {
    "evaluation_scope": "Validation observations only; no final test evaluation or model selection.",
    "n_observations": "Number of product-week-fold observations, each weighted equally.",
    "mae": "Mean absolute error, in demand units.",
    "rmse": "Square root of mean squared error, in demand units.",
    "wape": "100 * sum(abs(prediction - actual)) / sum(actual); percent, unbounded above. Null when total actual demand is zero, including perfect zero forecasts.",
    "wape_status": "defined or undefined_zero_actual; undefined values are JSON null.",
    "smape": "Mean of 200 * abs(prediction - actual) / (actual + prediction); percent in [0, 200]. A zero/zero pair contributes zero.",
    "bias": "Mean(prediction - actual), in demand units; positive is overforecasting.",
    "segments": "Within each fold's evaluated product cohort, rank training_units descending, breaking ties by stock_code ascending. Divide ranks into high, medium and low thirds (earlier thirds receive any extra products). Evaluation demand never determines segments.",
    "aggregation": "Overall, product and segment metrics pool observation-level errors across folds; by_week retains fold identity, including when validation windows overlap.",
    "error_direction": "Underforecast units=sum(max(actual-prediction,0)); overforecast units=sum(max(prediction-actual,0)); exact means prediction equals actual. Counts are product-week-fold observations.",
}


def _values(values: Any, name: str) -> np.ndarray:
    try:
        raw = np.asarray(values)
        if np.iscomplexobj(raw) or any(
            isinstance(value, bool | np.bool_)
            for value in np.asarray(values, dtype=object).flat
        ):
            raise ValueError
        array = np.asarray(values, dtype="float64")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must contain finite nonnegative numbers") from exc
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a nonempty one-dimensional array")
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError(f"{name} must contain finite nonnegative numbers")
    return array


def _finite(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Forecast metrics exceed the supported numerical range")
    return result


def forecast_metrics(
    actual: Any, predicted: Any
) -> dict[str, int | float | str | None]:
    """Evaluate aligned nonnegative demand; percentages are never silently clipped.

    A Series pair must have the same index. Other one-dimensional inputs align
    positionally. Scaled reductions avoid overflow for large representable units.
    Values whose derived percentages exceed float64 raise a helpful ValueError.
    """
    if isinstance(actual, pd.Series) and isinstance(predicted, pd.Series):
        if not actual.index.equals(predicted.index):
            raise ValueError("actual and predicted Series must have aligned indexes")
    observed = _values(actual, "actual")
    forecast = _values(predicted, "predicted")
    if observed.shape != forecast.shape:
        raise ValueError(
            "actual and predicted must have the same number of observations"
        )
    error = forecast - observed
    absolute = np.abs(error)
    scale = float(absolute.max())
    if scale:
        scaled_error = error / scale
        mae = scale * float(np.mean(np.abs(scaled_error)))
        rmse = scale * math.sqrt(float(np.mean(scaled_error**2)))
        bias = scale * float(np.mean(scaled_error))
    else:
        mae = rmse = bias = 0.0
    actual_scale = float(observed.max())
    if actual_scale:
        # Ratio of scaled means equals ratio of sums without overflowing sums.
        with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
            wape = _finite(
                100.0
                * (scale / actual_scale)
                * float(np.mean(absolute / scale) if scale else 0.0)
                / float(np.mean(observed / actual_scale))
            )
        wape_status = "defined"
    else:
        wape = None
        wape_status = "undefined_zero_actual"
    pair_scale = np.maximum(observed, forecast)
    pair_error = np.zeros_like(observed)
    nonzero = pair_scale > 0
    denominator = (
        observed[nonzero] / pair_scale[nonzero]
        + forecast[nonzero] / pair_scale[nonzero]
    )
    pair_error[nonzero] = (
        200.0 * (absolute[nonzero] / pair_scale[nonzero]) / denominator
    )
    return {
        "n_observations": int(observed.size),
        "mae": _finite(mae),
        "rmse": _finite(rmse),
        "wape": wape,
        "wape_status": wape_status,
        "smape": _finite(float(np.mean(pair_error))),
        "bias": _finite(bias),
    }


def _table(frame: pd.DataFrame, columns: frozenset[str], name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{name} must be a nonempty DataFrame")
    if frame.columns.has_duplicates or not columns.issubset(frame.columns):
        raise ValueError(
            f"{name} must contain unique required columns: {sorted(columns)}"
        )
    result = frame.loc[:, sorted(columns)].copy()
    if result.isna().any().any():
        raise ValueError(f"{name} must not contain missing values")
    for field in ("stock_code", "model"):
        if (
            field in result
            and not result[field]
            .map(lambda value: isinstance(value, str) and bool(value.strip()))
            .all()
        ):
            raise ValueError(f"{name}.{field} must contain nonempty strings")
    if not result.fold.map(
        lambda value: (isinstance(value, str) and bool(value.strip()))
        or (isinstance(value, Integral) and not isinstance(value, bool))
    ).all():
        raise ValueError(f"{name}.fold must contain nonempty strings or integer labels")
    result["fold"] = result.fold.map(str)
    return result


def validated_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    """Return canonical, aligned observations for both reports and figures."""
    result = _table(predictions, PREDICTION_COLUMNS, "predictions")
    if not result.week.map(
        lambda value: isinstance(value, str | date | datetime | np.datetime64)
    ).all():
        raise ValueError("predictions.week must contain valid timezone-naive dates")
    try:
        result["week"] = pd.to_datetime(result.week, errors="raise", format="ISO8601")
        if isinstance(result.week.dtype, pd.DatetimeTZDtype):
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            "predictions.week must contain valid timezone-naive dates"
        ) from exc
    if result.week.isna().any():
        raise ValueError("predictions.week must not contain missing dates")
    result["actual"] = _values(result.actual, "predictions.actual")
    result["prediction"] = _values(result.prediction, "predictions.prediction")
    if result.duplicated([*OBSERVATION_KEYS, "model"]).any():
        raise ValueError("predictions contains duplicate fold/product/week/model rows")
    observations = result.groupby(OBSERVATION_KEYS, sort=True)
    if not observations.model.nunique().eq(result.model.nunique()).all():
        raise ValueError(
            "Every model must predict the same fold/product/week observations"
        )
    if not observations.actual.nunique().eq(1).all():
        raise ValueError("Actual demand must agree across models for each observation")
    return result.sort_values([*OBSERVATION_KEYS, "model"], kind="stable").reset_index(
        drop=True
    )


def _training_units(value: Any) -> int | float:
    """Retain exact integer ranks instead of collapsing int64 values to float64."""
    if isinstance(value, bool | np.bool_) or not isinstance(value, Real):
        raise ValueError(
            "training_volumes.training_units must contain finite nonnegative numbers"
        )
    if isinstance(value, Integral):
        if value >= 0:
            return int(value)
    elif math.isfinite(value) and value >= 0:
        return float(value)
    raise ValueError(
        "training_volumes.training_units must contain finite nonnegative numbers"
    )


def _segments(
    predictions: pd.DataFrame, training_volumes: pd.DataFrame
) -> pd.DataFrame:
    volumes = _table(
        training_volumes,
        frozenset({"fold", "stock_code", "training_units"}),
        "training_volumes",
    )
    volumes["training_units"] = pd.Series(
        [_training_units(value) for value in volumes.training_units],
        index=volumes.index,
        dtype=object,
    )
    if volumes.duplicated(["fold", "stock_code"]).any():
        raise ValueError("training_volumes contains duplicate fold/product rows")
    cohort = predictions[["fold", "stock_code"]].drop_duplicates()
    volumes = cohort.merge(
        volumes, on=["fold", "stock_code"], how="left", validate="one_to_one"
    )
    if volumes.training_units.isna().any():
        raise ValueError("training_volumes must cover every evaluated fold/product")
    # pandas' multi-column categorical sort may itself coerce mixed object
    # integers/floats to float64. Python scalar comparisons preserve exact ints.
    sort_keys = [
        (row.fold, -row.training_units, row.stock_code)
        for row in volumes.itertuples(index=False)
    ]
    ordering = sorted(range(len(volumes)), key=sort_keys.__getitem__)
    volumes = volumes.iloc[ordering].reset_index(drop=True)
    rank = volumes.groupby("fold", sort=False).cumcount()
    count = volumes.groupby("fold", sort=False).stock_code.transform("size")
    volumes["segment"] = (rank * 3 // count).map({0: "high", 1: "medium", 2: "low"})
    return volumes


def _records(frame: pd.DataFrame, group_columns: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for keys, group in frame.groupby(group_columns, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        record = dict(zip(group_columns, keys, strict=True))
        if "week" in record:
            record["week"] = record["week"].isoformat()
        record.update(forecast_metrics(group.actual, group.prediction))
        records.append(record)
    return records


def evaluate_predictions(
    predictions: pd.DataFrame, *, training_volumes: pd.DataFrame
) -> dict[str, Any]:
    """Compare identical validation observations; never infer segments from targets.

    Required prediction fields are stock_code, week, model, prediction, actual,
    fold. Every model must cover the same observation keys, with consistent
    actuals. Training volumes must provide one nonnegative training_units per
    evaluated fold/product. Additional training products are ignored. Callers
    own chronological split enforcement; this interface contains no test data.
    """
    frame = validated_predictions(predictions)
    segments = _segments(frame, training_volumes)
    frame = frame.merge(
        segments[["fold", "stock_code", "segment"]],
        on=["fold", "stock_code"],
        how="left",
        validate="many_to_one",
    )
    direction = []
    for model, group in frame.groupby("model", sort=True):
        error = group.prediction.to_numpy() - group.actual.to_numpy()
        try:
            under_units = _finite(math.fsum((-error[error < 0]).tolist()))
            over_units = _finite(math.fsum(error[error > 0].tolist()))
        except OverflowError as exc:
            raise ValueError(
                "Error unit totals exceed the supported numerical range"
            ) from exc
        direction.append(
            {
                "model": model,
                "underforecast_count": int((error < 0).sum()),
                "overforecast_count": int((error > 0).sum()),
                "exact_count": int((error == 0).sum()),
                "underforecast_units": under_units,
                "overforecast_units": over_units,
            }
        )
    return {
        "evaluation_scope": "validation",
        "overall": _records(frame, ["model"]),
        "by_fold": _records(frame, ["model", "fold"]),
        "by_product": _records(frame, ["model", "stock_code"]),
        "by_week": _records(frame, ["model", "fold", "week"]),
        "by_segment": _records(frame, ["model", "segment"]),
        "error_direction": direction,
        "training_segments": segments.to_dict(orient="records"),
        "metric_definitions": dict(METRIC_DEFINITIONS),
    }
