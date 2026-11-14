"""Bind a bank hold's second-officer sign-off to the details it approved.

A freeze request gains details_fingerprint: the SHA-256 of a bank hold's
details (account, IFSC, bank, source, Magistrate's order, amount) as put up
for sign-off (notice_letters.fingerprint), never the details themselves.
Additive only: one NULL-able column, NULL on every request logged before,
so every stored request reads as it did. A bank hold signed off before this
has no fingerprint, so its letter waits for a fresh sign-off.

Revision ID: g7_signoff_binding_1
Revises: g7_domain_lookups_1
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_signoff_binding_1"
down_revision: Union[str, Sequence[str], None] = "g7_domain_lookups_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("freeze_requests")}
    if "details_fingerprint" not in have:
        op.add_column("freeze_requests", sa.Column("details_fingerprint", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("freeze_requests") as batch:
        batch.drop_column("details_fingerprint")
