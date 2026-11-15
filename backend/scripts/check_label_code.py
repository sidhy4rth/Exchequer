"""Type the Ethereum exchange labels by the code their addresses hold.

A label typed hot_wallet, cold_wallet or exchange_wallet says "an account the
exchange holds the key to". On 15 Nov 2026 a label audit found Ethereum ones
whose addresses hold bytecode. Two kinds are fine as they are or nearly so:

  * EIP-7702 delegated accounts (code 0xef0100 followed by a 20-byte delegate).
    The account still has its own private key, held by the exchange; the code
    only says which contract it runs as. The type is kept and the delegation
    is listed in the file's _meta (the label schema has no note field).
  * Proxy and forwarder contracts: a minimal proxy (EIP-1167), a Gnosis Safe
    proxy, an EIP-1967 proxy or an older delegatecall proxy, or a forwarder
    whose only code passes every payment on. There is no key behind them, so
    they are retyped contract_wallet, the type the label audit
    (scripts/audit_label_contracts.py) and the proof-of-reserves import (#226)
    give exchange-operated contracts. The row keeps the type it had as its
    `role` (hot_wallet, cold_wallet or exchange_wallet), so nothing a trace
    concludes changes: contract_wallet is still the exchange's own wallet
    everywhere a match is read (the letter kind, never_flag, the case
    contract), scoring gives it the directness of its role, and deposit
    inference treats a sweep into it as before (exchange_matcher.role_of).

Any other contract is left as it is and listed for review in _meta: what it is
(a multisig, an invoice contract, a payout contract) needs a person to read it.

The code is read keylessly from a public node and the answers are kept in
tests/fixtures/label_code/ethereum.json, so the guard test
(tests/test_label_code.py) checks the recorded labels offline. A label added
later has no recorded answer: the guard leaves it to this script, which a
label import runs (docs/label-releases.md) and which fails until it is read:

    cd backend && .venv/bin/python -m scripts.check_label_code --check    # offline: any label not yet read?
    cd backend && .venv/bin/python -m scripts.check_label_code --record   # asks the node
    cd backend && .venv/bin/python -m scripts.check_label_code --dry-run  # from the recording
    cd backend && .venv/bin/python -m scripts.check_label_code
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.keccak import keccak256  # noqa: E402

RPC = "https://ethereum-rpc.publicnode.com"  # keyless; answers JSON-RPC batches
ANSWERS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "label_code" / "ethereum.json"
META_KEY = "code_check_2026_11_15"
WALLET_TYPES = ("hot_wallet", "cold_wallet", "exchange_wallet")  # "an account the exchange holds the key to"
CONTRACT_WALLET = "contract_wallet"
KEPT_IN_FULL = 1024  # bytes: code this short is recorded verbatim; longer code by size and hash

EOA, DELEGATED, PROXY, FORWARDER, OTHER = "eoa", "eip7702", "proxy", "forwarder", "other"
EIP7702_PREFIX = "ef0100"
EIP1167 = ("363d3d373d3d3d363d73", "5af43d82803e903d91602b57fd5bf3")
SAFE_PROXY = "608060405273ffffffffffffffffffffffffffffffffffffffff600054167fa619486e"  # masterCopy() in slot 0
EIP1967_SLOT = "360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
PUSH1, PUSH4, PUSH32, CALL, DELEGATECALL = 0x60, 0x63, 0x7f, 0xf1, 0xf4


# -- reading code ------------------------------------------------------------------

def _without_metadata(code: bytes) -> bytes:
    """The code without solc's CBOR metadata trailer (its last two bytes give
    its length), so a hash inside it is not read as instructions."""
    if len(code) > 2:
        n = int.from_bytes(code[-2:], "big")
        if 0 < n < len(code) - 2 and code[-2 - n] in (0xa1, 0xa2, 0xa3):
            return code[:-2 - n]
    return code


def _opcodes(code: bytes) -> list[int]:
    out, i = [], 0
    while i < len(code):
        op = code[i]
        out.append(op)
        i += 1 + (op - PUSH1 + 1 if PUSH1 <= op <= PUSH32 else 0)
    return out


def classify(answer: str | dict[str, Any]) -> tuple[str, str]:
    """(kind, why) for one recorded eth_getCode answer."""
    if isinstance(answer, dict):  # longer than KEPT_IN_FULL: no proxy or forwarder is that large
        return OTHER, f"contract code, {answer['size']} bytes, not a proxy or forwarder"
    code = answer.lower().removeprefix("0x")
    if not code:
        return EOA, "no code"
    if code.startswith(EIP7702_PREFIX) and len(code) == 46:
        return DELEGATED, f"EIP-7702 delegated account, delegate 0x{code[6:]}"
    size = len(code) // 2
    if code.startswith(EIP1167[0]) and code.endswith(EIP1167[1]) and size == 45:
        return PROXY, f"EIP-1167 minimal proxy to 0x{code[20:60]}"
    ops = _opcodes(_without_metadata(bytes.fromhex(code)))
    if DELEGATECALL in ops:
        if code.startswith(SAFE_PROXY):
            return PROXY, f"Gnosis Safe proxy, {size} bytes"
        if EIP1967_SLOT in code:
            return PROXY, f"EIP-1967 proxy, {size} bytes"
        return PROXY, f"delegatecall proxy, {size} bytes"
    if CALL in ops and PUSH4 not in ops:
        return FORWARDER, f"forwarder: no functions, its fallback passes payments on, {size} bytes"
    return OTHER, f"contract code, {size} bytes, not a proxy or forwarder"


def recorded(code: str) -> str | dict[str, Any]:
    """What the recording keeps of one answer."""
    raw = bytes.fromhex(code.lower().removeprefix("0x"))
    if len(raw) <= KEPT_IN_FULL:
        return "0x" + raw.hex()
    return {"size": len(raw), "keccak256": "0x" + keccak256(raw).hex(), "head": "0x" + raw[:32].hex()}


# -- the decision ------------------------------------------------------------------

def plan(labels: dict[str, dict[str, Any]], answers: dict[str, Any]) -> dict[str, dict[str, str]]:
    """What happens to each Ethereum exchange label typed as a keyed wallet.

    retyped: proxy or forwarder -> contract_wallet; delegated: EIP-7702, kept;
    review: another contract, kept and listed; unread: no recorded answer.
    """
    out: dict[str, dict[str, str]] = {"retyped": {}, "delegated": {}, "review": {}, "unread": {}}
    for address, meta in sorted(labels.items()):
        if meta.get("type") not in WALLET_TYPES:
            continue
        if address not in answers:
            out["unread"][address] = meta.get("label", "")
            continue
        kind, why = classify(answers[address])
        if kind in (PROXY, FORWARDER):
            out["retyped"][address] = f"{meta['type']} -> {CONTRACT_WALLET}: {why} ({meta['label']})"
        elif kind == DELEGATED:
            out["delegated"][address] = f"{why}; type {meta['type']} kept ({meta['label']})"
        elif kind == OTHER:
            out["review"][address] = f"{why}; type {meta['type']} kept, for review ({meta['label']})"
    return out


UNREAD_HELP = ("{n} Ethereum label(s) typed hot_wallet, cold_wallet or exchange_wallet have no recorded "
               "eth_getCode answer. Run `cd backend && python -m scripts.check_label_code --record`, then "
               "`python -m scripts.check_label_code`, and commit backend/tests/fixtures/label_code/ethereum.json "
               "with the label file.")


def unread(labels: dict[str, dict[str, Any]], answers: dict[str, Any]) -> dict[str, str]:
    """Keyed-wallet labels with no recorded answer: address -> label."""
    return plan(labels, answers)["unread"]


def apply(document: dict[str, Any], decided: dict[str, dict[str, str]], recorded_at: str) -> None:
    for address in decided["retyped"]:
        row = document["labels"][address]
        row["role"] = row["type"]  # what the exchange uses it as (exchange_matcher.role_of)
        row["type"] = CONTRACT_WALLET
    document["_meta"][META_KEY] = {
        "date": "2026-11-15",
        "rule": "scripts/check_label_code.py: each label typed hot_wallet, cold_wallet or exchange_wallet "
                "was read with eth_getCode. A proxy or forwarder contract is typed contract_wallet; an "
                "EIP-7702 delegated account keeps its type (the exchange still holds its key); any other "
                "contract keeps its type and is listed for review.",
        "answers": f"backend/tests/fixtures/label_code/ethereum.json (read {recorded_at})",
        "retyped": decided["retyped"],
        "eip7702_delegated": decided["delegated"],
        "left_for_review": decided["review"],
    }


# -- asking the node (--record only) -----------------------------------------------

def _rpc(calls: list[tuple[str, list]]) -> list[Any]:
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)])
    request = urllib.request.Request(RPC, data=body.encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "exchequer-labels"})
    with urllib.request.urlopen(request, timeout=30) as response:
        answers = json.loads(response.read())
    by_id = {a.get("id"): a for a in answers} if isinstance(answers, list) else {}
    return [by_id.get(i, {}).get("result") for i in range(len(calls))]


def record(addresses: list[str], batch: int = 20, pause: float = 1.0) -> tuple[dict[str, Any], int]:
    """Every address's code at one block (a batch that fails is retried, then
    left out; the plan reports it unread)."""
    block = int(_rpc([("eth_blockNumber", [])])[0], 16)
    out: dict[str, Any] = {}
    for start in range(0, len(addresses), batch):
        part = addresses[start:start + batch]
        for attempt in range(5):
            try:
                codes = _rpc([("eth_getCode", [a, hex(block)]) for a in part])
                if all(isinstance(c, str) for c in codes):
                    out.update({a: recorded(c) for a, c in zip(part, codes, strict=True)})
                    break
            except Exception as exc:  # noqa: BLE001 -- a public node's hiccup; retried, then reported
                print(f"  {part[0]}..: {str(exc)[:60]}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
        print(f"  {min(start + batch, len(addresses))}/{len(addresses)}", file=sys.stderr, flush=True)
        time.sleep(pause)
    return out, block


def _indent(text: str) -> int:
    second = text.split("\n", 2)[1] if "\n" in text else ""
    return max(1, len(second) - len(second.lstrip(" ")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="read the code from the public node first")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="offline, writes nothing: fail if a keyed-wallet label has no recorded answer")
    args = parser.parse_args(argv)

    path = config.CHAINS["ethereum"].labels_path
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)
    labels = document["labels"]

    if args.record:
        asked = sorted(a for a, m in labels.items() if m.get("type") in (*WALLET_TYPES, CONTRACT_WALLET))
        answers, block = record(asked)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        ANSWERS.parent.mkdir(parents=True, exist_ok=True)
        ANSWERS.write_text(json.dumps({
            "_meta": {"what": "eth_getCode answers for the Ethereum exchange labels typed hot_wallet, cold_wallet, "
                              "exchange_wallet or contract_wallet; code over 1024 bytes kept as size, keccak256 "
                              "and first 32 bytes",
                      "rpc": RPC, "block": block, "recorded": stamp,
                      "regenerate_with": "cd backend && python -m scripts.check_label_code --record"},
            "code": answers,
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {len(answers)} of {len(asked)} at block {block}")

    recording = json.loads(ANSWERS.read_text(encoding="utf-8"))
    if args.check:
        missing = unread(labels, recording["code"])
        for address, label in missing.items():
            print(f"  not read  {address}  {label}")
        if missing:
            print(UNREAD_HELP.format(n=len(missing)), file=sys.stderr)
            return 1
        print(f"every Ethereum keyed-wallet label has a recorded answer ({len(recording['code'])} recorded)")
        return 0
    decided = plan(labels, recording["code"])
    for kind, rows in decided.items():
        print(f"{kind:10} {len(rows)}")
        for address, why in rows.items():
            print(f"  {address}  {why}")
    if decided["unread"]:
        print("some labels have no recorded answer: run with --record", file=sys.stderr)
        return 1
    if not args.dry_run:
        meta = recording["_meta"]
        apply(document, decided, f"{meta['recorded']}, block {meta['block']}")
        path.write_text(json.dumps(document, indent=_indent(text)) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
