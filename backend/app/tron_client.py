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
import logging
import random
import threading
import time
from typing import Any

import httpx

from .evidence import EvidenceLog

from . import config
from .etherscan_client import EtherscanError, Transaction, is_tron_address

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


class TronError(EtherscanError):
    """Any non-recoverable problem talking to TronGrid.

    Subclasses EtherscanError so main.py's existing upstream-failure handling
    applies to Tron traces unchanged.
    """


class TronClient:
    """Transaction source for Tron.

    Satisfies the contract the graph builder relies on:
        client.get_outgoing_transactions(address) -> list[Transaction]
    """

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
    ) -> None:
        self.api_key = api_key if api_key is not None else config.TRONGRID_API_KEY
        # When set, this TRC-20 contract is followed instead of native TRX.
        self.contract_address = contract_address
        self.asset_symbol = asset_symbol
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
        self._lock = threading.Lock()
        self._last_request_at = 0.0

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
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_at = time.monotonic()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = self._client.get(f"{self.base_url}{path}", params=params)
            except httpx.RequestError as exc:
                last_error = TronError(f"Network error contacting TronGrid: {exc}")
                self._backoff(attempt, str(exc))
                continue

            if response.status_code in (429, 403) or response.status_code >= 500:
                # 403 here means the free rate limit, not a bad key.
                last_error = TronError(f"TronGrid returned HTTP {response.status_code}")
                self._backoff(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                raise TronError(
                    f"TronGrid returned HTTP {response.status_code}: {response.text[:200]}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise TronError(f"TronGrid returned non-JSON: {exc}") from exc

            if body.get("success") is False:
                raise TronError(f"TronGrid error: {str(body.get('error'))[:200]}")
            query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            self.evidence.record("trongrid", f"GET {self.base_url}{path}?{query}", response.content)
            return body

        raise TronError(
            f"TronGrid request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _backoff(self, attempt: int, reason: str) -> None:
        delay = (0.5 * (2**attempt)) + random.uniform(0, 0.25)
        logger.warning("TronGrid retry %d/%d in %.2fs (%s)",
                       attempt + 1, self.max_retries + 1, delay, reason)
        time.sleep(delay)

    # -- parsing -----------------------------------------------------------
    def _token_transfer(self, raw: dict[str, Any]) -> Transaction | None:
        """One TRC-20 transfer from /transactions/trc20."""
        try:
            info = raw.get("token_info") or {}
            decimals = int(info.get("decimals", 6))
            units = int(raw.get("value", "0") or "0")
            return Transaction(
                hash=raw.get("transaction_id", ""),
                from_address=(raw.get("from") or "").strip(),
                to_address=(raw.get("to") or "").strip() or None,
                value_native=units / (10**decimals) if decimals >= 0 else float(units),
                value_wei=units,
                # TronGrid reports milliseconds; the rest of TraceChain uses seconds.
                timestamp=int(raw.get("block_timestamp", 0)) // 1000,
                block_number=0,  # not returned by this endpoint
                is_error=False,
                asset=info.get("symbol") or self.asset_symbol,
                contract_address=info.get("address") or self.contract_address,
            )
        except (TypeError, ValueError):
            logger.warning("Skipping malformed TRC-20 transfer: %r", raw)
            return None

    def _native_transfer(self, raw: dict[str, Any]) -> Transaction | None:
        """One native TRX transfer from /transactions.

        Tron wraps every operation in a contract object; only TransferContract
        moves TRX. Anything else (token transfers, staking, votes, contract
        calls) is skipped rather than counted as a payment.
        """
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
        except (TypeError, ValueError, IndexError):
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

    def _get_directional_transactions(
        self, address: str, direction_param: str, limit: int | None = None
    ) -> list[Transaction]:
        """Transfers with `address` at one end, newest first.

        `direction_param` is TronGrid's own filter flag -- `only_from` for
        transfers sent, `only_to` for transfers received. Pushing the filter to
        the server means we pay for exactly the records the trace follows
        rather than filtering a mixed page locally.
        """
        if not is_tron_address(address):
            raise ValueError(f"Not a valid Tron address: {address!r}")

        cap = limit or config.TRACE_MAX_TXS_PER_ADDRESS
        collected: list[Transaction] = []
        fingerprint: str | None = None

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

        while len(collected) < cap:
            params: dict[str, Any] = {
                direction_param: "true",
                "limit": page_size,
                "order_by": "block_timestamp,desc",
            }
            if self.contract_address:
                params["contract_address"] = self.contract_address
            if fingerprint:
                params["fingerprint"] = fingerprint

            body = self._get(path, params)
            records = body.get("data") or []
            for raw in records:
                tx = parse(raw)
                # Only successful, value-bearing transfers are evidence of money
                # moving; the rest is noise the trace must not follow.
                if tx and tx.to_address and not tx.is_error and tx.value_wei > 0:
                    collected.append(tx)

            fingerprint = (body.get("meta") or {}).get("fingerprint")
            if not fingerprint or not records:
                break

        return collected[:cap]

    def get_transactions(self, address: str, limit: int | None = None, sort: str = "desc"):
        """Present for interface parity; callers pick a direction explicitly."""
        return self.get_outgoing_transactions(address, limit=limit)
