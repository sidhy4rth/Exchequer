"""Matches addresses in a trace against sanctioned entities, mixers and stolen funds.

This answers a different question from `exchange_matcher`. That module asks
"where was the money cashed out", which is the end of the trail. This one asks
"what did the money touch on the way", which is what determines whether a case
is ordinary fraud or something an investigator must escalate.

The categories, with very different investigative meaning:

  sanctioned  The address is on a published sanctions list. For an Indian
              investigator this is the point at which a fraud case acquires an
              international dimension, because the counterparty is a
              designated entity rather than an anonymous wallet.

  seized      A government seizure or forfeiture order names the wallet
              (Israel's NBCTF orders): one government's measure against it,
              often time-limited, not a sanctions designation. A dated order
              carries valid_until and is not matched after that day.

  mixer       The address is a tumbler: it pools deposits from many users and
              pays out from that pool, deliberately severing the link between
              input and output.

  frozen      A stablecoin's issuer has frozen the address. In the label
              files, always Tether's USDT, as recorded by the USDT contract's
              own blacklist events; the on-disk store adds other issuers'
              freezes (Circle's USDC, Paxos's PYUSD, ...), and each match
              carries its token and issuer so nothing calls those Tether's.
              The issuer acted on it -- after a sanctions match, a
              law-enforcement request or a theft; the event does not say which.

  stolen      The address is a wallet a tag names as the perpetrator of a
              known hack or exploit (e.g. "WazirX Exploiter 3"). Funds that
              touch one are commingled with the proceeds of that theft, which
              ties a fraud case to a larger, already-documented laundering
              operation. A scam or phishing list's report is `scam`, not this.

  reported    Tron only, read live: TronScan's own warning tag on the address
              ("Suspicious", "Scam", a phishing tag). The weakest of the five
              -- an explorer's warning, not a designation, a freeze or a named
              theft -- and worded that way.

  gambling    A casino or betting platform's wallet: an attribution, like an
              exchange, not a designation.

  poisoning   From the on-disk label store (app/label_store.py), with
  scam        the evidence behind each row: an address-poisoning lookalike
  laundering  (on-chain detection), a wallet a report or court record ties to
              a scam, or one named as moving illicit proceeds. The store is
              consulted only for addresses no label file names.

The authority behind them is not the same. A sanctioned address is on a
government list -- OFAC's, or another government's (the international file:
UK, EU, Japan, France; Israel's orders are seized); mixer pools and stolen-funds wallets come
from the explorer's own public tags (the threat file), a strong attribution
but not a designation. Each match carries its source so a report never
blurs the two, and where an address is in both, the government entry is kept.
An address several governments list keeps every one of them in its source,
because "designated by the US, the UK and the EU" is a stronger finding than
any one of those alone.

The mixer category carries a consequence the exchange labels do not have, and
it is the reason this module exists rather than being another label type.
**A trace must stop at a mixer.** Following outgoing transfers from a tumbler
does not follow the money -- the outputs are funded from a commingled pool and
have no established relationship to the deposit we arrived on. Expanding
through one would manufacture a trail that the transactions do not support,
and would then hand an investigator a confident-looking graph built on a false
premise. Stopping and saying so is the honest answer.

The matching rule is identical to the exchange matcher's, and identical for
the same reason: an exact lookup of the address in a data file a human can
open and read. An address is called sanctioned if and only if a published
government list says so.
"""
from __future__ import annotations

import json
import logging
import os
import re
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

from . import config
from .etherscan_client import is_tron_address, is_valid_address, normalize_address
from .graph_builder import OUTGOING
from .label_store import LabelStore, get_label_store

logger = logging.getLogger(__name__)

SANCTIONED = "sanctioned"
# A government seizure or forfeiture order on the wallet: a measure, not a designation.
SEIZED = "seized"
MIXER = "mixer"
STOLEN = "stolen"
FROZEN = "frozen"
# A gambling platform's wallet (hot wallet or per-user deposit address). Not a
# designation and not a dead end: like an exchange, the platform holds the
# account behind the deposit, so the next step is a lawful request to it.
GAMBLING = "gambling"
# The three below come from the on-disk label store (app/label_store.py),
# though a label file may use them too.
# A lookalike address planted in a victim's history by an address-poisoning
# scam, found by on-chain detection: funds arriving were most likely sent to
# the scammer by mistake.
POISONING = "poisoning"
# A wallet a published report, scam database or court record attributes to a
# scam, phishing drainer or fraudulent platform.
SCAM = "scam"
# A wallet a court filing or published investigation names as moving illicit
# proceeds.
LAUNDERING = "laundering"
# Read live during a Tron trace, never from a label file, so not in CATEGORIES.
REPORTED = "reported"
CATEGORIES = (SANCTIONED, SEIZED, MIXER, FROZEN, STOLEN, GAMBLING, POISONING, SCAM, LAUNDERING)
# Categories a government list gives: an address several such lists name keeps every source.
GOVERNMENT = frozenset({SANCTIONED, SEIZED})

# Categories whose addresses end a trace. See the module docstring: a mixer
# breaks the link between deposit and withdrawal, so anything past it is not
# the same money in any sense a report could defend.
TERMINAL_CATEGORIES = frozenset({MIXER})

# Where a match came from when it is not a label file (a file's own name).
LABEL_STORE_ORIGIN = "label_store"
# The entity scripts/import_tether_freezes.py writes for every USDT blacklist entry.
TETHER_FREEZE_ENTITY = "Tether (USDT freeze)"
# "USDC frozen by Circle", "PYUSD frozen by Paxos (PYUSD)", "XSGD frozen by its
# issuer", "USDT frozen by Tether on 2021-08-05", "sUSDe holder restricted by issuer (...)".
_FREEZE_TEXT = re.compile(r"^(?P<token>[A-Za-z0-9.]+) (?:frozen|holder restricted) by (?P<issuer>.+?)"
                          r"(?: on \d{4}-\d{2}-\d{2})?(?: \([^)]*\))?$")


def freeze_issuer(*texts: str | None) -> tuple[str | None, str | None]:
    """(token, issuer) named by a freeze's entity or label; None where unsaid."""
    for text in texts:
        text = (text or "").strip()
        if text == TETHER_FREEZE_ENTITY:
            return "USDT", "Tether"
        found = _FREEZE_TEXT.match(text)
        if found:
            issuer = found["issuer"].strip()
            return found["token"], None if issuer in ("its issuer", "issuer", "a token issuer") else issuer
    return None, None


def freeze_parts(match: dict[str, Any]) -> tuple[str | None, str | None]:
    """A frozen match's (token, issuer): as recorded, or read from its text on
    a case stored before they were."""
    if "token" in match or "issuer" in match:
        return match.get("token"), match.get("issuer")
    return freeze_issuer(match.get("entity"), match.get("label"))


def is_tether_usdt_freeze(match: dict[str, Any]) -> bool:
    """Tether froze this address's USDT. Only such a freeze may be called one
    in a letter to Tether or in the report's summary: the store's 4,000-odd
    freezes are other issuers' (USDC, XSGD, PYUSD, USDT0, ...). Exact token
    and issuer, never a substring, so a USDT0 freeze is not one."""
    return match.get("category") == FROZEN and freeze_parts(match) == ("USDT", "Tether")


@dataclass(frozen=True)
class RiskMatch:
    """One address in the trace that appears on a risk list."""

    address: str
    category: str  # one of CATEGORIES, or reported
    entity: str  # the designated entity or mixer service
    label: str  # human-readable, e.g. "Tornado Cash: 10 ETH pool"
    source: str  # which published list, and when it was read
    depth: int  # hops from the victim-reported address
    value_received_native: float  # value that reached it within this trace
    # Which label file (its name) or "label_store" the match came from; None
    # when read live (TronScan). A freeze also names its token and issuer.
    origin: str | None = None
    token: str | None = None
    issuer: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.category in TERMINAL_CATEGORIES

    def to_dict(self) -> dict[str, Any]:
        out = {
            "address": self.address,
            "category": self.category,
            "entity": self.entity,
            "label": self.label,
            "source": self.source,
            "depth": self.depth,
            "value_received_native": round(self.value_received_native, 6),
            "is_terminal": self.is_terminal,
            "origin": self.origin,
        }
        if self.category == FROZEN:
            out.update(token=self.token, issuer=self.issuer)
        return out

    def describe(self, native_symbol: str = "ETH") -> str:
        """One sentence an investigator can paste into a report."""
        # The label usually is the entity name; repeating it as "X (X)" reads
        # like a bug in a document meant to be quoted.
        named = self.label if self.label == self.entity else f"{self.label} ({self.entity})"

        # For the reported address itself there is no "value that reached it
        # within this trace" -- the trace starts there, so the graph holds no
        # inbound edge and the figure would always be a misleading 0.0000.
        if self.depth == 0:
            placement = "It is the reported address itself"
        else:
            hops = f"{self.depth} hop{'s' if self.depth != 1 else ''}"
            placement = (
                f"It received {self.value_received_native:.4f} {native_symbol} "
                f"within this trace, {hops} from the reported address"
            )

        if self.category == SANCTIONED:
            return (
                f"Sanctioned entity: {self.address} is listed as {named} on "
                f"{self.source}. {placement}."
            )
        if self.category == SEIZED:
            # The entity is the holder's name when the order gives one, else the order id.
            holder = "" if self.entity.startswith("NBCTF ") else f" Listed holder: {named}."
            return (
                f"Government seizure order: {self.address} is named in {self.source}.{holder} "
                f"{placement}. A seizure or forfeiture order is one "
                f"government's measure against the wallet, often time-limited, not a "
                f"sanctions designation; it is not a finding that any counterparty took "
                f"part in anything."
            )
        if self.category == FROZEN:
            # The USDT blacklist file is Tether's; the label store adds other
            # issuers' freezes (Circle's USDC, PayPal's PYUSD, ...), whose entity
            # names the token and the issuer.
            token, issuer = ((self.token, self.issuer) if self.origin
                             else freeze_issuer(self.entity, self.label))
            if issuer is None and token is None and "tether" in f"{self.label} {self.source}".lower():
                issuer = "Tether"  # an older record that names nothing else
            issuer = issuer or "the token's issuer"
            by = f"{issuer} ({token})" if token else issuer
            return (
                f"Frozen by {by}: {self.address} — {self.label}, per {self.source}. "
                f"{placement}. The issuer acted on this address; the freeze does not "
                f"say why, and it is not a finding that any counterparty took part in "
                f"anything. {issuer[0].upper() + issuer[1:]} can say, on a lawful request."
            )
        if self.category == POISONING:
            return (
                f"Address poisoning: {self.address} is a lookalike address used in an "
                f"address-poisoning scam ({self.label}), per {self.source}. {placement}. "
                f"The scam plants a near-identical address in a victim's transaction "
                f"history so that it is copied by mistake; funds sent here most likely "
                f"went to the scammer in error. This is an on-chain detection, not a "
                f"designation."
            )
        if self.category == SCAM:
            return (
                f"Reported scam: {self.address} is attributed as {named} by "
                f"{self.source}. {placement}. The source ties the wallet to a scam or "
                f"fraud; it is not a sanctions designation, and not a finding that any "
                f"other counterparty took part in it."
            )
        if self.category == LAUNDERING:
            return (
                f"Laundering: {self.address} is identified as {named} by "
                f"{self.source}. {placement}. The source names the wallet as moving "
                f"illicit proceeds; it is not a sanctions designation, and not a "
                f"finding that any other counterparty took part in it."
            )
        if self.category == REPORTED:
            return (
                f"Warning tag: {self.address} is tagged \u201c{self.entity.removeprefix('TronScan: ')}\u201d by "
                f"TronScan, the Tron block explorer ({self.source}). {placement}. "
                f"This is the explorer's warning, not a designation or a finding "
                f"that anyone took part in anything; it is a reason to look closer."
            )
        if self.category == GAMBLING:
            return (
                f"Gambling platform: {self.address} is {named}, per {self.source}. "
                f"{placement}. The funds reached a wallet that a gambling platform "
                f"controls; the platform holds the account behind it and can identify "
                f"the account holder on a lawful request. This is an attribution of "
                f"the wallet, not a finding that any counterparty broke the law."
            )
        if self.category == STOLEN:
            return (
                f"Stolen funds: {self.address} is tagged as {named} by "
                f"{self.source}. {placement}. Funds that pass through it are "
                f"commingled with the proceeds of that theft; the tag is that "
                f"source's attribution, not a finding that any counterparty "
                f"took part in it."
            )
        return (
            f"Mixer: {self.address} is {named}, per {self.source}. {placement}. "
            f"The trace stops here — a mixer pays out from a commingled pool, "
            f"so transfers leaving it have no established link to the funds "
            f"that arrived."
        )


class RiskMatcher:
    """Exact-match lookup of addresses against the risk-label database."""

    def __init__(
        self,
        labels: dict[str, dict[str, str]] | None = None,
        chain: str | None = None,
        store: LabelStore | None = None,
    ) -> None:
        self._labels: dict[str, dict[str, str]] = labels or {}
        self.chain = chain or config.DEFAULT_CHAIN.key
        # The on-disk store is consulted only for addresses no file names, so
        # a curated or government label always outranks a scan result.
        self.store = store

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_file(
        cls,
        path: Path | None = None,
        chain: str | None = None,
        extra_paths: tuple[Path | None, ...] = (),
        store: LabelStore | None = None,
    ) -> "RiskMatcher":
        """Load one chain's risk labels.

        `path` is the OFAC file; `extra_paths` follow in order of authority
        (other governments' lists, then the explorer-tag threat file). An
        address already loaded is never overwritten, so a government
        designation always wins over an explorer tag; when two lists both
        sanction it, the later list is appended to the source.

        A missing file is not an error. Risk labels are an overlay on the
        trace: without them a trace still runs and still attributes an
        exchange, it just cannot warn about what the funds passed through.
        """
        if path is None:
            logger.warning("No risk label path given; risk screening disabled")
        labels: dict[str, dict[str, str]] = {}
        for index, source_path in enumerate((path, *extra_paths)):
            if source_path is None:
                continue
            for address, meta in _read_labels(source_path, required=index == 0).items():
                held = labels.setdefault(address, meta)
                if held is not meta and meta["category"] == MIXER and held["category"] != MIXER:
                    # Stopping at a mixer is a correctness rule, not a matter of
                    # authority: Tether freezing a Tornado Cash pool does not make
                    # its payouts traceable. The mixer label takes the address.
                    labels[address] = {**meta, "source": f"{meta['source']}; also {held['label']}, per {held['source']}"}
                    continue
                if (
                    held is not meta
                    and held["category"] in GOVERNMENT and meta["category"] in GOVERNMENT
                    and meta["source"] not in held["source"]
                ):
                    held["source"] = f"{held['source']}; also {meta['source']}"
        return cls(labels, chain=chain, store=store)

    # -- lookup ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._labels) + (sum(self.store.counts(self.chain).values()) if self.store else 0)

    @property
    def entities(self) -> list[str]:
        """Distinct entities covered, for the /risk-labels endpoint."""
        return sorted({meta["entity"] for meta in self._labels.values()})

    def counts_by_category(self) -> dict[str, int]:
        counts = {category: 0 for category in CATEGORIES}
        for meta in self._labels.values():
            counts[meta["category"]] = counts.get(meta["category"], 0) + 1
        if self.store:
            # The store's figures are counted when it is built; an address a
            # file also names is counted twice, a small overstatement of
            # coverage that never changes what a trace reports.
            for category, n in self.store.counts(self.chain).items():
                counts[category] = counts.get(category, 0) + n
        return counts

    def store_entry(self) -> dict[str, Any] | None:
        """The label store this matcher screens against, as a case records it; None without one."""
        return label_store_entry(self.store, self.chain)

    def lookup(self, address: str) -> dict[str, str] | None:
        address = normalize_address(address)
        meta = self._labels.get(address)
        if meta is not None and _lapsed(meta, date.today()):
            meta = None  # its order ended after this process loaded the file
        if meta is None and self.store is not None:
            meta = self.store.lookup(self.chain, address)
            if meta is not None and meta["category"] not in CATEGORIES:
                return None
            if meta is not None:
                meta = {**meta, "origin": LABEL_STORE_ORIGIN}
        return meta

    def entries(self) -> list[tuple[str, dict[str, str]]]:
        """Every (address, record) pair in the label files, for anything that
        lists the database. The on-disk store is not listed: it holds millions."""
        return list(self._labels.items())

    def is_flagged(self, address: str) -> bool:
        return self.lookup(address) is not None

    def is_terminal(self, address: str) -> bool:
        """True if a trace must stop expanding at `address`.

        Passed to the graph builder alongside the exchange matcher's own
        terminal test. Only mixers qualify: a sanctioned address is still an
        ordinary wallet whose outgoing transfers mean exactly what they say,
        so there is no reason to stop following the money there.
        """
        meta = self.lookup(address)
        return bool(meta) and meta["category"] in TERMINAL_CATEGORIES

    # -- graph annotation --------------------------------------------------
    def annotate(self, graph: nx.DiGraph, direction: str = OUTGOING) -> list[RiskMatch]:
        """Tag every risk-listed address in `graph` and return the matches.

        Sorted by depth (closest to the victim first), then by value, matching
        the exchange matcher so both lists read the same way in a report.
        """
        matches: list[RiskMatch] = []

        for node, data in graph.nodes(data=True):
            meta = self.lookup(node)
            if meta is None:
                continue

            edges = (
                graph.in_edges(node, data=True) if direction == OUTGOING
                else graph.out_edges(node, data=True)
            )
            value_in = sum(edge.get("value_native", 0.0) for _, _, edge in edges)
            data["risk_category"] = meta["category"]
            data["risk_entity"] = meta["entity"]
            data["risk_label"] = meta["label"]
            data["risk_source"] = meta["source"]
            data.setdefault("flags", set()).add(meta["category"])
            if meta["category"] in TERMINAL_CATEGORIES:
                data["is_terminal"] = True

            token, issuer = (freeze_issuer(meta["entity"], meta["label"]) if meta["category"] == FROZEN
                             else (None, None))
            matches.append(
                RiskMatch(
                    address=node,
                    category=meta["category"],
                    entity=meta["entity"],
                    label=meta["label"],
                    source=meta["source"],
                    depth=data.get("depth", 0),
                    value_received_native=value_in,
                    origin=meta.get("origin"),
                    token=token,
                    issuer=issuer,
                )
            )

        matches.sort(key=lambda m: (m.depth, -m.value_received_native))
        return matches


def get_risk_matcher(chain_key: str | None = None) -> RiskMatcher:
    """Risk matcher for one chain. Cached so each label file is read once."""
    return _risk_matcher(config.get_chain(chain_key).key)


# Cached on the chain's own key, not on the caller's spelling of it (None,
# "eth", "ethereum"), so a chain's files are held once.
@lru_cache(maxsize=None)
def _risk_matcher(key: str) -> RiskMatcher:
    chain = config.get_chain(key)
    return RiskMatcher.from_file(
        chain.risk_labels_path,
        chain=chain.key,
        extra_paths=(chain.intl_sanctions_path, chain.frozen_labels_path, chain.threat_labels_path,
                     chain.gambling_labels_path),
        store=get_label_store(),
    )


def clear_label_caches() -> None:
    """Forget every loaded label file, so the next call reads them again (tests)."""
    from . import exchange_matcher
    for cached in (_risk_matcher, _list_meta, _list_ends, exchange_matcher._matcher,
                   exchange_matcher._router_matcher):
        cached.cache_clear()


# -- how old each list was -------------------------------------------------------
# (chain attribute, name, whether an age limit means anything). The last two are
# fixed snapshots, not refreshed nightly, so a warning on them could never clear.
LISTS = (
    ("risk_labels_path", "OFAC SDN list", True),
    ("intl_sanctions_path", "Other governments' sanctions lists and seizure orders", True),
    ("frozen_labels_path", "Tether USDT freezes", True),
    ("threat_labels_path", "Mixer and stolen-funds tags", False),
    ("gambling_labels_path", "Gambling platform wallets", False),
    ("labels_path", "Exchange wallet labels", False),
)
# The on-disk store (label_store.py) is screened too, after the files. It is a
# build, replaced with each release, so it is named by when and from what it
# was built rather than by a list date.
STORE_LIST = "Flagged-address label store"
_HELD = object()  # list_freshness: the store this server holds, not one a case recorded
# OFAC names neither chain; scripts/port_evm_labels.py builds their risk files.
CARRIED_CHAINS = {"polygon", "arbitrum"}
CARRIED_NAME = "OFAC and other governments' sanctions lists, carried over from Ethereum"

UPDATED_NOTE = ("Updated after this case was traced: the trace used an earlier version this "
                "report cannot name. Re-run it to screen against this one.")
SNAPSHOT_NOTE = "A fixed snapshot, not refreshed nightly, so no age limit applies."


def is_stale(list_date: date | None, as_of: date) -> bool:
    """Was this list more than config.LIST_STALE_DAYS old on `as_of`?

    A list with no date counts as stale: it cannot show it was checked. Exactly
    the limit is not yet over it, and a list newer than `as_of` has no age to count.
    """
    if list_date is None:
        return True
    return (as_of - list_date).days > config.LIST_STALE_DAYS


def _iso_date(value: Any) -> date | None:
    """`last_reviewed` is ISO; OFAC publishes MM/DD/YYYY, which reads the other way round in India."""
    for layout in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), layout).date()
        except ValueError:
            continue
    return None


@lru_cache(maxsize=None)
def _list_meta(path: Path) -> dict[str, Any] | None:
    """A list file's `_meta`, or None if it is missing or unreadable. Cached: some are megabytes."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (document.get("_meta") or {}) if isinstance(document, dict) else None


@lru_cache(maxsize=None)
def _list_ends(path: Path) -> tuple[str, ...]:
    """Every valid_until in a list file, sorted: the last days of its dated orders."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    entries = document.get("labels", document) if isinstance(document, dict) else None
    if not isinstance(entries, dict):
        return ()
    ends = (_iso_date(v.get("valid_until")) for v in entries.values() if isinstance(v, dict) and v.get("valid_until"))
    return tuple(sorted(d.isoformat() for d in ends if d))


def list_freshness(chain_key: str | None, as_of: date, store: Any = _HELD) -> dict[str, Any]:
    """Each list this chain is screened against, and how old it was on `as_of`.

    `as_of` is the day the case was traced. These are the files this server holds
    now, so a list dated after the trace is reported as such, never as what the
    trace used. `store` is the label store the trace recorded
    (RiskMatcher.store_entry, None if it ran without one); left out, it is the
    one this server holds.
    """
    chain = config.get_chain(chain_key)
    lists: list[dict[str, Any]] = []
    not_held: list[str] = []
    overdue: list[str] = []
    for attribute, name, has_age_limit in LISTS:
        path = getattr(chain, attribute, None)
        meta = _list_meta(path) if path else None
        if meta is None:
            not_held.append(name)
            continue
        if attribute == "risk_labels_path" and chain.key in CARRIED_CHAINS:
            name = CARRIED_NAME
        authorities = (meta.get("counts") or {}).get("by_authority")
        if authorities:
            name = f"{name} ({', '.join(sorted(authorities))})"
        checked, published = _iso_date(meta.get("last_reviewed")), _iso_date(meta.get("ofac_publish_date"))

        state, note = "current", ""
        if checked and checked > as_of:
            state, note = "updated_since_trace", UPDATED_NOTE
        elif not has_age_limit:
            state, note = "fixed_snapshot", SNAPSHOT_NOTE
        elif is_stale(checked, as_of):
            state, note = "stale", f"Over {config.LIST_STALE_DAYS} days old when this case was traced."
            overdue.append(f"{name} ({f'checked {checked}' if checked else 'no date recorded'})")
        entry = {
            "name": name,
            "file": path.name,
            "checked": checked.isoformat() if checked else None,
            "published": published.isoformat() if published else None,
            "state": state,
            "note": note,
        }
        if has_age_limit:
            # Dated orders past their last day were held but not matched (_read_labels).
            entry["lapsed"] = bisect_left(_list_ends(path), as_of.isoformat())
            if entry["lapsed"]:
                ended = (f"{entry['lapsed']:,} listings in it had ended by {as_of.isoformat()} and were not matched."
                         if entry["lapsed"] > 1 else
                         f"1 listing in it had ended by {as_of.isoformat()} and was not matched.")
                entry["note"] = f"{note} {ended}".strip()
        lists.append(entry)
    recorded = store is not _HELD
    if not recorded:
        store = label_store_entry(get_label_store(), chain.key)
    if isinstance(store, dict) and store.get("rows"):
        lists.append(_store_freshness(store, as_of, recorded))
    else:
        not_held.append(STORE_LIST)  # no store, or nothing in it for this chain
    return {
        "as_of": as_of.isoformat(),
        "stale_after_days": config.LIST_STALE_DAYS,
        "lists": lists,
        "not_held": not_held,
        "warning": (f"Screening may have missed addresses listed recently, and may still name "
                    f"addresses whose listing has since been lifted. Over {config.LIST_STALE_DAYS} "
                    f"days old when this case was traced: {'; '.join(overdue)}.") if overdue else None,
    }


def label_store_entry(store: LabelStore | None, chain_key: str) -> dict[str, Any] | None:
    """Which label-store build screens `chain_key`: when and from what it was built, and its rows here."""
    if store is None:
        return None
    info = store.build_info()
    # The release the image fetched (Dockerfile: ENV EXCHEQUER_LABEL_STORE_TAG); None outside one.
    release = os.getenv("EXCHEQUER_LABEL_STORE_TAG", "").strip() or None
    return {"name": STORE_LIST, "file": store.path.name, "release": release, "built_at": info.get("built_at"),
            "built_from": info.get("built_from"), "rows": sum(store.counts(chain_key).values())}


def _store_freshness(store: dict[str, Any], as_of: date, recorded: bool) -> dict[str, Any]:
    built_at = str(store.get("built_at") or "")
    built = _iso_date(built_at[:10])
    release = f"Release {store['release']}, built" if store.get("release") else "Built"
    note = (f"{release} {built_at or 'at an unrecorded time'} from {store.get('built_from') or 'an unrecorded file'}; "
            f"{store['rows']:,} addresses on this chain. A build, replaced with each release, so no age limit "
            "applies.")
    state = "fixed_snapshot"
    if recorded:
        note += " Recorded when this case was traced."
    elif built and built > as_of:
        state, note = "updated_since_trace", f"{note} {UPDATED_NOTE}"
    return {"name": STORE_LIST, "file": store.get("file") or "label_store.db",
            "checked": built.isoformat() if built else None, "published": None, "state": state, "note": note,
            "release": store.get("release"), "built_at": built_at or None, "built_from": store.get("built_from"),
            "rows": store["rows"]}


_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def is_system_address(address: str) -> bool:
    """The zero address and its tiny neighbours, on an EVM chain or on Tron.

    Their 20-byte body is below 2**64: values no private key plausibly
    produces. Tokens are burned there and protocol code lives there; they are
    no one's wallet. A Tron address is that body in Base58Check (T9yD14Nj...
    is the zero address).
    """
    address = normalize_address(address)
    if address.startswith("0x"):
        body = address[2:]
    elif is_tron_address(address):
        number = 0
        for char in address:
            number = number * 58 + _BASE58.index(char)
        body = number.to_bytes(25, "big")[1:21].hex()
    else:
        return False
    try:
        return int(body or "0", 16) < 2**64
    except ValueError:
        return False


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _lapsed(meta: dict[str, str], today: date) -> bool:
    """A dated government order whose last day has passed."""
    until = meta.get("valid_until")
    return bool(until) and until < today.isoformat()


def _read_labels(path: Path, required: bool) -> dict[str, dict[str, str]]:
    """Validated {address: record} from one label file; {} if it is unusable.

    One bad entry is logged and skipped, never raised: the lifespan loads every
    chain's files, so an exception here would stop the site from starting.
    """
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        log = logger.warning if required else logger.info
        log("No risk label file at %s -- traces on this chain will not be "
            "screened against it", path)
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Risk label file at %s is not valid JSON: %s", path, exc)
        return {}

    entries = raw.get("labels", raw) if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        logger.error("Risk label file at %s: labels is not an object; file not used", path)
        return {}
    meta = raw.get("_meta")
    default_source = _text(meta.get("source")) if isinstance(meta, dict) else ""
    default_source = default_source or "unspecified list"

    labels: dict[str, dict[str, str]] = {}
    today, lapsed = date.today(), 0
    for address, value in entries.items():
        try:
            record = _read_entry(address, value, default_source)
        except (TypeError, ValueError, AttributeError) as exc:
            logger.warning("Risk entry for %r is malformed (%s); skipped", address, exc)
            continue
        if record is not None and _lapsed(record, today):
            # Its order has ended: not matched, whether or not a refresh has removed it yet.
            logger.debug("Risk entry for %s lapsed on %s; skipped", address, record["valid_until"])
            lapsed += 1
        elif record is not None:
            record["origin"] = path.name  # which file said so (request_letters names the issuer from it)
            labels[normalize_address(address)] = record

    logger.info("Loaded %d risk labels from %s%s", len(labels), path,
                f"; {lapsed} past their end date, left out" if lapsed else "")
    return labels


def _read_entry(address: Any, value: Any, default_source: str) -> dict[str, str] | None:
    """One validated record, or None (logged) if the entry must be skipped."""
    if not isinstance(address, str) or address.startswith("_"):  # metadata keys
        return None
    if not is_valid_address(normalize_address(address)):
        logger.warning("Risk entry key %r is not an address; skipped", address)
        return None
    if not isinstance(value, dict):
        logger.warning("Risk entry for %s is not an object; skipped", address)
        return None

    category = _text(value.get("category")).lower()
    if category not in CATEGORIES:
        # An unrecognised category must not silently become a warning
        # of the wrong kind. Dropping it is the safe failure.
        logger.warning(
            "Risk entry for %s has unknown category %r; skipped", address, value.get("category")
        )
        return None

    # The zero address and its tiny neighbours are where tokens are burned,
    # not anyone's wallet. No list may name one: a burn in a trace would
    # otherwise read as a finding against a party that does not exist.
    if is_system_address(address):
        logger.info("Risk entry for %s is a burn/system address, not a wallet; skipped", address)
        return None

    entity = _text(value.get("entity")) or _text(value.get("name"))
    if not entity:
        logger.warning("Risk entry for %s names no entity; skipped", address)
        return None

    record = {
        "category": category,
        "entity": entity,
        "label": _text(value.get("label")) or entity,
        "source": _text(value.get("source")) or default_source,
    }
    # The last day a dated order is in force (import_intl_sanctions).
    until = _iso_date(value.get("valid_until")) if value.get("valid_until") else None
    if until:
        record["valid_until"] = until.isoformat()
    return record
