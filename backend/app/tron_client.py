"""Tron data provider, backed by TronGrid.

Tron matters disproportionately for this problem statement. TRM Labs measured
58% of 2024 illicit crypto volume on Tron, and the UN Office on Drugs and Crime
describes USDT on Tron as the "preferred choice" of the Southeast-Asian
cyber-fraud operations that target Indian victims (sources in RESEARCH.md).
Transfers are cheap and fast, and a fraud tool that cannot follow a `T...`
address cannot follow a case it is very likely to be handed.

Tron is not an EVM chain, and three differences drive this module:

  * Addresses are Base58 beginning with 'T', and they are CASE-SENSITIVE.
    Lowercasing one does not yield another spelling of the same address, it
    yields a string that is not an address -- so nothing here normalises case.
  * TRX and USDT-TRC20 both use 6 decimals, not 18. The token's own
    `token_info.decimals` is used rather than any assumption.
  * There is no block-range limit to work around. TronGrid paginates with an
    opaque `fingerprint`, so full history is reachable -- unlike BSC, where
    coverage is a bounded recent window.

TronGrid serves requests without an API key at a low rate limit, which is
enough for a demo. A free key raises the limit and is sent as TRON-PRO-API-KEY.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from typing import Any, Callable

import httpx

from .api_budget import ResponseCache, ResponseTooLarge, SharedPacer, get_cache, get_pacer, read_capped
from .evidence import EvidenceLog

from . import config
from .etherscan_client import (EtherscanError, ProviderResponseError, SinceRead, Transaction, is_tron_address,
                               resolve_decimals, split_page)

logger = logging.getLogger(__name__)

TRONGRID_BASE = "https://api.trongrid.io"
# TRX is denominated in "sun": 1 TRX = 1,000,000 sun.
SUN_PER_TRX = 1_000_000

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# Mainnet address prefix. A raw Tron address is 21 bytes beginning 0x41.
TRON_ADDRESS_PREFIX = 0x41


def hex_to_base58(raw: str) -> str:
    """Convert a Tron hex address (41…) to its Base58Check form (T…).

    Tron presents the same address two ways, and the two endpoints this client
    uses disagree: the TRC-20 endpoint returns Base58 ("T…"), while raw
    transaction data returns 21-byte hex ("41…"). Left unconverted, a native
    TRX trace produces nodes that no label file can ever match and that fail
    address validation on the next hop.

    Base58Check = payload + first 4 bytes of the double SHA-256 of the payload,
    encoded in an alphabet that omits 0, O, I and l.
    """
    value = raw.strip()
    if not value or value.startswith("T"):
        return value  # already Base58
    if value.startswith("0x"):
        value = value[2:]
    try:
        payload = bytes.fromhex(value)
    except ValueError:
        return raw
    if not payload or payload[0] != TRON_ADDRESS_PREFIX:
        return raw

    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(payload + checksum, "big")

    encoded = ""
    while number > 0:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    #每 leading zero byte is one leading '1' in Base58.
    for byte in payload + checksum:
        if byte != 0:
            break
        encoded = "1" + encoded
    return encoded
# TronGrid's per-page maximum.
MAX_PAGE = 200
# How many raw records to read per address before giving up on filling the
# cap. The native endpoint returns every transaction the account signed, and
# on a busy wallet almost none of those are TRX transfers, so counting only
# the records we keep would page through the whole history (observed: a
# wallet that paginated for minutes and never finished). Five pages is the
# same budget as one fully-kept page on Etherscan, five times over.
MAX_SCAN = MAX_PAGE * 5
# A time range that ended this long ago is settled history: Tron solidifies a
# block in about a minute, and only confirmed records are read.
SETTLED_SECONDS = 300

# The fields the parsers read; a cached record keeps only these.
TRC20_FIELDS = ("type", "token_info", "value", "transaction_id", "from", "to", "block_timestamp")
TOKEN_INFO_FIELDS = ("address", "decimals", "symbol")
NATIVE_FIELDS = ("txID", "block_timestamp", "blockNumber")
TRANSFER_VALUE_FIELDS = ("amount", "to_address", "owner_address")


def _slim_trc20(raw: Any) -> Any:
    """A /transactions/trc20 record cut to what _token_transfer reads."""
    if not isinstance(raw, dict):
        return raw
    slim = {k: raw[k] for k in TRC20_FIELDS if k in raw}
    info = slim.get("token_info")
    if isinstance(info, dict):
        slim["token_info"] = {k: info[k] for k in TOKEN_INFO_FIELDS if k in info}
    return slim


def _slim_native(raw: Any) -> Any:
    """A /transactions record cut to what _native_transfer reads. Anything
    not TransferContract keeps only its type (it still counts as scanned);
    a record of a shape the parser would not read is kept as it came."""
    if not isinstance(raw, dict):
        return raw
    try:
        contract = raw["raw_data"]["contract"][0]
        kind = contract.get("type")
    except (KeyError, IndexError, TypeError, AttributeError):
        return raw
    if kind != "TransferContract":
        return {"raw_data": {"contract": [{"type": kind}]}}
    param = contract.get("parameter")
    value = param.get("value") if isinstance(param, dict) else None
    if not isinstance(value, dict):
        return raw
    slim = {k: raw[k] for k in NATIVE_FIELDS if k in raw}
    if "ret" in raw:
        slim["ret"] = raw["ret"][:1] if isinstance(raw["ret"], list) else raw["ret"]
    slim["raw_data"] = {"contract": [{"type": kind, "parameter": {
        "value": {k: value[k] for k in TRANSFER_VALUE_FIELDS if k in value}}}]}
    return slim


class TronError(EtherscanError):
    """Any non-recoverable problem talking to TronGrid.

    Subclasses EtherscanError so main.py's existing upstream-failure handling
    applies to Tron traces unchanged.
    """


class TronResponseError(TronError, ProviderResponseError):
    """TronGrid answered with a shape Exchequer cannot read."""


def _page(body: dict[str, Any]) -> tuple[list[Any], str | None]:
    """(records, next fingerprint) of one TronGrid page, or TronResponseError."""
    records = body.get("data") or []
    meta = body.get("meta") or {}
    fingerprint = meta.get("fingerprint") if isinstance(meta, dict) else None
    if not isinstance(records, list) or not isinstance(meta, dict) or not isinstance(fingerprint, (str, type(None))):
        raise TronResponseError("TronGrid returned a page in an unexpected shape")
    return records, fingerprint or None


class TronClient:
    """Transaction source for Tron.

    Satisfies the contract the graph builder relies on:
        client.get_outgoing_transactions(address) -> list[Transaction]
    """

    # The case's wall clock (api_budget.TraceBudget), set by pipeline.run_trace;
    # None outside a trace (scripts, the watcher).
    budget = None

    def __init__(
        self,
        api_key: str | None = None,
        contract_address: str | None = None,
        asset_symbol: str = "TRX",
        base_url: str = TRONGRID_BASE,
        timeout: float = 30.0,
        max_retries: int = 3,
        min_interval: float | None = None,
        client: httpx.Client | None = None,
        token_decimals: int | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.TRONGRID_API_KEY
        # When set, this TRC-20 contract is followed instead of native TRX.
        self.contract_address = contract_address
        self.asset_symbol = asset_symbol
        # The traced token's confirmed precision (config), as on the EVM chains.
        self.token_decimals = token_decimals
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        # Without a key TronGrid rate-limits aggressively (observed: 429 within
        # a handful of consecutive requests), so the keyless default is
        # deliberately slow. A key raises the ceiling and the pace with it.
        if min_interval is not None:
            self.min_interval = min_interval
        else:
            self.min_interval = 0.2 if self.api_key else 1.2

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["TRON-PRO-API-KEY"] = self.api_key

        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, headers=headers)
        self.evidence = EvidenceLog()
        # TronGrid limits requests per key (or per IP without one) across every
        # trace, so the pacer is shared by credential and widens on refusal; a
        # pacer per instance let four keyless traces send four times the rate.
        credential = hashlib.sha256(self.api_key.encode()).hexdigest()[:8] if self.api_key else "anon"
        interval = self.min_interval
        self._pacer = get_pacer(f"trongrid:{credential}", lambda: SharedPacer(
            interval=interval, min_interval=interval, max_interval=max(interval * 5, 6.0)))
        # Re-traces, both directions and follow-ons read the same pages again.
        # Shared by every key: the answer is the chain's, not the caller's.
        self._cache = get_cache("trongrid:responses", lambda: ResponseCache(
            ttl_seconds=config.API_CACHE_TTL_SECONDS, path=config.API_CACHE_PATH,
            max_bytes=config.CACHE_SMALL_MEMORY_BYTES))

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TronClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------
    def _throttle(self) -> None:
        self._pacer.wait()

    def _describe(self, path: str, params: dict[str, Any]) -> str:
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"GET {self.base_url}{path}?{query}"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._send("GET", path, self._describe(path, params), params=params)[0]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", path, f"POST {self.base_url}{path} {json.dumps(payload, sort_keys=True)}",
                          json=payload)[0]

    def _send(self, method: str, path: str, request_desc: str, **kwargs: Any) -> tuple[dict[str, Any], Any]:
        """(body, its evidence record)."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if self.budget is not None:
                self.budget.check()  # the case's wall clock, before every attempt
            self._throttle()
            try:
                response = read_capped(self._client, method, f"{self.base_url}{path}", **kwargs,
                                       **({"timeout": self.budget.timeout(20.0)} if self.budget else {}))
            except ResponseTooLarge as exc:
                raise TronResponseError(f"TronGrid response too large: {exc}") from exc
            except httpx.RequestError as exc:
                last_error = TronError(f"Network error contacting TronGrid: {exc}")
                self._backoff(attempt, str(exc))
                continue

            if response.status_code in (429, 403) or response.status_code >= 500:
                # 403 here means the free rate limit, not a bad key.
                last_error = TronError(f"TronGrid returned HTTP {response.status_code}")
                if response.status_code in (429, 403):
                    self._pacer.penalize()  # every trace on this key is going too fast
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise TronError(
                    f"TronGrid returned HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise TronResponseError(f"TronGrid returned non-JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise TronResponseError(f"TronGrid returned a JSON {type(body).__name__}, not an object")

            if body.get("success") is False:
                raise TronError(f"TronGrid error: {str(body.get('error'))[:200]}")
            rec = self.evidence.record("trongrid", request_desc, response.content)
            self._pacer.reward()
            return body, rec

        raise TronError(
            f"TronGrid request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _read_pages(self, path: str, params: dict[str, Any], scope: Any, ttl: float,
                    take: Callable[[list[Any], bool], bool]) -> None:
        """Page through one read, handing each page's records to `take` with
        whether more follow; `take` says whether to go on.

        The read is cached whole -- every page it took, under its first
        request and `scope` (what else decides where `take` stops) -- or not
        at all: a fingerprint belongs to the read that made it, so a cached
        first page is never followed by a live one. A hit replays the pages
        as cached evidence, each with its own request and original hash."""
        slim = _slim_trc20 if self.contract_address else _slim_native
        key = (self.base_url, path, json.dumps(params, sort_keys=True), json.dumps(scope))
        hit, pages = self._cache.get(key)
        if hit and isinstance(pages, list):
            for page in pages:
                self.evidence.record_cached("trongrid", page["request"], page["meta"])
                if not take(page["data"], page["more"]):
                    break
            return
        params, pages = dict(params), []
        while True:
            request_desc = self._describe(path, params)
            body, rec = self._send("GET", path, request_desc, params=dict(params))
            records, fingerprint = _page(body)
            more = bool(fingerprint and records)
            pages.append({"request": request_desc, "data": [slim(r) for r in records], "more": more,
                          "meta": {"sha256": rec.sha256, "retrieved_at": rec.retrieved_at, "bytes": rec.bytes}})
            if not take(records, more):
                break
            params["fingerprint"] = fingerprint
        self._cache.put(key, pages, ttl=ttl)

    def _backoff(self, attempt: int, reason: str) -> None:
        if attempt >= self.max_retries:
            return  # nothing follows the last attempt to wait for
        delay = (0.5 * (2**attempt)) + random.uniform(0, 0.25)
        logger.warning("TronGrid retry %d/%d in %.2fs (%s)",
                       attempt + 1, self.max_retries + 1, delay, reason)
        (self.budget.sleep(delay) if self.budget is not None else time.sleep(delay))

    # -- parsing -----------------------------------------------------------
    def _token_transfer(self, raw: dict[str, Any]) -> Transaction | None:
        """One TRC-20 transfer from /transactions/trc20, or None.

        That endpoint also returns approval records (`type` "Approval"): an
        approve() moves nothing, but read as a transfer it became an edge of
        up to 2**256-1 units to the spender. Only rows that do not say they
        are something else are transfers, and only of the token asked for."""
        if not isinstance(raw, dict) or raw.get("type", "Transfer") != "Transfer":
            return None
        try:
            info = raw.get("token_info") or {}
            if not isinstance(info, dict):
                return None
            token = info.get("address")
            if self.contract_address and token and token != self.contract_address:
                return None
            # ADR-0008: the record's own figure, else the configured one, else
            # drop it -- never a guess. A stated figure that disagrees with the
            # configured precision of the traced token is not trusted either.
            decimals = resolve_decimals(info.get("decimals"), self.token_decimals)
            if decimals is None or (self.token_decimals is not None and decimals != self.token_decimals):
                logger.warning("Skipping TRC-20 record with unknown or unexpected decimals: %r", str(raw)[:120])
                return None
            units = int(raw.get("value", "0") or "0")
            return Transaction(
                hash=raw.get("transaction_id", ""),
                from_address=(raw.get("from") or "").strip(),
                to_address=(raw.get("to") or "").strip() or None,
                value_native=units / (10**decimals),
                value_wei=units,
                # TronGrid reports milliseconds; the rest of Exchequer uses seconds.
                timestamp=int(raw.get("block_timestamp", 0)) // 1000,
                block_number=0,  # not returned by this endpoint
                is_error=False,
                asset=info.get("symbol") or self.asset_symbol,
                contract_address=info.get("address") or self.contract_address,
            )
        except (TypeError, ValueError, AttributeError):
            logger.warning("Skipping malformed TRC-20 transfer: %r", str(raw)[:120])
            return None

    def _native_transfer(self, raw: dict[str, Any]) -> Transaction | None:
        """One native TRX transfer from /transactions.

        Tron wraps every operation in a contract object; only TransferContract
        moves TRX. Anything else (token transfers, staking, votes, contract
        calls) is skipped rather than counted as a payment.
        """
        if not isinstance(raw, dict):
            return None
        try:
            contracts = (raw.get("raw_data") or {}).get("contract") or []
            if not contracts:
                return None
            contract = contracts[0]
            if contract.get("type") != "TransferContract":
                return None
            value = ((contract.get("parameter") or {}).get("value")) or {}

            # A failed transaction moved nothing.
            results = raw.get("ret") or [{}]
            succeeded = str(results[0].get("contractRet", "SUCCESS")) == "SUCCESS"

            units = int(value.get("amount", 0) or 0)
            recipient = value.get("to_address")
            return Transaction(
                hash=raw.get("txID", ""),
                from_address=hex_to_base58(value.get("owner_address", "")),
                to_address=hex_to_base58(recipient) if recipient else None,
                value_native=units / SUN_PER_TRX,
                value_wei=units,
                timestamp=int(raw.get("block_timestamp", 0)) // 1000,
                block_number=int(raw.get("blockNumber", 0) or 0),
                is_error=not succeeded,
                asset="TRX",
                contract_address=None,
            )
        except (TypeError, ValueError, IndexError, KeyError, AttributeError):
            logger.warning("Skipping malformed TRX transfer: %r", str(raw)[:120])
            return None

    # -- public API --------------------------------------------------------
    def get_outgoing_transactions(
        self, address: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers sent *by* `address`, newest first."""
        return self._get_directional_transactions(address, "only_from", limit)

    def get_incoming_transactions(
        self, address: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers received *by* `address`, newest first.

        What a reverse trace follows: which addresses funded this one.
        """
        return self._get_directional_transactions(address, "only_to", limit)

    def get_outgoing_transactions_since_time(
        self, address: str, since_ts: int, limit: int | None = None
    ) -> list[Transaction]:
        """The first transfers `address` sent at or after `since_ts` (s), oldest first.

        The Tron counterpart of the Etherscan read from a block: TRC-20
        transfers carry no block number, so the read starts from when the
        traced funds arrived instead. The graph builder asks for it only when
        the newest page did not reach back that far.
        """
        return self._get_directional_transactions(address, "only_from", limit, since_ts=since_ts)

    def get_incoming_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], bool]:
        """Every value-bearing transfer into `address` between two times (s).

        TronGrid filters by timestamp, not block. Returns (transfers, complete);
        complete is False if the window held more than MAX_SCAN records.
        """
        return self._between(address, "only_to", start_ts, end_ts)

    def get_flows_between(
        self, address: str, start_block: int, end_block: int, start_ts: int, end_ts: int,
    ) -> tuple[list[Transaction], list[Transaction], bool]:
        """Every value-bearing transfer into and out of `address` between two times (s).

        For FIFO and LIBR (app/tracing_methods.py). Two reads, one per
        direction; complete only if both are.
        """
        incoming, complete_in = self._between(address, "only_to", start_ts, end_ts)
        outgoing, complete_out = self._between(address, "only_from", start_ts, end_ts)
        return incoming, outgoing, complete_in and complete_out

    def _between(self, address: str, direction_param: str, start_ts: int, end_ts: int,
                 ) -> tuple[list[Transaction], bool]:
        """Transfers one way between two times, oldest first; (transfers, complete)."""
        if self.contract_address:
            path, parse = f"/v1/accounts/{address}/transactions/trc20", self._token_transfer
        else:
            path, parse = f"/v1/accounts/{address}/transactions", self._native_transfer
        # only_confirmed: TronGrid otherwise also returns records not yet in
        # a block, which evidence must never rest on.
        params: dict[str, Any] = {direction_param: "true", "only_confirmed": "true",
                                  "limit": MAX_PAGE, "order_by": "block_timestamp,asc",
                                  "min_timestamp": start_ts * 1000, "max_timestamp": end_ts * 1000}
        if self.contract_address:
            params["contract_address"] = self.contract_address

        def ours(tx: Transaction) -> bool:
            return (tx.to_address == address) if direction_param == "only_to" else (tx.from_address == address)

        collected: list[Transaction] = []
        scanned = 0
        complete = False

        def take(records: list[Any], more: bool) -> bool:
            nonlocal scanned, complete
            scanned += len(records)
            for raw in records:
                tx = parse(raw)
                if tx and ours(tx) and not tx.is_error and tx.value_wei > 0:
                    collected.append(tx)
            complete = not more
            return more and scanned < MAX_SCAN

        # A range that ended a few minutes ago is history and keeps the day;
        # one reaching the last minutes may still gain records.
        settled = end_ts <= time.time() - SETTLED_SECONDS
        ttl = config.API_CACHE_TTL_SECONDS if settled else config.API_CACHE_OPEN_TTL_SECONDS
        self._read_pages(path, params, ["between", self.token_decimals], ttl, take)
        return collected, complete

    def _get_directional_transactions(
        self, address: str, direction_param: str, limit: int | None = None,
        since_ts: int | None = None,
    ) -> list[Transaction]:
        """Transfers with `address` at one end, newest first -- or, with
        `since_ts`, oldest first from that time (s).

        `direction_param` is TronGrid's own filter flag -- `only_from` for
        transfers sent, `only_to` for transfers received. Pushing the filter to
        the server means we pay for exactly the records the trace follows
        rather than filtering a mixed page locally.
        """
        if not is_tron_address(address):
            raise ValueError(f"Not a valid Tron address: {address!r}")

        cap = limit or config.TRACE_MAX_TXS_PER_ADDRESS
        collected: list[Transaction] = []

        if self.contract_address:
            path = f"/v1/accounts/{address}/transactions/trc20"
            parse = self._token_transfer
        else:
            path = f"/v1/accounts/{address}/transactions"
            parse = self._native_transfer

        # The page size must stay identical across pages: a fingerprint is only
        # valid for the exact parameter set that produced it, and shrinking the
        # limit as results accumulate makes TronGrid reject the next page with
        # "fingerprint does not match current set of params".
        page_size = min(MAX_PAGE, cap)
        scanned = 0
        params: dict[str, Any] = {
            direction_param: "true",
            "only_confirmed": "true",  # never unconfirmed records (see _between)
            "limit": page_size,
            "order_by": "block_timestamp,desc" if since_ts is None else "block_timestamp,asc",
        }
        if since_ts is not None:
            params["min_timestamp"] = int(since_ts) * 1000
        if self.contract_address:
            params["contract_address"] = self.contract_address

        def take(records: list[Any], more: bool) -> bool:
            nonlocal scanned
            scanned += len(records)
            for raw in records:
                tx = parse(raw)
                # Only successful, value-bearing transfers are evidence of money
                # moving; the rest is noise the trace must not follow.
                if tx and tx.to_address and not tx.is_error and tx.value_wei > 0:
                    collected.append(tx)
            return more and len(collected) < cap and scanned < MAX_SCAN

        # Both read up to the newest records, which keep coming: minutes only.
        self._read_pages(path, params, ["directional", cap, self.token_decimals],
                         config.API_CACHE_OPEN_TTL_SECONDS, take)
        return collected[:cap]

    def is_contract(self, address: str) -> bool | None:
        """Whether `address` holds contract bytecode: True, False, or None when
        TronGrid could not say. What ADR-0006 asks of a label before it can
        name an exchange; the live TronScan tags are held to it too."""
        if not is_tron_address(address):
            return None
        try:
            body = self._post("/wallet/getcontract", {"value": address, "visible": True})
        except TronError as exc:
            logger.warning("Could not read whether %s is a contract: %s", address, type(exc).__name__)
            return None
        if body.get("Error"):
            return None
        return bool(body.get("bytecode"))

    def read_outgoing_since(self, address: str, after: int, limit: int) -> SinceRead:
        """What `address` sent after `after` (Unix seconds), oldest first, for a watch.

        Confirmed records only, ascending from after+1 s, page after page until
        `limit` transfers (and past the first second) or MAX_SCAN records.
        Every record read counts toward `through` -- failed and zero-value
        ones too, so a burst of dust can neither hide a transfer nor hold the
        cursor back."""
        if not is_tron_address(address):
            raise ValueError(f"Not a valid Tron address: {address!r}")
        if self.contract_address:
            path, parse = f"/v1/accounts/{address}/transactions/trc20", self._token_transfer
        else:
            path, parse = f"/v1/accounts/{address}/transactions", self._native_transfer
        params: dict[str, Any] = {"only_from": "true", "only_confirmed": "true",
                                  "limit": min(MAX_PAGE, limit), "order_by": "block_timestamp,asc",
                                  "min_timestamp": (int(after) + 1) * 1000}
        if self.contract_address:
            params["contract_address"] = self.contract_address
        sent: list[Transaction] = []
        stamps: list[int] = []
        cut = None
        while True:
            body = self._get(path, params)
            records = [r for r in (body.get("data") or []) if isinstance(r, dict)]
            stamps += [int(r.get("block_timestamp") or 0) // 1000 for r in records]
            for raw in records:
                tx = parse(raw)
                if tx and tx.to_address and not tx.is_error and tx.value_wei > 0:
                    sent.append(tx)
            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if not fingerprint or not records:
                through, complete = split_page(stamps, after, full=False)
                break
            # Stop at the limit only once the read has left its first second:
            # a second filled by one block's sends is read to its end.
            if (len(sent) >= limit and min(stamps) != max(stamps)) or len(stamps) >= MAX_SCAN:
                through, complete = split_page(stamps, after, full=True)
                if min(stamps) == max(stamps):
                    cut = through  # one second held more than MAX_SCAN records
                break
            params["fingerprint"] = fingerprint
        return SinceRead([t for t in sent if after < t.timestamp <= through], through, complete, cut)

    def get_transactions(self, address: str, limit: int | None = None, sort: str = "desc"):
        """Present for interface parity; callers pick a direction explicitly."""
        return self.get_outgoing_transactions(address, limit=limit)
