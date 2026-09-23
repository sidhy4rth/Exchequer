"""Thin, rate-limit-aware wrapper around the Etherscan API.

Only one thing is asked of this module by the rest of Exchequer:

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
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from . import config
from .api_budget import ResponseCache, SharedPacer, get_cache, get_pacer
from .evidence import EvidenceLog

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


_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def is_tron_address(address: str) -> bool:
    """A Tron address in its Base58Check form, checksum included.

    The shape alone lets a typo through, and TronGrid then refuses the address
    with an error that reads like a provider outage. The last four bytes are a
    double-SHA-256 checksum of the rest, so a mistyped character is caught
    here and reported as an invalid address instead.
    """
    if not address or not TRON_ADDRESS_RE.match(address.strip()):
        return False
    number = 0
    for char in address.strip():
        number = number * 58 + _BASE58.index(char)
    try:
        raw = number.to_bytes(25, "big")
    except OverflowError:
        return False
    return raw[0] == 0x41 and hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] == raw[21:]


def is_valid_address(address: str) -> bool:
    """True if `address` is a syntactically valid address on any chain we trace.

    Deliberately permissive: it accepts both formats, because the graph builder
    and matcher handle whatever the selected chain produced. Whether an address
    belongs to the chain the user actually asked for is a stricter question,
    answered by Chain.validate_address in config.py.
    """
    return is_evm_address(address) or is_tron_address(address)


def normalize_address(address: str) -> str:
    """Canonical key form used everywhere in Exchequer.

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
    # True when the value was moved by a contract call (Etherscan's
    # `txlistinternal`) rather than by a transaction the sender signed. The
    # money moved just the same; the flag is kept so a report can say how.
    internal: bool = False

    @classmethod
    def from_api(cls, raw: dict[str, Any], internal: bool = False) -> "Transaction | None":
        """Build a Transaction from one Etherscan `txlist` or `txlistinternal` record.

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
                internal=internal,
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
        min_interval: float | None = None,  # None -> config.ETHERSCAN_MIN_INTERVAL
        contract_address: str | None = None,
        asset_symbol: str | None = None,
        client: httpx.Client | None = None,
        include_internal: bool | None = None,  # None -> config.ETHERSCAN_INCLUDE_INTERNAL
    ) -> None:
        self.api_key = api_key if api_key is not None else config.ETHERSCAN_API_KEY
        self.chain_id = chain_id if chain_id is not None else config.ETHERSCAN_CHAIN_ID
        self.base_url = base_url or config.ETHERSCAN_BASE_URL
        self.max_retries = max_retries
        self.min_interval = (
            min_interval if min_interval is not None else config.ETHERSCAN_MIN_INTERVAL
        )
        # When set, the client follows this ERC-20 contract instead of native
        # ETH. A trace follows one asset at a time.
        self.contract_address = (
            normalize_address(contract_address) if contract_address else None
        )
        self.asset_symbol = asset_symbol or "ETH"
        self.include_internal = (
            include_internal if include_internal is not None else config.ETHERSCAN_INCLUDE_INTERNAL
        )

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

        # Etherscan enforces its rate limit per API key, across every chain that
        # key is used on -- one V2 key serves Ethereum and BSC alike. A client is
        # built per trace, so pacing it per instance would let two concurrent
        # traces double the request rate against a limit that never doubled.
        # Both the pacer and the cache are therefore keyed by credential, not by
        # client and not by chain.
        scope = f"etherscan:{(self.api_key or 'anon')[:8]}"
        self._pacer = get_pacer(
            scope,
            lambda: SharedPacer(
                interval=self.min_interval,
                min_interval=self.min_interval,
                # Measured against the live free tier, refusals start well below
                # the documented ceiling and cost more than they save. Give the
                # pacer room to back off to roughly one request per second.
                max_interval=max(self.min_interval * 5, 2.5),
            ),
        )
        self._cache = get_cache(
            scope, lambda: ResponseCache(
                ttl_seconds=config.API_CACHE_TTL_SECONDS, path=config.API_CACHE_PATH,
            )
        )
        # Every response this client's trace was built from, hashed on arrival.
        self.evidence = EvidenceLog()

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
        """Block until the credential's shared schedule permits a request."""
        self._pacer.wait()

    @staticmethod
    def _cache_key(params: dict[str, Any]) -> tuple:
        """A stable key for one query, with the credential left out.

        Sorted so parameter order cannot produce two entries for one question,
        and without `apikey` so the same query asked under a different key still
        hits -- the answer is a property of the chain, not of who asked.
        """
        return tuple(sorted(
            (k, str(v)) for k, v in params.items() if k != "apikey"
        ))

    def _describe(self, query: dict[str, Any]) -> str:
        """The request as a reviewer would re-issue it: same URL, same
        parameters in a fixed order, without the credential."""
        parts = "&".join(f"{k}={v}" for k, v in sorted(query.items()) if k != "apikey")
        return f"GET {self.base_url}?{parts}"

    def _record(self, request_desc: str, cache_key: tuple, response: httpx.Response, result: Any) -> None:
        """Hash the bytes this answer came from, store them with the cached
        value, and log them as evidence for this trace."""
        rec = self.evidence.record("etherscan", request_desc, response.content)
        self._cache.put(cache_key, result, meta={
            "sha256": rec.sha256, "retrieved_at": rec.retrieved_at, "bytes": rec.bytes,
        })

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

        # On-chain history is append-only, so a cached answer can only ever lag
        # the newest blocks -- it cannot be wrong about what already happened.
        # That is what makes this safe, and it is the single biggest saving
        # available: the provider, not the traversal, is what makes a trace slow.
        cache_key = self._cache_key(query)
        request_desc = self._describe(query)
        hit, cached = self._cache.get(cache_key)
        if hit:
            self.evidence.record_cached("etherscan", request_desc, self._cache.meta(cache_key))
            return cached

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
                if response.status_code == 429:
                    self._pacer.penalize()
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
                self._pacer.reward()
                result = payload.get("result")
                self._record(request_desc, cache_key, response, result)
                return result

            status = str(payload.get("status", ""))
            message = str(payload.get("message", ""))
            result = payload.get("result")

            if status == "1":
                self._pacer.reward()
                self._record(request_desc, cache_key, response, result)
                return result

            # status != "1". Three distinct cases, and they must not be conflated.
            haystack = f"{message} {result if isinstance(result, str) else ''}".lower()

            # 1. Genuinely empty -- a valid answer, not a failure. Cached like
            # any other answer: "this address has no transactions" is exactly as
            # re-askable as a full list, and re-asking it costs the same second.
            if any(phrase in haystack for phrase in _EMPTY_MESSAGES):
                self._pacer.reward()
                self._record(request_desc, cache_key, response, [])
                return []

            # 2. Rate limited -- back off and retry.
            if any(phrase in haystack for phrase in _RATE_LIMIT_MESSAGES):
                last_error = EtherscanRateLimitError(
                    f"Etherscan rate limit hit: {message} {result}"
                )
                # Tell the shared pacer, not just this call: a refusal means the
                # rate every trace is using is too high, and slowing only the
                # request that happened to be refused would leave the others to
                # trip the same limit again.
                self._pacer.penalize()
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
        include_internal: bool | None = None,
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
            result = []

        parse = (
            Transaction.from_token_api if self.contract_address else Transaction.from_api
        )
        txs = [tx for tx in (parse(raw) for raw in result) if tx is not None]

        # Value moved by a contract call -- a multisig paying out, a
        # smart-contract wallet, a router returning ETH -- never appears in
        # txlist. It is a second endpoint and a second request; see
        # config.ETHERSCAN_INCLUDE_INTERNAL for why that is a switch.
        want_internal = self.include_internal if include_internal is None else include_internal
        if not self.contract_address and want_internal:
            internal_raw = self._request({**params, "action": "txlistinternal"})
            if isinstance(internal_raw, list):
                txs += [
                    tx for tx in (Transaction.from_api(raw, internal=True) for raw in internal_raw)
                    if tx is not None
                ]
            # Each source was capped at `offset` by its own request. The union
            # is deliberately NOT capped again: measured on a busy demo wallet,
            # trimming the merged list to the newest `offset` let a burst of
            # recent internal inflows displace the older signed outflows the
            # trace was actually following, and the graph shrank from 31
            # addresses to 6.
            txs.sort(key=lambda t: t.timestamp, reverse=(sort == "desc"))

        return txs

    def get_outgoing_transactions(self, address: str, limit: int | None = None) -> list[Transaction]:
        """Only the transfers *sent by* `address` that actually moved value.

        This is what the trace follows: we are chasing where the money went.
        Reverted txs and zero-value calls are excluded because no funds moved.

        Internal transactions are read only when the signed list shows no
        outgoing transfer at all. A wallet that signs transactions cannot
        originate an internal transfer, so for an ordinary wallet the second
        request could only ever return nothing; it matters for a contract --
        a multisig, a smart-contract wallet -- which never signs. Measured on
        the README's flagship address at 4 hops, asking unconditionally cost
        110 requests where 41 had done the job.
        """
        target = normalize_address(address)

        def outgoing(txs: list[Transaction]) -> list[Transaction]:
            return [
                tx for tx in txs
                if tx.from_address == target
                and tx.to_address is not None
                and not tx.is_error
                and tx.value_wei > 0
            ]

        signed = outgoing(self.get_transactions(address, limit=limit, include_internal=False))
        if signed or self.contract_address or not self.include_internal:
            return signed
        return outgoing(self.get_transactions(address, limit=limit, include_internal=True))

    def get_incoming_transactions(self, address: str, limit: int | None = None) -> list[Transaction]:
        """Only the transfers *received by* `address` that actually moved value.

        This is what a reverse trace follows -- who funded this address, rather
        than where its money went. Etherscan's txlist returns both directions
        in one response, so this costs no extra API call beyond the outgoing
        fetch it mirrors.
        """
        target = normalize_address(address)
        return [
            tx
            for tx in self.get_transactions(address, limit=limit)
            if tx.to_address == target
            and tx.from_address
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

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        """The receipt of one transaction, with its event logs.

        Used to read what a swap returned to the sender: the ERC-20 Transfer
        events in the receipt are the only place that fact is recorded. The
        `proxy` module is on the free tier and one receipt costs one request.
        """
        result = self._request(
            {"module": "proxy", "action": "eth_getTransactionReceipt", "txhash": tx_hash}
        )
        return result if isinstance(result, dict) else None

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
