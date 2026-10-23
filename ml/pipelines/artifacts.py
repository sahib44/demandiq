"""Small shared helpers for immutable local analytical runs."""

import json
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from ml.data.acquisition import canonical_json, sha256_file
from ml.pipelines.ingestion import ArtifactError


def write_json(path: Path, value: Any) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def inventory(directory: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path != directory / "manifest.json":
            entry: dict[str, Any] = {"sha256": sha256_file(path)}
            if path.suffix == ".parquet":
                entry["rows"] = pq.read_metadata(path).num_rows
            result[path.relative_to(directory).as_posix()] = entry
    return result


def verify_run(
    directory: Path, *, required: set[str], expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Verify complete inventory before any model deserialization or cache reuse."""
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in (expected or {}).items()
        ):
            raise ArtifactError("Run identity does not match the requested experiment")
        entries = manifest["artifacts"]
        if not isinstance(entries, dict) or not required.issubset(entries):
            raise ArtifactError("Run artifact inventory is incomplete")
        for name in entries:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ArtifactError("Run artifact path is invalid")
        if inventory(directory) != entries:
            raise ArtifactError("Run artifact integrity or row counts do not match")
        return manifest
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ArtifactError(
            "Run manifest/artifacts are incomplete or unreadable"
        ) from exc
