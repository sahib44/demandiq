"""Reject mismatched operation lineage using isolated synthetic files only.

No database, official artifacts, model loading, training, final evaluation or
simulation is used. Dependency spies fail if rejected inputs reach calculation.
"""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.core.config import Settings
from backend.app.db.models import ForecastBatch, TrainingRun
from backend.app.services import operations
from ml.data.acquisition import sha256_file
from ml.pipelines.ingestion import ArtifactError

DATASET = "a" * 64
OTHER = "b" * 64
RUN = "c" * 64
FORECAST = "d" * 64


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts")


def synthetic_ingestion(settings, *, dataset_id=DATASET, source_sha256=OTHER):
    manifest = {
        "dataset_id": dataset_id,
        "source_sha256": source_sha256,
        "cleaning_version": "synthetic-v1",
        "original_rows": 0,
        "cleaned_rows": 0,
        "config": {},
        "artifacts": {},
        "artifact_dir": dataset_id,
    }
    return SimpleNamespace(
        dataset_dir=settings.data_dir / "processed" / dataset_id,
        manifest=manifest,
        report={"original_rows": 0, "cleaned_rows": 0},
    )


def forbid_registration(monkeypatch):
    catalog = Mock(side_effect=AssertionError("Rejected input reached catalog loading"))
    validation = Mock(side_effect=AssertionError("Rejected input reached registration"))
    monkeypatch.setattr(operations, "product_catalog", catalog)
    monkeypatch.setattr(operations, "_validated_payload", validation)
    return catalog, validation


def allow_registration(monkeypatch, result):
    monkeypatch.setattr(operations, "product_catalog", lambda _: [])
    monkeypatch.setattr(
        operations,
        "_validated_payload",
        lambda manifest, report, catalog: (manifest, report, catalog),
    )


def test_existing_dataset_must_match_requested_identity_before_catalog_loading(
    monkeypatch, settings
):
    result = synthetic_ingestion(settings, dataset_id=OTHER)
    verify = Mock(return_value=result)
    monkeypatch.setattr(operations, "verify_dataset", verify)
    catalog, validation = forbid_registration(monkeypatch)
    with pytest.raises(ArtifactError, match="Requested dataset identity"):
        operations._dataset(settings, {"source": "existing", "dataset_id": DATASET})
    verify.assert_called_once_with(settings.data_dir / "processed" / DATASET)
    catalog.assert_not_called()
    validation.assert_not_called()


def test_matching_existing_dataset_preserves_requested_identity(monkeypatch, settings):
    result = synthetic_ingestion(settings)
    monkeypatch.setattr(operations, "verify_dataset", lambda _: result)
    allow_registration(monkeypatch, result)
    prepared = operations._dataset(
        settings, {"source": "existing", "dataset_id": DATASET}
    )
    assert prepared.result == {"dataset_id": DATASET, "cleaned_rows": 0, "products": 0}


def test_existing_training_request_cannot_follow_an_alias_to_another_run(
    monkeypatch, settings
):
    phase3 = settings.artifact_dir / "phase3"
    target = phase3 / OTHER
    target.mkdir(parents=True)
    (phase3 / RUN).symlink_to(target, target_is_directory=True)
    modeling = ModuleType("ml.pipelines.modeling")
    modeling.TRAIN_REQUIRED = {"plan.json"}
    modeling.train_phase3 = Mock(side_effect=AssertionError("Existing run retrained"))
    monkeypatch.setitem(sys.modules, "ml.pipelines.modeling", modeling)
    verify = Mock(
        return_value={
            "experiment_id": OTHER,
            "dataset_id": DATASET,
            "state": "frozen_pretest",
        }
    )
    monkeypatch.setattr(operations, "verify_run", verify)
    parquet = Mock(side_effect=AssertionError("Mismatched run read analytical rows"))
    monkeypatch.setattr(operations.pd, "read_parquet", parquet)
    with pytest.raises(ArtifactError, match="Requested training identity"):
        operations._training(
            settings, {"mode": "existing", "dataset_id": DATASET, "run_id": RUN}
        )
    assert verify.call_args.args[0] == target.resolve()
    modeling.train_phase3.assert_not_called()
    parquet.assert_not_called()


def test_training_directory_name_must_match_verified_run(monkeypatch, settings):
    modeling = ModuleType("ml.pipelines.modeling")
    modeling.TRAIN_REQUIRED = {"plan.json"}
    modeling.train_phase3 = Mock(side_effect=AssertionError("Existing run retrained"))
    monkeypatch.setitem(sys.modules, "ml.pipelines.modeling", modeling)
    # Simulate a resolver returning an incorrectly named local directory while
    # the request and manifest IDs agree; the directory guard is independent.
    monkeypatch.setattr(
        operations, "bounded_path", lambda *_: settings.artifact_dir / OTHER
    )
    monkeypatch.setattr(
        operations, "verify_run", lambda *_, **__: {"experiment_id": RUN}
    )
    with pytest.raises(ArtifactError, match="directory does not match its identity"):
        operations._training(
            settings, {"mode": "existing", "dataset_id": DATASET, "run_id": RUN}
        )


def test_file_source_replacement_between_precheck_and_ingest_is_rejected(
    monkeypatch, settings
):
    raw = settings.data_dir / "raw"
    raw.mkdir(parents=True)
    path = raw / "synthetic.csv"
    path.write_text("synthetic original content", encoding="utf-8")
    queued_digest = sha256_file(path)
    calls = []

    def ingest_replacement(input_path, output_root):
        assert input_path == path
        assert output_root == settings.data_dir / "processed"
        # The old preflight succeeded; a stable replacement is then ingested.
        path.write_text("synthetic replacement content", encoding="utf-8")
        calls.append(input_path)
        return synthetic_ingestion(settings, source_sha256=sha256_file(path))

    monkeypatch.setattr(operations, "ingest_dataset", ingest_replacement)
    catalog, validation = forbid_registration(monkeypatch)
    with pytest.raises(
        ArtifactError, match="Ingested source differs from the queued checksum"
    ):
        operations._dataset(
            settings,
            {
                "source": "file",
                "input_file": path.name,
                "expected_sha256": queued_digest,
            },
        )
    assert calls == [path]
    assert sha256_file(path) != queued_digest
    catalog.assert_not_called()
    validation.assert_not_called()


def test_file_changed_before_ingestion_never_calls_pipeline(monkeypatch, settings):
    raw = settings.data_dir / "raw"
    raw.mkdir(parents=True)
    path = raw / "synthetic.csv"
    path.write_text("synthetic changed content", encoding="utf-8")
    ingest = Mock(side_effect=AssertionError("Changed source reached ingestion"))
    monkeypatch.setattr(operations, "ingest_dataset", ingest)
    with pytest.raises(ArtifactError, match="Queued input changed after submission"):
        operations._dataset(
            settings,
            {"source": "file", "input_file": path.name, "expected_sha256": OTHER},
        )
    ingest.assert_not_called()


def test_stable_file_checksum_is_accepted(monkeypatch, settings):
    path = settings.data_dir / "raw" / "synthetic.csv"
    path.parent.mkdir(parents=True)
    path.write_text("synthetic stable content", encoding="utf-8")
    digest = sha256_file(path)
    result = synthetic_ingestion(settings, source_sha256=digest)
    monkeypatch.setattr(operations, "ingest_dataset", lambda *_: result)
    allow_registration(monkeypatch, result)
    prepared = operations._dataset(
        settings, {"source": "file", "input_file": path.name, "expected_sha256": digest}
    )
    assert prepared.result["dataset_id"] == DATASET


def test_official_archive_checksum_is_not_compared_to_workbook_checksum(
    monkeypatch, settings
):
    workbook = settings.data_dir / "raw" / "synthetic.xlsx"
    archive_digest = "e" * 64
    result = synthetic_ingestion(settings, source_sha256="f" * 64)
    download = Mock(return_value=SimpleNamespace(workbook_path=workbook))
    ingest = Mock(return_value=result)
    monkeypatch.setattr(operations, "download_official", download)
    monkeypatch.setattr(operations, "ingest_dataset", ingest)
    allow_registration(monkeypatch, result)
    prepared = operations._dataset(
        settings, {"source": "official", "expected_sha256": archive_digest}
    )
    assert prepared.result["dataset_id"] == DATASET
    download.assert_called_once_with(
        settings.data_dir / "raw", expected_archive_sha256=archive_digest
    )
    ingest.assert_called_once_with(workbook, settings.data_dir / "processed")


class SimulationReached(Exception):
    """Stop a positive guard test before any simulation or analytical I/O."""


@pytest.fixture
def inventory_context(monkeypatch, settings):
    source = settings.artifact_dir / "phase3" / RUN
    source.mkdir(parents=True)
    manifest = source / "manifest.json"
    manifest.write_text("synthetic registered training bytes", encoding="utf-8")
    directory = settings.artifact_dir / "backend" / "forecasts" / FORECAST
    metadata = {
        "forecast_id": FORECAST,
        "run_id": RUN,
        "scope": "retrospective",
        "source": {"training_manifest_sha256": sha256_file(manifest)},
    }
    forecast = SimpleNamespace(
        forecast_id=FORECAST,
        run_id=RUN,
        scope="retrospective",
        artifact_dir=directory.relative_to(settings.artifact_dir).as_posix(),
        metadata_json=metadata,
    )
    run = SimpleNamespace(
        run_id=RUN,
        artifact_dir=source.relative_to(settings.artifact_dir).as_posix(),
        manifest_sha256=sha256_file(manifest),
    )
    rows = {(ForecastBatch, FORECAST): forecast, (TrainingRun, RUN): run}
    gets = []

    class FakeSession:
        def __init__(self, engine):
            assert engine is None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get(self, model, identifier):
            assert (model, identifier) in rows
            gets.append((model, identifier))
            return rows[(model, identifier)]

    monkeypatch.setattr(operations, "Session", FakeSession)
    forecasting = ModuleType("backend.app.services.forecasting")
    forecasting.prepare_forecast = Mock(
        return_value=(FORECAST, directory, metadata, None)
    )
    monkeypatch.setitem(sys.modules, "backend.app.services.forecasting", forecasting)
    inventory = ModuleType("ml.pipelines.inventory")
    inventory.run_inventory_scenario = Mock(side_effect=SimulationReached)
    monkeypatch.setitem(sys.modules, "ml.pipelines.inventory", inventory)
    parquet = Mock(side_effect=AssertionError("Preflight read simulation rows"))
    monkeypatch.setattr(operations.pd, "read_parquet", parquet)
    return SimpleNamespace(
        settings=settings,
        source=source,
        manifest=manifest,
        directory=directory,
        metadata=metadata,
        forecast=forecast,
        run=run,
        rows=rows,
        gets=gets,
        prepare=forecasting.prepare_forecast,
        simulate=inventory.run_inventory_scenario,
        parquet=parquet,
    )


def inventory_operation(context):
    return operations._inventory(
        context.settings, None, {"forecast_id": FORECAST, "config": {}}
    )


@pytest.mark.parametrize("missing", ["forecast", "training"])
def test_inventory_missing_registered_parent_never_prepares_or_simulates(
    inventory_context, missing
):
    context = inventory_context
    key = (ForecastBatch, FORECAST) if missing == "forecast" else (TrainingRun, RUN)
    context.rows[key] = None
    error = ValueError if missing == "forecast" else ArtifactError
    message = (
        "Completed retrospective forecast"
        if missing == "forecast"
        else "Registered training artifacts"
    )
    with pytest.raises(error, match=message):
        inventory_operation(context)
    context.prepare.assert_not_called()
    context.simulate.assert_not_called()
    context.parquet.assert_not_called()


def test_inventory_one_week_forecast_never_prepares_or_simulates(inventory_context):
    context = inventory_context
    context.forecast.scope = "one_week"
    with pytest.raises(ValueError, match="Completed retrospective forecast"):
        inventory_operation(context)
    context.prepare.assert_not_called()
    context.simulate.assert_not_called()
    assert context.gets == [(ForecastBatch, FORECAST)]


def test_inventory_rejects_changed_registered_training_manifest_before_forecast_loading(
    inventory_context,
):
    context = inventory_context
    context.manifest.write_text(
        "synthetic replacement training bytes", encoding="utf-8"
    )
    with pytest.raises(
        ArtifactError, match="Registered training artifacts have changed"
    ):
        inventory_operation(context)
    context.prepare.assert_not_called()
    context.simulate.assert_not_called()
    context.parquet.assert_not_called()


@pytest.mark.parametrize(
    "mismatch", ["identifier", "directory", "metadata", "source_hash"]
)
def test_inventory_rejects_forecast_lineage_mismatch_before_simulation(
    inventory_context, mismatch
):
    context = inventory_context
    returned_id, returned_dir, returned_metadata = (
        FORECAST,
        context.directory,
        context.metadata,
    )
    if mismatch == "identifier":
        returned_id = OTHER
    elif mismatch == "directory":
        returned_dir = context.settings.artifact_dir / "backend" / "forecasts" / OTHER
    elif mismatch == "metadata":
        returned_metadata = context.metadata | {"selected_ml_family": "different"}
    else:
        returned_metadata = context.metadata | {
            "source": {"training_manifest_sha256": OTHER}
        }
    context.prepare.return_value = (returned_id, returned_dir, returned_metadata, None)
    with pytest.raises(
        ArtifactError,
        match="Requested forecast does not match the frozen simulation inputs",
    ):
        inventory_operation(context)
    context.prepare.assert_called_once_with(context.settings, RUN, "retrospective")
    context.simulate.assert_not_called()
    context.parquet.assert_not_called()


def test_inventory_matching_registered_lineage_reaches_only_expected_frozen_source(
    inventory_context,
):
    context = inventory_context
    with pytest.raises(SimulationReached):
        inventory_operation(context)
    context.prepare.assert_called_once_with(context.settings, RUN, "retrospective")
    args, kwargs = context.simulate.call_args
    assert args == (context.source,)
    assert kwargs["output_root"] == context.settings.artifact_dir / "phase4"
    assert kwargs["ledger_root"] == context.settings.ledger_dir
    assert kwargs["config"].currency == "GBP"
    context.parquet.assert_not_called()


def test_inventory_propagates_forecast_integrity_failure_without_simulation(
    inventory_context,
):
    context = inventory_context
    context.prepare.side_effect = ArtifactError(
        "Synthetic frozen forecast integrity failure"
    )
    with pytest.raises(ArtifactError, match="frozen forecast integrity"):
        inventory_operation(context)
    context.simulate.assert_not_called()
    context.parquet.assert_not_called()
