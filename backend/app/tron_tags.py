"""Reading TronScan's public address tags during a Tron trace.

Tron is where the evidence says Indian scam money moves, yet a fixed label file
can only ever hold the wallets someone thought to import -- 41 of them. TronScan
publishes a tag for far more addresses than that, and the tag is the explorer's
own attribution, the same provenance the Tron label file already relies on. So
a Tron trace can ask TronScan, for each wallet it reaches that no file names,
what the explorer calls it -- and when the answer names a centralised exchange,
attribute it, saying that the attribution was read live and from where.

Three disciplines carry over from the importer (scripts/seed_tron_labels.py,
which now takes its rules from here):

- Only a tag naming a known exchange counts (CANONICAL). A tag this module does
  not recognise is reported, never guessed at; a tag naming a treasury, a
  bridge, a token or a protocol is never an exchange (NOT_AN_EXCHANGE).
- Every response is hashed into the case's evidence manifest like any other
  provider response, so the report can show what TronScan said and when.
- A failed lookup never fails a trace: TronScan being slow or refusing costs
  an attribution, not the answer the trace already has.

The same response carries a second signal, read at no extra cost: TronScan's
red "warning" tag (e.g. "Suspicious", "Scam"), and address tags naming a
scam, phishing or hack. Those are reported as a TronScan warning -- a weaker
finding than a government listing or a Tether freeze, and labelled as such.

TronScan's account endpoint needs its own API key (TRONSCAN_API_KEY, free from
tronscan.org). Without one the lookup is off and the trace says so.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from . import api_budget, config
from .evidence import EvidenceLog

logger = logging.getLogger(__name__)

TRONSCAN = "https://apilist.tronscanapi.com"
PROVIDER = "tronscan"

# Tags that name something other than a place funds are cashed out at.
NOT_AN_EXCHANGE = re.compile(
    r"(treasury|token|contract|bridge|foundation|team|burn|blackhole|black hole|justlend|sunswap|dao|"
    r"multisig|deployer|staking|validator|sr\b|super representative|exploit|hacker|scam|phish)",
    re.IGNORECASE,
)

# Tag prefixes (lower-cased, punctuation stripped) that name a centralised
# exchange, folded to the company name. Adding an exchange means adding a line
# here -- never typing an address.
CANONICAL: dict[str, str] = {
    "binance": "Binance", "okx": "OKX", "okex": "OKX", "bybit": "Bybit",
    "huobi": "Huobi / HTX", "htx": "Huobi / HTX", "kucoin": "KuCoin",
    "gate": "Gate.io", "gateio": "Gate.io", "mexc": "MEXC", "mxc": "MEXC",
    "bitget": "Bitget", "poloniex": "Poloniex", "kraken": "Kraken",
    "bitfinex": "Bitfinex", "coinbase": "Coinbase", "crypto": "Crypto.com",
    "cryptocom": "Crypto.com", "bitmart": "BitMart", "coindcx": "CoinDCX",
    "wazirx": "WazirX", "zebpay": "ZebPay", "giottus": "Giottus",
    "whitebit": "WhiteBIT", "bingx": "BingX", "lbank": "LBank", "hitbtc": "HitBTC",
    "upbit": "Upbit", "bithumb": "Bithumb", "coinex": "CoinEx", "xt": "XT.com",
    "phemex": "Phemex", "deepcoin": "Deepcoin", "bitstamp": "Bitstamp",
    "gemini": "Gemini", "bitkub": "Bitkub", "coinone": "Coinone", "korbit": "Korbit",
    "bitrue": "Bitrue", "hotbit": "Hotbit", "ascendex": "AscendEX", "bittrex": "Bittrex",
    "digifinex": "DigiFinex", "pionex": "Pionex", "toobit": "Toobit", "weex": "WEEX",
    "bitvavo": "Bitvavo", "bitpanda": "Bitpanda", "nexo": "Nexo", "backpack": "Backpack",
    "coinspot": "CoinSpot", "fixedfloat": "FixedFloat", "ueex": "UEEx",
    "flipster": "Flipster", "ourbit": "OURBIT", "onus": "ONUS", "westwallet": "WestWallet",
    "heleket": "Heleket",
}

# How many unlabelled wallets one trace will ask about. Each is a request, so
# the cap bounds what a lookup can add to a trace; the most valuable go first.
MAX_LOOKUPS_PER_TRACE = 60
# Lookups after the walk run a few at a time; the shared throttle still spaces
# the requests themselves, so this hides network wait without raising the rate.
SWEEP_WORKERS = 4


def tag_head(tag: str) -> str:
    head = re.split(r"[-:_(]| hot| cold| wallet| exchange| deposit|\d", tag, maxsplit=1, flags=re.I)[0]
    head = re.sub(r"\.(com|io|net)$", "", head.strip().lower())
    return re.sub(r"[^a-z]", "", head)


def wallet_type(tag: str) -> str:
    lowered = tag.lower()
    if "cold" in lowered:
        return "cold_wallet"
    if "deposit" in lowered:
        return "deposit_wallet"
    if "hot" in lowered:
        return "hot_wallet"
    return "exchange_wallet"


def exchange_for_tag(tag: str | None) -> str | None:
    """The exchange a TronScan tag names, or None if it names none we know."""
    if not tag or NOT_AN_EXCHANGE.search(tag):
        return None
    return CANONICAL.get(tag_head(tag))


# An address tag that is itself a warning, rather than a name.
WARNING_TAG = re.compile(r"(scam|phish|fraud|hacker|exploit|drainer|fake)", re.IGNORECASE)


def warning_from_response(body: Any) -> str | None:
    """TronScan's warning about an address: its red tag, else a tag naming a scam."""
    if not isinstance(body, dict):
        return None
    red = body.get("redTag")
    if isinstance(red, str) and red.strip():
        return red.strip()
    tag = tag_from_response(body)
    return tag if tag and WARNING_TAG.search(tag) else None


def tag_from_response(body: Any) -> str | None:
    """The address tag in a TronScan account response.

    TronScan's listings carry it as `addressTag`; the account endpoint is read
    the same way, with its other tag fields as fallbacks, and only a string
    that is actually there counts.
    """
    if not isinstance(body, dict):
        return None
    for key in ("addressTag", "publicTag", "tag"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class TronScanTags:
    """Per-trace reader of TronScan address tags, cached across traces."""

    def __init__(self, api_key: str | None, evidence: EvidenceLog | None = None,
                 client: httpx.Client | None = None, min_interval: float = 0.25,
                 timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.evidence = evidence
        self.min_interval = min_interval
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout, headers={
            "Accept": "application/json", "User-Agent": "Exchequer/1.0",
            **({"TRON-PRO-API-KEY": api_key} if api_key else {}),
        })
        self._cache = api_budget.get_cache("tronscan:tags", lambda: api_budget.ResponseCache(
            ttl_seconds=config.API_CACHE_TTL_SECONDS, max_entries=20000, path=config.API_CACHE_PATH))
        self._lock = threading.Lock()
        self._last = 0.0
        self.lookups = 0
        self.failures = 0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def tag(self, address: str) -> str | None:
        """TronScan's tag for `address`, or None (no tag, lookup off, or failed)."""
        return (self.account(address) or {}).get("tag")

    def account(self, address: str) -> dict[str, str | None] | None:
        """{"tag", "warning"} TronScan holds for `address`; None if off or failed."""
        if not self.enabled:
            return None
        key = ("tronscan-account", address)
        request = f"GET {TRONSCAN}/api/accountv2?address={address}"
        hit, value = self._cache.get(key)
        if hit:
            if self.evidence is not None:
                self.evidence.record_cached(PROVIDER, request, self._cache.meta(key))
            return value
        self._throttle()
        self.lookups += 1
        try:
            response = self._client.get(f"{TRONSCAN}/api/accountv2", params={"address": address})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.failures += 1
            logger.warning("TronScan tag lookup failed for %s: %s", address, exc)
            return None
        value = {"tag": tag_from_response(body), "warning": warning_from_response(body)}
        meta = None
        if self.evidence is not None:
            rec = self.evidence.record(PROVIDER, request, response.content)
            meta = {"retrieved_at": rec.retrieved_at, "sha256": rec.sha256, "bytes": rec.bytes}
        self._cache.put(key, value, meta)
        return value


class LiveTronExchanges:
    """Exchange wallets a Tron trace identified from TronScan tags as it ran."""

    def __init__(self, tags: TronScanTags, is_labelled) -> None:
        self.tags = tags
        self.is_labelled = is_labelled
        self.found: dict[str, dict[str, str]] = {}
        self.unrecognised: dict[str, str] = {}
        self.warnings: dict[str, str] = {}
        self._asked: set[str] = set()
        self._lock = threading.Lock()

    def is_exchange(self, address: str) -> bool:
        """For the traversal: stop at a wallet TronScan tags as an exchange."""
        if not self.tags.enabled or self.is_labelled(address):
            return False
        if self._claim(address):
            self._ask(address)
        return address in self.found

    def sweep(self, graph) -> None:
        """After the walk: ask about the wallets the traversal never checked --
        the last hop above all -- most valuable first, within the cap.

        Only wallets closer to the reported address than the nearest exchange
        the label file already found are worth asking about: a tag further out
        could not produce a nearer attribution, so asking would only cost time.
        """
        if not self.tags.enabled:
            return
        # The reported address itself: only its warning is wanted -- it is where
        # the trace starts, never an attribution.
        seed = next((n for n, data in graph.nodes(data=True) if data.get("is_seed")), None)
        if seed is not None and self._claim(seed):
            warning = (self.tags.account(seed) or {}).get("warning")
            if warning:
                with self._lock:
                    self.warnings[seed] = warning
        labelled_depths = [data.get("depth", 0) for n, data in graph.nodes(data=True)
                           if not data.get("is_seed") and (self.is_labelled(n) or n in self.found)]
        horizon = min(labelled_depths) if labelled_depths else None
        pending = [
            (sum(e.get("value_native", 0.0) for _, _, e in graph.in_edges(n, data=True)), n)
            for n, data in graph.nodes(data=True)
            if not data.get("is_seed") and n not in self._asked and not self.is_labelled(n)
            and (horizon is None or data.get("depth", 0) < horizon)
        ]
        todo = [a for _, a in sorted(pending, reverse=True) if self._claim(a)]
        if todo:
            with ThreadPoolExecutor(max_workers=SWEEP_WORKERS) as pool:
                list(pool.map(self._ask, todo))

    def _claim(self, address: str) -> bool:
        """Reserve one lookup for `address` if it is new and the cap allows."""
        with self._lock:
            if address in self._asked or len(self._asked) >= MAX_LOOKUPS_PER_TRACE:
                return False
            self._asked.add(address)
            return True

    def _ask(self, address: str) -> None:
        account = self.tags.account(address) or {}
        tag, warning = account.get("tag"), account.get("warning")
        exchange = exchange_for_tag(tag)
        with self._lock:
            if warning:
                self.warnings[address] = warning
            if exchange:
                self.found[address] = {"exchange": exchange, "label": f"{tag} (TronScan tag, read live)",
                                       "type": wallet_type(tag)}
            elif tag:
                self.unrecognised[address] = tag

    def risk_labels(self, category: str) -> dict[str, dict[str, str]]:
        """The warnings, as risk-label records for the risk matcher."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        return {
            address: {"category": category, "entity": f"TronScan: {warning}",
                      "label": f"Tagged \u201c{warning}\u201d by TronScan",
                      "source": f"TronScan public address tag, read live {day}"}
            for address, warning in self.warnings.items()
        }

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.tags.enabled,
            "asked": len(self._asked),
            "requests": self.tags.lookups,
            "failures": self.tags.failures,
            "found": [{"address": a, **m} for a, m in sorted(self.found.items())],
            "unrecognised_tags": [{"address": a, "tag": t} for a, t in sorted(self.unrecognised.items())],
            "warnings": [{"address": a, "warning": w} for a, w in sorted(self.warnings.items())],
        }
