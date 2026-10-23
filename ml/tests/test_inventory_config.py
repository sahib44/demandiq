"""Deserialization and snapshot tests for explicitly illustrative assumptions."""

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from ml.inventory.config import ScenarioConfig, week_start
from ml.inventory.planning import InventoryParameters


def test_defaults_are_explicit_illustrative_and_round_trip():
    config = ScenarioConfig()
    data = config.to_dict()
    assert data["name"] == "illustrative_default"
    assert data["currency"] == "GBP"
    assert data["initial_coverage_weeks"] == 2.0
    assert data["defaults"]["lead_time_weeks"] == 1
    assert data["defaults"]["review_period_weeks"] == 1
    assert data["defaults"]["service_level"] == 0.95
    assert data["defaults"]["unit_purchase_cost"] == 1.0
    assert data["defaults"]["unit_selling_price"] == 2.0
    assert data["defaults"]["stockout_penalty_per_unit"] == 3.0
    assert ScenarioConfig.from_dict(data).to_dict() == data
    json.dumps(data, allow_nan=False, sort_keys=True)


def test_round_trip_file_and_product_overrides_are_detached(tmp_path):
    source = {
        "name": "synthetic_sensitivity",
        "currency": "USD",
        "initial_coverage_weeks": 3.0,
        "defaults": {"lead_time_weeks": 2, "order_cost": 2.5},
        "products": {
            "SYNTH-A": {
                "parameters": {"case_pack_size": 4, "min_order_quantity": 8},
                "initial_on_hand": 12,
                "backordered_units": 0,
                "initial_orders": [{"week": "2011-10-17", "quantity": 8}],
            }
        },
    }
    config = ScenarioConfig.from_dict(source)
    before = config.to_dict()
    source["defaults"]["lead_time_weeks"] = 99
    source["products"]["SYNTH-A"]["initial_orders"][0]["quantity"] = 999
    assert config.to_dict() == before
    exported = config.to_dict()
    exported["products"]["SYNTH-A"]["parameters"]["case_pack_size"] = 99
    assert config.to_dict() == before
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(before))
    assert ScenarioConfig.from_file(path).to_dict() == before


def test_product_input_applies_overrides_and_preserves_fallbacks():
    config = ScenarioConfig.from_dict(
        {
            "defaults": {"lead_time_weeks": 2, "unit_purchase_cost": 1.5},
            "products": {
                "SYNTH-A": {
                    "parameters": {"case_pack_size": 4},
                    "initial_on_hand": 12,
                    "initial_orders": [
                        {"week": "2011-10-24", "quantity": 3},
                        {"week": "2011-10-17", "quantity": 2},
                    ],
                }
            },
        }
    )
    errors = {"ridge": 0.5, "moving_average_4": 0.7}
    item = config.product_input(
        "SYNTH-A",
        derived_on_hand=99,
        fixed_forecast=2.5,
        fixed_error_std=1.25,
        error_multipliers=errors,
    )
    assert item.initial_on_hand == 12
    assert item.parameters.lead_time_weeks == 2
    assert item.parameters.case_pack_size == 4
    assert item.parameters.unit_purchase_cost == 1.5
    assert [arrival.week for arrival in item.initial_orders] == [
        pd.Timestamp("2011-10-17"),
        pd.Timestamp("2011-10-24"),
    ]
    assert item.fixed_forecast == 2.5
    assert item.fixed_error_std == 1.25
    errors["ridge"] = 100
    assert item.error_multipliers["ridge"] == 0.5
    other = config.product_input(
        "SYNTH-B",
        derived_on_hand=9,
        fixed_forecast=1.0,
        fixed_error_std=0.0,
        error_multipliers=errors,
    )
    assert other.initial_on_hand == 9
    assert other.parameters == config.defaults
    assert not other.initial_orders


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "{}",
        {"unexpected": 1},
        {"defaults": None},
        {"defaults": {"unknown_cost": 1}},
    ],
)
def test_unknown_or_malformed_configuration_rejected(value):
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(value)


@pytest.mark.parametrize("name", [None, "", "   ", 12, True])
def test_name_requires_nonempty_text(name):
    with pytest.raises(ValueError, match="name"):
        ScenarioConfig.from_dict({"name": name})


@pytest.mark.parametrize(
    "currency", [None, "", "gbp", "GB", "GBPP", "123", "ÅBC", 123, True]
)
def test_currency_requires_uppercase_three_letter_text(currency):
    with pytest.raises(ValueError, match="currency"):
        ScenarioConfig.from_dict({"currency": currency})


@pytest.mark.parametrize("coverage", [-1, np.nan, np.inf, -np.inf, True, "2", None])
def test_initial_coverage_requires_finite_nonnegative_number(coverage):
    with pytest.raises(ValueError, match="initial_coverage_weeks"):
        ScenarioConfig.from_dict({"initial_coverage_weeks": coverage})


def test_zero_initial_coverage_is_permitted():
    assert (
        ScenarioConfig.from_dict({"initial_coverage_weeks": 0}).initial_coverage_weeks
        == 0
    )


@pytest.mark.parametrize(
    "override",
    [
        {"lead_time_weeks": True},
        {"lead_time_weeks": 0},
        {"review_period_weeks": 1.5},
        {"service_level": True},
        {"service_level": 1.0},
        {"unit_purchase_cost": "1"},
        {"stockout_penalty_per_unit": np.inf},
        {"case_pack_size": 0},
        {"fixed_reorder_point": 2},
        {"fixed_target_level": 2},
        {"fixed_reorder_point": 3, "fixed_target_level": 2},
    ],
)
def test_default_and_product_parameter_validation_is_shared(override):
    for data in (
        {"defaults": override},
        {"products": {"SYNTH-A": {"parameters": override}}},
    ):
        with pytest.raises(ValueError):
            ScenarioConfig.from_dict(data)


@pytest.mark.parametrize("products", [None, [], "A"])
def test_products_requires_map(products):
    with pytest.raises(ValueError, match="products"):
        ScenarioConfig.from_dict({"products": products})


@pytest.mark.parametrize("code", [None, 12, "", " ", " A", "A ", "A" * 129])
def test_override_product_ids_require_normalized_bounded_text(code):
    with pytest.raises(ValueError, match="Product codes"):
        ScenarioConfig.from_dict({"products": {code: {}}})


@pytest.mark.parametrize(
    "item",
    [None, [], {"unknown": 1}, {"parameters": []}, {"parameters": {"unknown": 1}}],
)
def test_override_objects_reject_unknown_or_malformed_fields(item):
    with pytest.raises(ValueError, match="override"):
        ScenarioConfig.from_dict({"products": {"SYNTH-A": item}})


@pytest.mark.parametrize("field", ["initial_on_hand", "backordered_units"])
@pytest.mark.parametrize("value", [-1, 1.5, True, "1", None, 2**53])
def test_stock_fields_require_bounded_whole_nonnegative_units(field, value):
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict({"products": {"SYNTH-A": {field: value}}})


def test_nonzero_initial_backlog_rejected_in_lost_sales_mode():
    with pytest.raises(ValueError, match="lost-sales"):
        ScenarioConfig.from_dict({"products": {"SYNTH-A": {"backordered_units": 1}}})


@pytest.mark.parametrize(
    "orders",
    [
        None,
        {},
        "2011-10-17",
        [None],
        [{"week": "2011-10-17"}],
        [{"week": "2011-10-17", "quantity": 1, "extra": 2}],
    ],
)
def test_initial_orders_require_exact_dated_quantity_objects(orders):
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict({"products": {"SYNTH-A": {"initial_orders": orders}}})


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "2", None, 2**53])
def test_initial_order_quantities_require_positive_bounded_integers(quantity):
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(
            {
                "products": {
                    "SYNTH-A": {
                        "initial_orders": [{"week": "2011-10-17", "quantity": quantity}]
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NaT,
        True,
        pd.Timestamp("2011-01-03").value,
        "2011-01-04",
        "2011-01-03 00:01",
        pd.Timestamp("2011-01-03", tz="UTC"),
        datetime(2011, 1, 3, tzinfo=UTC),
        "not a date",
    ],
)
def test_weeks_reject_numbers_missing_timezone_and_unaligned_dates(value):
    with pytest.raises(ValueError, match="date|Monday"):
        week_start(value)
    with pytest.raises(ValueError):
        ScenarioConfig.from_dict(
            {
                "products": {
                    "SYNTH-A": {"initial_orders": [{"week": value, "quantity": 1}]}
                }
            }
        )


@pytest.mark.parametrize(
    "value",
    [
        "2011-01-03",
        datetime(2011, 1, 3),
        pd.Timestamp("2011-01-03"),
        np.datetime64("2011-01-03"),
    ],
)
def test_supported_naive_monday_inputs_are_canonicalized(value):
    assert week_start(value) == pd.Timestamp("2011-01-03")
    config = ScenarioConfig.from_dict(
        {"products": {"SYNTH-A": {"initial_orders": [{"week": value, "quantity": 1}]}}}
    )
    assert (
        config.to_dict()["products"]["SYNTH-A"]["initial_orders"][0]["week"]
        == "2011-01-03"
    )


def test_file_errors_are_clear(tmp_path):
    with pytest.raises(ValueError, match="Cannot read"):
        ScenarioConfig.from_file(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{")
    with pytest.raises(ValueError, match="Cannot read"):
        ScenarioConfig.from_file(invalid)
    invalid.write_text("[]")
    with pytest.raises(ValueError, match="unsupported fields"):
        ScenarioConfig.from_file(invalid)


def test_capacity_with_initial_pipeline_is_checked_at_product_input():
    config = ScenarioConfig.from_dict(
        {
            "defaults": {"max_inventory_capacity": 5},
            "products": {
                "SYNTH-A": {
                    "initial_on_hand": 4,
                    "initial_orders": [{"week": "2011-10-17", "quantity": 2}],
                }
            },
        }
    )
    with pytest.raises(ValueError, match="capacity"):
        config.product_input(
            "SYNTH-A",
            derived_on_hand=0,
            fixed_forecast=1.0,
            fixed_error_std=0.0,
            error_multipliers={"ridge": 0.0, "moving_average_4": 0.0},
        )


def test_constructor_requires_validated_parameter_object():
    with pytest.raises(ValueError, match="InventoryParameters"):
        ScenarioConfig(defaults={})
    assert (
        ScenarioConfig(defaults=InventoryParameters(order_cost=0)).defaults.order_cost
        == 0
    )


def test_numpy_numeric_overrides_are_normalized_for_json_round_trip():
    config = ScenarioConfig.from_dict(
        {
            "initial_coverage_weeks": np.float64(2.0),
            "defaults": {"lead_time_weeks": np.int64(2), "order_cost": np.float64(2.5)},
            "products": {
                "SYNTH-A": {
                    "parameters": {
                        "case_pack_size": np.int64(4),
                        "service_level": np.float64(0.8),
                    },
                    "initial_on_hand": np.int64(6),
                    "backordered_units": np.int64(0),
                    "initial_orders": [
                        {"week": np.datetime64("2011-10-17"), "quantity": np.int64(2)}
                    ],
                }
            },
        }
    )
    data = config.to_dict()
    encoded = json.dumps(data, allow_nan=False, sort_keys=True)
    assert ScenarioConfig.from_dict(json.loads(encoded)).to_dict() == data
    assert type(data["defaults"]["lead_time_weeks"]) is int
    assert type(data["products"]["SYNTH-A"]["parameters"]["case_pack_size"]) is int
    assert type(data["products"]["SYNTH-A"]["initial_on_hand"]) is int
    assert type(data["products"]["SYNTH-A"]["backordered_units"]) is int
    assert type(data["products"]["SYNTH-A"]["initial_orders"][0]["quantity"]) is int
