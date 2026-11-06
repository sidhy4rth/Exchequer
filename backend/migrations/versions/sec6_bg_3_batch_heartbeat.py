"""Batches record when their runner last wrote (heartbeat_at).

The case store is shared by the old and new instance while Render deploys,
and the new one's start-up marked every running batch interrupted, including
those the old instance was still running; the old runner then kept
overwriting their rows. Now only a batch silent for two minutes is marked,
and a runner stops once its batch is no longer running. NULL (every batch
made before this) reads as silent.

Revision ID: sec6_bg_3
Revises: sec6_bg_2
Create Date: 2026-11-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_bg_3"
down_revision: Union[str, Sequence[str], None] = "sec6_bg_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("batches", sa.Column("heartbeat_at", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("batches") as batch:
        batch.drop_column("heartbeat_at")
