"""Persistence for traced cases: SQLite by default, Postgres when DATABASE_URL is set.

Deliberately one table. A case is an immutable record of what the tool
concluded at a point in time, stored as the exact JSON that was returned to
the caller -- so a report generated months later reproduces what the
investigator actually saw, rather than a re-run against changed chain data.

SQLAlchemy is used rather than raw sqlite3 purely for the upgrade path: moving
to Postgres later is a connection-string change, not a rewrite.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (BigInteger, Boolean, Float, Index, Integer, String, Text, create_engine, event, func, or_,
                        select, text)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from . import config
from .input_rules import plain_text

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Case(Base):
    """One trace, as returned to the caller."""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    created_at: Mapped[str] = mapped_column(String(32))  # ISO-8601 UTC
    result_json: Mapped[str] = mapped_column(Text)
    # SHA-256 of the owner key of the browser that traced it (ownership.py).
    # NULL for cases stored before ownership existed.
    owner_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)
    # A hash of the connection that saved it (a connection's saves per day are
    # counted whatever owner keys it uses), and whether it was saved without
    # an owner key. NULL for cases saved before either existed.
    client_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    anonymous: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # len(result_json): the store is bounded in bytes too. NULL only on a row
    # written before the column existed (its migration fills them).
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # -- convenience -------------------------------------------------------
    @property
    def result(self) -> dict[str, Any]:
        try:
            return json.loads(self.result_json)
        except json.JSONDecodeError:
            logger.error("Case %s has corrupt result_json", self.id)
            return {}

    @staticmethod
    def _normalise_chain(stored: Any) -> str:
        """Current chain key for a stored case.

        Cases predate the chain registry, so the stored value may be an old
        spelling or something no longer supported. The history list must
        survive either: an unreadable row would otherwise take the whole list
        down, and re-tracing must send a key the API still accepts.
        """
        try:
            return config.get_chain(stored).key
        except config.UnknownChainError:
            return config.DEFAULT_CHAIN.key

    def summary(self) -> dict[str, Any]:
        """Compact form used by the /cases history list."""
        result = self.result
        return {
            "case_id": self.id,
            "address": self.address,
            "created_at": self.created_at,
            "chain": self._normalise_chain(result.get("chain")),
            "asset": result.get("asset"),
            "direction": result.get("direction", "outgoing"),
            "exchange": result.get("exchange"),
            "confidence": result.get("confidence"),
            "flags": result.get("flags", []),
            "hop_count": result.get("hop_count"),
            "node_count": len(result.get("graph", {}).get("nodes", [])),
        }


class Watch(Base):
    """An address the owner wants to hear about when funds leave it."""

    __tablename__ = "watches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    chain: Mapped[str] = mapped_column(String(16))
    asset: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    last_checked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Newest block already seen; a transfer above it is news. NULL until the
    # first check sets the baseline (history before the watch is not news).
    # A Unix time on Tron (watchlist._position_of): 64-bit, past 2038.
    last_seen_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # A hash of the connection that made it (its share is counted whatever
    # owner keys it uses), and when its owner last listed or checked it (a
    # forgotten watch gives up its slot when the server is full). NULL for
    # watches made before either existed.
    client_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)
    touched_at: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)


class Alert(Base):
    """One movement the watcher noticed."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    watch_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # exchange | risk | moved | more (a notice)
    message: Mapped[str] = mapped_column(Text)
    tx_hash: Mapped[str] = mapped_column(String(80))
    tx_time: Mapped[int] = mapped_column(BigInteger)  # Unix seconds, past 2038
    value: Mapped[float] = mapped_column(Float)
    asset: Mapped[str] = mapped_column(String(16))
    counterparty: Mapped[str] = mapped_column(String(64))
    counterparty_label: Mapped[str] = mapped_column(String(200), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    # Its webhook post: pending | sent | failed (or a claim while posting);
    # NULL when the watch has no webhook, and for alerts from before this.
    delivery: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)


class InferredDeposit(Base):
    """A deposit address a stored case inferred: one row per case and address.

    Written with its case, in the same transaction, so a watch alert can ask
    "is this counterparty a probable exchange deposit address?" with one
    indexed query, and only of the cases its owner may see (ownership.py),
    instead of loading every stored case to find out."""

    __tablename__ = "inferred_deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    # The case's owner and reported address: whose inference it is, and
    # whether it is one of the public demo cases.
    owner_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    seed_address: Mapped[str] = mapped_column(String(64))
    chain: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(64))
    exchange: Mapped[str] = mapped_column(String(64))

    __table_args__ = (Index("ix_inferred_deposits_chain_address", "chain", "address"),)


class FreezeRequest(Base):
    """A request sent about a case -- to an exchange, to Tether -- and what came of it."""

    __tablename__ = "freeze_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    recipient: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # exchange | tether | other
    status: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(64), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    sent_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_frozen: Mapped[float | None] = mapped_column(Float, nullable=True)
    asset: Mapped[str] = mapped_column(String(16), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    history_json: Mapped[str] = mapped_column(Text, default="[]")
    # Checked and bumped by every UPDATE and DELETE: a write made from a stale
    # read fails (StaleDataError) instead of replacing what another wrote.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    __mapper_args__ = {"version_id_col": row_version}


class Batch(Base):
    """A list of reported addresses traced one after another (batches.py)."""

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # running | done | failed | interrupted
    rows_json: Mapped[str] = mapped_column(Text)
    # When the runner last wrote; a running batch silent for a while has no
    # runner left (batches.STALE_AFTER_SECONDS). NULL reads as silent.
    heartbeat_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


def _postgres_url(url: str) -> str:
    """Hosts hand out postgres:// URLs; SQLAlchemy wants the driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# A hosted Postgres closes idle connections (Neon suspends after a few
# minutes), so a pooled one is tested before use, never trusted. Every
# connect gives up after 5 s and a request waits at most 10 s for a pooled
# connection: an unreachable store used to hang each connect for the TCP retry
# period (about 2 minutes) and each request 30 s, until every worker thread
# was stuck. Ten connections stay well inside the free plan's limit.
POSTGRES_ENGINE_OPTIONS: dict = dict(pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5,
                                     pool_timeout=10, connect_args={"connect_timeout": 5})


def _make_engine() -> Engine:
    # hide_parameters: a database error's text then names the statement but
    # not its values -- an address, a case's JSON, an officer's note -- and
    # that text reaches the platform's logs.
    if config.DATABASE_URL:
        return create_engine(_postgres_url(config.DATABASE_URL), future=True, hide_parameters=True,
                             **POSTGRES_ENGINE_OPTIONS)
    return create_engine(
        f"sqlite:///{config.DB_PATH}", future=True, hide_parameters=True,
        # Wait up to 15 s for a lock rather than failing at once: background
        # traces, batches and the watchlist all write here.
        connect_args={"timeout": 15},
    )


_engine = _make_engine()


@event.listens_for(Engine, "connect")
def _sqlite_wal(dbapi_connection, _record) -> None:
    """Write-ahead logging: readers no longer block the writer, or the reverse."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass  # a read-only or in-memory database keeps its own mode
        finally:
            cursor.close()

# Bumped on every save. Stored cases never change, so anything computed over
# the whole store (correlation, the ledger) stays valid until this moves.
# Read it before computing, and stamp the result with that value.
_store_version = 0
_store_version_lock = threading.Lock()


def store_version() -> int:
    return _store_version


def engine() -> Engine:
    """The store's engine, for the migrations (migrations/env.py)."""
    return _engine


def ensure_storage_dir() -> None:
    """The SQLite file's folder must exist before the first connection."""
    if _engine.dialect.name == "sqlite":
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# Any fixed number; every migrator of this store asks for the same lock.
MIGRATION_LOCK_KEY = 727202611


def guard_migrations(connection) -> None:
    """Postgres: one migrator at a time, and DDL that cannot get its table
    lock within 5 s fails instead of queueing live queries behind it.

    Called inside the migration's transaction (migrations/env.py), so the
    transaction-level lock and SET LOCAL end with it -- which also works
    through a transaction pooler such as Neon's. The lock is taken before
    lock_timeout is set, so a second migrator (the CLI, a script, a booting
    instance) waits for the first, up to the 120 s statement limit."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
    connection.execute(text(f"SELECT pg_advisory_xact_lock({MIGRATION_LOCK_KEY})"))
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))


def init_db() -> None:
    """Bring the store to the current schema. Safe to call repeatedly.

    The schema is defined by the migrations in backend/migrations/, never
    created from the models directly: every change is a numbered migration,
    so every store -- an empty one, or one made by an older build -- reaches
    the same tables the same way. See migrations/versions/0001_baseline.py."""
    from alembic import command
    from alembic.config import Config

    ensure_storage_dir()
    settings = Config(str(config.BACKEND_DIR / "alembic.ini"))
    with _engine.begin() as conn:
        settings.attributes["connection"] = conn
        command.upgrade(settings, "head")
    if _engine.dialect.name == "sqlite":
        logger.info("SQLite ready at %s", config.DB_PATH)
    else:
        logger.info("Case store ready on %s at %s", _engine.dialect.name, _engine.url.host)


def new_case_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def save_case(
    case_id: str,
    address: str,
    result: dict[str, Any],
    created_at: str | None = None,
    owner_hash: str | None = None,
    result_json: str | None = None,
    client_hash: str | None = None,
    anonymous: bool | None = None,
) -> Case:
    """Persist one completed trace, and the deposit addresses it inferred.
    `result_json` is `result` already serialised, when the caller has it."""
    text = result_json if result_json is not None else json.dumps(result, default=str)
    case = Case(
        id=case_id,
        address=address,
        created_at=created_at or utc_now_iso(),
        result_json=text,
        owner_hash=owner_hash,
        client_hash=client_hash,
        anonymous=anonymous,
        size_bytes=len(text),
    )
    global _store_version
    with Session(_engine) as session:
        session.add(case)
        session.add_all(inferred_deposit_rows(case_id, owner_hash, address, result))
        session.commit()
        session.refresh(case)
        session.expunge(case)
    with _store_version_lock:
        _store_version += 1
    return case


def inferred_deposit_rows(case_id: str, owner_hash: str | None, seed: str,
                          result: dict[str, Any]) -> list[InferredDeposit]:
    """The InferredDeposit rows for one case's result["inferred_deposits"]."""
    try:
        chain = config.get_chain(result.get("chain") or "ethereum").key
    except config.UnknownChainError:
        return []
    matches = result.get("inferred_deposits")
    rows: list[InferredDeposit] = []
    seen: set[str] = set()
    for match in matches if isinstance(matches, list) else []:
        if not isinstance(match, dict):
            continue
        address, exchange = match.get("address"), match.get("exchange")
        if not (isinstance(address, str) and isinstance(exchange, str) and address.strip() and exchange.strip()):
            continue
        address = address.strip()
        address = address.lower() if address.startswith("0x") else address  # etherscan_client.normalize_address
        if len(address) > 64 or not address.isalnum() or address in seen:
            continue
        seen.add(address)
        rows.append(InferredDeposit(case_id=case_id, owner_hash=owner_hash, seed_address=(seed or "")[:64],
                                    chain=chain, address=address, exchange=plain_text(exchange, 64)))
    return rows


def case_count() -> int:
    with Session(_engine) as session:
        return int(session.scalar(select(func.count()).select_from(Case)) or 0)


def case_count_for(owner_hash: str) -> int:
    with Session(_engine) as session:
        stmt = select(func.count()).select_from(Case).where(Case.owner_hash == owner_hash)
        return int(session.scalar(stmt) or 0)


def case_count_from(client_hash: str, since: str) -> int:
    """Cases one connection saved since `since` (ISO-8601 UTC)."""
    with Session(_engine) as session:
        stmt = select(func.count()).select_from(Case).where(Case.client_hash == client_hash,
                                                            Case.created_at >= since)
        return int(session.scalar(stmt) or 0)


def _evictable(idle_before: str):
    """Cases that may give up their place when the store is full, oldest
    first: saved without an owner key, or kept by an owner who has saved
    nothing since `idle_before` (and older than that themselves). Never a
    demo case (no owner), and never one a freeze request or an active watch
    refers to: an officer is using it."""
    later = Case.__table__.alias("later")
    owner_active = (select(later.c.id).where(later.c.owner_hash == Case.owner_hash,
                                             later.c.created_at >= idle_before).exists())
    requested = select(FreezeRequest.id).where(FreezeRequest.case_id == Case.id).exists()
    watched = select(Watch.id).where(Watch.case_id == Case.id, Watch.active.is_(True)).exists()
    idle_owner = (Case.created_at < idle_before) & ~owner_active
    return (select(Case.id).where(Case.owner_hash.is_not(None), ~requested, ~watched,
                                  Case.anonymous.is_(True) | idle_owner)
            .order_by(Case.created_at, Case.id))


def stored_bytes() -> int:
    """The size of every stored result together, in bytes."""
    with Session(_engine) as session:
        return int(session.scalar(select(func.coalesce(func.sum(Case.size_bytes), 0))) or 0)


EVICT_AT_MOST = 200  # cases one save may delete to make room


def evict_cases(count: int, idle_before: str, nbytes: int = 0) -> tuple[int, int]:
    """Delete the oldest evictable cases (see _evictable), and their inferred
    deposits, until at least `count` cases and `nbytes` bytes are freed or
    none is left; returns (cases, bytes) freed. A deleted case's link then
    answers 404, like any id that matches no case."""
    if count <= 0 and nbytes <= 0:
        return 0, 0
    global _store_version
    with Session(_engine) as session:
        stmt = _evictable(idle_before).add_columns(Case.size_bytes).limit(EVICT_AT_MOST)
        ids, freed = [], 0
        for case_id, size in session.execute(stmt):
            if len(ids) >= count and freed >= nbytes:
                break
            ids.append(case_id)
            freed += size or 0
        if not ids:
            return 0, 0
        session.execute(InferredDeposit.__table__.delete().where(InferredDeposit.case_id.in_(ids)))
        session.execute(Case.__table__.delete().where(Case.id.in_(ids)))
        session.commit()
    _case_cache.drop(ids)
    with _store_version_lock:
        _store_version += 1
    return len(ids), freed


# Recently read cases, kept in memory. A stored case never changes (nothing
# updates one; the offline prune script deletes, and the server is restarted
# after it; evict_cases deletes and drops what it deleted from here), but its result can be megabytes and the production
# store is a metered free tier: re-reading one case in a loop would spend the
# month's transfer. Bounded in bytes of result_json; a case over a quarter of
# the bound is never kept, so a few huge ones cannot empty it.
CASE_CACHE_BYTES = 32 * 1024 * 1024


class _CaseCache:
    def __init__(self) -> None:
        self._items: OrderedDict[str, Case] = OrderedDict()
        self.size = 0
        self._engine: Engine | None = None
        self._lock = threading.Lock()

    def _for(self, engine: Engine) -> None:
        """Called with the lock held: a different store starts empty."""
        if engine is not self._engine:
            self._items.clear()
            self.size = 0
            self._engine = engine

    def get(self, engine: Engine, case_id: str) -> Case | None:
        with self._lock:
            self._for(engine)
            case = self._items.get(case_id)
            if case is not None:
                self._items.move_to_end(case_id)
            return case

    def put(self, engine: Engine, case: Case) -> None:
        cost = len(case.result_json or "")
        if cost > CASE_CACHE_BYTES // 4:
            return
        with self._lock:
            self._for(engine)
            if case.id in self._items:
                return
            self._items[case.id] = case
            self.size += cost
            while self.size > CASE_CACHE_BYTES and self._items:
                _, old = self._items.popitem(last=False)
                self.size -= len(old.result_json or "")


    def drop(self, case_ids: list[str]) -> None:
        with self._lock:
            for case_id in case_ids:
                old = self._items.pop(case_id, None)
                if old is not None:
                    self.size -= len(old.result_json or "")


_case_cache = _CaseCache()


def get_case(case_id: str) -> Case | None:
    engine = _engine
    cached = _case_cache.get(engine, case_id)
    if cached is not None:
        return cached
    with Session(engine) as session:
        case = session.get(Case, case_id)
        if case is not None:
            session.expunge(case)
    if case is not None:
        _case_cache.put(engine, case)
    return case


def all_cases(limit: int = 2000) -> list[Case]:
    """Every stored case with its full result, newest first, for correlation.

    Bounded so a long-running instance cannot be asked to load an unbounded
    table into memory; 2,000 traces is far more than a demo or a pilot holds.
    """
    with Session(_engine) as session:
        stmt = select(Case).order_by(Case.created_at.desc()).limit(limit)
        cases = list(session.scalars(stmt))
        for case in cases:
            session.expunge(case)
        return cases


def list_cases(
    limit: int = 50,
    owner_hash: str | None = None,
    public_addresses: frozenset[str] | None = None,
    everyone: bool = False,
) -> list[Case]:
    """Most recent cases first: the owner's own plus the public demo cases.

    `everyone=True` lists the whole store, for scripts on the server."""
    with Session(_engine) as session:
        stmt = select(Case)
        if not everyone:
            visible = []
            if owner_hash:
                visible.append(Case.owner_hash == owner_hash)
            if public_addresses:
                # Lowercased on both sides: EVM addresses are stored lowercase, Tron
                # ones as spelled, and the demo list is compared case-blind.
                visible.append(Case.owner_hash.is_(None)
                               & func.lower(Case.address).in_(sorted(public_addresses)))
            if not visible:
                return []
            stmt = stmt.where(or_(*visible))
        stmt = stmt.order_by(Case.created_at.desc()).limit(limit)
        cases = list(session.scalars(stmt))
        for case in cases:
            session.expunge(case)
        return cases


def session() -> Session:
    """A session on the case store, for modules with tables of their own here."""
    return Session(_engine)
