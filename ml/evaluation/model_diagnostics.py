"""Final-test error diagnostics; display cohorts chosen before evaluation."""

import os
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache/matplotlib")
)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FILENAMES = ("test_error_diagnostics.png", "test_error_direction.png")


def render_diagnostics(
    predictions: pd.DataFrame, metrics: dict[str, Any], output_dir: Path
) -> list[str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(predictions.model.unique())
    figure, axes = plt.subplots(3, 1, figsize=(14, 15), layout="constrained")
    errors = predictions.prediction - predictions.actual
    lo, hi = float(errors.min()), float(errors.max())
    bins = np.linspace(lo if lo != hi else lo - 0.5, hi if lo != hi else hi + 0.5, 41)
    for model in models:
        group = predictions.loc[predictions.model == model].copy()
        group["absolute_error"] = (group.prediction - group.actual).abs()
        axes[0].hist(
            group.prediction - group.actual,
            bins=bins,
            histtype="step",
            linewidth=1.5,
            label=model,
        )
        weekly = group.groupby("week").absolute_error.mean()
        axes[1].plot(weekly.index, weekly.values, marker="o", label=model)
    axes[0].set(
        title="Residual distribution · final test only",
        xlabel="Prediction − actual (units)",
        ylabel="Product-week observations",
    )
    axes[0].legend(ncols=2)
    axes[1].set(
        title="Error over test weeks · fixed pre-test cohort",
        xlabel="Week beginning",
        ylabel="MAE (units)",
    )
    axes[1].legend(ncols=2)
    volumes = sorted(
        metrics["training_segments"],
        key=lambda row: (-row["training_units"], row["stock_code"]),
    )
    products = [row["stock_code"] for row in volumes[:10]]
    x = np.arange(len(products))
    for index, model in enumerate(models):
        by_product = {
            row["stock_code"]: row["mae"]
            for row in metrics["by_product"]
            if row["model"] == model
        }
        axes[2].bar(
            x + (index - (len(models) - 1) / 2) * 0.12,
            [by_product[code] for code in products],
            width=0.12,
            label=model,
        )
    axes[2].set_xticks(x, products)
    axes[2].set(
        title="Product errors · up to ten products chosen from pre-test volume",
        xlabel="Product code",
        ylabel="MAE (units)",
    )
    axes[2].legend(ncols=2)
    for axis in axes:
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
    figure.savefig(
        output_dir / FILENAMES[0], dpi=150, metadata={"Software": "DemandIQ Phase 3"}
    )
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(13, 6), layout="constrained")
    rows = sorted(metrics["error_direction"], key=lambda row: row["model"])
    y = np.arange(len(rows))
    axis.barh(
        y,
        [-row["underforecast_units"] for row in rows],
        color="#D55E00",
        label="Underforecast units",
    )
    axis.barh(
        y,
        [row["overforecast_units"] for row in rows],
        color="#0072B2",
        label="Overforecast units",
    )
    axis.set_yticks(y, [row["model"] for row in rows])
    axis.axvline(0, color="#444444", linewidth=1)
    axis.set(
        title="Underforecasting versus overforecasting · final test only",
        xlabel="Total error units (under ← | → over)",
    )
    axis.legend()
    figure.savefig(
        output_dir / FILENAMES[1], dpi=150, metadata={"Software": "DemandIQ Phase 3"}
    )
    plt.close(figure)
    return list(FILENAMES)
