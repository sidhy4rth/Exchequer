"""case_identifiers: what the victim reported besides the wallet (app/identifiers.py, suite feature 4).

A scam domain, a Telegram handle, a phone number or a UPI ID, entered by hand
for a case, with who entered it and when. A new table, nothing else touched.

Revision ID: g7_identifiers_1
Revises: g7_exhibits_1
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_identifiers_1"
down_revision: Union[str, Sequence[str], None] = "g7_exhibits_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "case_identifiers" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "case_identifiers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("entered", sa.String(300), nullable=False),
        sa.Column("context", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_case_identifiers_owner_hash", "case_identifiers", ["owner_hash"])
    op.create_index("ix_case_identifiers_case_id", "case_identifiers", ["case_id"])
    op.create_index("ix_case_identifiers_unit_id", "case_identifiers", ["unit_id"])
    op.create_index("ix_case_identifiers_value", "case_identifiers", ["value"])


def downgrade() -> None:
    op.drop_index("ix_case_identifiers_value", table_name="case_identifiers")
    op.drop_index("ix_case_identifiers_unit_id", table_name="case_identifiers")
    op.drop_index("ix_case_identifiers_case_id", table_name="case_identifiers")
    op.drop_index("ix_case_identifiers_owner_hash", table_name="case_identifiers")
    op.drop_table("case_identifiers")
