"""Central configuration, loaded from environment / backend/.env.

Nothing secret is ever hardcoded here -- the Etherscan API key is read from
the ETHERSCAN_API_KEY environment variable only.

TraceChain is multi-chain. Etherscan's V2 endpoint serves every supported
chain from one host and one API key, selected by a `chainid` query parameter,
so adding a chain here costs no extra signup and no extra key. What a chain
*does* need is its own exchange-label file: Binance's hot wallets on BNB Smart
Chain are different addresses from Binance's hot wallets on Ethereum, and
attributing across chains would be simply wrong.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"

# Load backend/.env if present. Real environment variables always win.
load_dotenv(BACKEND_DIR / ".env", override=False)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Chains
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Token:
    """One traceable asset on a chain.

    `decimals` is recorded because it genuinely differs per chain: USDT is 6
    decimals on Ethereum and 18 on BNB Smart Chain. Assuming one value would
    misstate every amount by a factor of a trillion -- silently, since nothing
    would crash. Every address and precision below was confirmed by calling
    symbol() and decimals() on the contract itself.
    """

    symbol: str
    address: str
    decimals: int

    def to_dict(self) -> dict[str, object]:
        return {"symbol": self.symbol, "address": self.address, "decimals": self.decimals}


@dataclass(frozen=True)
class Chain:
    """One traceable chain.

    `native_symbol` is threaded through the whole pipeline rather than
    hardcoded, because a report that says "3.1 ETH" about a BNB Smart Chain
    transfer is not a cosmetic bug -- it misstates the evidence.
    """

    key: str  # url/API-facing identifier
    chain_id: int  # Etherscan V2 chainid parameter
    name: str  # human-readable, used in reports
    native_symbol: str  # ETH, BNB, ...
    explorer_url: str  # for "verify this yourself" links
    labels_filename: str  # exchange labels, relative to data/
    # Sanctions / mixer labels, relative to data/. Separate from the exchange
    # file because it answers a different question -- not "where was this
    # cashed out" but "what did it touch on the way" -- and because it comes
    # from a different source with its own publication date.
    risk_labels_filename: str = ""
    # Which upstream serves this chain's transaction history. "etherscan"
    # works only where the free tier does, which is Ethereum mainnet alone --
    # verified against the live API, which rejects every other chainid with
    # "Free API access is not supported for this chain".
    provider: str = "etherscan"
    # "evm" (0x…40 hex) or "tron" (T…33 Base58). An address is only meaningful
    # on the family it belongs to, so this is what makes "is this address valid
    # for the chain you picked" answerable.
    address_family: str = "evm"
    # Stablecoins traceable on this chain. A trace follows one asset at a time:
    # 1 BNB and 1 USDT are not comparable quantities, so summing them into a
    # single "value" would make the confidence score meaningless.
    tokens: tuple[Token, ...] = ()

    @property
    def labels_path(self) -> Path:
        return DATA_DIR / self.labels_filename

    @property
    def risk_labels_path(self) -> Path | None:
        """Where this chain's sanctions/mixer labels live, if it has any.

        None rather than a missing path: a chain with no risk file still
        traces and still attributes an exchange, it simply is not screened.
        """
        return DATA_DIR / self.risk_labels_filename if self.risk_labels_filename else None

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "chain_id": self.chain_id,
            "name": self.name,
            "native_symbol": self.native_symbol,
            "explorer_url": self.explorer_url,
            "provider": self.provider,
            "address_family": self.address_family,
            "assets": [{"symbol": self.native_symbol, "address": None,
                        "decimals": 18, "native": True}]
                      + [{**t.to_dict(), "native": False} for t in self.tokens],
        }

    def validate_address(self, address: str) -> bool:
        """True if `address` is well formed *for this chain*."""
        from .etherscan_client import is_evm_address, is_tron_address

        checker = is_tron_address if self.address_family == "tron" else is_evm_address
        return checker(address)

    def address_hint(self) -> str:
        """What a valid address looks like here, for an error message."""
        if self.address_family == "tron":
            return "T followed by 33 Base58 characters"
        return "0x followed by 40 hexadecimal characters"

    def find_token(self, symbol: str) -> "Token | None":
        wanted = symbol.strip().upper()
        for token in self.tokens:
            if token.symbol.upper() == wanted:
                return token
        return None


# Both chains are EVM: same 0x-address format, same 18-decimal native unit,
# same Etherscan V2 API surface. That is why one client serves both.
CHAINS: dict[str, Chain] = {
    "ethereum": Chain(
        key="ethereum",
        chain_id=1,
        name="Ethereum Mainnet",
        native_symbol="ETH",
        explorer_url="https://etherscan.io",
        labels_filename="exchange_labels.json",
        risk_labels_filename="risk_labels.json",
        tokens=(
            Token("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", 6),
            Token("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
        ),
    ),
    "bsc": Chain(
        key="bsc",
        chain_id=56,
        name="BNB Smart Chain",
        native_symbol="BNB",
        explorer_url="https://bscscan.com",
        labels_filename="exchange_labels_bsc.json",
        risk_labels_filename="risk_labels_bsc.json",
        # Etherscan's free tier refuses chainid 56, so BSC is served by
        # NodeReal, whose free tier does cover it.
        provider="nodereal",
        tokens=(
            Token("USDT", "0x55d398326f99059ff775485246999027b3197955", 18),
            Token("USDC", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", 18),
        ),
    ),
}

CHAINS["tron"] = Chain(
    key="tron",
    # Tron is not an EVM chain and has no Etherscan chainid. The field is kept
    # for interface parity and is never sent anywhere.
    chain_id=0,
    name="Tron",
    native_symbol="TRX",
    explorer_url="https://tronscan.org",
    labels_filename="exchange_labels_tron.json",
    risk_labels_filename="risk_labels_tron.json",
    provider="trongrid",
    address_family="tron",
    tokens=(
        # Verified against TronScan: symbol USDT, 6 decimals. USDT on Tron is
        # the single largest stablecoin rail by transfer count, which is why
        # this chain matters for fraud work at all.
        Token("USDT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", 6),
    ),
)

_CHAINS_BY_ID: dict[int, Chain] = {
    chain.chain_id: chain for chain in CHAINS.values() if chain.chain_id
}

# Older cases were stored before chains had keys, when the field was a free
# string. They are still in the database and still re-traceable from the
# history list, so their spelling has to keep resolving.
_CHAIN_ALIASES: dict[str, str] = {
    "ethereum-mainnet": "ethereum",
    "mainnet": "ethereum",
    "eth": "ethereum",
    "bnb": "bsc",
    "binance-smart-chain": "bsc",
    "bnb-smart-chain": "bsc",
}


class UnknownChainError(ValueError):
    """Raised when a caller asks for a chain TraceChain does not support."""


def get_chain(key: str | None = None) -> Chain:
    """Look up a chain by key, falling back to the configured default."""
    if key is None or not str(key).strip():
        return DEFAULT_CHAIN
    normalized = str(key).strip().lower()
    normalized = _CHAIN_ALIASES.get(normalized, normalized)
    chain = CHAINS.get(normalized)
    if chain is None:
        raise UnknownChainError(
            f"Unsupported chain '{key}'. Supported: {', '.join(sorted(CHAINS))}."
        )
    return chain


def chain_by_id(chain_id: int) -> Chain | None:
    """Look up a chain by its Etherscan V2 chainid."""
    return _CHAINS_BY_ID.get(chain_id)


ETHERSCAN_API_KEY: str | None = os.getenv("ETHERSCAN_API_KEY") or None
ETHERSCAN_BASE_URL: str = os.getenv("ETHERSCAN_BASE_URL", "https://api.etherscan.io/v2/api")

# Which chain a request that names none is traced on. ETHERSCAN_CHAIN_ID is
# still honoured so existing .env files keep working unchanged.
_default_key = (os.getenv("TRACECHAIN_DEFAULT_CHAIN") or "").strip().lower()
if _default_key and _default_key in CHAINS:
    DEFAULT_CHAIN: Chain = CHAINS[_default_key]
else:
    DEFAULT_CHAIN = _CHAINS_BY_ID.get(_int_env("ETHERSCAN_CHAIN_ID", 1), CHAINS["ethereum"])

# Kept for backwards compatibility with callers that expect a single chain id.
ETHERSCAN_CHAIN_ID: int = DEFAULT_CHAIN.chain_id

NODEREAL_API_KEY: str | None = os.getenv("NODEREAL_API_KEY") or None
# TronGrid works without a key at a low rate limit; a free key raises it. Sent
# as the TRON-PRO-API-KEY header.
TRONGRID_API_KEY: str | None = os.getenv("TRONGRID_API_KEY") or None
# How far back a NodeReal-served trace looks. Its API caps one query at 100,000
# blocks (~3.5 days on BSC), so this is walked in windows: 500,000 blocks is
# roughly 17 days and at most five requests per address. Raising it widens
# coverage and costs proportionally more calls.
NODEREAL_LOOKBACK_BLOCKS: int = _int_env("NODEREAL_LOOKBACK_BLOCKS", 500_000)

# Traversal safety limits -- a busy wallet must never make a trace run forever.
TRACE_MAX_DEPTH: int = _int_env("TRACE_MAX_DEPTH", 4)
TRACE_MAX_TXS_PER_ADDRESS: int = _int_env("TRACE_MAX_TXS_PER_ADDRESS", 200)
TRACE_MAX_NODES: int = _int_env("TRACE_MAX_NODES", 400)
# How many addresses at one depth are fetched concurrently. Providers answer in
# ~5s on the free tiers, almost all of it network wait, so fetching a level
# serially spends most of a trace idle. The shared pacer still caps the request
# rate, so this overlaps network waiting without raising the load on the API.
TRACE_CONCURRENCY: int = _int_env("TRACE_CONCURRENCY", 6)

# Minimum spacing between Etherscan requests, in seconds.
#
# Etherscan documents ~5 req/s on the free tier. Measured against a live free
# key, that is not what it grants: sustained load at 0.34s spacing (2.9 req/s)
# was refused 54% of the time, and every refusal costs a retry with exponential
# backoff. Pushing harder therefore made traces *slower* -- at 0.20s spacing,
# two thirds of requests were refused.
#
# 0.50s was the measured optimum: 4% refusals and the highest useful throughput
# of any spacing tried. Raise it if the key is shared with another tool; lower
# it only against a paid plan, where the real ceiling is higher.
ETHERSCAN_MIN_INTERVAL: float = float(os.getenv("ETHERSCAN_MIN_INTERVAL", "0.5"))

# SQLite location. Relative paths resolve against backend/.
_db_raw = os.getenv("TRACECHAIN_DB_PATH", "tracechain.db")
DB_PATH: Path = Path(_db_raw) if Path(_db_raw).is_absolute() else BACKEND_DIR / _db_raw

# Default-chain label file. Per-chain callers should use Chain.labels_path.
EXCHANGE_LABELS_PATH: Path = DEFAULT_CHAIN.labels_path

# How long a provider response stays reusable. On-chain history is append-only,
# so a cached answer can only lag the newest blocks -- never contradict them.
# The free tiers cap requests per *second* while leaving the daily quota barely
# touched (a trace costs ~35 of 100,000 calls/day), so reusing an answer is
# what actually shortens a trace: the second traversal direction, an overlapping
# trace and every re-run of the same address all stop touching the network.
API_CACHE_TTL_SECONDS: float = float(os.getenv("API_CACHE_TTL_SECONDS", "600"))
