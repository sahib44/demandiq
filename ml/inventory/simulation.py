"""Chronological, lost-sales policy comparisons from frozen one-week forecasts.

These outcomes are simulated estimates under supplied assumptions. Decisions
after week t use only the already-issued forecast for t+1. An order placed after
t arrives before demand at t+L+1; no order is placed after the final week.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from ml.inventory.planning import (
    MAX_UNITS,
    InventoryParameters,
    InventoryState,
    constrain_order_quantity,
    recommend_inventory,
    validate_nonnegative,
    validate_units,
)

POLICIES = (
    "previous_demand",
    "moving_average_4",
    "fixed_reorder_point",
    "ml_safety_stock",
    "moving_average_safety_stock",
)
_ORDER_COLUMNS = (
    "policy",
    "stock_code",
    "order_id",
    "placed_week",
    "due_week",
    "quantity",
    "is_initial",
    "received_by_horizon",
    "purchase_cost",
    "order_cost",
)


def _week(value: Any, name: str) -> pd.Timestamp:
    if isinstance(value, Real | bool | np.bool_):
        raise ValueError(f"{name} must contain naive Monday dates, not numbers.")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must contain valid naive Monday dates.") from exc
    if (
        pd.isna(result)
        or result.tzinfo is not None
        or result.dayofweek != 0
        or result != result.normalize()
    ):
        raise ValueError(f"{name} must be Monday at midnight without a timezone.")
    return result


@dataclass(frozen=True, slots=True)
class ScheduledArrival:
    """An already-paid initial purchase order with an explicit receipt week."""

    week: pd.Timestamp
    quantity: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "week", _week(self.week, "ScheduledArrival.week"))
        object.__setattr__(
            self,
            "quantity",
            validate_units(self.quantity, "ScheduledArrival.quantity", positive=True),
        )


@dataclass(frozen=True, slots=True)
class ProductSimulationInput:
    """Pre-test inputs shared unchanged by every policy for one product."""

    parameters: InventoryParameters
    initial_on_hand: int
    fixed_forecast: float
    fixed_error_std: float
    error_multipliers: dict[str, float]
    initial_orders: tuple[ScheduledArrival, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, InventoryParameters):
            raise ValueError("parameters must be validated InventoryParameters.")
        object.__setattr__(
            self,
            "initial_on_hand",
            validate_units(self.initial_on_hand, "initial_on_hand"),
        )
        for name in ("fixed_forecast", "fixed_error_std"):
            object.__setattr__(
                self,
                name,
                validate_nonnegative(getattr(self, name), name, quantity=True),
            )
        if not isinstance(self.error_multipliers, dict) or not all(
            isinstance(name, str) and bool(name.strip())
            for name in self.error_multipliers
        ):
            raise ValueError(
                "error_multipliers must map method names to nonnegative magnitudes."
            )
        object.__setattr__(
            self,
            "error_multipliers",
            {
                name: validate_nonnegative(value, f"error_multipliers.{name}")
                for name, value in sorted(self.error_multipliers.items())
            },
        )
        if not isinstance(self.initial_orders, tuple) or not all(
            isinstance(order, ScheduledArrival) for order in self.initial_orders
        ):
            raise ValueError(
                "initial_orders must be a tuple of ScheduledArrival entries."
            )
        initial_orders = tuple(
            sorted(self.initial_orders, key=lambda order: (order.week, order.quantity))
        )
        object.__setattr__(self, "initial_orders", initial_orders)
        reserved = self.initial_on_hand + sum(
            order.quantity for order in initial_orders
        )
        if reserved > MAX_UNITS:
            raise ValueError(
                "Initial on-hand plus all outstanding orders exceeds MAX_UNITS."
            )
        capacity = self.parameters.max_inventory_capacity
        if capacity is not None and reserved > capacity:
            raise ValueError(
                "Initial on-hand plus all outstanding orders exceeds capacity."
            )


@dataclass(frozen=True)
class SimulationResult:
    records: pd.DataFrame
    orders: pd.DataFrame
    summary: dict[str, Any]
    recommendations: pd.DataFrame


def _table(frame: pd.DataFrame, required: set[str], name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{name} must be a nonempty DataFrame.")
    if isinstance(frame.columns, pd.MultiIndex) or frame.columns.has_duplicates:
        raise ValueError(f"{name} must have unique flat column names.")
    if not required.issubset(frame.columns):
        raise ValueError(
            f"{name} is missing required columns: {sorted(required - set(frame.columns))}."
        )
    # In particular, forecasts.actual is not read or validated.
    result = frame.loc[:, sorted(required)].copy()
    if not result.stock_code.map(
        lambda value: isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
    ).all():
        raise ValueError(
            f"{name}.stock_code must contain normalized string identifiers."
        )
    result["week"] = result.week.map(lambda value: _week(value, f"{name}.week"))
    return result


def _actual_units(value: Any) -> int:
    number = validate_nonnegative(value, "demand.actual", quantity=True)
    if not number.is_integer():
        raise ValueError("demand.actual must contain whole units.")
    return int(number)


def _inputs(
    demand: pd.DataFrame,
    forecasts: pd.DataFrame,
    product_inputs: dict[str, ProductSimulationInput],
    selected_model: str,
) -> tuple[
    pd.DataFrame, pd.DataFrame, list[pd.Timestamp], dict[str, ProductSimulationInput]
]:
    if not isinstance(selected_model, str) or selected_model not in {
        "ridge",
        "random_forest",
        "xgboost",
    }:
        raise ValueError("selected_model must identify a supported frozen ML family.")
    actual = _table(demand, {"stock_code", "week", "actual"}, "demand")
    if actual.duplicated(["stock_code", "week"]).any():
        raise ValueError("demand contains duplicate product-week rows.")
    actual["actual"] = actual.actual.map(_actual_units).astype("int64")
    actual = actual.sort_values(["stock_code", "week"], kind="stable").reset_index(
        drop=True
    )
    weeks = sorted(actual.week.unique())
    weeks = [pd.Timestamp(value) for value in weeks]
    if weeks != list(pd.date_range(weeks[0], weeks[-1], freq="W-MON")):
        raise ValueError("Demand weeks must be continuous with no gaps.")
    for _, product in actual.groupby("stock_code", sort=True, observed=True):
        if product.week.tolist() != weeks:
            raise ValueError(
                "Every product must cover the same continuous demand weeks."
            )
    codes = set(actual.stock_code)
    if (
        not isinstance(product_inputs, dict)
        or set(product_inputs) != codes
        or not all(
            isinstance(value, ProductSimulationInput)
            for value in product_inputs.values()
        )
    ):
        raise ValueError(
            "product_inputs must provide exactly one ProductSimulationInput per demand product."
        )
    inputs = {}
    for code, item in sorted(product_inputs.items()):
        # Snapshot/revalidate nested dictionaries before starting any policy.
        item = ProductSimulationInput(
            parameters=item.parameters,
            initial_on_hand=item.initial_on_hand,
            fixed_forecast=item.fixed_forecast,
            fixed_error_std=item.fixed_error_std,
            error_multipliers=dict(item.error_multipliers),
            initial_orders=item.initial_orders,
        )
        if any(order.week < weeks[0] for order in item.initial_orders):
            raise ValueError(
                "Initial orders cannot arrive before the first simulated week."
            )
        if not {selected_model, "moving_average_4"}.issubset(item.error_multipliers):
            raise ValueError(
                "error_multipliers must cover selected_model and moving_average_4."
            )
        inputs[code] = item
    predicted = _table(
        forecasts, {"stock_code", "week", "model", "prediction", "scale"}, "forecasts"
    )
    if not predicted.model.map(
        lambda value: isinstance(value, str) and bool(value.strip())
    ).all():
        raise ValueError("forecasts.model must contain nonempty model identifiers.")
    if predicted.duplicated(["stock_code", "week", "model"]).any():
        raise ValueError("forecasts contains duplicate product-week-model rows.")
    for column in ("prediction", "scale"):
        predicted[column] = predicted[column].map(
            lambda value, name=column: validate_nonnegative(
                value, f"forecasts.{name}", quantity=True
            )
        )
    if not {selected_model, "naive", "moving_average_4"}.issubset(set(predicted.model)):
        raise ValueError(
            "Forecasts must include naive, moving_average_4 and selected_model."
        )
    expected = set(actual[["stock_code", "week"]].itertuples(index=False, name=None))
    for _, model_rows in predicted.groupby("model", sort=True, observed=True):
        observed = set(
            model_rows[["stock_code", "week"]].itertuples(index=False, name=None)
        )
        if observed != expected:
            raise ValueError(
                "Every forecast method must cover exactly the demand product-week grid."
            )
    predicted = predicted.sort_values(
        ["stock_code", "week", "model"], kind="stable"
    ).reset_index(drop=True)
    return actual, predicted, weeks, inputs


def _amount(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} exceeds the supported finite monetary range.")
    return float(value)


def _sum(values, name: str) -> float:
    try:
        return _amount(math.fsum(values), name)
    except OverflowError as exc:
        raise ValueError(
            f"{name} exceeds the supported finite monetary range."
        ) from exc


def _decision(
    policy: str,
    code: str,
    week: pd.Timestamp,
    next_week: pd.Timestamp | None,
    review_due: bool,
    state: InventoryState,
    item: ProductSimulationInput,
    lookup: dict[tuple[str, pd.Timestamp, str], tuple[float, float]],
    selected_model: str,
    observed_demand: int,
) -> dict[str, Any]:
    row = {
        "policy": policy,
        "stock_code": code,
        "week": week,
        "forecast_week": next_week if next_week is not None else pd.NaT,
        "review_due": review_due,
        "inventory_position": state.on_hand + state.on_order,
        "weekly_forecast": None,
        "error_std": None,
        "lead_time_demand": None,
        "safety_stock": None,
        "target_safety_stock": None,
        "reorder_point": None,
        "target_inventory_position": None,
        "requested_quantity": 0.0,
        "recommended_order_quantity": 0,
        "capacity_available": None,
        "service_level_factor": None,
        "forecast_model": None,
        "horizon_assumption": "No order decision at this boundary.",
    }
    if next_week is None:
        return {**row, "reasons": ("final_week_no_order",)}
    if not review_due:
        return {**row, "reasons": ("outside_review_period",)}
    parameters = item.parameters
    if policy == "fixed_reorder_point":
        result = recommend_inventory(
            item.fixed_forecast, item.fixed_error_std, state, parameters, fixed=True
        )
        return {**row, **asdict(result), "forecast_model": "pretest_fixed"}
    method = (
        selected_model
        if policy == "ml_safety_stock"
        else ("naive" if policy == "previous_demand" else "moving_average_4")
    )
    # The repeat-last policy uses the now-observed completed week's demand.
    # Other methods consult exactly one forecast issued for the next origin.
    prediction, scale = (
        (float(observed_demand), 0.0)
        if policy == "previous_demand"
        else lookup[(code, next_week, method)]
    )
    if policy in {"previous_demand", "moving_average_4"}:
        requested = validate_nonnegative(
            prediction * parameters.review_period_weeks,
            "direct_repeat_requested_quantity",
            quantity=True,
        )
        quantity, reasons = constrain_order_quantity(requested, state, parameters)
        return {
            **row,
            "weekly_forecast": prediction,
            "forecast_model": method,
            "requested_quantity": requested,
            "recommended_order_quantity": quantity,
            "reasons": ("direct_repeat_review_period_demand", *reasons),
            "horizon_assumption": (
                "Repeat the just-completed observed demand over R review weeks; no inventory-position correction or safety stock."
                if policy == "previous_demand"
                else "Flat carry-forward of the one available next-week forecast over R review weeks; no inventory-position correction or safety stock."
            ),
        }
    sigma = validate_nonnegative(
        item.error_multipliers[method] * max(scale, 10.0),
        "calibrated_error_std",
        quantity=True,
    )
    result = recommend_inventory(prediction, sigma, state, parameters)
    return {**row, **asdict(result), "forecast_model": method}


def _product_summary(
    records: pd.DataFrame, item: ProductSimulationInput, policy: str, code: str
) -> dict[str, Any]:
    parameters = item.parameters
    initial_units = item.initial_on_hand + sum(
        order.quantity for order in item.initial_orders
    )
    ending = int(records.ending_inventory.iloc[-1])
    outstanding = int(records.outstanding_units.iloc[-1])
    initial_assets = _amount(
        initial_units * parameters.unit_purchase_cost, "initial_inventory_asset_value"
    )
    terminal_assets = _amount(
        (ending + outstanding) * parameters.unit_purchase_cost,
        "terminal_inventory_asset_value",
    )
    demand = sum(int(value) for value in records.actual)
    fulfilled = sum(int(value) for value in records.fulfilled_units)
    lost = sum(int(value) for value in records.lost_units)
    events = int(records.stockout_event.sum())
    row = {
        "policy": policy,
        "stock_code": code,
        "weeks": len(records),
        "total_demand": demand,
        "fulfilled_units": fulfilled,
        "lost_units": lost,
        "fill_rate": fulfilled / demand if demand else 1.0,
        "service_level": 1 - events / len(records),
        "stockout_events": events,
        "stockout_frequency": events / len(records),
        "average_inventory": _sum(records.ending_inventory, "average_inventory")
        / len(records),
        "ending_inventory": ending,
        "outstanding_units": outstanding,
        "initial_on_hand": item.initial_on_hand,
        "initial_on_order": initial_units - item.initial_on_hand,
        "received_units": sum(int(value) for value in records.received_units),
        "ordered_units": sum(int(value) for value in records.ordered_units),
        "initial_inventory_asset_value": initial_assets,
        "terminal_inventory_asset_value": terminal_assets,
    }
    for column in (
        "purchase_cost",
        "holding_cost",
        "stockout_cost",
        "order_cost",
        "revenue",
        "lost_revenue",
        "estimated_lost_margin",
        "gross_cash_cost",
    ):
        row[column] = _sum(records[column], column)
    row["net_inventory_cost"] = _sum(
        [row["gross_cash_cost"], initial_assets, -terminal_assets], "net_inventory_cost"
    )
    row["cost_of_goods_sold"] = _amount(
        fulfilled * parameters.unit_purchase_cost, "cost_of_goods_sold"
    )
    reconciled = _sum(
        [
            row["cost_of_goods_sold"],
            row["holding_cost"],
            row["stockout_cost"],
            row["order_cost"],
        ],
        "reconciled_cost",
    )
    if not math.isclose(
        row["net_inventory_cost"], reconciled, rel_tol=1e-10, abs_tol=1e-8
    ):
        raise ValueError(
            "Terminal-adjusted costs failed monetary conservation; reduce numeric magnitudes."
        )
    # The equivalent consumed-goods form avoids tiny negative costs from
    # cancelling nearly equal floating-point initial/terminal asset values.
    row["net_inventory_cost"] = reconciled
    if initial_units + row["ordered_units"] != fulfilled + ending + outstanding:
        raise RuntimeError("Simulated stock and outstanding-order conservation failed.")
    return row


def _summary(
    products: list[dict[str, Any]], weeks: int, selected_model: str
) -> dict[str, Any]:
    policies = []
    sums = (
        "total_demand",
        "fulfilled_units",
        "lost_units",
        "stockout_events",
        "average_inventory",
        "ending_inventory",
        "outstanding_units",
        "initial_on_hand",
        "initial_on_order",
        "received_units",
        "ordered_units",
        "purchase_cost",
        "holding_cost",
        "stockout_cost",
        "order_cost",
        "gross_cash_cost",
        "initial_inventory_asset_value",
        "terminal_inventory_asset_value",
        "net_inventory_cost",
        "cost_of_goods_sold",
        "revenue",
        "lost_revenue",
        "estimated_lost_margin",
    )
    integer_fields = {
        "total_demand",
        "fulfilled_units",
        "lost_units",
        "stockout_events",
        "ending_inventory",
        "outstanding_units",
        "initial_on_hand",
        "initial_on_order",
        "received_units",
        "ordered_units",
    }
    for policy in POLICIES:
        rows = [row for row in products if row["policy"] == policy]
        item = {"policy": policy, "weeks": weeks, "product_count": len(rows)}
        for column in sums:
            item[column] = (
                sum(row[column] for row in rows)
                if column in integer_fields
                else _sum((row[column] for row in rows), column)
            )
        item["fill_rate"] = (
            item["fulfilled_units"] / item["total_demand"]
            if item["total_demand"]
            else 1.0
        )
        item["stockout_frequency"] = item["stockout_events"] / (weeks * len(rows))
        item["service_level"] = 1 - item["stockout_frequency"]
        policies.append(item)
    ml_cost = next(
        row["net_inventory_cost"]
        for row in policies
        if row["policy"] == "ml_safety_stock"
    )
    comparisons = []
    for row in policies:
        if row["policy"] == "ml_safety_stock":
            continue
        baseline_cost = row["net_inventory_cost"]
        savings = _sum([baseline_cost, -ml_cost], "simulated_savings")
        comparisons.append(
            {
                "policy": "ml_safety_stock",
                "baseline_policy": row["policy"],
                "baseline_net_inventory_cost": baseline_cost,
                "ml_net_inventory_cost": ml_cost,
                "simulated_savings": savings,
                "simulated_savings_percent": (
                    _amount(
                        100 * (savings / baseline_cost), "simulated_savings_percent"
                    )
                    if baseline_cost
                    else None
                ),
            }
        )
    return {
        "scope": "retrospective_assumption_driven_simulation",
        "selected_model": selected_model,
        "policies": policies,
        "products": products,
        "comparisons": comparisons,
        "accounting": "net_inventory_cost = gross_cash_cost + initial on-hand/pipeline asset value - terminal on-hand/pipeline asset value; initial pipeline is prepaid; lost margin is reported separately.",
        "timing": "Receive before demand; review after demand at indices 0,R,2R; orders arrive at t+L+1; no final-week orders.",
        "forecast_information": "Only the next-origin one-week forecast is consulted at each decision; longer horizons use explicit flat carry-forward.",
        "service_definition": "Fraction of product-weeks without lost units; fill rate is fulfilled / demand, defined as one for zero demand.",
        "savings_label": "Signed simulated estimates under stated assumptions; no realized company savings.",
    }


def run_simulation(
    demand: pd.DataFrame,
    forecasts: pd.DataFrame,
    product_inputs: dict[str, ProductSimulationInput],
    *,
    selected_model: str,
) -> SimulationResult:
    """Compare five policies with identical initial stock, economics and demand."""
    demand, forecasts, weeks, inputs = _inputs(
        demand, forecasts, product_inputs, selected_model
    )
    lookup = {
        (row.stock_code, pd.Timestamp(row.week), row.model): (
            float(row.prediction),
            float(row.scale),
        )
        for row in forecasts.itertuples(index=False)
    }
    records, orders, recommendations, product_summaries = [], [], [], []
    for policy in POLICIES:
        for code, item in inputs.items():
            parameters = item.parameters
            on_hand = item.initial_on_hand
            pending = []
            for index, initial in enumerate(item.initial_orders, start=1):
                order = {
                    "policy": policy,
                    "stock_code": code,
                    "order_id": f"{policy}:{code}:initial:{index}",
                    "placed_week": pd.NaT,
                    "due_week": initial.week,
                    "quantity": initial.quantity,
                    "is_initial": True,
                    "received_by_horizon": initial.week <= weeks[-1],
                    "purchase_cost": 0.0,
                    "order_cost": 0.0,
                }
                orders.append(order)
                pending.append(order)
            actuals = demand.loc[demand.stock_code.eq(code), "actual"].tolist()
            product_records = []
            for index, (week, actual) in enumerate(zip(weeks, actuals, strict=True)):
                opening = on_hand
                opening_pipeline = sum(order["quantity"] for order in pending)
                received = sum(
                    order["quantity"] for order in pending if order["due_week"] == week
                )
                pending = [order for order in pending if order["due_week"] != week]
                available = opening + received
                fulfilled = min(available, actual)
                lost = actual - fulfilled
                on_hand = available - fulfilled
                state = InventoryState(
                    on_hand, sum(order["quantity"] for order in pending)
                )
                next_week = weeks[index + 1] if index + 1 < len(weeks) else None
                review_due = (
                    index % parameters.review_period_weeks == 0
                    and next_week is not None
                )
                decision = _decision(
                    policy,
                    code,
                    week,
                    next_week,
                    review_due,
                    state,
                    item,
                    lookup,
                    selected_model,
                    actual,
                )
                recommendations.append(decision)
                ordered = decision["recommended_order_quantity"]
                purchase_cost = _amount(
                    ordered * parameters.unit_purchase_cost, "purchase_cost"
                )
                order_cost = parameters.order_cost if ordered else 0.0
                if ordered:
                    try:
                        due = week + pd.Timedelta(weeks=parameters.lead_time_weeks + 1)
                    except (OverflowError, ValueError) as exc:
                        raise ValueError(
                            "Supplier lead time puts the receipt outside the supported date range."
                        ) from exc
                    order = {
                        "policy": policy,
                        "stock_code": code,
                        "order_id": f"{policy}:{code}:week:{index}",
                        "placed_week": week,
                        "due_week": due,
                        "quantity": ordered,
                        "is_initial": False,
                        "received_by_horizon": due <= weeks[-1],
                        "purchase_cost": purchase_cost,
                        "order_cost": order_cost,
                    }
                    orders.append(order)
                    pending.append(order)
                outstanding = sum(order["quantity"] for order in pending)
                InventoryState(on_hand, outstanding)
                if (
                    parameters.max_inventory_capacity is not None
                    and on_hand + outstanding > parameters.max_inventory_capacity
                ):
                    raise RuntimeError(
                        "Simulated inventory reservation exceeded capacity."
                    )
                if (
                    opening + received != fulfilled + on_hand
                    or opening_pipeline - received + ordered != outstanding
                ):
                    raise RuntimeError("Weekly stock/order conservation failed.")
                holding = _amount(
                    on_hand * parameters.holding_cost_per_unit_week, "holding_cost"
                )
                stockout = _amount(
                    lost * parameters.stockout_penalty_per_unit, "stockout_cost"
                )
                row = {
                    "policy": policy,
                    "stock_code": code,
                    "week": week,
                    "actual": actual,
                    "opening_inventory": opening,
                    "opening_on_order": opening_pipeline,
                    "received_units": received,
                    "available_inventory": available,
                    "fulfilled_units": fulfilled,
                    "lost_units": lost,
                    "stockout_event": lost > 0,
                    "ending_inventory": on_hand,
                    "ordered_units": ordered,
                    "outstanding_units": outstanding,
                    "purchase_cost": purchase_cost,
                    "holding_cost": holding,
                    "stockout_cost": stockout,
                    "order_cost": order_cost,
                    "gross_cash_cost": _sum(
                        [purchase_cost, holding, stockout, order_cost],
                        "gross_cash_cost",
                    ),
                    "revenue": _amount(
                        fulfilled * parameters.unit_selling_price, "revenue"
                    ),
                    "lost_revenue": _amount(
                        lost * parameters.unit_selling_price, "lost_revenue"
                    ),
                    "estimated_lost_margin": _amount(
                        lost
                        * max(
                            parameters.unit_selling_price
                            - parameters.unit_purchase_cost,
                            0.0,
                        ),
                        "estimated_lost_margin",
                    ),
                }
                records.append(row)
                product_records.append(row)
            product_summaries.append(
                _product_summary(pd.DataFrame(product_records), item, policy, code)
            )
    return SimulationResult(
        records=pd.DataFrame(records),
        orders=pd.DataFrame(orders, columns=_ORDER_COLUMNS),
        summary=_summary(product_summaries, len(weeks), selected_model),
        recommendations=pd.DataFrame(recommendations),
    )
