"""Practical, frozen scaled-residual intervals for chronological forecasts.

The finite-sample quantile rule is useful for retrospective uncertainty estimates.
Serial dependence, product heterogeneity and cohort shift prevent a distribution-
free coverage guarantee here. Calibration must follow frozen model selection;
forecast periods must follow the complete calibration period.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

METHOD = "scaled_absolute_residual_higher_quantile"
WARNING = (
    "Empirical retrospective estimate, not a coverage guarantee. Residual stability "
    "and supplied preforecast scales are assumptions; time dependence, product "
    "heterogeneity and cohort shift can reduce future coverage. Model selection "
    "must be frozen before calibration; intervals must not adapt to future actuals."
)


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool | np.bool_) or not isinstance(value, Real):
        raise ValueError(
            f"{name} must be a finite {'positive' if positive else 'nonnegative'} number"
        )
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(
            f"{name} must be a finite {'positive' if positive else 'nonnegative'} number"
        )
    return result


def _coverage(value: Any) -> float:
    result = _number(value, "coverage")
    if not 0 < result < 1:
        raise ValueError("coverage must be strictly between zero and one")
    return result


def _dates(values: pd.Series, name: str) -> pd.Series:
    if not values.map(
        lambda value: isinstance(value, str | date | datetime | np.datetime64)
    ).all():
        raise ValueError(f"{name} must contain timezone-naive ISO dates")
    try:
        result = pd.to_datetime(values, format="ISO8601", errors="raise")
        if isinstance(result.dtype, pd.DatetimeTZDtype) or result.isna().any():
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must contain timezone-naive ISO dates") from exc


def _frame(source: pd.DataFrame, columns: set[str], name: str) -> pd.DataFrame:
    if not isinstance(source, pd.DataFrame) or source.empty:
        raise ValueError(f"{name} must be a nonempty DataFrame")
    if source.columns.has_duplicates or not columns.issubset(source.columns):
        raise ValueError(f"{name} requires unique columns: {sorted(columns)}")
    result = source.copy(deep=True)
    if result.loc[:, sorted(columns)].isna().any().any():
        raise ValueError(f"{name} required fields must not contain missing values")
    for field in ("model", "stock_code", "segment"):
        if (
            field in columns
            and not result[field]
            .map(lambda value: isinstance(value, str) and bool(value.strip()))
            .all()
        ):
            raise ValueError(f"{name}.{field} must contain nonempty strings")
    for field in columns & {"actual", "prediction", "scale", "lower", "upper"}:
        result[field] = result[field].map(
            lambda value, field=field: _number(value, f"{name}.{field}")
        )
    if "week" in columns:
        result["week"] = _dates(result.week, f"{name}.week")
    keys = [field for field in ("model", "stock_code", "week") if field in columns]
    if len(keys) == 3 and result.duplicated(keys).any():
        raise ValueError(f"{name} contains duplicate model/product/week observations")
    return result


def calibrate_intervals(
    calibration_predictions: pd.DataFrame,
    *,
    coverage: float = 0.8,
    scale_floor: float = 10.0,
) -> dict[str, dict[str, Any]]:
    """Freeze per-model radii from a reserved historical calibration window.

    ``scale`` must be supplied from information available before each forecast,
    such as its prior four-week mean; this function cannot verify its lineage.
    With n residuals use rank min(n, ceil((n+1)*coverage)), counting from one.
    A capped rank is explicitly flagged as insufficient finite-sample support.
    """
    nominal = _coverage(coverage)
    floor = _number(scale_floor, "scale_floor", positive=True)
    frame = _frame(
        calibration_predictions,
        {"stock_code", "week", "model", "actual", "prediction", "scale"},
        "calibration_predictions",
    )
    result: dict[str, dict[str, Any]] = {}
    for model, group in frame.groupby("model", sort=True):
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            scores = np.abs(
                group.prediction.to_numpy() - group.actual.to_numpy()
            ) / np.maximum(group.scale.to_numpy(), floor)
        if not np.isfinite(scores).all():
            raise ValueError(
                "Normalized calibration residuals exceed the supported numerical range"
            )
        count = len(scores)
        requested = math.ceil((count + 1) * nominal)
        rank = min(count, requested)
        insufficient = requested > count
        result[model] = {
            "method": METHOD,
            "nominal_coverage": nominal,
            "scale_floor": floor,
            "n_calibration": count,
            "calibration_start": group.week.min().isoformat(),
            "calibration_end": group.week.max().isoformat(),
            "normalized_radius": float(np.sort(scores)[rank - 1]),
            "requested_rank": requested,
            "quantile_rank": rank,
            "insufficient_samples": insufficient,
            "warning": WARNING
            + (
                " Requested quantile rank exceeds available residuals; maximum observed score is used."
                if insufficient
                else ""
            ),
        }
    return result


def add_intervals(
    predictions: pd.DataFrame, calibration: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Apply frozen radii to later predictions without reading their actuals.

    Lower bounds clip at zero; upper bounds retain the entire empirical radius.
    Existing columns and row order are preserved; input objects are not mutated.
    """
    frame = _frame(
        predictions,
        {"stock_code", "week", "model", "prediction", "scale"},
        "predictions",
    )
    original_index = frame.index
    frame = frame.reset_index(drop=True)
    if not isinstance(calibration, dict):
        raise ValueError("calibration must map model names to frozen metadata")
    lower = pd.Series(index=frame.index, dtype="float64")
    upper = pd.Series(index=frame.index, dtype="float64")
    nominal = pd.Series(index=frame.index, dtype="float64")
    labels = pd.Series(index=frame.index, dtype="string")
    for model, group in frame.groupby("model", sort=True):
        metadata = calibration.get(model)
        if not isinstance(metadata, dict) or metadata.get("method") != METHOD:
            raise ValueError(
                f"Frozen calibration metadata is missing or unsupported for model {model}"
            )
        try:
            radius = _number(metadata["normalized_radius"], "normalized_radius")
            floor = _number(metadata["scale_floor"], "scale_floor", positive=True)
            coverage = _coverage(metadata["nominal_coverage"])
            end = _dates(
                pd.Series([metadata["calibration_end"]]), "calibration_end"
            ).iloc[0]
        except KeyError as exc:
            raise ValueError("Frozen calibration metadata is incomplete") from exc
        if not group.week.gt(end).all():
            raise ValueError(
                "Every prediction week must be strictly after its model's calibration_end"
            )
        with np.errstate(over="ignore", invalid="ignore"):
            width = radius * np.maximum(group.scale.to_numpy(), floor)
            high = group.prediction.to_numpy() + width
        if not np.isfinite(width).all() or not np.isfinite(high).all():
            raise ValueError(
                "Prediction interval bounds exceed the supported numerical range"
            )
        lower.loc[group.index] = np.maximum(0, group.prediction.to_numpy() - width)
        upper.loc[group.index] = high
        nominal.loc[group.index] = coverage
        labels.loc[group.index] = (
            f"empirical scaled-residual interval; nominal {coverage:.1%}; no time-series coverage guarantee"
        )
    frame["lower"] = lower
    frame["upper"] = upper
    frame["nominal_coverage"] = nominal
    frame["uncertainty_label"] = labels
    frame.index = original_index
    return frame


def interval_metrics(bounded: pd.DataFrame) -> dict[str, Any]:
    """Measure retrospective inclusive coverage and widths; caller labels its scope."""
    columns = {"actual", "prediction", "lower", "upper", "model"}
    if isinstance(bounded, pd.DataFrame) and "segment" in bounded.columns:
        columns.add("segment")
    frame = _frame(bounded, columns, "bounded")
    if (frame.lower > frame.prediction).any() or (frame.upper < frame.prediction).any():
        raise ValueError("Interval bounds must contain the point prediction")
    if "nominal_coverage" in frame:
        frame["nominal_coverage"] = frame.nominal_coverage.map(_coverage)
        if not frame.groupby("model").nominal_coverage.nunique().eq(1).all():
            raise ValueError("Each model must have one frozen nominal_coverage")

    def records(keys: list[str]) -> list[dict[str, Any]]:
        rows = []
        for labels, group in frame.groupby(keys, sort=True):
            if not isinstance(labels, tuple):
                labels = (labels,)
            row = dict(zip(keys, labels, strict=True))
            width = group.upper.to_numpy() - group.lower.to_numpy()
            width_scale = float(width.max())
            mean_width = (
                width_scale * float(np.mean(width / width_scale))
                if width_scale
                else 0.0
            )
            row.update(
                {
                    "n_observations": len(group),
                    "coverage": float(
                        (
                            (group.actual >= group.lower)
                            & (group.actual <= group.upper)
                        ).mean()
                    ),
                    "mean_width": mean_width,
                    "below_rate": float((group.actual < group.lower).mean()),
                    "above_rate": float((group.actual > group.upper).mean()),
                    "nominal_coverage": (
                        float(group.nominal_coverage.iloc[0])
                        if "nominal_coverage" in group
                        else None
                    ),
                }
            )
            rows.append(row)
        return rows

    return {
        "scope": "caller_labeled",
        "overall": records(["model"]),
        "by_segment": records(["model", "segment"]) if "segment" in frame else [],
        "definition": "Inclusive empirical coverage; width=upper-lower in demand units; below/above are actual values outside bounds. Retrospective estimates, not future coverage guarantees.",
    }
