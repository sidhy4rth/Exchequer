"""Custody balance check: the TRX sum (free balance plus stake) on real Tron accounts (#376, feature 9).

custody_balance counts native TRX as TronGrid's free `balance` plus the account's own stake, the
stake it delegated out and the stake being unstaked, and leaves out stake others delegated to it.
Each fixture in fixtures/custody_trx_stake/ is a real keyless TronGrid /v1/accounts answer for a
public account (trimmed to the fields that matter, its `_meta` says which and gives the fetch time),
with the TRX total TronScan's account page showed for the same account at about the same time.

Between them the five accounts carry every stake field the module reads (Stake 2.0 own stake for
bandwidth and energy, stake delegated out for both, stake being unstaked, Stake 1.0 frozen stake for
both) and stake delegated in of all four kinds. The answers are served through the real TronClient
on an httpx.MockTransport; nothing reaches the network.

What TronScan shows apart from the total and the module also leaves out: SR or voting rewards not
yet claimed (`allowance`; TronScan lists them as "Claimable Rewards"), and stake delegated in.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app import config, custody_balance
from app.tron_client import TronClient

FIXTURES = Path(__file__).parent / "fixtures" / "custody_trx_stake"
TRX = config.CHAINS["tron"]

# address: (total in sun, of which staked), each derived field by field from its fixture.
EXPECTED = {
    # MinerGate: balance 304,661 + frozenV2 bandwidth 1,551,000,000 + delegated out for bandwidth
    # 848,251,000,000 + delegated out for energy 6,125,571,000,000.
    "TMG95kirH4cKW5GnKoCcCye1dBqbt77yGu": (6_975_373_304_661, 6_975_373_000_000),
    # Cryptomus: balance 18,584,619,669 + frozenV2 energy 17,347,499,022,174 + delegated out for
    # energy 1,532,000,977,826.
    "TDD97yguPESTpcrJMqU6h2ozZbibv4Vaqm": (18_898_084_619_669, 18_879_500_000_000),
    # HTX-Cold 6: balance 755,759,959,026,665 + unfrozenV2 30,000,000,000,000 (energy) and
    # 1,000,000,000,000 (bandwidth); 1,000,000 delegated in for energy is not counted.
    "TAuUCiH4JVNBZmDnEDZkXEUXDARdGpXTmX": (786_759_959_026_665, 31_000_000_000_000),
    # Kraken: balance 20,000,002 + Stake 1.0 frozen bandwidth 10,000,000 + Stake 1.0 frozen energy
    # 10,000,000; 1,000,000 (2.0 bandwidth) and 40,000,000 (1.0 energy) delegated in are not counted.
    "TBsyKdNsCKNXLgvneeUJ3rbXgWSgk6paTM": (40_000_002, 20_000_000),
    # Binance Staking: balance 617,559,505 and no stake of its own; 207,000,000 + 38,864,000,000
    # (bandwidth) and 7,300,000,000 + 7,000,000 (energy) delegated in are not counted.
    "TLyqzVGLV1srkB7dToTAEqgDSfPtXRJZYH": (617_559_505, 0),
}


def saved(address: str) -> dict:
    return json.loads((FIXTURES / f"{address}.json").read_text())


def read(address: str) -> tuple[int, str, int, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=saved(address)["trongrid_answer"])

    client = TronClient(api_key="", client=httpx.Client(transport=httpx.MockTransport(handle)), min_interval=0)
    try:
        return (*custody_balance._read_raw(client, TRX, address, None), seen)
    finally:
        client.close()


def tronscan_total_sun(address: str) -> int:
    return int(Decimal(saved(address)["_meta"]["tronscan"]["trx_total"].replace(",", "")).scaleb(TRX.native_decimals))


def test_every_saved_account_has_a_fixture_and_an_expected_total():
    assert sorted(p.stem for p in FIXTURES.glob("*.json")) == sorted(EXPECTED)


@pytest.mark.parametrize("address", sorted(EXPECTED))
def test_the_module_total_for_a_real_account_equals_the_derived_figure_and_tronscans(address):
    total, at, staked, seen = read(address)
    assert (total, staked) == EXPECTED[address]
    assert total == tronscan_total_sun(address)
    assert at == "latest block" and [r.url.path for r in seen] == [f"/v1/accounts/{address}"]


def test_the_saved_accounts_cover_every_stake_field_the_module_reads_and_stake_delegated_in():
    accounts = [saved(a)["trongrid_answer"]["data"][0] for a in EXPECTED]
    present = set()
    for a in accounts:
        res = a.get("account_resource", {})
        present |= {k for k in a if k.startswith(("delegated_", "acquired_"))} | {f"res.{k}" for k in res}
        present |= {f"frozenV2.{e.get('type', 'BANDWIDTH')}" for e in a.get("frozenV2", []) if e.get("amount")}
        present |= {"unfrozenV2"} if a.get("unfrozenV2") else set()
        present |= {"frozen"} if a.get("frozen") else set()
    assert {"frozenV2.BANDWIDTH", "frozenV2.ENERGY", "unfrozenV2", "frozen", "res.frozen_balance_for_energy",
            "delegated_frozenV2_balance_for_bandwidth", "res.delegated_frozenV2_balance_for_energy",
            "acquired_delegated_frozenV2_balance_for_bandwidth", "acquired_delegated_frozen_balance_for_bandwidth",
            "res.acquired_delegated_frozenV2_balance_for_energy",
            "res.acquired_delegated_frozen_balance_for_energy"} <= present


def test_stake_delegated_in_and_unclaimed_rewards_are_not_counted():
    """Binance Staking holds no stake of its own but ~46,378 TRX delegated in and ~78,758 TRX of
    unclaimed SR rewards: the module counts neither, and neither does TronScan's TRX total."""
    address = "TLyqzVGLV1srkB7dToTAEqgDSfPtXRJZYH"
    account = saved(address)["trongrid_answer"]["data"][0]
    assert account["allowance"] > 0 and account["acquired_delegated_frozen_balance_for_bandwidth"] > 0
    total, _, staked, _ = read(address)
    assert total == account["balance"] == tronscan_total_sun(address) and staked == 0
