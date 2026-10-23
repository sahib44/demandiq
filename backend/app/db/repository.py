"""Atomic, idempotent metadata registration after immutable files are published."""

import json
import re
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from backend.app.db.models import DataQualityReport, Dataset, Product


class DatasetConflictError(ValueError):
    """The same dataset identifier was used for different immutable metadata."""


def postgres_url(database_url: str) -> URL:
    """Require PostgreSQL with psycopg 3, without echoing credentials on error."""
    try:
        url = make_url(database_url)
    except (ArgumentError, TypeError, ValueError) as exc:
        raise ValueError("A valid PostgreSQL DATABASE_URL is required.") from exc
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("DATABASE_URL must use postgresql or postgresql+psycopg.")
    if not url.database:
        raise ValueError("DATABASE_URL must specify a PostgreSQL database name.")
    return url.set(drivername="postgresql+psycopg")


def _json_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object.")
    try:
        # Reject NaN/Infinity; normalize JSON-compatible containers before comparison.
        result = json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field} must contain finite, JSON-compatible values."
        ) from exc
    return result


def _validated_payload(
    manifest: dict[str, Any], report: dict[str, Any], products: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest = _json_object(manifest, "manifest")
    report = _json_object(report, "report")
    for field in ("dataset_id", "source_sha256"):
        if not isinstance(manifest.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{64}", manifest[field]
        ):
            raise ValueError(f"manifest.{field} must be a lowercase SHA-256 digest.")
    version = manifest.get("cleaning_version")
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        raise ValueError("manifest.cleaning_version must contain 1–64 characters.")
    for field in ("config", "artifacts"):
        _json_object(manifest.get(field), f"manifest.{field}")
    artifact_dir = manifest.get("artifact_dir")
    if not isinstance(artifact_dir, str) or not artifact_dir.strip():
        raise ValueError("manifest.artifact_dir must be a nonempty path.")
    for field in ("original_rows", "cleaned_rows"):
        value = manifest.get(field)
        if type(value) is not int or value < 0 or value > 2**63 - 1:
            raise ValueError(
                f"manifest.{field} must be a nonnegative signed 64-bit integer."
            )
    if manifest["cleaned_rows"] > manifest["original_rows"]:
        raise ValueError("Cleaned row count cannot exceed original row count.")
    if not isinstance(products, list):
        raise ValueError("products must be a list of catalog entries.")
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in products:
        if not isinstance(product, dict) or set(product) != {
            "stock_code",
            "description",
        }:
            raise ValueError(
                "Each product must contain only stock_code and description."
            )
        code = product["stock_code"]
        if not isinstance(code, str) or not code.strip() or len(code) > 128:
            raise ValueError("Product stock_code must contain 1–128 characters.")
        if code in seen:
            raise ValueError("Product catalog contains duplicate stock codes.")
        description = product["description"]
        if description is not None and not isinstance(description, str):
            raise ValueError("Product description must be text or null.")
        seen.add(code)
        catalog.append({"stock_code": code, "description": description})
    catalog.sort(key=lambda item: item["stock_code"])
    return manifest, report, catalog


def persist_dataset(
    database_url: str,
    manifest: dict[str, Any],
    report: dict[str, Any],
    products: list[dict[str, Any]],
) -> str:
    """Register dataset/report/catalog together, or return an identical existing ID.

    Migrations must have run first. PostgreSQL advisory transaction locks serialize
    imports of the same ID, including concurrent first imports. Any exception rolls
    back the entire registration. Artifact files must already be published and
    verified; this transaction does not attempt to roll back filesystem writes.
    """
    url = postgres_url(database_url)
    manifest, report, catalog = _validated_payload(manifest, report, products)
    dataset_id = manifest["dataset_id"]
    lock_key = int.from_bytes(bytes.fromhex(dataset_id)[:8], "big", signed=True)
    engine = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            session.execute(select(func.pg_advisory_xact_lock(lock_key)))
            existing = session.get(Dataset, dataset_id)
            if existing is not None:
                quality = session.get(DataQualityReport, dataset_id)
                stored_catalog = [
                    {"stock_code": row.stock_code, "description": row.description}
                    for row in session.scalars(
                        select(Product)
                        .where(Product.dataset_id == dataset_id)
                        .order_by(Product.stock_code)
                    )
                ]
                # PostgreSQL collation may differ from Python's code-point order.
                stored_catalog.sort(key=lambda item: item["stock_code"])
                if (
                    existing.manifest != manifest
                    or quality is None
                    or quality.report != report
                    or stored_catalog != catalog
                ):
                    raise DatasetConflictError(
                        "Dataset ID is already registered with different metadata."
                    )
                return dataset_id
            session.add(
                Dataset(
                    dataset_id=dataset_id,
                    source_sha256=manifest["source_sha256"],
                    cleaning_version=manifest["cleaning_version"],
                    status="ready",
                    original_rows=manifest["original_rows"],
                    cleaned_rows=manifest["cleaned_rows"],
                    config=manifest["config"],
                    artifacts=manifest["artifacts"],
                    artifact_dir=manifest["artifact_dir"],
                    manifest=manifest,
                )
            )
            # Explicit flush establishes the FK parent without ORM relationships.
            session.flush()
            session.add(DataQualityReport(dataset_id=dataset_id, report=report))
            session.add_all(
                Product(dataset_id=dataset_id, **product) for product in catalog
            )
            session.flush()
        return dataset_id
    finally:
        engine.dispose()
