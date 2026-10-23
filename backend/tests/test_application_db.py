"""Application metadata and isolated PostgreSQL persistence checks.

Integration fixtures migrate and clear every DemandIQ table in TEST_DATABASE_URL.
They require a disposable database whose name ends in _test. Run this suite
serially with the other PostgreSQL suites; no connection is made without the URL.
All inserted records are synthetic aggregate facts, never source transactions.
"""

import os
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, delete, func, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.models import (
    Base,
    DataQualityReport,
    Dataset,
    ForecastBatch,
    ForecastValue,
    InventoryConfiguration,
    Job,
    ModelArtifact,
    Product,
    SimulationResult,
    SimulationScenario,
    TrainingRun,
    WeeklyDemand,
)
from backend.app.db.repository import postgres_url

ROOT = Path(__file__).resolve().parents[2]
DATASET = "a" * 64
RUN = "c" * 64
MODEL = "d" * 64
FORECAST = "e" * 64
CONFIGURATION = "f" * 64
SCENARIO = "1" * 64
DIGEST = "2" * 64
OTHER = "3" * 64
STOCK = "SYNTHETIC-A"
MONDAY = date(2011, 10, 10)
APPLICATION_MODELS = (
    Job,
    TrainingRun,
    ModelArtifact,
    WeeklyDemand,
    ForecastBatch,
    ForecastValue,
    InventoryConfiguration,
    SimulationScenario,
    SimulationResult,
)


def alembic_config(output_buffer=None):
    return Config(str(ROOT / "backend/alembic.ini"), output_buffer=output_buffer)


def checked_test_url(value):
    url = postgres_url(value)
    if not url.database.endswith("_test"):
        raise ValueError("Disposable PostgreSQL database name must end in _test.")
    return url


def dataset_values(dataset_id=DATASET):
    return {
        "dataset_id": dataset_id,
        "source_sha256": "b" * 64,
        "cleaning_version": "synthetic-v1",
        "original_rows": 3,
        "cleaned_rows": 3,
        "config": {},
        "artifacts": {},
        "artifact_dir": "processed/synthetic",
        "manifest": {},
    }


def job_values(**overrides):
    return {
        "kind": "training",
        "payload": {"synthetic": True},
        "payload_hash": DIGEST,
        "idempotency_key": DIGEST,
    } | overrides


def graph_values():
    """One complete lineage, with no fabricated model performance metrics."""
    return [
        (Dataset, dataset_values()),
        (DataQualityReport, {"dataset_id": DATASET, "report": {"synthetic": True}}),
        (Product, {"dataset_id": DATASET, "stock_code": STOCK, "description": None}),
        (
            TrainingRun,
            {
                "run_id": RUN,
                "dataset_id": DATASET,
                "config": {"synthetic": True},
                "metrics": {},
                "artifact_dir": "phase3/synthetic",
                "manifest_sha256": DIGEST,
            },
        ),
        (
            ModelArtifact,
            {
                "model_id": MODEL,
                "run_id": RUN,
                "family": "ridge",
                "artifact_key": "models/ridge.joblib",
                "sha256": DIGEST,
                "metadata_json": {"synthetic": True},
            },
        ),
        (
            WeeklyDemand,
            {
                "run_id": RUN,
                "dataset_id": DATASET,
                "stock_code": STOCK,
                "week": MONDAY,
                "gross_units": 5,
                "returned_units": 1,
                "cancellation_units": 1,
                "net_units": 3,
                "revenue": 10.0,
                "transactions": 2,
                "unique_customers": 1,
                "average_price": 2.0,
            },
        ),
        (
            ForecastBatch,
            {
                "forecast_id": FORECAST,
                "run_id": RUN,
                "scope": "one_week",
                "metadata_json": {"synthetic": True},
                "artifact_dir": "forecasts/synthetic",
            },
        ),
        (
            ForecastValue,
            {
                "forecast_id": FORECAST,
                "stock_code": STOCK,
                "week": MONDAY,
                "method": "ridge",
                "point": 5.0,
                "lower": 1.0,
                "upper": 10.0,
                "actual": None,
                "nominal_coverage": 0.8,
                "uncertainty_label": "Synthetic bounds for persistence testing",
            },
        ),
        (
            InventoryConfiguration,
            {"configuration_id": CONFIGURATION, "config": {}, "currency": "GBP"},
        ),
        (
            SimulationScenario,
            {
                "scenario_id": SCENARIO,
                "forecast_id": FORECAST,
                "configuration_id": CONFIGURATION,
                "artifact_dir": "inventory/synthetic",
                "summary": {"synthetic": True},
                "manifest_sha256": DIGEST,
            },
        ),
        (
            SimulationResult,
            {
                "scenario_id": SCENARIO,
                "policy": "ml_safety_stock",
                "stock_code": STOCK,
                "week": MONDAY,
                "actual": 7,
                "fulfilled_units": 5,
                "lost_units": 2,
                "ending_inventory": 0,
                "details": {"purchase_cost": 2.0},
            },
        ),
    ]


def seed_graph(engine):
    with engine.begin() as connection:
        for model, values in graph_values():
            connection.execute(insert(model).values(**values))


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://local/demandiq",
        "postgresql://local/demandiq_test_backup",
        "postgresql://local/test",
    ],
)
def test_test_database_guard(value):
    with pytest.raises(ValueError, match="end in _test"):
        checked_test_url(value)


def test_test_database_guard_accepts_disposable_database():
    assert (
        checked_test_url("postgresql://local/demandiq_test").database == "demandiq_test"
    )


def test_application_metadata_contract():
    assert len(APPLICATION_MODELS) == 9
    assert len(Base.metadata.tables) == 12
    for model in APPLICATION_MODELS:
        for foreign_key in model.__table__.foreign_keys:
            assert foreign_key.ondelete == "CASCADE"
    assert Job.__table__.c.idempotency_key.nullable is False
    assert Job.__table__.c.result.type.none_as_null is True
    assert UUID(Job.__table__.c.job_id.default.arg(None)).version == 4
    indexes = {index.name: index for index in Job.__table__.indexes}
    assert set(indexes) == {"ix_jobs_queued_available", "ix_jobs_running_expiry"}
    assert (
        str(indexes["ix_jobs_queued_available"].dialect_options["postgresql"]["where"])
        == "status = 'queued'"
    )
    for model in (WeeklyDemand, ForecastValue, SimulationResult):
        assert model.__table__.c.week.type.__class__.__name__ == "Date"
    for model in APPLICATION_MODELS:
        assert "customer_id" not in model.__table__.c
        assert "customer_key" not in model.__table__.c


def test_application_migration_offline_sql(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:hidden@localhost/demandiq_test"
    )
    output = StringIO()
    command.upgrade(alembic_config(output), "head", sql=True)
    sql = output.getvalue()
    for model in APPLICATION_MODELS:
        assert f"CREATE TABLE {model.__tablename__}" in sql
    assert "CREATE INDEX ix_jobs_queued_available" in sql
    assert "CREATE INDEX ix_jobs_running_expiry" in sql
    assert "ON DELETE CASCADE" in sql
    assert "'Infinity'::float8" in sql
    assert "hidden" not in sql
    output = StringIO()
    command.downgrade(alembic_config(output), "head:0001_data_foundation", sql=True)
    sql = output.getvalue()
    for model in APPLICATION_MODELS:
        assert f"DROP TABLE {model.__tablename__}" in sql
    assert "DROP TABLE datasets" not in sql


@pytest.fixture
def database_url(monkeypatch):
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "TEST_DATABASE_URL absent: real PostgreSQL integration was not run."
        )
    checked_test_url(value)
    monkeypatch.setenv("DATABASE_URL", value)
    return value


@pytest.fixture
def database_engine(database_url):
    command.upgrade(alembic_config(), "head")
    engine = create_engine(checked_test_url(database_url), hide_parameters=True)

    def clear():
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

    clear()
    try:
        yield engine
    finally:
        clear()
        engine.dispose()


@pytest.mark.integration
def test_migration_roundtrip_preserves_existing_dataset_and_has_no_drift(
    database_engine,
):
    with database_engine.begin() as connection:
        connection.execute(insert(Dataset).values(**dataset_values()))
        connection.execute(insert(Product).values(dataset_id=DATASET, stock_code=STOCK))
    names = {model.__tablename__ for model in APPLICATION_MODELS}
    try:
        command.downgrade(alembic_config(), "0001_data_foundation")
        assert names.isdisjoint(inspect(database_engine).get_table_names())
        with database_engine.connect() as connection:
            assert connection.scalar(select(Dataset.dataset_id)) == DATASET
            assert connection.scalar(select(Product.stock_code)) == STOCK
    finally:
        command.upgrade(alembic_config(), "head")
    assert names <= set(inspect(database_engine).get_table_names())
    with database_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []
    indexes = {
        index["name"]: index for index in inspect(database_engine).get_indexes("jobs")
    }
    assert "status" in str(
        indexes["ix_jobs_queued_available"]["dialect_options"]["postgresql_where"]
    )


@pytest.mark.integration
def test_complete_lineage_roundtrips_typed_aggregate_facts(database_engine):
    seed_graph(database_engine)
    with Session(database_engine) as session:
        for model in APPLICATION_MODELS:
            if model is not Job:
                assert session.scalar(select(func.count()).select_from(model)) == 1
        run = session.get(TrainingRun, RUN)
        assert run.config == {"synthetic": True}
        assert run.created_at.tzinfo is not None
        assert session.get(ModelArtifact, MODEL).family == "ridge"
        weekly = session.get(WeeklyDemand, (RUN, STOCK, MONDAY))
        assert weekly.week == MONDAY
        assert (
            weekly.net_units
            == weekly.gross_units - weekly.returned_units - weekly.cancellation_units
        )
        value = session.get(ForecastValue, (FORECAST, STOCK, MONDAY, "ridge"))
        assert value.actual is None
        assert (value.lower, value.point, value.upper) == (1.0, 5.0, 10.0)
        result = session.get(
            SimulationResult, (SCENARIO, "ml_safety_stock", STOCK, MONDAY)
        )
        assert result.actual == result.fulfilled_units + result.lost_units
        assert result.details == {"purchase_cost": 2.0}


@pytest.mark.integration
def test_dataset_cascade_removes_lineage_without_removing_independent_config_or_jobs(
    database_engine,
):
    seed_graph(database_engine)
    with database_engine.begin() as connection:
        connection.execute(insert(Job).values(**job_values()))
        connection.execute(delete(Dataset).where(Dataset.dataset_id == DATASET))
        for model in (
            Dataset,
            Product,
            DataQualityReport,
            TrainingRun,
            ModelArtifact,
            WeeklyDemand,
            ForecastBatch,
            ForecastValue,
            SimulationScenario,
            SimulationResult,
        ):
            assert connection.scalar(select(func.count()).select_from(model)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(InventoryConfiguration))
            == 1
        )
        assert connection.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.integration
def test_configuration_cascade_is_limited_to_its_scenarios(database_engine):
    seed_graph(database_engine)
    with database_engine.begin() as connection:
        connection.execute(delete(InventoryConfiguration))
        for model in (InventoryConfiguration, SimulationScenario, SimulationResult):
            assert connection.scalar(select(func.count()).select_from(model)) == 0
        for model in (
            Dataset,
            TrainingRun,
            ModelArtifact,
            WeeklyDemand,
            ForecastBatch,
            ForecastValue,
        ):
            assert connection.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.integration
def test_jobs_have_safe_defaults_and_nullable_result_roundtrip(database_engine):
    with database_engine.begin() as connection:
        job_id = connection.scalar(
            insert(Job).values(**job_values()).returning(Job.job_id)
        )
    assert UUID(job_id).version == 4
    with Session(database_engine) as session:
        job = session.get(Job, job_id)
        assert (job.status, job.attempts, job.max_attempts) == ("queued", 0, 3)
        assert job.available_at.tzinfo is not None
        assert job.created_at.tzinfo is not None
        assert job.updated_at.tzinfo is not None
        assert job.started_at is None and job.completed_at is None
        assert job.result is None
    with database_engine.begin() as connection:
        connection.execute(update(Job).values(result={"ok": True}))
        connection.execute(update(Job).values(result=None))
        assert (
            connection.scalar(
                select(func.count()).select_from(Job).where(Job.result.is_(None))
            )
            == 1
        )


@pytest.mark.integration
def test_job_idempotency_is_kind_scoped_and_nonnull(database_engine):
    with database_engine.begin() as connection:
        connection.execute(insert(Job).values(**job_values()))
        connection.execute(insert(Job).values(**job_values(kind="forecasting")))
    for values in (job_values(), job_values(idempotency_key=None)):
        with pytest.raises(IntegrityError), database_engine.begin() as connection:
            connection.execute(insert(Job).values(**values))


JOB_INVALID_VALUES = [
    {"kind": "unknown"},
    {"payload": []},
    {"payload_hash": "X" * 64},
    {"idempotency_key": " "},
    {"status": "unknown"},
    {"attempts": -1},
    {"attempts": 4},
    {"max_attempts": 0},
    {"max_attempts": 6},
    {"result": []},
    {"error_code": " "},
    {"job_id": "not-a-uuid"},
    {"status": "running"},
    {"locked_by": "worker"},
    {"lease_token": str(uuid4())},
    {"lease_expires_at": datetime.now(UTC)},
    {
        "status": "running",
        "locked_by": "worker",
        "lease_token": "invalid",
        "lease_expires_at": datetime.now(UTC),
    },
    {
        "status": "running",
        "locked_by": " ",
        "lease_token": str(uuid4()),
        "lease_expires_at": datetime.now(UTC),
    },
]


@pytest.mark.integration
@pytest.mark.parametrize("invalid", JOB_INVALID_VALUES)
def test_job_constraints_are_enforced_in_postgresql(database_engine, invalid):
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(insert(Job).values(**job_values(**invalid)))


@pytest.mark.integration
def test_running_job_requires_complete_lease_and_completion_clears_it(database_engine):
    lease = {
        "locked_by": "synthetic-worker",
        "lease_token": str(uuid4()),
        "lease_expires_at": datetime.now(UTC) + timedelta(minutes=1),
    }
    with database_engine.begin() as connection:
        connection.execute(
            insert(Job).values(**job_values(status="running", attempts=1, **lease))
        )
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(update(Job).values(status="succeeded"))
    with database_engine.begin() as connection:
        connection.execute(
            update(Job).values(
                status="succeeded",
                locked_by=None,
                lease_token=None,
                lease_expires_at=None,
                result={"synthetic": True},
                completed_at=func.now(),
            )
        )
        row = connection.execute(select(Job.__table__)).mappings().one()
        assert row["status"] == "succeeded"
        assert row["result"] == {"synthetic": True}
        assert row["completed_at"].tzinfo is not None


INVALID_APPLICATION_VALUES = [
    (TrainingRun, {"config": []}),
    (TrainingRun, {"metrics": []}),
    (TrainingRun, {"manifest_sha256": "invalid"}),
    (TrainingRun, {"run_id": "invalid"}),
    (TrainingRun, {"dataset_id": OTHER}),
    (ModelArtifact, {"family": "unknown"}),
    (ModelArtifact, {"metadata_json": []}),
    (ModelArtifact, {"sha256": "invalid"}),
    (ModelArtifact, {"run_id": OTHER}),
    (WeeklyDemand, {"gross_units": -1}),
    (WeeklyDemand, {"returned_units": -1}),
    (WeeklyDemand, {"cancellation_units": -1}),
    (WeeklyDemand, {"net_units": 4}),
    (WeeklyDemand, {"revenue": -1.0}),
    (WeeklyDemand, {"revenue": float("inf")}),
    (WeeklyDemand, {"revenue": float("nan")}),
    (WeeklyDemand, {"transactions": -1}),
    (WeeklyDemand, {"unique_customers": -1}),
    (WeeklyDemand, {"unique_customers": 3}),
    (WeeklyDemand, {"average_price": None}),
    (WeeklyDemand, {"average_price": 0.0}),
    (WeeklyDemand, {"average_price": float("inf")}),
    (WeeklyDemand, {"average_price": float("nan")}),
    (WeeklyDemand, {"week": MONDAY + timedelta(days=1)}),
    (WeeklyDemand, {"stock_code": "UNKNOWN"}),
    (ForecastBatch, {"scope": "unknown"}),
    (ForecastBatch, {"metadata_json": []}),
    (ForecastBatch, {"run_id": OTHER}),
    (ForecastValue, {"lower": -1.0}),
    (ForecastValue, {"lower": float("nan")}),
    (ForecastValue, {"point": float("nan")}),
    (ForecastValue, {"point": float("inf")}),
    (ForecastValue, {"upper": float("nan")}),
    (ForecastValue, {"upper": float("inf")}),
    (ForecastValue, {"lower": 6.0}),
    (ForecastValue, {"upper": 4.0}),
    (ForecastValue, {"actual": -1}),
    (ForecastValue, {"nominal_coverage": 0.0}),
    (ForecastValue, {"nominal_coverage": 1.0}),
    (ForecastValue, {"nominal_coverage": float("nan")}),
    (ForecastValue, {"method": " "}),
    (ForecastValue, {"stock_code": " X"}),
    (ForecastValue, {"uncertainty_label": " "}),
    (ForecastValue, {"week": MONDAY + timedelta(days=1)}),
    (InventoryConfiguration, {"config": []}),
    (InventoryConfiguration, {"currency": "gbp"}),
    (InventoryConfiguration, {"currency": "ＧＢＰ"}),
    (InventoryConfiguration, {"configuration_id": "invalid"}),
    (SimulationScenario, {"forecast_id": OTHER}),
    (SimulationScenario, {"configuration_id": OTHER}),
    (SimulationScenario, {"summary": []}),
    (SimulationScenario, {"manifest_sha256": "invalid"}),
    (SimulationResult, {"actual": -1}),
    (SimulationResult, {"fulfilled_units": -1}),
    (SimulationResult, {"lost_units": -1}),
    (SimulationResult, {"ending_inventory": -1}),
    (SimulationResult, {"actual": 8}),
    (SimulationResult, {"details": []}),
    (SimulationResult, {"details": {"actual": 999}}),
    (SimulationResult, {"details": {"stock_code": "duplicated"}}),
    (SimulationResult, {"policy": " "}),
    (SimulationResult, {"stock_code": " X"}),
    (SimulationResult, {"week": MONDAY + timedelta(days=1)}),
]


@pytest.mark.integration
@pytest.mark.parametrize("model,invalid", INVALID_APPLICATION_VALUES)
def test_application_constraints_are_enforced_in_postgresql(
    database_engine, model, invalid
):
    seed_graph(database_engine)
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(update(model).values(**invalid))


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        "",
        " ",
        "/private/model",
        "../model",
        "./model",
        "models/../model",
        "models/./model",
        "C:/model",
        "models\\model",
        " models/model ",
    ],
)
@pytest.mark.parametrize(
    "model,field",
    [
        (TrainingRun, "artifact_dir"),
        (ModelArtifact, "artifact_key"),
        (ForecastBatch, "artifact_dir"),
        (SimulationScenario, "artifact_dir"),
    ],
)
def test_artifact_references_are_normalized_relative_paths(
    database_engine, model, field, path
):
    seed_graph(database_engine)
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(update(model).values(**{field: path}))


@pytest.mark.integration
def test_weekly_composite_foreign_key_prevents_cross_dataset_contamination(
    database_engine,
):
    seed_graph(database_engine)
    with database_engine.begin() as connection:
        connection.execute(insert(Dataset).values(**dataset_values(OTHER)))
        connection.execute(insert(Product).values(dataset_id=OTHER, stock_code=STOCK))
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(update(WeeklyDemand).values(dataset_id=OTHER))


@pytest.mark.integration
def test_zero_sale_week_keeps_credit_movements_and_null_price(database_engine):
    seed_graph(database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            update(WeeklyDemand).values(
                gross_units=0,
                net_units=-2,
                revenue=0.0,
                average_price=None,
                transactions=0,
                unique_customers=0,
            )
        )
        row = connection.execute(select(WeeklyDemand.__table__)).mappings().one()
        assert row["returned_units"] == 1 and row["cancellation_units"] == 1
        assert row["net_units"] == -2
        assert row["average_price"] is None
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(update(WeeklyDemand).values(average_price=0.0))


@pytest.mark.integration
def test_numeric_conservation_checks_do_not_overflow_bigint(database_engine):
    seed_graph(database_engine)
    maximum = 2**63 - 1
    with database_engine.begin() as connection:
        connection.execute(
            update(WeeklyDemand).values(
                gross_units=maximum,
                returned_units=maximum,
                cancellation_units=maximum,
                net_units=-maximum,
            )
        )
        connection.execute(
            update(SimulationResult).values(
                actual=maximum, fulfilled_units=maximum, lost_units=0
            )
        )
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(
            update(SimulationResult).values(fulfilled_units=maximum, lost_units=maximum)
        )


@pytest.mark.integration
def test_composite_primary_keys_prevent_duplicate_forecasts_and_simulation_rows(
    database_engine,
):
    seed_graph(database_engine)
    for model, values in graph_values():
        if model in (WeeklyDemand, ForecastValue, SimulationResult):
            with pytest.raises(IntegrityError), database_engine.begin() as connection:
                connection.execute(insert(model).values(**values))


@pytest.mark.integration
def test_zero_forecast_and_zero_outcomes_are_valid(database_engine):
    seed_graph(database_engine)
    with database_engine.begin() as connection:
        connection.execute(
            update(ForecastValue).values(lower=0.0, point=0.0, upper=0.0, actual=0)
        )
        connection.execute(
            update(SimulationResult).values(
                actual=0, fulfilled_units=0, lost_units=0, ending_inventory=0
            )
        )
        assert connection.scalar(select(ForecastValue.point)) == 0.0
        assert connection.scalar(select(SimulationResult.actual)) == 0
