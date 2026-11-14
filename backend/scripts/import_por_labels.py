"""Label Bybit's and OKX's own wallets on the EVM chains from their proof-of-reserves lists.

Why these sources
-----------------
An exchange's proof-of-reserves (PoR) file is the exchange naming its own
wallets: it publishes the addresses whose balances back its customers' funds
so anyone can check them. That is a first-party attribution, stronger than an
explorer tag someone else scraped, and the owner accepted it as a label source
on 15 Nov 2026. Before this, Bybit had one label on each EVM chain.

  Bybit   https://api2.bybit.com/common-static/por/bybit_por_<YYYYMM>.csv, the
          "Download Proof of Funds" file behind https://www.bybit.com/en/proof-of-reserve.
          One row per "<COIN>-<network>", its Address column space-separated.
  OKX     https://static.okx.com/cdn/okx/por/chain/por_csv_<date>_V<n>.zip, linked
          from https://www.okx.com/proof-of-reserves/download. One row per
          address, with OKX's signature of "I am an OKX address".

What the files say, and what they do not: each lists wallets the exchange says
it controls, on a named network, at a snapshot height. Neither says which are
hot and which cold, so every row is typed exchange_wallet ("role not
recorded"), or contract_wallet where the address holds contract code (a
multisig). The source's own words go in `source_kind`.

The rule, per address and chain (gather() offline, then check() on chain):
  1. a well-formed 0x address the source lists on that network;
  2. not named by both exchanges' lists, not already another exchange's label
     on any chain, and not in this chain's router, risk, threat, frozen,
     sanctions, gambling or privacy-protocol files, the instant-exchanger seed, a demo, a token
     list (app/never_flag.tokens) or the label store: each is a conflict,
     reported and left out, never overwritten;
  3. on chain, through a keyless public RPC: not a token contract (an ERC-20's
     totalSupply() answers), and used -- it has sent a transaction (nonce > 0),
     or holds the native coin, USDT or USDC (a cold wallet may only receive).
An address the file already labels for the same exchange keeps its label.

    cd backend && .venv/bin/python -m scripts.import_por_labels \\
        --bybit bybit_por_202610.csv --okx okx_por_2026110100_V1.csv \\
        --checks por_checks.json --store label_store.db --dry-run

The CSVs are downloaded by hand (they are not fetched here) and read as data.
--checks is a JSON checkpoint of the chain reads, so a rerun asks the RPCs
nothing it has asked already.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import time
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, never_flag  # noqa: E402
from app.exchange_matcher import INSTANT_EXCHANGERS_FILE  # noqa: E402

CHAINS = ("ethereum", "bsc", "polygon", "arbitrum")
ADDRESS = re.compile(r"0x[0-9a-f]{40}")
META_KEY = "por_2026_11_15"
csv.field_size_limit(1 << 24)  # Bybit's Address column holds every address of a network

# Each exchange's network names -> this repository's chain keys. Anything not
# listed (Arbitrum Nova, Optimism, Base...) is a chain Exchequer does not trace.
NETWORKS = {
    "Bybit": {"Ethereum": "ethereum", "BSC": "bsc", "Polygon": "polygon", "Arbitrum": "arbitrum"},
    # OKX's Network column (November 2026 file); it lists no BNB Smart Chain wallets.
    "OKX": {"ETH": "ethereum", "BSC": "bsc", "POLYGON": "polygon", "ARBITRUM": "arbitrum"},
}

# Where each row came from. Filled in from the files actually read (see SOURCES).
SOURCES: dict[str, dict[str, str]] = {
    "Bybit": {
        "publisher": "Bybit",
        "page": "https://www.bybit.com/en/proof-of-reserve",
        "kind": "Bybit proof-of-reserves wallet ('Proof of Funds' file; no hot or cold role given)",
    },
    "OKX": {
        "publisher": "OKX",
        "page": "https://www.okx.com/proof-of-reserves/download",
        "kind": "OKX proof-of-reserves address, type 'Non Staking' (signed 'I am an OKX address'; "
                "no hot or cold role given)",
    },
}

# A keyless public node per chain; each answers JSON-RPC batches.
RPC = {
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "bsc": "https://bsc-rpc.publicnode.com",
    "polygon": "https://polygon-bor-rpc.publicnode.com",
    "arbitrum": "https://arbitrum-one-rpc.publicnode.com",
}
TOTAL_SUPPLY = "0x18160ddd"  # ERC-20 totalSupply()
SAFE_THRESHOLD = "0xe75235b8"  # Gnosis Safe getThreshold()
BALANCE_OF = "0x70a08231"  # ERC-20 balanceOf(address)
DELEGATED = "0xef0100"  # EIP-7702: an account whose code only points at a delegate is still an account


# -- reading the sources -------------------------------------------------------------

def parse_bybit(text: str) -> dict[str, dict[str, set[str]]]:
    """{chain: {address: {network rows that list it}}} from Bybit's PoR CSV."""
    found: dict[str, dict[str, set[str]]] = {c: {} for c in CHAINS}
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or [h.strip() for h in header[:4]] != ["Coin", "Height", "Amount", "Address"]:
        raise ValueError("not Bybit's PoR CSV (header Coin,Height,Amount,Address)")
    for row in reader:
        if len(row) < 4 or "-" not in row[0]:
            continue  # "<COIN>(ALL)" totals name no network
        coin, network = row[0].split("-", 1)
        chain = NETWORKS["Bybit"].get(network.strip())
        if chain is None:
            continue
        for address in row[3].split():
            address = address.strip().lower()
            if ADDRESS.fullmatch(address):
                found[chain].setdefault(address, set()).add(f"{coin}-{network}@{row[1].strip()}")
    return found


def _address_section(lines: Iterable[str]) -> Iterable[dict[str, str]]:
    """The rows under the header that names an address column: OKX's file opens
    with a coin,amount totals table, then the per-address table."""
    lines = iter(lines)
    for line in lines:
        if "address" in [c.strip().lower() for c in line.split(",")]:
            yield from csv.DictReader(lines, fieldnames=next(csv.reader([line])))
            return


def _okx_rows(path: Path) -> Iterable[dict[str, str]]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".csv"):
                    with archive.open(name) as handle:
                        yield from _address_section(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
        return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from _address_section(handle)


def parse_okx(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, set[str]]]:
    """{chain: {address: {coin@network}}} from OKX's PoR CSV rows."""
    found: dict[str, dict[str, set[str]]] = {c: {} for c in CHAINS}
    for row in rows:
        fields = {k.strip().lower(): (v or "").strip() for k, v in row.items() if isinstance(k, str)
                  and (v is None or isinstance(v, str))}
        network = fields.get("network") or fields.get("chain") or ""
        chain = NETWORKS["OKX"].get(network)
        address = (fields.get("address") or "").lower()
        if chain is None or not ADDRESS.fullmatch(address):
            continue  # another chain, or a validator key (48 bytes), not an account
        if fields.get("type", "Non Staking").lower() != "non staking":
            continue  # a staking position, not a wallet funds are paid into
        coin = fields.get("coin") or fields.get("currency") or "?"
        kind = f" ({fields['type']})" if fields.get("type") else ""
        found[chain].setdefault(address, set()).add(f"{coin}{kind}@{network}")
    return found


# -- what each chain already names ---------------------------------------------------

def _labels(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    labels = document.get("labels", document) if isinstance(document, dict) else {}
    return {a.lower(): m for a, m in labels.items() if isinstance(a, str) and a.startswith("0x")}


def _demo_addresses() -> set[str]:
    found: set[str] = set()
    for name in ("demo_traces.json", "recorded_demos.json", "demo_expectations.json"):
        path = config.DATA_DIR / name
        if path.is_file():
            found |= {a.lower() for a in ADDRESS.findall(path.read_text(encoding="utf-8").lower())}
    return found


def _instant(chain: str) -> set[str]:
    path = config.DATA_DIR / INSTANT_EXCHANGERS_FILE
    rows = json.loads(path.read_text(encoding="utf-8")).get("rows", []) if path.is_file() else []
    return {r["address"].lower() for r in rows if r.get("chain") == chain and isinstance(r.get("address"), str)}


def listed(chain: str) -> dict[str, str]:
    """{address: which file} for every address this chain's other files name."""
    c = config.CHAINS[chain]
    files = {"router": c.router_labels_path, "risk": c.risk_labels_path, "threat": c.threat_labels_path,
             "frozen": c.frozen_labels_path, "sanctions": c.intl_sanctions_path,
             "gambling": c.gambling_labels_path, "privacy protocol": c.privacy_protocols_path}
    out: dict[str, str] = {}
    for what, path in files.items():
        for address in _labels(path):
            out.setdefault(address, what)
    for other in config.CHAINS.values():  # a router is the same contract on every EVM chain
        if other.address_family == "evm":
            for address in _labels(other.router_labels_path):
                out.setdefault(address, "router")
    for address in _instant(chain):
        out.setdefault(address, "instant exchanger")
    return out


def store_hits(store: Path | None, chain: str, addresses: Iterable[str]) -> dict[str, str]:
    """{address: category} for addresses the label store holds a row for on this chain."""
    if store is None:
        return {}
    from app.label_store import CHAIN_IDS, encode_address
    db = sqlite3.connect(f"file:{store}?mode=ro&immutable=1", uri=True)
    try:
        out = {}
        for address in addresses:
            row = db.execute("SELECT category FROM labels WHERE address=? AND chain=?",
                             (encode_address(address), CHAIN_IDS[chain])).fetchone()
            if row:
                out[address] = f"label store: {row[0]}"
        return out
    finally:
        db.close()


def gather(found: dict[str, dict[str, dict[str, set[str]]]], store: Path | None = None
           ) -> tuple[dict[str, dict[str, dict]], dict[str, list[dict]], dict[str, dict[str, int]]]:
    """(candidates {chain: {address: {exchange, seen}}}, conflicts {chain: [...]}, counts).

    `found` is {exchange: {chain: {address: rows}}} from the parsers."""
    all_labels = {c: _labels(config.CHAINS[c].labels_path) for c in config.CHAINS
                  if config.CHAINS[c].address_family == "evm"}
    demos = _demo_addresses()
    candidates: dict[str, dict[str, dict]] = {c: {} for c in CHAINS}
    conflicts: dict[str, list[dict]] = {c: [] for c in CHAINS}
    counts: dict[str, dict[str, int]] = {}
    for chain in CHAINS:
        others = listed(chain)
        tokens = never_flag.tokens(chain)
        by_exchange: dict[str, set[str]] = {}
        for exchange, chains in found.items():
            for address in chains.get(chain, {}):
                by_exchange.setdefault(address, set()).add(exchange)
        hits = store_hits(store, chain, by_exchange)
        for address, exchanges in sorted(by_exchange.items()):
            for exchange in sorted(exchanges):
                tally = counts.setdefault(f"{exchange}/{chain}", {"listed": 0, "kept": 0, "already": 0,
                                                                  "conflict": 0})
                tally["listed"] += 1
                why = None
                mine = all_labels[chain].get(address)
                if len(exchanges) == 1 and isinstance(mine, dict) and mine.get("exchange") == exchange:
                    tally["already"] += 1  # its label stays as it is
                    continue
                if len(exchanges) > 1:
                    why = "listed by both " + " and ".join(sorted(exchanges))
                elif never_flag._raw(chain, address) in tokens:
                    why = "token list (app/never_flag.tokens)"
                elif address in others:
                    why = f"{others[address]} file"
                elif address in demos:
                    why = "a recorded demo names it"
                elif address in hits:
                    why = hits[address]
                else:
                    for other_chain, labels in all_labels.items():
                        meta = labels.get(address)
                        if meta and isinstance(meta, dict) and meta.get("exchange") != exchange:
                            why = f"labelled {meta.get('exchange')} ({meta.get('label')}) on {other_chain}"
                            break
                if why:
                    tally["conflict"] += 1
                    conflicts[chain].append({"address": address, "exchange": exchange, "why": why})
                    continue
                candidates[chain][address] = {"exchange": exchange, "seen": sorted(found[exchange][chain][address])}
                tally["kept"] += 1
    return candidates, conflicts, counts


# -- on chain ------------------------------------------------------------------------

def _rpc(chain: str, calls: list[tuple[str, list]]) -> list[Any]:
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)])
    request = urllib.request.Request(RPC[chain], data=body.encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "exchequer-labels"})
    with urllib.request.urlopen(request, timeout=30) as response:
        answers = json.loads(response.read())
    by_id = {a.get("id"): a for a in answers} if isinstance(answers, list) else {}
    return [by_id.get(i, {}).get("result") for i in range(len(calls))]


def read_accounts(chain: str, addresses: list[str]) -> dict[str, dict[str, Any]]:
    """Code, nonce and native balance of each address, in one batch; and for a
    contract, whether it answers totalSupply() (a token) or getThreshold() (a Safe)."""
    calls = [(m, [a, "latest"]) for a in addresses for m in ("eth_getCode", "eth_getTransactionCount", "eth_getBalance")]
    answers = _rpc(chain, calls)
    out: dict[str, dict[str, Any]] = {}
    for i, address in enumerate(addresses):
        code, nonce, balance = answers[3 * i:3 * i + 3]
        if code is None or nonce is None or balance is None:
            continue  # asked again on the next run
        out[address] = {"code": len(code) > 2, "delegated": code.startswith(DELEGATED), "nonce": int(nonce, 16),
                        "balance": int(balance, 16)}
    idle = [a for a, r in out.items() if r["nonce"] == 0 and r["balance"] == 0]
    tokens = [t.address for t in config.CHAINS[chain].tokens]  # USDT and USDC: what a cold wallet may hold alone
    if idle and tokens:
        answers = _rpc(chain, [("eth_call", [{"to": t, "data": BALANCE_OF + a[2:].rjust(64, "0")}, "latest"])
                               for a in idle for t in tokens])
        for i, address in enumerate(idle):
            held = answers[len(tokens) * i:len(tokens) * (i + 1)]
            out[address]["stablecoins"] = sum(int(h, 16) for h in held if h and len(h) == 66)
    contracts = [a for a, r in out.items() if r["code"] and not r["delegated"]]
    if contracts:
        answers = _rpc(chain, [("eth_call", [{"to": a, "data": d}, "latest"])
                               for a in contracts for d in (TOTAL_SUPPLY, SAFE_THRESHOLD)])
        for i, address in enumerate(contracts):
            supply, threshold = answers[2 * i:2 * i + 2]
            out[address]["erc20"] = bool(supply and len(supply) == 66)
            out[address]["safe"] = bool(threshold and len(threshold) == 66 and int(threshold, 16) > 0)
    return out


def check(candidates: dict[str, dict[str, dict]], checkpoint: Path, batch: int = 25,
          pause: float = 1.0) -> dict[str, dict]:
    """Read every candidate on chain (keyless, `batch` addresses a request), resuming from `checkpoint`."""
    done: dict[str, dict] = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {}
    for chain, found in candidates.items():
        todo = [a for a in found if f"{chain}:{a}" not in done]
        for start in range(0, len(todo), batch):
            part = todo[start:start + batch]
            for attempt in range(4):
                try:
                    done |= {f"{chain}:{a}": r for a, r in read_accounts(chain, part).items()}
                    break
                except Exception as exc:  # noqa: BLE001 -- a public node's hiccup; retried, then reported
                    if attempt == 3:
                        print(f"  {chain} {part[0]}..: {exc}", file=sys.stderr)
                    time.sleep(3 * (attempt + 1))
            checkpoint.write_text(json.dumps(done, indent=1))
            print(f"  {chain}: {min(start + batch, len(todo))}/{len(todo)}", file=sys.stderr, flush=True)
            time.sleep(pause)
    return done


def verdict(account: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(type, None) for a usable wallet, or (None, why it is left out)."""
    if account is None:
        return None, "not read on chain"
    if account.get("erc20"):
        return None, "a token contract (answers totalSupply)"
    if not (account["nonce"] > 0 or account["balance"] > 0 or account.get("stablecoins", 0) > 0):
        return None, "no activity on chain (nonce 0, no native coin, no USDT or USDC)"
    if account["code"] and not account["delegated"]:
        return "contract_wallet", None
    return "exchange_wallet", None


# -- writing the label files ---------------------------------------------------------

LABEL = "{exchange}: Reserve Wallet {n}"
_NUMBERED = re.compile(r"^(?P<exchange>.+): Reserve Wallet (?P<n>\d+)$")


def numbering(exchange: str, addresses: Iterable[str]) -> dict[str, int]:
    """A number per address, the same on every chain: one already given keeps
    its number, a new one (in address order) takes the next free number."""
    given: dict[str, int] = {}
    for chain in config.CHAINS.values():
        if chain.address_family != "evm":
            continue
        for address, meta in _labels(chain.labels_path).items():
            found = _NUMBERED.match(meta.get("label", "")) if isinstance(meta, dict) else None
            if found and found["exchange"] == exchange:
                given[address] = int(found["n"])
    top = max(given.values(), default=0)
    for address in sorted(set(addresses) - set(given)):
        top += 1
        given[address] = top
    return given


def rows(candidates: dict[str, dict[str, dict]], accounts: dict[str, dict], source: dict[str, dict[str, str]]
         ) -> tuple[dict[str, dict[str, dict]], dict[str, list[dict]]]:
    """({chain: {address: label row}}, {chain: [left out on chain]}).

    `source` is {exchange: {url, archive, source_date, retrieved}} for the files read."""
    out: dict[str, dict[str, dict]] = {c: {} for c in candidates}
    left: dict[str, list[dict]] = {c: [] for c in candidates}
    kept: dict[str, list[tuple[str, str, str]]] = {}
    for chain, found in candidates.items():
        for address, meta in sorted(found.items()):
            kind, why = verdict(accounts.get(f"{chain}:{address}"))
            if why:
                left[chain].append({"address": address, "exchange": meta["exchange"], "why": why})
                continue
            kept.setdefault(meta["exchange"], []).append((chain, address, kind))
    for exchange, items in kept.items():
        numbers = numbering(exchange, (a for _, a, _ in items))
        cite = source[exchange]
        for chain, address, kind in items:
            row = {"exchange": exchange, "label": LABEL.format(exchange=exchange, n=numbers[address]), "type": kind,
                   "source_kind": SOURCES[exchange]["kind"], "source": cite["url"]}
            if cite.get("archive"):
                row["source_archive"] = cite["archive"]
            row["source_date"], row["retrieved"] = cite["source_date"], cite["retrieved"]
            out[chain][address] = row
    return out, left


def apply(new_rows: dict[str, dict[str, dict]], note: dict[str, Any]) -> dict[str, int]:
    """Add the rows to each chain's label file (never replacing one) and record `note` in its _meta."""
    added = {}
    for chain, found in new_rows.items():
        path = config.CHAINS[chain].labels_path
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        indent = 2 if text.startswith('{\n  "') else 1
        labels = document["labels"]
        fresh = {a: r for a, r in found.items() if a not in labels}
        in_order = list(labels) == sorted(labels)
        labels.update(fresh)
        if in_order:  # a file kept in address order stays in it
            document["labels"] = dict(sorted(labels.items()))
        document["_meta"][META_KEY] = {**note, "added": {
            e: sum(1 for r in fresh.values() if r["exchange"] == e) for e in sorted({r["exchange"] for r in fresh.values()})}}
        path.write_text(json.dumps(document, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
        added[chain] = len(fresh)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bybit", type=Path, help="Bybit's PoR CSV, downloaded by hand")
    parser.add_argument("--okx", type=Path, help="OKX's PoR zip or CSV, downloaded by hand")
    parser.add_argument("--sources", type=Path, required=True,
                        help='JSON {"Bybit": {"url", "archive", "source_date", "retrieved"}, "OKX": {...}}')
    parser.add_argument("--checks", type=Path, required=True, help="checkpoint of the on-chain reads")
    parser.add_argument("--store", type=Path, help="a label-store release to check for rows on these addresses")
    parser.add_argument("--report", type=Path, help="write counts, conflicts and the left-out list here")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    found: dict[str, dict[str, dict[str, set[str]]]] = {}
    if args.bybit:
        found["Bybit"] = parse_bybit(args.bybit.read_text(encoding="utf-8-sig"))
    if args.okx:
        found["OKX"] = parse_okx(_okx_rows(args.okx))
    if not found:
        parser.error("give --bybit and/or --okx")
    source = json.loads(args.sources.read_text())
    candidates, conflicts, counts = gather(found, store=args.store)
    accounts = check(candidates, args.checks)
    new_rows, left = rows(candidates, accounts, source)
    for chain in CHAINS:
        for row in new_rows[chain].values():
            counts[f"{row['exchange']}/{chain}"].setdefault("added", 0)
            counts[f"{row['exchange']}/{chain}"]["added"] += 1
    report = {"counts": counts, "conflicts": conflicts, "left_out_on_chain": left}
    if args.report:
        args.report.write_text(json.dumps(report, indent=1))
    print(json.dumps(counts, indent=1))
    if not args.dry_run:
        note = {"rule": "scripts/import_por_labels.py: each exchange's own proof-of-reserves wallet list (a "
                        "first-party source, accepted by the owner 15 Nov 2026); a conflict with any other file, "
                        "a demo or the label store is left out, never overwritten; a token contract or an address "
                        "with no activity on this chain is left out",
                "sources": source}
        print(apply(new_rows, note))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
