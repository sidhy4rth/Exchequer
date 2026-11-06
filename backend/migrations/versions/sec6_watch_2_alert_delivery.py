"""alerts.delivery: whether an alert has been posted to its watch's webhook.

pending, sent or failed; NULL for alerts of a watch without a webhook, and
for every alert stored before this column existed (never posted late).
A store made by create_all() from the current models already has it.

Revision ID: sec6_watch_2
Revises: sec6_watch_1
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_watch_2"
down_revision: Union[str, Sequence[str], None] = "sec6_watch_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("alerts")}
    if "delivery" not in columns:
        op.add_column("alerts", sa.Column("delivery", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("delivery")
