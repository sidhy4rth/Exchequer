"""case_tasks.source: which suggestion a task came from (app/tasks.py, suite feature 6).

A task added from a suggestion (a request with no reply, funds with no court
order) records the suggestion's key, so the same suggestion is not made again.
One column, empty for tasks typed by hand.

Revision ID: g7_tasks_2
Revises: g7_tasks_1
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_tasks_2"
down_revision: Union[str, Sequence[str], None] = "g7_tasks_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "source" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("case_tasks")}:
        op.add_column("case_tasks", sa.Column("source", sa.String(80), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("case_tasks") as batch:
        batch.drop_column("source")
