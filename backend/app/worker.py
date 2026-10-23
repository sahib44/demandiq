"""Lease-fenced durable jobs; expensive computation never holds a transaction."""

from __future__ import annotations

import threading
import time
from uuid import uuid4

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from backend.app.core.config import Settings
from backend.app.core.logging import configure_logging
from backend.app.services.errors import ServiceError
from backend.app.services.jobs import claim_job, fail_job, finish_job, heartbeat_job
from backend.app.services.operations import execute_operation
from ml.pipelines.ingestion import ArtifactError


def _failure(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, ArtifactError):
        return "artifact_integrity", False
    if isinstance(exc, DBAPIError | SQLAlchemyTimeoutError):
        return "database_unavailable", True
    if isinstance(exc, OSError):
        return "operation_failed", True
    if isinstance(exc, ValueError | ServiceError):
        return "invalid_input", False
    return "operation_failed", False


def _heartbeat_interval(settings: Settings) -> float:
    return settings.lease_seconds / 3


def run_once(settings: Settings, engine, worker_id: str | None = None) -> bool:
    """Claim at most one job and return whether a claim was acquired.

    Claim failures propagate to the CLI's redacted retry boundary. Once claimed,
    failures are recorded with static codes or left for expired-lease recovery if
    PostgreSQL/ownership is unavailable. The queue fences every success/failure;
    only its successful transaction invokes the short persistence callback.
    """
    owner = worker_id or f"worker-{uuid4()}"
    job = claim_job(engine, owner, lease_seconds=settings.lease_seconds)
    if job is None:
        return False
    started = time.perf_counter()
    logger = configure_logging()
    identity = {"job_id": job["job_id"], "kind": job["kind"]}
    logger.info("job_claimed", extra={**identity, "status": "running"})
    stop, lost = threading.Event(), threading.Event()

    def heartbeat() -> None:
        while not stop.wait(_heartbeat_interval(settings)):
            try:
                live = heartbeat_job(
                    engine,
                    job["job_id"],
                    job["lease_token"],
                    lease_seconds=settings.lease_seconds,
                )
            except Exception:
                lost.set()
                logger.warning(
                    "job_heartbeat_unavailable",
                    extra={**identity, "error_code": "database_unavailable"},
                )
                return
            if not live:
                lost.set()
                logger.warning(
                    "job_lease_lost", extra={**identity, "error_code": "lease_expired"}
                )
                return

    thread = threading.Thread(
        target=heartbeat, name="demandiq-job-heartbeat", daemon=True
    )
    thread.start()
    prepared, error = None, None
    try:
        prepared = execute_operation(settings, engine, job)
    except Exception as exc:
        error = exc
    finally:
        stop.set()
        # A blocked heartbeat must not make the main worker wait indefinitely.
        thread.join(timeout=3)
        if thread.is_alive():
            lost.set()
    if lost.is_set():
        logger.warning(
            "job_completion_abandoned",
            extra={**identity, "error_code": "lease_expired"},
        )
        return True
    if error is None:
        try:
            # Reserve a full lease for the short fenced persistence transaction.
            if not heartbeat_job(
                engine,
                job["job_id"],
                job["lease_token"],
                lease_seconds=settings.lease_seconds,
            ):
                logger.warning(
                    "job_completion_abandoned",
                    extra={**identity, "error_code": "lease_expired"},
                )
                return True
            succeeded = finish_job(
                engine,
                job["job_id"],
                job["lease_token"],
                prepared.result,
                on_success=prepared.persist,
            )
            logger.info(
                "job_completed" if succeeded else "job_completion_abandoned",
                extra={
                    **identity,
                    "status": "succeeded" if succeeded else "lease_lost",
                    "duration_seconds": round(time.perf_counter() - started, 6),
                },
            )
            return True
        except Exception as exc:
            error = exc
    code, retryable = _failure(error)
    try:
        recorded = fail_job(
            engine,
            job["job_id"],
            job["lease_token"],
            error_code=code,
            retryable=retryable,
            backoff_seconds=min(2 ** min(job.get("attempts", 1), 6), 60),
        )
    except Exception:
        logger.error(
            "job_failure_unrecorded",
            extra={**identity, "error_code": "database_unavailable"},
        )
        return True
    logger.warning(
        "job_operation_failed" if recorded else "job_failure_lease_lost",
        extra={
            **identity,
            "error_code": code,
            "duration_seconds": round(time.perf_counter() - started, 6),
        },
    )
    return True
