"""Inferred deposit addresses get a table of their own.

Watch alerts used to find them by loading every stored case and parsing its
result after each save. Now each case's inferences are rows here, written
with the case, and looked up by (chain, address). This fills the table from
the cases already stored: only rows whose JSON mentions inferred_deposits are
read, a hundred at a time, and a row that does not parse is skipped.

A store made by create_all() from the current models already has the table;
it is then only filled.

Revision ID: sec6_watch_1
Revises: sec6_bg_3
Create Date: 2026-11-06
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec6_watch_1"
down_revision: Union[str, Sequence[str], None] = "sec6_bg_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH = 100


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("inferred_deposits"):
        op.create_table(
            "inferred_deposits",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("case_id", sa.String(length=36), nullable=False),
            sa.Column("owner_hash", sa.String(length=64), nullable=True),
            sa.Column("seed_address", sa.String(length=64), nullable=False),
            sa.Column("chain", sa.String(length=16), nullable=False),
            sa.Column("address", sa.String(length=64), nullable=False),
            sa.Column("exchange", sa.String(length=64), nullable=False),
        )
        op.create_index("ix_inferred_deposits_case_id", "inferred_deposits", ["case_id"])
        op.create_index("ix_inferred_deposits_chain_address", "inferred_deposits", ["chain", "address"])
    _backfill(bind)


def _rows(case_id, owner_hash, seed, result_json):
    """The same rows models.inferred_deposit_rows writes for a new case,
    frozen here so a later change there cannot change what this did."""
    from app import config
    from app.input_rules import plain_text
    try:
        result = json.loads(result_json)
        chain = config.get_chain(result.get("chain") or "ethereum").key
    except (ValueError, TypeError, AttributeError, config.UnknownChainError):
        return []
    matches = result.get("inferred_deposits")
    out, seen = [], set()
    for match in matches if isinstance(matches, list) else []:
        if not isinstance(match, dict):
            continue
        address, exchange = match.get("address"), match.get("exchange")
        if not (isinstance(address, str) and isinstance(exchange, str) and address.strip() and exchange.strip()):
            continue
        address = address.strip()
        address = address.lower() if address.startswith("0x") else address
        if len(address) > 64 or not address.isalnum() or address in seen:
            continue
        seen.add(address)
        out.append({"case_id": case_id, "owner_hash": owner_hash, "seed_address": (seed or "")[:64],
                    "chain": chain, "address": address, "exchange": plain_text(exchange, 64)})
    return out


def _backfill(bind) -> None:
    table = sa.table("inferred_deposits", sa.column("case_id"), sa.column("owner_hash"),
                     sa.column("seed_address"), sa.column("chain"), sa.column("address"),
                     sa.column("exchange"))
    done = {row[0] for row in bind.execute(sa.text("SELECT DISTINCT case_id FROM inferred_deposits"))}
    last = ""
    while True:
        # Keyset pages by id: no server-side cursor needed, and only the cases
        # that mention inferences cross the connection.
        page = bind.execute(sa.text(
            "SELECT id, owner_hash, address, result_json FROM cases "
            "WHERE id > :last AND result_json LIKE :mention ORDER BY id LIMIT :n"),
            {"last": last, "mention": "%inferred_deposits%", "n": BATCH}).all()
        if not page:
            return
        rows = []
        for case_id, owner_hash, seed, result_json in page:
            if case_id not in done:
                rows += _rows(case_id, owner_hash, seed, result_json)
        if rows:
            bind.execute(table.insert(), rows)
        last = page[-1][0]


def downgrade() -> None:
    op.drop_index("ix_inferred_deposits_chain_address", table_name="inferred_deposits")
    op.drop_index("ix_inferred_deposits_case_id", table_name="inferred_deposits")
    op.drop_table("inferred_deposits")
