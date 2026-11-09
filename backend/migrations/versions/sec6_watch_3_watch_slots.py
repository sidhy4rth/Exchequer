"""watches.client_hash and watches.touched_at: who holds a watch slot, and
when its owner last used it.

client_hash is a hash of the connection that made the watch, so one
connection's share can be counted whatever owner keys it invents; touched_at
is when the owner last listed or checked it, so a forgotten watch can give
up its slot when the server is full. Both NULL for watches made before:
those count against no connection, and their creation time stands in.
A store made by create_all() from the current models already has them.

Revision ID: sec6_watch_3
Revises: sec6_watch_2
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_watch_3"
down_revision: Union[str, Sequence[str], None] = "sec6_watch_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("watches")}
    if "client_hash" not in columns:
        op.add_column("watches", sa.Column("client_hash", sa.String(length=64), nullable=True))
    if "touched_at" not in columns:
        op.add_column("watches", sa.Column("touched_at", sa.String(length=32), nullable=True))
    if "ix_watches_client_hash" not in {i["name"] for i in inspector.get_indexes("watches")}:
        op.create_index("ix_watches_client_hash", "watches", ["client_hash"])


def downgrade() -> None:
    op.drop_index("ix_watches_client_hash", table_name="watches")
    with op.batch_alter_table("watches") as batch:
        batch.drop_column("touched_at")
        batch.drop_column("client_hash")
