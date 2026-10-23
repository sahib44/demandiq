"""Synthetic portable-copy/ledger checks; no model fitting or final evaluation."""

import json

import pandas as pd
import pytest

from ml.data.acquisition import sha256_file
from ml.evaluation.final_test import claim_final_evaluation, complete_final_evaluation
from ml.pipelines.artifacts import inventory, write_json
from ml.pipelines.ingestion import ArtifactError, ingest_dataset
from scripts.prepare_demo_bundle import (
    _identity,
    install_bundle,
    prepare_bundle,
    verify_bundle,
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "synthetic.csv"
    pd.DataFrame(
        [
            {
                "InvoiceNo": "100",
                "StockCode": "SYNTH-A",
                "Description": "Synthetic item",
                "Quantity": 4,
                "InvoiceDate": "2024-01-01 12:00:00",
                "UnitPrice": 2.0,
                "CustomerID": "123",
                "Country": "Synthetic",
            }
        ]
    ).to_csv(path, index=False)
    dataset = ingest_dataset(path, tmp_path / "processed")
    dataset_id, run_id = dataset.manifest["dataset_id"], "a" * 64
    run = tmp_path / "phase3" / run_id
    run.mkdir(parents=True)
    plan = {
        "experiment_id": run_id,
        "dataset_id": dataset_id,
        "horizon_weeks": 1,
        "test_methods": [
            "ridge",
            "random_forest",
            "xgboost",
            "naive",
            "moving_average_4",
            "seasonal_naive_4",
        ],
        "best_ml_family": "ridge",
    }
    write_json(run / "plan.json", plan)
    write_json(run / "config.json", {})
    write_json(run / "cohort.json", [{"stock_code": "SYNTH-A"}])
    for name in ("pretest_weekly", "calibration_predictions", "pretest_forecasts"):
        # The copy workflow checks bytes/metadata and never interprets targets.
        pd.DataFrame({"synthetic_fixture": [1]}).to_parquet(run / f"{name}.parquet")
    (run / "models").mkdir()
    (run / "models/ridge.joblib").write_bytes(
        b"synthetic never-deserialized model placeholder"
    )
    digest = sha256_file(run / "plan.json")
    write_json(
        run / "manifest.json",
        {
            "dataset_id": dataset_id,
            "experiment_id": run_id,
            "plan_sha256": digest,
            "state": "frozen_pretest",
            "artifacts": inventory(run),
        },
    )
    evaluation = tmp_path / "completed" / run_id
    evaluation.mkdir(parents=True)
    pd.DataFrame({"synthetic_fixture": [1]}).to_parquet(
        evaluation / "predictions.parquet"
    )
    write_json(
        evaluation / "evaluation_metadata.json",
        {
            "dataset_id": dataset_id,
            "experiment_id": run_id,
            "plan_sha256": digest,
            "evaluation_scope": "test",
            "all_models_frozen_before_test": True,
            "test_refitting": False,
            "selected_before_test": "ridge",
        },
    )
    write_json(evaluation / "metrics.json", {"evaluation_scope": "test"})
    write_json(evaluation / "interval_metrics.json", {"scope": "test"})
    write_json(
        evaluation / "manifest.json",
        {
            "dataset_id": dataset_id,
            "experiment_id": run_id,
            "plan_sha256": digest,
            "evaluation_scope": "test",
            "artifacts": inventory(evaluation),
        },
    )
    ledger = tmp_path / "source-ledger"
    claim_final_evaluation(ledger, dataset_id, run_id, digest)
    complete_final_evaluation(
        ledger,
        dataset_id,
        run_id,
        digest,
        results_dir=evaluation,
        results_manifest_sha256=sha256_file(evaluation / "manifest.json"),
    )
    return dataset.dataset_dir, run, ledger, tmp_path / "bundle", tmp_path / "runtime"


def prepare(source):
    dataset, run, ledger, output, runtime = source
    return prepare_bundle(dataset, run, ledger, output, runtime_root=str(runtime))


def test_bundle_preserves_sources_and_changes_only_copied_absolute_path(source):
    dataset, run, ledger, output, runtime = source
    before = {str(root): inventory(root) for root in (dataset, run, ledger)}
    manifest = prepare(source)
    assert before == {str(root): inventory(root) for root in (dataset, run, ledger)}
    original = ledger / f"{manifest['dataset_id']}.json"
    archived = output / "provenance/original-ledger" / original.name
    copied = output / "data/evaluation-ledger" / original.name
    assert original.read_bytes() == archived.read_bytes()
    old, new = json.loads(original.read_text()), json.loads(copied.read_text())
    assert [name for name in old if old[name] != new[name]] == ["results_dir"]
    assert new["results_dir"] == str(
        runtime / "artifacts/phase3/evaluations" / manifest["run_id"]
    )
    assert new["status"] == "complete"
    assert manifest["ledger_relocation"]["original_sha256"] == sha256_file(original)
    assert manifest["ledger_relocation"]["copied_sha256"] == sha256_file(copied)
    assert verify_bundle(output) == manifest


def test_bundle_preparation_and_install_are_idempotent(source):
    _, _, _, output, runtime = source
    first = prepare(source)
    assert prepare(source) == first
    assert install_bundle(output, runtime) == {
        "status": "installed",
        "bundle_id": first["bundle_id"],
    }
    assert install_bundle(output, runtime)["bundle_id"] == first["bundle_id"]
    assert (
        runtime / "artifacts/demo-bundles" / first["bundle_id"] / "original-ledger.json"
    ).exists()


def test_output_must_be_separate_from_protected_sources(source):
    dataset, run, ledger, _, _ = source
    with pytest.raises(ValueError, match="separate"):
        prepare_bundle(dataset, run, ledger, run / "nested-bundle")


def test_tampered_bundle_fails_before_installation(source):
    _, _, _, output, runtime = source
    prepare(source)
    (output / "artifacts/phase3" / ("a" * 64) / "models/ridge.joblib").write_bytes(
        b"tampered"
    )
    with pytest.raises(ArtifactError, match="integrity"):
        install_bundle(output, runtime)
    assert not runtime.exists()


def test_recomputed_inventory_cannot_hide_other_ledger_changes(source):
    _, _, _, output, _ = source
    manifest = prepare(source)
    copied = output / "data/evaluation-ledger" / f"{manifest['dataset_id']}.json"
    ledger = json.loads(copied.read_text())
    ledger["completed_at"] = "2099-01-01T00:00:00.000000Z"
    write_json(copied, ledger)
    manifest["ledger_relocation"]["changed_fields"] = ["completed_at", "results_dir"]
    manifest["ledger_relocation"]["copied_sha256"] = sha256_file(copied)
    manifest["artifacts"] = inventory(output)
    manifest["bundle_id"] = _identity(manifest)
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ArtifactError, match="provenance"):
        verify_bundle(output)


def test_existing_runtime_ledger_is_never_overwritten(source):
    _, _, _, output, runtime = source
    manifest = prepare(source)
    path = runtime / "data/evaluation-ledger" / f"{manifest['dataset_id']}.json"
    path.parent.mkdir(parents=True)
    path.write_text("preserve this prior ledger")
    with pytest.raises(ArtifactError, match="different evaluation ledger"):
        install_bundle(output, runtime)
    assert path.read_text() == "preserve this prior ledger"


def test_existing_runtime_artifact_is_never_overwritten(source):
    _, _, _, output, runtime = source
    manifest = prepare(source)
    install_bundle(output, runtime)
    path = runtime / "artifacts/phase3" / manifest["run_id"] / "models/ridge.joblib"
    path.write_bytes(b"preserve changed runtime model")
    with pytest.raises(ArtifactError, match="different frozen artifacts"):
        install_bundle(output, runtime)
    assert path.read_bytes() == b"preserve changed runtime model"


def test_different_runtime_path_cannot_silently_relocate_again(source):
    _, _, _, output, runtime = source
    prepare(source)
    with pytest.raises(ArtifactError, match="mount path differs"):
        install_bundle(output, runtime.parent / "different-runtime")


def test_empty_application_start_does_not_require_demo_bundle(tmp_path):
    runtime = tmp_path / "runtime"
    assert install_bundle(tmp_path / "missing", runtime, if_present=True) == {
        "status": "empty_runtime",
        "bundle_id": None,
    }
    assert (runtime / "data").is_dir() and (runtime / "artifacts").is_dir()


def test_partial_bundle_is_not_treated_as_an_empty_optional_bundle(tmp_path):
    bundle = tmp_path / "incomplete"
    bundle.mkdir()
    (bundle / "partial.txt").write_text("partial")
    with pytest.raises(ArtifactError, match="missing or unreadable"):
        install_bundle(bundle, tmp_path / "runtime", if_present=True)


def test_runtime_root_symlink_is_rejected_before_directory_creation(tmp_path):
    target = tmp_path / "protected"
    target.mkdir()
    link = tmp_path / "runtime"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ArtifactError, match="Runtime root cannot be a symlink"):
        install_bundle(tmp_path / "missing", link, if_present=True)
    assert list(target.iterdir()) == []


def test_symlink_inputs_are_rejected(source):
    dataset, run, ledger, output, _ = source
    link = run / "escape"
    link.symlink_to(dataset / "purchases.parquet")
    with pytest.raises(ArtifactError, match="symlinks"):
        prepare_bundle(dataset, run, ledger, output)


@pytest.mark.parametrize(
    "runtime",
    ["relative", "/", "/runtime/../outside", "/runtime/", "/runtime\\outside"],
)
def test_runtime_path_must_be_explicit_and_normalized(source, runtime):
    dataset, run, ledger, output, _ = source
    with pytest.raises(ValueError, match="absolute POSIX"):
        prepare_bundle(dataset, run, ledger, output, runtime_root=runtime)


@pytest.mark.parametrize("uid", [0, -1, True, 2**31, "10001"])
def test_runtime_uid_is_validated_before_writes(tmp_path, uid):
    with pytest.raises(ValueError, match="user ID"):
        install_bundle(
            tmp_path / "missing", tmp_path / "runtime", if_present=True, uid=uid
        )
    assert not (tmp_path / "runtime").exists()
