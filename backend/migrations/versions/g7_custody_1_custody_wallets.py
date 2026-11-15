"""custody_wallets: records of the unit's multisig custody wallets (app/custody.py, suite feature 9).

The chain, the multisig address, the scheme as entered, the threshold m of n,
the n signers by name, role and unit (never a key), who set it up and when, and
the asset-register rows moved into it. A new table, nothing else touched.

Revision ID: g7_custody_1
Revises: g7_tasks_2
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_custody_1"
down_revision: Union[str, Sequence[str], None] = "g7_tasks_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "custody_wallets" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "custody_wallets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("address", sa.String(64), nullable=False),
        sa.Column("scheme", sa.String(120), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("signers_json", sa.Text(), nullable=False),
        sa.Column("proposer_may_sign", sa.Boolean(), nullable=False),
        sa.Column("set_up_by", sa.String(120), nullable=False),
        sa.Column("set_up_on", sa.String(10), nullable=False),
        sa.Column("asset_ids_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_custody_wallets_owner_hash", "custody_wallets", ["owner_hash"])
    op.create_index("ix_custody_wallets_case_id", "custody_wallets", ["case_id"])
    op.create_index("ix_custody_wallets_unit_id", "custody_wallets", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_custody_wallets_unit_id", table_name="custody_wallets")
    op.drop_index("ix_custody_wallets_case_id", table_name="custody_wallets")
    op.drop_index("ix_custody_wallets_owner_hash", table_name="custody_wallets")
    op.drop_table("custody_wallets")
