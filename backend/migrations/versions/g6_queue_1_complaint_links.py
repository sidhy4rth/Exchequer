"""complaint_links: the stored case an officer linked a complaint to
(app/complaints.py ComplaintLink, routes/complaints.py).

Officers only. A new table, nothing else touched; the citizen role
(citizen/api/citizen_role.sql) is never granted it, so a citizen cannot
learn which case their complaint was traced in.

Revision ID: g6_queue_1
Revises: g6_citizen_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g6_queue_1"
down_revision: Union[str, Sequence[str], None] = "g6_citizen_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "complaint_links" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "complaint_links",
        sa.Column("complaint_id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("linked_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("complaint_links")
