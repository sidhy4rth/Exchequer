"""Second-officer sign-off on urgent freeze letters.

A freeze request now records the officer and unit that drafted it, and the
officer who signed it off, with their name and when. Additive only: five
NULL-able columns, NULL on every request logged before (or without) a
sign-in, so every stored request reads exactly as it did.

Revision ID: g5_signoff_1
Revises: g5_accounts_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g5_signoff_1"
down_revision: Union[str, Sequence[str], None] = "g5_accounts_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [("officer_id", sa.Integer()), ("unit_id", sa.Integer()), ("signed_off_by", sa.Integer()),
           ("signed_off_name", sa.String(length=120)), ("signed_off_at", sa.String(length=32))]


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("freeze_requests")}
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column("freeze_requests", sa.Column(name, kind, nullable=True))
    if "unit_id" not in have:
        op.create_index("ix_freeze_requests_unit_id", "freeze_requests", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_freeze_requests_unit_id", table_name="freeze_requests")
    with op.batch_alter_table("freeze_requests") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
