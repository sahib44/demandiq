"""Serializable illustrative business assumptions, with product-level overrides."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields, replace
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd

from ml.inventory.planning import (
    InventoryParameters,
    validate_nonnegative,
    validate_units,
)
from ml.inventory.simulation import ProductSimulationInput, ScheduledArrival


def week_start(value: Any, name: str = "week") -> pd.Timestamp:
    if isinstance(value, Real):
        raise ValueError(f"{name} must be a date, not a numeric timestamp")
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be a naive Monday date") from exc
    if (
        pd.isna(result)
        or result.tzinfo is not None
        or result != result.normalize()
        or result.dayofweek != 0
    ):
        raise ValueError(f"{name} must be a naive Monday date")
    return result


@dataclass(frozen=True)
class ScenarioConfig:
    name: str = "illustrative_default"
    currency: str = "GBP"
    initial_coverage_weeks: float = 2.0
    defaults: InventoryParameters = field(default_factory=InventoryParameters)
    products: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Scenario name must be nonempty text")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isupper()
            or not self.currency.isalpha()
            or not self.currency.isascii()
        ):
            raise ValueError("currency must be a three-letter uppercase code")
        object.__setattr__(
            self,
            "initial_coverage_weeks",
            validate_nonnegative(self.initial_coverage_weeks, "initial_coverage_weeks"),
        )
        if not isinstance(self.defaults, InventoryParameters):
            raise ValueError("defaults must be InventoryParameters")
        if not isinstance(self.products, dict):
            raise ValueError("products must map product codes to override objects")
        allowed = {
            "parameters",
            "initial_on_hand",
            "initial_orders",
            "backordered_units",
        }
        parameter_names = {f.name for f in fields(InventoryParameters)}
        normalized = deepcopy(self.products)
        for code, item in normalized.items():
            if (
                not isinstance(code, str)
                or not code.strip()
                or len(code) > 128
                or code != code.strip()
            ):
                raise ValueError(
                    "Product codes must be nonempty strings up to 128 characters"
                )
            if not isinstance(item, dict) or set(item) - allowed:
                raise ValueError(f"Unsupported product override for {code}")
            override = item.get("parameters", {})
            if not isinstance(override, dict) or set(override) - parameter_names:
                raise ValueError(f"Unsupported parameter override for {code}")
            parameters = replace(self.defaults, **override)
            if "parameters" in item:
                item["parameters"] = {key: getattr(parameters, key) for key in override}
            if "initial_on_hand" in item:
                item["initial_on_hand"] = validate_units(
                    item["initial_on_hand"], f"{code}.initial_on_hand"
                )
            backlog = item.get("backordered_units", 0)
            validate_units(backlog, f"{code}.backordered_units")
            if backlog:
                raise ValueError(
                    "Simulation is lost-sales only; initial backorders must be zero"
                )
            if "backordered_units" in item:
                item["backordered_units"] = int(backlog)
            arrivals = item.get("initial_orders", [])
            if not isinstance(arrivals, list):
                raise ValueError("initial_orders must be dated prepaid arrivals")
            for order in arrivals:
                if not isinstance(order, dict) or set(order) != {"week", "quantity"}:
                    raise ValueError(
                        "Each initial order needs exactly week and quantity"
                    )
                date = week_start(order["week"], "initial order week")
                order["quantity"] = validate_units(
                    order["quantity"], "initial order quantity", positive=True
                )
                order["week"] = date.date().isoformat()
        object.__setattr__(self, "products", normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "currency": self.currency,
            "initial_coverage_weeks": self.initial_coverage_weeks,
            "defaults": asdict(self.defaults),
            "products": deepcopy(self.products),
        }

    @classmethod
    def from_dict(cls, value: Any) -> ScenarioConfig:
        if not isinstance(value, dict) or set(value) - {
            "name",
            "currency",
            "initial_coverage_weeks",
            "defaults",
            "products",
        }:
            raise ValueError("Scenario configuration has unsupported fields")
        data = deepcopy(value)
        parameters = data.pop("defaults", {})
        if not isinstance(parameters, dict) or set(parameters) - {
            f.name for f in fields(InventoryParameters)
        }:
            raise ValueError("Unsupported default inventory parameter")
        return cls(defaults=InventoryParameters(**parameters), **data)

    @classmethod
    def from_file(cls, path: Path) -> ScenarioConfig:
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read scenario configuration: {path}") from exc
        return cls.from_dict(value)

    def product_input(
        self,
        stock_code: str,
        *,
        derived_on_hand: int,
        fixed_forecast: float,
        fixed_error_std: float,
        error_multipliers: dict[str, float],
    ) -> ProductSimulationInput:
        item = self.products.get(stock_code, {})
        return ProductSimulationInput(
            parameters=replace(self.defaults, **item.get("parameters", {})),
            initial_on_hand=item.get("initial_on_hand", derived_on_hand),
            fixed_forecast=fixed_forecast,
            fixed_error_std=fixed_error_std,
            error_multipliers=dict(error_multipliers),
            initial_orders=tuple(
                ScheduledArrival(week_start(order["week"]), order["quantity"])
                for order in item.get("initial_orders", [])
            ),
        )
