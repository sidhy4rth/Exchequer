"""Watch cursors and alert times are 64-bit.

watches.last_seen_block holds a Unix time on Tron watches and a block number
elsewhere; alerts.tx_time is Unix seconds. Both were Integer, which is 64-bit
on SQLite but int4 on Postgres: every Tron watch check would fail with
"integer out of range" from 19 January 2038, and Arbitrum block numbers pass
2^31 around then too. Widening only, so an older build still reads them.

On Postgres each ALTER rewrites a small table under a short lock (and gives
up after 5 s if a read holds it: models.guard_migrations).

Revision ID: sec6_bg_1
Revises: 0001
Create Date: 2026-11-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_bg_1"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("watches") as batch:
        batch.alter_column("last_seen_block", existing_type=sa.Integer(), type_=sa.BigInteger(),
                           existing_nullable=True)
    with op.batch_alter_table("alerts") as batch:
        batch.alter_column("tx_time", existing_type=sa.Integer(), type_=sa.BigInteger(),
                           existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.alter_column("tx_time", existing_type=sa.BigInteger(), type_=sa.Integer(),
                           existing_nullable=False)
    with op.batch_alter_table("watches") as batch:
        batch.alter_column("last_seen_block", existing_type=sa.BigInteger(), type_=sa.Integer(),
                           existing_nullable=True)
