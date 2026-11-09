"""cases.size_bytes: how large each stored case is, so the store can be
bounded in bytes as well as in cases.

A count alone let a few hundred dense cases (about 1.5 MB each) fill the
hosted database's 0.5 GB. The column is filled here from the cases already
stored, in the database itself (nothing crosses the connection); a stored
result is JSON with non-ASCII escaped, so its length is its size in bytes.
A store made by create_all() from the current models already has it.

Revision ID: sec7_cap_2
Revises: sec7_cap_1
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec7_cap_2"
down_revision: Union[str, Sequence[str], None] = "sec7_cap_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "size_bytes" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("cases")}:
        op.add_column("cases", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.execute("UPDATE cases SET size_bytes = length(result_json) WHERE size_bytes IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("size_bytes")
