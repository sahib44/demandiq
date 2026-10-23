"""Immutable, privacy-safe Phase 1 dataset publication and metadata registration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from ml.data.acquisition import canonical_json, sha256_file
from ml.data.cleaning import CLEANING_VERSION, clean_transactions
from ml.data.io import InputError, read_transactions

PIPELINE_VERSION = "1"
PARTITIONS = ("purchases", "cancellations", "returns")
ARTIFACT_NAMES = {f"{name}.parquet" for name in (*PARTITIONS, "audit")} | {
    "quality.json"
}


class ArtifactError(ValueError):
    """A dataset is incomplete, corrupt or incompatible with its expected version."""


@dataclass(frozen=True)
class IngestionResult:
    dataset_dir: Path
    manifest: dict[str, Any]
    report: dict[str, Any]


def verify_dataset(dataset_dir: Path) -> IngestionResult:
    """Verify a published dataset without parsing raw transaction values.

    The source/configuration-derived ID and every artifact hash/count are
    checked. This permits downstream pipelines to read only their allowed date
    partitions while still verifying complete-file integrity.
    """
    dataset_dir = Path(dataset_dir)
    try:
        manifest = json.loads((dataset_dir / "manifest.json").read_text())
        source_digest = manifest["source_sha256"]
        config = manifest["config"]
        if (
            not isinstance(source_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_digest)
            or not isinstance(config, dict)
        ):
            raise ArtifactError("Dataset source/configuration metadata is invalid")
        expected_id = hashlib.sha256(
            canonical_json({"source_sha256": source_digest, "config": config}).encode()
        ).hexdigest()
        return _verify_existing(dataset_dir, expected_id, source_digest, config)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ArtifactError("Could not verify dataset manifest") from exc


def _verify_existing(
    dataset_dir: Path, dataset_id: str, source_sha256: str, config: dict[str, Any]
) -> IngestionResult:
    try:
        manifest = json.loads((dataset_dir / "manifest.json").read_text())
        if (
            not isinstance(manifest, dict)
            or set(manifest)
            != {
                "dataset_id",
                "source_sha256",
                "cleaning_version",
                "config",
                "artifact_dir",
                "artifacts",
                "original_rows",
                "cleaned_rows",
            }
            or manifest["dataset_id"] != dataset_id
            or manifest["source_sha256"] != source_sha256
            or manifest["config"] != config
            or manifest["cleaning_version"] != CLEANING_VERSION
            or manifest["artifact_dir"] != dataset_id
            or not isinstance(manifest["artifacts"], dict)
            or set(manifest["artifacts"]) != ARTIFACT_NAMES
        ):
            raise ArtifactError("Dataset manifest does not match the requested version")
        for name, artifact in manifest["artifacts"].items():
            expected_keys = {"sha256"} if name == "quality.json" else {"sha256", "rows"}
            if (
                not isinstance(artifact, dict)
                or set(artifact) != expected_keys
                or not isinstance(artifact["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
            ):
                raise ArtifactError(f"Dataset artifact metadata is invalid: {name}")
            if sha256_file(dataset_dir / name) != artifact["sha256"]:
                raise ArtifactError(
                    f"Dataset artifact failed integrity verification: {name}"
                )
            if name.endswith(".parquet") and (
                type(artifact["rows"]) is not int
                or artifact["rows"] < 0
                or pq.read_metadata(dataset_dir / name).num_rows != artifact["rows"]
            ):
                raise ArtifactError(f"Dataset artifact row count is invalid: {name}")
        report = json.loads((dataset_dir / "quality.json").read_text())
        count_keys = (
            "original_rows",
            "cleaned_rows",
            "duplicate_rows",
            "rejected_rows",
            "purchase_rows",
            "cancellation_rows",
            "return_rows",
        )
        if not isinstance(report, dict) or any(
            type(report.get(key)) is not int or report[key] < 0 for key in count_keys
        ):
            raise ArtifactError("Quality report row counts are invalid")
        if any(
            type(manifest[key]) is not int or manifest[key] != report[key]
            for key in ("original_rows", "cleaned_rows")
        ):
            raise ArtifactError("Dataset manifest row counts contradict quality report")
        partition_counts = [
            manifest["artifacts"][f"{name}.parquet"]["rows"] for name in PARTITIONS
        ]
        if (
            partition_counts
            != [
                report[f"{name}_rows"]
                for name in ("purchase", "cancellation", "return")
            ]
            or sum(partition_counts) != report["cleaned_rows"]
            or manifest["artifacts"]["audit.parquet"]["rows"] != report["original_rows"]
            or report["original_rows"]
            != report["cleaned_rows"]
            + report["duplicate_rows"]
            + report["rejected_rows"]
        ):
            raise ArtifactError("Dataset row conservation does not hold")
        return IngestionResult(dataset_dir, manifest, report)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ArtifactError(
            "Dataset cache is incomplete; use a new output directory"
        ) from exc


def product_catalog(dataset_dir: Path) -> list[dict[str, str | None]]:
    """Catalog accepted products without ranking or future-dependent eligibility."""
    accepted = pd.concat(
        [
            pd.read_parquet(
                dataset_dir / f"{name}.parquet",
                columns=["source_row", "stock_code", "description"],
            )
            for name in PARTITIONS
        ],
        ignore_index=True,
    ).sort_values("source_row", kind="stable")
    # Prefer the earliest known description; never infer a missing description.
    catalog = accepted.groupby("stock_code", sort=True)["description"].first()
    return [
        {
            "stock_code": str(stock_code),
            "description": None if pd.isna(description) else str(description),
        }
        for stock_code, description in catalog.items()
    ]


def ingest_dataset(
    input_path: Path,
    output_root: Path,
    *,
    database_url: str | None = None,
) -> IngestionResult:
    """Validate/clean an input, publish atomically, optionally persist metadata.

    File outputs contain no wall-clock timings, raw customer identifiers or
    machine-specific source paths. Metadata registration can be retried after
    database failure without repeating or duplicating a completed import.
    """
    input_path = Path(input_path)
    output_root = Path(output_root)
    if input_path.suffix.lower() not in {".xlsx", ".csv"}:
        raise InputError("Supported input formats are .xlsx and UTF-8 .csv")
    try:
        source_digest = sha256_file(input_path)
    except OSError as exc:
        raise InputError("Input file is missing or unreadable") from exc
    config = {
        "cleaning_version": CLEANING_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "input_format": input_path.suffix.lower(),
    }
    dataset_id = hashlib.sha256(
        canonical_json({"source_sha256": source_digest, "config": config}).encode()
    ).hexdigest()
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / dataset_id
    if final.exists():
        result = _verify_existing(final, dataset_id, source_digest, config)
    else:
        staging = Path(tempfile.mkdtemp(prefix=".ingest-", dir=output_root))
        try:
            frame = read_transactions(input_path)
            if sha256_file(input_path) != source_digest:
                raise InputError(
                    "Input changed while being read; retry with a stable file"
                )
            cleaned = clean_transactions(frame)
            artifact_info: dict[str, Any] = {}
            for name in (*PARTITIONS, "audit"):
                data = getattr(cleaned, name)
                path = staging / f"{name}.parquet"
                data.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
                artifact_info[path.name] = {
                    "sha256": sha256_file(path),
                    "rows": len(data),
                }
            report_path = staging / "quality.json"
            report_path.write_text(canonical_json(cleaned.report), encoding="utf-8")
            artifact_info[report_path.name] = {"sha256": sha256_file(report_path)}
            manifest = {
                "dataset_id": dataset_id,
                "source_sha256": source_digest,
                "cleaning_version": CLEANING_VERSION,
                "config": config,
                "artifact_dir": dataset_id,
                "artifacts": artifact_info,
                "original_rows": cleaned.report["original_rows"],
                "cleaned_rows": cleaned.report["cleaned_rows"],
            }
            (staging / "manifest.json").write_text(
                canonical_json(manifest), encoding="utf-8"
            )
            try:
                os.rename(staging, final)
            except OSError:
                if not final.exists():
                    raise
            result = _verify_existing(final, dataset_id, source_digest, config)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    if database_url is not None:
        # File-only data workflows do not need a running PostgreSQL instance.
        from backend.app.db.repository import persist_dataset

        persist_dataset(
            database_url, result.manifest, result.report, product_catalog(final)
        )
    return result
