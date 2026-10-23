"""Copy verified trusted artifacts into a portable local demo bundle.

No training or evaluation runs here. The original completed ledger is retained
byte-for-byte as provenance. Only the copied ledger's absolute results_dir is
relocated; its reservation, timestamps, experiment, plan and results hash remain
unchanged. Generated bundles contain private processed data and trusted pickles:
keep them local/ignored, outside image build contexts and source control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from ml.data.acquisition import canonical_json, sha256_file
from ml.evaluation.final_test import read_final_evaluation, verify_cached_evaluation
from ml.pipelines.artifacts import inventory, verify_run, write_json
from ml.pipelines.ingestion import ArtifactError, verify_dataset
from ml.pipelines.inventory import load_frozen_inputs
from scripts.demo_backend import DEFAULT_DATASET, DEFAULT_RUN

BUNDLE_VERSION = 1


def _read(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("Demo bundle metadata is missing or unreadable") from exc
    if not isinstance(result, dict):
        raise ArtifactError("Demo bundle metadata must be a JSON object")
    return result


def _runtime_path(value: str | Path) -> str:
    text = str(value)
    path = PurePosixPath(text)
    if (
        not path.is_absolute()
        or str(path) == "/"
        or ".." in path.parts
        or "\\" in text
        or "\0" in text
        or str(path) != text
    ):
        raise ValueError("runtime_root must be a normalized absolute POSIX directory")
    return str(path)


def _regular_tree(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("Bundle inputs must be regular local directories")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ArtifactError("Demo bundle trees cannot contain symlinks")


def _copy_files(source: Path, destination: Path, names: set[str]) -> None:
    _regular_tree(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(names):
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ArtifactError("Demo artifact path is invalid")
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ArtifactError("Demo artifact is not a regular file")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _identity(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json(
            {name: value for name, value in manifest.items() if name != "bundle_id"}
        ).encode()
    ).hexdigest()


def _paths(manifest: dict[str, Any]) -> dict[str, str]:
    dataset, run = manifest["dataset_id"], manifest["run_id"]
    return {
        "dataset": f"data/processed/{dataset}",
        "training": f"artifacts/phase3/{run}",
        "evaluation": f"artifacts/phase3/evaluations/{run}",
        "ledger": f"data/evaluation-ledger/{dataset}.json",
        "original_ledger": f"provenance/original-ledger/{dataset}.json",
    }


def verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Verify inventory, lineage and the single permitted copied-ledger change."""
    root = Path(bundle_dir)
    _regular_tree(root)
    manifest = _read(root / "manifest.json")
    try:
        if (
            manifest["bundle_version"] != BUNDLE_VERSION
            or manifest["bundle_id"] != _identity(manifest)
            or _runtime_path(manifest["runtime_root"]) != manifest["runtime_root"]
        ):
            raise ArtifactError("Demo bundle identity is inconsistent")
        paths = _paths(manifest)
        verify_run(
            root,
            required={
                paths["ledger"],
                paths["original_ledger"],
                *(
                    f"{paths[key]}/manifest.json"
                    for key in ("dataset", "training", "evaluation")
                ),
            },
            expected={"bundle_version": BUNDLE_VERSION},
        )
        dataset = verify_dataset(root / paths["dataset"])
        training = verify_run(
            root / paths["training"],
            required={"plan.json"},
            expected={
                "experiment_id": manifest["run_id"],
                "dataset_id": manifest["dataset_id"],
                "state": "frozen_pretest",
            },
        )
        evaluation = verify_run(
            root / paths["evaluation"],
            required={
                "predictions.parquet",
                "evaluation_metadata.json",
                "metrics.json",
                "interval_metrics.json",
            },
            expected={
                "experiment_id": manifest["run_id"],
                "dataset_id": manifest["dataset_id"],
                "plan_sha256": training["plan_sha256"],
                "evaluation_scope": "test",
            },
        )
        original = read_final_evaluation(
            root / "provenance/original-ledger", manifest["dataset_id"]
        )
        relocated = read_final_evaluation(
            root / "data/evaluation-ledger", manifest["dataset_id"]
        )
        changed = sorted(name for name in original if original[name] != relocated[name])
        provenance = manifest["ledger_relocation"]
        expected_result_dir = f"{manifest['runtime_root']}/{paths['evaluation']}"
        expected_sources = {
            "dataset_manifest_sha256": sha256_file(
                root / paths["dataset"] / "manifest.json"
            ),
            "training_manifest_sha256": sha256_file(
                root / paths["training"] / "manifest.json"
            ),
            "evaluation_manifest_sha256": sha256_file(
                root / paths["evaluation"] / "manifest.json"
            ),
        }
        if (
            dataset.manifest["dataset_id"] != manifest["dataset_id"]
            or original["status"] != "complete"
            or original["experiment_id"] != manifest["run_id"]
            or original["plan_sha256"] != training["plan_sha256"]
            or original["plan_sha256"] != evaluation["plan_sha256"]
            or original["results_manifest_sha256"]
            != expected_sources["evaluation_manifest_sha256"]
            or changed not in ([], ["results_dir"])
            or provenance["changed_fields"] != changed
            or provenance["original_results_dir"] != original["results_dir"]
            or provenance["relocated_results_dir"] != expected_result_dir
            or relocated["results_dir"] != expected_result_dir
            or provenance["original_sha256"]
            != sha256_file(root / paths["original_ledger"])
            or provenance["copied_sha256"] != sha256_file(root / paths["ledger"])
            or manifest["source"] != expected_sources
        ):
            raise ArtifactError(
                "Demo copied ledger/provenance contradicts its frozen source"
            )
        return manifest
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("Demo bundle metadata or lineage is invalid") from exc


def prepare_bundle(
    dataset_dir: Path,
    run_dir: Path,
    ledger_dir: Path,
    output_dir: Path,
    *,
    runtime_root: str = "/runtime",
) -> dict[str, Any]:
    """Publish a deterministic copied bundle; never mutate any source artifact."""
    target_root = _runtime_path(runtime_root)
    dataset_dir, run_dir, ledger_dir, output = map(
        lambda path: Path(path).resolve(),
        (dataset_dir, run_dir, ledger_dir, output_dir),
    )
    # Refuse accidental publication over/inside the protected sources.
    if any(
        output == source
        or output.is_relative_to(source)
        or source.is_relative_to(output)
        for source in (dataset_dir, run_dir, ledger_dir)
    ):
        raise ValueError("Bundle output must be separate from source directories")
    _regular_tree(dataset_dir)
    _regular_tree(run_dir)
    dataset = verify_dataset(dataset_dir)
    plan, _, evaluation_dir = load_frozen_inputs(run_dir, ledger_dir)
    if plan["dataset_id"] != dataset.manifest["dataset_id"]:
        raise ArtifactError("Dataset and frozen experiment identities differ")
    _regular_tree(evaluation_dir)
    original_path = ledger_dir / f"{plan['dataset_id']}.json"
    original_bytes = original_path.read_bytes()
    original = read_final_evaluation(ledger_dir, plan["dataset_id"])
    paths = _paths(plan | {"run_id": plan["experiment_id"]})
    relocated = original | {"results_dir": f"{target_root}/{paths['evaluation']}"}
    training_manifest = _read(run_dir / "manifest.json")
    evaluation_manifest = _read(evaluation_dir / "manifest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".demo-bundle-", dir=output.parent))
    try:
        for source, relative, manifest in (
            (dataset_dir, paths["dataset"], dataset.manifest),
            (run_dir, paths["training"], training_manifest),
            (evaluation_dir, paths["evaluation"], evaluation_manifest),
        ):
            _copy_files(
                source, staging / relative, {"manifest.json", *manifest["artifacts"]}
            )
        copied_ledger = staging / paths["ledger"]
        copied_ledger.parent.mkdir(parents=True)
        write_json(copied_ledger, relocated)
        archived_ledger = staging / paths["original_ledger"]
        archived_ledger.parent.mkdir(parents=True)
        archived_ledger.write_bytes(original_bytes)
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "dataset_id": plan["dataset_id"],
            "run_id": plan["experiment_id"],
            "runtime_root": target_root,
            "source": {
                "dataset_manifest_sha256": sha256_file(dataset_dir / "manifest.json"),
                "training_manifest_sha256": sha256_file(run_dir / "manifest.json"),
                "evaluation_manifest_sha256": sha256_file(
                    evaluation_dir / "manifest.json"
                ),
            },
            "ledger_relocation": {
                "changed_fields": sorted(
                    name for name in original if original[name] != relocated[name]
                ),
                "original_results_dir": original["results_dir"],
                "relocated_results_dir": relocated["results_dir"],
                "original_sha256": sha256_file(original_path),
                "copied_sha256": sha256_file(copied_ledger),
            },
            "scope": "trusted local copied completed evaluation; no new training or test evaluation",
            "artifacts": inventory(staging),
        }
        manifest["bundle_id"] = _identity(manifest)
        write_json(staging / "manifest.json", manifest)
        verify_bundle(staging)
        if original_path.read_bytes() != original_bytes:
            raise ArtifactError(
                "Original evaluation ledger changed during bundle preparation"
            )
        if output.exists():
            existing = verify_bundle(output)
            if existing != manifest:
                raise ArtifactError(
                    "Bundle output already contains another immutable bundle"
                )
            return existing
        staging.rename(output)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _install_tree(source: Path, target: Path) -> None:
    if target.exists():
        _regular_tree(target)
        if (
            inventory(source) != inventory(target)
            or (source / "manifest.json").read_bytes()
            != (target / "manifest.json").read_bytes()
        ):
            raise ArtifactError(
                "Runtime already contains different frozen artifacts; preserve it"
            )
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".demo-install-", dir=target.parent))
    try:
        _copy_files(
            source,
            staging,
            {
                path.relative_to(source).as_posix()
                for path in source.rglob("*")
                if path.is_file()
            },
        )
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def install_bundle(
    bundle_dir: Path,
    runtime_root: Path,
    *,
    if_present: bool = False,
    uid: int | None = None,
) -> dict[str, Any]:
    """Install into explicit volumes without replacing an existing ledger/run."""
    bundle_dir, runtime_root = Path(bundle_dir), Path(_runtime_path(runtime_root))
    if runtime_root.is_symlink():
        raise ArtifactError("Runtime root cannot be a symlink")
    if uid is not None and (type(uid) is not int or not 1 <= uid <= 2**31 - 1):
        raise ValueError("uid must be a positive operating-system user ID")
    missing = not bundle_dir.exists() or (
        bundle_dir.is_dir() and not any(bundle_dir.iterdir())
    )
    if missing and if_present:
        manifest = None
    else:
        manifest = verify_bundle(bundle_dir)
        if manifest["runtime_root"] != str(runtime_root):
            raise ArtifactError(
                "Runtime mount path differs from the copied ledger target"
            )
    for name in ("data", "artifacts"):
        directory = runtime_root / name
        directory.mkdir(parents=True, exist_ok=True)
        _regular_tree(directory)
    if manifest is not None:
        paths = _paths(manifest)
        for name in ("dataset", "training", "evaluation"):
            _install_tree(bundle_dir / paths[name], runtime_root / paths[name])
        target = runtime_root / paths["ledger"]
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = (bundle_dir / paths["ledger"]).read_bytes()
        if target.exists():
            if target.is_symlink() or target.read_bytes() != contents:
                raise ArtifactError(
                    "Runtime has a different evaluation ledger; preserve it"
                )
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".ledger-", dir=target.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        verify_cached_evaluation(
            target.parent,
            manifest["dataset_id"],
            manifest["run_id"],
            _read(runtime_root / paths["training"] / "manifest.json")["plan_sha256"],
        )
        provenance = runtime_root / "artifacts/demo-bundles" / manifest["bundle_id"]
        provenance.mkdir(parents=True, exist_ok=True)
        for source, name in (
            (bundle_dir / "manifest.json", "bundle-manifest.json"),
            (bundle_dir / paths["original_ledger"], "original-ledger.json"),
        ):
            destination = provenance / name
            if destination.exists() and destination.read_bytes() != source.read_bytes():
                raise ArtifactError("Runtime bundle provenance has changed")
            shutil.copyfile(source, destination)
    if uid is not None:
        for directory in (runtime_root / "data", runtime_root / "artifacts"):
            _regular_tree(directory)
            for path in (directory, *directory.rglob("*")):
                os.chown(path, uid, uid)
    return {
        "status": "installed" if manifest is not None else "empty_runtime",
        "bundle_id": manifest["bundle_id"] if manifest is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="Verify and copy existing completed local artifacts"
    )
    prepare.add_argument(
        "--dataset-dir", type=Path, default=Path("data/processed") / DEFAULT_DATASET
    )
    prepare.add_argument(
        "--run-dir", type=Path, default=Path("artifacts/phase3") / DEFAULT_RUN
    )
    prepare.add_argument(
        "--ledger-dir", type=Path, default=Path("data/evaluation-ledger")
    )
    prepare.add_argument("--output-dir", type=Path, default=Path(".cache/demo-bundle"))
    prepare.add_argument("--runtime-root", default="/runtime")
    install = commands.add_parser(
        "install", help="Seed explicit runtime volumes from a verified bundle"
    )
    install.add_argument("--bundle-dir", type=Path, required=True)
    install.add_argument("--runtime-root", type=Path, default=Path("/runtime"))
    install.add_argument("--if-present", action="store_true")
    install.add_argument("--uid", type=int)
    verify = commands.add_parser(
        "verify", help="Verify bundle bytes and copied-ledger provenance"
    )
    verify.add_argument("--bundle-dir", type=Path, default=Path(".cache/demo-bundle"))
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_bundle(
            args.dataset_dir,
            args.run_dir,
            args.ledger_dir,
            args.output_dir,
            runtime_root=args.runtime_root,
        )
    elif args.command == "install":
        result = install_bundle(
            args.bundle_dir, args.runtime_root, if_present=args.if_present, uid=args.uid
        )
    else:
        result = verify_bundle(args.bundle_dir)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "bundle_id", "dataset_id", "run_id")
                if key in result
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
