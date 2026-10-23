"""Service/worker/API integration on synthetic transactions and isolated PostgreSQL.

This module never reads or reevaluates the official UCI forecasting test.
"""

import csv
import io
import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import (
    Dataset,
    ForecastValue,
    InventoryConfiguration,
    Job,
    ModelArtifact,
    SimulationResult,
    TrainingRun,
    WeeklyDemand,
)
from backend.app.db.repository import postgres_url
from backend.app.db.session import make_engine
from backend.app.main import create_app
from backend.app.services.application import ApplicationService, _csv, bounded_path
from backend.app.services.errors import ServiceError
from backend.app.services.operations import _records
from ml.pipelines.ingestion import ArtifactError


def test_settings_environment_and_safe_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost/local")
    monkeypatch.setenv("DEMANDIQ_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOB_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("MAX_REQUEST_BYTES", "2048")
    settings = Settings.from_env()
    settings.ensure_directories()
    assert settings.max_attempts == 2 and settings.max_request_bytes == 2048
    assert settings.data_dir.is_dir()
    assert "secret" not in json.dumps(settings.safe_config())
    assert "localhost" not in json.dumps(settings.safe_config())


@pytest.mark.parametrize(
    "changes",
    [
        {"max_attempts": True},
        {"max_attempts": 6},
        {"lease_seconds": 2},
        {"poll_seconds": float("nan")},
        {"cors_origins": ("bad",)},
        {"max_request_bytes": 0},
    ],
)
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        Settings(**changes)


def test_paths_reject_traversal_and_symlinks(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(tmp_path)
    for value in (
        "..",
        "../outside.csv",
        "link/outside.csv",
        str(tmp_path / "outside.csv"),
    ):
        with pytest.raises(ServiceError):
            bounded_path(root, value)
    assert bounded_path(root, "inside.csv") == root / "inside.csv"


def test_csv_escapes_formula_cells_and_keeps_numeric_negatives():
    rows = list(
        csv.DictReader(
            io.StringIO(
                _csv(
                    [{"stock_code": "=BAD()", "net": -2, "description": "+text"}]
                ).decode()
            )
        )
    )
    assert rows == [{"stock_code": "'=BAD()", "net": "-2", "description": "'+text"}]


def test_records_preserve_float_precision_and_missing_values():
    import pandas as pd

    x = 1.2345678901234567
    assert _records(pd.DataFrame({"v": [x, float("nan")]})) == [{"v": x}, {"v": None}]


@pytest.fixture(scope="module")
def analytical(tmp_path_factory):
    from ml.tests.test_modeling_pipeline import config, make_source

    root = tmp_path_factory.mktemp("backend-analytical")
    source = make_source(root)
    processed = root / "data" / "processed"
    processed.mkdir(parents=True)
    source = source.rename(processed / source.name)
    return root, source, config()


@pytest.fixture
def application_db(monkeypatch, tmp_path):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL absent: PostgreSQL service integration not run")
    if not postgres_url(url).database.endswith("_test"):
        pytest.fail("Refusing non-test database")
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    engine = make_engine(url)

    def clear():
        with engine.begin() as connection:
            connection.execute(delete(Job))
            connection.execute(delete(Dataset))
            connection.execute(delete(InventoryConfiguration))

    clear()
    try:
        yield engine, url
    finally:
        clear()
        engine.dispose()


@pytest.mark.integration
def test_http_worker_persistence_forecasts_inventory_and_exports(
    application_db, analytical
):
    from backend.app.worker import run_once
    from ml.data.acquisition import sha256_file
    from ml.pipelines.modeling import evaluate_phase3

    root, source, configuration = analytical
    engine, url = application_db
    settings = Settings(
        database_url=url, data_dir=root / "data", artifact_dir=root / "artifacts"
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.get("/ready").status_code == 200

        def submit(path, payload, key=None):
            response = client.post(
                path, json=payload, headers={"Idempotency-Key": key} if key else {}
            )
            assert response.status_code == 202, response.text
            assert run_once(settings, engine)
            status = client.get(response.headers["location"]).json()
            assert status["status"] == "succeeded", status
            return status["result"], response.json()["job_id"]

        dataset, dataset_job = submit(
            "/datasets/import", {"source": "existing", "dataset_id": source.name}
        )
        assert dataset["products"] == 3
        assert client.get(f"/datasets/{source.name}/quality").status_code == 200
        trained, _ = submit(
            "/training-runs",
            {"dataset_id": source.name, "config": configuration.to_dict()},
        )
        run_id = trained["run_id"]
        assert trained["models"] == 3 and trained["weekly_rows"] == 44
        assert len(client.get("/models").json()) == 3
        history = client.get(
            "/products/SYNTH-A/history",
            params={"dataset_id": source.name, "run_id": run_id, "limit": 5},
        ).json()
        assert history["total"] == 22 and len(history["rows"]) == 5
        assert max(row["week"] for row in history["rows"]) < "2011-06-06"
        one_week, _ = submit("/forecasts", {"run_id": run_id})
        values = client.get(f"/forecasts/{one_week['forecast_id']}/values").json()
        assert values["total"] == 12
        assert all(row["actual"] is None for row in values["rows"])
        assert {row["week"] for row in values["rows"]} == {"2011-06-06"}
        assert (
            client.post(
                "/inventory/scenarios", json={"forecast_id": one_week["forecast_id"]}
            ).status_code
            == 422
        )
        # Synthetic final evaluation only; official ledger is never referenced.
        run_dir = settings.artifact_dir / "phase3" / run_id
        evaluate_phase3(run_dir, source, ledger_root=settings.ledger_dir)
        protected = {
            str(p): sha256_file(p)
            for parent in (run_dir, settings.ledger_dir)
            for p in parent.rglob("*")
            if p.is_file()
        }
        retro, _ = submit("/forecasts", {"run_id": run_id, "scope": "retrospective"})
        assert retro["rows"] == 48
        scenario, _ = submit(
            "/inventory/scenarios", {"forecast_id": retro["forecast_id"]}
        )
        scenario_id = scenario["scenario_id"]
        results = client.get(
            f"/inventory/scenarios/{scenario_id}/results", params={"limit": 5}
        ).json()
        assert results["total"] == 40 and len(results["rows"]) == 5
        assert all(
            row["actual"] == row["fulfilled_units"] + row["lost_units"]
            for row in results["rows"]
        )
        export = client.get(f"/inventory/scenarios/{scenario_id}/export")
        assert export.status_code == 200
        assert len(list(csv.DictReader(io.StringIO(export.text)))) == 40
        forecast_csv = client.get(f"/forecasts/{retro['forecast_id']}/export")
        assert len(list(csv.DictReader(io.StringIO(forecast_csv.text)))) == 48
        # Replays don't enqueue; a new key reuses immutable resources atomically.
        replay = client.post(
            "/datasets/import", json={"source": "existing", "dataset_id": source.name}
        ).json()
        assert replay["job_id"] == dataset_job
        assert not run_once(settings, engine)
        again, _ = submit(
            "/training-runs",
            {"dataset_id": source.name, "mode": "existing", "run_id": run_id},
            "register-again",
        )
        assert again["run_id"] == run_id
        with Session(engine) as session:
            for model, count in [
                (Dataset, 1),
                (TrainingRun, 1),
                (WeeklyDemand, 44),
                (ModelArtifact, 3),
                (ForecastValue, 60),
                (SimulationResult, 40),
            ]:
                assert session.scalar(select(func.count()).select_from(model)) == count
        assert protected == {p: sha256_file(Path(p)) for p in protected}


@pytest.mark.integration
def test_submission_checks_file_hash_scope_references_and_conflicts(
    application_db, tmp_path
):
    engine, url = application_db
    settings = Settings(
        database_url=url,
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
    )
    service = ApplicationService(settings, engine)
    raw = settings.data_dir / "raw"
    raw.mkdir(parents=True)
    path = raw / "synthetic.csv"
    path.write_text("synthetic test fixture")
    job = service.submit(
        "dataset_import",
        {"source": "file", "input_file": path.name},
        idempotency_key="file-v1",
    )
    assert job["payload"]["expected_sha256"]
    path.write_text("changed source")
    with pytest.raises(ServiceError) as exc:
        service.submit(
            "dataset_import",
            {"source": "file", "input_file": path.name},
            idempotency_key="file-v1",
        )
    assert exc.value.status_code == 409
    with pytest.raises(ServiceError) as exc:
        service.submit("training", {"dataset_id": "a" * 64})
    assert exc.value.status_code == 404
    with pytest.raises(ServiceError):
        service.submit(
            "dataset_import", {"source": "official", "expected_sha256": "0" * 64}
        )
    with pytest.raises(ServiceError):
        service.submit(
            "dataset_import", {"source": "file", "input_file": "missing.csv"}
        )
    with pytest.raises(ServiceError):
        service.submit(
            "dataset_import",
            {"source": "file", "input_file": path.name, "expected_sha256": "0" * 64},
        )
    from backend.app.services.operations import execute_operation

    with pytest.raises(ArtifactError):
        execute_operation(settings, engine, job)
