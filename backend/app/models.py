"""SQLite persistence for traced cases.

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
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, func, inspect, or_, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from . import config

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
    last_seen_block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    """One movement the watcher noticed."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    watch_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # exchange | risk | moved
    message: Mapped[str] = mapped_column(Text)
    tx_hash: Mapped[str] = mapped_column(String(80))
    tx_time: Mapped[int] = mapped_column(Integer)
    value: Mapped[float] = mapped_column(Float)
    asset: Mapped[str] = mapped_column(String(16))
    counterparty: Mapped[str] = mapped_column(String(64))
    counterparty_label: Mapped[str] = mapped_column(String(200), default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)


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


_engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)

# Bumped on every save. Stored cases never change, so anything computed over
# the whole store (correlation, the ledger) stays valid until this moves.
_store_version = 0


def store_version() -> int:
    return _store_version


def init_db() -> None:
    """Create the schema if it does not exist. Safe to call repeatedly."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    _add_missing_columns()
    logger.info("SQLite ready at %s", config.DB_PATH)


def _add_missing_columns() -> None:
    """Bring a store created by an older build up to the current table.

    create_all() makes missing tables but never alters an existing one, and
    the deployed store on the volume predates owner_hash. Additive only: a
    nullable column, so old rows read as unowned."""
    columns = {c["name"] for c in inspect(_engine).get_columns("cases")}
    if "owner_hash" not in columns:
        with _engine.begin() as conn:
            conn.execute(text("ALTER TABLE cases ADD COLUMN owner_hash VARCHAR(64)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cases_owner_hash ON cases (owner_hash)"))
        logger.info("Case store: added owner_hash column")


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
) -> Case:
    """Persist one completed trace."""
    case = Case(
        id=case_id,
        address=address,
        created_at=created_at or utc_now_iso(),
        result_json=json.dumps(result, default=str),
        owner_hash=owner_hash,
    )
    global _store_version
    with Session(_engine) as session:
        session.add(case)
        session.commit()
        session.refresh(case)
        session.expunge(case)
    _store_version += 1
    return case


def get_case(case_id: str) -> Case | None:
    with Session(_engine) as session:
        case = session.get(Case, case_id)
        if case is not None:
            session.expunge(case)
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
