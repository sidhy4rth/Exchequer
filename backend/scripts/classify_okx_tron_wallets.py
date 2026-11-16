"""Which OKX proof-of-reserves Tron addresses are OKX's own operating wallets.

OKX's proof-of-reserves file (por_csv_2026110100_V1.zip) lists 474,529 Tron
addresses OKX says it controls. Most are customer deposit addresses. ADR-0012
lets a deposit address have a deposit row only when it swept into a wallet the
label file names as OKX's own, and the PoR listing alone does not show which
addresses are those (it is the claim being checked). Until this script, the
Tron label file named one: TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv, "OKX Hot
Wallet 8".

This script reads candidates keylessly from TronGrid and classes each one by
the rules in `classify`. Candidates come from on-chain flows: the PoR
addresses that sent Hot Wallet 8 the most (paged from its incoming USDT), the
PoR addresses Hot Wallet 8 paid, and the PoR addresses that a random sample of
PoR addresses swept into instead of Hot Wallet 8.

Reads, per address (keyless, one request at a time, spaced out):
  * /v1/accounts/{a}: the account (its type, TRX and USDT balances);
  * /v1/accounts/{a}/transactions/trc20 with contract_address = real USDT,
    only_from and only_to, two pages of 200 each: the newest <= 400 USDT
    transfers each way. Only `Transfer` events of the real USDT contract with
    value > 0 count, so a fake token's forged `from` cannot make an address
    look like a payer;
  * /v1/accounts/{a}/transactions, only_from and only_to, one page of 200: the
    TRX transfers (TransferContract, SUCCESS) among them.

"An OKX wallet" is Hot Wallet 8 or any address in the PoR file. A transfer
from an address to itself is no flow with anyone, so it is not read: a PoR
address's self-sends must never meet the "both ways" rule on their own.

    cd backend && .venv/bin/python -m scripts.classify_okx_tron_wallets \\
        --por okx_por_tron.csv \\
        --candidates candidates.json --out evidence.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tron_client import hex_to_base58  # noqa: E402

TRONGRID = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
HOT_WALLET_8 = "TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv"
PACE_S = 2.5

OWN = "own_wallet"
DEPOSIT_LIKE = "deposit_like"
UNCLASSIFIED = "unclassified"

# A wallet that pays real USDT to this many different addresses outside OKX
# within the transfers read is paying withdrawals: only OKX can sign for a PoR
# address, so it is OKX paying out, not one customer's deposit address sweeping.
MIN_PAYEES = 50

RULES = {
    OWN: ("an account (not a contract) that paid real USDT, or TRX, to >= 50 distinct addresses outside OKX in "
          "what was read, and moved value both ways with OKX wallets: it sent real USDT or TRX to one and "
          "received real USDT or TRX from one"),
    DEPOSIT_LIKE: ("everything it sent in what was read (real USDT and TRX) went to OKX wallets: a one-way sweep, "
                   "what a deposit address does"),
    UNCLASSIFIED: "anything else, including a contract, an address that sent nothing read here, or one that paid "
                  "fewer than 50 addresses outside OKX",
}


def summarise(transfers: list[dict], other: str, okx: set[str]) -> dict:
    """Counts for one direction. `other` is the counterparty key ("to" for sent, "from" for received)."""
    parties = [t[other] for t in transfers]
    okx_counts: dict[str, int] = {}
    for party in parties:
        if party in okx:
            okx_counts[party] = okx_counts.get(party, 0) + 1
    return {"n": len(transfers), "distinct": len(set(parties)),
            "distinct_non_okx": len({p for p in parties if p not in okx}),
            "distinct_okx": len(okx_counts), "okx_counts": dict(sorted(okx_counts.items())),
            "value_total": round(sum(t["v"] for t in transfers) / 1e6, 2),
            "value_to_okx": round(sum(t["v"] for t in transfers if t[other] in okx) / 1e6, 2),
            "newest": transfers[0]["ts"] if transfers else None,
            "oldest": transfers[-1]["ts"] if transfers else None,
            "span_days": round((transfers[0]["ts"] - transfers[-1]["ts"]) / 8.64e7, 2) if transfers else None}


def usdt_transfers(rows: list[dict], address: str, side: str) -> list[dict]:
    """Real-USDT `Transfer` events with value > 0 that `address` sent (side "out") or received ("in"), not to itself."""
    kept = []
    for t in rows:
        if (t.get("token_info") or {}).get("address") != USDT or t.get("type") != "Transfer" or int(t["value"]) <= 0:
            continue
        if t["from"] == t["to"]:
            continue
        if (side == "out" and t["from"] != address) or (side == "in" and t["to"] != address):
            continue
        kept.append({"from": t["from"], "to": t["to"], "v": int(t["value"]), "ts": t["block_timestamp"]})
    return kept


def trx_transfers(rows: list[dict], address: str, side: str) -> list[dict]:
    """Successful TRX TransferContract transactions that `address` sent ("out") or received ("in"), not to itself."""
    kept = []
    for t in rows:
        contract = ((t.get("raw_data") or {}).get("contract") or [{}])[0]
        if contract.get("type") != "TransferContract" or (t.get("ret") or [{}])[0].get("contractRet") != "SUCCESS":
            continue
        value = contract["parameter"]["value"]
        sender, receiver = hex_to_base58(value["owner_address"]), hex_to_base58(value["to_address"])
        if sender == receiver or (side == "out" and sender != address) or (side == "in" and receiver != address):
            continue
        kept.append({"from": sender, "to": receiver, "v": int(value.get("amount", 0)), "ts": t["block_timestamp"]})
    return kept


def classify(metrics: dict) -> tuple[str, str]:
    """(class, why) for one address's recorded metrics, by RULES."""
    sides = {name: metrics[name] for name in ("usdt_out", "trx_out", "usdt_in", "trx_in")}
    if metrics["is_contract"]:
        return UNCLASSIFIED, "a contract"
    sent = sides["usdt_out"]["n"] + sides["trx_out"]["n"]
    if sent == 0:
        return UNCLASSIFIED, "sent no real USDT or TRX in what was read"
    payees = max(sides["usdt_out"]["distinct_non_okx"], sides["trx_out"]["distinct_non_okx"])
    if sides["usdt_out"]["distinct_non_okx"] == 0 and sides["trx_out"]["distinct_non_okx"] == 0:
        return DEPOSIT_LIKE, f"all {sent} real-USDT and TRX transfers it sent went to OKX wallets"
    to_okx = max(sides["usdt_out"]["distinct_okx"], sides["trx_out"]["distinct_okx"])
    from_okx = max(sides["usdt_in"]["distinct_okx"], sides["trx_in"]["distinct_okx"])
    if not (to_okx and from_okx):
        return UNCLASSIFIED, "no flow both ways with an OKX wallet in what was read"
    if payees < MIN_PAYEES:
        return UNCLASSIFIED, f"paid only {payees} address{'es' if payees != 1 else ''} outside OKX (fewer than {MIN_PAYEES})"
    asset = "USDT" if sides["usdt_out"]["distinct_non_okx"] >= sides["trx_out"]["distinct_non_okx"] else "TRX"
    side = sides["usdt_out" if asset == "USDT" else "trx_out"]
    return OWN, (f"paid {'real USDT' if asset == 'USDT' else 'TRX'} to {payees} distinct addresses outside OKX in "
                 f"its newest {side['n']} {asset} transfers read ({side['span_days']} days); sent to {to_okx} and "
                 f"received from {from_okx} OKX wallet(s)")


class Reader:
    """Keyless TronGrid, one request at a time, spaced out; waits and retries when the shared quota says so."""

    def __init__(self, client: httpx.Client):
        self.client, self.last = client, 0.0

    def get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(8):
            wait = PACE_S - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                answer = self.client.get(TRONGRID + path, params=params)
            except httpx.HTTPError:
                time.sleep(7 + 3 * attempt)
                continue
            if answer.status_code in (429, 403, 500, 502, 503):
                time.sleep(7 + 3 * attempt)
                continue
            answer.raise_for_status()
            return answer.json()
        raise RuntimeError(f"TronGrid did not answer {path}")

    def pages(self, path: str, params: dict, count: int) -> list[dict]:
        rows, params = [], dict(params)
        for _ in range(count):
            body = self.get(path, params)
            rows.extend(body.get("data", []))
            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if not fingerprint:
                break
            params["fingerprint"] = fingerprint
        return rows


def read(reader: Reader, address: str, okx: set[str]) -> dict:
    account = (reader.get(f"/v1/accounts/{address}").get("data") or [{}])[0]
    usdt_balance = next((int(d[USDT]) / 1e6 for d in account.get("trc20") or [] if USDT in d), 0.0)
    query = {"only_confirmed": "true", "limit": 200, "contract_address": USDT}
    sent = reader.pages(f"/v1/accounts/{address}/transactions/trc20", {**query, "only_from": "true"}, 2)
    got = reader.pages(f"/v1/accounts/{address}/transactions/trc20", {**query, "only_to": "true"}, 2)
    trx = {side: reader.get(f"/v1/accounts/{address}/transactions",
                            {"only_confirmed": "true", "limit": 200, f"only_{'from' if side == 'out' else 'to'}": "true"})
           .get("data", []) for side in ("out", "in")}
    return {"in_por": address in okx, "is_contract": account.get("type") == "Contract",
            "trx_balance": account.get("balance", 0) / 1e6, "usdt_balance": usdt_balance,
            "create_time": account.get("create_time"), "read_on": time.strftime("%Y-%m-%d", time.gmtime()),
            "usdt_out": summarise(usdt_transfers(sent, address, "out"), "to", okx),
            "usdt_in": summarise(usdt_transfers(got, address, "in"), "from", okx),
            "trx_out": summarise(trx_transfers(trx["out"], address, "out"), "to", okx),
            "trx_in": summarise(trx_transfers(trx["in"], address, "in"), "from", okx)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--por", type=Path, required=True, help="the staged OKX Tron PoR rows (okx_por_tron.csv)")
    parser.add_argument("--candidates", type=Path, required=True, help="JSON list of addresses to read")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.por.open(encoding="utf-8") as handle:
        okx = {row["address"] for row in csv.DictReader(handle)} | {HOT_WALLET_8}
    found: dict[str, dict] = {}
    with httpx.Client(timeout=40, headers={"Accept": "application/json", "User-Agent": "Exchequer/1.0"}) as client:
        reader = Reader(client)
        for address in json.loads(args.candidates.read_text(encoding="utf-8")):
            found[address] = read(reader, address, okx)
            found[address]["class"], found[address]["why"] = classify(found[address])
            print(address, found[address]["class"], found[address]["why"], flush=True)
    args.out.write_text(json.dumps({"rules": RULES, "addresses": found}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
