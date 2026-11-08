"""cases.client_hash and cases.anonymous: which connection saved a case, and
whether it was saved without an owner key.

client_hash is a hash of the connection that saved the case, so how many one
connection saves a day is counted whatever owner keys it invents. anonymous
marks a trace sent without an owner key (a script, curl): private to its link
from the start and claimed by no browser, so the first to give up its place
when the store is full. Both NULL for cases saved before: those count against
no connection, and are not taken for anonymous.
A store made by create_all() from the current models already has them.

Revision ID: sec7_cap_1
Revises: sec6_watch_3
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec7_cap_1"
down_revision: Union[str, Sequence[str], None] = "sec6_watch_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("cases")}
    if "client_hash" not in columns:
        op.add_column("cases", sa.Column("client_hash", sa.String(length=64), nullable=True))
    if "anonymous" not in columns:
        op.add_column("cases", sa.Column("anonymous", sa.Boolean(), nullable=True))
    if "ix_cases_client_hash" not in {i["name"] for i in inspector.get_indexes("cases")}:
        op.create_index("ix_cases_client_hash", "cases", ["client_hash"])


def downgrade() -> None:
    op.drop_index("ix_cases_client_hash", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("anonymous")
        batch.drop_column("client_hash")
