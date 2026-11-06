"""Schema migrations (backend/migrations/): every kind of store reaches the
same schema, the one app/models.py describes, without losing a row.

Runs against throwaway SQLite files; CI runs the same upgrade on Postgres.
"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app import config, models

ALEMBIC_INI = str(config.BACKEND_DIR / "alembic.ini")
ADDRESS = "0x" + "1" * 40


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'store.db'}", future=True)
    monkeypatch.setattr(models, "_engine", engine)
    return engine


def drift(engine) -> list:
    """What differs between the database and app/models.py; [] when nothing."""
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), models.Base.metadata)


def revision(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head() -> str:
    return ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_current_head()


def test_there_is_exactly_one_migration_head():
    # Two heads means two branches each added a migration: rebase and renumber.
    assert len(ScriptDirectory.from_config(Config(ALEMBIC_INI)).get_heads()) == 1


def test_an_empty_database_gets_the_whole_schema(engine):
    models.init_db()
    assert revision(engine) == head()
    assert drift(engine) == []


def pre_migration_store(engine, skip: tuple[str, ...] = ()) -> None:
    """What create_all() made before migrations existed: the baseline's tables
    and indexes, no version table. (Today's models are ahead of it: later
    migrations add columns the old stores do not have.)"""
    import importlib.util

    from sqlalchemy import Index, MetaData, Table
    spec = importlib.util.spec_from_file_location(
        "baseline", config.BACKEND_DIR / "migrations" / "versions" / "0001_baseline.py")
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    metadata = MetaData()
    for name, (columns, indexed) in baseline.TABLES.items():
        if name in skip:
            continue
        table = Table(name, metadata, *columns())
        for column in indexed:
            Index(f"ix_{name}_{column}", table.c[column])
    metadata.create_all(engine)


def test_a_store_made_before_migrations_is_adopted_untouched(engine):
    # What every deployed or local store was on 2 Nov: create_all(), no version.
    pre_migration_store(engine)
    models.save_case("kept", ADDRESS, {"address": ADDRESS}, owner_hash="h" * 64)
    models.init_db()
    assert revision(engine) == head()
    assert drift(engine) == []
    kept = models.get_case("kept")
    assert kept.result == {"address": ADDRESS} and kept.owner_hash == "h" * 64


def test_a_store_older_than_ownership_gains_owner_hash_and_keeps_its_cases(engine):
    pre_migration_store(engine, skip=("cases",))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE cases (id VARCHAR(36) NOT NULL PRIMARY KEY, "
                          "address VARCHAR(42) NOT NULL, created_at VARCHAR(32) NOT NULL, "
                          "result_json TEXT NOT NULL)"))
        conn.execute(text("CREATE INDEX ix_cases_address ON cases (address)"))
        conn.execute(text("INSERT INTO cases VALUES ('old', :a, 't', '{}')"), {"a": ADDRESS})
    models.init_db()
    assert drift(engine) == []
    assert models.get_case("old").owner_hash is None  # an old case reads as unowned


def test_running_it_again_changes_nothing(engine):
    models.init_db()
    models.save_case("kept", ADDRESS, {"address": ADDRESS})
    models.init_db()
    assert revision(engine) == head() and drift(engine) == []
    assert models.get_case("kept") is not None


def test_the_baseline_refuses_to_be_downgraded(engine):
    models.init_db()
    models.save_case("kept", ADDRESS, {"address": ADDRESS})
    settings = Config(ALEMBIC_INI)
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        with pytest.raises(RuntimeError, match="drop every stored case"):
            command.downgrade(settings, "base")
    assert "cases" in inspect(engine).get_table_names()
    assert models.get_case("kept") is not None


def test_migrating_at_startup_leaves_the_apps_logging_alone(engine):
    # Alembic's usual env.py calls fileConfig(), which silences every logger
    # that already exists -- log_safety's included -- unless told not to.
    import logging
    before = {name for name, lg in logging.Logger.manager.loggerDict.items()
              if isinstance(lg, logging.Logger) and not lg.disabled}
    models.init_db()
    assert not logging.getLogger("app.models").disabled
    assert all(not logging.getLogger(name).disabled for name in before)


class _RecordingConnection:
    """Stands in for a live connection: records each statement it is given."""

    def __init__(self, dialect: str):
        self.dialect = type("Dialect", (), {"name": dialect})()
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))


def test_postgres_migrations_take_the_lock_before_any_ddl():
    # One migrator at a time; DDL that cannot get its table lock gives up
    # instead of queueing every live query behind it.
    conn = _RecordingConnection("postgresql")
    models.guard_migrations(conn)
    assert conn.statements == [
        "SET LOCAL statement_timeout = '120s'",
        f"SELECT pg_advisory_xact_lock({models.MIGRATION_LOCK_KEY})",
        "SET LOCAL lock_timeout = '5s'",
    ]


def test_sqlite_migrations_run_no_lock_sql():
    conn = _RecordingConnection("sqlite")
    models.guard_migrations(conn)
    assert conn.statements == []


def test_every_upgrade_goes_through_the_guard(engine, monkeypatch):
    seen = []
    monkeypatch.setattr(models, "guard_migrations", lambda conn: seen.append(conn.dialect.name))
    models.init_db()
    assert seen == ["sqlite"]
    assert revision(engine) == head()


def test_cursor_columns_are_bigint_on_postgres():
    # A Tron cursor and an alert's tx_time are Unix seconds, past int4 in
    # January 2038; Arbitrum block numbers pass it around then too.
    from sqlalchemy.dialects import postgresql
    for column in (models.Watch.__table__.c.last_seen_block, models.Alert.__table__.c.tx_time):
        assert column.type.compile(dialect=postgresql.dialect()) == "BIGINT"


def test_upgrade_keeps_a_cursor_past_2038(engine):
    settings = Config(ALEMBIC_INI)
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "0001")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watches (id, owner_hash, chain, asset, address, note, created_at, "
                          "last_seen_block, active) VALUES ('w', 'h', 'tron', 'USDT', 'T', '', 't', "
                          "3000000000, 1)"))
        conn.execute(text("INSERT INTO alerts (id, watch_id, owner_hash, created_at, kind, message, tx_hash, "
                          "tx_time, value, asset, counterparty, counterparty_label, read) VALUES "
                          "('a', 'w', 'h', 't', 'moved', 'm', '0x', 3000000001, 1.0, 'USDT', 'T2', '', 0)"))
    models.init_db()
    assert revision(engine) == head() and drift(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT last_seen_block FROM watches")).scalar() == 3_000_000_000
        assert conn.execute(text("SELECT tx_time FROM alerts")).scalar() == 3_000_000_001
    assert {i["name"] for i in inspect(engine).get_indexes("watches")} >= {"ix_watches_address",
                                                                            "ix_watches_owner_hash"}


def test_existing_freeze_requests_start_at_version_one_and_still_update(engine):
    from app import freeze_requests
    settings = Config(ALEMBIC_INI)
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "0001")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO freeze_requests (id, owner_hash, case_id, recipient, kind, status, "
                          "address, reference, asset, notes, created_at, updated_at, history_json) VALUES "
                          "('r', 'o', 'c', 'Binance', 'exchange', 'drafted', '', '', '', '', 't', 't', '[]')"))
    models.init_db()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT row_version FROM freeze_requests")).scalar() == 1
    assert freeze_requests.update("o", "r", {"status": "sent"})["status"] == "sent"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT row_version FROM freeze_requests")).scalar() == 2


def test_sec6_watch_1_fills_inferred_deposits_from_the_cases_already_stored(engine):
    settings = Config(ALEMBIC_INI)
    with engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "0001")
        rows = [
            ("good", '{"chain": "ethereum", "inferred_deposits": [{"address": "0xABC1", "exchange": "OKX"},'
                     ' {"address": "0xabc1", "exchange": "OKX"}, {"address": "bad addr", "exchange": "X"}]}'),
            ("corrupt", '{"inferred_deposits": [ not json'),
            ("none", '{"chain": "ethereum", "inferred_deposits": []}'),
            ("plain", '{"chain": "ethereum"}'),
        ]
        for case_id, body in rows:
            conn.execute(text("INSERT INTO cases (id, address, created_at, result_json, owner_hash) "
                              "VALUES (:i, :a, 't', :r, :o)"), {"i": case_id, "a": ADDRESS, "r": body, "o": "h" * 64})
    models.init_db()
    assert revision(engine) == head() and drift(engine) == []
    with engine.connect() as conn:
        got = conn.execute(text("SELECT case_id, chain, address, exchange, owner_hash, seed_address "
                                "FROM inferred_deposits")).all()
    assert got == [("good", "ethereum", "0xabc1", "OKX", "h" * 64, ADDRESS)]
    models.init_db()  # nothing runs twice
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM inferred_deposits")).scalar() == 1
