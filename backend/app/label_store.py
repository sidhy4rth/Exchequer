"""On-disk risk labels: millions of addresses, looked up one at a time.

The JSON label files are loaded whole into memory, which is right for tens of
thousands of curated entries and wrong for the millions an on-chain scan
produces (address poisoning alone runs to millions of wallets). This store is
a single SQLite file, opened read-only and queried by primary key, so its size
costs disk, not memory: a lookup is one index probe whether it holds a
thousand rows or ten million.

It is an overlay, never an authority over the files. RiskMatcher asks the
files first and consults the store only for an address they do not name, so a
government designation can never be displaced by a scan result. Nor does it
ever label an exchange wallet, router, token contract or burn address
(app/never_flag.py). Without the file a trace runs exactly as it did before:
no store, no extra screening.

Rows are stored compactly -- addresses, lookalike targets and sample
transactions as raw bytes, repeated text (entities, sources) once in a side
table -- because the evidence for each row, not just the verdict, has to ship
with it. Build it with scripts/build_label_store.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from . import config, label_rules

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CHAIN_IDS = {"ethereum": 1, "bsc": 2, "polygon": 3, "arbitrum": 4, "tron": 5}

# How strong the evidence behind a row is, strongest first. Quoted in the
# source line so a report never presents a scan result as a court finding, or
# a crowd-sourced list as research. app/label_rules.py says which applies.
TIERS = {
    1: "government or court record",
    2: "stablecoin issuer action",
    3: "published threat intelligence",
    4: "on-chain detection",
    5: "unvetted list (community reports or a machine-learning dataset), not checked",
}

# The mixer pools and routers a store row may end a trace at (see pinned_mixers).
MIXER_POOLS_FILE = "mixer_pools.json"

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def encode_address(address: str) -> bytes | None:
    """Raw bytes for an EVM (20) or Tron (21, with the 0x41 prefix) address."""
    a = (address or "").strip()
    if a.startswith(("0x", "0X")) and len(a) == 42:
        try:
            return bytes.fromhex(a[2:])
        except ValueError:
            return None
    if a.startswith("T") and len(a) == 34:
        n = 0
        for ch in a:
            if ch not in _B58_INDEX:
                return None
            n = n * 58 + _B58_INDEX[ch]
        raw = n.to_bytes(25, "big")
        if raw[0] != 0x41 or _sha256d(raw[:21])[:4] != raw[21:]:
            return None
        return raw[:21]
    return None


def decode_address(raw: bytes) -> str:
    if len(raw) == 20:
        return "0x" + raw.hex()
    payload = raw + _sha256d(raw)[:4]
    n = int.from_bytes(payload, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return out


def encode_tx(tx: str) -> bytes | None:
    h = (tx or "").strip().removeprefix("0x").removeprefix("0X")
    if len(h) != 64:
        return None
    try:
        return bytes.fromhex(h)
    except ValueError:
        return None


@lru_cache(maxsize=None)
def pinned_mixers(chain: str) -> frozenset[bytes]:
    """The addresses a store mixer row may end a trace at on this chain.

    A store row is a name in someone else's list; a name alone must never cut
    a trail (ADR-0006), or one poisoned row ("Tornado.Cash: Router" on a
    launderer's wallet) would stop every trace a hop short of the exchange.
    So only a pool or router kept in the repository counts: the mixer entries
    of the chain's curated threat file, and data/mixer_pools.json. Any other
    store mixer row is shown as a tag, and the walk goes on past it.
    """
    found: set[bytes] = set()
    try:
        path = config.get_chain(chain).threat_labels_path
    except config.UnknownChainError:
        return frozenset()
    sources: list[dict] = []
    for file in (path, config.DATA_DIR / MIXER_POOLS_FILE):
        if file is None or not file.is_file():
            continue
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("%s unreadable; no store mixer row there ends a trace: %s", file, exc)
            continue
        # A part of the wrong shape counts as empty, with one log line, as in
        # risk_matcher._read_labels: a list here made every store mixer
        # lookup raise (r1-labels-data-11).
        part = (document.get("labels") if file == path else document.get(chain)) \
            if isinstance(document, dict) else document
        if part is None:
            continue
        if not isinstance(part, dict):
            logger.error("%s: %s is not an object of addresses; no store mixer row there ends a trace",
                         file, "'labels'" if file == path else (f"'{chain}'" if isinstance(document, dict)
                                                                 else "the file"))
            continue
        if file == path:
            sources.append({a: v for a, v in part.items() if isinstance(v, dict) and v.get("category") == "mixer"})
        else:
            sources.append(part)
    for entries in sources:
        for address in entries:
            raw = encode_address(address) if not address.startswith("_") else None
            if raw is not None:
                found.add(raw)
    return frozenset(found)


class LabelStore:
    """Read-only lookups against one label-store file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # immutable=1: the file is never written while the app runs, so SQLite
        # can skip locking entirely. One connection, guarded, shared by threads.
        self._db = sqlite3.connect(f"file:{self.path}?mode=ro&immutable=1", uri=True,
                                   check_same_thread=False)
        self._lock = threading.Lock()
        version = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or int(version[0]) != SCHEMA_VERSION:
            raise ValueError(f"label store {self.path} has schema {version and version[0]}, "
                             f"expected {SCHEMA_VERSION}; rebuild it")
        # The rules apply on read too, so a store built before them reads
        # right: no team member's name in a source, no "null" entity.
        self._texts = {i: label_rules.public_text(t) for i, t in self._db.execute("SELECT id, text FROM texts")}
        self._tiers: dict[tuple[int, str, int], int] = {}
        self._counts: dict[str, dict[str, int]] = {}
        for chain, category, n in self._db.execute("SELECT chain, category, n FROM counts"):
            self._counts.setdefault(chain, {})[category] = n

    def lookup(self, chain: str, address: str) -> dict[str, str] | None:
        chain_id = CHAIN_IDS.get(chain)
        raw = encode_address(address)
        if chain_id is None or raw is None:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT category, entity, label, peer, tx, date, source, tier "
                "FROM labels WHERE address=? AND chain=?", (raw, chain_id)).fetchone()
        if row is None:
            return None
        category, entity_id, label, peer, tx, date, source_id, tier = row
        if category == "mixer" and (chain not in label_rules.STORE_MIXER_CHAINS
                                    or not label_rules.mixer_service(self._texts.get(entity_id, ""))):
            # Only a mixer's own pool ends a trace, and only on the chain its
            # tag was read on. Anything else is left out: the walk goes on.
            return None
        from .never_flag import blocks, kind  # never_flag imports this module

        if blocks(kind(chain, address), category):
            # An exchange, router, token contract or burn address: a scan or
            # list that names one is wrong, whatever it says (never_flag.py).
            return None
        # A mixer row stops a trace only at a pool or router kept in the repo.
        terminal = {"terminal": raw in pinned_mixers(chain)} if category == "mixer" else {}
        label = label_rules.clean_text(label)
        if not label and peer is not None:
            label = f"Lookalike of {decode_address(peer)}"
        entity = (label_rules.clean_text(self._texts.get(entity_id, ""))
                  or label_rules.DEFAULT_ENTITY.get(category, category))
        evidence = []
        if tx is not None:
            evidence.append(f"sample tx {'' if chain == 'tron' else '0x'}{tx.hex()}")
        if date:
            d = str(date)
            evidence.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
        source = label_rules.clean_text(self._texts.get(source_id, ""))
        # Who published the row decides its tier, never more than it was built with.
        tier = self._tier(source_id, category, tier)
        if evidence:
            source = f"{source} ({', '.join(evidence)})"
        if tier in TIERS:
            source = f"{source}; evidence: {TIERS[tier]}"
        # The tier travels with the row as well as in its text, so the sentence
        # a report quotes can say what kind of evidence it is (RiskMatch.describe).
        return {"category": category, "entity": entity, "label": label or entity, "source": source, "tier": tier,
                **terminal}

    def _tier(self, source_id: int, category: str, stored: int) -> int:
        key = (source_id, category, stored)
        if key not in self._tiers:
            self._tiers[key] = label_rules.evidence_tier(category, self._texts.get(source_id, ""), stored)
        return self._tiers[key]

    def counts(self, chain: str) -> dict[str, int]:
        return dict(self._counts.get(chain, {}))

    def __len__(self) -> int:
        return sum(sum(c.values()) for c in self._counts.values())

    def build_info(self) -> dict[str, str]:
        """When the store was built and from which file, as scripts/build_label_store.py recorded."""
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM meta WHERE key IN ('built_at', 'built_from')").fetchall()
        return {key: str(value) for key, value in rows}


@lru_cache(maxsize=1)
def get_label_store() -> LabelStore | None:
    """The configured store, or None when there is no file (screening as before)."""
    path = config.LABEL_STORE_PATH
    if not path or not Path(path).is_file():
        if config.LABEL_STORE_REQUIRED:
            logger.error("No label store at %s although this image requires one; screening is "
                         "degraded to the label files only", path)
        else:
            logger.info("No label store at %s; screening uses the label files only", path)
        return None
    try:
        store = LabelStore(Path(path))
    except (sqlite3.Error, ValueError) as exc:
        logger.error("Label store at %s is unusable, ignored: %s", path, exc)
        return None
    logger.info("Label store %s: %d addresses", path, len(store))
    return store


def status() -> dict[str, object]:
    """For /health/detail: whether the store this image needs is in use."""
    store = get_label_store()
    return {"required": config.LABEL_STORE_REQUIRED, "loaded": store is not None,
            "rows": len(store) if store is not None else 0, "tag": config.LABEL_STORE_TAG}
