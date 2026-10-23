"""Standalone research figures from actual simulated records, not UI mock data."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(".cache/matplotlib").resolve()))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PLOT_FILENAMES = (
    "policy_comparison.png",
    "inventory_trajectory.png",
    "cost_components.png",
)


def render_inventory_plots(
    records: pd.DataFrame, summary: dict[str, Any], output_dir: Path, *, currency: str
) -> None:
    if records.empty or not summary.get("policies"):
        raise ValueError("Inventory figures require measured simulation records")
    rows = pd.DataFrame(summary["policies"]).sort_values("policy")
    if rows.policy.duplicated().any() or set(rows.policy) != set(records.policy):
        raise ValueError("Summary and weekly policies differ")
    for _, row in rows.iterrows():
        part = records.loc[records.policy == row.policy]
        if (
            int(part.actual.sum()) != row.total_demand
            or int(part.fulfilled_units.sum()) != row.fulfilled_units
            or int(part.lost_units.sum()) != row.lost_units
        ):
            raise ValueError("Summary demand does not reconcile with plotted records")
        expected_fill = (
            float(part.fulfilled_units.sum() / part.actual.sum())
            if part.actual.sum()
            else 1.0
        )
        expected_service = 1 - float(part.lost_units.gt(0).sum()) / len(part)
        expected_inventory = float(part.groupby("week").ending_inventory.sum().mean())
        for actual, expected in (
            (row.fill_rate, expected_fill),
            (row.service_level, expected_service),
            (row.average_inventory, expected_inventory),
        ):
            if not math.isfinite(actual) or not math.isclose(
                actual, expected, rel_tol=1e-10, abs_tol=1e-8
            ):
                raise ValueError(
                    "Summary service/inventory does not reconcile with plotted records"
                )
        for column in (
            "purchase_cost",
            "holding_cost",
            "stockout_cost",
            "order_cost",
            "gross_cash_cost",
        ):
            value = float(row[column])
            if (
                not math.isfinite(value)
                or value < 0
                or not math.isclose(
                    value, math.fsum(part[column]), rel_tol=1e-10, abs_tol=1e-8
                )
            ):
                raise ValueError("Summary costs do not reconcile with plotted records")
        net = float(row.net_inventory_cost)
        component_net = math.fsum(
            (
                row.cost_of_goods_sold,
                row.holding_cost,
                row.stockout_cost,
                row.order_cost,
            )
        )
        asset_net = math.fsum(
            (
                row.gross_cash_cost,
                row.initial_inventory_asset_value,
                -row.terminal_inventory_asset_value,
            )
        )
        if (
            not math.isfinite(net)
            or net < 0
            or not math.isclose(net, component_net, rel_tol=1e-10, abs_tol=1e-8)
            or not math.isclose(net, asset_net, rel_tol=1e-10, abs_tol=1e-8)
        ):
            raise ValueError(
                "Plotted net cost does not reconcile with components and assets"
            )
    labels = [str(p).replace("_", "\n") for p in rows.policy]
    x = np.arange(len(rows))
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
    axes[0].bar(x, rows.net_inventory_cost, color="#0072B2")
    axes[0].set_ylabel(f"Terminal-adjusted net cost ({currency})")
    axes[1].bar(
        x, 100 * rows.fill_rate, label="Unit fill rate", width=0.4, color="#009E73"
    )
    axes[1].bar(
        x + 0.4,
        100 * rows.service_level,
        label="Weekly no-stockout fraction",
        width=0.4,
        color="#E69F00",
    )
    axes[1].set_ylabel("Simulated service (%)")
    axes[1].set_ylim(0, 105)
    axes[1].legend(loc="lower right")
    for axis in axes:
        axis.set_xticks(x, labels)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    fig.suptitle(
        "Retrospective policy comparison · illustrative assumptions, no real company savings"
    )
    fig.savefig(
        output_dir / PLOT_FILENAMES[0], dpi=150, metadata={"Software": "DemandIQ"}
    )
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), layout="constrained", sharex=True)
    for policy, group in records.groupby("policy", sort=True):
        weekly = group.groupby("week").agg(
            ending_inventory=("ending_inventory", "sum"),
            fulfilled_units=("fulfilled_units", "sum"),
            actual=("actual", "sum"),
        )
        axes[0].plot(weekly.index, weekly.ending_inventory, marker="o", label=policy)
        fill = weekly.fulfilled_units.div(
            weekly.actual.where(weekly.actual != 0)
        ).fillna(1)
        axes[1].plot(weekly.index, 100 * fill, marker="o", label=policy)
    axes[0].set_ylabel("Total ending on-hand units")
    axes[1].set_ylabel("Weekly fulfilled / demand (%)")
    axes[1].set_xlabel("Historical demand week beginning")
    axes[0].legend(ncols=2)
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.suptitle(
        "Simulated inventory and service over time · common initial state and demand"
    )
    fig.savefig(
        output_dir / PLOT_FILENAMES[1], dpi=150, metadata={"Software": "DemandIQ"}
    )
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(11, 5), layout="constrained")
    bottom = np.zeros(len(rows))
    cogs = (
        rows.net_inventory_cost
        - rows.holding_cost
        - rows.stockout_cost
        - rows.order_cost
    )
    for name, values, color in (
        ("Consumed inventory at purchase cost", cogs, "#0072B2"),
        ("Holding", rows.holding_cost, "#009E73"),
        ("Lost-unit penalty", rows.stockout_cost, "#D55E00"),
        ("Order fees", rows.order_cost, "#CC79A7"),
    ):
        axis.bar(x, values, bottom=bottom, label=name, color=color)
        bottom += np.asarray(values)
    axis.set_xticks(x, labels)
    axis.set_ylabel(f"Terminal-adjusted net cost ({currency})")
    axis.legend()
    axis.set_title("Simulated cost components · full terminal asset recovery assumed")
    fig.savefig(
        output_dir / PLOT_FILENAMES[2], dpi=150, metadata={"Software": "DemandIQ"}
    )
    plt.close(fig)
