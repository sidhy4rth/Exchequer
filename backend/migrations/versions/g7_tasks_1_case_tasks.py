"""case_tasks: a task list per case (app/tasks.py, suite feature 6).

What still has to be done in a case, who it is assigned to (a name), by when,
and what came of it, with every change kept in the row's history. A new table,
nothing else touched.

Revision ID: g7_tasks_1
Revises: g7_domain_lookups_1
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_tasks_1"
down_revision: Union[str, Sequence[str], None] = "g7_domain_lookups_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "case_tasks" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "case_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("assignee", sa.String(120), nullable=False),
        sa.Column("due_on", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_case_tasks_owner_hash", "case_tasks", ["owner_hash"])
    op.create_index("ix_case_tasks_case_id", "case_tasks", ["case_id"])
    op.create_index("ix_case_tasks_unit_id", "case_tasks", ["unit_id"])


def downgrade() -> None:
    op.drop_index("ix_case_tasks_unit_id", table_name="case_tasks")
    op.drop_index("ix_case_tasks_case_id", table_name="case_tasks")
    op.drop_index("ix_case_tasks_owner_hash", table_name="case_tasks")
    op.drop_table("case_tasks")
