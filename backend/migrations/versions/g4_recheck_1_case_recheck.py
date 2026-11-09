"""cases.recheck_json: the last second-provider recheck of a case's cited
transfers (POST /trace/{id}/recheck), so GET returns it later.

A column beside the case rather than a table of its own: one recheck per
case, replaced by the next, and a case deleted to make room or pruned takes
its recheck with it. The stored result is untouched. NULL until a recheck
runs. A store made by create_all() from the current models already has it.

Revision ID: g4_recheck_1
Revises: sec7_cap_4
Create Date: 2026-11-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g4_recheck_1"
down_revision: Union[str, Sequence[str], None] = "sec7_cap_4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "recheck_json" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("cases")}:
        op.add_column("cases", sa.Column("recheck_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("recheck_json")
