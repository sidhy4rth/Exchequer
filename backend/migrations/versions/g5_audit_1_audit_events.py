"""audit_events: R24's append-only, hash-chained audit log (app/audit.py).

A table of its own, added and nothing else changed: each row carries the
hash of the one before it, so an edited, deleted or reordered row breaks
the chain and GET /audit/verify says where.

Revision ID: g5_audit_1
Revises: g6_unit_limits_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g5_audit_1"
down_revision: Union[str, Sequence[str], None] = "g6_unit_limits_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("audit_events"):
        return
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("at", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("unit_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_audit_events_case_id", "audit_events", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_case_id", table_name="audit_events")
    op.drop_table("audit_events")
