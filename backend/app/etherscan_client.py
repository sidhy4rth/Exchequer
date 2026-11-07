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
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from . import config
from .api_budget import (BudgetSpent, ResponseCache, ResponseTooLarge, SharedPacer, fresh_reads, get_cache,
                         get_pacer, spend, credential as meter_key,
                         read_capped)
from .evidence import EvidenceLog

logger = logging.getLogger(__name__)

WEI_PER_UNIT = 10**18

# The `endblock` of every open-ended read: above any chain's height, so
# Etherscan stops at its newest indexed block. It was 99,999,999, which
# Arbitrum passed in 2023 -- its reads then ended in 2023, and a read from an
# arrival above that block asked for an inverted range. A constant rather
# than the head, so the request (and its cache key) is the same every time.
ENDBLOCK_LATEST = 9_999_999_999

# The chain head, read once per chain and shared by every client for this
# long: concurrent traces and watch checks then cost one eth_blockNumber call
# between them. (base_url, chain_id) -> (monotonic read time, head).
HEAD_MEMO_SECONDS = 15.0
_confirmed_heads: dict[tuple[str, int], tuple[float, int]] = {}
_confirmed_heads_lock = threading.Lock()
_UNREAD = object()

# An EVM address: 0x followed by 40 hex characters. Identical on Ethereum
# and BNB Smart Chain.
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# A Tron address: 'T' followed by 33 Base58 characters. Base58 deliberately
# omits 0, O, I and l because they are easy to confuse by eye.
TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def is_evm_address(address: str) -> bool:
    return bool(address) and bool(ADDRESS_RE.match(address.strip()))


def evm_checksum_ok(address: str) -> bool:
    """True unless `address` mixes upper and lower case against its EIP-55 checksum.

    Mixed case is EIP-55: each letter is upper case exactly when the matching
    nibble of keccak256(lowercase hex) is 8 or more, which is what catches a
    mistyped character. An all-lowercase or all-uppercase address carries no
    checksum and passes. Only addresses a person submits are held to this;
    provider records are not.
    """
    body = address.strip()[2:]
    if body == body.lower() or body == body.upper():
        return True
    from .keccak import keccak256

    digest = keccak256(body.lower().encode("ascii")).hex()
    return all(
        char.isdigit() or char.isupper() == (int(nibble, 16) >= 8)
        for char, nibble in zip(body, digest, strict=False)
    )


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


@dataclass(frozen=True)
class SinceRead:
    """What a watch read forward from its cursor (read_outgoing_since).

    `transfers`: value-bearing transfers the address sent, oldest first, each
    after the cursor and at or below `through`. `through`: every record at or
    below this position (block, or Unix time on Tron) has been read, whatever
    its direction or value, so the cursor may move there and no further.
    `complete`: nothing more up to the chain's head. `cut`: a block (on Tron,
    a second) that held more records than a read can return; it counts as
    read so the cursor moves on, and the watch says some may be missing."""

    transfers: list["Transaction"]
    through: int
    complete: bool
    cut: int | None = None


def split_page(blocks: list[int], after: int, full: bool) -> tuple[int, bool]:
    """(through, complete) for an ascending page whose records sat at `blocks`.

    A short page read everything there is. A full one may have cut its last
    block in two, so that block is left for the next read -- unless the whole
    page is one block. The readers then read that block alone, whole, before
    it counts as read; it counts as read either way, so the cursor can never
    stall (a block too big to read whole is reported as `cut`)."""
    if not full:
        return max([after, *blocks]), True
    first, last = min(blocks), max(blocks)
    return (last if first == last else last - 1), False


# The last block a watch's forward read asks for: above any chain's height
# (Arbitrum One passed 99,999,999 in 2023); Etherscan stops at its newest.
SINCE_ENDBLOCK = 9_999_999_999
# Records a read of one block alone may return: Etherscan's page x offset
# ceiling, and more than one address's records any block's gas can hold.
WHOLE_BLOCK = 10_000


class EtherscanError(RuntimeError):
    """Any non-recoverable problem talking to Etherscan."""


class EtherscanRateLimitError(EtherscanError):
    """Raised when Etherscan keeps rate-limiting us after all retries."""


class ProviderQuotaError(EtherscanRateLimitError):
    """A provider's daily or monthly allowance is spent. Unlike a momentary rate
    limit, waiting seconds cannot help, so it is never retried and never slows
    the shared pacer; the officer is told the quota is used up."""


class AllowanceSpent(BudgetSpent, ProviderQuotaError):
    """The site's own allowance for the day (api_budget.UnitMeter) refused a
    request: to a trace a stop like its request budget, to a script or a
    watch check a spent quota like the provider's own."""


class EtherscanConfigError(EtherscanError):
    """Raised when no API key is configured."""


class ProviderResponseError(EtherscanError):
    """A provider answered with something Exchequer cannot read: the wrong JSON
    shape, a field that should be hex and is not. A provider failure like any
    other (a 502 at the seed), never an AttributeError that reads as a crash."""


def safe_int(value: Any, base: int = 10, default: int = 0) -> int:
    """`int(value, base)` for a provider field, `default` when it is garbled."""
    try:
        if isinstance(value, str):
            return int(value, base) if value.strip() else default
        return int(value) if isinstance(value, int) and base == 10 else default
    except (TypeError, ValueError):
        return default


def resolve_decimals(stated: Any, fallback: int | None) -> int | None:
    """The precision to divide a token amount by, or None if it is unknowable.

    The record's own figure wins; otherwise the fallback (the traced token's
    on-chain `decimals()` from config). A negative or garbled figure is treated
    as missing rather than trusted.
    """
    if stated not in (None, ""):
        try:
            value = int(stated)
        except (TypeError, ValueError):
            value = -1
        if value >= 0:
            return value
    return fallback


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
        if not isinstance(raw, dict):
            return None
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
    def from_token_api(
        cls, raw: dict[str, Any], fallback_decimals: int | None = None
    ) -> "Transaction | None":
        """Build a Transaction from one Etherscan `tokentx` record.

        Two differences from the native `txlist` shape matter:

          * `value` is in the token's own smallest unit and the record carries
            its own `tokenDecimal`. USDT is 6 decimals on Ethereum and 18 on
            BNB Smart Chain, so the precision is read from the record rather
            than assumed -- getting this wrong misstates every amount by a
            factor of a trillion without anything appearing to fail.
          * There is no `isError` field, because a Transfer event only exists
            when the transaction succeeded. A reverted transfer emits nothing.

        A record that arrives without `tokenDecimal` falls back to
        `fallback_decimals` -- the precision confirmed on-chain for the token
        being traced -- and is dropped if that is unknown too. Guessing 18 would
        turn a USDT transfer into a trillionth of itself.
        """
        if not isinstance(raw, dict):
            return None
        try:
            to_raw = raw.get("to") or ""
            if not to_raw:
                return None
            units = int(raw.get("value", "0") or "0")
            decimals = resolve_decimals(raw.get("tokenDecimal"), fallback_decimals)
            if decimals is None:
                logger.warning("Skipping token record with no known decimals: %r", raw)
                return None
            return cls(
                hash=raw.get("hash", ""),
                from_address=normalize_address(raw.get("from", "")),
                to_address=normalize_address(to_raw),
                value_native=units / (10**decimals),
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


# The fields of an account-list record (txlist, tokentx, txlistinternal) the
# parsers read. Only these are cached: the rest -- calldata (`input`) above
# all, which a sender controls -- is never read and was most of a cached page.
RECORD_FIELDS = ("hash", "from", "to", "value", "timeStamp", "blockNumber", "isError",
                 "contractAddress", "tokenDecimal", "tokenSymbol")
_LIST_ACTIONS = ("txlist", "tokentx", "txlistinternal")


# Current state rather than history: never served from the cache.
_STATE_ACTIONS = ("balance", "eth_getTransactionCount", "eth_getCode", "eth_call", "eth_blockNumber")


def cache_ttl(params: dict[str, Any], result: Any) -> float:
    """How long an answer to `params` may be reused (0: not at all).

    A closed block range is history and keeps for the cache's day. A read up
    to the tip -- newest-first pages, reads from a block forward, and their
    empty answers -- keeps for minutes; current state (`latest` balances,
    nonces, code, calls) and a receipt not yet mined are never kept."""
    if (params.get("tag") == "latest" or str(params.get("toBlock")) == "latest"
            or params.get("action") in _STATE_ACTIONS):
        return 0
    if params.get("action") == "eth_getTransactionReceipt" and result is None:
        return 0
    if str(params.get("endblock")) == str(ENDBLOCK_LATEST):
        return config.API_CACHE_OPEN_TTL_SECONDS
    return config.API_CACHE_TTL_SECONDS


def slim_records(params: dict[str, Any], result: Any) -> Any:
    """An account-list result cut down to RECORD_FIELDS; anything else as it came."""
    if params.get("module") != "account" or params.get("action") not in _LIST_ACTIONS:
        return result
    if not isinstance(result, list):
        return result
    return [{k: raw[k] for k in RECORD_FIELDS if k in raw} if isinstance(raw, dict) else raw
            for raw in result]


# Etherscan phrases that mean "your query was fine, there is simply no data".
# These are successful empty results, not errors.
_EMPTY_MESSAGES = (
    "no transactions found",
    "no records found",
)

# Phrases that mean "slow down" -- worth retrying with backoff.
# A spent allowance, checked before the rate-limit phrases ("Max daily rate
# limit reached ... calls per day" contains "rate limit" too).
_QUOTA_MESSAGES = ("daily", "per day", "monthly", "quota", "compute unit", "cu limit")
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

    # The case's clock and request budget (api_budget.TraceBudget), set by
    # pipeline.run_trace; None outside a trace (scripts, the watcher).
    budget = None

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
        token_decimals: int | None = None,
        client: httpx.Client | None = None,
        include_internal: bool | None = None,  # None -> config.ETHERSCAN_INCLUDE_INTERNAL
        confirmations: int | None = None,  # config.Chain.confirmations; None reads to the tip
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
        # The traced token's confirmed precision, used only when a record
        # omits its own.
        self.token_decimals = token_decimals
        self.include_internal = (
            include_internal if include_internal is not None else config.ETHERSCAN_INCLUDE_INTERNAL
        )
        # Rows above the head less this many blocks are dropped from every
        # parsed read (confirmed_head). False once the head could not be read:
        # the rows were then kept, and the trace says so.
        self.confirmations = confirmations
        self.confirmed_bound_applied = True
        self._bound: Any = _UNREAD
        self._bound_lock = threading.Lock()

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

        # Etherscan enforces its rate limit per API key, across every chain that
        # key is used on -- one V2 key serves Ethereum and BSC alike. A client is
        # built per trace, so pacing it per instance would let two concurrent
        # traces double the request rate against a limit that never doubled.
        # Both the pacer and the cache are therefore keyed by credential, not by
        # client and not by chain. The name is shown on the public /health
        # page, so it carries a digest of the key rather than any of the key.
        credential = hashlib.sha256((self.api_key or "anon").encode()).hexdigest()[:8]
        scope = f"etherscan:{credential}"
        self._meter_key = meter_key(self.api_key)  # the key's allowance for the day
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
        # address -> (the newest page came back full, its oldest record's time).
        # The page holds both directions, so the count of transfers an address
        # *sent* says nothing about whether older history went unread.
        self._newest_page: dict[str, tuple[bool, int | None]] = {}
        # address -> whether its latest read (newest page or forward read)
        # filled its page, so records past it went unread (history_capped).
        self._last_full: dict[str, bool] = {}

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

    def _record(self, request_desc: str, cache_key: tuple, response: httpx.Response, result: Any,
                params: dict[str, Any]) -> None:
        """Hash the bytes this answer came from, store them with the cached
        value for as long as that kind of answer stays true (cache_ttl), and
        log them as evidence for this trace. The hash is of the whole raw
        body; the cached value is only what the parsers read."""
        rec = self.evidence.record("etherscan", request_desc, response.content)
        self._cache.put(cache_key, result, meta={
            "sha256": rec.sha256, "retrieved_at": rec.retrieved_at, "bytes": rec.bytes,
        }, ttl=cache_ttl(params, result))

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
        # available: the provider, not the traversal, is what makes a trace
        # slow. How long an answer about the tip may lag is cache_ttl's call.
        cache_key = self._cache_key(query)
        request_desc = self._describe(query)
        hit, cached, meta = self._cache.get_with_meta(cache_key)
        if hit:
            self.evidence.record_cached("etherscan", request_desc, meta)
            return cached

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            spend("etherscan", self._meter_key, 1, self.budget)  # the case's clock and request budget, every attempt
            self._throttle()
            try:
                response = read_capped(self._client, "GET", self.base_url, params=query, **self._timeout())
            except ResponseTooLarge as exc:
                raise ProviderResponseError(f"Etherscan response too large: {exc}") from exc
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
                raise ProviderResponseError(f"Etherscan returned non-JSON response: {exc}") from exc
            if not isinstance(payload, dict):
                raise ProviderResponseError(f"Etherscan returned a JSON {type(payload).__name__}, not an object")

            # The `proxy` module speaks JSON-RPC and has no `status` field.
            if "jsonrpc" in payload:
                if payload.get("error"):
                    raise EtherscanError(f"Etherscan proxy error: {payload['error']}")
                self._pacer.reward()
                result = payload.get("result")
                self._record(request_desc, cache_key, response, result, params)
                return result

            status = str(payload.get("status", ""))
            message = str(payload.get("message", ""))
            result = payload.get("result")

            if status == "1":
                self._pacer.reward()
                result = slim_records(params, result)
                self._record(request_desc, cache_key, response, result, params)
                return result

            # status != "1". Three distinct cases, and they must not be conflated.
            haystack = f"{message} {result if isinstance(result, str) else ''}".lower()

            # 1. Genuinely empty -- a valid answer, not a failure. Cached like
            # any other answer: "this address has no transactions" is exactly as
            # re-askable as a full list, and re-asking it costs the same second.
            if any(phrase in haystack for phrase in _EMPTY_MESSAGES):
                self._pacer.reward()
                self._record(request_desc, cache_key, response, [], params)
                return []

            # 2a. The day's allowance is spent -- retrying cannot help.
            if any(phrase in haystack for phrase in _QUOTA_MESSAGES):
                raise ProviderQuotaError(f"Etherscan quota spent: {message} {result}")

            # 2b. Rate limited -- back off and retry.
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
        """Exponential backoff with jitter: ~0.5s, 1s, 2s, 4s. None after the
        last attempt: nothing follows it to wait for."""
        if attempt >= self.max_retries:
            return
        delay = (0.5 * (2**attempt)) + random.uniform(0, 0.25)
        logger.warning(
            "Etherscan retry %d/%d in %.2fs (%s)",
            attempt + 1,
            self.max_retries,
            delay,
            reason,
        )
        if self.budget is not None:
            self.budget.sleep(delay)  # never past the case's deadline
        else:
            time.sleep(delay)

    def _timeout(self) -> dict[str, float]:
        return {"timeout": self.budget.timeout(20.0)} if self.budget is not None else {}

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
            "endblock": ENDBLOCK_LATEST,
            "page": 1,
            "offset": offset,
            "sort": sort,
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address

        # The bound's head is read before the rows, so no kept row is newer.
        parse = self._parser()
        result = self._request(params)

        if not isinstance(result, list):
            # Etherscan occasionally returns a bare string on odd inputs.
            logger.warning("Unexpected %s result for %s: %r",
                           params["action"], address, result)
            result = []

        if sort == "desc":
            stamps = [safe_int(raw.get("timeStamp")) for raw in result if isinstance(raw, dict)]
            self._newest_page[normalize_address(address)] = (
                len(result) >= offset, min((t for t in stamps if t > 0), default=None),
            )
        self._last_full[normalize_address(address)] = len(result) >= offset

        txs = [tx for tx in (parse(raw) for raw in result) if tx is not None]

        # Value moved by a contract call -- a multisig paying out, a
        # smart-contract wallet, a router returning ETH -- never appears in
        # txlist. It is a second endpoint and a second request; see
        # config.ETHERSCAN_INCLUDE_INTERNAL for why that is a switch.
        want_internal = self.include_internal if include_internal is None else include_internal
        if not self.contract_address and want_internal:
            internal_raw = self._request({**params, "action": "txlistinternal"})
            if isinstance(internal_raw, list):
                parse_internal = self._parser(internal=True)
                txs += [tx for tx in (parse_internal(raw) for raw in internal_raw) if tx is not None]
            # Each source was capped at `offset` by its own request. The union
            # is deliberately NOT capped again: measured on a busy demo wallet,
            # trimming the merged list to the newest `offset` let a burst of
            # recent internal inflows displace the older signed outflows the
            # trace was actually following, and the graph shrank from 31
            # addresses to 6.
            txs.sort(key=lambda t: t.timestamp, reverse=(sort == "desc"))

        return txs

    def history_capped(self, address: str) -> bool | None:
        """Whether the latest read of `address` (its newest page, or a read
        forward from a block) came back full, so records past it went unread:
        zero-value or dust spam fills a page as well as real transfers do.
        None if it has not been read."""
        return self._last_full.get(normalize_address(address))

    def newest_page_info(self, address: str) -> tuple[bool, int | None] | None:
        """Whether the last newest-first read of `address` filled its page, and
        the time of the oldest record on it; None if it has not been read.

        A full page means older history exists that was not read, however few
        of the records on it were transfers the address sent."""
        return self._newest_page.get(normalize_address(address))

    def get_incoming_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], bool]:
        """Every value-bearing transfer *into* `address` in a block range.

        For pro-rata tracing: what joined the traced funds in a wallet between
        their arrival and the wallet sending on. Returns (transfers, complete);
        complete is False when the range held more than one page, so the
        caller can say "unknown" instead of scoring from part of the picture.
        """
        page = 1000
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx" if self.contract_address else "txlist",
            "address": normalize_address(address),
            "startblock": start_block, "endblock": end_block,
            "page": 1, "offset": page, "sort": "asc",
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address
        parse = self._parser()
        result = self._request(params)
        if not isinstance(result, list):
            result = []
        target = normalize_address(address)
        txs = [t for t in (parse(r) for r in result) if t is not None and t.to_address == target
               and not t.is_error and t.value_wei > 0]
        return txs, len(result) < page

    def get_flows_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], list[Transaction], bool]:
        """Every value-bearing transfer into and out of `address` in a block range.

        For FIFO and LIBR (app/tracing_methods.py), which need the order of
        everything the wallet did, not only what joined the traced funds. One
        request: the account list holds both directions. Returns (in, out,
        complete); complete is False when the range held more than one page.
        """
        page = 1000
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx" if self.contract_address else "txlist",
            "address": normalize_address(address),
            "startblock": start_block, "endblock": end_block,
            "page": 1, "offset": page, "sort": "asc",
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address
        parse = self._parser()
        result = self._request(params)
        if not isinstance(result, list):
            result = []
        target = normalize_address(address)
        moved = [t for t in (parse(r) for r in result) if t is not None and not t.is_error and t.value_wei > 0]
        incoming = [t for t in moved if t.to_address == target]
        outgoing = [t for t in moved if t.from_address == target and t.to_address is not None]
        return incoming, outgoing, len(result) < page

    def _parser(self, internal: bool = False) -> Callable[[dict[str, Any]], Transaction | None]:
        """The record parser for the asset this client follows. With a
        confirmation depth, a row above the confirmed head parses to None."""
        if self.contract_address:
            def parse(raw: dict[str, Any]) -> Transaction | None:
                return Transaction.from_token_api(raw, self.token_decimals)
        else:
            def parse(raw: dict[str, Any]) -> Transaction | None:
                return Transaction.from_api(raw, internal=internal)
        bound = self.confirmed_head()
        if bound is None:
            return parse

        def confirmed(raw: dict[str, Any]) -> Transaction | None:
            tx = parse(raw)
            return tx if tx is None or tx.block_number <= bound else None
        return confirmed

    def confirmed_head(self) -> int | None:
        """The newest block with `confirmations` blocks on top of it; None
        when no depth is set or the head could not be read.

        Read once per client, so every read of one trace (or one watch check)
        cuts at the same block, from a head shared across clients for
        HEAD_MEMO_SECONDS. The request (endblock=ENDBLOCK_LATEST) never
        changes, so cache keys and evidence URLs stay the same; the rows are
        cut after the answer arrives."""
        if not self.confirmations:
            return None
        with self._bound_lock:
            if self._bound is not _UNREAD:
                return self._bound
            memo_key = (self.base_url, self.chain_id)
            with _confirmed_heads_lock:
                memo = _confirmed_heads.get(memo_key)
            if memo is not None and time.monotonic() - memo[0] < HEAD_MEMO_SECONDS:
                head: int | None = memo[1]
            else:
                head = self._read_head()
                if head is not None:
                    with _confirmed_heads_lock:
                        _confirmed_heads[memo_key] = (time.monotonic(), head)
            if head is None:
                self.confirmed_bound_applied = False
                self._bound = None
            else:
                self._bound = max(0, head - self.confirmations)
            return self._bound

    def _read_head(self) -> int | None:
        """The chain's newest block number, never from the cache; None on failure."""
        try:
            with fresh_reads():
                result = self._request({"module": "proxy", "action": "eth_blockNumber"})
            head = int(result, 16) if isinstance(result, str) else None
        except (EtherscanError, ValueError) as exc:
            logger.warning("Could not read the %s head; newest rows are kept unconfirmed: %s",
                           self.chain_id, type(exc).__name__)
            return None
        return head if head and head > 0 else None

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

    def get_outgoing_transactions_since(
        self, address: str, start_block: int, limit: int | None = None,
    ) -> list[Transaction]:
        """The first transfers `address` sent at or after `start_block`, oldest first.

        get_outgoing_transactions reads the newest `limit` transfers. On a
        wallet that has been busy since the traced funds arrived, those can
        all be later than the transfers that moved the funds on, which the
        trace then never sees. This reads from the arrival forward instead;
        the graph builder asks for it only when the newest page did not reach
        back that far.
        """
        target = normalize_address(address)
        offset = limit or config.TRACE_MAX_TXS_PER_ADDRESS
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx" if self.contract_address else "txlist",
            "address": target,
            "startblock": max(0, int(start_block)),
            "endblock": ENDBLOCK_LATEST,
            "page": 1,
            "offset": offset,
            "sort": "asc",
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address

        def sent(raws: Any, internal: bool = False) -> list[Transaction]:
            if not isinstance(raws, list):
                return []
            parse = self._parser(internal=internal)
            return [
                tx for tx in (parse(raw) for raw in raws)
                if tx is not None and tx.from_address == target and tx.to_address is not None
                and not tx.is_error and tx.value_wei > 0
            ]

        self.confirmed_head()  # before the rows, so no kept row is newer than its head
        raws = self._request(params)
        self._last_full[target] = isinstance(raws, list) and len(raws) >= offset
        signed = sent(raws)
        if signed or self.contract_address or not self.include_internal:
            return signed
        internal = self._request({**params, "action": "txlistinternal"})
        self._last_full[target] = self._last_full[target] or (isinstance(internal, list) and len(internal) >= offset)
        return sent(internal, internal=True)

    def read_outgoing_since(self, address: str, after: int, limit: int) -> SinceRead:
        """What `address` sent after block `after`, oldest first, for a watch.

        One ascending page from after+1. The page holds both directions and
        zero-value records, and every one of them counts toward `through`:
        incoming dust or spam can fill a page but never hides the transfer
        before it, and never holds the cursor back. A full page that is all
        one block (one transaction can emit that many token records) is read
        again as that block alone, so a transfer after them in the same block
        is read too. Internal transfers are read over the same span when the
        signed list shows no send, as in get_outgoing_transactions."""
        target = normalize_address(address)
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx" if self.contract_address else "txlist",
            "address": target,
            "startblock": int(after) + 1,
            "endblock": SINCE_ENDBLOCK,
            "page": 1,
            "offset": limit,
            "sort": "asc",
        }
        if self.contract_address:
            params["contractaddress"] = self.contract_address

        def rows_of(raws: Any) -> list[dict[str, Any]]:
            return [r for r in raws if isinstance(r, dict)] if isinstance(raws, list) else []

        cut: list[int] = []
        # Rows above the confirmed head may still be reorganised away: they are
        # neither news nor read, so the cursor stops below them and the next
        # check reads them once they have settled (r2-g2-watchlist-alerts-0-10).
        bound = self.confirmed_head()

        def settled(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return rows if bound is None else [r for r in rows if int(r.get("blockNumber") or 0) <= bound]

        def page(query: dict[str, Any], parse: Callable[[dict[str, Any]], Transaction | None]
                 ) -> tuple[list[Transaction], list[int], bool]:
            fetched = rows_of(self._request(query))
            rows = settled(fetched)
            # A page cut at the bound read every settled row up to it: not full.
            full = bool(rows) and len(fetched) >= limit and len(rows) == len(fetched)
            blocks = [int(r.get("blockNumber") or 0) for r in rows]
            if full and min(blocks) == max(blocks):
                whole = rows_of(self._request({**query, "startblock": blocks[0], "endblock": blocks[0],
                                               "offset": WHOLE_BLOCK}))
                if len(whole) < len(rows):  # the block came back smaller than its first page
                    raise EtherscanError(f"Etherscan did not return block {blocks[0]} whole")
                if len(whole) >= WHOLE_BLOCK:
                    cut.append(blocks[0])
                rows, blocks = whole, [blocks[0]] * len(whole)
            sent = [t for t in (parse(r) for r in rows) if t is not None and t.from_address == target
                    and t.to_address is not None and not t.is_error and t.value_wei > 0]
            return sent, blocks, full

        sent, blocks, full = page(params, self._parser())
        through, complete = split_page(blocks, after, full)
        if not sent and not self.contract_address and self.include_internal:
            span = {**params, "action": "txlistinternal"}
            if not complete:
                span["endblock"] = through
            sent, iblocks, ifull = page(span, lambda raw: Transaction.from_api(raw, internal=True))
            ithrough, icomplete = split_page(iblocks, after, ifull)
            through = ithrough if not icomplete else max(through, ithrough)
            complete = complete and icomplete
        return SinceRead([t for t in sent if after < t.block_number <= through], through, complete,
                         max((b for b in cut if b <= through), default=None))

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
        return safe_int(result, 16)

    def head_block(self) -> int:
        """The chain's newest block number: one free-tier `proxy` request.

        Where a new watch starts reading, so that what moved after it was set
        is news and what came before is history."""
        result = self._request({"module": "proxy", "action": "eth_blockNumber"})
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
