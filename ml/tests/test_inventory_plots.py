"""Figures must reconcile with simulated facts, rather than accepting stale KPIs."""

from copy import deepcopy

import pandas as pd
import pytest

from ml.data.acquisition import sha256_file
from ml.inventory.planning import InventoryParameters
from ml.inventory.plots import PLOT_FILENAMES, render_inventory_plots
from ml.inventory.simulation import ProductSimulationInput, run_simulation


def measured(demand_units=3):
    weeks = pd.date_range("2020-01-06", periods=4, freq="W-MON")
    demand = pd.DataFrame({"stock_code": "A", "week": weeks, "actual": demand_units})
    forecasts = pd.DataFrame(
        [
            {
                "stock_code": "A",
                "week": week,
                "model": model,
                "prediction": demand_units,
                "scale": demand_units,
            }
            for week in weeks
            for model in ("naive", "moving_average_4", "ridge")
        ]
    )
    return run_simulation(
        demand,
        forecasts,
        {
            "A": ProductSimulationInput(
                InventoryParameters(),
                0,
                demand_units,
                0.0,
                {"ridge": 0.0, "moving_average_4": 0.0},
            )
        },
        selected_model="ridge",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("fill_rate", 0.999),
        ("service_level", 0.123),
        ("net_inventory_cost", 1_000_000),
        ("holding_cost", 100_000),
        ("average_inventory", 1_000_000),
        ("gross_cash_cost", float("nan")),
    ],
)
def test_stale_or_nonfinite_summary_cannot_generate_figures(tmp_path, field, value):
    result = measured()
    summary = deepcopy(result.summary)
    summary["policies"][0][field] = value
    with pytest.raises(ValueError, match="reconcile"):
        render_inventory_plots(
            result.records, summary, tmp_path / "bad", currency="GBP"
        )
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("units", [0, 3])
def test_real_simulation_figures_are_complete_and_deterministic(tmp_path, units):
    result = measured(units)
    for name in ("a", "b"):
        render_inventory_plots(
            result.records, result.summary, tmp_path / name, currency="GBP"
        )
    assert {p.name for p in (tmp_path / "a").iterdir()} == set(PLOT_FILENAMES)
    for name in PLOT_FILENAMES:
        assert (tmp_path / "a" / name).read_bytes().startswith(b"\x89PNG")
        assert sha256_file(tmp_path / "a" / name) == sha256_file(tmp_path / "b" / name)
