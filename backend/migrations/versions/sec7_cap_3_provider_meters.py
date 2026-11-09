"""provider_meters: what each provider credential has spent today, kept in
the store so a restart does not forget it.

The daily allowance lived only in memory, and the free host restarts after
15 idle minutes, so each wake began the day again at zero. One row per
credential and UTC day: the units spent, the requests made and refused, and
each connection's share (by a hash of the connection, never its address).

Revision ID: sec7_cap_3
Revises: sec7_cap_2
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec7_cap_3"
down_revision: Union[str, Sequence[str], None] = "sec7_cap_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("provider_meters"):
        return
    op.create_table(
        "provider_meters",
        sa.Column("name", sa.String(length=80), primary_key=True),
        sa.Column("day", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("used", sa.Float(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("refused", sa.Integer(), nullable=False),
        sa.Column("clients_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("provider_meters")
