"""Short-lived PostgreSQL units of work; no connection is made at import time."""

from sqlalchemy import create_engine

from backend.app.db.repository import postgres_url


def make_engine(database_url: str):
    return create_engine(
        postgres_url(database_url),
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
