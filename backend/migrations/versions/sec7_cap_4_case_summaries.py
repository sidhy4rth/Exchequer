"""cases.direction and cases.summary_json: what the history list shows, kept
beside each case so listing never reads a whole stored result.

GET /cases read the full result of every visible case to show a dozen small
fields (about 5.85 MB per anonymous request on the deployed store), from a
database whose transfer is metered. Each case now stores its summary when
saved; this fills it for the cases already stored, a hundred at a time, and
a result that does not parse is left without one (the list then reads that
row's result, as before). direction is a column of its own so the demo
copies can be told apart in SQL.
A store made by create_all() from the current models already has them.

Revision ID: sec7_cap_4
Revises: sec7_cap_3
Create Date: 2026-11-08
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sec7_cap_4"
down_revision: Union[str, Sequence[str], None] = "sec7_cap_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BATCH = 100


def summary_fields(result):
    """The same fields models.summary_fields stores for a new case, frozen
    here so a later change there cannot change what this did."""
    return {
        "chain": result.get("chain"),
        "asset": result.get("asset"),
        "direction": result.get("direction", "outgoing"),
        "exchange": result.get("exchange"),
        "confidence": result.get("confidence"),
        "flags": result.get("flags", []),
        "hop_count": result.get("hop_count"),
        "node_count": len((result.get("graph") or {}).get("nodes") or []),
    }


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("cases")}
    if "direction" not in columns:
        op.add_column("cases", sa.Column("direction", sa.String(length=16), nullable=True))
    if "summary_json" not in columns:
        op.add_column("cases", sa.Column("summary_json", sa.Text(), nullable=True))
    last = ""
    while True:
        # Keyset pages by id: no server-side cursor needed.
        page = bind.execute(sa.text(
            "SELECT id, result_json FROM cases WHERE id > :last AND summary_json IS NULL "
            "ORDER BY id LIMIT :n"), {"last": last, "n": BATCH}).all()
        if not page:
            return
        for case_id, result_json in page:
            try:
                result = json.loads(result_json)
                fields = summary_fields(result) if isinstance(result, dict) else None
            except (TypeError, ValueError, AttributeError):
                fields = None
            if fields is None:
                continue
            direction = fields["direction"] if isinstance(fields["direction"], str) else None
            bind.execute(sa.text("UPDATE cases SET direction = :d, summary_json = :s WHERE id = :id"),
                         {"d": (direction or "")[:16] or None, "s": json.dumps(fields, default=str),
                          "id": case_id})
        last = page[-1][0]


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("summary_json")
        batch.drop_column("direction")
