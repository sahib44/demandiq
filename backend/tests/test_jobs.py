"""Queue unit tests and real PostgreSQL claim/fencing/recovery integration tests.

Integration fixtures DELETE all jobs in TEST_DATABASE_URL and one synthetic
Dataset used for transactional callback checks. Only disposable database names
ending in _test are accepted. Run this suite sequentially with other destructive
database suites, never in parallel against their shared database.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from backend.app.db.models import Dataset, Job
from backend.app.db.repository import postgres_url
from backend.app.services import jobs
from backend.app.services.jobs import (
    IdempotencyConflict,
    claim_job,
    enqueue_job,
    fail_job,
    finish_job,
    get_job,
    heartbeat_job,
    list_jobs,
    recover_expired_jobs,
)

ROOT = Path(__file__).resolve().parents[2]
CALLBACK_DATASET_ID = "e" * 64


@pytest.fixture(scope="module")
def queue_engine():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "TEST_DATABASE_URL absent: real PostgreSQL queue tests were not run."
        )
    url = postgres_url(value)
    if not url.database.endswith("_test"):
        pytest.fail(
            "Refusing destructive queue tests: database name must end in _test."
        )
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = value
    try:
        command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
    engine = create_engine(url, hide_parameters=True, pool_size=12, max_overflow=4)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def engine(queue_engine):
    def clear():
        with queue_engine.begin() as connection:
            connection.execute(delete(Job))
            connection.execute(
                delete(Dataset).where(Dataset.dataset_id == CALLBACK_DATASET_ID)
            )

    clear()
    try:
        yield queue_engine
    finally:
        clear()


def expire(engine, job_id):
    with engine.begin() as connection:
        connection.execute(
            update(Job)
            .where(Job.job_id == job_id)
            .values(lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def make_available(engine, job_id):
    with engine.begin() as connection:
        connection.execute(
            update(Job)
            .where(Job.job_id == job_id)
            .values(available_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def callback_dataset():
    return Dataset(
        dataset_id=CALLBACK_DATASET_ID,
        source_sha256="f" * 64,
        cleaning_version="synthetic-queue-test",
        status="ready",
        original_rows=0,
        cleaned_rows=0,
        config={},
        artifacts={},
        artifact_dir="synthetic/queue",
        manifest={},
    )


@pytest.mark.parametrize(
    "kind,payload,key,attempts",
    [
        ("unknown", {}, None, 3),
        ("training", [], None, 3),
        ("training", {"invalid": float("nan")}, None, 3),
        ("training", {"invalid": float("inf")}, None, 3),
        ("training", {1: "nonstring key"}, None, 3),
        ("training", {"nested": {1: "invalid"}}, None, 3),
        ("training", {"invalid": datetime.now(UTC)}, None, 3),
        ("training", {}, "", 3),
        ("training", {}, "x" * 129, 3),
        ("training", {}, "key\nsecret", 3),
        ("training", {}, " spaced ", 3),
        ("training", {}, None, 0),
        ("training", {}, None, 6),
        ("training", {}, None, True),
    ],
)
def test_invalid_enqueue_requests_fail_before_connecting(kind, payload, key, attempts):
    with pytest.raises(ValueError):
        enqueue_job(None, kind, payload, idempotency_key=key, max_attempts=attempts)


def test_cyclic_payload_is_a_validation_error():
    payload = {}
    payload["self"] = payload
    with pytest.raises(ValueError, match="JSON-compatible"):
        enqueue_job(None, "training", payload)


def test_sqlite_cannot_substitute_for_postgresql():
    engine = create_engine("sqlite://")
    try:
        with pytest.raises(ValueError, match="PostgreSQL"):
            enqueue_job(engine, "training", {})
    finally:
        engine.dispose()


@pytest.mark.parametrize("lease", [0, -1, True, 1.5, 86401])
def test_invalid_lease_parameters_fail_before_connecting(lease):
    with pytest.raises(ValueError, match="lease_seconds"):
        claim_job(None, "synthetic-worker", lease_seconds=lease)
    with pytest.raises(ValueError, match="lease_seconds"):
        heartbeat_job(None, str(uuid4()), str(uuid4()), lease_seconds=lease)


@pytest.mark.parametrize(
    "code", ["secret password=private", "OPERATION_FAILED", "", "x" * 65, None]
)
def test_only_static_sanitized_failure_codes_are_accepted(code):
    with pytest.raises(ValueError, match="error_code"):
        fail_job(None, str(uuid4()), str(uuid4()), error_code=code, retryable=False)


@pytest.mark.parametrize("backoff", [-1, True, float("nan"), float("inf"), 3601, "2"])
def test_invalid_backoff_parameters_fail_before_connecting(backoff):
    with pytest.raises(ValueError, match="backoff_seconds"):
        recover_expired_jobs(None, backoff_seconds=backoff)


@pytest.mark.integration
def test_enqueue_default_hash_is_idempotent_and_snapshots_are_json_safe(engine):
    original = {"b": [1, 2], "a": {"setting": True}}
    first = enqueue_job(engine, "training", original, max_attempts=2)
    replay = enqueue_job(
        engine, "training", {"a": {"setting": True}, "b": [1, 2]}, max_attempts=5
    )
    assert first == replay
    assert first["idempotency_key"] == first["payload_hash"]
    assert first["max_attempts"] == 2
    assert first["attempts"] == 0 and first["status"] == "queued"
    assert first["created_at"].endswith("Z") and first["available_at"].endswith("Z")
    json.dumps(first, allow_nan=False)
    original["b"].append(3)
    assert get_job(engine, first["job_id"])["payload"]["b"] == [1, 2]


@pytest.mark.integration
def test_explicit_idempotency_conflict_and_different_kinds_or_keys(engine):
    first = enqueue_job(
        engine, "training", {"setting": 1}, idempotency_key="synthetic-key"
    )
    assert (
        enqueue_job(
            engine, "training", {"setting": 1}, idempotency_key="synthetic-key"
        )["job_id"]
        == first["job_id"]
    )
    with pytest.raises(IdempotencyConflict, match="different payload"):
        enqueue_job(engine, "training", {"setting": 2}, idempotency_key="synthetic-key")
    assert (
        enqueue_job(
            engine, "forecasting", {"setting": 2}, idempotency_key="synthetic-key"
        )["job_id"]
        != first["job_id"]
    )
    assert (
        enqueue_job(
            engine, "training", {"setting": 1}, idempotency_key="different-key"
        )["job_id"]
        != first["job_id"]
    )


@pytest.mark.integration
def test_concurrent_idempotent_enqueue_creates_exactly_one_job(engine):
    barrier = Barrier(8)

    def enqueue():
        barrier.wait()
        return enqueue_job(engine, "inventory", {"synthetic": 1})["job_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        identifiers = list(pool.map(lambda _: enqueue(), range(8)))
    assert len(set(identifiers)) == 1
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.integration
def test_concurrent_claims_are_exclusive_and_attempts_increment_once(engine):
    identifiers = {
        enqueue_job(engine, "training", {"synthetic": i})["job_id"] for i in range(5)
    }
    barrier = Barrier(10)

    def claim(index):
        barrier.wait()
        return claim_job(engine, f"worker-{index}")

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(claim, range(10)))
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 5
    assert {item["job_id"] for item in claimed} == identifiers
    assert len({item["lease_token"] for item in claimed}) == 5
    assert all(
        item["attempts"] == 1 and item["status"] == "running" for item in claimed
    )


@pytest.mark.integration
def test_claim_skips_a_locked_ready_job_without_waiting(engine):
    first = enqueue_job(engine, "training", {"synthetic": 1})
    second = enqueue_job(engine, "training", {"synthetic": 2})
    with ThreadPoolExecutor(max_workers=1) as pool, Session(engine) as locker:
        locker.begin()
        locker.execute(
            select(Job).where(Job.job_id == first["job_id"]).with_for_update()
        )
        try:
            claimed = pool.submit(claim_job, engine, "unblocked-worker").result(
                timeout=3
            )
            assert claimed["job_id"] == second["job_id"]
        finally:
            locker.rollback()
    assert claim_job(engine, "later-worker")["job_id"] == first["job_id"]


@pytest.mark.integration
def test_expired_claim_requeues_with_backoff_rotates_token_and_fences_stale_worker(
    engine,
):
    queued = enqueue_job(engine, "training", {})
    first = claim_job(engine, "first-worker")
    expire(engine, queued["job_id"])
    called = []
    assert not heartbeat_job(
        engine, first["job_id"], first["lease_token"], lease_seconds=60
    )
    assert not finish_job(
        engine,
        first["job_id"],
        first["lease_token"],
        {},
        on_success=lambda _: called.append(True),
    )
    assert not fail_job(
        engine,
        first["job_id"],
        first["lease_token"],
        error_code="operation_failed",
        retryable=True,
    )
    assert not called
    assert claim_job(engine, "recovery-worker") is None
    recovered = get_job(engine, first["job_id"])
    assert recovered["status"] == "queued" and recovered["attempts"] == 1
    assert recovered["error_code"] == "lease_expired"
    assert recovered["lease_token"] is None and recovered["locked_by"] is None
    assert datetime.fromisoformat(recovered["available_at"]) > datetime.fromisoformat(
        recovered["updated_at"]
    )
    make_available(engine, first["job_id"])
    second = claim_job(engine, "second-worker")
    assert second["attempts"] == 2 and second["lease_token"] != first["lease_token"]
    assert not finish_job(
        engine, first["job_id"], first["lease_token"], {"stale": True}
    )
    assert finish_job(
        engine, second["job_id"], second["lease_token"], {"finished": True}
    )


@pytest.mark.integration
def test_heartbeat_extends_only_a_live_matching_token(engine):
    enqueue_job(engine, "forecasting", {})
    claim = claim_job(engine, "worker", lease_seconds=10)
    original = datetime.fromisoformat(claim["lease_expires_at"])
    assert not heartbeat_job(engine, claim["job_id"], str(uuid4()), lease_seconds=60)
    assert heartbeat_job(
        engine, claim["job_id"], claim["lease_token"], lease_seconds=60
    )
    assert (
        datetime.fromisoformat(get_job(engine, claim["job_id"])["lease_expires_at"])
        > original
    )
    assert finish_job(engine, claim["job_id"], claim["lease_token"], {})
    assert not heartbeat_job(
        engine, claim["job_id"], claim["lease_token"], lease_seconds=60
    )


@pytest.mark.integration
def test_finish_persists_callback_and_success_in_one_transaction(engine):
    enqueue_job(engine, "dataset_import", {})
    claim = claim_job(engine, "worker")
    assert finish_job(
        engine,
        claim["job_id"],
        claim["lease_token"],
        {"dataset_id": CALLBACK_DATASET_ID},
        on_success=lambda session: session.add(callback_dataset()),
    )
    finished = get_job(engine, claim["job_id"])
    assert finished["status"] == "succeeded"
    assert finished["result"] == {"dataset_id": CALLBACK_DATASET_ID}
    assert finished["lease_token"] is None and finished["lease_expires_at"] is None
    assert finished["completed_at"] is not None
    with Session(engine) as session:
        assert session.get(Dataset, CALLBACK_DATASET_ID) is not None


@pytest.mark.integration
def test_callback_exception_rolls_back_domain_rows_and_job_success(engine):
    enqueue_job(engine, "dataset_import", {})
    claim = claim_job(engine, "worker")

    def broken(session):
        session.add(callback_dataset())
        session.flush()
        raise RuntimeError("Synthetic callback failure")

    with pytest.raises(RuntimeError, match="Synthetic"):
        finish_job(engine, claim["job_id"], claim["lease_token"], {}, on_success=broken)
    assert get_job(engine, claim["job_id"])["status"] == "running"
    with Session(engine) as session:
        assert session.get(Dataset, CALLBACK_DATASET_ID) is None


@pytest.mark.integration
def test_lease_loss_during_callback_rolls_back_its_database_writes(engine, monkeypatch):
    enqueue_job(engine, "dataset_import", {})
    claim = claim_job(engine, "worker")
    real_now = jobs._now
    reads = 0

    def advancing_clock(session):
        nonlocal reads
        reads += 1
        now = real_now(session)
        return (
            now
            if reads == 1
            else datetime.fromisoformat(claim["lease_expires_at"])
            + timedelta(seconds=1)
        )

    # Simulate elapsed DB-clock time deterministically, without waiting a lease.
    monkeypatch.setattr(jobs, "_now", advancing_clock)
    assert not finish_job(
        engine,
        claim["job_id"],
        claim["lease_token"],
        {},
        on_success=lambda session: session.add(callback_dataset()),
    )
    with Session(engine) as session:
        assert session.get(Dataset, CALLBACK_DATASET_ID) is None
    assert get_job(engine, claim["job_id"])["status"] == "running"


@pytest.mark.integration
def test_retry_backoff_and_original_attempt_budget_are_bounded(engine):
    enqueue_job(engine, "training", {}, max_attempts=2)
    first = claim_job(engine, "first")
    assert fail_job(
        engine,
        first["job_id"],
        first["lease_token"],
        error_code="operation_failed",
        retryable=True,
        backoff_seconds=30,
    )
    assert claim_job(engine, "early") is None
    retry = get_job(engine, first["job_id"])
    assert retry["status"] == "queued" and retry["error_code"] == "operation_failed"
    make_available(engine, first["job_id"])
    second = claim_job(engine, "second")
    assert second["attempts"] == 2
    assert fail_job(
        engine,
        second["job_id"],
        second["lease_token"],
        error_code="operation_failed",
        retryable=True,
        backoff_seconds=0,
    )
    assert get_job(engine, second["job_id"])["status"] == "failed"
    assert claim_job(engine, "third") is None
    replay = enqueue_job(engine, "training", {}, max_attempts=5)
    assert (
        replay["job_id"] == first["job_id"]
        and replay["status"] == "failed"
        and replay["max_attempts"] == 2
    )
    assert (
        enqueue_job(engine, "training", {}, idempotency_key="intentional-new-run")[
            "job_id"
        ]
        != first["job_id"]
    )


@pytest.mark.integration
def test_nonretryable_failure_and_expired_last_attempt_are_terminal(engine):
    enqueue_job(engine, "training", {"synthetic": 1})
    claim = claim_job(engine, "worker")
    assert fail_job(
        engine,
        claim["job_id"],
        claim["lease_token"],
        error_code="invalid_input",
        retryable=False,
    )
    assert get_job(engine, claim["job_id"])["status"] == "failed"
    enqueue_job(engine, "inventory", {}, max_attempts=1)
    last = claim_job(engine, "last")
    expire(engine, last["job_id"])
    assert recover_expired_jobs(engine) == 1
    exhausted = get_job(engine, last["job_id"])
    assert (
        exhausted["status"] == "failed" and exhausted["error_code"] == "lease_expired"
    )
    assert exhausted["completed_at"] is not None and exhausted["lease_token"] is None


@pytest.mark.integration
def test_database_statement_failure_rolls_back_callback_metadata(engine):
    enqueue_job(engine, "dataset_import", {})
    claim = claim_job(engine, "worker")

    def failed_database_operation(session):
        session.add(callback_dataset())
        session.flush()
        session.execute(text("SELECT definitely_missing_synthetic_function()"))

    with pytest.raises(ProgrammingError):
        finish_job(
            engine,
            claim["job_id"],
            claim["lease_token"],
            {},
            on_success=failed_database_operation,
        )
    with Session(engine) as session:
        assert session.get(Dataset, CALLBACK_DATASET_ID) is None
    assert get_job(engine, claim["job_id"])["status"] == "running"


@pytest.mark.integration
def test_absent_jobs_get_list_filters_and_database_outage_propagate(engine):
    assert get_job(engine, str(uuid4())) is None
    assert not heartbeat_job(engine, str(uuid4()), str(uuid4()), lease_seconds=60)
    assert not finish_job(engine, str(uuid4()), str(uuid4()), {})
    training = enqueue_job(engine, "training", {})
    enqueue_job(engine, "forecasting", {})
    assert list_jobs(engine, kind="training")[0]["job_id"] == training["job_id"]
    assert len(list_jobs(engine, status="queued", limit=1)) == 1
    assert len(list_jobs(engine, offset=1)) == 1
    assert list_jobs(engine, status="failed") == []
    offline = create_engine(
        "postgresql+psycopg://synthetic:synthetic@127.0.0.1:1/demandiq_test",
        connect_args={"connect_timeout": 1},
    )
    try:
        with pytest.raises(OperationalError):
            get_job(offline, training["job_id"])
    finally:
        offline.dispose()
