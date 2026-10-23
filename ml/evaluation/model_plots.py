"""Static figures separating model selection, final testing and uncertainty."""

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

from ml.evaluation.metrics import evaluate_predictions  # noqa: E402
from ml.evaluation.uncertainty import interval_metrics  # noqa: E402

PLOT_FILENAMES = (
    "model_comparison.png",
    "selected_forecast_intervals.png",
    "uncertainty_coverage.png",
    "native_feature_importance.png",
)
LABELS = {
    "naive": "Last observed",
    "moving_average_4": "Four-week mean",
    "seasonal_naive_4": "Four-week seasonal naive",
    "ridge": "Ridge",
    "hist_gradient_boosting": "Histogram gradient boosting",
    "xgboost": "XGBoost",
}


def _label(model: str) -> str:
    return LABELS.get(model, model.replace("_", " "))


def _tick_label(model: str) -> str:
    return {
        "hist_gradient_boosting": "Histogram\nboosting",
        "seasonal_naive_4": "Seasonal naive\n(four weeks)",
        "moving_average_4": "Four-week\nmean",
        "naive": "Last\nobserved",
    }.get(model, _label(model))


def _save(figure: plt.Figure, output: Path, name: str) -> None:
    try:
        figure.savefig(
            output / name,
            dpi=150,
            facecolor="white",
            metadata={"Software": "DemandIQ Phase 3 evaluation"},
        )
    finally:
        plt.close(figure)


def _overall(metrics: dict[str, Any], scope: set[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(metrics, dict) or metrics.get("evaluation_scope") not in scope:
        raise ValueError(
            "Evaluation metrics must explicitly identify selection validation or final test scope"
        )
    rows = metrics.get("overall")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Evaluation metrics require nonempty overall model results")
    result = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("model"), str)
            or row["model"] in result
        ):
            raise ValueError("Evaluation results require distinct model names")
        for key in ("mae", "wape"):
            value = row.get(key)
            if (
                value is None
                and key == "wape"
                and row.get("wape_status") == "undefined_zero_actual"
            ):
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not np.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    "Evaluation metrics must contain valid MAE and WAPE values"
                )
        result[row["model"]] = row
    return result


def _importance_rows(importance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(importance, list):
        raise ValueError(
            "importance must be a list of measured native feature importance rows"
        )
    rows = []
    seen = set()
    for row in importance:
        if not isinstance(row, dict):
            raise ValueError(
                "Each importance row requires feature, importance and method"
            )
        feature, method, value = (
            row.get("feature"),
            row.get("method"),
            row.get("importance"),
        )
        if (
            not isinstance(feature, str)
            or not feature.strip()
            or feature in seen
            or not isinstance(method, str)
            or not method.strip()
        ):
            raise ValueError(
                "Importance rows require distinct feature names and an explicit method"
            )
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not np.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                "Measured importance values must be finite and nonnegative"
            )
        rows.append({"feature": feature, "importance": float(value), "method": method})
        seen.add(feature)
    if len({row["method"] for row in rows}) > 1:
        raise ValueError(
            "A feature importance figure must use one explicit native method"
        )
    return sorted(rows, key=lambda row: (-row["importance"], row["feature"]))


def render_model_plots(
    test_predictions: pd.DataFrame,
    test_metrics: dict[str, Any],
    validation_metrics: dict[str, Any],
    importance: list[dict[str, Any]],
    output_dir: Path,
    *,
    selected_model: str,
    selected_product: str,
) -> list[str]:
    """Render four reproducible figures from real measured results.

    The caller freezes model selection before calibration and supplies the product
    selected using pretest training volume. The final-test report is checked
    against predictions. No selection is performed using final-test outcomes.
    """
    test = _overall(test_metrics, {"test", "final_test"})
    validation = _overall(validation_metrics, {"validation", "selection_validation"})
    if set(test) != set(validation):
        raise ValueError(
            "Selection-validation and final-test results must cover the same models"
        )
    try:
        measured = evaluate_predictions(
            test_predictions,
            training_volumes=pd.DataFrame(
                test_metrics["training_segments"], dtype=object
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Final-test plots require aligned predictions and training metadata"
        ) from exc
    if any(
        test_metrics.get(key) != value
        for key, value in measured.items()
        if key not in {"evaluation_scope", "metric_definitions"}
    ):
        raise ValueError("Final-test metrics do not match the supplied predictions")
    intervals = interval_metrics(test_predictions)
    if any(row["nominal_coverage"] is None for row in intervals["overall"]):
        raise ValueError(
            "Interval plots require nominal_coverage from frozen calibration for every model"
        )
    importance_rows = _importance_rows(importance)
    models = sorted(test)
    if selected_model not in test:
        raise ValueError("selected_model must appear in the measured results")
    selected = test_predictions[
        test_predictions.model.eq(selected_model)
        & test_predictions.stock_code.eq(selected_product)
    ].copy()
    if selected.empty:
        raise ValueError(
            "selected_product must appear in the selected model's final-test predictions"
        )
    if "week" not in selected or selected.week.duplicated().any():
        raise ValueError("The selected forecast must contain unique test weeks")
    selected["week"] = pd.to_datetime(selected.week, format="ISO8601", errors="raise")
    selected = selected.sort_values("week", kind="stable")
    if "nominal_coverage" not in selected:
        raise ValueError(
            "Interval plots require nominal_coverage from frozen calibration"
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.hashsalt": "demandiq-phase3-evaluation",
        }
    ):
        figure, axes = plt.subplots(1, 2, figsize=(15, 6), layout="constrained")
        positions = np.arange(len(models))
        for axis, metric, title in zip(
            axes, ("mae", "wape"), ("MAE (demand units)", "WAPE (%)"), strict=True
        ):
            for shift, table, color, label in [
                (-0.2, validation, "#0072B2", "Selection validation · first two folds"),
                (0.2, test, "#D55E00", "Final test · frozen choices"),
            ]:
                values = [table[model][metric] for model in models]
                bars = axis.bar(
                    positions + shift,
                    [value if value is not None else 0 for value in values],
                    width=0.38,
                    color=color,
                    label=label,
                )
                for bar, value in zip(bars, values, strict=True):
                    if value is None:
                        bar.set_visible(False)
                        axis.annotate(
                            "Undefined",
                            (bar.get_x() + bar.get_width() / 2, 0),
                            rotation=90,
                            ha="center",
                            va="bottom",
                            fontsize=8,
                        )
            axis.set_xticks(
                positions,
                [_tick_label(model) for model in models],
                ha="center",
                fontsize=9,
            )
            axis.set(title=title + " · lower is better", ylabel=title)
            axis.grid(axis="y", alpha=0.25)
            axis.set_axisbelow(True)
            axis.legend(fontsize=8)
        figure.suptitle(
            "Model comparison · selection validation and final test are separate",
            fontsize=15,
        )
        _save(figure, output, PLOT_FILENAMES[0])

        figure, axis = plt.subplots(figsize=(13, 5.5), layout="constrained")
        axis.fill_between(
            selected.week,
            selected.lower,
            selected.upper,
            color="#0072B2",
            alpha=0.2,
            label=f"Empirical interval · nominal {selected.nominal_coverage.iloc[0]:.0%}",
        )
        axis.plot(
            selected.week,
            selected.actual,
            color="#222222",
            marker="o",
            linewidth=2,
            label="Observed gross demand",
        )
        axis.plot(
            selected.week,
            selected.prediction,
            color="#0072B2",
            marker="s",
            linestyle="--",
            label="Frozen point forecast",
        )
        axis.set(
            title=f"Final test · {_label(selected_model)} · product {selected_product}\nProduct chosen from pretest volume; empirical intervals have no coverage guarantee",
            xlabel="Test week beginning",
            ylabel="Gross demand units",
        )
        axis.grid(axis="y", alpha=0.25)
        axis.legend(fontsize=9)
        axis.set_ylim(bottom=0)
        _save(figure, output, PLOT_FILENAMES[1])

        interval_rows = {row["model"]: row for row in intervals["overall"]}
        figure, axes = plt.subplots(1, 2, figsize=(15, 6), layout="constrained")
        axes[0].bar(
            positions - 0.2,
            [interval_rows[model]["coverage"] * 100 for model in models],
            width=0.38,
            color="#0072B2",
            label="Measured final-test coverage",
        )
        axes[0].bar(
            positions + 0.2,
            [interval_rows[model]["nominal_coverage"] * 100 for model in models],
            width=0.38,
            color="#888888",
            label="Requested nominal coverage",
        )
        axes[0].set(
            title="Empirical coverage versus nominal level",
            ylabel="Covered product-week observations (%)",
            ylim=(0, 105),
        )
        axes[0].legend(fontsize=8)
        axes[1].bar(
            positions,
            [interval_rows[model]["mean_width"] for model in models],
            width=0.65,
            color="#009E73",
        )
        axes[1].set(
            title="Average final-test interval width",
            ylabel="Mean width (demand units)",
        )
        for axis in axes:
            axis.set_xticks(
                positions,
                [_tick_label(model) for model in models],
                ha="center",
                fontsize=9,
            )
            axis.grid(axis="y", alpha=0.25)
            axis.set_axisbelow(True)
        figure.suptitle(
            "Retrospective uncertainty evaluation · no future coverage guarantee",
            fontsize=15,
        )
        _save(figure, output, PLOT_FILENAMES[2])

        top = importance_rows[:20]
        figure, axis = plt.subplots(
            figsize=(12, max(5, len(top) * 0.32 + 2)), layout="constrained"
        )
        if top:
            axis.barh(
                np.arange(len(top)), [row["importance"] for row in top], color="#0072B2"
            )
            axis.set_yticks(
                np.arange(len(top)), [row["feature"] for row in top], fontsize=9
            )
            axis.invert_yaxis()
            axis.set(
                xlabel="Native importance magnitude (not a causal effect)",
                title=f"{_label(selected_model)} · native feature importance\nMethod: {top[0]['method']} · up to 20 largest measured values",
            )
            axis.grid(axis="x", alpha=0.25)
            axis.set_axisbelow(True)
        else:
            axis.text(
                0.5,
                0.5,
                "Native feature importance is unavailable for this model.",
                ha="center",
                va="center",
                transform=axis.transAxes,
            )
            axis.set_title(f"{_label(selected_model)} · feature importance unavailable")
            axis.set_axis_off()
        _save(figure, output, PLOT_FILENAMES[3])
    return list(PLOT_FILENAMES)
