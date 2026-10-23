"""Worker boundaries use fake queue calls; no PostgreSQL data is modified."""

import io
import logging
import signal
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from backend.app import worker
from backend.app.core.config import Settings
from backend.app.core.logging import JsonFormatter
from backend.app.services.errors import ServiceError
from backend.app.services.operations import PreparedOperation
from ml.pipelines.ingestion import ArtifactError
from scripts import run_worker

SECRET = "PRIVATE-DATABASE-OR-SOURCE-123"
JOB = {
    "job_id": "00000000-0000-4000-8000-000000000001",
    "lease_token": "00000000-0000-4000-8000-000000000002",
    "kind": "training",
    "attempts": 1,
    "payload": {"private": SECRET},
}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = Settings(
        database_url="postgresql://localhost/demandiq",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        lease_seconds=3,
        poll_seconds=0.01,
    )
    engine = object()
    calls = []
    monkeypatch.setattr(
        worker,
        "claim_job",
        lambda *args, **kwargs: (calls.append(("claim", args, kwargs)) or dict(JOB)),
    )
    monkeypatch.setattr(
        worker,
        "heartbeat_job",
        lambda *args, **kwargs: (calls.append(("heartbeat", args, kwargs)) or True),
    )
    monkeypatch.setattr(
        worker,
        "finish_job",
        lambda *args, **kwargs: (calls.append(("finish", args, kwargs)) or True),
    )
    monkeypatch.setattr(
        worker,
        "fail_job",
        lambda *args, **kwargs: (calls.append(("fail", args, kwargs)) or True),
    )
    prepared = PreparedOperation({"run_id": "a" * 64}, lambda session: None)
    monkeypatch.setattr(worker, "execute_operation", lambda *args: prepared)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("demandiq")
    logger.addHandler(handler)
    try:
        yield SimpleNamespace(
            settings=settings,
            engine=engine,
            calls=calls,
            prepared=prepared,
            logs=output,
        )
    finally:
        logger.removeHandler(handler)


def test_idle_returns_false_without_computing_or_completing(setup, monkeypatch):
    monkeypatch.setattr(worker, "claim_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        worker,
        "execute_operation",
        lambda *args: pytest.fail("Idle workers cannot compute"),
    )
    assert worker.run_once(setup.settings, setup.engine) is False
    assert not setup.calls


def test_success_computes_outside_completion_and_passes_atomic_callback(
    setup, monkeypatch
):
    persisted = []
    session = object()
    prepared = PreparedOperation(
        {"run_id": "a" * 64}, lambda value: persisted.append(value)
    )

    def compute(*args):
        assert not persisted
        assert not any(call[0] == "finish" for call in setup.calls)
        return prepared

    def finish(*args, **kwargs):
        assert args[3] == prepared.result
        assert kwargs["on_success"] is prepared.persist
        kwargs["on_success"](session)
        return True

    monkeypatch.setattr(worker, "execute_operation", compute)
    monkeypatch.setattr(worker, "finish_job", finish)
    assert worker.run_once(setup.settings, setup.engine, "synthetic-worker") is True
    assert persisted == [session]
    assert setup.calls[0][1] == (setup.engine, "synthetic-worker")
    assert setup.calls[0][2] == {"lease_seconds": 3}
    assert any(call[0] == "heartbeat" for call in setup.calls)
    assert SECRET not in setup.logs.getvalue()


@pytest.mark.parametrize(
    "error,code,retry",
    [
        (ArtifactError(SECRET), "artifact_integrity", False),
        (ValueError(SECRET), "invalid_input", False),
        (ServiceError(422, "invalid_input", SECRET), "invalid_input", False),
        (
            OperationalError("SQL", {"secret": SECRET}, RuntimeError(SECRET)),
            "database_unavailable",
            True,
        ),
        (SQLAlchemyTimeoutError(SECRET), "database_unavailable", True),
        (OSError(SECRET), "operation_failed", True),
        (RuntimeError(SECRET), "operation_failed", False),
    ],
)
def test_failure_classification_is_static_and_retry_is_bounded(
    setup, monkeypatch, error, code, retry
):
    def fail(*args):
        raise error

    monkeypatch.setattr(worker, "execute_operation", fail)
    assert worker.run_once(setup.settings, setup.engine) is True
    failure = next(call for call in setup.calls if call[0] == "fail")
    assert failure[2] == {"error_code": code, "retryable": retry, "backoff_seconds": 2}
    assert not any(call[0] == "finish" for call in setup.calls)
    assert SECRET not in setup.logs.getvalue()


@pytest.mark.parametrize("raises", [False, True])
def test_lost_or_failed_background_heartbeat_prevents_completion(
    setup, monkeypatch, raises
):
    observed = threading.Event()
    monkeypatch.setattr(worker, "_heartbeat_interval", lambda settings: 0.001)

    def heartbeat(*args, **kwargs):
        observed.set()
        if raises:
            raise RuntimeError(SECRET)
        return False

    def compute(*args):
        assert observed.wait(1)
        return setup.prepared

    monkeypatch.setattr(worker, "heartbeat_job", heartbeat)
    monkeypatch.setattr(worker, "execute_operation", compute)
    assert worker.run_once(setup.settings, setup.engine) is True
    assert not any(call[0] in {"finish", "fail"} for call in setup.calls)
    assert SECRET not in setup.logs.getvalue()


def test_final_refresh_and_stale_completion_cannot_persist(setup, monkeypatch):
    monkeypatch.setattr(worker, "heartbeat_job", lambda *args, **kwargs: False)
    assert worker.run_once(setup.settings, setup.engine) is True
    assert not any(call[0] in {"finish", "fail"} for call in setup.calls)
    monkeypatch.setattr(worker, "heartbeat_job", lambda *args, **kwargs: True)
    monkeypatch.setattr(worker, "finish_job", lambda *args, **kwargs: False)
    assert worker.run_once(setup.settings, setup.engine) is True
    assert not any(call[0] == "fail" for call in setup.calls)


def test_completion_failure_is_recorded_and_failed_recording_is_redacted(
    setup, monkeypatch
):
    def finish(*args, **kwargs):
        raise OperationalError("SQL", {"password": SECRET}, RuntimeError(SECRET))

    monkeypatch.setattr(worker, "finish_job", finish)
    assert worker.run_once(setup.settings, setup.engine) is True
    assert (
        next(call for call in setup.calls if call[0] == "fail")[2]["retryable"] is True
    )
    monkeypatch.setattr(worker, "fail_job", finish)
    assert worker.run_once(setup.settings, setup.engine) is True
    assert SECRET not in setup.logs.getvalue()


@pytest.fixture
def cli(setup, monkeypatch):
    handlers = {}
    disposed = []
    engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    monkeypatch.setattr(run_worker.Settings, "from_env", lambda: setup.settings)
    monkeypatch.setattr(run_worker, "make_engine", lambda url: engine)
    monkeypatch.setattr(
        run_worker.signal,
        "signal",
        lambda number, handler: handlers.setdefault(number, handler),
    )
    return SimpleNamespace(handlers=handlers, disposed=disposed, engine=engine)


@pytest.mark.parametrize("claimed", [False, True])
def test_cli_once_claims_at_most_one_job_and_disposes(cli, monkeypatch, claimed):
    calls = []
    monkeypatch.setattr("sys.argv", ["run_worker", "--once"])
    monkeypatch.setattr(
        run_worker, "run_once", lambda *args: (calls.append(args) or claimed)
    )
    assert run_worker.main() == 0
    assert len(calls) == 1
    assert cli.disposed == [True]


def test_cli_claim_failure_is_nonzero_and_never_logs_private_errors(
    setup, cli, monkeypatch
):
    monkeypatch.setattr("sys.argv", ["run_worker", "--once"])

    def fail(*args):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(run_worker, "run_once", fail)
    assert run_worker.main() == 1
    assert SECRET not in setup.logs.getvalue()


def test_cli_signal_stops_polling_after_current_job(cli, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_worker"])
    calls = []

    def execute(*args):
        calls.append(1)
        cli.handlers[signal.SIGTERM](None, None)
        return True

    monkeypatch.setattr(run_worker, "run_once", execute)
    assert run_worker.main() == 0
    assert calls == [1]
    assert cli.disposed == [True]


def test_cli_shutdown_grace_is_bounded_and_leaves_lease_for_recovery(cli, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr("sys.argv", ["run_worker", "--shutdown-grace-seconds", "0.02"])

    def execute(*args):
        cli.handlers[signal.SIGTERM](None, None)
        release.wait(2)
        return True

    monkeypatch.setattr(run_worker, "run_once", execute)
    started = time.monotonic()
    try:
        assert run_worker.main() == 0
        assert time.monotonic() - started < 0.75
        assert not cli.disposed
    finally:
        release.set()


def test_cli_missing_database_is_a_redacted_configuration_error(setup, monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_worker", "--once"])
    monkeypatch.setattr(
        run_worker.Settings, "from_env", lambda: Settings(database_url="")
    )
    assert run_worker.main() == 2
    assert SECRET not in setup.logs.getvalue()
