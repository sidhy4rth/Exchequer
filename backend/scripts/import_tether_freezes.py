"""Build data/frozen_labels*.json: addresses Tether has frozen on USDT.

Tether can blacklist an address on its USDT contract, after which the address
can no longer send USDT. It does so on its own compliance review and at the
request of law enforcement, and it publishes nothing more than the act itself
-- but the act is on chain. Every freeze is an `AddedBlackList(address)` event
emitted by the USDT contract, and every release a `RemovedBlackList(address)`.
Replaying those events in order gives the set of addresses frozen today, from
the contract itself: no dataset, no scrape, no third party between the chain
and the label.

Sources
-------
  Ethereum  USDT 0xdac17f958d2ee523a2206206994597c13d831ec7, events read with
            Etherscan's getLogs.
  Tron      USDT TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t, events read from TronGrid.
BNB Smart Chain's USDT is a Binance-issued peg with no Tether blacklist, so it
has no file.

Verification
------------
The replay is the authority, and a sample is checked against it: for a random
set of frozen addresses (and of released ones) the contract's own public
`isBlackListed(address)` is called, and the import refuses to write if any
answer disagrees with the replay.

What this establishes: Tether has frozen the address's USDT as of the review
date. What it does NOT establish: why. A freeze follows a sanctions match, a
law-enforcement request or a theft, and the event does not say which -- it is a
strong signal that the address was involved in something an issuer acted on,
and a reason to ask Tether, not a finding of guilt.

    cd backend && .venv/bin/python -m scripts.import_tether_freezes
    cd backend && .venv/bin/python -m scripts.import_tether_freezes --dry-run
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, normalize_address  # noqa: E402
from app.risk_matcher import FROZEN  # noqa: E402
from app.tron_client import hex_to_base58  # noqa: E402

ETH_USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
TRON_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# keccak256 of the event signatures, as emitted by the USDT contract.
ADDED = "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc"   # AddedBlackList(address)
REMOVED = "0xd7e9ec6e6ecd65492dce6bf513cd6867560d49544421d0783ddf06e76c24470c"  # RemovedBlackList(address)
IS_BLACKLISTED = "0xe47d6060"  # isBlackListed(address)
TRONGRID = "https://api.trongrid.io"
SAMPLE = 25


# -- Ethereum -------------------------------------------------------------------
def eth_events(client: EtherscanClient, topic: str) -> list[tuple[int, int, str, str, int]]:
    """(block, log index, address, tx hash, timestamp s) for every event with this topic."""
    out: dict[tuple[str, int], tuple[int, int, str, str, int]] = {}
    from_block = 0
    while True:
        logs = client._request({
            "module": "logs", "action": "getLogs", "address": ETH_USDT, "topic0": topic,
            "fromBlock": from_block, "toBlock": "latest", "page": 1, "offset": 1000,
        }) or []
        for log in logs:
            block, index = int(log["blockNumber"], 16), int(log["logIndex"] if log["logIndex"] not in ("", "0x") else "0x0", 16)
            address = normalize_address("0x" + log["data"][-40:])
            out[(log["transactionHash"], index)] = (
                block, index, address, log["transactionHash"], int(log["timeStamp"], 16))
        if len(logs) < 1000:
            break
        # Restart at the last block rather than after it: a page can end
        # partway through a block, and the dedupe above absorbs the overlap.
        from_block = int(logs[-1]["blockNumber"], 16)
    return list(out.values())


def eth_is_blacklisted(client: EtherscanClient, address: str) -> bool:
    data = IS_BLACKLISTED + address[2:].rjust(64, "0")
    result = client._request({"module": "proxy", "action": "eth_call", "to": ETH_USDT,
                              "data": data, "tag": "latest"})
    return int(result or "0x0", 16) == 1


# -- Tron -----------------------------------------------------------------------
def tron_events(http: httpx.Client, name: str) -> list[tuple[int, int, str, str, int]]:
    """(block, index, address, tx, timestamp ms) for every event with this name."""
    url = f"{TRONGRID}/v1/contracts/{TRON_USDT}/events"
    params = {"event_name": name, "limit": 200, "order_by": "block_timestamp,asc"}
    out = []
    while True:
        body = http.get(url, params=params).json()
        for event in body.get("data") or []:
            raw = (event.get("result") or {}).get("_user") or (event.get("result") or {}).get("0") or ""
            address = hex_to_base58("41" + raw[2:] if raw.startswith("0x") else raw)
            out.append((event["block_number"], event.get("event_index", 0), address,
                        event["transaction_id"], event["block_timestamp"]))
        fingerprint = (body.get("meta") or {}).get("fingerprint")
        if not fingerprint:
            return out
        params["fingerprint"] = fingerprint
        time.sleep(0.25)


def _tron_hex(address: str) -> str:
    """Base58 T-address -> 20-byte hex, for an ABI argument."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for char in address:
        num = num * 58 + alphabet.index(char)
    raw = num.to_bytes(25, "big")
    return raw[1:21].hex()


def tron_check(http: httpx.Client, address: str) -> bool:
    body = http.post(f"{TRONGRID}/wallet/triggerconstantcontract", json={
        "owner_address": TRON_USDT, "contract_address": TRON_USDT, "visible": True,
        "function_selector": "isBlackListed(address)", "parameter": _tron_hex(address).rjust(64, "0"),
    }).json()
    result = (body.get("constant_result") or ["0"])[0]
    return int(result or "0", 16) == 1


# -- shared ---------------------------------------------------------------------
def is_system_address(hex20: str) -> bool:
    """True for the zero address and the other tiny "addresses" Tether blacklisted.

    Tether's blacklist includes 0x0000…0000 and a run of addresses like
    0x0000…0018 -- values no private key could plausibly produce. They are
    where tokens are burned and where protocol code lives, not wallets, and a
    burn in any trace would otherwise be reported as a Tether freeze.
    """
    return int(hex20.removeprefix("0x") or "0", 16) < 2**64


def replay(added: list, removed: list) -> dict[str, tuple]:
    """address -> the add event that left it frozen, for every address frozen now."""
    timeline = [(e[0], e[1], 1, e) for e in added] + [(e[0], e[1], 0, e) for e in removed]
    state: dict[str, tuple | None] = {}
    for _block, _index, is_add, event in sorted(timeline, key=lambda t: (t[0], t[1])):
        state[event[2]] = event if is_add else None
    return {address: event for address, event in state.items() if event is not None}


def write(chain_key: str, frozen: dict[str, dict], counts: dict, dry_run: bool) -> None:
    chain = config.CHAINS[chain_key]
    print(f"  {chain_key:<9} {len(frozen):>6} addresses frozen now -> {chain.frozen_labels_path.name}")
    if dry_run:
        return
    document = {
        "_meta": {
            "description": (
                "Addresses whose USDT Tether has frozen. A match means the funds touched a "
                "wallet the stablecoin's issuer has acted against."
            ),
            "provenance": (
                "Replayed from the USDT contract's own AddedBlackList / RemovedBlackList events "
                f"({ETH_USDT if chain_key == 'ethereum' else TRON_USDT}) by "
                "backend/scripts/import_tether_freezes.py. An address is listed if its most "
                "recent event is a freeze."
            ),
            "verification_note": (
                "A random sample of frozen and released addresses was checked against the "
                "contract's own isBlackListed(address) and every answer agreed with the replay. "
                "A freeze establishes that Tether acted on the address; it does NOT say why "
                "(sanctions, a law-enforcement request, a theft), and it is not a finding that a "
                "counterparty took part in anything."
            ),
            "chain": chain_key,
            "last_reviewed": datetime.now(timezone.utc).date().isoformat(),
            "counts": counts,
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.import_tether_freezes",
            "schema": "labels maps an address to {category, entity, label, source}",
        },
        "labels": dict(sorted(frozen.items())),
    }
    chain.frozen_labels_path.write_text(json.dumps(document, indent=1) + "\n")


def record(chain_name: str, address: str, tx: str, when: datetime) -> dict:
    """One label entry; the tx hash is the durable reference to the freeze."""
    day = when.strftime("%Y-%m-%d")
    return {
        "category": FROZEN,
        "entity": "Tether (USDT freeze)",
        "label": f"USDT frozen by Tether on {day}",
        "source": f"Tether USDT contract on {chain_name}, AddedBlackList event, tx {tx}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chain", choices=["ethereum", "tron", "all"], default="all")
    args = parser.parse_args()
    rng = random.Random(7)

    if args.chain in ("ethereum", "all"):
        with EtherscanClient(chain_id=1) as client:
            added, removed = eth_events(client, ADDED), eth_events(client, REMOVED)
            frozen = replay(added, removed)
            frozen = {a: ev for a, ev in frozen.items() if not is_system_address(a)}
            print(f"Ethereum: {len(added)} freezes, {len(removed)} releases, {len(frozen)} frozen now")
            released = sorted({e[2] for e in removed} - set(frozen))
            sample = rng.sample(sorted(frozen), min(SAMPLE, len(frozen))) + rng.sample(released, min(5, len(released)))
            wrong = [a for a in sample if eth_is_blacklisted(client, a) != (a in frozen)]
            print(f"  checked {len(sample)} against isBlackListed(): {len(wrong)} disagree {wrong[:3]}")
            if wrong:
                print("Replay disagrees with the contract; not writing.")
                return 1
        labels = {
            addr: record("Ethereum", addr, ev[3], datetime.fromtimestamp(ev[4], tz=timezone.utc))
            for addr, ev in frozen.items()
        }
        write("ethereum", labels, {"frozen": len(labels), "freeze_events": len(added),
                                   "release_events": len(removed)}, args.dry_run)

    if args.chain in ("tron", "all"):
        headers = {"Accept": "application/json"}
        if config.TRONGRID_API_KEY:
            headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY
        with httpx.Client(timeout=60, headers=headers) as http:
            added = tron_events(http, "AddedBlackList")
            removed = tron_events(http, "RemovedBlackList")
            frozen = replay(added, removed)
            frozen.pop(TRON_USDT, None)  # Tether blacklisted its own contract; not a wallet
            frozen = {a: ev for a, ev in frozen.items() if not is_system_address(_tron_hex(a))}
            print(f"Tron: {len(added)} freezes, {len(removed)} releases, {len(frozen)} frozen now")
            released = sorted({e[2] for e in removed} - set(frozen))
            sample = rng.sample(sorted(frozen), min(SAMPLE, len(frozen))) + rng.sample(released, min(5, len(released)))
            wrong = []
            for address in sample:
                if tron_check(http, address) != (address in frozen):
                    wrong.append(address)
                time.sleep(0.25)
            print(f"  checked {len(sample)} against isBlackListed(): {len(wrong)} disagree {wrong[:3]}")
            if wrong:
                print("Replay disagrees with the contract; not writing.")
                return 1
        labels = {
            addr: record("Tron", addr, ev[3], datetime.fromtimestamp(ev[4] / 1000, tz=timezone.utc))
            for addr, ev in frozen.items()
        }
        write("tron", labels, {"frozen": len(labels), "freeze_events": len(added),
                               "release_events": len(removed)}, args.dry_run)

    if args.dry_run:
        print("\nDry run -- nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
