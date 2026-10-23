"""Validated inventory thresholds and feasible orders from one available forecast.

All economic inputs are explicit assumptions. Lead/review demand carries the
single available next-week forecast forward flat; this is not a fitted multiweek
forecast. Recommendations are decision support and never place purchase orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral, Real
from statistics import NormalDist

MAX_UNITS = 2**53 - 1


def validate_units(value: int, name: str, *, positive: bool = False) -> int:
    """Require a whole-unit input inside the exact float64 integer range."""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer, excluding booleans")
    result = int(value)
    if result < (1 if positive else 0) or result > MAX_UNITS:
        bound = "1" if positive else "0"
        raise ValueError(f"{name} must be between {bound} and MAX_UNITS ({MAX_UNITS})")
    return result


def validate_nonnegative(value: float, name: str, *, quantity: bool = False) -> float:
    """Validate numeric assumptions without accepting strings or boolean counts."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{name} must be a finite nonnegative number, excluding booleans"
        )
    if quantity and value > MAX_UNITS:
        raise ValueError(f"{name} must not exceed MAX_UNITS ({MAX_UNITS})")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite nonnegative number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return result


@dataclass(frozen=True, slots=True)
class InventoryParameters:
    """Illustrative single-location costs, service target and order constraints."""

    lead_time_weeks: int = 1
    review_period_weeks: int = 1
    service_level: float = 0.95
    unit_purchase_cost: float = 1.0
    unit_selling_price: float = 2.0
    holding_cost_per_unit_week: float = 0.02
    stockout_penalty_per_unit: float = 3.0
    order_cost: float = 5.0
    min_order_quantity: int = 0
    case_pack_size: int = 1
    max_inventory_capacity: int | None = None
    fixed_reorder_point: float | None = None
    fixed_target_level: float | None = None

    def __post_init__(self) -> None:
        for name in ("lead_time_weeks", "review_period_weeks", "case_pack_size"):
            object.__setattr__(
                self, name, validate_units(getattr(self, name), name, positive=True)
            )
        object.__setattr__(
            self,
            "min_order_quantity",
            validate_units(self.min_order_quantity, "min_order_quantity"),
        )
        for name in (
            "unit_purchase_cost",
            "unit_selling_price",
            "holding_cost_per_unit_week",
            "stockout_penalty_per_unit",
            "order_cost",
        ):
            object.__setattr__(
                self, name, validate_nonnegative(getattr(self, name), name)
            )
        service = validate_nonnegative(self.service_level, "service_level")
        if not 0 < service < 1:
            raise ValueError("service_level must be strictly between zero and one")
        object.__setattr__(self, "service_level", service)
        if self.max_inventory_capacity is not None:
            object.__setattr__(
                self,
                "max_inventory_capacity",
                validate_units(self.max_inventory_capacity, "max_inventory_capacity"),
            )
        if (self.fixed_reorder_point is None) != (self.fixed_target_level is None):
            raise ValueError(
                "fixed_reorder_point and fixed_target_level must be provided together"
            )
        if self.fixed_reorder_point is not None:
            for name in ("fixed_reorder_point", "fixed_target_level"):
                object.__setattr__(
                    self,
                    name,
                    validate_nonnegative(getattr(self, name), name, quantity=True),
                )
            if self.fixed_target_level < self.fixed_reorder_point:
                raise ValueError(
                    "fixed_target_level must be at least fixed_reorder_point"
                )


@dataclass(frozen=True, slots=True)
class InventoryState:
    """Current stock, all outstanding units and separately represented backorders."""

    on_hand: int
    on_order: int = 0
    backordered_units: int = 0

    def __post_init__(self) -> None:
        for name in ("on_hand", "on_order", "backordered_units"):
            object.__setattr__(self, name, validate_units(getattr(self, name), name))
        if self.on_hand + self.on_order > MAX_UNITS:
            raise ValueError("on_hand plus on_order must not exceed MAX_UNITS")


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Calculated assumptions/thresholds and the feasible whole-unit order."""

    weekly_forecast: float
    error_std: float
    lead_time_demand: float
    safety_stock: float
    reorder_point: float
    target_safety_stock: float
    target_inventory_position: float
    inventory_position: int
    requested_quantity: float
    recommended_order_quantity: int
    capacity_available: int | None
    service_level_factor: float
    reasons: tuple[str, ...]
    horizon_assumption: str


def _capacity_available(
    state: InventoryState, parameters: InventoryParameters
) -> int | None:
    if not isinstance(state, InventoryState) or not isinstance(
        parameters, InventoryParameters
    ):
        raise ValueError("state and parameters must be validated inventory dataclasses")
    capacity = parameters.max_inventory_capacity
    if capacity is None:
        return None
    reserved = state.on_hand + state.on_order
    if reserved > capacity:
        raise ValueError(
            "Initial on_hand plus all on_order exceeds max_inventory_capacity"
        )
    return capacity - reserved


def constrain_order_quantity(
    requested: float, state: InventoryState, parameters: InventoryParameters
) -> tuple[int, tuple[str, ...]]:
    """Round up positive demand to MOQ/pack, then apply conservative capacity.

    Capacity reserves on-hand plus every pipeline unit without assuming future
    consumption. If capacity prevents the rounded order, reduce to a pack multiple
    and return zero whenever a positive MOQ cannot fit. Without a configured
    capacity, crossing the exact-unit bound raises instead of silently truncating.
    """
    room = _capacity_available(state, parameters)
    request = validate_nonnegative(requested, "requested", quantity=True)
    if request == 0:
        return 0, ("no_order_requested",)
    reasons: list[str] = []
    whole = math.ceil(request)
    if whole != request:
        reasons.append("fractional_request_rounded_up")
    minimum = max(whole, parameters.min_order_quantity)
    if minimum > whole:
        reasons.append("minimum_order_quantity_applied")
    pack = parameters.case_pack_size
    rounded = ((minimum + pack - 1) // pack) * pack
    if rounded != minimum:
        reasons.append("case_pack_rounding_applied")
    if room is not None and rounded > room:
        reasons.append("capacity_limited_order")
        rounded = (room // pack) * pack
        if rounded == 0:
            reasons.append("capacity_cannot_fit_case_pack")
        if rounded < parameters.min_order_quantity:
            rounded = 0
            reasons.append("capacity_cannot_fit_minimum_order")
    elif room is None and state.on_hand + state.on_order + rounded > MAX_UNITS:
        raise ValueError("Order plus reserved inventory would exceed MAX_UNITS")
    if rounded == 0:
        reasons.append("no_feasible_positive_order")
    else:
        reasons.append("positive_order_feasible")
    return rounded, tuple(reasons)


def recommend_inventory(
    forecast: float,
    error_std: float,
    state: InventoryState,
    parameters: InventoryParameters,
    *,
    fixed: bool = False,
) -> Recommendation:
    """Plan at a scheduled review using only the supplied next-week information.

    An end-of-week order with lead L arrives before demand at t+L+1. Thus the
    lead-time threshold covers L complete future weeks and the order-up-to target
    covers L+R weeks. The same one-week forecast is carried forward explicitly.
    ``error_std`` is the caller's pre-calibrated empirical error magnitude; the
    normal and square-root formula assumes stable independent weekly errors.
    """
    capacity = _capacity_available(state, parameters)
    if not isinstance(fixed, bool):
        raise ValueError("fixed must be a boolean")
    demand = validate_nonnegative(forecast, "forecast", quantity=True)
    error = validate_nonnegative(error_std, "error_std", quantity=True)
    lead = parameters.lead_time_weeks
    protection = lead + parameters.review_period_weeks
    raw_factor = NormalDist().inv_cdf(parameters.service_level)
    factor = max(0.0, raw_factor)
    lead_demand = validate_nonnegative(lead * demand, "lead_time_demand", quantity=True)
    safety = validate_nonnegative(
        factor * error * math.sqrt(lead), "safety_stock", quantity=True
    )
    protection_safety = validate_nonnegative(
        factor * error * math.sqrt(protection), "target_safety_stock", quantity=True
    )
    reorder_point = validate_nonnegative(
        lead_demand + safety, "reorder_point", quantity=True
    )
    target = validate_nonnegative(
        protection * demand + protection_safety,
        "target_inventory_position",
        quantity=True,
    )
    reasons = ["flat_carry_forward_horizon"]
    if raw_factor < 0:
        reasons.append("negative_service_factor_floored_to_zero")
    if safety > 0:
        reasons.append("safety_stock_uses_normal_independent_error_approximation")
    if fixed and parameters.fixed_reorder_point is not None:
        reorder_point = parameters.fixed_reorder_point
        target = parameters.fixed_target_level
        reasons.append("fixed_override_replaces_computed_thresholds")
    elif fixed:
        reasons.append("fixed_policy_levels_derived_from_supplied_static_inputs")
    position = state.on_hand + state.on_order - state.backordered_units
    if position <= reorder_point:
        reasons.append("inventory_position_at_or_below_reorder_point")
        requested = validate_nonnegative(
            max(0.0, target - position), "requested_quantity", quantity=True
        )
        if requested == 0:
            reasons.append("target_inventory_position_already_met")
    else:
        requested = 0.0
        reasons.append("inventory_position_above_reorder_point")
    quantity, constraints = constrain_order_quantity(requested, state, parameters)
    reasons.extend(constraints)
    horizon = (
        f"Flat carry-forward approximation of the one available next-week forecast: "
        f"{lead} lead-time week(s) and {protection} protection week(s) (L+R). "
        f"An order placed after week t arrives before demand in week t+{lead + 1}; "
        "later-issued forecasts and future actuals are not consulted."
    )
    return Recommendation(
        weekly_forecast=demand,
        error_std=error,
        lead_time_demand=lead_demand,
        safety_stock=safety,
        reorder_point=reorder_point,
        target_safety_stock=protection_safety,
        target_inventory_position=target,
        inventory_position=position,
        requested_quantity=requested,
        recommended_order_quantity=quantity,
        capacity_available=capacity,
        service_level_factor=factor,
        reasons=tuple(reasons),
        horizon_assumption=horizon,
    )
