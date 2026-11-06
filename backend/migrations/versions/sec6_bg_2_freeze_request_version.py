"""Freeze requests carry a row version.

Two PATCHes of one request at the same moment each read history_json, added
an entry and wrote the whole list back, so the later write dropped the
other's dated entry. Every update now checks and bumps row_version
(freeze_requests.update retries on a conflict). Existing rows start at 1;
adding a column with a constant default rewrites nothing on Postgres.

Revision ID: sec6_bg_2
Revises: sec6_bg_1
Create Date: 2026-11-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_bg_2"
down_revision: Union[str, Sequence[str], None] = "sec6_bg_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("freeze_requests", sa.Column("row_version", sa.Integer(), nullable=False,
                                               server_default=sa.text("1")))


def downgrade() -> None:
    with op.batch_alter_table("freeze_requests") as batch:
        batch.drop_column("row_version")
