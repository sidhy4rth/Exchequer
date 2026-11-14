"""custody_movements: the signing log of a custody wallet (app/custody_log.py, suite feature 9).

Each deposit into or release out of a custody wallet: who proposed it, the
amount and asset, the destination, the court's order for a release, each
signer's approval as an officer recorded it, and the transaction hash once
broadcast. A new table, nothing else touched.

Revision ID: g7_custody_2
Revises: g7_custody_1
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_custody_2"
down_revision: Union[str, Sequence[str], None] = "g7_custody_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "custody_movements" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "custody_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("wallet_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("amount", sa.String(48), nullable=False),
        sa.Column("destination", sa.String(64), nullable=False),
        sa.Column("order_ref", sa.String(200), nullable=False),
        sa.Column("proposed_by", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approvals_json", sa.Text(), nullable=False),
        sa.Column("tx_hash", sa.String(80), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_custody_movements_wallet_id", "custody_movements", ["wallet_id"])
    op.create_index("ix_custody_movements_case_id", "custody_movements", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_custody_movements_case_id", table_name="custody_movements")
    op.drop_index("ix_custody_movements_wallet_id", table_name="custody_movements")
    op.drop_table("custody_movements")
