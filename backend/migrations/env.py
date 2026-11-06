"""Alembic's entry point: which database, and what its schema should be.

The database is the app's own (app.models), so the command line and the
running app can never disagree about it. models.init_db() hands in its open
connection; the alembic CLI connects with the same settings.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app import models

config = context.config
target_metadata = models.Base.metadata


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot alter most columns in place; batch mode copies the
        # table instead, so a migration written once runs on SQLite and Postgres.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        # Postgres: wait for any other migrator, and fail fast on a busy table.
        models.guard_migrations(connection)
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported: run against a database.")

connection = config.attributes.get("connection")
if connection is not None:
    # Called from the app: its logging is already set up, so leave it alone.
    run_migrations(connection)
else:
    if config.config_file_name:
        # From the CLI. disable_existing_loggers=False: the default would
        # silence every logger app.models has already created.
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    models.ensure_storage_dir()
    with models.engine().connect() as conn:
        run_migrations(conn)
        conn.commit()
