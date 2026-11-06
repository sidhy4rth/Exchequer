"""On-disk risk labels: millions of addresses, looked up one at a time.

The JSON label files are loaded whole into memory, which is right for tens of
thousands of curated entries and wrong for the millions an on-chain scan
produces (address poisoning alone runs to millions of wallets). This store is
a single SQLite file, opened read-only and queried by primary key, so its size
costs disk, not memory: a lookup is one index probe whether it holds a
thousand rows or ten million.

It is an overlay, never an authority over the files. RiskMatcher asks the
files first and consults the store only for an address they do not name, so a
government designation can never be displaced by a scan result. Without the
file a trace runs exactly as it did before: no store, no extra screening.

Rows are stored compactly -- addresses, lookalike targets and sample
transactions as raw bytes, repeated text (entities, sources) once in a side
table -- because the evidence for each row, not just the verdict, has to ship
with it. Build it with scripts/build_label_store.py.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CHAIN_IDS = {"ethereum": 1, "bsc": 2, "polygon": 3, "arbitrum": 4, "tron": 5}

# How strong the evidence behind a row is, strongest first. Quoted in the
# source line so a report never presents a scan result as a court finding.
TIERS = {
    1: "government or court record",
    2: "stablecoin issuer action",
    3: "published threat intelligence",
    4: "on-chain detection",
}

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
        self._texts = dict(self._db.execute("SELECT id, text FROM texts"))
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
        if label is None and peer is not None:
            label = f"Lookalike of {decode_address(peer)}"
        entity = self._texts.get(entity_id, "")
        evidence = []
        if tx is not None:
            evidence.append(f"sample tx {'' if chain == 'tron' else '0x'}{tx.hex()}")
        if date:
            d = str(date)
            evidence.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
        source = self._texts.get(source_id, "")
        if evidence:
            source = f"{source} ({', '.join(evidence)})"
        if tier in TIERS:
            source = f"{source}; evidence: {TIERS[tier]}"
        return {"category": category, "entity": entity, "label": label or entity, "source": source}

    def counts(self, chain: str) -> dict[str, int]:
        return dict(self._counts.get(chain, {}))

    def __len__(self) -> int:
        return sum(sum(c.values()) for c in self._counts.values())


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
