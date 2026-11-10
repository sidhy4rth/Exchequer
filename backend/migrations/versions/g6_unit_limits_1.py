"""A unit's own per-officer limits (case references and officer limits).

Additive only: one NULL-able column on units, NULL for every unit, so every
officer keeps the default limits (config.OFFICER_LIMITS) until an admin sets
their unit's own.

Revision ID: g6_unit_limits_1
Revises: g5_signoff_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g6_unit_limits_1"
down_revision: Union[str, Sequence[str], None] = "g5_signoff_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "limits_json" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("units")}:
        op.add_column("units", sa.Column("limits_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("units") as batch:
        batch.drop_column("limits_json")
