"""Synthetic temporary rendering fixtures, never presented as model performance."""

from copy import deepcopy

import pandas as pd
import pytest
from PIL import Image

from ml.evaluation.metrics import evaluate_predictions
from ml.evaluation.model_plots import PLOT_FILENAMES, render_model_plots
from ml.evaluation.uncertainty import add_intervals, calibrate_intervals


def plot_fixture():
    models = [
        "naive",
        "moving_average_4",
        "seasonal_naive_4",
        "ridge",
        "hist_gradient_boosting",
        "xgboost",
    ]
    rows = []
    calibration_rows = []
    for index, model in enumerate(models):
        offset = index - 2
        for code in ["SYNTH-A", "SYNTH-B"]:
            for week, actual in [("2011-09-12", 10), ("2011-09-19", 15)]:
                calibration_rows.append(
                    {
                        "stock_code": code,
                        "model": model,
                        "week": week,
                        "actual": actual,
                        "prediction": actual + offset,
                        "scale": 10,
                    }
                )
            for week, actual in [("2011-10-10", 12), ("2011-10-17", 18)]:
                rows.append(
                    {
                        "fold": "test",
                        "stock_code": code,
                        "model": model,
                        "week": week,
                        "actual": actual,
                        "prediction": actual + offset,
                        "scale": 10,
                    }
                )
    bounded = add_intervals(
        pd.DataFrame(rows), calibrate_intervals(pd.DataFrame(calibration_rows))
    )
    volumes = pd.DataFrame(
        {
            "fold": "test",
            "stock_code": ["SYNTH-A", "SYNTH-B"],
            "training_units": [200, 100],
        }
    )
    test_metrics = evaluate_predictions(bounded, training_volumes=volumes)
    test_metrics["evaluation_scope"] = "test"
    validation = pd.DataFrame(rows)
    validation["week"] = validation.week.map(
        {"2011-10-10": "2011-08-01", "2011-10-17": "2011-08-08"}
    )
    validation["fold"] = "selection"
    validation["prediction"] += 1
    validation_metrics = evaluate_predictions(
        validation, training_volumes=volumes.assign(fold="selection")
    )
    importance = [
        {
            "feature": "lag_1",
            "importance": 0.6,
            "method": "native tree gain (synthetic rendering fixture)",
        },
        {
            "feature": "rolling_mean_4",
            "importance": 0.4,
            "method": "native tree gain (synthetic rendering fixture)",
        },
    ]
    return bounded, test_metrics, validation_metrics, importance


def test_model_figures_are_reproducible_valid_bounded_pngs(tmp_path):
    predictions, test_metrics, validation_metrics, importance = plot_fixture()
    first, second = tmp_path / "first", tmp_path / "second"
    files = render_model_plots(
        predictions,
        test_metrics,
        validation_metrics,
        importance,
        first,
        selected_model="xgboost",
        selected_product="SYNTH-A",
    )
    assert files == list(PLOT_FILENAMES)
    assert (
        render_model_plots(
            predictions,
            test_metrics,
            validation_metrics,
            importance,
            second,
            selected_model="xgboost",
            selected_product="SYNTH-A",
        )
        == files
    )
    for filename in files:
        contents = (first / filename).read_bytes()
        assert contents == (second / filename).read_bytes()
        assert 1000 < len(contents) < 1_000_000
        with Image.open(first / filename) as image:
            assert image.format == "PNG"
            assert 600 <= image.width <= 2500
            assert 400 <= image.height <= 2000
            assert image.info["Software"] == "DemandIQ Phase 3 evaluation"


@pytest.mark.parametrize(
    "change,match",
    [
        ("scope", "explicitly identify"),
        ("metrics", "do not match"),
        ("importance", "explicit method"),
        ("coverage", "nominal_coverage"),
    ],
)
def test_model_figures_refuse_mislabeled_or_unrelated_inputs_before_writing(
    tmp_path, change, match
):
    predictions, test_metrics, validation_metrics, importance = plot_fixture()
    if change == "scope":
        test_metrics["evaluation_scope"] = "validation"
    elif change == "metrics":
        test_metrics = deepcopy(test_metrics)
        test_metrics["overall"][0]["mae"] = 99999
    elif change == "importance":
        importance = [{"feature": "lag_1", "importance": 1}]
    else:
        predictions = predictions.drop(columns="nominal_coverage")
    with pytest.raises(ValueError, match=match):
        render_model_plots(
            predictions,
            test_metrics,
            validation_metrics,
            importance,
            tmp_path / "invalid",
            selected_model="xgboost",
            selected_product="SYNTH-A",
        )
    assert not (tmp_path / "invalid").exists()
