"""Pooled demand regressors with preprocessing fitted on supplied training only.

The caller owns chronological folds and feature availability. This module never
splits rows, observes validation targets, or selects a winning candidate. Numeric
missing values are imputed from training medians, with missingness indicators;
all-missing training columns remain represented. Only Ridge standardizes numeric
columns. Product identifiers use training-only one-hot categories.

Joblib artifacts contain Python pickle data. Load only artifacts from a trusted
local training run, with an independently retained expected SHA-256. A matching
digest detects corruption; it cannot make an untrusted pickle safe to execute.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from numbers import Real
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.utils.validation import check_is_fitted
from xgboost import XGBRegressor

from ml.features.weekly import FEATURE_COLUMNS

_FAMILIES = {"ridge", "random_forest", "xgboost"}


@dataclass(frozen=True)
class FittedDemandModel:
    """Fitted transform/regressor pipeline and its auditable training boundary."""

    pipeline: Pipeline
    candidate: dict[str, Any]
    feature_names: tuple[str, ...]
    training_row_count: int
    training_end: pd.Timestamp


def model_candidates(seed: int = 42) -> list[dict[str, Any]]:
    """Return the predeclared two-candidate grid for each of three model families."""
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer from 0 through 2**32 - 1.")
    candidates = [
        {
            "id": f"ridge_alpha_{alpha}",
            "family": "ridge",
            "parameters": {"alpha": float(alpha), "random_state": seed},
        }
        for alpha in (1, 100)
    ]
    candidates += [
        {
            "id": f"random_forest_depth_{depth if depth is not None else 'none'}",
            "family": "random_forest",
            "parameters": {
                "n_estimators": 100,
                "max_depth": depth,
                "min_samples_leaf": 2,
                "n_jobs": 1,
                "random_state": seed,
            },
        }
        for depth in (8, None)
    ]
    candidates += [
        {
            "id": f"xgboost_depth_{depth}",
            "family": "xgboost",
            "parameters": {
                "n_estimators": 150,
                "max_depth": depth,
                "learning_rate": 0.05,
                "objective": "reg:squarederror",
                "tree_method": "hist",
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "n_jobs": 1,
                "random_state": seed,
                "importance_type": "gain",
            },
        }
        for depth in (2, 4)
    ]
    return candidates


def _candidate(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"id", "family", "parameters"}:
        raise ValueError("candidate must contain exactly id, family and parameters.")
    if not isinstance(value["id"], str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,95}", value["id"]
    ):
        raise ValueError("candidate.id must be a safe lowercase identifier.")
    if (
        not isinstance(value["family"], str)
        or value["family"] not in _FAMILIES
        or not isinstance(value["parameters"], dict)
    ):
        raise ValueError(
            "candidate must specify a supported family and parameter object."
        )
    try:
        json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "candidate parameters must contain finite JSON values."
        ) from exc
    return deepcopy(value)


def _feature_names(value: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) < 2
        or any(not isinstance(name, str) for name in value)
        or len(set(value)) != len(value)
        or "stock_code" not in value
    ):
        raise ValueError(
            "feature_names must be a unique tuple including stock_code and numeric features."
        )
    for name in value:
        if name not in FEATURE_COLUMNS and not re.fullmatch(
            r"seasonal_[a-z][a-z0-9_]{0,47}", name
        ):
            raise ValueError(f"Unsupported or unsafe feature name: {name!r}.")
    return value


def _numeric(values: pd.Series, name: str, *, allow_missing: bool) -> np.ndarray:
    def valid(value: Any) -> bool:
        if value is None or value is pd.NA:
            return allow_missing
        return isinstance(value, Real) and not isinstance(value, bool | np.bool_)

    if not values.map(valid).all():
        raise ValueError(
            f"{name} must contain numeric values{' or NaN' if allow_missing else ''}."
        )
    try:
        result = values.to_numpy(dtype="float64", na_value=np.nan)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} exceeds the supported numeric range.") from exc
    if np.isinf(result).any() or (not allow_missing and np.isnan(result).any()):
        raise ValueError(
            f"{name} must contain finite values{' or NaN' if allow_missing else ''}."
        )
    return result


def _frame(
    frame: pd.DataFrame, feature_names: tuple[str, ...], *, training: bool
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("Model input must be a nonempty pandas DataFrame.")
    if isinstance(frame.columns, pd.MultiIndex) or frame.columns.has_duplicates:
        raise ValueError("Model input must have unique flat column names.")
    required = {"week", *feature_names} | ({"gross_units"} if training else set())
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"Model input is missing required columns: {', '.join(missing)}."
        )
    # Selecting first ensures extra actual/current-period columns cannot enter X.
    result = frame.loc[
        :, ["week", *feature_names, *(["gross_units"] if training else [])]
    ].copy()
    if not result.stock_code.map(
        lambda value: isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
    ).all():
        raise ValueError(
            "stock_code must contain normalized nonempty string identifiers."
        )
    if pd.api.types.is_numeric_dtype(result.week.dtype):
        raise ValueError(
            "week must contain naive Monday dates, not numeric timestamps."
        )
    try:
        weeks = pd.to_datetime(result.week, errors="raise")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("week must contain valid naive Monday dates.") from exc
    if not pd.api.types.is_datetime64_any_dtype(weeks.dtype) or isinstance(
        weeks.dtype, pd.DatetimeTZDtype
    ):
        raise ValueError("week must contain timezone-naive Monday dates.")
    if (
        weeks.isna().any()
        or not (weeks.dt.dayofweek.eq(0) & weeks.eq(weeks.dt.normalize())).all()
    ):
        raise ValueError("week must be Monday at midnight without missing dates.")
    result["week"] = weeks
    if result.duplicated(["stock_code", "week"]).any():
        raise ValueError("Model input contains duplicate product-week rows.")
    for name in feature_names:
        if name != "stock_code":
            result[name] = _numeric(result[name], name, allow_missing=True)
    if training:
        result["gross_units"] = _numeric(
            result.gross_units, "gross_units", allow_missing=False
        )
        if result.gross_units.lt(0).any():
            raise ValueError("gross_units must be nonnegative.")
        result = result.sort_values(["week", "stock_code"], kind="stable").reset_index(
            drop=True
        )
    return result


def fit_model(
    training_features: pd.DataFrame,
    candidate: dict[str, Any],
    *,
    feature_names: tuple[str, ...],
) -> FittedDemandModel:
    """Fit one candidate on all supplied training rows, without a validation split."""
    names = _feature_names(feature_names)
    specification = _candidate(candidate)
    frame = _frame(training_features, names, training=True)
    numeric_names = [name for name in names if name != "stock_code"]
    numeric_steps = [
        (
            "imputer",
            SimpleImputer(
                strategy="median", add_indicator=True, keep_empty_features=True
            ),
        )
    ]
    if specification["family"] == "ridge":
        numeric_steps.append(("scaler", StandardScaler()))
    preprocessor = ColumnTransformer(
        [
            ("numeric", Pipeline(numeric_steps), numeric_names),
            (
                "product",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ["stock_code"],
            ),
        ],
        remainder="drop",
        sparse_threshold=0.0,
    )
    constructors = {
        "ridge": Ridge,
        "random_forest": RandomForestRegressor,
        "xgboost": XGBRegressor,
    }
    try:
        regressor = constructors[specification["family"]](**specification["parameters"])
    except TypeError as exc:
        raise ValueError(
            "candidate parameters are not supported by its model family."
        ) from exc
    pipeline = Pipeline([("preprocessor", preprocessor), ("regressor", regressor)])
    pipeline.fit(frame.loc[:, list(names)], frame.gross_units.to_numpy(dtype="float64"))
    return FittedDemandModel(
        pipeline=pipeline,
        candidate=specification,
        feature_names=names,
        training_row_count=len(frame),
        training_end=frame.week.max(),
    )


def _fitted(model: FittedDemandModel) -> None:
    if not isinstance(model, FittedDemandModel) or not isinstance(
        model.pipeline, Pipeline
    ):
        raise ValueError("Expected a FittedDemandModel with a fitted sklearn pipeline.")
    _feature_names(model.feature_names)
    _candidate(model.candidate)
    constructors = {
        "ridge": Ridge,
        "random_forest": RandomForestRegressor,
        "xgboost": XGBRegressor,
    }
    if not isinstance(
        model.pipeline.named_steps.get("preprocessor"), ColumnTransformer
    ) or not isinstance(
        model.pipeline.named_steps.get("regressor"),
        constructors[model.candidate["family"]],
    ):
        raise ValueError("Model pipeline family contradicts its metadata.")
    if type(model.training_row_count) is not int or model.training_row_count < 1:
        raise ValueError("Model training row count must be positive.")
    if (
        not isinstance(model.training_end, pd.Timestamp)
        or pd.isna(model.training_end)
        or model.training_end.tzinfo is not None
        or model.training_end.dayofweek != 0
        or model.training_end != model.training_end.normalize()
    ):
        raise ValueError("Model training boundary must be a naive Monday at midnight.")
    check_is_fitted(model.pipeline)
    if tuple(model.pipeline.feature_names_in_) != model.feature_names:
        raise ValueError("Model pipeline features contradict its metadata.")


def predict_model(model: FittedDemandModel, features: pd.DataFrame) -> np.ndarray:
    """Predict strictly after training; preserve row order and clip negatives to zero.

    Clipping is a declared nonnegative-demand postprocessing rule, not a fitted
    transformation. Extra columns (including held-out actuals) are ignored.
    """
    _fitted(model)
    frame = _frame(features, model.feature_names, training=False)
    if frame.week.le(model.training_end).any():
        raise ValueError(
            "Prediction weeks must be strictly after the model training_end."
        )
    result = np.asarray(
        model.pipeline.predict(frame.loc[:, list(model.feature_names)]), dtype="float64"
    )
    if result.shape != (len(frame),) or not np.isfinite(result).all():
        raise ValueError("Model generated nonfinite or misaligned predictions.")
    return np.maximum(result, 0.0)


def feature_importance(model: FittedDemandModel) -> list[dict[str, Any]]:
    """Return native importances; methods differ and are not causal effects.

    Ridge uses absolute coefficients with numeric features standardized and
    product dummy variables unscaled. Tree methods use normalized impurity
    decrease (forest) or normalized average split gain (XGBoost). Missingness
    indicators and product dummies retain their individual transformed names.
    """
    _fitted(model)
    names = model.pipeline.named_steps["preprocessor"].get_feature_names_out()
    regressor = model.pipeline.named_steps["regressor"]
    if model.candidate["family"] == "ridge":
        values = np.abs(regressor.coef_)
        method = "absolute_coefficient_standardized_numeric"
    else:
        values = regressor.feature_importances_
        method = (
            "normalized_impurity_decrease"
            if model.candidate["family"] == "random_forest"
            else "normalized_average_gain"
        )
    values = np.asarray(values, dtype="float64")
    if (
        values.shape != (len(names),)
        or not np.isfinite(values).all()
        or (values < 0).any()
    ):
        raise ValueError("Native feature importance is nonfinite or misaligned.")
    rows = [
        {"feature": str(name), "importance": float(value), "method": method}
        for name, value in zip(names, values, strict=True)
    ]
    return sorted(rows, key=lambda row: (-row["importance"], row["feature"]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_model(model: FittedDemandModel, path: Path) -> str:
    """Atomically save a trusted local joblib artifact (compression level three)."""
    _fitted(model)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".model-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        joblib.dump(model, temporary, compress=3)
        digest = _sha256(temporary)
        os.replace(temporary, path)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def load_model(path: Path, expected_sha256: str) -> FittedDemandModel:
    """Verify the expected digest before unpickling a trusted local artifact."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest.")
    path = Path(path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("Model artifact is missing or unreadable.") from exc
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Model artifact SHA-256 does not match the expected digest.")
    # Load exactly the verified bytes, even if another process replaces the path.
    model = joblib.load(BytesIO(payload))
    _fitted(model)
    return model
