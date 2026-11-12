"""seized_assets: the asset register (app/assets.py, suite feature 9).

Every amount frozen or seized in a case, where it is held, the transaction that
moved it, who holds the keys (names only, never a key), the court deadline and
the outcome. A new table, nothing else touched.

Revision ID: g7_assets_1
Revises: g6_queue_2
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_assets_1"
down_revision: Union[str, Sequence[str], None] = "g6_queue_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "seized_assets" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "seized_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("holder", sa.String(16), nullable=False),
        sa.Column("asset", sa.String(16), nullable=False),
        sa.Column("amount", sa.String(48), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("held_at", sa.String(120), nullable=False),
        sa.Column("tx_hash", sa.String(80), nullable=False),
        sa.Column("key_holders", sa.String(200), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("seized_on", sa.String(10), nullable=False),
        sa.Column("order_ref", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("outcome_ref", sa.String(200), nullable=False),
        sa.Column("outcome_tx", sa.String(80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_seized_assets_owner_hash", "seized_assets", ["owner_hash"])
    op.create_index("ix_seized_assets_case_id", "seized_assets", ["case_id"])
    op.create_index("ix_seized_assets_unit_id", "seized_assets", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_seized_assets_unit_id", table_name="seized_assets")
    op.drop_index("ix_seized_assets_case_id", table_name="seized_assets")
    op.drop_index("ix_seized_assets_owner_hash", table_name="seized_assets")
    op.drop_table("seized_assets")
