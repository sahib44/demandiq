"""Standalone validation figures from measured predictions, never mock results."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".cache" / "matplotlib")
)

import matplotlib  # noqa: E402

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.evaluation.metrics import (  # noqa: E402
    evaluate_predictions,
    validated_predictions,
)

PLOT_FILENAMES = (
    "baseline_metrics.png",
    "validation_demand.png",
    "residuals_and_bias.png",
    "product_errors.png",
)
MODEL_LABELS = {
    "naive": "Last observed",
    "moving_average_4": "Four-week mean",
    "seasonal_naive_4": "Four-week seasonal naive",
}
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9")


def _label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


def _save(figure: plt.Figure, output_dir: Path, filename: str) -> None:
    try:
        figure.savefig(
            output_dir / filename,
            dpi=150,
            facecolor="white",
            metadata={"Software": "DemandIQ Phase 2 validation"},
        )
    finally:
        plt.close(figure)


def _metric_bars(metrics: dict[str, Any], models: list[str], output: Path) -> None:
    overall = {row["model"]: row for row in metrics["overall"]}
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for axis, metric, title, ylabel in zip(
        axes,
        ("wape", "rmse"),
        ("Weighted absolute percentage error", "Root mean squared error"),
        ("WAPE (%) — lower is better", "RMSE (demand units) — lower is better"),
        strict=True,
    ):
        values = [overall[model][metric] for model in models]
        bars = axis.bar(
            np.arange(len(models)),
            [value if value is not None else 0 for value in values],
            color=[COLORS[index % len(COLORS)] for index in range(len(models))],
            width=0.65,
        )
        for bar, value in zip(bars, values, strict=True):
            axis.annotate(
                "Undefined\nzero actual demand" if value is None else f"{value:,.2f}",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
            )
            if value is None:
                bar.set_visible(False)
        axis.set_xticks(
            np.arange(len(models)),
            [_label(model) for model in models],
            rotation=18,
            ha="right",
        )
        axis.set(title=title, ylabel=ylabel)
        axis.set_ylim(
            0, max([value for value in values if value is not None] or [1]) * 1.22 or 1
        )
        axis.grid(axis="y", alpha=0.25)
        axis.set_axisbelow(True)
    figure.suptitle("Baseline comparison · validation only", fontsize=15)
    _save(figure, output, PLOT_FILENAMES[0])


def _weekly_plots(
    frame: pd.DataFrame, metrics: dict[str, Any], models: list[str], output: Path
) -> None:
    first_model = frame[frame.model.eq(models[0])]
    fold_order = (
        first_model.groupby("fold")
        .week.min()
        .reset_index()
        .sort_values(["week", "fold"], kind="stable")
        .fold.tolist()
    )
    keys: list[tuple[str, pd.Timestamp]] = []
    cohorts: list[str] = []
    boundaries: list[float] = []
    for fold in fold_order:
        subset = first_model[first_model.fold.eq(fold)]
        if keys:
            boundaries.append(len(keys) - 0.5)
        keys.extend((fold, week) for week in sorted(subset.week.unique()))
        cohorts.append(f"{fold}: {subset.stock_code.nunique()} products")
    positions = {key: index for index, key in enumerate(keys)}
    actuals = first_model.groupby(["fold", "week"], sort=True).actual.sum()
    figure, axes = plt.subplots(
        2, 1, figsize=(13, 8), layout="constrained", sharex=True
    )
    # Draw each fold independently so changing cohorts never form a continuous line.
    for fold_number, fold in enumerate(fold_order):
        fold_keys = [key for key in keys if key[0] == fold]
        x = [positions[key] for key in fold_keys]
        axes[0].plot(
            x,
            [actuals.loc[key] for key in fold_keys],
            color="#222222",
            linewidth=2.2,
            marker="o",
            markersize=4,
            label="Observed gross demand" if fold_number == 0 else None,
        )
        for model_number, model in enumerate(models):
            subset = frame[frame.model.eq(model) & frame.fold.eq(fold)]
            totals = subset.groupby("week").prediction.sum()
            color = COLORS[model_number % len(COLORS)]
            axes[0].plot(
                x,
                [totals.loc[key[1]] for key in fold_keys],
                color=color,
                linewidth=1.5,
                linestyle="--",
                marker=".",
                label=_label(model) if fold_number == 0 else None,
            )
            weekly = {
                pd.Timestamp(row["week"]): row["mae"]
                for row in metrics["by_week"]
                if row["model"] == model and row["fold"] == fold
            }
            axes[1].plot(
                x,
                [weekly[key[1]] for key in fold_keys],
                color=color,
                linewidth=1.5,
                marker=".",
                label=_label(model) if fold_number == 0 else None,
            )
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
        axis.set_axisbelow(True)
        for boundary in boundaries:
            axis.axvline(boundary, color="#666666", linewidth=0.8, linestyle=":")
    tick_step = max(1, int(np.ceil(len(keys) / 14)))
    ticks = list(range(0, len(keys), tick_step))
    if ticks[-1] != len(keys) - 1:
        ticks.append(len(keys) - 1)
    axes[1].set_xticks(
        ticks,
        [f"{keys[index][0]}\n{keys[index][1]:%Y-%m-%d}" for index in ticks],
        fontsize=8,
    )
    axes[0].set(
        title="Observed versus predicted demand · sum over each fold's cohort",
        ylabel="Gross demand units",
    )
    axes[1].set(
        title="Error over validation weeks",
        ylabel="MAE (units per product)",
        xlabel="Validation fold / week beginning (folds displayed sequentially)",
    )
    axes[0].legend(loc="best", fontsize=9)
    axes[1].legend(loc="best", fontsize=9)
    figure.suptitle("Validation history · " + "; ".join(cohorts), fontsize=13)
    _save(figure, output, PLOT_FILENAMES[1])


def _residual_plots(
    frame: pd.DataFrame, metrics: dict[str, Any], models: list[str], output: Path
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(13, 5), layout="constrained")
    residuals = frame.prediction.to_numpy() - frame.actual.to_numpy()
    limit = float(np.abs(residuals).max()) or 0.5
    bins = np.linspace(-limit, limit, 32)
    for index, model in enumerate(models):
        subset = frame[frame.model.eq(model)]
        axes[0].hist(
            subset.prediction - subset.actual,
            bins=bins,
            histtype="step",
            linewidth=1.8,
            color=COLORS[index % len(COLORS)],
            label=_label(model),
        )
    axes[0].axvline(0, color="#333333", linewidth=0.8, linestyle=":")
    axes[0].set(
        title="Residual distribution",
        xlabel="Prediction − actual (units)",
        ylabel="Product-week observations",
    )
    axes[0].legend(fontsize=8)
    direction = {row["model"]: row for row in metrics["error_direction"]}
    overall = {row["model"]: row for row in metrics["overall"]}
    positions = np.arange(len(models))
    axes[1].barh(
        positions,
        [-direction[model]["underforecast_units"] for model in models],
        color="#D55E00",
        label="Underforecast units",
    )
    axes[1].barh(
        positions,
        [direction[model]["overforecast_units"] for model in models],
        color="#0072B2",
        label="Overforecast units",
    )
    axes[1].axvline(0, color="#333333", linewidth=0.8)
    axes[1].set_yticks(
        positions,
        [
            f"{_label(model)}\nmean bias: {overall[model]['bias']:+,.2f} units"
            for model in models
        ],
        fontsize=9,
    )
    axes[1].set(
        title="Underforecasting, overforecasting and bias",
        xlabel="Total error units (under ← | → over)",
    )
    axes[1].legend(fontsize=8, loc="best")
    axes[1].grid(axis="x", alpha=0.25)
    axes[1].set_axisbelow(True)
    figure.suptitle("Forecast errors · validation only", fontsize=15)
    _save(figure, output, PLOT_FILENAMES[2])


def _product_plot(metrics: dict[str, Any], models: list[str], output: Path) -> None:
    training = pd.DataFrame(metrics["training_segments"])
    products = (
        training.groupby("stock_code")
        .training_units.sum()
        .reset_index()
        .sort_values(
            ["training_units", "stock_code"], ascending=[False, True], kind="stable"
        )
        .head(10)
        .stock_code.tolist()
    )
    errors = {
        (row["model"], row["stock_code"]): row["mae"] for row in metrics["by_product"]
    }
    figure, axis = plt.subplots(
        figsize=(12, max(4.5, len(products) * 0.55 + 1.8)), layout="constrained"
    )
    height = 0.8 / len(models)
    positions = np.arange(len(products))
    for index, model in enumerate(models):
        offset = (index - (len(models) - 1) / 2) * height
        axis.barh(
            positions + offset,
            [errors[(model, product)] for product in products],
            height=height,
            label=_label(model),
            color=COLORS[index % len(COLORS)],
        )
    axis.set_yticks(positions, products, fontsize=9)
    axis.invert_yaxis()
    axis.set(
        title="Product errors · validation only\nUp to 10 products selected by summed training volume across folds",
        xlabel="MAE (demand units) — lower is better",
        ylabel="Product stock code",
    )
    axis.grid(axis="x", alpha=0.25)
    axis.set_axisbelow(True)
    axis.legend(fontsize=9, loc="best")
    _save(figure, output, PLOT_FILENAMES[3])


def render_phase2_plots(
    predictions: pd.DataFrame, metrics: dict[str, Any], output_dir: Path
) -> list[str]:
    """Render four deterministic 150-dpi PNGs from a validation report.

    Metrics are checked against the supplied observations and historical training
    volumes before publishing figures. Files contain no timestamps or local paths.
    PNG byte reproducibility assumes the same pinned libraries and font runtime.
    """
    frame = validated_predictions(predictions)
    if not isinstance(metrics, dict) or metrics.get("evaluation_scope") != "validation":
        raise ValueError("Plots require validation metrics from evaluate_predictions")
    try:
        expected = evaluate_predictions(
            frame, training_volumes=pd.DataFrame(metrics["training_segments"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Plots require a complete validation report with training volumes"
        ) from exc
    if any(metrics.get(key) != value for key, value in expected.items()):
        raise ValueError("Validation metrics do not match the supplied predictions")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    models = sorted(frame.model.unique().tolist())
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.hashsalt": "demandiq-phase2-validation",
        }
    ):
        _metric_bars(metrics, models, output)
        _weekly_plots(frame, metrics, models, output)
        _residual_plots(frame, metrics, models, output)
        _product_plot(metrics, models, output)
    return list(PLOT_FILENAMES)
