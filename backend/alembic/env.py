"""Alembic environment: the database URL comes only from DATABASE_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.db.models import Base
from backend.app.db.repository import postgres_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = postgres_url(os.environ.get("DATABASE_URL", ""))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Compile PostgreSQL SQL without connecting to a database."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
