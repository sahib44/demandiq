"""Reproducible pipeline behavior and test-target isolation with synthetic input."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from ml.evaluation.splits import Phase2Config
from ml.pipelines import forecasting_foundation as pipeline
from ml.pipelines.ingestion import ArtifactError, ingest_dataset, verify_dataset


def configuration(**changes):
    return Phase2Config(
        start_week="2011-01-03",
        train_end="2011-02-21",
        validation_end="2011-03-14",
        test_end="2011-03-28",
        top_products=2,
        min_history_weeks=4,
        **changes,
    )


def dataset(tmp_path, *, heldout_units=10, suffix=""):
    weeks = pd.date_range("2011-01-03", "2011-04-04", freq="W-MON")
    rows = []
    for index, week in enumerate(weeks):
        for product, units in (("SYNTH-A", index + 2), ("SYNTH-B", 3), ("SYNTH-C", 1)):
            if week >= pd.Timestamp("2011-03-21"):
                units = heldout_units
            rows.append(
                {
                    "InvoiceNo": f"TEST-{index}-{product}",
                    "StockCode": product,
                    "Description": "Synthetic fixture",
                    "Quantity": units,
                    "InvoiceDate": week.isoformat(),
                    "UnitPrice": 1,
                    "CustomerID": None,
                    "Country": "Testland",
                }
            )
    path = tmp_path / f"synthetic{suffix}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return ingest_dataset(path, tmp_path / "source").dataset_dir


def test_pipeline_cold_repeat_and_cache_and_all_artifacts(tmp_path, monkeypatch):
    source = dataset(tmp_path)
    config = configuration()
    first = pipeline.run_phase2(source, tmp_path / "one", config)
    second = pipeline.run_phase2(source, tmp_path / "two", config)
    assert first.manifest == second.manifest
    assert first.metrics == second.metrics
    assert first.manifest["selected_products_per_fold"] == [2, 2, 2]
    for name in first.manifest["artifacts"]:
        assert (first.run_dir / name).read_bytes() == (
            second.run_dir / name
        ).read_bytes(), name
    monkeypatch.setattr(
        pipeline,
        "_read_allowed_transactions",
        lambda *args: pytest.fail("verified cache must avoid parsing outcomes"),
    )
    cached = pipeline.run_phase2(source, tmp_path / "one", config)
    assert cached.manifest == first.manifest
    assert cached.timings["cache_reused"] == 1
    (first.run_dir / "metrics.json").write_text("{}")
    with pytest.raises(ArtifactError, match="integrity"):
        pipeline.run_phase2(source, tmp_path / "one", config)


def test_reserved_test_perturbation_cannot_change_validation(tmp_path, monkeypatch):
    source_a = dataset(tmp_path, heldout_units=10, suffix="a")
    source_b = dataset(tmp_path, heldout_units=999999, suffix="b")
    config = configuration()
    filters_seen = []
    real_read = pipeline.pd.read_parquet

    def guarded_reader(path, **kwargs):
        filters_seen.append(kwargs.get("filters"))
        assert kwargs.get("filters") == [
            ("invoice_date", ">=", pd.Timestamp(config.start_week)),
            ("invoice_date", "<", config.test_start),
        ]
        frame = real_read(path, **kwargs)
        assert (frame.invoice_date < config.test_start).all()
        return frame

    monkeypatch.setattr(pipeline.pd, "read_parquet", guarded_reader)
    a = pipeline.run_phase2(source_a, tmp_path / "runs", config)
    b = pipeline.run_phase2(source_b, tmp_path / "runs", config)
    assert len(filters_seen) == 6
    assert a.manifest["run_id"] != b.manifest["run_id"]
    assert a.metrics == b.metrics
    for name in (
        "weekly.parquet",
        "validation_predictions.parquet",
        "training_volumes.parquet",
        "selected_products.json",
        "fold_products.json",
        "features_fold_1.parquet",
        "features_fold_2.parquet",
        "features_fold_3.parquet",
    ):
        assert (a.run_dir / name).read_bytes() == (b.run_dir / name).read_bytes(), name
    predictions = real_read(a.run_dir / "validation_predictions.parquet")
    assert predictions.week.max() == pd.Timestamp(config.validation_end)
    assert predictions.groupby("model").size().eq(6).all()
    assert (
        json.loads((a.run_dir / "splits.json").read_text())["test"]["status"]
        == "reserved_unread_unevaluated"
    )


def test_failed_run_never_publishes_partial_output(tmp_path, monkeypatch):
    source = dataset(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(pipeline, "render_phase2_plots", fail)
    with pytest.raises(OSError, match="disk failure"):
        pipeline.run_phase2(source, tmp_path / "runs", configuration())
    assert list((tmp_path / "runs").iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("weekly_rows", -1),
        ("validation_prediction_rows", -1),
        ("selected_products_per_fold", []),
        ("feature_columns", []),
    ],
)
def test_cache_reconciles_manifest_metadata(tmp_path, field, value):
    source = dataset(tmp_path)
    result = pipeline.run_phase2(source, tmp_path / "runs", configuration())
    manifest = result.manifest
    manifest[field] = value
    (result.run_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ArtifactError):
        pipeline.run_phase2(source, tmp_path / "runs", configuration())


def test_missing_plots_cannot_be_hidden_by_removing_inventory(tmp_path):
    source = dataset(tmp_path)
    result = pipeline.run_phase2(source, tmp_path / "runs", configuration())
    manifest = result.manifest
    for name in list(manifest["artifacts"]):
        if name.startswith("plots/"):
            (result.run_dir / name).unlink()
            manifest["artifacts"].pop(name)
    (result.run_dir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ArtifactError, match="inventory"):
        pipeline.run_phase2(source, tmp_path / "runs", configuration())


def test_source_identity_and_complete_coverage_are_checked(tmp_path):
    source = dataset(tmp_path)
    verified = verify_dataset(source)
    assert verified.manifest["dataset_id"] == source.name
    bad_config = Phase2Config(
        start_week="2010-12-27",
        train_end="2011-02-21",
        validation_end="2011-03-14",
        test_end="2011-03-28",
        top_products=2,
        min_history_weeks=4,
    )
    with pytest.raises(ValueError, match="coverage"):
        pipeline.run_phase2(source, tmp_path / "runs", bad_config)
    manifest = dict(verified.manifest)
    manifest["source_sha256"] = "a" * 64
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ArtifactError):
        verify_dataset(source)


def test_cli_config_limit_override_and_safe_status(tmp_path):
    source = dataset(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(configuration().to_dict()))
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root), "TOP_PRODUCTS": "1"}
    args = [
        sys.executable,
        str(root / "scripts/run_phase2.py"),
        "--dataset-dir",
        str(source),
        "--config",
        str(config_path),
        "--output-dir",
        str(tmp_path / "runs"),
    ]
    result = subprocess.run(
        args, capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selected_products_per_fold"] == [1, 1, 1]
    result = subprocess.run(
        [*args, "--top-products", "2"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["selected_products_per_fold"] == [2, 2, 2]
    environment["TOP_PRODUCTS"] = "invalid"
    result = subprocess.run(
        args, capture_output=True, text=True, env=environment, check=False
    )
    assert result.returncode == 1
    assert json.loads(result.stderr)["event"] == "phase2_failed"


@pytest.mark.parametrize("invalid", [{}, [], False, 0])
def test_invalid_falsy_config_is_not_silently_defaulted(tmp_path, invalid):
    with pytest.raises(ValueError, match="config"):
        pipeline.run_phase2(tmp_path / "absent-source", tmp_path / "runs", invalid)


def test_mutated_nested_configuration_is_revalidated_before_source_read(tmp_path):
    config = configuration(seasonal_indicators={"season": [1]})
    config.seasonal_indicators["season"].append(99)
    with pytest.raises(ValueError, match="seasonal_indicators"):
        pipeline.run_phase2(tmp_path / "absent-source", tmp_path / "runs", config)
