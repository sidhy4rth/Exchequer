"""statement_imports: bank or exchange statement rows an officer confirmed against a case
(app/statement_imports.py, suite feature 5).

Only the rows the officer chose to keep, never the whole statement. A new
table, nothing else touched.

Revision ID: g7_statements_1
Revises: g7_custody_2
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_statements_1"
down_revision: Union[str, Sequence[str], None] = "g7_custody_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "statement_imports" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "statement_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(12), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("rows_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
    )
    op.create_index("ix_statement_imports_owner_hash", "statement_imports", ["owner_hash"])
    op.create_index("ix_statement_imports_case_id", "statement_imports", ["case_id"])
    op.create_index("ix_statement_imports_unit_id", "statement_imports", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_statement_imports_unit_id", table_name="statement_imports")
    op.drop_index("ix_statement_imports_case_id", table_name="statement_imports")
    op.drop_index("ix_statement_imports_owner_hash", table_name="statement_imports")
    op.drop_table("statement_imports")
