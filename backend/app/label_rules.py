"""How a label-store row reads: its evidence tier, and text fit for a report.

The label store (app/label_store.py) is built offline from the hunt's CSV and
shipped as a pinned release, so these rules run twice: when a store is built
(scripts/build_label_store.py), and again on every row read, so a store that
is already released reads correctly without a rebuild.

  * The evidence tier comes from who published a row, not from the hunt
    category: a machine-learning training set or a crowd-sourced list is
    never "published threat intelligence", and a list someone else published
    is never "on-chain detection" (that is our own detectors).
  * Source text never names a team member. A report cites a method a reader
    can check, not a person.
  * A list's literal "null" (or "none", "n/a", ...) is no entity name.
"""
from __future__ import annotations

import re
from functools import lru_cache

POISONING = "poisoning"

# Evidence tiers, strongest first; label_store.TIERS words them.
GOVERNMENT, ISSUER, PUBLISHED, DETECTION, UNVETTED = 1, 2, 3, 4, 5

# Our own detectors: the BigQuery scans, the Etherscan/NodeReal/Tenderly/Alchemy/
# TronGrid runs and the operator expansion.
ON_CHAIN_DETECTOR = re.compile(r"poisoning (?:detection|via)|operator expansion", re.I)

# The hunt joins a row's sources with " ; ". Each source is matched at its start
# against this list, and a row's tier is its strongest source's. A source not
# listed is unknown: the build refuses it until a line here says what it is.
SOURCE_TIERS: tuple[tuple[re.Pattern[str], int], ...] = tuple((re.compile(p), t) for p, t in (
    # A government or court record.
    (r"FBI\b", GOVERNMENT),
    (r"OpenSanctions us_fbi", GOVERNMENT),
    (r"DOJ\b", GOVERNMENT),
    (r"Threat-intel report: DOJ\b", GOVERNMENT),
    (r"Threat-intel report: (?:Texas State Securities Board|Washington DFI)\b", GOVERNMENT),
    # A stablecoin issuer's own freeze, replayed from its contract.
    (r"\S+(?: Tron)? (?:contract )?freeze(?:/restriction)? events\b", ISSUER),
    # Published research, or an explorer's own tag.
    (r"Elliptic\b", PUBLISHED),
    (r"Threat-intel report: (?:Check Point|Sophos|SlowMist|CertiK|Unit 42|Global Ledger)\b", PUBLISHED),
    (r"Laundering source: SlowMist\b", PUBLISHED),
    (r"DeFiHackLabs\b", PUBLISHED),
    (r"Poison-Hunter CCS24\b", PUBLISHED),
    (r"Xia et al\. ", PUBLISHED),
    # An academic set that cites court records; the record itself is not cited.
    (r"Mendeley judicial ground-truth labels\b", PUBLISHED),
    (r"Explorer tag via dawsbot/eth-labels\b", PUBLISHED),
    # Our own on-chain detection.
    (r"\w+ (?:poisoning (?:detection|via)|operator expansion)\b", DETECTION),
    # Community reports and machine-learning datasets: listed, never checked.
    (r"HF ethereum_fraud_dataset\b", UNVETTED),
    (r"ScamSniffer\b", UNVETTED),
    (r"MyEtherWallet darklist\b", UNVETTED),
    (r"Chainabuse\b", UNVETTED),
    (r"Forta labelled-datasets\b", UNVETTED),
    (r"Threat-intel report: (?:Codatta|EtherAddressLookup|California DFPI Crypto Scam Tracker)\b", UNVETTED),
))
# Pieces of a stored source text that are citations, not sources.
_CITATION = re.compile(r"https?://|label:")


def _pieces(text: str) -> list[str]:
    return [p for p in (piece.strip() for piece in (text or "").split(" ; ")) if p and not _CITATION.match(p)]


def _piece_tier(piece: str) -> int | None:
    for pattern, tier in SOURCE_TIERS:
        if pattern.match(piece):
            return tier
    return None


@lru_cache(maxsize=65536)
def source_tier(text: str) -> int | None:
    """The strongest tier among the sources in `text`, or None if none is known."""
    tiers = [t for t in map(_piece_tier, _pieces(text)) if t is not None]
    return min(tiers) if tiers else None


@lru_cache(maxsize=65536)
def unknown_sources(text: str) -> tuple[str, ...]:
    """The sources in `text` that SOURCE_TIERS does not place."""
    pieces = _pieces(text)
    if not pieces:
        return ("(no source)",)
    return tuple(p for p in pieces if _piece_tier(p) is None)


def evidence_tier(category: str, source: str, claimed: int) -> int:
    """A row's tier: what its sources support, never more than `claimed`.

    `claimed` is the tier the hunt category gives (when building) or the tier
    a store was built with (when reading). A poisoning row is on-chain
    detection only when one of our detectors found it; a list someone else
    published is at best published intelligence, whatever branch filed it.
    """
    derived = source_tier(source)
    if category == POISONING:
        if derived is None:
            return PUBLISHED if claimed == DETECTION else claimed
        return max(derived, PUBLISHED)
    return claimed if derived is None else max(claimed, derived)


# -- text a report may quote ------------------------------------------------------
# Hunt lanes are named after the people who ran them; extend as lanes are added.
INTERNAL_NAMES = re.compile(r"\b(?:mukesh|suresh)\b", re.I)
_NAME = INTERNAL_NAMES.pattern
_REWRITES = (
    (re.compile(rf"\s*\({_NAME}\)", re.I), ""),            # "Laundering source (X): ..."
    (re.compile(rf"\({_NAME},\s*", re.I), "("),            # "(X, operator-level verification)"
    (re.compile(rf",\s*{_NAME}\)", re.I), ")"),            # "(on-chain replay, X)"
    (re.compile(rf"\s+by\s+{_NAME}", re.I), ""),           # "poisoning detection by X"
    (re.compile(rf"\s*{_NAME}", re.I), ""),                # anything else
)


@lru_cache(maxsize=65536)
def public_text(text: str) -> str:
    """`text` with every internal name taken out; the method it names stays."""
    if not INTERNAL_NAMES.search(text or ""):
        return text
    for pattern, repl in _REWRITES:
        text = pattern.sub(repl, text)
    return text.strip()


NULL_LIKE = frozenset({"null", "none", "nan", "n/a", "na", "-", "—", "?", "undefined"})


def clean_text(value: str | None) -> str:
    """`value` stripped, or "" when a list wrote "null", "none", "n/a" or the like."""
    v = (value or "").strip()
    return "" if v.lower() in NULL_LIKE else v


# What a row is called when its list gave no entity name.
DEFAULT_ENTITY = {
    "scam": "Reported scam wallet",
    "stolen": "Wallet tied to a theft",
    "laundering": "Wallet named as moving illicit proceeds",
    "poisoning": "Address-poisoning operator",
    "frozen": "Frozen by its token's issuer",
    "mixer": "Mixer",
}
