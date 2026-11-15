"""Add Tron wallets that exchanges themselves publish as theirs (proof of reserves).

An exchange's proof-of-reserves (PoR) disclosure lists the addresses the
exchange says it controls. That is a first-party attribution -- the company
naming its own wallets -- and the strongest source this project has for a
cash-out point. Tron is where the coverage was thinnest (68 labels, OKX 1,
Bybit 2), so this script reads each exchange's own published list and adds
the Tron addresses to data/exchange_labels_tron.json.

Sources (SOURCES below) are files a person downloads by hand from the
exchange's own site or official GitHub repository, or an Internet Archive copy
of the exchange's page. The script never fetches them: it is given the local
copy, records the file's SHA-256, and parses only the Tron rows.

Every address must then pass the same gates as the TronScan importer:
- a valid Base58Check Tron address (the repo validator, checksum included);
- active on chain and not a contract: an account (TronGrid wallet/getaccount),
  or, for an address that never received TRX, a received USDT-TRC20 transfer
  (keyless, spaced out, backing off when the shared quota answers "rate").
  An address the check could not answer is not added; one added on an earlier
  run keeps its row;
- not already labelled as a different exchange (a conflict is reported,
  never overwritten); one already labelled as the same exchange keeps its
  TronScan row and is recorded as corroborated;
- not a token contract, router or burn address (never_flag), and not on the
  chain's frozen, sanctions, risk or gambling lists, nor in a recorded demo or
  a test that uses it as an unlabelled wallet: those are left out and listed,
  for a person to decide.

What this establishes: the exchange published the address as its own on the
recorded date. What it does NOT establish: who any customer is. Only the
exchange can say that, on lawful request.

    cd backend && .venv/bin/python -m scripts.import_por_tron_labels \\
        --file por:bybit:2026-10=~/por/bybit_por_202610.csv \\
        --file por:htx:2026-11=~/por/huobi_por.csv  [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import re
import sys
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, never_flag  # noqa: E402
from app.etherscan_client import is_tron_address  # noqa: E402
from scripts._label_files import merge_owned  # noqa: E402

TRON = config.CHAINS["tron"]
TRONGRID = "https://api.trongrid.io"
USDT = TRON.find_token("USDT").address
PREFIX = "por:"  # every row this script owns carries a source id starting with this
PAUSE = 1.0  # seconds between TronGrid requests: keyless (3 rps shared with every other job here)
MAX_FILE_ROWS = 5000  # a source larger than this does not go into the JSON label file
TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
DEMO_FILES = ("demo_traces.json", "recorded_demos.json", "demo_expectations.json")


@dataclass(frozen=True)
class Source:
    exchange: str          # tron_tags.CANONICAL spelling
    parser: str
    url: str
    published: str         # the date the exchange published or dated the list
    kind: str              # what the source calls the addresses, in its own words
    statement: str
    archive_url: str | None = None
    page: str | None = None
    # Rows marked SIGNED stand on the exchange's own evidence; a random sample
    # of them is still checked on chain, and one failure stops the source.
    self_evidenced: bool = False
    # For a source read as an API answer, not a file: the request that returned it.
    request: str | None = None


# Bitget publishes its reserve wallets per audit through its proof-of-reserves page's
# public API (no key, no login). The answer is JSON, read byte-for-byte as served; the
# answers read are kept in tests/fixtures/bitget_por/ (an API answer to a POST has no
# Internet Archive copy).
BITGET_URL = "https://www.bitget.com/v1/bill/proof/assets/public/queryReserveWalletDetail"
BITGET_PAGE = "https://www.bitget.com/promotion/proof-of-reserves"
BITGET_KIND = "proof-of-reserves reserve wallet (Bitget does not mark hot or cold per address)"
BITGET_STATEMENT = ("Bitget's proof-of-reserves page lists, per audit, the wallets it calls its reserve wallets; "
                    "this is the page's own public API answer for audit {audit} (snapshot {snapshot} UTC), "
                    "retrieved {retrieved} UTC. Rows read: chain 'Tron', address from the TronScan link "
                    "Bitget gives for each wallet.")

SOURCES: dict[str, Source] = {
    "por:bybit:2026-10": Source(
        exchange="Bybit", parser="bybit_csv", published="2026-10-27",
        url="https://api2.bybit.com/common-static/por/bybit_por_202610.csv",
        page="https://www.bybit.com/app/user/proof-of-reserve",
        kind="proof-of-reserves wallet address (Bybit does not mark hot or cold per address)",
        statement="Bybit's monthly proof-of-reserves file (Coin,Height,Amount,Address) lists, per coin and "
                  "chain, the wallet addresses Bybit announces as holding its reserves. Rows read: coins on "
                  "the TRX and Tron chains. Published date is the file's Last-Modified header."),
    "por:htx:2026-11": Source(
        exchange="Huobi / HTX", parser="htx_csv", published="2026-11-10",
        url="https://raw.githubusercontent.com/huobiapi/Tool-Node.js-VerifyAddress/"
            "0774c876e6df5400549005b3ec08de0fafdf97b9/snapshot/huobi_por.csv",
        page="https://github.com/huobiapi/Tool-Node.js-VerifyAddress",
        kind="proof-of-reserves address (HTX does not mark hot or cold per address)",
        statement="HTX's proof-of-reserves snapshot in its official address-verification repository "
                  "(commit 0774c876, 'upgrade merkle_proof_20261101'). The address section lists each "
                  "address with the message HTX signed with its key ('huobi', 'htx'); a row without a "
                  "signature is still listed by HTX as its address and is noted as unsigned."),
    "por:binance:2022-11": Source(
        exchange="Binance", parser="tronscan_links", published="2022-11-10",
        url="https://www.binance.com/en/blog/community/our-commitment-to-transparency-2895840147147652626",
        archive_url="https://web.archive.org/web/20221115192653/https://www.binance.com/en/blog/community/"
                    "our-commitment-to-transparency-2895840147147652626",
        kind="hot and cold wallet address (the post does not say which is which)",
        statement="Binance's blog post 'Our Commitment To Transparency' (10 Nov 2022) shares 'details of our "
                  "hot and cold wallet addresses', snapshot 10/11/2022 00:00 UTC, and says it is not a "
                  "complete set. Read from the Internet Archive copy: the live page answers automated "
                  "clients with a bot check, which was not bypassed."),
    "por:kucoin:2022-11": Source(
        exchange="KuCoin", parser="tronscan_links", published="2022-11-11",
        url="https://www.kucoin.com/blog/9152-34",
        kind="hot and cold wallet address (the post does not say which is which)",
        statement="KuCoin's blog post 'Transparency and Trust' (11 Nov 2022) shares 'an overview of our hot "
                  "and cold wallet addresses and their current holdings', snapshot 11/11/2022 07:00 UTC, "
                  "and says it does not represent all holdings."),
    "por:bitget:2026-11": Source(
        exchange="Bitget", parser="bitget_json", published="2026-11-12",
        url=BITGET_URL, page=BITGET_PAGE, request='POST {"auditId": "Au2026111300"}',
        kind=BITGET_KIND,
        statement=BITGET_STATEMENT.format(audit="Au2026111300", snapshot="2026-11-12 16:00", retrieved="2026-11-15 12:39:12")),
    "por:bitget:2026-10": Source(
        exchange="Bitget", parser="bitget_json", published="2026-10-21",
        url=BITGET_URL, page=BITGET_PAGE, request='POST {"auditId": "Au2026102112"}',
        kind=BITGET_KIND,
        statement=BITGET_STATEMENT.format(audit="Au2026102112", snapshot="2026-10-21 04:00", retrieved="2026-11-15 12:39:17")),
    "por:bitget:2026-05": Source(
        exchange="Bitget", parser="bitget_json", published="2026-05-20",
        url=BITGET_URL, page=BITGET_PAGE, request='POST {"auditId": "Au2026052008"}',
        kind=BITGET_KIND,
        statement=BITGET_STATEMENT.format(audit="Au2026052008", snapshot="2026-05-20 00:00", retrieved="2026-11-15 12:39:50")),
    "por:okx:2026-11": Source(
        exchange="OKX", parser="okx_zip", published="2026-11-01", self_evidenced=True,
        url="https://www.okx.com/cdn/okx/por/chain/por_csv_2026110100_V1.zip",
        page="https://www.okx.com/proof-of-reserves/download",
        kind="proof-of-reserves address (OKX does not mark hot or cold per address)",
        statement="OKX's monthly proof-of-reserves address file (snapshot 2026-11-01). Each row gives coin, "
                  "network, snapshot height, address, amount and a signature of the message 'I am an OKX "
                  "address' made with that address's key. Rows read: the Tron network."),
}


# -- parsers: (address, note) for every Tron row of a source file ----------
def parse_bybit_csv(data: bytes) -> Iterator[tuple[str, str]]:
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
        if len(row) < 4 or "-" not in row[0]:
            continue
        coin, _, chain = row[0].rpartition("-")
        if chain in ("TRX", "Tron"):
            for address in row[3].split():
                yield address, coin


def parse_htx_csv(data: bytes) -> Iterator[tuple[str, str]]:
    in_addresses = False
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
        if row[:2] == ["coin", "address"]:
            in_addresses = True
            continue
        if in_addresses and len(row) >= 6 and row[1].startswith("T"):
            yield row[1], row[0] + ("" if row[4] not in ("", "-") else " (unsigned)")


TRONSCAN_LINK = re.compile(r"tronscan\.org/#/address/(T[1-9A-HJ-NP-Za-km-z]{33})\b")


def parse_tronscan_links(data: bytes) -> Iterator[tuple[str, str]]:
    """Addresses a page links to on TronScan: how both blog posts list them."""
    for address in TRONSCAN_LINK.findall(data.decode("utf-8", "replace")):
        yield address, ""


OKX_TRON_NETWORKS = {"TRX", "TRON", "TRC20"}
# A row whose address signed the exchange's message and held a balance at the
# snapshot height: the signature needs that address's key (so it is not a
# contract) and the balance means the account existed on chain.
SIGNED = " [signed, balance>0]"


def parse_okx_csv(text: Iterator[str]) -> Iterator[tuple[str, str]]:
    header = None
    for row in csv.reader(text):
        if row[:4] == ["coin", "Type", "Network", "Snapshot Height"]:
            header = row
            continue
        if header and len(row) >= 8 and row[2].strip().upper() in OKX_TRON_NETWORKS:
            yield row[4].strip(), row[0] + (SIGNED if _positive(row[5]) and row[7].strip() else "")


def _positive(amount: str) -> bool:
    try:
        return float(amount) > 0
    except ValueError:
        return False


def parse_okx_zip(data: bytes) -> Iterator[tuple[str, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if name.lower().endswith(".csv"):
                with archive.open(name) as handle:
                    yield from parse_okx_csv(io.TextIOWrapper(handle, encoding="utf-8-sig"))


def parse_bitget_json(data: bytes) -> Iterator[tuple[str, str]]:
    """Tron wallets in Bitget's queryReserveWalletDetail answer: one entry per wallet and coin."""
    for entry in json.loads(data.decode("utf-8")).get("data") or []:
        if entry.get("chainName") == "Tron":
            for address in TRONSCAN_LINK.findall(entry.get("walletUrl", "")):
                yield address, entry.get("coinName", "")


PARSERS = {"bybit_csv": parse_bybit_csv, "htx_csv": parse_htx_csv, "bitget_json": parse_bitget_json,
           "tronscan_links": parse_tronscan_links, "okx_zip": parse_okx_zip}


# -- gates -------------------------------------------------------------------
def on_chain(client: httpx.Client, address: str) -> str | None:
    """'account' (activated, or received USDT), 'contract', 'none' (no activity) or None (no answer)."""
    for attempt in range(3):
        try:
            body = client.post(f"{TRONGRID}/wallet/getaccount", json={"address": address, "visible": True}).json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"  ! getaccount {address}: {str(exc)[:60]}")
            return None
        if not (isinstance(body, dict) and "rate" in str(body.get("Error", ""))):
            break
        time.sleep(6 * (attempt + 1))  # keyless quota is shared: back off, never push harder
    if not isinstance(body, dict) or "Error" in body:
        return None
    if body:
        return "contract" if body.get("type") == "Contract" else "account"
    # No account: never sent TRX. A deposit address that has only ever received
    # USDT-TRC20 is like that (a token transfer does not activate an account; a
    # contract always has one), so a received USDT transfer counts as activity.
    time.sleep(PAUSE)
    try:
        usdt = client.get(f"{TRONGRID}/v1/accounts/{address}/transactions/trc20",
                          params={"only_to": "true", "limit": 1, "contract_address": USDT}).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ! trc20 {address}: {str(exc)[:60]}")
        return None
    if not isinstance(usdt, dict) or usdt.get("success") is False:
        return None
    return "account" if usdt.get("data") else "none"


def spot_check(client: httpx.Client, notes: dict[str, set[str]], size: int, seed: str) -> dict:
    """Check a reproducible random sample of a source's signed rows on chain."""
    signed = sorted(a for a, n in notes.items() if any(SIGNED in x for x in n) and is_tron_address(a))
    sample = random.Random(seed).sample(signed, min(size, len(signed)))
    result: dict = {"signed_rows": len(signed), "checked": 0, "accounts": 0, "no_answer": 0, "failed": {}}
    for address in sample:
        state = on_chain(client, address)
        time.sleep(PAUSE)
        if state is None:
            result["no_answer"] += 1
            continue
        result["checked"] += 1
        if state == "account":
            result["accounts"] += 1
        else:
            result["failed"][address] = state
    return result


def listed_elsewhere() -> dict[str, str]:
    """Every address on a Tron list an exchange wallet must not silently join, -> which list."""
    found: dict[str, str] = {}
    for label, path in (("frozen", TRON.frozen_labels_path), ("sanctions", TRON.intl_sanctions_path),
                        ("risk", TRON.risk_labels_path), ("gambling", TRON.gambling_labels_path)):
        if path and path.exists():
            raw = json.loads(path.read_text())
            entries = raw.get("labels", raw) if isinstance(raw, dict) else {}
            for address in entries:
                if is_tron_address(address):
                    found.setdefault(address, f"on the Tron {label} list ({path.name})")
    for name in DEMO_FILES:
        path = config.DATA_DIR / name
        if path.exists():
            for address in set(re.findall(r"T[1-9A-HJ-NP-Za-km-z]{33}", path.read_text())):
                found.setdefault(address, f"in a recorded demo ({name}); re-record it before labelling")
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        for address in set(re.findall(r"T[1-9A-HJ-NP-Za-km-z]{33}", path.read_text())):
            found.setdefault(address, f"used in {path.name}, which may rely on it being unlabelled")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", action="append", default=[], metavar="ID=PATH",
                        help=f"a downloaded source file; ID is one of {', '.join(SOURCES)}")
    parser.add_argument("--retrieved", default=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
                        help="the date the files were downloaded (default today, UTC)")
    parser.add_argument("--sample", type=int, default=150,
                        help="signed rows of a self-evidenced source checked on chain (default 150)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-shrink", action="store_true")
    args = parser.parse_args()

    document = json.loads(TRON.labels_path.read_text())
    held: dict[str, dict] = document["labels"]
    meta = document["_meta"]
    por = meta.setdefault("proof_of_reserves", {"sources": {}})
    elsewhere = listed_elsewhere()

    fresh: dict[str, dict] = {}
    unknown: set[str] = set()
    with httpx.Client(timeout=40, headers={"Accept": "application/json", "User-Agent": "Exchequer/1.0"}) as grid:
        for item in args.file:
            source_id, _, path = item.partition("=")
            source = SOURCES.get(source_id)
            if source is None or not path:
                parser.error(f"--file {item!r}: unknown source id")
            data = Path(path).expanduser().read_bytes()
            notes: dict[str, set[str]] = {}
            for address, note in PARSERS[source.parser](data):
                notes.setdefault(address.strip(), set()).update({note} if note else set())
            record = {
                "exchange": source.exchange, "url": source.url, "archive_url": source.archive_url,
                "page": source.page, "published": source.published, "retrieved": args.retrieved,
                "sha256": hashlib.sha256(data).hexdigest(), "kind": source.kind,
                "statement": source.statement, "tron_addresses_listed": len(notes),
                "added": 0, "corroborated": {}, "left_out": {},
            }
            if source.request:
                record["request"] = source.request
            if source.self_evidenced:
                record["spot_check"] = spot_check(grid, notes, args.sample, record["sha256"])
                print(f"{source_id}: on-chain spot check {record['spot_check']}")
                if record["spot_check"]["failed"]:
                    print(f"{source_id}: on-chain spot check failed {record['spot_check']['failed']}; "
                          "source not used")
                    return 1
            # The label reads as its exchange to tron_tags.exchange_for_tag (name, then
            # only wallet qualifiers), like every other row in the file.
            label = f"{'HTX' if source.exchange == 'Huobi / HTX' else source.exchange}: Reserves Wallet ({source_id[-7:]})"
            print(f"{source_id}: {len(notes)} Tron addresses listed")
            if len(notes) > MAX_FILE_ROWS and not args.dry_run:
                # OKX's list (474,530 on 1 Nov 2026) made this file 91 MB and the loader hold 220 MB:
                # a list that size needs a compact store first (docs/handoff/tron-exchange-por.md).
                print(f"{source_id}: more than {MAX_FILE_ROWS} addresses is too many for the JSON label "
                      "file; nothing written")
                return 1
            for address in sorted(notes):
                existing = held.get(address)
                if not is_tron_address(address):
                    record["left_out"][address] = "not a valid Tron address (Base58Check)"
                elif existing and not str(existing.get("source", "")).startswith(PREFIX):
                    if existing["exchange"] == source.exchange:
                        record["corroborated"][address] = existing["label"]
                    else:
                        record["left_out"][address] = (f"CONFLICT: already labelled {existing['exchange']} "
                                                       f"('{existing['label']}'); not overwritten")
                elif address in fresh:
                    record["corroborated"][address] = fresh[address]["label"]
                elif (kind := never_flag.kind("tron", address)) and kind != never_flag.EXCHANGE:
                    record["left_out"][address] = f"a {kind}"
                elif address in elsewhere:
                    record["left_out"][address] = elsewhere[address]
                else:
                    if source.self_evidenced and any(SIGNED in n for n in notes[address]):
                        state = "account"  # the exchange's own evidence; the sample above was checked
                    else:
                        state = on_chain(grid, address)
                        time.sleep(PAUSE)
                    if state == "account":
                        fresh[address] = {"exchange": source.exchange, "label": label,
                                          "type": "exchange_wallet", "source": source_id}
                        record["added"] += 1
                    elif state is None:
                        unknown.add(address)
                        record["left_out"][address] = "on-chain check did not answer; not added this run"
                    else:
                        record["left_out"][address] = ("a contract account on chain" if state == "contract"
                                                       else "no account and no USDT received on chain")
            por["sources"][source_id] = record
            print(f"  added {record['added']}, corroborated {len(record['corroborated'])}, "
                  f"left out {len(record['left_out'])}")
            for address, why in record["left_out"].items():
                print(f"    - {address}  {why}")

    # Rows from a source not re-read this run are kept as they are.
    reread = {s.partition("=")[0] for s in args.file}
    keep = {a for a, e in held.items() if str(e.get("source", "")).startswith(PREFIX)
            and e["source"] not in reread}
    labels, counts = merge_owned(held, fresh, lambda a, e: str(e.get("source", "")).startswith(PREFIX),
                                 unknown=unknown | keep, allow_shrink=args.allow_shrink)
    print(dict(counts))

    por["description"] = (
        "Rows whose 'source' starts with 'por:' come from the exchange's own published proof-of-reserves or "
        "wallet-address disclosure (sources below: URL, archive copy, publication and retrieval dates, "
        "SHA-256 of the file read). The exchange itself states it controls these addresses. Each was "
        "checked to be a valid Tron address, active on chain and not a contract (an account per TronGrid "
        "wallet/getaccount, or a received USDT-TRC20 transfer; keyless) on the retrieval date. A PoR list says nothing about hot or cold "
        "unless the source does, so these are typed exchange_wallet. Addresses already labelled from "
        "TronScan keep that row and are listed as corroborated; conflicts and anything on a frozen, "
        "sanctions, risk, gambling or demo list were left out, never overwritten.")
    por["regenerate_with"] = ("cd backend && .venv/bin/python -m scripts.import_por_tron_labels "
                              "--file <source id>=<downloaded file> ...")
    by_exchange: dict[str, int] = {}
    for entry in labels.values():
        by_exchange[entry["exchange"]] = by_exchange.get(entry["exchange"], 0) + 1
    meta["counts"] = {"labels": len(labels), "exchanges": len(by_exchange),
                      "by_exchange": dict(sorted(by_exchange.items()))}
    document["labels"] = dict(sorted(labels.items(), key=lambda kv: (kv[1]["exchange"], kv[1]["label"], kv[0])))

    if args.dry_run:
        print("--dry-run: nothing written.")
        return 0
    TRON.labels_path.write_text(json.dumps(document, indent=2) + "\n")
    print(f"Wrote {len(labels)} labels to {TRON.labels_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
