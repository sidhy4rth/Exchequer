"""Thin, rate-limit-aware wrapper around the Etherscan API.

Only one thing is asked of this module by the rest of TraceChain:

    client.get_transactions(address) -> list[Transaction]

Everything else (retries, backoff, Etherscan's several ways of saying
"nothing here", wei -> native-unit conversion) is handled internally so the
graph
builder can stay readable.

Notes on the API:
  * We target Etherscan's V2 multi-chain endpoint
    (https://api.etherscan.io/v2/api?chainid=<id>&...). The old per-chain V1
    hosts have been retired.
  * One key serves every chain. `chain_id` selects which one: 1 = Ethereum
    mainnet, 56 = BNB Smart Chain. Both are EVM chains with the same address
    format and the same 18-decimal native unit, so nothing below is
    chain-specific -- only the value's *name* (ETH vs BNB) differs, and that
    is the caller's business, not this module's.
  * The free tier allows ~5 requests/second. We self-throttle below that and
    back off exponentially on the "rate limit reached" response, so a live
    demo does not die mid-trace.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import config

logger = logging.getLogger(__name__)

WEI_PER_UNIT = 10**18

# An EVM address: 0x followed by 40 hex characters. Identical on Ethereum
# and BNB Smart Chain.
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# A Tron address: 'T' followed by 33 Base58 characters. Base58 deliberately
# omits 0, O, I and l because they are easy to confuse by eye.
TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def is_evm_address(address: str) -> bool:
    return bool(address) and bool(ADDRESS_RE.match(address.strip()))


def is_tron_address(address: str) -> bool:
    return bool(address) and bool(TRON_ADDRESS_RE.match(address.strip()))


def is_valid_address(address: str) -> bool:
    """True if `address` is a syntactically valid address on any chain we trace.

    Deliberately permissive: it accepts both formats, because the graph builder
    and matcher handle whatever the selected chain produced. Whether an address
    belongs to the chain the user actually asked for is a stricter question,
    answered by Chain.validate_address in config.py.
    """
    return is_evm_address(address) or is_tron_address(address)


def normalize_address(address: str) -> str:
    """Canonical key form used everywhere in TraceChain.

    EVM addresses are lowercased: Etherscan returns mixed-case (EIP-55
    checksummed) addresses in some fields and lowercase in others, and
    comparing them raw would silently miss exchange hot-wallet matches -- the
    whole point of the tool.

    Tron addresses are left exactly as they are. Base58 is case-sensitive, so
    lowercasing one does not produce a different spelling of the same address;
    it produces a string that is not an address at all, and every subsequent
    comparison would fail silently.
    """
    stripped = address.strip()
    return stripped.lower() if stripped.startswith("0x") else stripped


class EtherscanError(RuntimeError):
    """Any non-recoverable problem talking to Etherscan."""


class EtherscanRateLimitError(EtherscanError):
    """Raised when Etherscan keeps rate-limiting us after all retries."""


class EtherscanConfigError(EtherscanError):
    """Raised when no API key is configured."""


@dataclass(frozen=True)
class Transaction:
    """One normal (external) native-currency transfer, normalized for our use.

    `value_native` is denominated in the chain's native unit -- ETH on
    Ethereum, BNB on BNB Smart Chain. Both use 18 decimals, so the conversion
    is the same; only the symbol shown to a reader differs.
    """

    hash: str
    from_address: str
    to_address: str | None  # None for contract-creation txs
    value_native: float
    value_wei: int
    timestamp: int  # unix seconds
    block_number: int
    is_error: bool  # True if the tx reverted -- no value actually moved
    # Which asset moved. Defaults to the chain's native currency, which is all
    # the Etherscan txlist endpoint returns; token providers set it explicitly.
    # A trace follows one asset at a time, so this is what the graph is about.
    asset: str = ""
    contract_address: str | None = None  # None for native transfers

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Transaction | None":
        """Build a Transaction from one Etherscan `txlist` record.

        Returns None if the record is unusable (missing/garbled fields) rather
        than raising, so one bad row cannot abort an entire trace.
        """
        try:
            to_raw = raw.get("to") or ""
            value_wei = int(raw.get("value", "0") or "0")
            return cls(
                hash=raw.get("hash", ""),
                from_address=normalize_address(raw.get("from", "")),
                to_address=normalize_address(to_raw) if to_raw else None,
                value_native=value_wei / WEI_PER_UNIT,
                value_wei=value_wei,
                timestamp=int(raw.get("timeStamp", "0") or "0"),
                block_number=int(raw.get("blockNumber", "0") or "0"),
                # Etherscan sets isError="1" on reverted txs. Those moved no
                # funds, so laundering heuristics must ignore them.
                is_error=str(raw.get("isError", "0")) == "1",
            )
        except (TypeError, ValueError):
            logger.warning("Skipping malformed Etherscan tx record: %r", raw)
            return None

    @classmethod
    def from_token_api(cls, raw: dict[str, Any]) -> "Transaction | None":
        """Build a Transaction from one Etherscan `tokentx` record.

        Two differences from the native `txlist` shape matter:

          * `value` is in the token's own smallest unit and the record carries
            its own `tokenDecimal`. USDT is 6 decimals on Ethereum and 18 on
            BNB Smart Chain, so the precision is read from the record rather
            than assumed -- getting this wrong misstates every amount by a
            factor of a trillion without anything appearing to fail.
          * There is no `isError` field, because a Transfer event only exists
            when the transaction succeeded. A reverted transfer emits nothing.
        """
        try:
            to_raw = raw.get("to") or ""
            if not to_raw:
                return None
            units = int(raw.get("value", "0") or "0")
            decimals = int(raw.get("tokenDecimal") or 18)
            return cls(
                hash=raw.get("hash", ""),
                from_address=normalize_address(raw.get("from", "")),
                to_address=normalize_address(to_raw),
                value_native=units / (10**decimals) if decimals >= 0 else float(units),
                value_wei=units,
                timestamp=int(raw.get("timeStamp", "0") or "0"),
                block_number=int(raw.get("blockNumber", "0") or "0"),
                is_error=False,
                asset=raw.get("tokenSymbol") or "",
                contract_address=normalize_address(raw["contractAddress"])
                if raw.get("contractAddress")
                else None,
            )
        except (TypeError, ValueError):
            logger.warning("Skipping malformed Etherscan token record: %r", raw)
            return None


# Etherscan phrases that mean "your query was fine, there is simply no data".
# These are successful empty results, not errors.
_EMPTY_MESSAGES = (
    "no transactions found",
    "no records found",
)

# Phrases that mean "slow down" -- worth retrying with backoff.
_RATE_LIMIT_MESSAGES = (
    "rate limit",
    "max rate limit reached",
    "too many requests",
)


class EtherscanClient:
    """Rate-limit-aware Etherscan client.

    Thread-safe: the internal throttle is guarded by a lock so the client can
    be shared across FastAPI's worker threads.
    """

    def __init__(
        self,
        api_key: str | None = None,
        chain_id: int | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
        max_retries: int = 4,
        min_interval: float = 0.34,  # ~3 req/s, the current free-tier ceiling
        contract_address: str | None = None,
        asset_symbol: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.ETHERSCAN_API_KEY
        self.chain_id = chain_id if chain_id is not None else config.ETHERSCAN_CHAIN_ID
        self.base_url = base_url or config.ETHERSCAN_BASE_URL
        self.max_retries = max_retries
        self.min_interval = min_interval
        # When set, the client follows this ERC-20 contract instead of native
        # ETH. A trace follows one asset at a time.
        self.contract_address = (
            normalize_address(contract_address) if contract_address else None
        )
        self.asset_symbol = asset_symbol or "ETH"

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "EtherscanClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------
    def _throttle(self) -> None:
        """Space requests at least `min_interval` apart to stay under the cap."""
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_at = time.monotonic()

    def _request(self, params: dict[str, Any]) -> Any:
        """Perform one Etherscan call with throttling, retries and backoff.

        Returns the `result` field on success. Raises EtherscanError on a
        non-recoverable failure.
        """
        if not self.api_key:
            raise EtherscanConfigError(
                "ETHERSCAN_API_KEY is not set. Copy backend/.env.example to "
                "backend/.env and add a free key from https://etherscan.io/apis "
                "(the same key works on every supported chain)."
            )

        query = {**params, "chainid": self.chain_id, "apikey": self.api_key}
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(self.base_url, params=query)
            except httpx.RequestError as exc:  # DNS failure, timeout, reset...
                last_error = EtherscanError(f"Network error contacting Etherscan: {exc}")
                self._backoff(attempt, reason=str(exc))
                continue

            # 429/5xx are transient; retry them.
            if response.status_code == 429 or response.status_code >= 500:
                last_error = EtherscanError(
                    f"Etherscan returned HTTP {response.status_code}"
                )
                self._backoff(attempt, reason=f"HTTP {response.status_code}")
                continue

            if response.status_code != 200:
                raise EtherscanError(
                    f"Etherscan returned HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise EtherscanError(f"Etherscan returned non-JSON response: {exc}") from exc

            # The `proxy` module speaks JSON-RPC and has no `status` field.
            if "jsonrpc" in payload:
                if payload.get("error"):
                    raise EtherscanError(f"Etherscan proxy error: {payload['error']}")
                return payload.get("result")

            status = str(payload.get("status", ""))
            message = str(payload.get("message", ""))
            result = payload.get("result")

            if status == "1":
                return result

            # status != "1". Three distinct cases, and they must not be conflated.
            haystack = f"{message} {result if isinstance(result, str) else ''}".lower()

            # 1. Genuinely empty -- a valid answer, not a failure.
            if any(phrase in haystack for phrase in _EMPTY_MESSAGES):
                return []

            # 2. Rate limited -- back off and retry.
            if any(phrase in haystack for phrase in _RATE_LIMIT_MESSAGES):
                last_error = EtherscanRateLimitError(
                    f"Etherscan rate limit hit: {message} {result}"
                )
                self._backoff(attempt, reason="rate limit")
                continue

            # 3. A real error (bad key, invalid address, ...) -- do not retry.
            raise EtherscanError(
                f"Etherscan error: {message or 'unknown'} ({result})"
            )

        if isinstance(last_error, EtherscanRateLimitError):
            raise last_error
        raise EtherscanError(
            f"Etherscan request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _backoff(self, attempt: int, reason: str) -> None:
        """Exponential backoff with jitter: ~0.5s, 1s, 2s, 4s."""
        delay = (0.5 * (2**attempt)) + random.uniform(0, 0.25)
        logger.warning(
            "Etherscan retry %d/%d in %.2fs (%s)",
            attempt + 1,
            self.max_retries,
            delay,
            reason,
        )
        time.sleep(delay)

    # -- public API --------------------------------------------------------
    def get_transactions(
        self,
        address: str,
        limit: int | None = None,
        sort: str = "desc",
    ) -> list[Transaction]:
        """Return normal native-currency transactions involving `address`.

        `limit` caps how many records we pull (default: TRACE_MAX_TXS_PER_ADDRESS)
        so one whale wallet cannot stall a trace. `sort="desc"` puts the most
        recent activity first, which is what an investigator cares about.

        An address with no transactions returns [] -- that is a valid answer,
        not an error.
        """
        if not is_valid_address(address):
            raise ValueError(f"Not a valid EVM address: {address!r}")

        offset = limit or config.TRACE_MAX_TXS_PER_ADDRESS
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx" if self.contract_address else "txlist",
            "address": normalize_address(address),
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": offset,
            "sort": sort,
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address

        result = self._request(params)

        if not isinstance(result, list):
            # Etherscan occasionally returns a bare string on odd inputs.
            logger.warning("Unexpected %s result for %s: %r",
                           params["action"], address, result)
            return []

        parse = (
            Transaction.from_token_api if self.contract_address else Transaction.from_api
        )
        txs = [parse(raw) for raw in result]
        return [tx for tx in txs if tx is not None]

    def get_outgoing_transactions(self, address: str, limit: int | None = None) -> list[Transaction]:
        """Only the transfers *sent by* `address` that actually moved value.

        This is what the trace follows: we are chasing where the money went.
        Reverted txs and zero-value calls are excluded because no funds moved.
        """
        target = normalize_address(address)
        return [
            tx
            for tx in self.get_transactions(address, limit=limit)
            if tx.from_address == target
            and tx.to_address is not None
            and not tx.is_error
            and tx.value_wei > 0
        ]

    def get_transaction_count(self, address: str) -> int:
        """Nonce = number of transactions *sent* by this address.

        Used to sanity-check exchange labels: a real hot wallet has sent a very
        large number of transactions.
        """
        if not is_valid_address(address):
            raise ValueError(f"Not a valid EVM address: {address!r}")
        result = self._request(
            {
                "module": "proxy",
                "action": "eth_getTransactionCount",
                "address": normalize_address(address),
                "tag": "latest",
            }
        )
        return int(result, 16) if isinstance(result, str) else 0

    def get_balance_native(self, address: str) -> float:
        """Current native-currency balance of `address`."""
        if not is_valid_address(address):
            raise ValueError(f"Not a valid EVM address: {address!r}")
        result = self._request(
            {
                "module": "account",
                "action": "balance",
                "address": normalize_address(address),
                "tag": "latest",
            }
        )
        try:
            return int(result) / WEI_PER_UNIT
        except (TypeError, ValueError):
            return 0.0
