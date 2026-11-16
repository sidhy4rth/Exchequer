"""custody_balance_checks: runs of the custody balance check (app/custody_balance.py, suite feature 9 part 2).

Each run keeps, per custody address and asset, the balance a provider gave, what
the asset register records, whether they match, and the provider's evidence
(request, SHA-256 of the answer, time). A new table, nothing else touched.

Revision ID: g7_custody_3
Revises: g7_statements_2
Create Date: 2026-11-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_custody_3"
down_revision: Union[str, Sequence[str], None] = "g7_statements_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "custody_balance_checks" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "custody_balance_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.String(32), nullable=False),
        sa.Column("checked_by", sa.String(64), nullable=False),
        sa.Column("results_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_custody_balance_checks_owner_hash", "custody_balance_checks", ["owner_hash"])
    op.create_index("ix_custody_balance_checks_case_id", "custody_balance_checks", ["case_id"])
    op.create_index("ix_custody_balance_checks_unit_id", "custody_balance_checks", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_custody_balance_checks_unit_id", table_name="custody_balance_checks")
    op.drop_index("ix_custody_balance_checks_case_id", table_name="custody_balance_checks")
    op.drop_index("ix_custody_balance_checks_owner_hash", table_name="custody_balance_checks")
    op.drop_table("custody_balance_checks")
