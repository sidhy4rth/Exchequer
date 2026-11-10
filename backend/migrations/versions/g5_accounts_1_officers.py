"""Officer accounts (R23): units, officers and their sign-in sessions, and
which officer and unit traced a case.

Additive only: three new tables, and two NULL-able columns on cases that
stay NULL for every case traced before (or without) a sign-in, so every
stored case reads exactly as it did. A session row keeps only the SHA-256 of
its cookie's token. Plain types and constraints, the same on SQLite and on
Postgres.

Revision ID: g5_accounts_1
Revises: g4_recheck_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g5_accounts_1"
down_revision: Union[str, Sequence[str], None] = "g4_recheck_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
    )
    op.create_table(
        "officers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("last_login_at", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_officers_unit_id", "officers", ["unit_id"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("officer_id", sa.Integer(), sa.ForeignKey("officers.id"), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_sessions_officer_id", "sessions", ["officer_id"])
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("cases")}
    if "officer_id" not in columns:
        op.add_column("cases", sa.Column("officer_id", sa.Integer(), nullable=True))
    if "unit_id" not in columns:
        op.add_column("cases", sa.Column("unit_id", sa.Integer(), nullable=True))
        op.create_index("ix_cases_unit_id", "cases", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_cases_unit_id", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("unit_id")
        batch.drop_column("officer_id")
    op.drop_table("sessions")
    op.drop_table("officers")
    op.drop_table("units")
