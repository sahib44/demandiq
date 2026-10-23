"""PostgreSQL job queue with bounded attempts and token-fenced completion.

The database clock defines every lease and retry deadline. Workers compute
outside transactions, heartbeat their claim, then pass a short database-only
``on_success`` callback to finish_job. That callback must use the supplied Session
without committing/rolling back or making external side effects. Its writes and
the successful job status commit together; stale claims cannot invoke it.

Queue operations intentionally do not log payloads, results, exception messages
or database URLs. Worker/API boundaries map failures to the static error codes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from numbers import Real
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.app.db.models import Job

KINDS = frozenset({"dataset_import", "training", "forecasting", "inventory"})
STATUSES = frozenset({"queued", "running", "succeeded", "failed"})
ERROR_CODES = frozenset(
    {
        "invalid_input",
        "artifact_integrity",
        "database_unavailable",
        "operation_failed",
        "lease_expired",
        "attempts_exhausted",
    }
)
_TIMESTAMPS = (
    "available_at",
    "lease_expires_at",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
)


class IdempotencyConflict(ValueError):
    """An existing kind/key belongs to a different canonical request payload."""


class _LeaseLost(Exception):
    """Internal signal used to roll back callback writes after lease expiry."""


def _engine(engine: Engine) -> None:
    if not isinstance(engine, Engine) or engine.dialect.name != "postgresql":
        raise ValueError("The job queue requires a PostgreSQL SQLAlchemy Engine.")


def _text(value: Any, name: str, length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > length
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"{name} must contain 1–{length} noncontrol characters without surrounding whitespace."
        )
    return value


def _uuid(value: Any, name: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{name} must be a canonical lowercase UUID.") from exc
    return value


def _json_object(value: Any, name: str) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object.")

    def string_keys(item: Any) -> bool:
        if isinstance(item, dict):
            return all(
                isinstance(key, str) and string_keys(child)
                for key, child in item.items()
            )
        if isinstance(item, list | tuple):
            return all(string_keys(child) for child in item)
        return True

    try:
        if not string_keys(value):
            raise ValueError(f"{name} JSON object keys must be strings.")
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        )
        normalized = json.loads(canonical)
        canonical.encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError(
            f"{name} must contain finite, UTF-8 JSON-compatible values."
        ) from exc
    return normalized, canonical


def _lease_seconds(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 86400:
        raise ValueError("lease_seconds must be an integer from 1 through 86400.")
    return value


def _backoff(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("backoff_seconds must be a finite number from 0 through 3600.")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 3600:
        raise ValueError("backoff_seconds must be a finite number from 0 through 3600.")
    return result


def _now(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp())).astimezone(UTC)


def _snapshot(job: Job) -> dict[str, Any]:
    fields = (
        "job_id",
        "kind",
        "payload_hash",
        "idempotency_key",
        "status",
        "attempts",
        "max_attempts",
        "locked_by",
        "lease_token",
        "error_code",
    )
    result = {name: getattr(job, name) for name in fields}
    result["payload"] = deepcopy(job.payload)
    result["result"] = deepcopy(job.result)
    for name in _TIMESTAMPS:
        value = getattr(job, name)
        result[name] = (
            value.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if value is not None
            else None
        )
    return result


def enqueue_job(
    engine: Engine,
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Insert once per kind/key; a missing key defaults to canonical payload SHA.

    Identical replay returns the original status, result and retry budget, even
    for failed jobs. An intentional new run requires a new explicit key.
    """
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Unsupported job kind.")
    normalized, canonical = _json_object(payload, "payload")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    key = (
        digest
        if idempotency_key is None
        else _text(idempotency_key, "idempotency_key", 128)
    )
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be an integer from 1 through 5.")
    _engine(engine)
    with Session(engine) as session, session.begin():
        now = _now(session)
        job_id = str(uuid4())
        inserted = session.scalar(
            insert(Job)
            .values(
                job_id=job_id,
                kind=kind,
                payload=normalized,
                payload_hash=digest,
                idempotency_key=key,
                status="queued",
                attempts=0,
                max_attempts=max_attempts,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["kind", "idempotency_key"])
            .returning(Job.job_id)
        )
        if inserted is None:
            job = session.scalar(
                select(Job).where(Job.kind == kind, Job.idempotency_key == key)
            )
            if job.payload_hash != digest or job.payload != normalized:
                raise IdempotencyConflict(
                    "This job kind and idempotency key already identify a different payload."
                )
        else:
            job = session.get(Job, inserted)
        return _snapshot(job)


def _clear_lease(job: Job) -> None:
    job.locked_by = None
    job.lease_token = None
    job.lease_expires_at = None


def _recover(
    session: Session, now: datetime, backoff_seconds: float, limit: int
) -> int:
    expired = session.scalars(
        select(Job)
        .where(Job.status == "running", Job.lease_expires_at <= now)
        .order_by(Job.lease_expires_at, Job.job_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        job.error_code = "lease_expired"
        job.result = None
        job.updated_at = now
        _clear_lease(job)
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.completed_at = now
        else:
            job.status = "queued"
            job.available_at = now + timedelta(seconds=backoff_seconds)
            job.completed_at = None
    exhausted = session.scalars(
        select(Job)
        .where(Job.status == "queued", Job.attempts >= Job.max_attempts)
        .order_by(Job.created_at, Job.job_id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for job in exhausted:
        job.status = "failed"
        job.error_code = "attempts_exhausted"
        job.completed_at = now
        job.updated_at = now
        job.result = None
        _clear_lease(job)
    session.flush()
    return len(expired) + len(exhausted)


def recover_expired_jobs(
    engine: Engine, *, backoff_seconds: float = 2, limit: int = 100
) -> int:
    """Recover a bounded unlocked batch; exhausted attempts become terminal failures."""
    delay = _backoff(backoff_seconds)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer from 1 through 1000.")
    _engine(engine)
    with Session(engine) as session, session.begin():
        return _recover(session, _now(session), delay, limit)


def claim_job(
    engine: Engine, worker_id: str, *, lease_seconds: int = 60
) -> dict[str, Any] | None:
    """Atomically claim one available job, skipping locks held by other workers.

    Expired claims are first requeued with two-second backoff or failed at their
    attempt limit. Every successful claim increments attempts and rotates token.
    """
    owner = _text(worker_id, "worker_id", 64)
    duration = _lease_seconds(lease_seconds)
    _engine(engine)
    with Session(engine) as session, session.begin():
        _recover(session, _now(session), 2.0, 100)
        now = _now(session)
        job = session.scalar(
            select(Job)
            .where(
                Job.status == "queued",
                Job.available_at <= now,
                Job.attempts < Job.max_attempts,
            )
            .order_by(Job.available_at, Job.created_at, Job.job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_by = owner
        job.lease_token = str(uuid4())
        job.lease_expires_at = now + timedelta(seconds=duration)
        job.started_at = job.started_at or now
        job.completed_at = None
        job.updated_at = now
        job.error_code = None
        job.result = None
        session.flush()
        return _snapshot(job)


def _active(job: Job | None, token: str, now: datetime) -> bool:
    return bool(
        job is not None
        and job.status == "running"
        and job.lease_token == token
        and job.lease_expires_at is not None
        and job.lease_expires_at > now
    )


def _locked(session: Session, job_id: str) -> Job | None:
    return session.scalar(select(Job).where(Job.job_id == job_id).with_for_update())


def heartbeat_job(
    engine: Engine, job_id: str, token: str, *, lease_seconds: int
) -> bool:
    """Extend only the still-live token, checking database time after row locking."""
    _uuid(job_id, "job_id")
    _uuid(token, "token")
    duration = _lease_seconds(lease_seconds)
    _engine(engine)
    with Session(engine) as session, session.begin():
        job = _locked(session, job_id)
        now = _now(session)
        if not _active(job, token, now):
            return False
        job.lease_expires_at = max(
            job.lease_expires_at, now + timedelta(seconds=duration)
        )
        job.updated_at = now
        return True


def finish_job(
    engine: Engine,
    job_id: str,
    token: str,
    result: dict[str, Any],
    *,
    on_success: Callable[[Session], None] | None = None,
) -> bool:
    """Fence the claim, persist callback metadata and succeed in one transaction.

    Callback errors propagate after rollback. If its database writes consume the
    remaining lease, those writes are rolled back and False is returned.
    """
    _uuid(job_id, "job_id")
    _uuid(token, "token")
    normalized, _ = _json_object(result, "result")
    if on_success is not None and not callable(on_success):
        raise ValueError("on_success must be a callable or None.")
    _engine(engine)
    try:
        with Session(engine) as session, session.begin():
            job = _locked(session, job_id)
            now = _now(session)
            if not _active(job, token, now):
                return False
            if on_success is not None:
                on_success(session)
                session.flush()
            now = _now(session)
            if not _active(job, token, now):
                raise _LeaseLost
            job.status = "succeeded"
            job.result = normalized
            job.error_code = None
            job.completed_at = now
            job.updated_at = now
            _clear_lease(job)
            session.flush()
        return True
    except _LeaseLost:
        return False


def fail_job(
    engine: Engine,
    job_id: str,
    token: str,
    *,
    error_code: str,
    retryable: bool,
    backoff_seconds: float = 2,
) -> bool:
    """Fail a live claim with a static code; retry only within its original budget."""
    _uuid(job_id, "job_id")
    _uuid(token, "token")
    if not isinstance(error_code, str) or error_code not in ERROR_CODES:
        raise ValueError("error_code must be one of the static supported queue codes.")
    if type(retryable) is not bool:
        raise ValueError("retryable must be a boolean.")
    delay = _backoff(backoff_seconds)
    _engine(engine)
    with Session(engine) as session, session.begin():
        job = _locked(session, job_id)
        now = _now(session)
        if not _active(job, token, now):
            return False
        job.status = (
            "queued" if retryable and job.attempts < job.max_attempts else "failed"
        )
        job.available_at = (
            now + timedelta(seconds=delay)
            if job.status == "queued"
            else job.available_at
        )
        job.completed_at = None if job.status == "queued" else now
        job.updated_at = now
        job.error_code = error_code
        job.result = None
        _clear_lease(job)
        return True


def get_job(engine: Engine, job_id: str) -> dict[str, Any] | None:
    """Read a detached JSON-safe snapshot, or None for an absent UUID."""
    _uuid(job_id, "job_id")
    _engine(engine)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        return _snapshot(job) if job is not None else None


def list_jobs(
    engine: Engine,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List newest jobs with bounded pagination and optional exact filters."""
    if kind is not None and (not isinstance(kind, str) or kind not in KINDS):
        raise ValueError("Unsupported job kind.")
    if status is not None and (not isinstance(status, str) or status not in STATUSES):
        raise ValueError("Unsupported job status.")
    if (
        type(limit) is not int
        or not 1 <= limit <= 500
        or type(offset) is not int
        or offset < 0
    ):
        raise ValueError("limit must be 1..500 and offset a nonnegative integer.")
    _engine(engine)
    with Session(engine) as session:
        statement = select(Job)
        if kind is not None:
            statement = statement.where(Job.kind == kind)
        if status is not None:
            statement = statement.where(Job.status == status)
        jobs = session.scalars(
            statement.order_by(Job.created_at.desc(), Job.job_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_snapshot(job) for job in jobs]
