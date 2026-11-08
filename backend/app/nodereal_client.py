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

import hashlib
import logging
import random
import threading
import time
from typing import Any, Iterable

import json

import httpx

from .api_budget import (ResponseCache, ResponseTooLarge, SharedPacer, TraceStopped, get_cache, get_pacer,
                         read_capped, spend)
from .api_budget import credential as meter_key
from .evidence import EvidenceLog

from . import config
from .etherscan_client import (
    _QUOTA_MESSAGES,
    EtherscanError,
    ProviderQuotaError,
    ProviderResponseError,
    SinceRead,
    Transaction,
    is_valid_address,
    normalize_address,
    resolve_decimals,
    split_page,
)

logger = logging.getLogger(__name__)

# nr_getAssetTransfers categories.
CATEGORY_NATIVE = "external"
CATEGORY_ERC20 = "20"

# Hard limits imposed by the API itself.
MAX_BLOCK_WINDOW = 100_000
MAX_COUNT = 1_000
# Raw records to read per address before giving up on filling the cap. The
# lookback already bounds the walk to a few windows, but a wallet that spams
# zero-value or failed transfers inside one window would otherwise be paged
# through in full, since only kept transfers count against the cap. Pages are
# sized to the trace cap (200 by default), so this is five pages.
MAX_SCAN = 1_000
# Pages one block window may take before the scan gives up on it (see _scan).
MAX_PAGES_PER_WINDOW = MAX_SCAN // 100 + 2

# NodeReal's transfer index trails the chain head by a few blocks, and asking
# for a block it has not indexed yet fails the whole query with "blockNum not
# reached". Measured at ~5 blocks; 32 is a cheap margin (~1.5 minutes on BSC)
# that costs nothing, since a trace is not interested in the last few seconds
# of chain history anyway. The retry below covers the margin being wrong.
INDEX_LAG_BLOCKS = 32

# A wallet quiet for longer than the lookback is found through its nonce: the
# count of transactions it has sent, readable at any past block. A binary search
# over blocks finds when it last sent (about 27 cheap calls), and history is
# read backwards from there for up to this many more windows. Only wallets the
# recent search found nothing for pay this; busy ones never do.
DEEP_WINDOWS = 20
# Which wallets may be deep-searched is named, not counted: the reported
# address (pipeline.run_trace calls allow_deep_search for it), never a hop. A
# shared count raced across the fetch threads -- every quiet wallet of a level
# passed it before the first search was recorded -- and which hops went deep,
# and so what deposit inference saw, depended on network timing. A trace whose
# every quiet hop went deep would take minutes, and a hop is already bounded by
# the time the funds arrived. A watch check never deep-searches.
# A wallet this client has seen receive funds is searched forward from the
# block they arrived in, for up to this many windows (~2.5 days at BSC's
# ~0.45 s blocks): a trace follows money only after it arrived, so that is
# the history that matters, and most of it moves on within days.
ARRIVAL_WINDOWS = 5
# Block windows one watch read walks forward before it stops and says so
# (~5 days at BSC's ~0.45 s blocks); the next check carries on from there.
SINCE_WINDOWS = 10
NOT_INDEXED = "not reached"

# Compute units per method (NodeReal's published table; others at 25). The
# pacer spaces requests by what they cost, in units of one transfer read.
METHOD_CU = {"nr_getAssetTransfers": 250, "eth_getTransactionCount": 25, "eth_blockNumber": 5}
TRANSFER_CU = METHOD_CU["nr_getAssetTransfers"]

# The fields of a transfer record _to_transaction reads; only these are cached.
TRANSFER_FIELDS = ("hash", "from", "to", "value", "decimal", "blockNum", "blockTimeStamp",
                   "receiptsStatus", "asset", "contractAddress")


def _block_of(raw: dict[str, Any]) -> int:
    value = raw.get("blockNum") or "0x0"
    try:
        return int(value, 16) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return 0


class NoderealError(EtherscanError):
    """Any non-recoverable problem talking to NodeReal.

    Subclasses EtherscanError so main.py's existing handling of upstream
    failures applies unchanged to BSC traces.
    """


class NoderealQuotaError(NoderealError, ProviderQuotaError):
    """NodeReal's monthly compute units are spent: not retried."""


class NoderealResponseError(NoderealError, ProviderResponseError):
    """NodeReal answered with a shape Exchequer cannot read."""


def _hex_int(value: Any) -> int:
    """A JSON-RPC hex quantity ("0x1a"), or NoderealResponseError."""
    if not isinstance(value, str):
        raise NoderealResponseError(f"NodeReal returned {type(value).__name__} where a hex number belongs")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise NoderealResponseError("NodeReal returned a number that is not hex") from exc


class NoderealClient:
    """Transaction source for BNB Smart Chain.

    Satisfies the same contract the graph builder relies on:
        client.get_outgoing_transactions(address) -> list[Transaction]
    """

    # The case's clock and request budget (api_budget.TraceBudget), set by
    # pipeline.run_trace; None outside a trace (scripts, the watcher).
    budget = None

    def __init__(
        self,
        api_key: str | None = None,
        chain_slug: str = "bsc-mainnet",
        native_symbol: str = "BNB",
        contract_addresses: Iterable[str] | None = None,
        asset_symbol: str | None = None,
        token_decimals: int | None = None,
        lookback_blocks: int | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_interval: float | None = None,  # None: paced by compute units (config.NODEREAL_CUPS*)
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.NODEREAL_API_KEY
        self.chain_slug = chain_slug
        self.native_symbol = native_symbol
        # When set, only these token contracts are followed. Empty means the
        # chain's native currency.
        self.contract_addresses = [normalize_address(a) for a in (contract_addresses or [])]
        self.asset_symbol = asset_symbol or native_symbol
        # The traced token's confirmed precision, used only when a record
        # omits its own.
        self.token_decimals = token_decimals
        # address -> (lowest, highest) block of a nonce-located deep search, and
        # address -> lowest block searched when nothing was found at all.
        self.deep_searched: dict[str, tuple[int, int]] = {}
        self.searched_from: dict[str, int] = {}
        self._send_ranges: dict[str, tuple[int, int] | None] = {}
        # Addresses a deep search may run for (allow_deep_search).
        self._deep_allowed: set[str] = set()
        # address -> earliest block this client has seen it receive in.
        self._arrived: dict[str, int] = {}
        # address -> whether its latest read stopped at a record or scan limit (history_capped).
        self._capped: dict[str, bool] = {}
        # One trace's fetch threads share this client: its per-trace state
        # (arrivals, searches, the head) is read and written under this lock.
        self._state_lock = threading.Lock()
        self.lookback_blocks = (
            lookback_blocks if lookback_blocks is not None else config.NODEREAL_LOOKBACK_BLOCKS
        )
        self.max_retries = max_retries

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self.evidence = EvidenceLog()
        self._head_block: int | None = None
        # NodeReal limits compute units per second per key, across every trace
        # using it. A client is built per trace, so a pacer per instance let four
        # concurrent traces send four times the rate: it is shared by key, as
        # Etherscan's is, and widens when the provider refuses. An explicit
        # `min_interval` spaces requests evenly instead (tests, scripts).
        self._per_cu = min_interval is None
        credential = hashlib.sha256((self.api_key or "anon").encode()).hexdigest()[:8]
        self._meter_key = meter_key(self.api_key)  # the key's allowance for the day
        if self._per_cu:
            interval = TRANSFER_CU / config.NODEREAL_CUPS_FLOOR
            floor = min(interval, TRANSFER_CU / config.NODEREAL_CUPS)
        else:
            interval = floor = min_interval
        self._pacer = get_pacer(f"nodereal:{credential}", lambda: SharedPacer(
            interval=interval, min_interval=floor, max_interval=max(interval * 6, 1.0)))
        # Answers about blocks at least INDEX_LAG_BLOCKS deep are history: a
        # re-trace of the same address, both directions and the deep search
        # read the same closed windows again (aligned, so the keys repeat).
        # Shared by every key: the answer is the chain's, not the caller's.
        self._cache = get_cache("nodereal:responses", lambda: ResponseCache(
            ttl_seconds=config.API_CACHE_TTL_SECONDS, path=config.API_CACHE_PATH,
            max_bytes=config.CACHE_SMALL_MEMORY_BYTES))

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
    def _throttle(self, method: str) -> None:
        """Wait for the key's shared schedule; a request's weight is its compute units."""
        self._pacer.wait(METHOD_CU.get(method, 25) / TRANSFER_CU if self._per_cu else 1.0)

    def _rpc(self, method: str, params: list[Any]) -> Any:
        if not self.api_key:
            raise NoderealError(
                "NODEREAL_API_KEY is not set. Add a free key from "
                "https://nodereal.io to backend/.env to trace this chain."
            )

        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        request_desc = (f"POST {self.url.split('/v1/')[0]}/v1/<key> {method} "
                        f"{json.dumps(params, sort_keys=True)}")
        cache_key = (self.chain_slug, method, json.dumps(params, sort_keys=True))
        cacheable = method != "eth_blockNumber"  # the tip is never history
        if cacheable:
            hit, cached = self._cache.get(cache_key)
            if hit:
                self.evidence.record_cached("nodereal", request_desc, self._cache.meta(cache_key), cached)
                return cached
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            # The case's clock and compute-unit budget, before every attempt.
            spend("nodereal", self._meter_key, METHOD_CU.get(method, 25), self.budget)
            self._throttle(method)
            try:
                response = read_capped(self._client, "POST", self.url, json=payload,
                                       **({"timeout": self.budget.timeout(20.0)} if self.budget else {}))
            except ResponseTooLarge as exc:
                raise NoderealResponseError(f"NodeReal response too large: {exc}") from exc
            except httpx.RequestError as exc:
                last_error = NoderealError(f"Network error contacting NodeReal: {exc}")
                self._backoff(attempt, str(exc))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = NoderealError(f"NodeReal returned HTTP {response.status_code}")
                if response.status_code == 429:
                    self._pacer.penalize()  # every trace on this key is going too fast
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise NoderealError(
                    f"NodeReal returned HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise NoderealResponseError(f"NodeReal returned non-JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise NoderealResponseError(f"NodeReal returned a JSON {type(body).__name__}, not an object")

            error = body.get("error")
            if error:
                # A JSON-RPC error is an object; a provider in trouble has sent a bare string.
                message = str(error.get("message", error)) if isinstance(error, dict) else str(error)
                # Rate limiting arrives as a JSON-RPC error, not an HTTP status.
                if any(phrase in message.lower() for phrase in _QUOTA_MESSAGES):
                    raise NoderealQuotaError(f"NodeReal quota spent: {message}")
                if "limit" in message.lower() or "too many" in message.lower():
                    last_error = NoderealError(f"NodeReal rate limit: {message}")
                    self._pacer.penalize()
                    self._backoff(attempt, "rate limit")
                    continue
                raise NoderealError(f"NodeReal error: {message}")

            rec = self.evidence.record("nodereal", request_desc, response.content)
            self._pacer.reward()
            result = body.get("result")
            ttl = self._cache_ttl(method, params, result) if cacheable else 0
            if ttl:
                self._cache.put(cache_key, self._slim(method, result), ttl=ttl, meta={
                    "sha256": rec.sha256, "retrieved_at": rec.retrieved_at, "bytes": rec.bytes})
            return result

        raise NoderealError(
            f"NodeReal request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _cache_ttl(self, method: str, params: list[Any], result: Any) -> float:
        """How long an answer may be reused. Every block this client asks
        about is at least INDEX_LAG_BLOCKS deep, so its answer is history; a
        window that reaches the head keeps for minutes, as it is the one
        whose key repeats only while the head stands still. A paged answer is
        not kept, since a page key may not outlive the query that made it.
        A null answer (a block or receipt the node does not have yet) is
        asked again next time."""
        if result is None:
            return 0
        if method == "nr_getAssetTransfers":
            query = params[0] if params and isinstance(params[0], dict) else {}
            if "pageKey" in query or not isinstance(result, dict) or result.get("pageKey"):
                return 0
            with self._state_lock:
                head = self._head_block
            to_block = int(query.get("toBlock", "0x0"), 16)
            return config.API_CACHE_TTL_SECONDS if head and to_block < head else config.API_CACHE_OPEN_TTL_SECONDS
        return config.API_CACHE_TTL_SECONDS  # nonces, receipts and blocks at a fixed past height

    @staticmethod
    def _slim(method: str, result: Any) -> Any:
        if method != "nr_getAssetTransfers" or not isinstance(result, dict):
            return result
        transfers = result.get("transfers")
        if not isinstance(transfers, list):
            return result
        return {**result, "transfers": [
            {k: t[k] for k in TRANSFER_FIELDS if k in t} if isinstance(t, dict) else t for t in transfers]}

    def _backoff(self, attempt: int, reason: str) -> None:
        if attempt >= self.max_retries:
            return  # nothing follows the last attempt to wait for
        delay = (0.4 * (2**attempt)) + random.uniform(0, 0.2)
        logger.warning("NodeReal retry %d/%d in %.2fs (%s)",
                       attempt + 1, self.max_retries, delay, reason)
        (self.budget.sleep(delay) if self.budget is not None else time.sleep(delay))

    def head_block(self) -> int:
        """Highest block safe to query, cached for the life of the client.

        This is the chain head less an indexing margin, not the head itself --
        see INDEX_LAG_BLOCKS.
        """
        with self._state_lock:
            if self._head_block is not None:
                return self._head_block
        tip = _hex_int(self._rpc("eth_blockNumber", []))
        with self._state_lock:
            if self._head_block is None:
                self._head_block = max(0, tip - INDEX_LAG_BLOCKS)
            return self._head_block

    # -- parsing -----------------------------------------------------------
    def _to_transaction(self, raw: dict[str, Any]) -> Transaction | None:
        """Convert one nr_getAssetTransfers record into our Transaction.

        Returns None for anything unusable so a single malformed record cannot
        abort a trace.
        """
        if not isinstance(raw, dict):
            return None
        try:
            to_raw = raw.get("to") or ""
            if not to_raw:
                return None

            raw_value = raw.get("value") or "0x0"
            units = int(raw_value, 16) if isinstance(raw_value, str) else int(raw_value)
            # The token states its own precision; never assume 18. Only the
            # native coin is 18 by definition -- a token record without one
            # falls back to the traced token's confirmed precision, or is
            # dropped rather than misstated.
            is_token = bool(raw.get("contractAddress"))
            decimals = resolve_decimals(
                raw.get("decimal"), self.token_decimals if is_token else 18
            )
            if decimals is None:
                logger.warning("Skipping NodeReal transfer with no known decimals: %r", raw)
                return None
            amount = units / (10**decimals)

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
        head = self.head_block()
        # The lookback's oldest block, inclusive: `lookback_blocks` blocks in all.
        # Rounded down to a window boundary, so every window but the newest is
        # a whole, aligned one whose answer a later trace can reuse.
        floor = max(0, head - self.lookback_blocks + 1) // MAX_BLOCK_WINDOW * MAX_BLOCK_WINDOW
        key = normalize_address(address)
        with self._state_lock:
            arrived = self._arrived.get(key)
        collected: list[Transaction] = []
        lowest = floor
        if direction_param == "fromAddress" and arrived is not None and arrived < floor:
            # Funds that arrived before the recent window: what the trace
            # follows is what moved after they arrived, so read that first. A
            # wallet that moved them on costs these windows only; the recent
            # search is skipped, since newer sends are not the traced money.
            top = min(floor - 1, arrived + ARRIVAL_WINDOWS * MAX_BLOCK_WINDOW)
            collected, capped = self._scan(address, direction_param, cap, top, arrived)
            lowest = arrived
        if not collected:
            collected, capped = self._scan(address, direction_param, cap, head, floor)
            lowest = min(lowest, floor)
        # Only a named address goes deep; and not one whose funds arrived inside
        # the recent window -- sends from before they arrived are not the
        # traced money, and the time rule would discard them anyway.
        with self._state_lock:
            deep = key in self._deep_allowed and (arrived is None or arrived < floor)
        if not collected and deep:
            sent = self.send_range(address)
            if sent is not None and sent[1] < floor:
                first, last = sent
                # Money arrives before it is sent on, so a search for what the
                # wallet received starts a little before its first send.
                start = first if direction_param == "fromAddress" else first - 2 * MAX_BLOCK_WINDOW
                lowest = max(0, start, last - DEEP_WINDOWS * MAX_BLOCK_WINDOW)
                collected, capped = self._scan(address, direction_param, cap, last, lowest)
                with self._state_lock:
                    self.deep_searched[key] = (lowest, last)
        with self._state_lock:
            self._capped[key] = capped
            if not collected:
                self.searched_from[key] = lowest
        return collected

    def history_capped(self, address: str) -> bool | None:
        """Whether the latest read of `address` stopped at its record or scan
        limit (zero-value spam counts toward the scan) with records unread;
        None if it has not been read."""
        with self._state_lock:
            return self._capped.get(normalize_address(address))

    def allow_deep_search(self, address: str) -> None:
        """Let a nonce-located deep search run for `address` if its recent
        history is empty. Called for the reported address only."""
        with self._state_lock:
            self._deep_allowed.add(normalize_address(address))

    def set_arrival(self, address: str, block: int) -> None:
        """Say when the traced funds reached `address` (a payment trace's first
        payment). Replaces what any scan noted: the intake's incoming read
        records the oldest inflow it saw, which can be other, older money, and
        reading the wallet's sends from there skipped the victim's."""
        with self._state_lock:
            self._arrived[normalize_address(address)] = block

    def get_incoming_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], bool]:
        """Every value-bearing transfer into `address` in a block range.

        Returns (transfers, complete). A range wider than DEEP_WINDOWS windows,
        or one holding more records than a scan reads, is reported incomplete
        rather than read in part.
        """
        if end_block - start_block > DEEP_WINDOWS * MAX_BLOCK_WINDOW:
            return [], False
        txs, capped = self._scan(address, "toAddress", MAX_SCAN, end_block, start_block)
        return txs, not capped

    def get_flows_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], list[Transaction], bool]:
        """Every value-bearing transfer into and out of `address` in a block range.

        For FIFO and LIBR (app/tracing_methods.py). Two scans, one per
        direction; complete only if both are. Same range limit as
        get_incoming_between.
        """
        if end_block - start_block > DEEP_WINDOWS * MAX_BLOCK_WINDOW:
            return [], [], False
        incoming, capped_in = self._scan(address, "toAddress", MAX_SCAN, end_block, start_block)
        outgoing, capped_out = self._scan(address, "fromAddress", MAX_SCAN, end_block, start_block)
        return incoming, outgoing, not (capped_in or capped_out)

    def _nonce(self, address: str, block: int) -> int:
        return _hex_int(self._rpc("eth_getTransactionCount", [normalize_address(address), hex(block)]))

    def send_range(self, address: str) -> tuple[int, int] | None:
        """Cached `_send_range` from the current head."""
        key = normalize_address(address)
        with self._state_lock:
            if key in self._send_ranges:
                return self._send_ranges[key]
        found = self._send_range(address, self.head_block())
        with self._state_lock:
            return self._send_ranges.setdefault(key, found)

    def _send_range(self, address: str, head: int) -> tuple[int, int] | None:
        """(block of first send, block of last send), or None if it never sent.

        Read from the nonce at past blocks, which needs an archive node; if the
        provider cannot answer, the wallet is treated as not found rather than
        failing the trace.
        """
        try:
            total = self._nonce(address, head)
            if total == 0:
                return None

            def first_block_with(count: int) -> int:
                lo, hi = 0, head
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if self._nonce(address, mid) >= count:
                        hi = mid
                    else:
                        lo = mid
                return hi

            last = first_block_with(total)
            first = first_block_with(1) if total > 1 else last
            return first, last
        except NoderealError as exc:
            logger.warning("Could not locate past sends for %s: %s", address, exc)
            return None

    def block_time(self, block: int) -> int | None:
        """A block's timestamp (s), for saying how far back a search reached."""
        try:
            return _hex_int(self._rpc("eth_getBlockByNumber", [hex(block), False])["timestamp"])
        except (NoderealError, TraceStopped, KeyError, TypeError, ValueError):
            return None  # a spent clock or budget costs only the date

    def _scan(self, address: str, direction_param: str, cap: int, top: int, floor: int,
              ) -> tuple[list[Transaction], bool]:
        """Transfers in blocks floor..top, newest first, in API-sized windows,
        and whether the read stopped at a limit rather than at the range's end
        (returned, not kept on the client: the fetch threads share it)."""
        category = [CATEGORY_ERC20] if self.contract_addresses else [CATEGORY_NATIVE]
        collected: list[Transaction] = []
        scanned = 0
        window_end = top

        guard_stopped = False
        while window_end >= floor and len(collected) < cap and scanned < MAX_SCAN and not guard_stopped:
            # Windows end on fixed boundaries (multiples of the API's maximum),
            # not relative to the head, so the same block range is the same
            # request -- and the same cached answer -- from one trace to the next.
            window_start = max(floor, window_end - window_end % MAX_BLOCK_WINDOW)
            page_key: str | None = None
            seen_keys: set[str] = set()
            pages = 0

            while len(collected) < cap and scanned < MAX_SCAN:
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
                    with self._state_lock:
                        self._head_block = min(self._head_block or window_end, window_end)
                    params["toBlock"] = hex(window_end)
                    result = self._rpc("nr_getAssetTransfers", [params]) or {}
                transfers = (result.get("transfers") or []) if isinstance(result, dict) else None
                if not isinstance(transfers, list):
                    raise NoderealResponseError("NodeReal returned transfers in an unexpected shape")
                scanned += len(transfers)
                for raw in transfers:
                    tx = self._to_transaction(raw)
                    # Only value-bearing, successful transfers are evidence of
                    # money moving; the rest is noise the trace must not follow.
                    if tx and not tx.is_error and tx.value_wei > 0:
                        collected.append(tx)
                        if tx.to_address:
                            with self._state_lock:
                                seen = self._arrived.get(tx.to_address)
                                self._arrived[tx.to_address] = (min(seen, tx.block_number) if seen
                                                                else tx.block_number)

                pages += 1
                page_key = result.get("pageKey")
                if not page_key:
                    break
                if not isinstance(page_key, str):
                    raise NoderealResponseError("NodeReal returned a page key that is not a string")
                # An empty page that still offers more, a key seen before, or
                # more pages than the scan ceiling allows: the provider is not
                # converging. Stop, and mark the read incomplete so "sent
                # nothing" is never claimed from it.
                if not transfers or page_key in seen_keys or pages >= MAX_PAGES_PER_WINDOW:
                    guard_stopped = True
                    break
                seen_keys.add(page_key)

            window_end = window_start - 1

        # Whether the read stopped at a limit rather than at the range's end.
        capped = len(collected) >= cap or scanned >= MAX_SCAN or guard_stopped
        return collected[:cap], capped

    def read_outgoing_since(self, address: str, after: int, limit: int) -> SinceRead:
        """What `address` sent after block `after`, oldest first, for a watch.

        Walks forward from after+1 to the indexed head in API-sized windows,
        at most SINCE_WINDOWS of them, one ascending page each. Never runs
        the nonce search a trace uses for quiet wallets: a dormant watched
        wallet costs the head read and a window or two. A page that is one
        block alone is followed through that block, so nothing in it after
        the page counts as read unseen."""
        if not is_valid_address(address):
            raise ValueError(f"Not a valid EVM address: {address!r}")
        head = self.head_block()
        category = [CATEGORY_ERC20] if self.contract_addresses else [CATEGORY_NATIVE]
        sent: list[Transaction] = []
        start, through = int(after) + 1, int(after)
        for _ in range(SINCE_WINDOWS):
            if start > head:
                return SinceRead(sent, through, True)
            end = min(head, start + MAX_BLOCK_WINDOW - 1)
            params: dict[str, Any] = {
                "category": category, "fromBlock": hex(start), "toBlock": hex(end),
                "fromAddress": normalize_address(address),
                "maxCount": hex(min(MAX_COUNT, limit)), "order": "asc",
            }
            if self.contract_addresses:
                params["contractAddresses"] = self.contract_addresses
            try:
                raws, page_key = self._since_page(params)
            except NoderealError as exc:
                # The index is further behind than its margin: step back, as _scan does.
                if NOT_INDEXED not in str(exc).lower() or end <= start:
                    raise
                end = head = max(start, end - 256)
                self._head_block = min(self._head_block or end, end)
                params["toBlock"] = hex(end)
                raws, page_key = self._since_page(params)
            if page_key and not raws:
                # "More" with nothing on the page: the window was not read.
                raise NoderealError("NodeReal offered more transfers but returned none")
            if page_key:
                # More in this window than one page: stop inside it.
                blocks = [_block_of(r) for r in raws]
                through, _ = split_page(blocks, after, full=True)
                cut = None
                if min(blocks) == max(blocks):
                    raws, whole = self._whole_block(params, blocks[0])
                    through, cut = blocks[0], (None if whole else blocks[0])
                sent += self._kept(raws)
                return SinceRead([t for t in sent if t.block_number <= through], max(through, after), False, cut)
            sent += self._kept(raws)
            through, start = end, end + 1
            if len(sent) >= limit:
                break
        return SinceRead(sent, through, start > head)

    def _since_page(self, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        """One page for a watch read: (records, pageKey). An answer that is no
        transfer list is a failed read, never an empty one: read as empty it
        would move the watch's cursor over blocks nobody read."""
        result = self._rpc("nr_getAssetTransfers", [params])
        if not isinstance(result, dict):
            raise NoderealError("NodeReal returned no transfer list")
        return [r for r in (result.get("transfers") or []) if isinstance(r, dict)], result.get("pageKey")

    def _whole_block(self, params: dict[str, Any], block: int) -> tuple[list[dict[str, Any]], bool]:
        """Every record of one block the address sent, page after page, and
        whether that was all of them (False: the pages ran out first)."""
        query = {**params, "fromBlock": hex(block), "toBlock": hex(block), "maxCount": hex(MAX_COUNT)}
        raws: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _ in range(MAX_PAGES_PER_WINDOW):
            page, key = self._since_page(query)
            raws += page
            if not key:
                return raws, True
            if not page or key in seen:
                break
            seen.add(key)
            query["pageKey"] = key
        return raws, False

    def _kept(self, raws: list[dict[str, Any]]) -> list[Transaction]:
        txs = (self._to_transaction(r) for r in raws)
        return [t for t in txs if t and not t.is_error and t.value_wei > 0]

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        """One transaction's receipt and event logs, for reading swap outputs."""
        result = self._rpc("eth_getTransactionReceipt", [tx_hash])
        return result if isinstance(result, dict) else None

    def get_transactions(self, address: str, limit: int | None = None, sort: str = "desc"):
        """Present for interface parity; callers pick a direction explicitly."""
        return self.get_outgoing_transactions(address, limit=limit)
