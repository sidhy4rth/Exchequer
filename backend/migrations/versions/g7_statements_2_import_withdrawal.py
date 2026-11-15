"""statement_imports can be withdrawn: who, when and why, and a row version
(app/statement_imports.py withdraw, suite feature 5).

A statement or CDR import entered by mistake is withdrawn, never deleted: it
stays in the case record with the reason, hidden from listings unless the
officer asks to see withdrawn imports. Existing rows are not withdrawn and
start at row version 1; adding nullable columns and one with a constant
default rewrites nothing on Postgres.

Revision ID: g7_statements_2
Revises: g7_statements_1
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_statements_2"
down_revision: Union[str, Sequence[str], None] = "g7_statements_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("withdrawn_at", "withdrawn_by", "withdrawn_reason", "row_version")


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("statement_imports")}
    new = {
        "withdrawn_at": sa.Column("withdrawn_at", sa.String(32), nullable=True),
        "withdrawn_by": sa.Column("withdrawn_by", sa.String(64), nullable=True),
        "withdrawn_reason": sa.Column("withdrawn_reason", sa.String(300), nullable=True),
        "row_version": sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    }
    for name in COLUMNS:
        if name not in have:  # a store made by create_all() from the current models has them
            op.add_column("statement_imports", new[name])


def downgrade() -> None:
    with op.batch_alter_table("statement_imports") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
