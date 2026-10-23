"""Relational metadata for immutable, privacy-safe dataset artifacts."""

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


class Dataset(Base):
    """A successfully published immutable set of analytical files."""

    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("dataset_id ~ '^[0-9a-f]{64}$'", name="dataset_id_sha256"),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256"),
        CheckConstraint("length(trim(cleaning_version)) > 0", name="cleaning_version"),
        CheckConstraint("status IN ('ready')", name="status"),
        CheckConstraint("original_rows >= 0", name="original_rows"),
        CheckConstraint(
            "cleaned_rows >= 0 AND cleaned_rows <= original_rows", name="cleaned_rows"
        ),
        CheckConstraint("length(trim(artifact_dir)) > 0", name="artifact_dir"),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="config_object"),
        CheckConstraint("jsonb_typeof(artifacts) = 'object'", name="artifacts_object"),
        CheckConstraint("jsonb_typeof(manifest) = 'object'", name="manifest_object"),
    )

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cleaning_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ready"
    )
    original_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cleaned_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataQualityReport(Base):
    """Exactly one aggregate cleaning report per registered dataset."""

    __tablename__ = "data_quality_reports"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(report) = 'object'", name="report_object"),
    )

    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        primary_key=True,
    )
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class Product(Base):
    """The full accepted product catalog, without ranking or future selection."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("length(trim(stock_code)) > 0", name="stock_code"),
    )

    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stock_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


def _digest_check(field: str) -> CheckConstraint:
    return CheckConstraint(f"{field} ~ '^[0-9a-f]{{64}}$'", name=f"{field}_sha256")


def _object_check(field: str, *, nullable: bool = False) -> CheckConstraint:
    expression = f"jsonb_typeof({field}) = 'object'"
    if nullable:
        expression = f"{field} IS NULL OR ({expression})"
    return CheckConstraint(expression, name=f"{field}_object")


def _relative_path_check(field: str) -> CheckConstraint:
    return CheckConstraint(
        f"length(trim({field})) > 0 AND {field} = trim({field}) "
        f"AND {field} !~ '^/' AND {field} !~ '^[A-Za-z]:' "
        f"AND {field} !~ '(^|/)[.][.]?(/|$)' AND strpos({field}, chr(92)) = 0",
        name=f"{field}_relative",
    )


class Job(Base):
    """Durable idempotent work, with leases valid only while running."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "job_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name="job_id_uuid",
        ),
        CheckConstraint(
            "kind IN ('dataset_import', 'training', 'forecasting', 'inventory')",
            name="kind",
        ),
        _object_check("payload"),
        _digest_check("payload_hash"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status"
        ),
        CheckConstraint("max_attempts BETWEEN 1 AND 5", name="max_attempts"),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts"),
        CheckConstraint(
            "(status = 'running' AND locked_by IS NOT NULL AND length(trim(locked_by)) > 0 "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND locked_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="lease_state",
        ),
        CheckConstraint(
            "lease_token IS NULL OR lease_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name="lease_token_uuid",
        ),
        _object_check("result", nullable=True),
        CheckConstraint(
            "error_code IS NULL OR length(trim(error_code)) > 0", name="error_code"
        ),
        UniqueConstraint("kind", "idempotency_key"),
        Index(
            "ix_jobs_queued_available",
            "available_at",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_jobs_running_expiry",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
    )

    job_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TrainingRun(Base):
    """Immutable frozen training identity and references to private artifacts."""

    __tablename__ = "training_runs"
    __table_args__ = (
        _digest_check("run_id"),
        _object_check("config"),
        _object_check("metrics"),
        _relative_path_check("artifact_dir"),
        _digest_check("manifest_sha256"),
        UniqueConstraint("run_id", "dataset_id"),
    )
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelArtifact(Base):
    """A trusted local serialized pipeline with content and training lineage."""

    __tablename__ = "model_artifacts"
    __table_args__ = (
        _digest_check("model_id"),
        _digest_check("sha256"),
        CheckConstraint(
            "family IN ('ridge', 'random_forest', 'xgboost')", name="family"
        ),
        _relative_path_check("artifact_key"),
        _object_check("metadata_json"),
    )
    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("training_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WeeklyDemand(Base):
    """Training-run-scoped gross and credit facts, never customer-level data."""

    __tablename__ = "weekly_demand"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "dataset_id"],
            ["training_runs.run_id", "training_runs.dataset_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "stock_code"],
            ["products.dataset_id", "products.stock_code"],
            ondelete="CASCADE",
        ),
        CheckConstraint("extract(isodow from week) = 1", name="week_monday"),
        CheckConstraint(
            "gross_units >= 0 AND returned_units >= 0 AND cancellation_units >= 0",
            name="movement_units",
        ),
        CheckConstraint(
            "net_units::numeric = gross_units::numeric - returned_units::numeric - cancellation_units::numeric",
            name="net_units",
        ),
        CheckConstraint(
            "revenue >= 0 AND revenue < 'Infinity'::float8", name="revenue_finite"
        ),
        CheckConstraint(
            "transactions >= 0 AND unique_customers >= 0 AND unique_customers <= transactions",
            name="transaction_counts",
        ),
        CheckConstraint(
            "(gross_units = 0 AND average_price IS NULL AND revenue = 0 AND transactions = 0 AND unique_customers = 0) OR "
            "(gross_units > 0 AND average_price IS NOT NULL AND average_price > 0 AND average_price < 'Infinity'::float8)",
            name="average_price",
        ),
    )
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    week: Mapped[date] = mapped_column(Date, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    gross_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    returned_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cancellation_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, nullable=False)
    transactions: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unique_customers: Mapped[int] = mapped_column(BigInteger, nullable=False)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)


class ForecastBatch(Base):
    """One generated origin or already-observed retrospective forecast collection."""

    __tablename__ = "forecast_batches"
    __table_args__ = (
        _digest_check("forecast_id"),
        _object_check("metadata_json"),
        _relative_path_check("artifact_dir"),
        CheckConstraint("scope IN ('one_week', 'retrospective')", name="scope"),
    )
    forecast_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("training_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ForecastValue(Base):
    """A product-week method forecast with finite ordered empirical bounds."""

    __tablename__ = "forecast_values"
    __table_args__ = (
        CheckConstraint(
            "length(trim(stock_code)) > 0 AND stock_code = trim(stock_code)",
            name="stock_code",
        ),
        CheckConstraint("length(trim(method)) > 0", name="method"),
        CheckConstraint("extract(isodow from week) = 1", name="week_monday"),
        CheckConstraint(
            "lower >= 0 AND lower < 'Infinity'::float8 AND point >= lower AND point <= upper AND upper < 'Infinity'::float8",
            name="bounds_finite",
        ),
        CheckConstraint("actual IS NULL OR actual >= 0", name="actual"),
        CheckConstraint(
            "nominal_coverage > 0 AND nominal_coverage < 1", name="nominal_coverage"
        ),
        CheckConstraint(
            "length(trim(uncertainty_label)) > 0", name="uncertainty_label"
        ),
    )
    forecast_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("forecast_batches.forecast_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stock_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    week: Mapped[date] = mapped_column(Date, primary_key=True)
    method: Mapped[str] = mapped_column(String(64), primary_key=True)
    point: Mapped[float] = mapped_column(Float, nullable=False)
    lower: Mapped[float] = mapped_column(Float, nullable=False)
    upper: Mapped[float] = mapped_column(Float, nullable=False)
    actual: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nominal_coverage: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty_label: Mapped[str] = mapped_column(Text, nullable=False)


class InventoryConfiguration(Base):
    """Illustrative inventory assumptions, identified independently of datasets."""

    __tablename__ = "inventory_configurations"
    __table_args__ = (
        _digest_check("configuration_id"),
        _object_check("config"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    )
    configuration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SimulationScenario(Base):
    """Retrospective simulation lineage, economics and private artifact reference."""

    __tablename__ = "simulation_scenarios"
    __table_args__ = (
        _digest_check("scenario_id"),
        _digest_check("manifest_sha256"),
        _relative_path_check("artifact_dir"),
        _object_check("summary"),
    )
    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    forecast_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("forecast_batches.forecast_id", ondelete="CASCADE"),
        nullable=False,
    )
    configuration_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("inventory_configurations.configuration_id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_dir: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SimulationResult(Base):
    """Weekly simulated outcomes with conserved demand and JSON detail fields."""

    __tablename__ = "simulation_results"
    __table_args__ = (
        CheckConstraint("length(trim(policy)) > 0", name="policy"),
        CheckConstraint(
            "length(trim(stock_code)) > 0 AND stock_code = trim(stock_code)",
            name="stock_code",
        ),
        CheckConstraint("extract(isodow from week) = 1", name="week_monday"),
        CheckConstraint(
            "actual >= 0 AND fulfilled_units >= 0 AND lost_units >= 0 AND ending_inventory >= 0",
            name="nonnegative_units",
        ),
        CheckConstraint(
            "actual::numeric = fulfilled_units::numeric + lost_units::numeric",
            name="demand_conservation",
        ),
        _object_check("details"),
        CheckConstraint(
            "NOT (details ?| ARRAY['scenario_id', 'policy', 'stock_code', 'week', 'actual', 'fulfilled_units', 'lost_units', 'ending_inventory'])",
            name="details_excludes_columns",
        ),
    )
    scenario_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("simulation_scenarios.scenario_id", ondelete="CASCADE"),
        primary_key=True,
    )
    policy: Mapped[str] = mapped_column(String(64), primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    week: Mapped[date] = mapped_column(Date, primary_key=True)
    actual: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fulfilled_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lost_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ending_inventory: Mapped[int] = mapped_column(BigInteger, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
