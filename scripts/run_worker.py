"""Run durable jobs without applying migrations or logging private payloads."""

from __future__ import annotations

import argparse
import signal
import threading
import time

from backend.app.core.config import Settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import make_engine
from backend.app.worker import run_once


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Claim at most one available job, then exit"
    )
    parser.add_argument(
        "--shutdown-grace-seconds",
        type=float,
        default=10.0,
        help="Wait at most 0–60 seconds for an active job after SIGINT/SIGTERM",
    )
    args = parser.parse_args()
    if not 0 <= args.shutdown_grace_seconds <= 60:
        parser.error("--shutdown-grace-seconds must be between zero and sixty")
    logger = configure_logging()
    try:
        settings = Settings.from_env()
        if not settings.database_url:
            raise ValueError
        settings.ensure_directories()
        engine = make_engine(settings.database_url)
    except Exception:
        logger.error(
            "worker_configuration_failed", extra={"error_code": "invalid_input"}
        )
        return 2
    shutdown = threading.Event()
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.signal(number, lambda *_: shutdown.set())
    active: threading.Thread | None = None
    abandoned = False
    try:
        while not shutdown.is_set():
            done = threading.Event()
            outcome = {"claimed": False, "failed": False}

            def run(outcome=outcome, done=done) -> None:
                try:
                    outcome["claimed"] = run_once(settings, engine)
                except Exception:
                    outcome["failed"] = True
                    logger.error(
                        "worker_claim_unavailable",
                        extra={"error_code": "database_unavailable"},
                    )
                finally:
                    done.set()

            active = threading.Thread(
                target=run, name="demandiq-worker-job", daemon=True
            )
            active.start()
            while not done.wait(0.1):
                if shutdown.is_set():
                    deadline = time.monotonic() + args.shutdown_grace_seconds
                    while not done.is_set() and time.monotonic() < deadline:
                        done.wait(min(0.1, max(0.0, deadline - time.monotonic())))
                    if not done.is_set():
                        abandoned = True
                        logger.warning(
                            "worker_shutdown_lease_recovery",
                            extra={"error_code": "lease_expired"},
                        )
                    break
            if abandoned:
                break
            active.join()
            if args.once:
                return 1 if outcome["failed"] else 0
            if not outcome["claimed"] or outcome["failed"]:
                shutdown.wait(settings.poll_seconds)
        return 0
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        # On forced grace expiry the process exits with a recoverable live lease;
        # disposing its pool underneath the daemon operation would be unsafe.
        if not abandoned:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
