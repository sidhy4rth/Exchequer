"""The citizen site's tables: complaints sent from it, and what it needs to
let a citizen sign in and read their own case (citizen/api/).

The citizen functions connect as their own database role, granted only these
tables (docs/citizen-deploy.md); this app owns the schema (migration
g6_citizen_1) and reads the queue. Data flows one way: a complaint comes in,
and only a message an officer sends goes back.

complaints.wallet_match is for officers only, never shown to a citizen: a
comma list of "complaint" (another complaint paid the same wallet; set by the
citizen site, which can read complaints) and "case" (a stored case's
reported address; set here, since the citizen role cannot read cases). The
"case" tag is set when the store opens and then every MATCH_EVERY seconds
(start_matching, from main.py), so a new complaint is tagged within that.
"""
from __future__ import annotations

import logging
import threading

from sqlalchemy import BigInteger, Index, Integer, String, Text, func, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from . import models
from .models import Base

logger = logging.getLogger(__name__)
MATCH_EVERY = 15 * 60.0
_stop = threading.Event()
_matcher: threading.Thread | None = None


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reference: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    ncrp: Mapped[str] = mapped_column(String(32), index=True)
    # received | with_cell | investigating | closed (what the citizen sees, coarsely)
    status: Mapped[str] = mapped_column(String(24))
    details_json: Mapped[str] = mapped_column(Text)  # the pack's text fields, as sent
    wallet_match: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class ComplaintPayment(Base):
    __tablename__ = "complaint_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(36), index=True)
    tx_hash: Mapped[str] = mapped_column(String(100))
    amount: Mapped[str] = mapped_column(String(32))
    token: Mapped[str] = mapped_column(String(24))
    network: Mapped[str] = mapped_column(String(40))
    paid_at: Mapped[str] = mapped_column(String(40))
    wallet: Mapped[str] = mapped_column(String(100), index=True)  # a 0x wallet lowercased


class ComplaintMessage(Base):
    __tablename__ = "complaint_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(36), index=True)
    sender: Mapped[str] = mapped_column(String(16))  # citizen | officer (only sent ones are stored)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))


class TrackingCode(Base):
    """Only a scrypt hash of the code shown once to the citizen, and its salt."""

    __tablename__ = "tracking_codes"

    complaint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ncrp: Mapped[str] = mapped_column(String(32), index=True)
    salt: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32))


class CitizenSession(Base):
    """A signed-in citizen: a SHA-256 of the cookie's token, never the token."""

    __tablename__ = "citizen_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[int] = mapped_column(BigInteger)  # Unix seconds; 0 once signed out


class CitizenAttempt(Base):
    """A counter per kind and key (a keyed hash of an NCRP number or a
    connection) in a window: rate limits and sign-in delays. Updated in place,
    so the citizen role needs no DELETE and the table stays bounded."""

    __tablename__ = "citizen_attempts"

    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    first_at: Mapped[int] = mapped_column(BigInteger)
    last_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (Index("ix_citizen_attempts_last_at", "last_at"),)


class ComplaintLink(Base):
    """Officers only: the stored case a complaint was traced in
    (routes/complaints.py). The citizen role is never granted this table."""

    __tablename__ = "complaint_links"

    complaint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(36))
    linked_at: Mapped[str] = mapped_column(String(32))


def merge_tags(current: str | None, tag: str) -> str:
    return ",".join(sorted({t for t in (current or "").split(",") if t} | {tag}))


def flag_case_matches() -> int:
    """Tag "case" on each complaint whose paid wallet is a stored case's
    reported address; returns how many changed. Officers only."""
    with models.session() as s:
        paid = select(ComplaintPayment.complaint_id).join(models.Case, or_(
            models.Case.address == ComplaintPayment.wallet,
            func.lower(models.Case.address) == ComplaintPayment.wallet))
        changed = 0
        for row in s.scalars(select(Complaint).where(Complaint.id.in_(paid))):
            tagged = merge_tags(row.wallet_match, "case")
            if tagged != row.wallet_match:
                row.wallet_match, changed = tagged, changed + 1
        s.commit()
    return changed



def start_matching(every: float = MATCH_EVERY) -> bool:
    """Run flag_case_matches every `every` seconds in the background, the
    first time one interval from now (opening the store runs it at once).
    False if it is already running."""
    global _matcher
    if _matcher and _matcher.is_alive():
        return False
    _stop.clear()

    def loop() -> None:
        while not _stop.wait(every):
            try:
                flag_case_matches()
            except Exception as exc:  # noqa: BLE001 -- the next run tries again
                logger.warning("Could not tag complaints that pay a case's wallet: %s", type(exc).__name__)

    _matcher = threading.Thread(target=loop, name="complaint-case-matches", daemon=True)
    _matcher.start()
    return True


def stop_matching() -> None:
    _stop.set()
    if _matcher:
        _matcher.join(5)
