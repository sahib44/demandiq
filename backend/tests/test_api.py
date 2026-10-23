"""HTTP contracts use synthetic services and fake engines; no database mutations."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import traceback
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app import main
from backend.app.core.config import Settings
from backend.app.core.logging import JsonFormatter
from backend.app.services import application as service_module
from backend.app.services.errors import ServiceError
from ml.data.acquisition import sha256_file
from ml.pipelines.artifacts import inventory, write_json

HASH = "a" * 64
OTHER = "b" * 64
JOB_ID = "00000000-0000-4000-8000-000000000001"
SECRET = "PRIVATE-SOURCE-AND-PASSWORD-123"


class SyntheticService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def invoke(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.failure:
            raise self.failure

    def job(self):
        return {
            "job_id": JOB_ID,
            "kind": "training",
            "status": "queued",
            "attempts": 0,
            "max_attempts": 3,
            "result": None,
            "error_code": None,
            "payload": {"private": SECRET},
            "lease_token": SECRET,
            "last_error": SECRET,
        }

    def submit(self, *args, **kwargs):
        self.invoke("submit", *args, **kwargs)
        return self.job()

    def list_resources(self, kind, **kwargs):
        self.invoke("list_resources", kind, **kwargs)
        return [self.job()] if kind == "jobs" else [{"resource": kind}]

    def get_resource(self, kind, identifier, **kwargs):
        self.invoke("get_resource", kind, identifier, **kwargs)
        return (
            self.job()
            if kind == "jobs"
            else {"resource": kind, "identifier": identifier}
        )

    def quality(self, *args):
        self.invoke("quality", *args)
        return {"original_rows": 2}

    def history(self, *args, **kwargs):
        self.invoke("history", *args, **kwargs)
        return {"rows": []}

    def training_metrics(self, *args):
        self.invoke("training_metrics", *args)
        return {"evaluation_scope": "selection_validation", "overall": []}

    def forecast_rows(self, *args, **kwargs):
        self.invoke("forecast_rows", *args, **kwargs)
        return {"rows": []}

    def scenario_results(self, *args, **kwargs):
        self.invoke("scenario_results", *args, **kwargs)
        return {"rows": []}

    def export_forecasts(self, *args):
        self.invoke("export_forecasts", *args)
        return b"stock_code,prediction\nSYNTH-A,1\n", "forecasts.csv"

    def export_scenario(self, *args, **kwargs):
        self.invoke("export_scenario", *args, **kwargs)
        return b"stock_code,order_quantity\nSYNTH-A,2\n", '../unsafe"\r\nX: bad.csv'


class FakeEngine:
    def __init__(self, revision="0002_application", failure=None):
        self.revision, self.failure, self.statements = revision, failure, []

    @contextmanager
    def connect(self):
        if self.failure:
            raise self.failure
        yield self

    def execute(self, statement):
        self.statements.append(str(statement))
        value = self.revision if "alembic_version" in str(statement) else 1
        return SimpleNamespace(scalar_one=lambda: value)


@pytest.fixture
def api(tmp_path, monkeypatch):
    service = SyntheticService()
    monkeypatch.setattr(main, "ApplicationService", lambda settings, engine: service)
    settings = Settings(
        data_dir=tmp_path / "private-data", artifact_dir=tmp_path / "private-artifacts"
    )
    application = main.create_app(settings)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("demandiq")
    logger.addHandler(handler)
    try:
        with TestClient(application, raise_server_exceptions=False) as client:
            yield SimpleNamespace(
                client=client,
                app=application,
                service=service,
                settings=settings,
                logs=output,
            )
    finally:
        logger.removeHandler(handler)


def test_health_config_docs_and_request_ids_need_no_database(api):
    response = api.client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    UUID(response.headers["x-request-id"])
    public = api.client.get("/config")
    assert public.status_code == 200
    assert public.json()["features"]["durable_jobs"] is True
    assert str(api.settings.data_dir) not in public.text
    assert "database_url" not in public.text
    assert api.client.get("/docs").status_code == 200
    schema = api.client.get("/openapi.json").json()
    assert {
        "/datasets/import",
        "/training-runs",
        "/forecasts",
        "/inventory/scenarios",
        "/jobs/{job_id}",
    }.issubset(schema["paths"])
    assert not api.service.calls
    assert api.client.get("/ready").status_code == 503


def test_create_and_startup_do_not_connect_to_database(tmp_path, monkeypatch):
    engine, service = FakeEngine(), SyntheticService()
    monkeypatch.setattr(main, "make_engine", lambda url: engine)
    monkeypatch.setattr(main, "ApplicationService", lambda settings, engine: service)
    settings = Settings(
        database_url="postgresql://user:private-password@localhost/demo",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
    )
    engine.dispose = lambda: None
    application = main.create_app(settings)
    assert not engine.statements
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert not engine.statements


def test_readiness_requires_migration_and_writable_storage(api, monkeypatch):
    engine = FakeEngine()
    api.app.state.engine = engine
    assert api.client.get("/ready").json() == {"status": "ready"}
    assert engine.statements == ["SELECT 1", "SELECT version_num FROM alembic_version"]
    assert not list(api.settings.data_dir.iterdir())
    assert not list(api.settings.artifact_dir.iterdir())
    engine.revision = "0001_data_foundation"
    assert api.client.get("/ready").status_code == 503
    api.app.state.engine = FakeEngine(failure=RuntimeError(SECRET))
    outage = api.client.get("/ready")
    assert outage.status_code == 503 and SECRET not in outage.text
    api.app.state.engine = FakeEngine()
    monkeypatch.setattr(
        main.tempfile,
        "mkstemp",
        lambda **kwargs: (_ for _ in ()).throw(PermissionError(SECRET)),
    )
    assert api.client.get("/ready").status_code == 503
    assert SECRET not in api.logs.getvalue()


@pytest.mark.parametrize(
    "path,payload,kind",
    [
        ("/datasets/import", {"dataset_id": HASH}, "dataset_import"),
        (
            "/datasets/import",
            {"source": "official", "expected_sha256": HASH},
            "dataset_import",
        ),
        (
            "/datasets/import",
            {
                "source": "file",
                "input_file": "uci-online-retail/Online Retail.xlsx",
                "expected_sha256": HASH,
            },
            "dataset_import",
        ),
        ("/training-runs", {"dataset_id": HASH}, "training"),
        (
            "/training-runs",
            {"dataset_id": HASH, "mode": "existing", "run_id": OTHER},
            "training",
        ),
        ("/forecasts", {"run_id": HASH}, "forecasting"),
        ("/forecasts", {"run_id": HASH, "scope": "retrospective"}, "forecasting"),
        ("/inventory/scenarios", {"forecast_id": HASH}, "inventory"),
    ],
)
def test_job_submissions_are_accepted_and_filtered(api, path, payload, kind):
    response = api.client.post(
        path, json=payload, headers={"Idempotency-Key": "synthetic-request-001"}
    )
    assert response.status_code == 202, response.text
    assert response.headers["location"] == f"/jobs/{JOB_ID}"
    assert response.json()["job_id"] == JOB_ID
    assert SECRET not in response.text
    assert api.service.calls[-1][0] == "submit"
    assert api.service.calls[-1][1][0] == kind
    assert api.service.calls[-1][2] == {"idempotency_key": "synthetic-request-001"}


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/datasets/import", {}),
        ("/datasets/import", {"dataset_id": SECRET}),
        ("/datasets/import", {"source": "official", "dataset_id": HASH}),
        (
            "/datasets/import",
            {"source": "existing", "dataset_id": HASH, "input_file": "source.csv"},
        ),
        ("/datasets/import", {"source": "file", "input_file": "../private.csv"}),
        ("/datasets/import", {"source": "file", "input_file": "/private.csv"}),
        ("/datasets/import", {"source": "file", "input_file": "C:/private.csv"}),
        ("/datasets/import", {"source": "file", "input_file": "source.txt"}),
        ("/datasets/import", {"source": "official", "url": SECRET}),
        ("/training-runs", {"dataset_id": HASH, "mode": "existing"}),
        ("/training-runs", {"dataset_id": HASH, "run_id": OTHER}),
        (
            "/training-runs",
            {"dataset_id": HASH, "mode": "existing", "run_id": OTHER, "config": {}},
        ),
        ("/training-runs", {"dataset_id": HASH, "config": {"seed": True}}),
        ("/forecasts", {"run_id": HASH, "scope": SECRET}),
        (
            "/inventory/scenarios",
            {
                "forecast_id": HASH,
                "config": {"products": {SECRET: {"unexpected": SECRET}}},
            },
        ),
        ("/inventory/scenarios", {"forecast_id": HASH, SECRET: SECRET}),
    ],
)
def test_validation_rejects_invalid_inputs_without_echo_or_side_effects(
    api, path, payload
):
    response = api.client.post(path, json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert SECRET not in response.text + api.logs.getvalue()
    for detail in response.json()["error"]["details"]:
        assert set(detail) == {"loc", "msg", "type"}
    assert not api.service.calls
    assert not list(api.settings.data_dir.iterdir())
    assert not list(api.settings.artifact_dir.iterdir())


@pytest.mark.parametrize("header", ["", "space key", "line\tkey", "x" * 129])
def test_idempotency_keys_are_bounded_ascii(api, header):
    response = api.client.post(
        "/forecasts", json={"run_id": HASH}, headers={"Idempotency-Key": header}
    )
    assert response.status_code == 422
    assert not api.service.calls


@pytest.mark.parametrize(
    "path,method",
    [
        ("/datasets", "list_resources"),
        (f"/datasets/{HASH}", "get_resource"),
        (f"/datasets/{HASH}/quality", "quality"),
        (f"/products?dataset_id={HASH}", "list_resources"),
        (f"/products/SYNTH-A?dataset_id={HASH}", "get_resource"),
        (f"/products/SYNTH-A/history?dataset_id={HASH}", "history"),
        ("/training-runs", "list_resources"),
        (f"/training-runs/{HASH}", "get_resource"),
        (f"/training-runs/{HASH}/metrics", "training_metrics"),
        ("/models", "list_resources"),
        (f"/models/{HASH}", "get_resource"),
        ("/forecasts", "list_resources"),
        (f"/forecasts/{HASH}", "get_resource"),
        (f"/forecasts/{HASH}/values", "forecast_rows"),
        ("/inventory/scenarios", "list_resources"),
        (f"/inventory/scenarios/{HASH}", "get_resource"),
        (f"/inventory/scenarios/{HASH}/results", "scenario_results"),
        ("/jobs", "list_resources"),
        (f"/jobs/{JOB_ID}", "get_resource"),
    ],
)
def test_read_endpoints_delegate_to_services(api, path, method):
    response = api.client.get(path)
    assert response.status_code == 200, response.text
    assert api.service.calls[-1][0] == method
    assert SECRET not in response.text


def test_pagination_filters_and_dataset_scope_are_preserved(api):
    assert api.client.get("/products").status_code == 422
    assert api.client.get("/datasets?limit=201").status_code == 422
    assert api.client.get("/datasets?offset=-1").status_code == 422
    response = api.client.get(
        f"/products/SYNTH-A/history?dataset_id={HASH}&run_id={OTHER}&limit=25&offset=10"
    )
    assert response.status_code == 200
    assert api.service.calls[-1] == (
        "history",
        ("SYNTH-A",),
        {"dataset_id": HASH, "run_id": OTHER, "limit": 25, "offset": 10},
    )
    response = api.client.get(
        f"/forecasts/{HASH}/values?stock_code=SYNTH-B&method=ridge&limit=20&offset=5"
    )
    assert response.status_code == 200
    assert api.service.calls[-1][2] == {
        "stock_code": "SYNTH-B",
        "method": "ridge",
        "limit": 20,
        "offset": 5,
    }


def test_exports_return_csv_and_safe_download_headers(api):
    forecasts = api.client.get(f"/forecasts/{HASH}/export")
    assert forecasts.status_code == 200
    assert forecasts.headers["content-type"].startswith("text/csv")
    assert forecasts.content.startswith(b"stock_code,prediction")
    scenario = api.client.get(f"/inventory/scenarios/{HASH}/export?kind=weekly_results")
    assert scenario.status_code == 200
    assert "\r" not in scenario.headers["content-disposition"]
    assert "\n" not in scenario.headers["content-disposition"]
    assert "../" not in scenario.headers["content-disposition"]
    assert api.service.calls[-1][2] == {"kind": "weekly_results"}
    assert (
        api.client.get(
            f"/inventory/scenarios/{HASH}/export?kind=private_file"
        ).status_code
        == 422
    )


def test_service_errors_and_unexpected_failures_are_safe(api):
    api.service.failure = ServiceError(
        409, "idempotency_conflict", "The key belongs to another request"
    )
    response = api.client.post("/forecasts", json={"run_id": HASH})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    api.service.failure = RuntimeError(f"postgresql://user:{SECRET}@host/db")
    failed = api.client.get("/datasets")
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert SECRET not in failed.text + api.logs.getvalue()
    UUID(failed.headers["x-request-id"])


def test_unexpected_error_does_not_escape_to_server_logging_and_retains_cors(api):
    api.service.failure = RuntimeError(f"postgresql://user:{SECRET}@host/db")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    server_logger = logging.getLogger("uvicorn.error")
    server_logger.addHandler(handler)
    try:
        # The default True setting detects Starlette's usual post-response rethrow.
        with TestClient(api.app) as client:
            response = client.get(
                "/datasets", headers={"Origin": "http://localhost:5173"}
            )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:5173"
        )
        UUID(response.headers["x-request-id"])
        assert SECRET not in response.text + api.logs.getvalue() + output.getvalue()
        requests = [
            json.loads(line)
            for line in api.logs.getvalue().splitlines()
            if json.loads(line)["event"] == "http_request"
        ]
        assert requests[-1]["status_code"] == 500
    finally:
        server_logger.removeHandler(handler)


def test_error_after_response_starts_exposes_only_static_exception():
    sent = []

    async def failing_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError(SECRET)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    with pytest.raises(RuntimeError, match="^Response transmission failed$") as caught:
        asyncio.run(
            main.UnexpectedErrorBoundary(failing_app)(
                {"type": "http", "state": {"request_id": JOB_ID}}, receive, send
            )
        )
    assert len(sent) == 1
    assert caught.value.__suppress_context__ is True
    assert SECRET not in "".join(traceback.format_exception(caught.value))


def test_database_endpoint_outage_is_redacted_service_unavailable(api):
    api.service.failure = OperationalError(
        "SELECT secret", {"password": SECRET}, RuntimeError(SECRET)
    )
    response = api.client.get("/datasets")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert SECRET not in response.text + api.logs.getvalue()


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/datasets/import", {"dataset_id": HASH}),
        ("/datasets/import", {"source": "official"}),
        ("/datasets/import", {"source": "file", "input_file": "source.csv"}),
        ("/training-runs", {"dataset_id": HASH}),
        ("/forecasts", {"run_id": HASH}),
        ("/inventory/scenarios", {"forecast_id": HASH}),
    ],
)
def test_real_service_submissions_without_database_are_unavailable(api, path, payload):
    api.app.state.service = service_module.ApplicationService(api.settings, None)
    response = api.client.post(path, json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert SECRET not in response.text + api.logs.getvalue()
    assert not list(api.settings.data_dir.iterdir())
    assert not list(api.settings.artifact_dir.iterdir())


def test_csv_preserves_signed_numbers_and_escapes_formula_like_product_text():
    content = service_module._csv(
        [{"stock_code": "-123", "bias": -1.25, "net_cost": -7, "other": "=1+1"}]
    )
    assert list(csv.DictReader(io.StringIO(content.decode()))) == [
        {"stock_code": "'-123", "bias": "-1.25", "net_cost": "-7", "other": "'=1+1"}
    ]


@pytest.mark.parametrize("kind", ["recommendations", "weekly_results", "summary"])
def test_real_scenario_export_preserves_signed_typed_values(api, monkeypatch, kind):
    # These synthetic outcomes check transport fidelity, not model performance.
    directory = api.settings.artifact_dir / "synthetic-scenario"
    (directory / "exports").mkdir(parents=True)
    rows = [{"stock_code": "-123", "inventory_position": -3, "net_cost": -1.25}]
    frame = pd.DataFrame(rows)
    frame.to_csv(directory / "exports" / f"{kind}.csv", index=False)
    if kind == "summary":
        write_json(directory / "summary.json", {"policies": rows})
    else:
        frame.to_parquet(directory / f"{kind}.parquet", index=False)
    write_json(directory / "manifest.json", {"artifacts": inventory(directory)})
    scenario = SimpleNamespace(
        artifact_dir="synthetic-scenario",
        manifest_sha256=sha256_file(directory / "manifest.json"),
    )

    @contextmanager
    def session(engine):
        yield SimpleNamespace(get=lambda model, identifier: scenario)

    monkeypatch.setattr(service_module, "Session", session)
    api.app.state.service = service_module.ApplicationService(api.settings, object())
    response = api.client.get(f"/inventory/scenarios/{HASH}/export?kind={kind}")
    assert response.status_code == 200, response.text
    assert list(csv.DictReader(io.StringIO(response.text))) == [
        {"stock_code": "'-123", "inventory_position": "-3", "net_cost": "-1.25"}
    ]


def test_logs_use_request_uuid_route_templates_without_query_body_headers_or_unknown_paths(
    api,
):
    api.client.get(
        f"/datasets/{HASH}?password={SECRET}",
        headers={"Authorization": f"Bearer {SECRET}", "X-Request-ID": SECRET},
    )
    api.client.get(f"/{SECRET}")
    invalid = api.client.post(
        "/forecasts",
        content=f'{{"private":"{SECRET}"',
        headers={"Content-Type": "application/json"},
    )
    assert invalid.status_code == 422
    assert SECRET not in invalid.text + api.logs.getvalue()
    logs = [json.loads(line) for line in api.logs.getvalue().splitlines()]
    requests = [line for line in logs if line["event"] == "http_request"]
    assert any(row["path"] == "/datasets/{dataset_id}" for row in requests)
    assert any(row["path"] == "unmatched" for row in requests)
    for row in requests:
        UUID(row["request_id"])
        assert row["duration_seconds"] >= 0


def test_cors_is_limited_to_configured_development_origins(api):
    allowed = api.client.options(
        "/forecasts",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,content-type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    rejected = api.client.get(
        "/health", headers={"Origin": "https://untrusted.example"}
    )
    assert "access-control-allow-origin" not in rejected.headers


def test_request_size_limit_covers_advertised_and_chunked_bodies(tmp_path, monkeypatch):
    service = SyntheticService()
    monkeypatch.setattr(main, "ApplicationService", lambda settings, engine: service)
    application = main.create_app(
        Settings(
            data_dir=tmp_path / "data",
            artifact_dir=tmp_path / "artifacts",
            max_request_bytes=1024,
        )
    )
    with TestClient(application) as client:
        oversized = client.post("/forecasts", content=b"x" * 1025)
        assert oversized.status_code == 413
        chunked = client.post(
            "/forecasts", content=iter([b'{"x":"', b"x" * 1100, b'"}'])
        )
        assert chunked.status_code == 413
        assert not service.calls
