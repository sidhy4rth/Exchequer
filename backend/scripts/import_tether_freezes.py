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

What is left out
----------------
Tether has blacklisted contracts too: its own USDT contract, the MetaMask swap
router, dozens of token contracts. Those are on every user's path, not anyone's
wallet, so a trace through one must not read "Frozen by Tether". After the
sample check (which covers them, so the replay still matches the contract),
every address app/never_flag.py names as a token contract, a DEX router or a
burn address, or lists in data/never_frozen.json as a shared contract (a DEX
pool, a mixer contract, a token sale), is moved to `_meta.excluded`. A frozen
exchange wallet that is not a per-customer deposit address stops the import for
review instead. `--screen-held` applies the same rules to the files already held.

    cd backend && .venv/bin/python -m scripts.import_tether_freezes
    cd backend && .venv/bin/python -m scripts.import_tether_freezes --dry-run
    cd backend && .venv/bin/python -m scripts.import_tether_freezes --screen-held   # offline
    cd backend && .venv/bin/python -m scripts.import_tether_freezes --recheck-lifts  # keyless

Lifts
-----
A freeze can be lifted. The full import replays the releases, but it needs an
Etherscan key. `--recheck-lifts` needs none: it asks the USDT contract's own
isBlackListed(address) for every held freeze on a public endpoint
(ethereum-rpc.publicnode.com, Tron's tron-evm-rpc.publicnode.com), asks a
second one (Tenderly's public gateway, TronGrid) about every answer that is not
"frozen", and moves an address to `_meta.excluded` only when both say it is no
longer frozen, with the RemovedBlackList tx when one is found since the list's
last_reviewed date. The nightly refresh runs it when the key is missing.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app import never_flag  # noqa: E402
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
EXCLUDED_NOTE = ("Frozen by Tether but left out: token contracts, DEX routers, burn addresses and the shared "
                 "contracts in data/never_frozen.json (DEX pools, mixer contracts, token sales) are on many "
                 "users' paths, not one party's wallet (app/never_flag.py).")
LIFT_NOTE = ("An entry whose why starts 'lifted' was frozen when the list was built and Tether has since "
             "released it: isBlackListed(address) answered false on two public endpoints "
             "(scripts/import_tether_freezes.py --recheck-lifts). It is no longer a freeze.")


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
        last_block = int(logs[-1]["blockNumber"], 16)
        if last_block <= from_block:
            # A full page inside one block would be asked for again for ever.
            raise RuntimeError(f"more than 1000 {topic[:10]} events in block {from_block}; cannot page past it")
        from_block = last_block
    return list(out.values())


def eth_is_blacklisted(client: EtherscanClient, address: str) -> bool:
    data = IS_BLACKLISTED + address[2:].rjust(64, "0")
    result = client._request({"module": "proxy", "action": "eth_call", "to": ETH_USDT,
                              "data": data, "tag": "latest"})
    return int(result or "0x0", 16) == 1


# -- Tron -----------------------------------------------------------------------
class TronReadError(RuntimeError):
    """TronGrid answered with something other than a page of events."""


def tron_events(http: httpx.Client, name: str) -> list[tuple[int, int, str, str, int]]:
    """(block, index, address, tx, timestamp ms) for every event with this name.

    A rate limit or an error page has no fingerprint, so read loosely it looks just
    like the last page and leaves the freeze list short. Anything that is not a page
    of events stops the import instead.
    """
    url = f"{TRONGRID}/v1/contracts/{TRON_USDT}/events"
    params = {"event_name": name, "limit": 200, "order_by": "block_timestamp,asc"}
    out = []
    while True:
        response = http.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        if body.get("success") is False or not isinstance(body.get("data"), list):
            raise TronReadError(f"TronGrid did not return events for {name}: {str(body)[:120]}")
        for event in body["data"]:
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


# -- lifts: is each held freeze still in force? ----------------------------------
# Keyless public endpoints. A lift is acted on only when a second endpoint agrees.
ETH_RPC = "https://ethereum-rpc.publicnode.com"
ETH_RPC_2 = "https://gateway.tenderly.co/public/mainnet"
TRON_RPC = "https://tron-evm-rpc.publicnode.com"  # Tron's eth_call, hex addresses without the 41
BATCH = 50
PAUSE = 0.6
RETRIES = 4
BACKOFF = 4  # seconds, times the attempt number
LOG_STEP = 100_000  # blocks per eth_getLogs
UNREADABLE_MAX = 0.01  # more unreadable answers than this and nothing is written
_WORD = re.compile(r"0x[0-9a-fA-F]{64}")


def _call_once(http: httpx.Client, url: str, body: list[dict]) -> dict:
    try:
        response = http.post(url, json=body)
        response.raise_for_status()
        answers = response.json()
    except (httpx.HTTPError, ValueError):
        return {}
    if not isinstance(answers, list):
        return {}
    return {a.get("id"): a.get("result") for a in answers if isinstance(a, dict)}


def _calls(http: httpx.Client, url: str, contract_hex: str, addresses_hex: list[str]) -> list[bool | None]:
    """isBlackListed(address) for each, in batched JSON-RPC requests. None: no readable answer.

    A public endpoint rate-limits a whole batch now and then; the unanswered calls are
    asked again after a pause, up to RETRIES times.
    """
    calls = {i: {"jsonrpc": "2.0", "id": i, "method": "eth_call",
                 "params": [{"to": contract_hex, "data": IS_BLACKLISTED + a.removeprefix("0x").rjust(64, "0")},
                            "latest"]}
             for i, a in enumerate(addresses_hex)}
    answers: dict[int, bool] = {}
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(BACKOFF * attempt)
        got = _call_once(http, url, [c for i, c in calls.items() if i not in answers])
        answers.update({i: int(v, 16) != 0 for i, v in got.items()
                        if i in calls and isinstance(v, str) and _WORD.fullmatch(v)})
        if len(answers) == len(calls):
            break
    return [answers.get(i) for i in range(len(addresses_hex))]


def _tron_answer(http: httpx.Client, address: str) -> bool | None:
    """TronGrid's isBlackListed(address); None unless the call plainly succeeded."""
    try:
        body = http.post(f"{TRONGRID}/wallet/triggerconstantcontract", json={
            "owner_address": TRON_USDT, "contract_address": TRON_USDT, "visible": True,
            "function_selector": "isBlackListed(address)", "parameter": _tron_hex(address).rjust(64, "0"),
        }).json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(body, dict) or not (body.get("result") or {}).get("result"):
        return None
    result = (body.get("constant_result") or [None])[0]
    if not isinstance(result, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", result):
        return None
    return int(result, 16) != 0


def still_frozen(http: httpx.Client, chain_key: str, addresses: list[str]) -> dict[str, bool | None]:
    """address -> True (still frozen), False (lifted, seen on two endpoints) or None (could not tell)."""
    if chain_key == "ethereum":
        url, contract, as_hex = ETH_RPC, ETH_USDT, (lambda a: a)
    else:
        url, contract, as_hex = TRON_RPC, "0x" + _tron_hex(TRON_USDT), _tron_hex
    state: dict[str, bool | None] = {}
    for start in range(0, len(addresses), BATCH):
        chunk = addresses[start:start + BATCH]
        state.update(zip(chunk, _calls(http, url, contract, [as_hex(a) for a in chunk]), strict=True))
        time.sleep(PAUSE)
    doubtful = [a for a, v in state.items() if v is not True]
    if chain_key == "ethereum":
        again = {}
        for start in range(0, len(doubtful), BATCH):
            chunk = doubtful[start:start + BATCH]
            again.update(zip(chunk, _calls(http, ETH_RPC_2, ETH_USDT, chunk), strict=True))
            time.sleep(PAUSE)
    else:
        again = {}
        for address in doubtful:
            again[address] = _tron_answer(http, address)
            time.sleep(PAUSE)
    for address in doubtful:
        first, second = state[address], again.get(address)
        # One endpoint unreadable: the other's answer. A lift on one endpoint only: unknown.
        state[address] = second if first is None else (False if second is False else None)
    return state


def _rpc(http: httpx.Client, url: str, method: str, params: list):
    body = http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).json()
    if "error" in body:
        raise RuntimeError(f"{method}: {str(body['error'])[:120]}")
    return body["result"]


def eth_releases(http: httpx.Client, since: datetime) -> dict[str, tuple[str, int]]:
    """address -> (tx, unix time) of its latest RemovedBlackList since `since`, from a public endpoint."""
    head = _rpc(http, ETH_RPC_2, "eth_getBlockByNumber", ["latest", False])
    latest, now = int(head["number"], 16), int(head["timestamp"], 16)
    # A block is at most one per 12 s, so this starts no later than `since`; a day of margin on top.
    block = max(0, latest - (now - int(since.timestamp())) // 12 - 7200)
    found: dict[str, tuple[int, int, str]] = {}
    while block <= latest:
        logs = _rpc(http, ETH_RPC_2, "eth_getLogs", [{"address": ETH_USDT, "topics": [REMOVED],
                                                      "fromBlock": hex(block), "toBlock": hex(min(latest, block + LOG_STEP - 1))}])
        for log in logs:
            key = (int(log["blockNumber"], 16), int(log["logIndex"], 16), log["transactionHash"])
            address = normalize_address("0x" + log["data"][-40:])
            found[address] = max(found.get(address, key), key)
        block += LOG_STEP
        time.sleep(PAUSE)
    out = {}
    for address, (number, _index, tx) in found.items():
        stamp = _rpc(http, ETH_RPC_2, "eth_getBlockByNumber", [hex(number), False])["timestamp"]
        out[address] = (tx, int(stamp, 16))
    return out


def tron_releases(http: httpx.Client, since: datetime) -> dict[str, tuple[str, int]]:
    """address -> (tx, unix time) of its latest RemovedBlackList since `since`, from TronGrid."""
    url = f"{TRONGRID}/v1/contracts/{TRON_USDT}/events"
    params = {"event_name": "RemovedBlackList", "limit": 200, "order_by": "block_timestamp,asc",
              "min_block_timestamp": int(since.timestamp()) * 1000}
    out: dict[str, tuple[str, int]] = {}
    while True:
        body = http.get(url, params=params).json()
        if body.get("success") is False or not isinstance(body.get("data"), list):
            raise TronReadError(f"TronGrid did not return RemovedBlackList events: {str(body)[:120]}")
        for event in body["data"]:  # ascending, so the last one per address wins
            raw = (event.get("result") or {}).get("_user") or (event.get("result") or {}).get("0") or ""
            address = hex_to_base58("41" + raw[2:] if raw.startswith("0x") else raw)
            out[address] = (event["transaction_id"], event["block_timestamp"] // 1000)
        fingerprint = (body.get("meta") or {}).get("fingerprint")
        if not fingerprint:
            return out
        params["fingerprint"] = fingerprint
        time.sleep(PAUSE)


def lifted_why(release: tuple[str, int] | None, today: str) -> str:
    if release is None:
        return (f"lifted: isBlackListed(address) answered false on two endpoints on {today}; "
                "the RemovedBlackList tx was not found")
    tx, stamp = release
    return f"lifted on {datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()}, tx {tx}"


def recheck_lifts(dry_run: bool, chains: tuple[str, ...] = ("ethereum", "tron"),
                  http: httpx.Client | None = None) -> int:
    """Ask the USDT contract whether each held freeze is still in force; move lifted ones to _meta.excluded.

    Keyless (public RPCs and TronGrid) and needs no event replay, so it can run where the full
    import cannot. It never adds a freeze, and it leaves last_reviewed alone: it re-checks
    the held list, it does not re-read Tether's events. A file with nothing lifted is not rewritten.
    """
    headers = {"Accept": "application/json"}
    if config.TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY
    own = http is None
    http = http or httpx.Client(timeout=60, headers=headers)
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        for chain_key in chains:
            path = config.CHAINS[chain_key].frozen_labels_path
            document = json.loads(path.read_text())
            labels, meta = document["labels"], document["_meta"]
            state = still_frozen(http, chain_key, sorted(labels))
            lifted = sorted(a for a, v in state.items() if v is False)
            unknown = sorted(a for a, v in state.items() if v is None)
            print(f"{chain_key}: {len(labels)} checked, {len(lifted)} lifted, {len(unknown)} could not be read")
            if len(unknown) > max(5, len(labels) * UNREADABLE_MAX):
                print(f"  too many unreadable answers ({unknown[:3]}...); not writing")
                return 1
            if not lifted:
                continue
            since = datetime.fromisoformat(meta.get("last_reviewed") or "2017-11-28").replace(tzinfo=timezone.utc)
            releases = (eth_releases if chain_key == "ethereum" else tron_releases)(http, since)
            excluded = dict(meta.get("excluded") or {})
            for address in lifted:
                excluded[address] = {"why": lifted_why(releases.get(address), today), "label": labels[address]["label"]}
                print(f"  {address}: {excluded[address]['why']}")
            document["labels"] = {a: m for a, m in sorted(labels.items()) if a not in set(lifted)}
            meta["excluded"] = dict(sorted(excluded.items()))
            meta["counts"] = {**(meta.get("counts") or {}), "frozen": len(document["labels"]), "excluded": len(excluded)}
            meta["lifts_rechecked"] = today
            meta["lift_note"] = LIFT_NOTE
            if not dry_run:
                path.write_text(json.dumps(document, indent=1) + "\n")
    finally:
        if own:
            http.close()
    return 0


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


def leave_out(chain_key: str, labels: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """(labels kept, excluded {address: why and label}, exchange wallets that need review)."""
    usdt = ETH_USDT if chain_key == "ethereum" else TRON_USDT
    reasons = {a: why for a in labels if (why := never_flag.freeze_refusal(chain_key, a))}
    if usdt in labels:
        reasons[usdt] = never_flag.TOKEN  # Tether blacklisted its own contract; not a wallet
    review = sorted(a for a, why in reasons.items() if why == never_flag.EXCHANGE)
    excluded = {a: {"why": why, "label": labels[a]["label"]} for a, why in sorted(reasons.items())
                if why != never_flag.EXCHANGE}
    kept = {a: m for a, m in labels.items() if a not in excluded}
    return kept, excluded, review


def write(chain_key: str, frozen: dict[str, dict], counts: dict, dry_run: bool,
          excluded: dict[str, dict] | None = None) -> None:
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
            "counts": {**counts, "excluded": len(excluded or {})},
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.import_tether_freezes",
            "schema": "labels maps an address to {category, entity, label, source}",
            "excluded_note": EXCLUDED_NOTE,
            "excluded": excluded or {},
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


def _screened(chain_key: str, labels: dict[str, dict], counts: dict, dry_run: bool) -> int:
    """Apply the never-flag rules, then write; 1 (nothing written) if an exchange wallet needs review."""
    kept, excluded, review = leave_out(chain_key, labels)
    if review:
        print(f"  {chain_key}: Tether froze exchange wallets that are not deposit addresses: {review}. "
              "Review them (add an 'allow' entry to data/never_flag_tokens.json if right); not writing.")
        return 1
    print(f"  {chain_key}: {len(excluded)} left out (token contracts, routers, burn addresses, shared contracts)")
    write(chain_key, kept, {**counts, "frozen": len(kept)}, dry_run, excluded)
    return 0


def screen_held(dry_run: bool) -> int:
    """Apply the never-flag rules to the files already held. Reads and writes local files only."""
    status = 0
    for chain_key in ("ethereum", "tron"):
        path = config.CHAINS[chain_key].frozen_labels_path
        document = json.loads(path.read_text())
        kept, excluded, review = leave_out(chain_key, document["labels"])
        if review:
            print(f"{chain_key}: exchange wallets need review, not changed: {review}")
            status = 1
            continue
        meta = document["_meta"]
        meta["excluded"] = {**(meta.get("excluded") or {}), **excluded}
        meta["excluded_note"] = EXCLUDED_NOTE
        meta["counts"] = {**(meta.get("counts") or {}), "frozen": len(kept), "excluded": len(meta["excluded"])}
        document["labels"] = dict(sorted(kept.items()))
        print(f"{chain_key}: {len(excluded)} moved to _meta.excluded; {len(kept)} kept")
        if not dry_run:
            path.write_text(json.dumps(document, indent=1) + "\n")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chain", choices=["ethereum", "tron", "all"], default="all")
    parser.add_argument("--screen-held", action="store_true",
                        help="apply the never-flag rules to the held files, offline")
    parser.add_argument("--recheck-lifts", action="store_true",
                        help="ask the USDT contract (keyless public RPCs) whether each held freeze is still "
                             "in force, and move the lifted ones to _meta.excluded")
    args = parser.parse_args()
    if args.recheck_lifts:
        chains = ("ethereum", "tron") if args.chain == "all" else (args.chain,)
        return recheck_lifts(args.dry_run, chains)
    if args.screen_held:
        return screen_held(args.dry_run)
    rng = random.Random(7)
    status = 0

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
        status |= _screened("ethereum", labels, {"freeze_events": len(added), "release_events": len(removed)},
                            args.dry_run)

    if args.chain in ("tron", "all"):
        headers = {"Accept": "application/json"}
        if config.TRONGRID_API_KEY:
            headers["TRON-PRO-API-KEY"] = config.TRONGRID_API_KEY
        with httpx.Client(timeout=60, headers=headers) as http:
            added = tron_events(http, "AddedBlackList")
            removed = tron_events(http, "RemovedBlackList")
            frozen = replay(added, removed)
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
        status |= _screened("tron", labels, {"freeze_events": len(added), "release_events": len(removed)},
                            args.dry_run)

    if args.dry_run:
        print("\nDry run -- nothing written.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
