"""The trace screen says a label-store row's basis in the report's words (#336).

`tests/fixtures/store_basis_lines.json` holds what `report.basis_lines` gives
for an own-wallet row and two deposit rows. The frontend's
`StoreRowBasis.basisLines` is tested against the same file, so a change to the
report's sentences that is not made on the screen fails one of the two.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.report import basis_lines

CASES = json.loads((Path(__file__).parent / "fixtures" / "store_basis_lines.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_report_gives_the_lines_the_trace_screen_is_tested_against(case):
    assert basis_lines(case["basis"], case["exchange"]) == case["lines"]


def test_the_fixture_has_an_own_wallet_row_and_a_deposit_row():
    assert [bool(c["basis"].get("deposit")) for c in CASES].count(False) >= 1
    assert [bool(c["basis"].get("deposit")) for c in CASES].count(True) >= 1
