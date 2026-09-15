"""BNB Smart Chain data provider, backed by NodeReal's MegaNode.

Why this exists rather than reusing EtherscanClient: Etherscan's V2 endpoint
advertises 60+ chains, but its free tier serves Ethereum mainnet only. Asking
it for chainid 56 returns "Free API access is not supported for this chain",
verified against the live API. NodeReal's free tier does serve BSC, and its
`nr_getAssetTransfers` method covers exactly what a trace needs: transfers
*out of* one address, optionally narrowed to specific token contracts.

Two properties of this API shape the code:

  * A query may span at most 100,000 blocks. BSC produces a block every ~3
    seconds, so one window is roughly 3.5 days. History is therefore walked
    backwards in windows from the chain head, and the walk stops as soon as
    enough transfers have been collected. This is why a BSC trace covers a
    bounded recent window rather than all history, and the limit is stated
    rather than hidden.
  * Results paginate with an opaque `pageKey` -- note the lower-case 'p', and
    `blockTimeStamp` with a capital 'S'. Both differ from the published
    documentation; the field names here were taken from live responses.

Amounts are returned as hex alongside the token's own `decimal`, so the
6-vs-18 decimal difference between Ethereum USDT and BSC USDT is handled by
the data rather than by an assumption in our code.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Iterable

import json

import httpx

from .evidence import EvidenceLog

from . import config
from .etherscan_client import (
    EtherscanError,
    Transaction,
    is_valid_address,
    normalize_address,
)

logger = logging.getLogger(__name__)

# nr_getAssetTransfers categories.
CATEGORY_NATIVE = "external"
CATEGORY_ERC20 = "20"

# Hard limits imposed by the API itself.
MAX_BLOCK_WINDOW = 100_000
MAX_COUNT = 1_000

# NodeReal's transfer index trails the chain head by a few blocks, and asking
# for a block it has not indexed yet fails the whole query with "blockNum not
# reached". Measured at ~5 blocks; 32 is a cheap margin (~1.5 minutes on BSC)
# that costs nothing, since a trace is not interested in the last few seconds
# of chain history anyway. The retry below covers the margin being wrong.
INDEX_LAG_BLOCKS = 32
NOT_INDEXED = "not reached"


class NoderealError(EtherscanError):
    """Any non-recoverable problem talking to NodeReal.

    Subclasses EtherscanError so main.py's existing handling of upstream
    failures applies unchanged to BSC traces.
    """


class NoderealClient:
    """Transaction source for BNB Smart Chain.

    Satisfies the same contract the graph builder relies on:
        client.get_outgoing_transactions(address) -> list[Transaction]
    """

    def __init__(
        self,
        api_key: str | None = None,
        chain_slug: str = "bsc-mainnet",
        native_symbol: str = "BNB",
        contract_addresses: Iterable[str] | None = None,
        asset_symbol: str | None = None,
        lookback_blocks: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_interval: float = 0.12,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.NODEREAL_API_KEY
        self.chain_slug = chain_slug
        self.native_symbol = native_symbol
        # When set, only these token contracts are followed. Empty means the
        # chain's native currency.
        self.contract_addresses = [normalize_address(a) for a in (contract_addresses or [])]
        self.asset_symbol = asset_symbol or native_symbol
        self.lookback_blocks = (
            lookback_blocks if lookback_blocks is not None else config.NODEREAL_LOOKBACK_BLOCKS
        )
        self.max_retries = max_retries
        self.min_interval = min_interval

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self.evidence = EvidenceLog()
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._head_block: int | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def url(self) -> str:
        return f"https://{self.chain_slug}.nodereal.io/v1/{self.api_key}"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "NoderealClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_at = time.monotonic()

    def _rpc(self, method: str, params: list[Any]) -> Any:
        if not self.api_key:
            raise NoderealError(
                "NODEREAL_API_KEY is not set. Add a free key from "
                "https://nodereal.io to backend/.env to trace this chain."
            )

        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.post(self.url, json=payload)
            except httpx.RequestError as exc:
                last_error = NoderealError(f"Network error contacting NodeReal: {exc}")
                self._backoff(attempt, str(exc))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = NoderealError(f"NodeReal returned HTTP {response.status_code}")
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise NoderealError(
                    f"NodeReal returned HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise NoderealError(f"NodeReal returned non-JSON: {exc}") from exc

            if body.get("error"):
                message = str(body["error"].get("message", body["error"]))
                # Rate limiting arrives as a JSON-RPC error, not an HTTP status.
                if "limit" in message.lower() or "too many" in message.lower():
                    last_error = NoderealError(f"NodeReal rate limit: {message}")
                    self._backoff(attempt, "rate limit")
                    continue
                raise NoderealError(f"NodeReal error: {message}")

            self.evidence.record(
                "nodereal",
                f"POST {self.url.split('/v1/')[0]}/v1/<key> {method} {json.dumps(params, sort_keys=True)}",
                response.content,
            )
            return body.get("result")

        raise NoderealError(
            f"NodeReal request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _backoff(self, attempt: int, reason: str) -> None:
        delay = (0.4 * (2**attempt)) + random.uniform(0, 0.2)
        logger.warning("NodeReal retry %d/%d in %.2fs (%s)",
                       attempt + 1, self.max_retries, delay, reason)
        time.sleep(delay)

    def head_block(self) -> int:
        """Highest block safe to query, cached for the life of the client.

        This is the chain head less an indexing margin, not the head itself --
        see INDEX_LAG_BLOCKS.
        """
        if self._head_block is None:
            result = self._rpc("eth_blockNumber", [])
            tip = int(result, 16) if isinstance(result, str) else 0
            self._head_block = max(0, tip - INDEX_LAG_BLOCKS)
        return self._head_block

    # -- parsing -----------------------------------------------------------
    def _to_transaction(self, raw: dict[str, Any]) -> Transaction | None:
        """Convert one nr_getAssetTransfers record into our Transaction.

        Returns None for anything unusable so a single malformed record cannot
        abort a trace.
        """
        try:
            to_raw = raw.get("to") or ""
            if not to_raw:
                return None

            raw_value = raw.get("value") or "0x0"
            units = int(raw_value, 16) if isinstance(raw_value, str) else int(raw_value)
            # The token states its own precision; never assume 18.
            decimals = int(raw.get("decimal") or 18)
            amount = units / (10**decimals) if decimals >= 0 else float(units)

            block_raw = raw.get("blockNum") or "0x0"
            block = int(block_raw, 16) if isinstance(block_raw, str) else int(block_raw)

            return Transaction(
                hash=raw.get("hash", ""),
                from_address=normalize_address(raw.get("from", "")),
                to_address=normalize_address(to_raw),
                value_native=amount,
                value_wei=units,
                timestamp=int(raw.get("blockTimeStamp") or 0),
                block_number=block,
                # receiptsStatus 0 means the transaction reverted; no value moved.
                is_error=str(raw.get("receiptsStatus", 1)) == "0",
                asset=raw.get("asset") or self.asset_symbol,
                contract_address=normalize_address(raw["contractAddress"])
                if raw.get("contractAddress")
                else None,
            )
        except (TypeError, ValueError):
            logger.warning("Skipping malformed NodeReal transfer: %r", raw)
            return None

    # -- public API --------------------------------------------------------
    def get_outgoing_transactions(
        self, address: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers sent *by* `address`, newest first."""
        return self._get_directional_transactions(address, "fromAddress", limit)

    def get_incoming_transactions(
        self, address: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers received *by* `address`, newest first.

        What a reverse trace follows. NodeReal filters on either end server
        side, so this costs exactly what the outgoing direction costs.
        """
        return self._get_directional_transactions(address, "toAddress", limit)

    def _get_directional_transactions(
        self, address: str, direction_param: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers with `address` at one end, newest first.

        `direction_param` is NodeReal's own filter key -- "fromAddress" for
        transfers sent, "toAddress" for transfers received. Pushing the filter
        to the server means we pay for exactly the records the trace follows.

        History is walked backwards from the chain head in 100k-block windows
        (the API maximum) and stops as soon as `limit` transfers are collected,
        so an active address costs one request while a quiet one costs a few.
        """
        if not is_valid_address(address):
            raise ValueError(f"Not a valid EVM address: {address!r}")

        cap = limit or config.TRACE_MAX_TXS_PER_ADDRESS
        category = [CATEGORY_ERC20] if self.contract_addresses else [CATEGORY_NATIVE]

        head = self.head_block()
        floor = max(0, head - self.lookback_blocks)
        collected: list[Transaction] = []
        window_end = head

        while window_end > floor and len(collected) < cap:
            window_start = max(floor, window_end - MAX_BLOCK_WINDOW + 1)
            page_key: str | None = None

            while len(collected) < cap:
                params: dict[str, Any] = {
                    "category": category,
                    "fromBlock": hex(window_start),
                    "toBlock": hex(window_end),
                    direction_param: normalize_address(address),
                    "maxCount": hex(min(MAX_COUNT, cap - len(collected))),
                    "order": "desc",
                }
                if self.contract_addresses:
                    params["contractAddresses"] = self.contract_addresses
                if page_key:
                    params["pageKey"] = page_key

                try:
                    result = self._rpc("nr_getAssetTransfers", [params]) or {}
                except NoderealError as exc:
                    # The index is further behind than our margin assumed. Step
                    # the window back and try once more rather than failing the
                    # whole trace over a few seconds of chain tip.
                    if NOT_INDEXED not in str(exc).lower() or window_end <= window_start:
                        raise
                    window_end = max(window_start, window_end - 256)
                    self._head_block = min(self._head_block or window_end, window_end)
                    params["toBlock"] = hex(window_end)
                    result = self._rpc("nr_getAssetTransfers", [params]) or {}
                for raw in result.get("transfers") or []:
                    tx = self._to_transaction(raw)
                    # Only value-bearing, successful transfers are evidence of
                    # money moving; the rest is noise the trace must not follow.
                    if tx and not tx.is_error and tx.value_wei > 0:
                        collected.append(tx)

                page_key = result.get("pageKey")
                if not page_key:
                    break

            window_end = window_start - 1

        return collected[:cap]

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        """One transaction's receipt and event logs, for reading swap outputs."""
        result = self._rpc("eth_getTransactionReceipt", [tx_hash])
        return result if isinstance(result, dict) else None

    def get_transactions(self, address: str, limit: int | None = None, sort: str = "desc"):
        """Present for interface parity; callers pick a direction explicitly."""
        return self.get_outgoing_transactions(address, limit=limit)
