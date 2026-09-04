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

from sqlalchemy import String, Text, create_engine, select
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
            "exchange": result.get("exchange"),
            "confidence": result.get("confidence"),
            "flags": result.get("flags", []),
            "hop_count": result.get("hop_count"),
            "node_count": len(result.get("graph", {}).get("nodes", [])),
        }


_engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)


def init_db() -> None:
    """Create the schema if it does not exist. Safe to call repeatedly."""
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    logger.info("SQLite ready at %s", config.DB_PATH)


def new_case_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def save_case(case_id: str, address: str, result: dict[str, Any], created_at: str | None = None) -> Case:
    """Persist one completed trace."""
    case = Case(
        id=case_id,
        address=address,
        created_at=created_at or utc_now_iso(),
        result_json=json.dumps(result, default=str),
    )
    with Session(_engine) as session:
        session.add(case)
        session.commit()
        session.refresh(case)
        session.expunge(case)
    return case


def get_case(case_id: str) -> Case | None:
    with Session(_engine) as session:
        case = session.get(Case, case_id)
        if case is not None:
            session.expunge(case)
        return case


def list_cases(limit: int = 50) -> list[Case]:
    """Most recent cases first."""
    with Session(_engine) as session:
        stmt = select(Case).order_by(Case.created_at.desc()).limit(limit)
        cases = list(session.scalars(stmt))
        for case in cases:
            session.expunge(case)
        return cases
