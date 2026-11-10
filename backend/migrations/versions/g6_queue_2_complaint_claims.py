"""complaint_claims: the unit that claimed a citizen's complaint
(app/complaints.py ComplaintClaim, routes/complaints.py).

Officers only. A new table, nothing else touched; the citizen role
(citizen/api/citizen_role.sql) is never granted it, so a citizen cannot
learn which unit has their complaint. A complaint with no row is unclaimed.

Revision ID: g6_queue_2
Revises: g6_queue_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g6_queue_2"
down_revision: Union[str, Sequence[str], None] = "g6_queue_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "complaint_claims" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "complaint_claims",
        sa.Column("complaint_id", sa.String(36), primary_key=True),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_complaint_claims_unit_id", "complaint_claims", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_complaint_claims_unit_id", table_name="complaint_claims")
    op.drop_table("complaint_claims")
