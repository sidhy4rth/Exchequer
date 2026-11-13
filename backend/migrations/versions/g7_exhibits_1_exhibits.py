"""exhibits: the exhibit register (app/exhibits.py, suite feature 3).

Files outside forensic tools produced for a case, by their hashes (never the
file), with who made them, where they are kept, who holds them and their chain
of custody. A new table, nothing else touched.

Revision ID: g7_exhibits_1
Revises: g7_assets_1
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_exhibits_1"
down_revision: Union[str, Sequence[str], None] = "g7_assets_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "exhibits" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "exhibits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("tool", sa.String(120), nullable=False),
        sa.Column("file_name", sa.String(200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("sha1", sa.String(40), nullable=False),
        sa.Column("md5", sa.String(32), nullable=False),
        sa.Column("made_by", sa.String(120), nullable=False),
        sa.Column("made_on", sa.String(10), nullable=False),
        sa.Column("stored_at", sa.String(200), nullable=False),
        sa.Column("holder", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_exhibits_owner_hash", "exhibits", ["owner_hash"])
    op.create_index("ix_exhibits_case_id", "exhibits", ["case_id"])
    op.create_index("ix_exhibits_unit_id", "exhibits", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_exhibits_unit_id", table_name="exhibits")
    op.drop_index("ix_exhibits_case_id", table_name="exhibits")
    op.drop_index("ix_exhibits_owner_hash", table_name="exhibits")
    op.drop_table("exhibits")
