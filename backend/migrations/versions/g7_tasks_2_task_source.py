"""case_tasks.source: which suggestion a task came from (app/tasks.py, suite feature 6).

A task added from a suggestion (a request with no reply, funds with no court
order) records the suggestion's key, so the same suggestion is not made again.
One column, empty for tasks typed by hand, and a unique index on (case_id,
source) over the rows that have one (partial on Postgres and SQLite), so two
requests at the same moment cannot both take a suggestion up: the second
commit fails and is told it is already a task. Every task with a source
counts, open or closed, as tasks.suggestions() does: a declined or finished
suggestion is not offered again.

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


INDEX = "uq_case_tasks_case_source"
TAKEN = sa.text("source <> ''")  # tasks typed by hand ("") are any number


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "source" not in {c["name"] for c in inspector.get_columns("case_tasks")}:
        op.add_column("case_tasks", sa.Column("source", sa.String(80), nullable=False, server_default=""))
    if INDEX not in {i["name"] for i in inspector.get_indexes("case_tasks")}:
        op.create_index(INDEX, "case_tasks", ["case_id", "source"], unique=True,
                        postgresql_where=TAKEN, sqlite_where=TAKEN)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="case_tasks")
    with op.batch_alter_table("case_tasks") as batch:
        batch.drop_column("source")
