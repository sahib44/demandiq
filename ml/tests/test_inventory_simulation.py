"""Hand-calculated synthetic inventory timing, conservation and information tests."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from ml.inventory.planning import InventoryParameters
from ml.inventory.simulation import (
    POLICIES,
    ProductSimulationInput,
    ScheduledArrival,
    run_simulation,
)

MODELS = (
    "naive",
    "moving_average_4",
    "seasonal_naive_4",
    "ridge",
    "random_forest",
    "xgboost",
)


def frames(actual=(2, 4, 2), *, predictions=None, products=("SYNTH-A",), scale=10):
    weeks = pd.date_range("2024-01-01", periods=len(actual), freq="W-MON")
    demand, forecasts = [], []
    defaults = {
        "naive": [actual[0], *actual[:-1]],
        "moving_average_4": [2] * len(actual),
        "ridge": [2] * len(actual),
    }
    defaults.update(predictions or {})
    for code in products:
        for index, week in enumerate(weeks):
            demand.append({"stock_code": code, "week": week, "actual": actual[index]})
            for model in MODELS:
                forecasts.append(
                    {
                        "stock_code": code,
                        "week": week,
                        "model": model,
                        "prediction": defaults.get(model, [2] * len(actual))[index],
                        "scale": scale,
                        "actual": "Deliberately ignored: simulated decisions cannot read this field.",
                    }
                )
    return pd.DataFrame(demand), pd.DataFrame(forecasts)


def inputs(
    *,
    products=("SYNTH-A",),
    parameters=None,
    initial=3,
    fixed_forecast=2,
    fixed_error=0,
    errors=None,
    initial_orders=(),
):
    return {
        code: ProductSimulationInput(
            parameters=parameters or InventoryParameters(),
            initial_on_hand=initial,
            fixed_forecast=fixed_forecast,
            fixed_error_std=fixed_error,
            error_multipliers=(
                errors if errors is not None else {model: 0 for model in MODELS}
            ),
            initial_orders=initial_orders,
        )
        for code in products
    }


def result(
    actual=(2, 4, 2),
    *,
    configuration=None,
    predictions=None,
    products=("SYNTH-A",),
    scale=10,
):
    demand, forecasts = frames(
        actual, predictions=predictions, products=products, scale=scale
    )
    return run_simulation(
        demand,
        forecasts,
        configuration or inputs(products=products),
        selected_model="ridge",
    )


def policy_summary(simulation, policy):
    return next(
        row for row in simulation.summary["policies"] if row["policy"] == policy
    )


def test_hand_calculated_receipts_lost_sales_pipeline_and_terminal_costs():
    simulation = result()
    rows = simulation.records.query("policy == 'previous_demand'").reset_index(
        drop=True
    )
    assert rows.actual.tolist() == [2, 4, 2]
    assert rows.opening_inventory.tolist() == [3, 1, 0]
    assert rows.received_units.tolist() == [0, 0, 2]
    assert rows.fulfilled_units.tolist() == [2, 1, 2]
    assert rows.lost_units.tolist() == [0, 3, 0]
    assert rows.ending_inventory.tolist() == [1, 0, 0]
    assert rows.ordered_units.tolist() == [2, 4, 0]
    assert rows.outstanding_units.tolist() == [2, 6, 4]
    orders = simulation.orders.query("policy == 'previous_demand'").reset_index(
        drop=True
    )
    assert orders.due_week.tolist() == list(
        pd.to_datetime(["2024-01-15", "2024-01-22"])
    )
    assert orders.received_by_horizon.tolist() == [True, False]
    summary = policy_summary(simulation, "previous_demand")
    assert summary["total_demand"] == 8
    assert summary["fulfilled_units"] == 5
    assert summary["lost_units"] == 3
    assert summary["fill_rate"] == pytest.approx(5 / 8)
    assert summary["service_level"] == pytest.approx(2 / 3)
    assert summary["stockout_events"] == 1
    assert summary["average_inventory"] == pytest.approx(1 / 3)
    assert summary["purchase_cost"] == 6
    assert summary["holding_cost"] == pytest.approx(0.02)
    assert summary["stockout_cost"] == 9
    assert summary["order_cost"] == 10
    assert summary["gross_cash_cost"] == pytest.approx(25.02)
    assert summary["initial_inventory_asset_value"] == 3
    assert summary["terminal_inventory_asset_value"] == 4
    assert summary["net_inventory_cost"] == pytest.approx(24.02)
    assert summary["cost_of_goods_sold"] == 5
    assert summary["revenue"] == 10
    assert summary["lost_revenue"] == 6
    assert summary["estimated_lost_margin"] == 3
    assert summary["net_inventory_cost"] == pytest.approx(
        summary["cost_of_goods_sold"]
        + summary["holding_cost"]
        + summary["stockout_cost"]
        + summary["order_cost"]
    )


def test_every_week_obeys_stock_and_pipeline_conservation_and_nonnegative_state():
    simulation = result((1, 4, 0, 9, 2, 3), products=("SYNTH-A", "SYNTH-B"))
    rows = simulation.records
    assert (
        rows.opening_inventory + rows.received_units
        == rows.fulfilled_units + rows.ending_inventory
    ).all()
    assert (
        rows.opening_on_order - rows.received_units + rows.ordered_units
        == rows.outstanding_units
    ).all()
    assert (rows.actual == rows.fulfilled_units + rows.lost_units).all()
    assert (
        rows[["ending_inventory", "outstanding_units", "ordered_units", "lost_units"]]
        .ge(0)
        .all()
        .all()
    )
    assert len(simulation.summary["products"]) == 2 * len(POLICIES)
    for summary in simulation.summary["policies"]:
        assert summary["total_demand"] == 38
        assert summary["fulfilled_units"] + summary["lost_units"] == 38
        assert (
            summary["initial_on_hand"]
            + summary["initial_on_order"]
            + summary["ordered_units"]
            == summary["fulfilled_units"]
            + summary["ending_inventory"]
            + summary["outstanding_units"]
        )


def test_initial_pipeline_receives_before_demand_is_prepaid_and_keeps_future_assets():
    parameters = InventoryParameters(
        unit_purchase_cost=2,
        unit_selling_price=3,
        holding_cost_per_unit_week=0,
        stockout_penalty_per_unit=0,
        order_cost=0,
    )
    initial = (ScheduledArrival("2024-01-01", 2), ScheduledArrival("2024-02-05", 4))
    zero = {model: [0, 0] for model in MODELS}
    simulation = result(
        (2, 0),
        predictions=zero,
        configuration=inputs(
            parameters=parameters, initial=1, fixed_forecast=0, initial_orders=initial
        ),
    )
    first = simulation.records.groupby("policy", sort=False).head(1)
    assert first.opening_inventory.eq(1).all()
    assert first.opening_on_order.eq(6).all()
    assert first.received_units.eq(2).all()
    assert first.fulfilled_units.eq(2).all()
    prepaid = simulation.orders[simulation.orders.is_initial]
    assert len(prepaid) == 2 * len(POLICIES)
    assert prepaid.purchase_cost.eq(0).all()
    assert prepaid.order_cost.eq(0).all()
    for summary in simulation.summary["policies"]:
        direct_repeat = summary["policy"] == "previous_demand"
        assert summary["initial_inventory_asset_value"] == 14
        assert summary["terminal_inventory_asset_value"] == (
            14 if direct_repeat else 10
        )
        assert summary["outstanding_units"] == (6 if direct_repeat else 4)
        assert summary["ending_inventory"] == 1
        assert summary["gross_cash_cost"] == (4 if direct_repeat else 0)
        assert summary["net_inventory_cost"] == 4


def test_lead_time_waits_full_future_weeks_and_never_receives_early():
    parameters = InventoryParameters(lead_time_weeks=2)
    predictions = {model: [1] * 4 for model in MODELS}
    simulation = result(
        (1, 0, 0, 0),
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=0, fixed_forecast=1),
    )
    rows = simulation.records.query("policy == 'previous_demand'")
    assert rows.received_units.tolist() == [0, 0, 0, 1]
    for order in simulation.orders.itertuples():
        assert order.due_week == order.placed_week + pd.Timedelta(weeks=3)


def test_review_every_r_weeks_direct_repeat_uses_r_times_next_forecast_and_final_has_no_order():
    parameters = InventoryParameters(review_period_weeks=2)
    predictions = {model: [3] * 5 for model in MODELS}
    simulation = result(
        (3, 0, 3, 0, 0),
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=0, fixed_forecast=3),
    )
    previous = simulation.records.query("policy == 'previous_demand'")
    assert previous.ordered_units.tolist() == [6, 0, 6, 0, 0]
    final = simulation.records.groupby(["policy", "stock_code"], sort=False).tail(1)
    assert final.ordered_units.eq(0).all()
    last_recommendations = simulation.recommendations.groupby(
        ["policy", "stock_code"], sort=False
    ).tail(1)
    assert last_recommendations.reasons.map(
        lambda reasons: reasons == ("final_week_no_order",)
    ).all()
    assert last_recommendations.forecast_week.isna().all()


def test_matched_controllers_are_identical_when_forecasts_and_error_estimates_match():
    simulation = result(
        (2, 5, 4, 1, 0),
        predictions={"ridge": [2, 3, 4, 3, 2], "moving_average_4": [2, 3, 4, 3, 2]},
        configuration=inputs(errors={model: 0.25 for model in MODELS}),
    )
    columns = [name for name in simulation.records if name != "policy"]
    ml = simulation.records.query("policy == 'ml_safety_stock'")[columns].reset_index(
        drop=True
    )
    matched = simulation.records.query("policy == 'moving_average_safety_stock'")[
        columns
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(ml, matched)


def test_dynamic_error_uses_only_method_multiplier_and_known_scale_with_floor():
    configuration = inputs(errors={"ridge": 0.2, "moving_average_4": 0.4})
    simulation = result((2, 4, 2), configuration=configuration, scale=3)
    first = (
        simulation.recommendations.groupby("policy", sort=False)
        .head(1)
        .set_index("policy")
    )
    assert first.loc["ml_safety_stock", "error_std"] == 2
    assert first.loc["moving_average_safety_stock", "error_std"] == 4
    assert first.loc["fixed_reorder_point", "error_std"] == 0


def test_capacity_moq_and_pack_apply_to_all_policies_and_reserve_pipeline():
    parameters = InventoryParameters(
        max_inventory_capacity=8, min_order_quantity=5, case_pack_size=3
    )
    predictions = {model: [1] * 4 for model in MODELS}
    simulation = result(
        (1, 0, 1, 0),
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=0, fixed_forecast=1),
    )
    assert (
        (simulation.records.ending_inventory + simulation.records.outstanding_units)
        .le(8)
        .all()
    )
    assert simulation.orders.quantity.ge(5).all()
    assert simulation.orders.quantity.mod(3).eq(0).all()
    previous = simulation.records.query("policy == 'previous_demand'")
    assert previous.ordered_units.tolist() == [6, 0, 0, 0]
    blocked = simulation.recommendations.query("policy == 'previous_demand'").iloc[2]
    assert "capacity_limited_order" in blocked.reasons
    assert "capacity_cannot_fit_minimum_order" in blocked.reasons


def test_no_final_orders_even_for_one_week_horizon_and_huge_forecasts():
    predictions = {model: [1000] for model in MODELS}
    simulation = result((2,), predictions=predictions, configuration=inputs(initial=0))
    assert simulation.orders.empty
    assert simulation.records.ordered_units.eq(0).all()
    assert simulation.records.lost_units.eq(2).all()
    assert simulation.recommendations.weekly_forecast.isna().all()


def test_zero_demand_has_defined_service_fill_and_zero_baseline_savings_denominator():
    parameters = InventoryParameters(
        unit_purchase_cost=0,
        unit_selling_price=0,
        holding_cost_per_unit_week=0,
        stockout_penalty_per_unit=0,
        order_cost=0,
    )
    predictions = {model: [0] * 3 for model in MODELS}
    simulation = result(
        (0,) * 3,
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=0, fixed_forecast=0),
    )
    for summary in simulation.summary["policies"]:
        assert summary["fill_rate"] == 1
        assert summary["service_level"] == 1
        assert summary["stockout_events"] == 0
        assert summary["net_inventory_cost"] == 0
    assert all(
        row["simulated_savings"] == 0 and row["simulated_savings_percent"] is None
        for row in simulation.summary["comparisons"]
    )


def test_signed_simulated_savings_can_be_negative_and_lost_margin_is_not_double_counted():
    parameters = InventoryParameters(
        holding_cost_per_unit_week=1, stockout_penalty_per_unit=0
    )
    predictions = {model: [0] * 3 for model in MODELS}
    predictions["ridge"] = [0, 100, 100]
    simulation = result(
        (0,) * 3,
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=0, fixed_forecast=0),
    )
    ml = policy_summary(simulation, "ml_safety_stock")
    assert ml["net_inventory_cost"] == 205
    assert all(
        row["simulated_savings"] == -205 and row["simulated_savings_percent"] is None
        for row in simulation.summary["comparisons"]
    )
    assert "simulated" in simulation.summary["savings_label"]


def test_current_origin_forecast_is_ignored_and_future_information_cannot_change_earlier_decisions():
    demand, forecasts = frames((2, 4, 2, 3))
    original = run_simulation(demand, forecasts, inputs(), selected_model="ridge")
    current_changed = forecasts.copy(deep=True)
    current_changed.loc[
        current_changed.week.eq(pd.Timestamp("2024-01-01")), ["prediction", "scale"]
    ] = 99999
    ignored = run_simulation(demand, current_changed, inputs(), selected_model="ridge")
    pd.testing.assert_frame_equal(original.records, ignored.records)
    pd.testing.assert_frame_equal(original.recommendations, ignored.recommendations)
    future_demand, future_forecasts = demand.copy(deep=True), forecasts.copy(deep=True)
    future_demand.loc[future_demand.week.gt(pd.Timestamp("2024-01-01")), "actual"] = (
        9999
    )
    future_forecasts.loc[
        future_forecasts.week.ge(pd.Timestamp("2024-01-15")), ["prediction", "scale"]
    ] = 99999
    changed = run_simulation(
        future_demand, future_forecasts, inputs(), selected_model="ridge"
    )
    for original_table, changed_table in (
        (original.records, changed.records),
        (original.recommendations, changed.recommendations),
    ):
        pd.testing.assert_frame_equal(
            original_table[
                original_table.week.eq(pd.Timestamp("2024-01-01"))
            ].reset_index(drop=True),
            changed_table[
                changed_table.week.eq(pd.Timestamp("2024-01-01"))
            ].reset_index(drop=True),
        )


def test_fixed_policy_does_not_use_dynamic_forecasts_or_test_residuals():
    demand, forecasts = frames((2, 4, 2, 3))
    original = run_simulation(demand, forecasts, inputs(), selected_model="ridge")
    forecasts[["prediction", "scale"]] = 1000
    altered = run_simulation(demand, forecasts, inputs(), selected_model="ridge")
    pd.testing.assert_frame_equal(
        original.records.query("policy == 'fixed_reorder_point'").reset_index(
            drop=True
        ),
        altered.records.query("policy == 'fixed_reorder_point'").reset_index(drop=True),
    )


def test_previous_demand_reads_observed_completed_demand_and_ignores_naive_cache_values():
    demand, forecasts = frames((2, 4, 2))
    original = run_simulation(demand, forecasts, inputs(), selected_model="ridge")
    forecasts.loc[forecasts.model.eq("naive"), "prediction"] = 99999
    changed = run_simulation(demand, forecasts, inputs(), selected_model="ridge")
    pd.testing.assert_frame_equal(
        original.records.query("policy == 'previous_demand'").reset_index(drop=True),
        changed.records.query("policy == 'previous_demand'").reset_index(drop=True),
    )


def test_fractional_costs_do_not_create_negative_zero_consumption_costs():
    parameters = InventoryParameters(
        unit_purchase_cost=0.1,
        holding_cost_per_unit_week=0,
        stockout_penalty_per_unit=0,
        order_cost=0,
    )
    predictions = {model: [0] * 3 for model in MODELS}
    predictions["moving_average_4"] = [3] * 3
    simulation = result(
        (0,) * 3,
        predictions=predictions,
        configuration=inputs(parameters=parameters, initial=20, fixed_forecast=0),
    )
    assert all(row["net_inventory_cost"] == 0 for row in simulation.summary["policies"])
    assert all(
        row["simulated_savings_percent"] is None
        for row in simulation.summary["comparisons"]
    )


def test_input_permutation_reproducibility_and_original_frames_are_unchanged():
    demand, forecasts = frames(products=("SYNTH-A", "SYNTH-B"))
    before_demand, before_forecasts = demand.copy(deep=True), forecasts.copy(deep=True)
    original = run_simulation(
        demand,
        forecasts,
        inputs(products=("SYNTH-A", "SYNTH-B")),
        selected_model="ridge",
    )
    permuted = run_simulation(
        demand.sample(frac=1, random_state=11),
        forecasts.sample(frac=1, random_state=12),
        inputs(products=("SYNTH-B", "SYNTH-A")),
        selected_model="ridge",
    )
    pd.testing.assert_frame_equal(original.records, permuted.records)
    pd.testing.assert_frame_equal(original.orders, permuted.orders)
    pd.testing.assert_frame_equal(original.recommendations, permuted.recommendations)
    assert original.summary == permuted.summary
    pd.testing.assert_frame_equal(demand, before_demand)
    pd.testing.assert_frame_equal(forecasts, before_forecasts)


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate_demand",
        "duplicate_forecast",
        "missing_week",
        "product_gap",
        "missing_forecast",
        "extra_forecast",
        "missing_model",
        "negative_actual",
        "fractional_actual",
        "infinite_actual",
        "boolean_actual",
        "invalid_prediction",
        "invalid_scale",
        "aware_date",
        "tuesday",
        "missing_column",
        "empty",
    ],
)
def test_invalid_demand_or_forecast_inputs_are_rejected(kind):
    demand, forecasts = frames(products=("SYNTH-A", "SYNTH-B"))
    if kind == "duplicate_demand":
        demand = pd.concat([demand, demand.iloc[[0]]], ignore_index=True)
    elif kind == "duplicate_forecast":
        forecasts = pd.concat([forecasts, forecasts.iloc[[0]]], ignore_index=True)
    elif kind == "missing_week":
        demand = demand[demand.week.ne(pd.Timestamp("2024-01-08"))]
    elif kind == "product_gap":
        demand = demand.drop(index=1)
    elif kind == "missing_forecast":
        forecasts = forecasts.drop(index=0)
    elif kind == "extra_forecast":
        extra = forecasts.iloc[[0]].copy()
        extra["week"] = pd.Timestamp("2024-01-22")
        forecasts = pd.concat([forecasts, extra], ignore_index=True)
    elif kind == "missing_model":
        forecasts = forecasts[forecasts.model.ne("ridge")]
    elif kind == "negative_actual":
        demand["actual"] = -1
    elif kind == "fractional_actual":
        demand["actual"] = 0.5
    elif kind == "infinite_actual":
        demand["actual"] = np.inf
    elif kind == "boolean_actual":
        demand["actual"] = True
    elif kind == "invalid_prediction":
        forecasts["prediction"] = np.nan
    elif kind == "invalid_scale":
        forecasts["scale"] = -1
    elif kind == "aware_date":
        demand["week"] = demand.week.dt.tz_localize("UTC")
    elif kind == "tuesday":
        demand["week"] += pd.Timedelta(days=1)
    elif kind == "missing_column":
        forecasts = forecasts.drop(columns="scale")
    elif kind == "empty":
        demand = demand.iloc[:0]
    with pytest.raises(ValueError):
        run_simulation(
            demand,
            forecasts,
            inputs(products=("SYNTH-A", "SYNTH-B")),
            selected_model="ridge",
        )


@pytest.mark.parametrize(
    "change",
    [
        "missing_product",
        "extra_product",
        "wrong_type",
        "missing_error",
        "mutated_error",
        "past_arrival",
    ],
)
def test_invalid_product_configuration_is_rejected(change):
    demand, forecasts = frames()
    configuration = inputs()
    if change == "missing_product":
        configuration = {}
    elif change == "extra_product":
        configuration["SYNTH-EXTRA"] = configuration["SYNTH-A"]
    elif change == "wrong_type":
        configuration["SYNTH-A"] = {}
    elif change == "missing_error":
        configuration["SYNTH-A"] = replace(
            configuration["SYNTH-A"], error_multipliers={"ridge": 0}
        )
    elif change == "mutated_error":
        configuration["SYNTH-A"].error_multipliers["ridge"] = -1
    elif change == "past_arrival":
        configuration["SYNTH-A"] = replace(
            configuration["SYNTH-A"],
            initial_orders=(ScheduledArrival("2023-12-25", 1),),
        )
    with pytest.raises(ValueError):
        run_simulation(demand, forecasts, configuration, selected_model="ridge")


@pytest.mark.parametrize(
    "kind",
    [
        "negative_initial",
        "noninteger_initial",
        "capacity",
        "pipeline_capacity",
        "negative_error",
        "invalid_multiplier",
        "invalid_orders",
    ],
)
def test_invalid_product_inputs_fail_at_creation(kind):
    values = dict(
        parameters=InventoryParameters(),
        initial_on_hand=3,
        fixed_forecast=2,
        fixed_error_std=0,
        error_multipliers={"ridge": 0, "moving_average_4": 0},
    )
    if kind == "negative_initial":
        values["initial_on_hand"] = -1
    elif kind == "noninteger_initial":
        values["initial_on_hand"] = 1.0
    elif kind == "capacity":
        values["parameters"] = InventoryParameters(max_inventory_capacity=2)
    elif kind == "pipeline_capacity":
        values["parameters"] = InventoryParameters(max_inventory_capacity=4)
        values["initial_orders"] = (ScheduledArrival("2024-01-08", 2),)
    elif kind == "negative_error":
        values["fixed_error_std"] = -1
    elif kind == "invalid_multiplier":
        values["error_multipliers"] = {"ridge": np.inf}
    elif kind == "invalid_orders":
        values["initial_orders"] = []
    with pytest.raises(ValueError):
        ProductSimulationInput(**values)


@pytest.mark.parametrize(
    "week,quantity",
    [
        ("2024-01-02", 1),
        ("2024-01-01T00:00Z", 1),
        ("2024-01-01", 0),
        ("2024-01-01", True),
        ("2024-01-01", -1),
    ],
)
def test_invalid_scheduled_arrivals_are_rejected(week, quantity):
    with pytest.raises(ValueError):
        ScheduledArrival(week, quantity)
