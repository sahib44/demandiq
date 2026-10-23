"""Temporary synthetic fixtures test PNG rendering, never performance evidence."""

from copy import deepcopy

import pandas as pd
import pytest
from PIL import Image

from ml.evaluation import plots
from ml.evaluation.metrics import evaluate_predictions
from ml.evaluation.plots import PLOT_FILENAMES, render_phase2_plots


def plotting_fixture():
    predictions = pd.DataFrame(
        [
            {
                "fold": fold,
                "stock_code": code,
                "week": week,
                "actual": actual,
                "prediction": max(0, actual + offset),
                "model": model,
            }
            for fold, week, actual in [
                ("fold_1", "2011-01-03", 4),
                ("fold_1", "2011-01-10", 7),
                ("fold_2", "2011-01-17", 2),
            ]
            for code in ["SYNTH-A", "SYNTH-B"]
            for model, offset in [
                ("naive", 1),
                ("moving_average_4", -1),
                ("seasonal_naive_4", 2),
            ]
        ]
    )
    volumes = pd.DataFrame(
        [
            {"fold": fold, "stock_code": code, "training_units": units}
            for fold in ["fold_1", "fold_2"]
            for code, units in [("SYNTH-A", 8), ("SYNTH-B", 4)]
        ]
    )
    return predictions, evaluate_predictions(predictions, training_volumes=volumes)


def test_rendered_figures_are_bounded_valid_pngs_and_reproducible(tmp_path):
    predictions, metrics = plotting_fixture()
    first = tmp_path / "first"
    second = tmp_path / "second"
    filenames = render_phase2_plots(predictions, metrics, first)
    assert filenames == list(PLOT_FILENAMES)
    assert plots.matplotlib.get_backend().lower() == "agg"
    assert render_phase2_plots(predictions, metrics, second) == filenames
    for filename in filenames:
        contents = (first / filename).read_bytes()
        assert contents == (second / filename).read_bytes()
        assert contents.startswith(b"\x89PNG\r\n\x1a\n")
        assert 1000 < len(contents) < 1_000_000
        with Image.open(first / filename) as image:
            assert image.format == "PNG"
            assert 500 <= image.width <= 2500
            assert 400 <= image.height <= 2000
            assert "date" not in {key.lower() for key in image.info}


def test_figures_refuse_unrelated_metrics_before_writing(tmp_path):
    predictions, metrics = plotting_fixture()
    modified = deepcopy(metrics)
    modified["overall"][0]["mae"] = 123456
    with pytest.raises(ValueError, match="do not match"):
        render_phase2_plots(predictions, modified, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    with pytest.raises(ValueError, match="validation metrics"):
        render_phase2_plots(
            predictions, {"evaluation_scope": "test"}, tmp_path / "test"
        )
