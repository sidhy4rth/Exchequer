"""What an importer may do to a label file that other importers also write.

Several label files are built by more than one script: the threat files by the
explorer-tag run and by --scam-lists, the BSC exchange file by seed_bsc_labels,
import_eth_labels and port_evm_labels, the router file by seed_router_labels
and by hand. An importer that rebuilt such a file from its own source alone
deleted everything the others had merged in, and exited 0. So each importer
replaces only the entries it owns, keeps the rest, and refuses to shrink its
own share by more than a handful without being told to.

An entry whose check failed is "unknown", never "no": it keeps its last known
state.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable

SHRINK_SHARE = 0.10
SHRINK_MIN = 5
JOIN = " && then "


class ShrinkRefused(RuntimeError):
    """An importer would remove more of its own entries than a re-run plausibly should."""


def merge_owned(
    held: dict[str, dict],
    fresh: dict[str, dict],
    owned: Callable[[str, dict], bool],
    unknown: set[str] | frozenset[str] = frozenset(),
    allow_shrink: bool = False,
) -> tuple[dict[str, dict], Counter]:
    """`held` with this importer's entries replaced by `fresh`; everything else kept.

    An entry is this importer's when `owned(address, entry)`. One it no longer
    produces is removed, unless its check failed this run (`unknown`), which
    keeps it. Raises ShrinkRefused when more than max(SHRINK_MIN, 10%) of its
    own entries would go, unless `allow_shrink`.
    """
    labels: dict[str, dict] = {}
    counts: Counter = Counter()
    own_before = 0
    for address, entry in held.items():
        mine = owned(address, entry)
        own_before += mine
        if address in fresh:
            continue
        if mine and address not in unknown:
            counts["removed"] += 1
            continue
        labels[address] = entry
        counts["kept, check failed" if mine else "kept from other importers"] += 1
    for address, entry in fresh.items():
        counts["replaced" if address in held else "added"] += 1
        labels[address] = entry
    if not allow_shrink and counts["removed"] > max(SHRINK_MIN, own_before * SHRINK_SHARE):
        raise ShrinkRefused(f"would remove {counts['removed']} of its own {own_before} entries; "
                            "re-run with --allow-shrink if the source really dropped them")
    return labels, counts


def chain_regenerate(current: str | None, *commands: str) -> str:
    """`regenerate_with` naming every contributing command once, in order."""
    steps = [s for s in (current or "").split(JOIN) if s]
    for command in commands:
        if command not in steps:
            steps.append(command)
    return JOIN.join(steps)
