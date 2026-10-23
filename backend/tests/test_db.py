"""Metadata tests; integration cases require a disposable PostgreSQL *_test DB.

WARNING: integration fixtures migrate and DELETE all rows from DemandIQ's
datasets, data_quality_reports and products tables in TEST_DATABASE_URL.
They refuse database names not ending in _test. Never point this at valuable data.
No database connection is attempted when TEST_DATABASE_URL is absent.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import (
    create_engine,
    delete,
    event,
    func,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from backend.app.db.models import Base, DataQualityReport, Dataset, Product
from backend.app.db.repository import (
    DatasetConflictError,
    persist_dataset,
    postgres_url,
)

ROOT = Path(__file__).resolve().parents[2]


def manifest() -> dict:
    """Synthetic metadata only; no real customer or transaction records."""
    return {
        "dataset_id": "a" * 64,
        "source_sha256": "b" * 64,
        "cleaning_version": "test-v1",
        "config": {"source_timezone": "Europe/London"},
        "artifacts": {"purchases.parquet": {"sha256": "c" * 64}},
        "artifact_dir": "data/processed/synthetic",
        "original_rows": 10,
        "cleaned_rows": 8,
    }


def report() -> dict:
    return {"original_rows": 10, "cleaned_rows": 8, "duplicate_rows": 2}


def products() -> list[dict]:
    return [
        {"stock_code": "SYNTHETIC-B", "description": None},
        {"stock_code": "SYNTHETIC-A", "description": "Synthetic item"},
    ]


def alembic_config(output_buffer=None) -> Config:
    return Config(str(ROOT / "backend" / "alembic.ini"), output_buffer=output_buffer)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a database URL",
        "sqlite:///data.db",
        "mysql://localhost/demo",
        "postgresql+psycopg2://localhost/demo",
        "postgresql://localhost",
    ],
)
def test_non_postgres_or_incomplete_urls_rejected(url):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        postgres_url(url)


def test_url_defaults_to_psycopg3_and_errors_hide_password():
    assert (
        postgres_url("postgresql://localhost/demandiq").drivername
        == "postgresql+psycopg"
    )
    with pytest.raises(ValueError) as exc:
        postgres_url("https://user:private-password@localhost/demandiq")
    assert "private-password" not in str(exc.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_id", "not-a-hash"),
        ("source_sha256", "B" * 64),
        ("cleaning_version", ""),
        ("artifact_dir", " "),
        ("config", []),
        ("artifacts", {} | {"invalid": float("nan")}),
        ("original_rows", -1),
        ("cleaned_rows", 11),
        ("cleaned_rows", True),
    ],
)
def test_invalid_manifest_is_rejected_before_connecting(monkeypatch, field, value):
    invalid = manifest()
    invalid[field] = value

    def unexpected_connection(*args, **kwargs):
        pytest.fail("Invalid input must be rejected before creating an engine.")

    monkeypatch.setattr(
        "backend.app.db.repository.create_engine", unexpected_connection
    )
    with pytest.raises(ValueError):
        persist_dataset("postgresql://localhost/unused", invalid, report(), products())


@pytest.mark.parametrize(
    "catalog",
    [
        [{"stock_code": "", "description": None}],
        [{"stock_code": "X", "description": 123}],
        [{"stock_code": "X", "description": None, "customer_id": "SYNTHETIC"}],
        [{"stock_code": "X", "description": None}] * 2,
    ],
)
def test_invalid_catalog_is_rejected_before_connecting(monkeypatch, catalog):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("Invalid input must be rejected before creating an engine.")

    monkeypatch.setattr(
        "backend.app.db.repository.create_engine", unexpected_connection
    )
    with pytest.raises(ValueError):
        persist_dataset("postgresql://localhost/unused", manifest(), report(), catalog)


def test_offline_migration_compiles_postgresql_sql(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://test:private-password@localhost/demandiq_test"
    )
    output = StringIO()
    command.upgrade(alembic_config(output), "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE datasets" in sql
    assert "CREATE TABLE data_quality_reports" in sql
    assert "CREATE TABLE products" in sql
    assert "JSONB" in sql
    assert "private-password" not in sql
    output = StringIO()
    command.downgrade(alembic_config(output), "head:base", sql=True)
    assert "DROP TABLE datasets" in output.getvalue()


@pytest.fixture
def database_url(monkeypatch):
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "TEST_DATABASE_URL absent: real PostgreSQL integration was not run."
        )
    url = postgres_url(value)
    if not url.database.endswith("_test"):
        pytest.fail(
            "Refusing destructive integration tests: database name must end in _test."
        )
    monkeypatch.setenv("DATABASE_URL", value)
    return value


@pytest.fixture
def database_engine(database_url):
    command.upgrade(alembic_config(), "head")
    engine = create_engine(postgres_url(database_url), hide_parameters=True)
    with engine.begin() as connection:
        connection.execute(delete(Dataset))
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(delete(Dataset))
        engine.dispose()


@pytest.mark.integration
def test_postgresql_migration_roundtrip_and_model_match(database_engine):
    expected = {"datasets", "data_quality_reports", "products"}
    assert expected <= set(inspect(database_engine).get_table_names())
    command.downgrade(alembic_config(), "base")
    assert expected.isdisjoint(inspect(database_engine).get_table_names())
    command.upgrade(alembic_config(), "head")
    assert expected <= set(inspect(database_engine).get_table_names())
    with database_engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        assert compare_metadata(migration_context, Base.metadata) == []


@pytest.mark.integration
def test_persistence_is_idempotent_and_detects_conflicts(database_engine, database_url):
    dataset_id = persist_dataset(database_url, manifest(), report(), products())
    assert (
        persist_dataset(database_url, manifest(), report(), list(reversed(products())))
        == dataset_id
    )
    with database_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Dataset)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(DataQualityReport)) == 1
        )
        assert connection.scalar(select(func.count()).select_from(Product)) == 2
    changed_manifest = manifest() | {"artifact_dir": "different/path"}
    changed_report = report() | {"extra": "different"}
    changed_products = deepcopy(products())
    changed_products[0]["description"] = "Changed description"
    for candidate_manifest, candidate_report, candidate_products in [
        (changed_manifest, report(), products()),
        (manifest(), changed_report, products()),
        (manifest(), report(), changed_products),
    ]:
        with pytest.raises(DatasetConflictError, match="different metadata"):
            persist_dataset(
                database_url, candidate_manifest, candidate_report, candidate_products
            )
    assert persist_dataset(database_url, manifest(), report(), products()) == dataset_id


@pytest.mark.integration
@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "invalid"),
        ("cleaning_version", " "),
        ("status", "unrecognized"),
        ("original_rows", -1),
        ("cleaned_rows", -1),
        ("cleaned_rows", 11),
        ("artifact_dir", ""),
        ("config", []),
        ("artifacts", []),
        ("manifest", []),
    ],
)
def test_postgresql_dataset_constraints(database_engine, database_url, field, value):
    dataset_id = persist_dataset(database_url, manifest(), report(), products())
    with pytest.raises(IntegrityError), database_engine.begin() as connection:
        connection.execute(
            update(Dataset)
            .where(Dataset.dataset_id == dataset_id)
            .values(**{field: value})
        )


@pytest.mark.integration
def test_postgresql_foreign_keys_uniqueness_and_cascade(database_engine, database_url):
    for table, values in [
        (
            Product,
            {"dataset_id": "f" * 64, "stock_code": "SYNTHETIC", "description": None},
        ),
        (DataQualityReport, {"dataset_id": "f" * 64, "report": {}}),
    ]:
        with pytest.raises(IntegrityError), database_engine.begin() as connection:
            connection.execute(insert(table).values(**values))
    dataset_id = persist_dataset(database_url, manifest(), report(), products())
    for table, values in [
        (Product, {"dataset_id": dataset_id, **products()[0]}),
        (DataQualityReport, {"dataset_id": dataset_id, "report": {}}),
        (Product, {"dataset_id": dataset_id, "stock_code": " ", "description": None}),
    ]:
        with pytest.raises(IntegrityError), database_engine.begin() as connection:
            connection.execute(insert(table).values(**values))
    with database_engine.begin() as connection:
        connection.execute(delete(Dataset).where(Dataset.dataset_id == dataset_id))
        assert connection.scalar(select(func.count()).select_from(Product)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(DataQualityReport)) == 0
        )


@pytest.mark.integration
def test_postgresql_transaction_rolls_back_all_records(database_engine, database_url):
    def fail_catalog_insert(*args):
        raise RuntimeError("Deliberate test failure after parent insert.")

    event.listen(Product, "before_insert", fail_catalog_insert)
    try:
        with pytest.raises(RuntimeError, match="Deliberate test failure"):
            persist_dataset(database_url, manifest(), report(), products())
    finally:
        event.remove(Product, "before_insert", fail_catalog_insert)
    with database_engine.connect() as connection:
        for table in (Dataset, DataQualityReport, Product):
            assert connection.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.integration
def test_concurrent_registration_creates_one_dataset(database_engine, database_url):
    with ThreadPoolExecutor(max_workers=3) as workers:
        futures = [
            workers.submit(
                persist_dataset, database_url, manifest(), report(), products()
            )
            for _ in range(3)
        ]
        assert [future.result() for future in futures] == [manifest()["dataset_id"]] * 3
    with database_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Dataset)) == 1
        assert connection.scalar(select(func.count()).select_from(Product)) == 2
