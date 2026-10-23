"""Hand-calculated inventory decisions under explicit synthetic assumptions."""

import json
import math
from dataclasses import FrozenInstanceError, asdict

import numpy as np
import pytest

from ml.inventory.planning import (
    MAX_UNITS,
    InventoryParameters,
    InventoryState,
    constrain_order_quantity,
    recommend_inventory,
    validate_nonnegative,
    validate_units,
)


def test_default_assumptions_and_frozen_inputs_are_explicit():
    parameters = InventoryParameters()
    assert asdict(parameters) == {
        "lead_time_weeks": 1,
        "review_period_weeks": 1,
        "service_level": 0.95,
        "unit_purchase_cost": 1.0,
        "unit_selling_price": 2.0,
        "holding_cost_per_unit_week": 0.02,
        "stockout_penalty_per_unit": 3.0,
        "order_cost": 5.0,
        "min_order_quantity": 0,
        "case_pack_size": 1,
        "max_inventory_capacity": None,
        "fixed_reorder_point": None,
        "fixed_target_level": None,
    }
    state = InventoryState(5)
    with pytest.raises(FrozenInstanceError):
        state.on_hand = 6
    with pytest.raises(FrozenInstanceError):
        parameters.service_level = 0.9


def test_hand_calculated_lead_review_and_inventory_position_without_safety():
    parameters = InventoryParameters(
        lead_time_weeks=4, review_period_weeks=2, service_level=0.5
    )
    state = InventoryState(on_hand=20, on_order=5, backordered_units=5)
    result = recommend_inventory(10, 3, state, parameters)
    assert result.lead_time_demand == 40
    assert result.safety_stock == result.target_safety_stock == 0
    assert result.service_level_factor == 0
    assert result.reorder_point == 40
    assert result.target_inventory_position == 60
    assert result.inventory_position == 20
    assert result.requested_quantity == result.recommended_order_quantity == 40
    assert result.capacity_available is None
    assert "6 protection week(s) (L+R)" in result.horizon_assumption
    assert "t+5" in result.horizon_assumption
    assert "Flat carry-forward approximation" in result.horizon_assumption


def test_normal_safety_stock_and_pack_order_match_known_numeric_example():
    parameters = InventoryParameters(
        lead_time_weeks=4, review_period_weeks=2, case_pack_size=5
    )
    result = recommend_inventory(10, 3, InventoryState(20), parameters)
    assert result.service_level_factor == pytest.approx(1.64485362695)
    assert result.safety_stock == pytest.approx(9.86912176171)
    assert result.target_safety_stock == pytest.approx(12.087, abs=0.001)
    assert result.reorder_point == pytest.approx(49.86912176171)
    assert result.target_inventory_position == pytest.approx(72.087, abs=0.001)
    assert result.requested_quantity == pytest.approx(52.087, abs=0.001)
    assert result.recommended_order_quantity == 55
    assert "case_pack_rounding_applied" in result.reasons


def test_reorder_is_inclusive_and_pipeline_prevents_duplicate_ordering():
    parameters = InventoryParameters(service_level=0.5)
    at_threshold = recommend_inventory(10, 0, InventoryState(10), parameters)
    assert (
        at_threshold.requested_quantity == at_threshold.recommended_order_quantity == 10
    )
    above = recommend_inventory(10, 0, InventoryState(4, on_order=7), parameters)
    assert above.inventory_position == 11
    assert above.recommended_order_quantity == 0
    assert "inventory_position_above_reorder_point" in above.reasons
    backlog = recommend_inventory(
        10, 0, InventoryState(4, on_order=7, backordered_units=6), parameters
    )
    assert backlog.inventory_position == 5
    assert backlog.recommended_order_quantity == 15


def test_service_below_half_floors_negative_normal_factor_to_zero():
    result = recommend_inventory(
        10, 100, InventoryState(0), InventoryParameters(service_level=0.1)
    )
    assert (
        result.service_level_factor
        == result.safety_stock
        == result.target_safety_stock
        == 0
    )
    assert result.reorder_point == 10
    assert result.target_inventory_position == 20
    assert "negative_service_factor_floored_to_zero" in result.reasons


def test_minimum_then_pack_rounding_applies_only_to_positive_requests():
    parameters = InventoryParameters(min_order_quantity=10, case_pack_size=6)
    quantity, reasons = constrain_order_quantity(1, InventoryState(0), parameters)
    assert quantity == 12
    assert "minimum_order_quantity_applied" in reasons
    assert "case_pack_rounding_applied" in reasons
    assert constrain_order_quantity(0, InventoryState(0), parameters)[0] == 0
    assert (
        constrain_order_quantity(
            6.1, InventoryState(0), InventoryParameters(case_pack_size=2)
        )[0]
        == 8
    )


def test_capacity_reserves_all_pipeline_and_reduces_to_feasible_pack():
    parameters = InventoryParameters(
        min_order_quantity=10, case_pack_size=5, max_inventory_capacity=30
    )
    state = InventoryState(10, on_order=8)
    result = recommend_inventory(100, 0, state, parameters)
    assert result.capacity_available == 12
    assert result.recommended_order_quantity == 10
    assert result.recommended_order_quantity + state.on_hand + state.on_order <= 30
    assert "capacity_limited_order" in result.reasons


def test_capacity_never_creates_a_positive_order_below_moq():
    parameters = InventoryParameters(
        min_order_quantity=10, case_pack_size=3, max_inventory_capacity=9
    )
    quantity, reasons = constrain_order_quantity(20, InventoryState(0), parameters)
    assert quantity == 0
    assert "capacity_cannot_fit_minimum_order" in reasons
    quantity, reasons = constrain_order_quantity(
        5, InventoryState(0), InventoryParameters(max_inventory_capacity=0)
    )
    assert quantity == 0
    assert "capacity_cannot_fit_case_pack" in reasons


def test_initial_capacity_violation_is_rejected_even_without_requested_order():
    parameters = InventoryParameters(max_inventory_capacity=4)
    with pytest.raises(ValueError, match="all on_order exceeds"):
        constrain_order_quantity(0, InventoryState(2, on_order=3), parameters)
    with pytest.raises(ValueError, match="all on_order exceeds"):
        recommend_inventory(0, 0, InventoryState(2, on_order=3), parameters)


def test_fixed_threshold_overrides_are_explicit_and_do_not_change_dynamic_policy():
    parameters = InventoryParameters(
        fixed_reorder_point=5, fixed_target_level=12, service_level=0.5
    )
    state = InventoryState(4)
    fixed = recommend_inventory(10, 0, state, parameters, fixed=True)
    dynamic = recommend_inventory(10, 0, state, parameters)
    assert fixed.reorder_point == 5
    assert fixed.target_inventory_position == 12
    assert fixed.recommended_order_quantity == 8
    assert "fixed_override_replaces_computed_thresholds" in fixed.reasons
    assert dynamic.recommended_order_quantity == 16
    derived = recommend_inventory(
        10, 0, state, InventoryParameters(service_level=0.5), fixed=True
    )
    assert derived.recommended_order_quantity == dynamic.recommended_order_quantity


@pytest.mark.parametrize(
    "field,value",
    [
        ("lead_time_weeks", 0),
        ("lead_time_weeks", 1.5),
        ("review_period_weeks", True),
        ("review_period_weeks", -1),
        ("service_level", 0),
        ("service_level", 1),
        ("service_level", True),
        ("unit_purchase_cost", math.inf),
        ("unit_selling_price", -1),
        ("holding_cost_per_unit_week", math.nan),
        ("stockout_penalty_per_unit", False),
        ("order_cost", "5"),
        ("min_order_quantity", 1.5),
        ("min_order_quantity", True),
        ("case_pack_size", 0),
        ("max_inventory_capacity", -1),
        ("max_inventory_capacity", 3.0),
        ("fixed_reorder_point", 5),
        ("fixed_target_level", 10),
    ],
)
def test_invalid_business_parameters_fail_usefully(field, value):
    with pytest.raises(ValueError):
        InventoryParameters(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("on_hand", True),
        ("on_hand", -1),
        ("on_order", 0.5),
        ("backordered_units", np.bool_(False)),
        ("on_hand", MAX_UNITS + 1),
    ],
)
def test_invalid_inventory_state_rejected(field, value):
    fields = {"on_hand": 0, "on_order": 0, "backordered_units": 0}
    fields[field] = value
    with pytest.raises(ValueError):
        InventoryState(**fields)


def test_conflicting_fixed_levels_and_boolean_fixed_flag_rejected():
    with pytest.raises(ValueError, match="at least"):
        InventoryParameters(fixed_reorder_point=10, fixed_target_level=9)
    with pytest.raises(ValueError, match="boolean"):
        recommend_inventory(10, 0, InventoryState(0), InventoryParameters(), fixed=1)


@pytest.mark.parametrize(
    "forecast,error",
    [(-1, 0), (True, 0), (np.nan, 0), (1, np.inf), (1, -1), (1, False)],
)
def test_invalid_forecast_error_values_rejected(forecast, error):
    with pytest.raises(ValueError):
        recommend_inventory(forecast, error, InventoryState(0), InventoryParameters())


def test_exact_unit_bound_and_rounding_overflow_are_guarded():
    assert validate_units(np.int64(MAX_UNITS), "units") == MAX_UNITS
    assert validate_nonnegative(MAX_UNITS, "forecast", quantity=True) == MAX_UNITS
    with pytest.raises(ValueError, match="MAX_UNITS"):
        InventoryState(MAX_UNITS, on_order=1)
    with pytest.raises(ValueError, match="MAX_UNITS"):
        constrain_order_quantity(
            MAX_UNITS, InventoryState(0), InventoryParameters(case_pack_size=2)
        )
    with pytest.raises(ValueError, match="MAX_UNITS"):
        constrain_order_quantity(1, InventoryState(MAX_UNITS), InventoryParameters())
    assert (
        constrain_order_quantity(
            MAX_UNITS,
            InventoryState(0),
            InventoryParameters(case_pack_size=2, max_inventory_capacity=MAX_UNITS),
        )[0]
        == MAX_UNITS - 1
    )
    with pytest.raises(ValueError, match="MAX_UNITS"):
        recommend_inventory(
            MAX_UNITS, 0, InventoryState(0), InventoryParameters(lead_time_weeks=2)
        )
    with pytest.raises(ValueError, match="MAX_UNITS"):
        recommend_inventory(
            1,
            0,
            InventoryState(0, backordered_units=MAX_UNITS),
            InventoryParameters(service_level=0.5),
        )


def test_stateless_decisions_are_independent_of_later_planning_calls():
    state, parameters = InventoryState(10), InventoryParameters()
    before = recommend_inventory(8, 2, state, parameters)
    recommend_inventory(
        100000, 50, InventoryState(0), InventoryParameters(lead_time_weeks=3)
    )
    after = recommend_inventory(8, 2, state, parameters)
    assert before == after
    assert state == InventoryState(10)
    json.dumps(asdict(after), allow_nan=False)


@pytest.mark.parametrize(
    "requested,moq,pack,capacity",
    [(0.1, 0, 2, 50), (30, 10, 7, 20), (100, 15, 5, 18), (2, 10, 6, 11)],
)
def test_feasible_order_invariants(requested, moq, pack, capacity):
    state = InventoryState(1, on_order=2)
    parameters = InventoryParameters(
        min_order_quantity=moq, case_pack_size=pack, max_inventory_capacity=capacity
    )
    quantity, _ = constrain_order_quantity(requested, state, parameters)
    assert quantity >= 0
    assert quantity % pack == 0
    assert quantity == 0 or quantity >= moq
    assert quantity + state.on_hand + state.on_order <= capacity
