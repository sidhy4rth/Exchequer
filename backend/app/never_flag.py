"""Addresses no scan-derived label may name: infrastructure, not wallets.

The label store (app/label_store.py) is built from bulk on-chain scans and
third-party lists. A scan can catch a busy contract -- a spam token can name
any sender -- and a list can carry a mistake: on 5 Nov the store called WETH,
DAI and the WhiteBIT hot wallet poisoners until checks kept outside the repo
caught them. An exchange or a token contract shown as a scammer misleads the
investigator, and the exchange the letter goes to. So the store never labels:

  system    the zero and burn range (an address below 2**64) and the
            native-coin placeholder
  token     each chain's traced tokens, data/never_flag_tokens.txt, and the
            CoinGecko/Uniswap token lists in data/never_flag_tokens.json
            (scripts/build_never_flag.py; its "allow" map holds reviewed
            exceptions, address -> why, never code)
  router    a DEX router in any EVM chain's router_labels*.json, on every
            EVM chain (see evm_routers for why that is safe)
  exchange  an exchange's own wallet in exchange_labels*.json
  deposit   an exchange deposit address (one customer's account)
  gambling  a casino wallet in gambling_labels*.json

An exchange, deposit or casino wallet keeps an issuer's freeze -- a recorded
act on that one wallet, not an accusation -- and nothing else; a system, token
or router address keeps nothing. Enforced when the store is built
(scripts/build_label_store.py) and again on every store lookup, so a store
already released reads correctly too. The curated label files keep their own
rules; at run time they also outrank the store, so a casino wallet named in a
gambling file never reaches a store lookup at all.

The list importers and the nightly gate ask the same question per address
with reason()/screen(): a token contract, DEX router, exchange wallet (not a
per-customer deposit address) or burn address must never carry a sanctions,
freeze or scam label there either.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from . import config
from .label_store import decode_address, encode_address

logger = logging.getLogger(__name__)

# Readable: the importers print these in their refusals and excluded notes.
SYSTEM, TOKEN, ROUTER, EXCHANGE = "burn/system address", "token contract", "DEX router", "exchange wallet"
DEPOSIT, GAMBLING = "exchange deposit address", "casino wallet"
# From a list given to the store build: every label refused, or only poisoning.
LISTED, NO_POISONING = "on a never-flag list", "on a never-poison list"
_STRICT = frozenset({SYSTEM, TOKEN, ROUTER, LISTED})
# Precedence when one address is several kinds: the strictest wins.
_RANK = {SYSTEM: 0, TOKEN: 1, ROUTER: 2, LISTED: 3, EXCHANGE: 4, DEPOSIT: 5, GAMBLING: 6, NO_POISONING: 7}

TOKENS_FILE = config.DATA_DIR / "never_flag_tokens.txt"  # as shipped; read through _tokens_file()


def _tokens_file() -> Path:
    return config.DATA_DIR / TOKENS_FILE.name
NEVER_FLAG_FILE = "never_flag_tokens.json"
# Above 2**64, but no one's wallet: the native-coin placeholder DEX
# aggregators use, and a common burn address.
_SYSTEM_BODIES = frozenset(bytes.fromhex(h) for h in (
    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    "dead000000000000000042069420694206942069",
))


def is_system(raw: bytes) -> bool:
    """The zero/burn range or a placeholder, for an EVM (20-byte) or Tron (0x41 + 20) address."""
    body = raw[1:] if len(raw) == 21 else raw
    return int.from_bytes(body, "big") < 2**64 or body in _SYSTEM_BODIES


def blocks(kind: str | None, category: str) -> bool:
    """Whether a store row of `category` must not be used for an address of `kind`."""
    if kind is None:
        return False
    if kind in _STRICT:
        return True
    if kind == NO_POISONING:
        return category == "poisoning"
    return category != "frozen"  # exchange, deposit, casino: only an issuer's freeze stands


def _raw(chain_key: str, address: str, hex_as_tron: bool = True) -> bytes | None:
    raw = encode_address(address)
    if raw is not None and chain_key == "tron" and len(raw) == 20 and hex_as_tron:
        raw = b"\x41" + raw  # a Tron address written in hex form
    if raw is None or (chain_key == "tron") != (len(raw) == 21):
        return None  # not an address of this chain's family
    return raw


def read_list(path: Path, chain_key: str, missing_ok: bool = False) -> set[bytes]:
    """The addresses of `chain_key`'s family in a list: one per line (the last
    field of a line counts, so a tab-separated note may come first), # for notes.
    A 0x address is an EVM one; only a base58 address is Tron's.

    A line that is not UTF-8 is skipped, with one log line for the file: one
    stray byte in an appended token list made every store-row lookup on every
    chain raise (r1-labels-data-11). With `missing_ok` (the trace path), a file
    that cannot be read counts as empty, logged; the store build passes its
    lists explicitly and stops instead.
    """
    return _addresses(_list_fields(Path(path), missing_ok), chain_key)


def _addresses(fields: Iterable[str], chain_key: str) -> set[bytes]:
    return {raw for raw in (_raw(chain_key, f, hex_as_tron=False) for f in fields) if raw is not None}


def _list_fields(path: Path, missing_ok: bool) -> tuple[str, ...]:
    """Each entry line's last field (see read_list)."""
    try:
        body = path.read_bytes()
    except OSError as exc:
        if not missing_ok:
            raise
        logger.error("%s unreadable; its addresses do not count: %s", path.name, exc)
        return ()
    fields, skipped = [], 0
    for chunk in body.splitlines():
        try:
            line = chunk.decode("utf-8").strip()
        except UnicodeDecodeError:
            skipped += 1
            continue
        if line and not line.startswith("#"):
            fields.append(line.split()[-1])
    if skipped:
        logger.warning("%s: %d line%s not UTF-8, skipped", path.name, skipped, "" if skipped == 1 else "s")
    return tuple(fields)


@lru_cache(maxsize=1)
def _token_list() -> tuple[str, ...]:
    """data/never_flag_tokens.txt's entries, read (and any bad line logged) once for every chain."""
    path = _tokens_file()
    return _list_fields(path, missing_ok=True) if path.exists() else ()


@lru_cache(maxsize=1)
def _file() -> tuple[frozenset[str], dict[str, str]]:
    """(token contracts, allowed exceptions) from data/never_flag_tokens.json; empty if it is missing."""
    try:
        document = json.loads((config.DATA_DIR / NEVER_FLAG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("No readable %s; only configured tokens count as token contracts", NEVER_FLAG_FILE)
        return frozenset(), {}
    # A file of the wrong shape counts as empty, part by part: a list here
    # made every store lookup that found a row raise (r1-labels-data-11).
    if not isinstance(document, dict):
        logger.warning("%s is a JSON %s, not an object; only configured tokens count as token contracts",
                       NEVER_FLAG_FILE, type(document).__name__)
        return frozenset(), {}
    tokens_part, allow_part = document.get("tokens") or [], document.get("allow") or {}
    if not isinstance(tokens_part, list):
        logger.warning("%s: 'tokens' is not a list; ignored", NEVER_FLAG_FILE)
        tokens_part = []
    if not isinstance(allow_part, dict):
        logger.warning("%s: 'allow' is not an object; ignored", NEVER_FLAG_FILE)
        allow_part = {}
    listed = frozenset(a for a in tokens_part if isinstance(a, str))
    allow = {a: str(why) for a, why in allow_part.items() if isinstance(a, str)}
    if len(listed) < len(tokens_part):
        logger.warning("%s: %d token entries that are not addresses skipped", NEVER_FLAG_FILE,
                       len(tokens_part) - len(listed))
    return listed, allow


def _allowed(chain_key: str) -> frozenset[bytes]:
    return frozenset(r for r in (_raw(chain_key, a, hex_as_tron=False) for a in _file()[1]) if r is not None)


@lru_cache(maxsize=None)
def tokens(chain_key: str) -> frozenset[bytes]:
    chain = config.get_chain(chain_key)
    found = {r for r in (_raw(chain.key, t.address) for t in chain.tokens) if r is not None}
    found |= _addresses(_token_list(), chain.key)
    found |= {r for r in (_raw(chain.key, a, hex_as_tron=False) for a in _file()[0]) if r is not None}
    return frozenset(found - _allowed(chain.key))


@lru_cache(maxsize=1)
def evm_routers() -> frozenset[bytes]:
    """Every router any EVM chain's router file names, refused a label on every EVM chain.

    Polygon and Arbitrum have no router file, so the 1inch or Uniswap router a
    scan names there was labelled. The rule that makes carrying them over safe:
    a router file holds only contracts (scripts/seed_router_labels.py keeps an
    entry only if it has bytecode). A contract's address has no private key: it
    comes from its deployer and that deployer's nonce, or from a factory, a salt
    and the code itself. So on another EVM chain the same address is either
    unused, the same protocol's deployment, or code the same deployer or factory
    put there -- never a wallet a scammer holds the key to. A label lost there
    is a missed warning; a router labelled a scammer in a letter is the harm
    this module exists to stop.

    Only the refusal carries over. The router matcher, which calls a transfer a
    swap and reads the receipt, still uses each chain's own file: a positive
    claim about the contract on another chain needs that chain's own check
    (scripts/port_evm_labels.py: a contract address means nothing across
    chains). Exchange wallets are not carried this way; they have their own
    port with on-chain checks. Tron is another address family and gets none.
    """
    from .exchange_matcher import get_router_matcher

    found: set[bytes] = set()
    for chain in config.CHAINS.values():
        if chain.address_family != "evm":
            continue
        for address, _ in get_router_matcher(chain.key).entries():
            raw = _raw(chain.key, address)
            if raw is not None:
                found.add(raw)
    return frozenset(found)


@lru_cache(maxsize=None)
def routers(chain_key: str) -> frozenset[bytes]:
    """The routers no row may label on this chain: its own file's, and on an EVM chain every EVM file's."""
    from .exchange_matcher import get_router_matcher

    chain = config.get_chain(chain_key)
    own = frozenset(r for r in (_raw(chain.key, a) for a, _ in get_router_matcher(chain.key).entries()) if r)
    return own | evm_routers() if chain.address_family == "evm" else own


@lru_cache(maxsize=None)
def gambling(chain_key: str) -> frozenset[bytes]:
    path = config.get_chain(chain_key).gambling_labels_path
    if path is None or not path.is_file():
        return frozenset()
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.error("Gambling labels at %s unreadable for the never-flag check: %s", path, exc)
        return frozenset()
    entries = document.get("labels", {}) if isinstance(document, dict) else None
    if not isinstance(entries, (dict, list)):
        logger.error("Gambling labels at %s are not an object of labels; none count for the never-flag check",
                     path)
        return frozenset()
    keys = [a for a in entries if isinstance(a, str)]
    if len(keys) < len(entries):
        logger.warning("Gambling labels at %s: %d entries that are not addresses skipped",
                       path, len(entries) - len(keys))
    return frozenset(r for r in (_raw(chain_key, a) for a in keys if not a.startswith("_")) if r is not None)


def kind(chain_key: str, address: str, *, with_gambling: bool = False) -> str | None:
    """What infrastructure `address` is on this chain, if any.

    Reads the exchange and router matchers the trace already holds, so it
    copies nothing. Casino wallets are checked only when asked: at run time
    the gambling file outranks the store and they never reach it.
    """
    from .exchange_matcher import get_matcher

    raw = _raw(chain_key, address)
    if raw is None or raw in _allowed(chain_key):
        return None
    if is_system(raw):
        return SYSTEM
    if raw in tokens(chain_key):
        return TOKEN
    canonical = decode_address(raw)
    if raw in routers(chain_key):
        return ROUTER
    exchange = get_matcher(chain_key).lookup(canonical)
    if exchange:
        return DEPOSIT if exchange.get("type") == "deposit_wallet" else EXCHANGE
    if with_gambling and raw in gambling(chain_key):
        return GAMBLING
    return None


def build_kinds(chain_key: str, listed: Iterable[Path] = (), no_poisoning: Iterable[Path] = ()) -> dict[bytes, str]:
    """Every never-flag address of one chain, raw bytes -> kind, for the store
    build's tight loop (the system range is checked by is_system)."""
    from .exchange_matcher import get_matcher

    found: dict[bytes, str] = {}

    def add(raws: Iterable[bytes], what: str) -> None:
        for raw in raws:
            if raw not in found or _RANK[what] < _RANK[found[raw]]:
                found[raw] = what

    add(tokens(chain_key), TOKEN)
    add(routers(chain_key), ROUTER)
    for address, meta in get_matcher(chain_key).entries():
        raw = _raw(chain_key, address)
        if raw is not None:
            add((raw,), DEPOSIT if meta.get("type") == "deposit_wallet" else EXCHANGE)
    add(gambling(chain_key), GAMBLING)
    for path in listed:
        add(read_list(path, chain_key), LISTED)
    for path in no_poisoning:
        add(read_list(path, chain_key), NO_POISONING)
    return found


# -- the list importers' view (scripts/import_*.py, import_all_lists' gate) --
_NEVER_LABEL = frozenset({SYSTEM, TOKEN, ROUTER, EXCHANGE})


def reason(chain_key: str | None, address: str) -> str | None:
    """Why `address` must never carry a sanctions, freeze or scam label on this
    chain (SYSTEM, TOKEN, ROUTER or EXCHANGE), or None. A per-customer deposit
    address is not refused: a government or issuer acting on it is a fact
    about that one customer."""
    found = kind(chain_key or config.DEFAULT_CHAIN.key, address)
    return found if found in _NEVER_LABEL else None


def screen(chain_key: str | None, addresses) -> dict[str, str]:
    """{address: reason} for every address in `addresses` that must not be labelled."""
    return {a: why for a in addresses if (why := reason(chain_key, a))}


def clear_cache() -> None:
    _file.cache_clear()
    _token_list.cache_clear()
    tokens.cache_clear()
    evm_routers.cache_clear()
    routers.cache_clear()
    gambling.cache_clear()
