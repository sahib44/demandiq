"""Local dataset-scoped reservation for a single frozen final-test experiment.

The caller freezes its plan, fitted models and calibration before claiming, then
claims immediately before interpreting any held-out target. An interrupted claim
stays locked: automatic retries cannot establish whether targets were observed.
This is a cooperative POSIX local-filesystem protocol, not a distributed lock or
an access-control boundary against someone modifying/deleting the ledger root.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

LEDGER_VERSION: Final = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_RUNNING_FIELDS: Final = frozenset(
    {
        "ledger_version",
        "dataset_id",
        "experiment_id",
        "plan_sha256",
        "status",
        "started_at",
    }
)
_COMPLETE_FIELDS: Final = _RUNNING_FIELDS | {
    "results_dir",
    "results_manifest_sha256",
    "completed_at",
}
_MAX_LEDGER_BYTES: Final = 64 * 1024
_LOCKED: Final = (
    "The test is already reserved/evaluated for this dataset; do not retune "
    "or start another experiment."
)
_RECOVERY: Final = (
    "The reservation is running and may already have read test targets. "
    "Preserve the ledger and partial outputs; recover manually by inspecting "
    "the original experiment and completing its verified result. Do not delete "
    "the ledger or rerun evaluation."
)


class FinalTestLedgerError(ValueError):
    """A missing, malformed or inconsistent final-test ledger requires attention."""


class FinalTestLockedError(FinalTestLedgerError):
    """The dataset's test reservation cannot authorize a new evaluation."""


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise FinalTestLedgerError(f"{name} must be a lowercase 64-hex SHA-256 digest")
    return value


def _identity(dataset_id: str, experiment_id: str, plan_sha256: str) -> None:
    for name, value in (
        ("dataset_id", dataset_id),
        ("experiment_id", experiment_id),
        ("plan_sha256", plan_sha256),
    ):
        _digest(value, name)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise FinalTestLedgerError(
            "Ledger timestamps must be explicit UTC ISO datetimes"
        )
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalTestLedgerError("Ledger contains an invalid UTC timestamp") from exc


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FinalTestLedgerError("Ledger contains duplicate JSON fields")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise FinalTestLedgerError("Ledger contains unsupported nonfinite JSON values")


def _validate_ledger(value: Any, dataset_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalTestLedgerError("Final-test ledger must contain a JSON object")
    if not isinstance(value.get("status"), str) or value["status"] not in {
        "running",
        "complete",
    }:
        raise FinalTestLedgerError("Final-test ledger contains an invalid status")
    expected_fields = (
        _COMPLETE_FIELDS if value["status"] == "complete" else _RUNNING_FIELDS
    )
    if set(value) != expected_fields:
        raise FinalTestLedgerError(
            "Final-test ledger contains missing or unexpected fields"
        )
    if (
        type(value["ledger_version"]) is not int
        or value["ledger_version"] != LEDGER_VERSION
    ):
        raise FinalTestLedgerError("Final-test ledger version is incompatible")
    _identity(value["dataset_id"], value["experiment_id"], value["plan_sha256"])
    if value["dataset_id"] != dataset_id:
        raise FinalTestLedgerError(
            "Final-test ledger identity contradicts its dataset filename"
        )
    started = _timestamp(value["started_at"])
    if value["status"] == "complete":
        _digest(value["results_manifest_sha256"], "results_manifest_sha256")
        result_path = value["results_dir"]
        if (
            not isinstance(result_path, str)
            or not result_path
            or "\0" in result_path
            or not Path(result_path).is_absolute()
            or ".." in Path(result_path).parts
        ):
            raise FinalTestLedgerError(
                "Final-test ledger results_dir must be an absolute local path"
            )
        try:
            result_path.encode("utf-8")
        except UnicodeError as exc:
            raise FinalTestLedgerError(
                "Final-test ledger results_dir must be valid UTF-8"
            ) from exc
        if _timestamp(value["completed_at"]) < started:
            raise FinalTestLedgerError(
                "Final-test completion timestamp precedes its reservation"
            )
    return value


def read_final_evaluation(ledger_root: Path, dataset_id: str) -> dict[str, Any]:
    """Read and validate metadata without interpreting result/test observations.

    Digests are canonical lowercase hex, schemas are strict, timestamps are UTC,
    and the dataset identity must match its filename. This validates consistency,
    not authenticity against an actor able to rewrite trusted local files.
    """
    _digest(dataset_id, "dataset_id")
    path = Path(ledger_root) / f"{dataset_id}.json"
    try:
        if path.is_symlink() or not path.is_file():
            raise FinalTestLedgerError(
                "Final-test ledger is missing or is not a regular local file"
            )
        with path.open("rb") as stream:
            encoded = stream.read(_MAX_LEDGER_BYTES + 1)
        if len(encoded) > _MAX_LEDGER_BYTES:
            raise FinalTestLedgerError(
                "Final-test ledger exceeds its metadata size limit"
            )
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_json_pairs,
            parse_constant=_invalid_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinalTestLedgerError(
            "Final-test ledger is unreadable or malformed; preserve it and inspect manually"
        ) from exc
    return _validate_ledger(payload, dataset_id)


def _matches(ledger: dict[str, Any], experiment_id: str, plan_sha256: str) -> None:
    if ledger["experiment_id"] != experiment_id or ledger["plan_sha256"] != plan_sha256:
        raise FinalTestLockedError(_LOCKED)


def _hash_manifest(results_dir: Path) -> str:
    manifest = results_dir / "manifest.json"
    try:
        if not results_dir.is_dir() or not manifest.is_file() or manifest.is_symlink():
            raise FinalTestLedgerError(
                "Final-test results require an existing regular manifest.json"
            )
        digest = hashlib.sha256()
        with manifest.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise FinalTestLedgerError("Final-test result manifest is unreadable") from exc


def verify_cached_evaluation(
    ledger_root: Path,
    dataset_id: str,
    experiment_id: str,
    plan_sha256: str,
) -> dict[str, Any]:
    """Return a matching completed ledger only if its result manifest is intact.

    The caller must also verify every artifact listed in that manifest. This
    helper never reopens test data and never authorizes another experiment.
    """
    _identity(dataset_id, experiment_id, plan_sha256)
    ledger = read_final_evaluation(ledger_root, dataset_id)
    _matches(ledger, experiment_id, plan_sha256)
    if ledger["status"] != "complete":
        raise FinalTestLockedError(f"{_LOCKED} {_RECOVERY}")
    if _hash_manifest(Path(ledger["results_dir"])) != ledger["results_manifest_sha256"]:
        raise FinalTestLedgerError(
            "Final-test cached result manifest failed integrity verification; "
            "preserve the reservation and recover manually, without rerunning evaluation"
        )
    return ledger


def _write_temporary(root: Path, dataset_id: str, payload: dict[str, Any]) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{dataset_id}.", suffix=".tmp", dir=root)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _sync_directory(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def claim_final_evaluation(
    ledger_root: Path,
    dataset_id: str,
    experiment_id: str,
    plan_sha256: str,
) -> str:
    """Exclusively claim a dataset test, or reuse the same verified completion.

    Returns ``claimed`` only to the first claimant. An existing running record
    refuses even the same identity: there is no automatic retry after a possible
    partial read. A matching complete record returns ``complete`` after checking
    its result manifest hash. Different experiment/plan identities are locked.
    """
    _identity(dataset_id, experiment_id, plan_sha256)
    root = Path(ledger_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f"{dataset_id}.json"
    payload = {
        "ledger_version": LEDGER_VERSION,
        "dataset_id": dataset_id,
        "experiment_id": experiment_id,
        "plan_sha256": plan_sha256,
        "status": "running",
        "started_at": _now(),
    }
    temporary = _write_temporary(root, dataset_id, payload)
    try:
        try:
            # A same-filesystem hard link both publishes a complete JSON record
            # atomically and fails exclusively if another claimant already won.
            os.link(temporary, path)
        except FileExistsError:
            ledger = read_final_evaluation(root, dataset_id)
            _matches(ledger, experiment_id, plan_sha256)
            if ledger["status"] == "running":
                raise FinalTestLockedError(f"{_LOCKED} {_RECOVERY}") from None
            verify_cached_evaluation(root, dataset_id, experiment_id, plan_sha256)
            return "complete"
        _sync_directory(root)
        return "claimed"
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _completion_lock(root: Path, dataset_id: str) -> Iterator[None]:
    # Keep the empty lock inode: unlinking lock files can create two independent
    # locks while another process still holds the original descriptor.
    descriptor = os.open(root / f".{dataset_id}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def complete_final_evaluation(
    ledger_root: Path,
    dataset_id: str,
    experiment_id: str,
    plan_sha256: str,
    *,
    results_dir: Path,
    results_manifest_sha256: str,
) -> None:
    """Atomically finish a matching running reservation after results publish.

    The supplied hash must match the existing result ``manifest.json``. Failures
    preserve the reservation; an already complete ledger is never overwritten.
    A local advisory lock serializes concurrent completions before rechecking
    status, so exactly one running-to-complete transition can succeed.
    """
    _identity(dataset_id, experiment_id, plan_sha256)
    _digest(results_manifest_sha256, "results_manifest_sha256")
    root = Path(ledger_root)
    if not root.is_dir():
        raise FinalTestLedgerError("Final-test ledger root does not exist")
    with _completion_lock(root, dataset_id):
        ledger = read_final_evaluation(root, dataset_id)
        _matches(ledger, experiment_id, plan_sha256)
        if ledger["status"] != "running":
            raise FinalTestLockedError(f"{_LOCKED} Reuse the completed cached result.")
        try:
            resolved_results = Path(results_dir).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise FinalTestLedgerError(
                "Final-test results directory is unavailable"
            ) from exc
        if _hash_manifest(resolved_results) != results_manifest_sha256:
            raise FinalTestLedgerError("Final-test result manifest hash does not match")
        completed = {
            **ledger,
            "status": "complete",
            "results_dir": str(resolved_results),
            "results_manifest_sha256": results_manifest_sha256,
            "completed_at": _now(),
        }
        _validate_ledger(completed, dataset_id)
        temporary = _write_temporary(root, dataset_id, completed)
        try:
            os.replace(temporary, root / f"{dataset_id}.json")
            _sync_directory(root)
        finally:
            temporary.unlink(missing_ok=True)
