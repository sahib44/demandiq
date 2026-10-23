"""Continuous weekly merchandise movements and training-only product ranking.

The forecasting target is gross positive purchase units. Returns and invoice
cancellations are separate accounting signals; neither proves a matched physical
return. Revenue is gross purchase revenue, not a net revenue or margin estimate.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import date, datetime
from numbers import Integral, Real
from typing import Any, Final

import numpy as np
import pandas as pd

from ml.data.cleaning import INT64_MAX, INT64_MIN, PRODUCT_ID_MAX_LENGTH

_SOURCE_COLUMNS: Final = (
    "source_row",
    "invoice_no",
    "stock_code",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_key",
)
_WEEK_STRING = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?)?$"
)
WEEKLY_DTYPES: Final = {
    "stock_code": "string",
    "week": "datetime64[ns]",
    "gross_units": "int64",
    "returned_units": "int64",
    "cancellation_units": "int64",
    "net_units": "int64",
    "revenue": "float64",
    "transactions": "int64",
    "unique_customers": "int64",
    "average_price": "float64",
}
SELECTION_DTYPES: Final = {
    "stock_code": "string",
    "training_units": "int64",
    "active_training_weeks": "int64",
}


class WeeklyDataError(ValueError):
    """Weekly input violates a cleaned-data or chronological-panel invariant."""


def _empty(dtypes: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {name: pd.Series(dtype=dtype) for name, dtype in dtypes.items()}
    )


def _week_boundary(value: Any, name: str) -> pd.Timestamp:
    if not isinstance(value, str | date | datetime | np.datetime64):
        raise WeeklyDataError(f"{name} must be a naive Monday at midnight")
    if isinstance(value, str) and not _WEEK_STRING.fullmatch(value):
        raise WeeklyDataError(f"{name} must use a naive ISO date or datetime")
    try:
        boundary = pd.Timestamp(value)
        _ = boundary.value
    except (ValueError, TypeError, OverflowError) as exc:
        raise WeeklyDataError(
            f"{name} is outside the supported datetime range"
        ) from exc
    if (
        pd.isna(boundary)
        or boundary.tzinfo is not None
        or boundary.dayofweek != 0
        or boundary != boundary.normalize()
    ):
        raise WeeklyDataError(f"{name} must be a naive Monday at midnight")
    return boundary


def _columns(frame: pd.DataFrame, required: Sequence[str], name: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise WeeklyDataError(f"{name} must be a pandas DataFrame")
    if isinstance(frame.columns, pd.MultiIndex) or frame.columns.has_duplicates:
        raise WeeklyDataError(f"{name} must have unique flat column names")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise WeeklyDataError(f"{name} is missing required columns: {missing}")


def _valid_stock(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= PRODUCT_ID_MAX_LENGTH
    )


def _integers(values: pd.Series, name: str, *, minimum: int = 0) -> pd.Series:
    """Reject coercion and validate Python-int arithmetic before int64 conversion."""
    if not values.map(
        lambda value: isinstance(value, Integral)
        and not isinstance(value, bool | np.bool_)
        and minimum <= value <= INT64_MAX
    ).all():
        raise WeeklyDataError(f"{name} must contain signed-int64 integers >= {minimum}")
    return values.astype("int64")


def _safe_units(values: pd.Series, name: str) -> pd.Series:
    if not values.map(lambda value: INT64_MIN <= value <= INT64_MAX).all():
        raise WeeklyDataError(f"{name} exceeds the signed-int64 aggregation range")
    return values.astype("int64")


def _dates(values: pd.Series, name: str) -> pd.Series:
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        raise WeeklyDataError(f"{name} must use naive London wall datetimes")
    if not pd.api.types.is_datetime64_any_dtype(values.dtype) or values.isna().any():
        raise WeeklyDataError(f"{name} must contain nonnull native datetimes")
    try:
        return values.astype("datetime64[ns]")
    except (ValueError, TypeError, OverflowError) as exc:
        raise WeeklyDataError(
            f"{name} is outside the supported datetime range"
        ) from exc


def _valid_price(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool | np.bool_):
        return False
    try:
        price = float(value)
    except (ValueError, TypeError, OverflowError):
        return False
    return math.isfinite(price) and price > 0


def _partition(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    _columns(frame, _SOURCE_COLUMNS, name)
    if frame.empty:
        return pd.DataFrame(
            {
                "source_row": pd.Series(dtype="int64"),
                "invoice_no": pd.Series(dtype="string"),
                "stock_code": pd.Series(dtype="string"),
                "quantity": pd.Series(dtype="int64"),
                "invoice_date": pd.Series(dtype="datetime64[ns]"),
                "unit_price": pd.Series(dtype="float64"),
                "customer_key": pd.Series(dtype="string"),
            }
        )
    result = frame.loc[:, list(_SOURCE_COLUMNS)].copy()
    result["source_row"] = _integers(result.source_row, f"{name}.source_row", minimum=1)
    if result.source_row.duplicated().any():
        raise WeeklyDataError(f"{name} contains duplicate source_row identifiers")
    if not result.stock_code.map(_valid_stock).all():
        raise WeeklyDataError(f"{name}.stock_code must contain normalized product IDs")
    result["stock_code"] = result.stock_code.astype("string")
    if not result.invoice_no.map(
        lambda value: isinstance(value, str) and bool(value) and value == value.strip()
    ).all():
        raise WeeklyDataError(f"{name}.invoice_no must contain invoice identifiers")
    cancellations = result.invoice_no.str.upper().str.startswith("C")
    if (cancellations if name != "cancellations" else ~cancellations).any():
        raise WeeklyDataError(
            f"{name} contains inconsistent C-prefixed invoice classes"
        )
    result["quantity"] = _integers(
        result.quantity, f"{name}.quantity", minimum=INT64_MIN
    )
    wrong_sign = result.quantity.le(0) if name == "purchases" else result.quantity.ge(0)
    if wrong_sign.any():
        raise WeeklyDataError(
            f"{name} contains quantities with the wrong movement sign"
        )
    if name != "purchases" and result.quantity.eq(INT64_MIN).any():
        raise WeeklyDataError(
            f"{name} contains an absolute quantity outside the signed-int64 range"
        )
    result["invoice_date"] = _dates(result.invoice_date, f"{name}.invoice_date")
    if not result.unit_price.map(_valid_price).all():
        raise WeeklyDataError(f"{name}.unit_price must contain finite positive prices")
    result["unit_price"] = result.unit_price.astype("float64")
    if not np.isfinite(result.unit_price.to_numpy()).all():
        raise WeeklyDataError(f"{name}.unit_price exceeds the float64 range")
    if not all(
        isinstance(value, str) and bool(value) for value in result.customer_key.dropna()
    ):
        raise WeeklyDataError(f"{name}.customer_key must contain pseudonyms or nulls")
    return result


def _product_list(products: Sequence[str]) -> list[str]:
    if isinstance(products, str | bytes):
        raise WeeklyDataError("products must be a nonempty collection of unique IDs")
    try:
        result = list(products)
    except TypeError as exc:
        raise WeeklyDataError("products must be a collection of unique IDs") from exc
    if not result or not all(_valid_stock(value) for value in result):
        raise WeeklyDataError("products must contain nonempty normalized string IDs")
    if len(set(result)) != len(result):
        raise WeeklyDataError("products contains duplicate product IDs")
    return sorted(result)


def _aggregate_partition(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    units = "gross_units" if name == "purchases" else f"{name[:-1]}_units"
    if name == "returns":
        units = "returned_units"
    data = frame.copy()
    # W-SUN denotes a Monday-start, Sunday-ending calendar week.
    data["week"] = data.invoice_date.dt.to_period("W-SUN").dt.start_time
    quantities = data.quantity.astype(object)
    data[units] = quantities if name == "purchases" else -quantities
    grouped = data.groupby(["stock_code", "week"], sort=True, observed=True)
    result = grouped[units].sum().to_frame()
    result[units] = _safe_units(result[units], units)
    if name == "purchases":
        with np.errstate(over="ignore", invalid="ignore"):
            data["revenue"] = data.quantity.to_numpy(
                dtype="float64"
            ) * data.unit_price.to_numpy(dtype="float64")
        if not np.isfinite(data.revenue.to_numpy()).all():
            raise WeeklyDataError("Purchase revenue exceeds the finite float64 range")
        grouped = data.groupby(["stock_code", "week"], sort=True, observed=True)
        result["revenue"] = grouped.revenue.sum()
        if not np.isfinite(result.revenue.to_numpy()).all():
            raise WeeklyDataError("Weekly revenue exceeds the finite float64 range")
        result["transactions"] = grouped.size()
        result["unique_customers"] = grouped.customer_key.nunique(dropna=True)
    return result


def aggregate_weekly(
    purchases: pd.DataFrame,
    cancellations: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    start_week: Any,
    end_week: Any,
    products: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return a complete product-week grid over inclusive Monday boundaries.

    ``end_week`` includes its entire Monday–Sunday week. The caller must choose
    complete edge weeks from source coverage; this function does not extrapolate
    partial weeks. Without ``products``, use the union of products observed in any
    partition inside the window. Explicit products may be entirely absent, in
    which case their rows are zero-demand weeks. Zero-sales average prices remain
    NaN, because a missing observed selling price is not a zero price.

    Require Phase 1 movement signs/classes, positive finite prices, naive native
    dates and unique source_row IDs across partitions. All arithmetic that may
    exceed int64 is checked using Python integers before conversion. No source
    customer pseudonym or transaction identifier is included in the result.
    """
    start = _week_boundary(start_week, "start_week")
    end = _week_boundary(end_week, "end_week")
    if start > end:
        raise WeeklyDataError("start_week must not be after end_week")
    try:
        exclusive_end = end + pd.Timedelta(weeks=1)
    except (ValueError, OverflowError) as exc:
        raise WeeklyDataError(
            "The complete end week exceeds the datetime range"
        ) from exc
    partitions = {
        "purchases": _partition(purchases, "purchases"),
        "cancellations": _partition(cancellations, "cancellations"),
        "returns": _partition(returns, "returns"),
    }
    source_rows = pd.concat([frame.source_row for frame in partitions.values()])
    if source_rows.duplicated().any():
        raise WeeklyDataError(
            "source_row identifiers overlap across movement partitions"
        )
    for name, frame in partitions.items():
        partitions[name] = frame.loc[
            frame.invoice_date.ge(start) & frame.invoice_date.lt(exclusive_end)
        ].copy()
    codes = (
        _product_list(products)
        if products is not None
        else sorted(
            set().union(*(set(frame.stock_code) for frame in partitions.values()))
        )
    )
    if not codes:
        return _empty(WEEKLY_DTYPES)
    grid = pd.MultiIndex.from_product(
        [pd.Index(codes, dtype="string"), pd.date_range(start, end, freq="W-MON")],
        names=["stock_code", "week"],
    )
    result = pd.DataFrame(index=grid)
    for name, frame in partitions.items():
        selected = frame.loc[frame.stock_code.isin(codes)]
        aggregates = _aggregate_partition(selected, name)
        for column in aggregates.columns:
            result[column] = aggregates[column].reindex(grid, fill_value=0)
    net = (
        result.gross_units.astype(object)
        - result.returned_units.astype(object)
        - result.cancellation_units.astype(object)
    )
    result["net_units"] = _safe_units(net, "net_units")
    result["average_price"] = result.revenue.div(
        result.gross_units.where(result.gross_units.gt(0))
    )
    return result.reset_index().loc[:, list(WEEKLY_DTYPES)].astype(WEEKLY_DTYPES)


def select_top_products(
    panel: pd.DataFrame,
    *,
    train_end: Any,
    top_n: int = 50,
    min_history_weeks: int = 12,
) -> pd.DataFrame:
    """Rank eligible products using gross volume through ``train_end`` only.

    ``train_end`` is an inclusive Monday week label. A product needs at least
    ``min_history_weeks`` continuous training observations and positive total
    gross volume. Zero-demand weeks count as history, but not active weeks.
    Products with no training observations or zero training volume are excluded.
    Rank by descending exact training units, then ascending product ID on ties.
    Future gross quantities do not participate in ranking or eligibility.
    """
    end = _week_boundary(train_end, "train_end")
    for name, value in (("top_n", top_n), ("min_history_weeks", min_history_weeks)):
        if not isinstance(value, Integral) or isinstance(value, bool) or value < 1:
            raise WeeklyDataError(f"{name} must be a positive integer")
    _columns(panel, ("stock_code", "week", "gross_units"), "panel")
    if panel.empty:
        return _empty(SELECTION_DTYPES)
    if not panel.stock_code.map(_valid_stock).all():
        raise WeeklyDataError("panel.stock_code must contain normalized product IDs")
    weeks = _dates(panel.week, "panel.week")
    if weeks.dt.dayofweek.ne(0).any() or weeks.ne(weeks.dt.normalize()).any():
        raise WeeklyDataError("panel.week must contain Monday-midnight week labels")
    if panel.duplicated(["stock_code", "week"]).any():
        raise WeeklyDataError("panel contains duplicate product/week observations")
    training = panel.loc[weeks.le(end), ["stock_code", "week", "gross_units"]].copy()
    if training.empty:
        return _empty(SELECTION_DTYPES)
    training["gross_units"] = _integers(training.gross_units, "training gross_units")
    training["week"] = _dates(training.week, "training week")
    training = training.sort_values(["stock_code", "week"], kind="stable")
    rows: list[dict[str, Any]] = []
    for code, history in training.groupby("stock_code", sort=True, observed=True):
        differences = history.week.diff().dropna()
        if differences.ne(pd.Timedelta(weeks=1)).any() or history.week.iloc[-1] != end:
            raise WeeklyDataError(
                "Training panel contains missing product-week observations"
            )
        if len(history) < min_history_weeks:
            continue
        units = sum(int(value) for value in history.gross_units)
        if units > INT64_MAX:
            raise WeeklyDataError("training_units exceeds the signed-int64 range")
        if units > 0:
            rows.append(
                {
                    "stock_code": code,
                    "training_units": units,
                    "active_training_weeks": int(history.gross_units.gt(0).sum()),
                }
            )
    if not rows:
        return _empty(SELECTION_DTYPES)
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["training_units", "stock_code"], ascending=[False, True], kind="stable"
        )
        .head(top_n)
        .reset_index(drop=True)
        .astype(SELECTION_DTYPES)
    )
