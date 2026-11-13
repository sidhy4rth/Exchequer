"""domain_lookups: RDAP and DNS facts about a case's scam domains (app/domain_lookup.py, feature 4 slice 2).

Each lookup keeps the facts shown and every response it came from, by source,
fetch time and SHA-256. A new table, nothing else touched.

Revision ID: g7_domain_lookups_1
Revises: g7_identifiers_1
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g7_domain_lookups_1"
down_revision: Union[str, Sequence[str], None] = "g7_identifiers_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "domain_lookups" in sa.inspect(op.get_bind()).get_table_names():
        return  # a store made by create_all() from the current models
    op.create_table(
        "domain_lookups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("identifier_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("queried", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("by", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("records_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_domain_lookups_identifier_id", "domain_lookups", ["identifier_id"])
    op.create_index("ix_domain_lookups_case_id", "domain_lookups", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_domain_lookups_case_id", table_name="domain_lookups")
    op.drop_index("ix_domain_lookups_identifier_id", table_name="domain_lookups")
    op.drop_table("domain_lookups")
