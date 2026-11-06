"""Addresses no scan-derived label may name: infrastructure, not wallets.

The label store (app/label_store.py) is built from bulk on-chain scans and
third-party lists. A scan can catch a busy contract -- a spam token can name
any sender -- and a list can carry a mistake: on 5 Nov the store called WETH,
DAI and the WhiteBIT hot wallet poisoners until checks kept outside the repo
caught them. An exchange or a token contract shown as a scammer misleads the
investigator, and the exchange the letter goes to. So the store never labels:

  system    the zero and burn range (an address below 2**64) and the
            native-coin placeholder
  token     each chain's traced tokens, and data/never_flag_tokens.txt
  router    a DEX router in router_labels*.json
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

SYSTEM, TOKEN, ROUTER, EXCHANGE, DEPOSIT, GAMBLING = "system", "token", "router", "exchange", "deposit", "gambling"
# From a list given to the store build: every label refused, or only poisoning.
LISTED, NO_POISONING = "listed", "never-poison"
_STRICT = frozenset({SYSTEM, TOKEN, ROUTER, LISTED})
# Precedence when one address is several kinds: the strictest wins.
_RANK = {SYSTEM: 0, TOKEN: 1, ROUTER: 2, LISTED: 3, EXCHANGE: 4, DEPOSIT: 5, GAMBLING: 6, NO_POISONING: 7}

TOKENS_FILE = config.DATA_DIR / "never_flag_tokens.txt"
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


def read_list(path: Path, chain_key: str) -> set[bytes]:
    """The addresses of `chain_key`'s family in a list: one per line (the last
    field of a line counts, so a tab-separated note may come first), # for notes.
    A 0x address is an EVM one; only a base58 address is Tron's."""
    out: set[bytes] = set()
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            raw = _raw(chain_key, line.split()[-1], hex_as_tron=False)
            if raw is not None:
                out.add(raw)
    return out


@lru_cache(maxsize=None)
def tokens(chain_key: str) -> frozenset[bytes]:
    chain = config.get_chain(chain_key)
    found = {r for r in (_raw(chain.key, t.address) for t in chain.tokens) if r is not None}
    if TOKENS_FILE.is_file():
        found |= read_list(TOKENS_FILE, chain.key)
    return frozenset(found)


@lru_cache(maxsize=None)
def gambling(chain_key: str) -> frozenset[bytes]:
    path = config.get_chain(chain_key).gambling_labels_path
    if path is None or not path.is_file():
        return frozenset()
    try:
        entries = json.loads(path.read_text()).get("labels", {})
    except (OSError, ValueError, AttributeError) as exc:
        logger.error("Gambling labels at %s unreadable for the never-flag check: %s", path, exc)
        return frozenset()
    return frozenset(r for r in (_raw(chain_key, a) for a in entries if not a.startswith("_")) if r is not None)


def kind(chain_key: str, address: str, *, with_gambling: bool = False) -> str | None:
    """What infrastructure `address` is on this chain, if any.

    Reads the exchange and router matchers the trace already holds, so it
    copies nothing. Casino wallets are checked only when asked: at run time
    the gambling file outranks the store and they never reach it.
    """
    from .exchange_matcher import get_matcher, get_router_matcher

    raw = _raw(chain_key, address)
    if raw is None:
        return None
    if is_system(raw):
        return SYSTEM
    if raw in tokens(chain_key):
        return TOKEN
    canonical = decode_address(raw)
    if get_router_matcher(chain_key).lookup(canonical):
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
    from .exchange_matcher import get_matcher, get_router_matcher

    found: dict[bytes, str] = {}

    def add(raws: Iterable[bytes], what: str) -> None:
        for raw in raws:
            if raw not in found or _RANK[what] < _RANK[found[raw]]:
                found[raw] = what

    add(tokens(chain_key), TOKEN)
    add((r for r in (_raw(chain_key, a) for a, _ in get_router_matcher(chain_key).entries()) if r), ROUTER)
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
