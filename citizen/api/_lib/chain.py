"""One transaction, read from a keyless public endpoint: who paid whom, how
much of which token, and when. Only the citizen's own payment: never a
transfer after it, a label, or anything else a provider says about it.

Tron is read from TronScan's public API, the EVM networks from their public
RPC nodes. No API key is used or accepted. A lookup has DEADLINE seconds in
all, inside the function's time limit (vercel.json): each read gets only
the time left, and a node that stalls past it ends in "could not check".
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

TIMEOUT, MAX_BYTES, DEADLINE = 6, 512 * 1024, 8.0
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Transfer(address,address,uint256)
TRONSCAN = "https://apilist.tronscanapi.com/api/transaction-info"
TRON_TOKENS = {"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": ("USDT", 6)}
EVM = {
    "ethereum": ("Ethereum", "ETH", ("https://cloudflare-eth.com", "https://eth.drpc.org"), {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6)}),
    "bsc": ("BNB Smart Chain", "BNB", ("https://bsc-dataseed.bnbchain.org", "https://bsc.drpc.org"), {
        "0x55d398326f99059ff775485246999027b3197955": ("USDT", 18),
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18)}),
    "polygon": ("Polygon", "POL", ("https://polygon-rpc.com", "https://polygon.drpc.org"), {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": ("USDT", 6),
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("USDC", 6)}),
    "arbitrum": ("Arbitrum", "ETH", ("https://arb1.arbitrum.io/rpc", "https://arbitrum.drpc.org"), {
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": ("USDT", 6),
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831": ("USDC", 6)}),
}
NETWORKS = ("tron", *EVM)


class CouldNotCheck(Exception):
    """The provider did not answer, or not in the shape expected."""


class NotFound(Exception):
    pass


class Unreadable(Exception):
    """The transaction exists but is not a payment read here."""


def endpoints() -> list[str]:
    return [TRONSCAN, *(node for _n, _s, nodes, _t in EVM.values() for node in nodes)]


def _left(deadline: float) -> float:
    """The timeout for the next read: the time left, at most TIMEOUT."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise CouldNotCheck("out of time")
    return min(TIMEOUT, left)


def fetch(url: str, body: dict | None = None, timeout: float = TIMEOUT) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "exchequer-citizen"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            raw = answer.read(MAX_BYTES + 1)
    except Exception as exc:  # timeouts, refusals, HTTP errors: all "could not check"
        raise CouldNotCheck(type(exc).__name__) from None
    if len(raw) > MAX_BYTES:
        raise CouldNotCheck("answer too large")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise CouldNotCheck("not JSON") from None
    if not isinstance(parsed, dict):
        raise CouldNotCheck("not an object")
    return parsed


def _amount(raw: int | str, decimals: int) -> str:
    value = Decimal(int(raw)) / (Decimal(10) ** decimals)
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _time(seconds: int) -> str:
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tron(digest: str, deadline: float) -> dict:
    answer = fetch(f"{TRONSCAN}?hash={digest}", None, _left(deadline))
    if (answer.get("Error") or answer.get("error")) and not answer.get("hash"):
        raise CouldNotCheck("refused")
    if not answer:
        raise NotFound
    if answer.get("hash") != digest:
        raise CouldNotCheck("another transaction")
    when, ok = _time(int(answer["timestamp"]) // 1000), answer.get("contractRet") == "SUCCESS"
    for item in answer.get("trc20TransferInfo") or []:
        token = TRON_TOKENS.get(item["contract_address"])
        if token:  # the first transfer of a known token is the payment
            return {"from": item["from_address"], "to": item["to_address"], "token": token[0],
                    "amount": _amount(item["amount_str"], token[1]), "time": when, "succeeded": ok}
    if answer.get("contractType") == 1:
        data = answer["contractData"]
        return {"from": data["owner_address"], "to": data["to_address"], "token": "TRX",
                "amount": _amount(data["amount"], 6), "time": when, "succeeded": ok}
    raise Unreadable


def _rpc(nodes: tuple[str, ...], method: str, params: list, deadline: float):
    failed = False
    for node in nodes:
        try:
            answer = fetch(node, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, _left(deadline))
        except CouldNotCheck:
            failed = True
            continue
        if "error" in answer or "result" not in answer:
            failed = True
            continue
        if answer["result"] is not None:
            return answer["result"]
    if failed:
        raise CouldNotCheck(method)
    return None


def _evm(network: str, digest: str, deadline: float) -> dict:
    _name, native, nodes, tokens = EVM[network]
    digest = digest if digest.startswith("0x") else "0x" + digest
    tx = _rpc(nodes, "eth_getTransactionByHash", [digest], deadline)
    if tx is None:
        raise NotFound
    if tx.get("blockNumber") is None:
        raise Unreadable  # not in a block yet
    receipt = _rpc(nodes, "eth_getTransactionReceipt", [digest], deadline) or {}
    block = _rpc(nodes, "eth_getBlockByNumber", [tx["blockNumber"], False], deadline) or {}
    when, ok = _time(int(block["timestamp"], 16)), receipt.get("status") == "0x1"
    for log in receipt.get("logs") or []:
        token, topics = tokens.get(str(log["address"]).lower()), log["topics"]
        if token and len(topics) == 3 and topics[0] == TRANSFER:
            return {"from": "0x" + topics[1][-40:], "to": "0x" + topics[2][-40:], "token": token[0],
                    "amount": _amount(int(log["data"], 16), token[1]), "time": when, "succeeded": ok}
    if int(tx.get("value") or "0x0", 16) > 0:
        return {"from": tx["from"], "to": tx["to"], "token": native, "amount": _amount(int(tx["value"], 16), 18),
                "time": when, "succeeded": ok}
    raise Unreadable


def _read(network: str, digest: str, deadline: float) -> dict:
    try:
        found = _tron(digest, deadline) if network == "tron" else _evm(network, digest, deadline)
    except (NotFound, Unreadable, CouldNotCheck):
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, ArithmeticError):
        raise CouldNotCheck("unexpected shape") from None
    name = "Tron" if network == "tron" else EVM[network][0]
    return {"network": name, "hash": digest, **found}


def lookup(network: str, digest: str) -> dict:
    """{network, hash, from, to, amount, token, time, succeeded}; or NotFound,
    Unreadable, CouldNotCheck. Never longer than DEADLINE: a read that will
    not end (a server sending a byte at a time) is left behind."""
    box: dict = {}

    def run() -> None:
        try:
            box["found"] = _read(network, digest, time.monotonic() + DEADLINE)
        except Exception as exc:  # handed back to the caller below
            box["error"] = exc

    worker = threading.Thread(target=run, name="payment-lookup", daemon=True)
    worker.start()
    worker.join(DEADLINE)
    if worker.is_alive():
        raise CouldNotCheck("out of time")
    if "error" in box:
        raise box["error"]
    return box["found"]
