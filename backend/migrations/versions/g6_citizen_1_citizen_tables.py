"""The citizen site's tables (app/complaints.py): complaints and their
payments and messages, tracking-code hashes, sessions, and attempt counters.

New tables only, nothing else touched, so this runs beside any other branch's
migration. The citizen functions (citizen/api/) connect as a role granted
only these six tables (docs/citizen-deploy.md). String ids throughout: no
sequence for that role to need. A store made by create_all() from the
current models already has them.

Revision ID: g6_citizen_1
Revises: g5_audit_1
Create Date: 2026-11-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g6_citizen_1"
down_revision: Union[str, Sequence[str], None] = "g5_audit_1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

S = sa.String


def tables() -> dict:
    """{name: (columns, [(indexed column, unique)])}, new Column objects each call."""
    return {
        "complaints": ([
            sa.Column("id", S(36), primary_key=True),
            sa.Column("reference", S(16), nullable=False),
            sa.Column("ncrp", S(32), nullable=False),
            sa.Column("status", S(24), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("wallet_match", S(64), nullable=True),
            sa.Column("created_at", S(32), nullable=False),
            sa.Column("updated_at", S(32), nullable=False),
        ], [("reference", True), ("ncrp", False)]),
        "complaint_payments": ([
            sa.Column("id", S(36), primary_key=True),
            sa.Column("complaint_id", S(36), nullable=False),
            sa.Column("tx_hash", S(100), nullable=False),
            sa.Column("amount", S(32), nullable=False),
            sa.Column("token", S(24), nullable=False),
            sa.Column("network", S(40), nullable=False),
            sa.Column("paid_at", S(40), nullable=False),
            sa.Column("wallet", S(100), nullable=False),
        ], [("complaint_id", False), ("wallet", False)]),
        "complaint_messages": ([
            sa.Column("id", S(36), primary_key=True),
            sa.Column("complaint_id", S(36), nullable=False),
            sa.Column("sender", S(16), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", S(32), nullable=False),
        ], [("complaint_id", False)]),
        "tracking_codes": ([
            sa.Column("complaint_id", S(36), primary_key=True),
            sa.Column("ncrp", S(32), nullable=False),
            sa.Column("salt", S(32), nullable=False),
            sa.Column("code_hash", S(64), nullable=False),
            sa.Column("created_at", S(32), nullable=False),
        ], [("ncrp", False)]),
        "citizen_sessions": ([
            sa.Column("token_hash", S(64), primary_key=True),
            sa.Column("complaint_id", S(36), nullable=False),
            sa.Column("created_at", S(32), nullable=False),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
        ], [("complaint_id", False)]),
        "citizen_attempts": ([
            sa.Column("kind", S(24), primary_key=True),
            sa.Column("key_hash", S(64), primary_key=True),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("first_at", sa.BigInteger(), nullable=False),
            sa.Column("last_at", sa.BigInteger(), nullable=False),
        ], [("last_at", False)]),
    }


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for name, (columns, indexes) in tables().items():
        if name in existing:
            continue
        op.create_table(name, *columns)
        for column, unique in indexes:
            op.create_index(f"ix_{name}_{column}", name, [column], unique=unique)


def downgrade() -> None:
    for name in reversed(list(tables())):
        op.drop_table(name)
