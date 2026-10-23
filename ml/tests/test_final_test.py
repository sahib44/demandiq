"""Synthetic local-ledger tests: no official held-out observations are read."""

import hashlib
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from ml.evaluation.final_test import (
    LEDGER_VERSION,
    FinalTestLedgerError,
    FinalTestLockedError,
    claim_final_evaluation,
    complete_final_evaluation,
    read_final_evaluation,
    verify_cached_evaluation,
)

DATASET = "a" * 64
EXPERIMENT = "b" * 64
PLAN = "c" * 64
OTHER = "d" * 64


def ledger_path(root):
    return root / f"{DATASET}.json"


def claim(root, **changes):
    return claim_final_evaluation(
        root,
        changes.get("dataset_id", DATASET),
        changes.get("experiment_id", EXPERIMENT),
        changes.get("plan_sha256", PLAN),
    )


def results(directory, content='{"synthetic": true}\n'):
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def complete(root, directory, digest, **changes):
    return complete_final_evaluation(
        root,
        changes.get("dataset_id", DATASET),
        changes.get("experiment_id", EXPERIMENT),
        changes.get("plan_sha256", PLAN),
        results_dir=directory,
        results_manifest_sha256=digest,
    )


def rewrite(root, **changes):
    path = ledger_path(root)
    payload = json.loads(path.read_text())
    payload.update(changes)
    path.write_text(json.dumps(payload))


def test_first_claim_is_private_atomic_running_metadata(tmp_path):
    root = tmp_path / "new" / "ledger"
    before = datetime.now(UTC)
    assert claim(root) == "claimed"
    ledger = read_final_evaluation(root, DATASET)
    assert set(ledger) == {
        "ledger_version",
        "dataset_id",
        "experiment_id",
        "plan_sha256",
        "status",
        "started_at",
    }
    assert ledger["ledger_version"] == LEDGER_VERSION
    assert ledger["dataset_id"] == DATASET
    assert ledger["experiment_id"] == EXPERIMENT
    assert ledger["plan_sha256"] == PLAN
    assert ledger["status"] == "running"
    timestamp = datetime.fromisoformat(ledger["started_at"].replace("Z", "+00:00"))
    assert before <= timestamp <= datetime.now(UTC)
    assert timestamp.utcoffset().total_seconds() == 0
    assert stat.S_IMODE(ledger_path(root).stat().st_mode) == 0o600
    assert not list(root.glob("*.tmp"))
    assert not list(root.glob(".*.tmp"))
    assert "customer" not in ledger_path(root).read_text().lower()


def test_same_running_identity_refuses_automatic_retry_with_manual_recovery(tmp_path):
    claim(tmp_path)
    before = ledger_path(tmp_path).read_bytes()
    with pytest.raises(FinalTestLockedError, match="recover manually") as error:
        claim(tmp_path)
    assert "already reserved/evaluated" in str(error.value)
    assert "do not retune" in str(error.value)
    assert "Do not delete" in str(error.value)
    assert ledger_path(tmp_path).read_bytes() == before


@pytest.mark.parametrize("field", ["experiment_id", "plan_sha256"])
def test_different_experiment_or_plan_cannot_reuse_running_dataset(tmp_path, field):
    claim(tmp_path)
    with pytest.raises(
        FinalTestLockedError, match="already reserved/evaluated.*do not retune"
    ):
        claim(tmp_path, **{field: OTHER})
    assert read_final_evaluation(tmp_path, DATASET)["status"] == "running"


def test_different_dataset_has_independent_reservation(tmp_path):
    assert claim(tmp_path) == "claimed"
    assert claim(tmp_path, dataset_id=OTHER) == "claimed"
    assert len(list(tmp_path.glob("*.json"))) == 2


@pytest.mark.parametrize("field", ["dataset_id", "experiment_id", "plan_sha256"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "z" * 64,
        "../escape",
        "a" * 64 + "\n",
    ],
)
def test_identity_inputs_require_canonical_lowercase_sha256_before_writing(
    tmp_path, field, value
):
    with pytest.raises(FinalTestLedgerError, match=field):
        claim(tmp_path, **{field: value})
    assert list(tmp_path.iterdir()) == []


def test_exactly_one_concurrent_first_claim_wins(tmp_path):
    count = 16
    barrier = Barrier(count)

    def attempt(_):
        barrier.wait()
        try:
            return claim(tmp_path)
        except FinalTestLockedError:
            return "locked"

    with ThreadPoolExecutor(max_workers=count) as executor:
        states = list(executor.map(attempt, range(count)))
    assert states.count("claimed") == 1
    assert states.count("locked") == count - 1
    assert read_final_evaluation(tmp_path, DATASET)["status"] == "running"
    assert not list(tmp_path.glob(".*.tmp"))


def test_complete_matching_reservation_and_reuse_verified_cache(tmp_path):
    root, directory = tmp_path / "ledger", tmp_path / "synthetic-results"
    claim(root)
    running = read_final_evaluation(root, DATASET)
    digest = results(directory)
    assert complete(root, directory, digest) is None
    ledger = read_final_evaluation(root, DATASET)
    assert ledger["status"] == "complete"
    assert ledger["results_dir"] == str(directory.resolve())
    assert ledger["results_manifest_sha256"] == digest
    assert ledger["started_at"] == running["started_at"]
    assert ledger["completed_at"] >= ledger["started_at"]
    assert set(ledger) == set(running) | {
        "results_dir",
        "results_manifest_sha256",
        "completed_at",
    }
    assert verify_cached_evaluation(root, DATASET, EXPERIMENT, PLAN) == ledger
    before = ledger_path(root).read_bytes()
    assert claim(root) == "complete"
    assert ledger_path(root).read_bytes() == before
    assert stat.S_IMODE(ledger_path(root).stat().st_mode) == 0o600


@pytest.mark.parametrize("field", ["experiment_id", "plan_sha256"])
def test_completed_dataset_blocks_alternate_experiment_or_plan(tmp_path, field):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    complete(root, directory, results(directory))
    with pytest.raises(FinalTestLockedError, match="do not retune"):
        claim(root, **{field: OTHER})
    with pytest.raises(FinalTestLockedError, match="do not retune"):
        verify_cached_evaluation(
            root,
            DATASET,
            OTHER if field == "experiment_id" else EXPERIMENT,
            OTHER if field == "plan_sha256" else PLAN,
        )


@pytest.mark.parametrize("field", ["experiment_id", "plan_sha256"])
def test_completion_requires_matching_running_identity(tmp_path, field):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    digest = results(directory)
    before = ledger_path(root).read_bytes()
    with pytest.raises(FinalTestLockedError, match="do not retune"):
        complete(root, directory, digest, **{field: OTHER})
    assert ledger_path(root).read_bytes() == before


def test_completion_without_claim_cannot_create_completed_ledger(tmp_path):
    directory = tmp_path / "results"
    digest = results(directory)
    root = tmp_path / "missing-ledger"
    with pytest.raises(FinalTestLedgerError, match="root does not exist"):
        complete(root, directory, digest)
    root.mkdir()
    with pytest.raises(FinalTestLedgerError, match="missing"):
        complete(root, directory, digest)
    assert not ledger_path(root).exists()


def test_completion_cannot_overwrite_existing_complete_result(tmp_path):
    root, original = tmp_path / "ledger", tmp_path / "original"
    claim(root)
    complete(root, original, results(original))
    before = ledger_path(root).read_bytes()
    alternate = tmp_path / "alternate"
    with pytest.raises(FinalTestLockedError, match="Reuse the completed cached result"):
        complete(root, alternate, results(alternate, '{"alternate": true}'))
    assert ledger_path(root).read_bytes() == before


def test_exactly_one_concurrent_completion_transitions_to_immutable_result(tmp_path):
    root = tmp_path / "ledger"
    claim(root)
    count = 8
    directories = [tmp_path / f"synthetic-result-{i}" for i in range(count)]
    digests = [
        results(directory, json.dumps({"synthetic_result": i}))
        for i, directory in enumerate(directories)
    ]
    barrier = Barrier(count)

    def attempt(i):
        barrier.wait()
        try:
            complete(root, directories[i], digests[i])
            return "complete", i
        except FinalTestLockedError:
            return "locked", i

    with ThreadPoolExecutor(max_workers=count) as executor:
        states = list(executor.map(attempt, range(count)))
    winners = [i for status, i in states if status == "complete"]
    assert len(winners) == 1
    assert sum(status == "locked" for status, _ in states) == count - 1
    ledger = verify_cached_evaluation(root, DATASET, EXPERIMENT, PLAN)
    assert ledger["results_dir"] == str(directories[winners[0]].resolve())
    assert ledger["results_manifest_sha256"] == digests[winners[0]]


@pytest.mark.parametrize("digest", ["", "x" * 64, "a" * 63, "A" * 64, None])
def test_completion_rejects_malformed_result_digest_without_changing_running_state(
    tmp_path, digest
):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    results(directory)
    with pytest.raises(FinalTestLedgerError, match="results_manifest_sha256"):
        complete(root, directory, digest)
    assert read_final_evaluation(root, DATASET)["status"] == "running"


def test_completion_verifies_result_existence_and_hash_before_changing_state(tmp_path):
    root = tmp_path / "ledger"
    claim(root)
    with pytest.raises(FinalTestLedgerError, match="unavailable"):
        complete(root, tmp_path / "missing", OTHER)
    directory = tmp_path / "empty-results"
    directory.mkdir()
    with pytest.raises(FinalTestLedgerError, match="manifest.json"):
        complete(root, directory, OTHER)
    (directory / "manifest.json").write_text("{}")
    with pytest.raises(FinalTestLedgerError, match="hash does not match"):
        complete(root, directory, OTHER)
    assert read_final_evaluation(root, DATASET)["status"] == "running"


def test_cached_verification_refuses_running_record(tmp_path):
    claim(tmp_path)
    with pytest.raises(FinalTestLockedError, match="recover manually"):
        verify_cached_evaluation(tmp_path, DATASET, EXPERIMENT, PLAN)


def test_cached_tampered_manifest_never_authorizes_new_test_run(tmp_path):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    complete(root, directory, results(directory))
    before = ledger_path(root).read_bytes()
    (directory / "manifest.json").write_text('{"tampered": true}')
    with pytest.raises(FinalTestLedgerError, match="integrity verification"):
        verify_cached_evaluation(root, DATASET, EXPERIMENT, PLAN)
    with pytest.raises(FinalTestLedgerError, match="integrity verification"):
        claim(root)
    assert ledger_path(root).read_bytes() == before
    assert read_final_evaluation(root, DATASET)["status"] == "complete"


def test_cached_missing_manifest_fails_without_altering_completion(tmp_path):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    complete(root, directory, results(directory))
    (directory / "manifest.json").unlink()
    with pytest.raises(FinalTestLedgerError, match="manifest.json"):
        verify_cached_evaluation(root, DATASET, EXPERIMENT, PLAN)
    assert read_final_evaluation(root, DATASET)["status"] == "complete"


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_id": OTHER},
        {"experiment_id": "invalid"},
        {"plan_sha256": "A" * 64},
        {"ledger_version": 2},
        {"ledger_version": True},
        {"status": "failed"},
        {"status": []},
        {"started_at": "yesterday"},
        {"started_at": "2011-02-30T00:00:00Z"},
        {"started_at": "2011-01-01T00:00:00+01:00"},
        {"extra_customer_id": "SYNTHETIC-SENSITIVE-VALUE"},
        {"results_dir": "/unexpected"},
    ],
)
def test_malformed_or_tampered_running_metadata_fails_closed(tmp_path, changes):
    claim(tmp_path)
    rewrite(tmp_path, **changes)
    before = ledger_path(tmp_path).read_bytes()
    with pytest.raises(FinalTestLedgerError) as error:
        read_final_evaluation(tmp_path, DATASET)
    assert "SYNTHETIC-SENSITIVE-VALUE" not in str(error.value)
    with pytest.raises(FinalTestLedgerError):
        claim(tmp_path)
    assert ledger_path(tmp_path).read_bytes() == before


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{",
        "[]",
        "null",
        '{"status":"running","status":"complete"}',
        '{"status":NaN}',
        "x" * (64 * 1024 + 1),
    ],
)
def test_invalid_or_oversized_json_is_rejected_clearly(tmp_path, content):
    ledger_path(tmp_path).write_text(content)
    with pytest.raises(FinalTestLedgerError, match="ledger|Ledger"):
        read_final_evaluation(tmp_path, DATASET)
    with pytest.raises(FinalTestLedgerError):
        claim(tmp_path)


def test_missing_nonregular_and_symlink_ledgers_are_rejected(tmp_path):
    with pytest.raises(FinalTestLedgerError, match="missing"):
        read_final_evaluation(tmp_path, DATASET)
    ledger_path(tmp_path).mkdir()
    with pytest.raises(FinalTestLedgerError, match="regular"):
        read_final_evaluation(tmp_path, DATASET)
    ledger_path(tmp_path).rmdir()
    target = tmp_path / "unrelated.json"
    target.write_text("{}")
    ledger_path(tmp_path).symlink_to(target)
    with pytest.raises(FinalTestLedgerError, match="regular"):
        read_final_evaluation(tmp_path, DATASET)


@pytest.mark.parametrize(
    "changes",
    [
        {"results_manifest_sha256": "invalid"},
        {"results_dir": "relative/path"},
        {"results_dir": "/contains/../traversal"},
        {"results_dir": "/bad\0path"},
        {"results_dir": "/bad\ud800path"},
        {"completed_at": "2011-01-01T00:00:00Z"},
    ],
)
def test_completed_metadata_validation_rejects_invalid_paths_hashes_and_chronology(
    tmp_path, changes
):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    complete(root, directory, results(directory))
    rewrite(root, **changes)
    with pytest.raises(FinalTestLedgerError):
        read_final_evaluation(root, DATASET)


def test_missing_required_metadata_field_is_rejected(tmp_path):
    claim(tmp_path)
    payload = json.loads(ledger_path(tmp_path).read_text())
    del payload["started_at"]
    ledger_path(tmp_path).write_text(json.dumps(payload))
    with pytest.raises(FinalTestLedgerError, match="missing or unexpected fields"):
        read_final_evaluation(tmp_path, DATASET)


def test_manifest_symlinks_are_not_accepted_as_completed_artifacts(tmp_path):
    root, directory = tmp_path / "ledger", tmp_path / "results"
    claim(root)
    directory.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    (directory / "manifest.json").symlink_to(target)
    with pytest.raises(FinalTestLedgerError, match="regular manifest.json"):
        complete(root, directory, hashlib.sha256(b"{}").hexdigest())
    assert read_final_evaluation(root, DATASET)["status"] == "running"
