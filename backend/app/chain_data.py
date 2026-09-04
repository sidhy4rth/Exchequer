"""Chooses which data provider serves which chain.

The rest of TraceChain does not care where transactions come from. It asks a
source for `get_outgoing_transactions(address)` and gets back a list of
`Transaction`. That is the whole contract, and this module is the only place
that knows which upstream satisfies it for a given chain.

Why this indirection exists rather than calling Etherscan everywhere:

    Etherscan's V2 endpoint advertises 60+ chains behind one key, but the free
    tier only serves Ethereum mainnet. Any other chainid -- BNB Smart Chain
    (56) included -- answers:

        "Free API access is not supported for this chain.
         Please upgrade your api plan for full chain coverage."

    That was verified against the live API, not assumed. So BSC cannot be a
    one-line chainid change; it needs its own free provider, and therefore the
    pipeline needs a seam.

A chain whose provider is not configured fails with a message that says
exactly what to do about it, rather than surfacing as an opaque 502 that looks
like the chain has no transactions.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

from . import config
from .etherscan_client import EtherscanClient, EtherscanError, Transaction
from .nodereal_client import NoderealClient
from .tron_client import TronClient

logger = logging.getLogger(__name__)


class ProviderNotConfiguredError(EtherscanError):
    """A chain was requested whose data provider has no key configured.

    Subclasses EtherscanError so existing error handling keeps working, but is
    caught separately in main.py to return a 503 (server is missing config)
    rather than a 502 (upstream is broken). The distinction matters to whoever
    is trying to get the demo running.
    """


class UnknownAssetError(ValueError):
    """The caller asked for an asset this chain does not carry.

    Distinct from ProviderNotConfiguredError: nothing is wrong with the
    server, the request simply named a currency that does not exist here. It
    therefore deserves a 400, not a 503 -- the difference matters to whoever
    is trying to work out whether to fix their request or the deployment.
    """


@runtime_checkable
class TransactionSource(Protocol):
    """What the graph builder needs from any chain data provider."""

    def get_outgoing_transactions(
        self, address: str, limit: int | None = None
    ) -> list[Transaction]:
        ...

    def close(self) -> None:
        ...

    # main.py opens a source with `with`, so the contract includes it.
    def __enter__(self) -> "TransactionSource":
        ...

    def __exit__(self, *exc: object) -> None:
        ...


def open_source(chain: config.Chain, asset: str | None = None) -> TransactionSource:
    """Return a transaction source for `chain`, ready to use as a context manager.

    `asset` selects which currency the trace follows. None or the chain's
    native symbol means native value; a token symbol restricts the source to
    that contract. Providers that cannot serve the requested asset say so
    rather than silently returning native transfers instead.

    Raises ProviderNotConfiguredError if the chain has no usable provider, so
    the caller can report a fixable configuration problem instead of a failed
    trace.
    """
    token = None
    if asset and asset.upper() != chain.native_symbol.upper():
        token = chain.find_token(asset)
        if token is None:
            raise UnknownAssetError(
                f"{chain.name} has no traceable asset called '{asset}'. "
                f"Available: {chain.native_symbol}, "
                + ", ".join(t.symbol for t in chain.tokens)
            )

    if chain.provider == "trongrid":
        # TronGrid answers without a key at a reduced rate limit, so Tron is
        # usable out of the box; a key only raises throughput.
        return TronClient(
            contract_address=token.address if token else None,
            asset_symbol=token.symbol if token else chain.native_symbol,
        )

    if chain.provider == "nodereal":
        if not config.NODEREAL_API_KEY:
            raise ProviderNotConfiguredError(
                f"NODEREAL_API_KEY is not set, so {chain.name} cannot be traced. "
                "Add a free key from https://nodereal.io to backend/.env."
            )
        return NoderealClient(
            chain_slug="bsc-mainnet" if chain.key == "bsc" else "eth-mainnet",
            native_symbol=chain.native_symbol,
            contract_addresses=[token.address] if token else None,
            asset_symbol=token.symbol if token else chain.native_symbol,
        )

    if chain.provider == "etherscan":
        if not config.ETHERSCAN_API_KEY:
            raise ProviderNotConfiguredError(
                "ETHERSCAN_API_KEY is not set. Copy backend/.env.example to "
                "backend/.env and add a free key from https://etherscan.io/apis"
            )
        # `tokentx` is on the same free key as `txlist`, so following USDT or
        # USDC here costs nothing extra.
        return EtherscanClient(
            chain_id=chain.chain_id,
            contract_address=token.address if token else None,
            asset_symbol=token.symbol if token else chain.native_symbol,
        )

    raise ProviderNotConfiguredError(
        f"Unknown provider '{chain.provider}' configured for {chain.name}."
    )


def provider_status() -> dict[str, dict[str, object]]:
    """Per-chain readiness, for /health.

    Reported up front because "which chains can I actually trace right now" is
    the question that otherwise gets answered by a failed trace mid-demo.
    """
    status: dict[str, dict[str, object]] = {}
    for key, chain in config.CHAINS.items():
        try:
            open_source(chain).close()
            ready, detail = True, None
        except ProviderNotConfiguredError as exc:
            ready, detail = False, str(exc)
        status[key] = {**chain.to_dict(), "ready": ready, "detail": detail}
    return status
