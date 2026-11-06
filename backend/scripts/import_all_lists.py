"""Refresh the screening lists, keep only what is safe, and say what changed.

.github/workflows/refresh-lists.yml runs this every night. Each importer runs as
its own process, and its files are held in memory first, so a source that fails
or returns nonsense leaves the good list exactly as it was. One list failing
does not stop the others, because a stale OFAC list is worse than a late Tether
one.

What counts as a change
-----------------------
An address added or removed, or its category or entity changed. Nothing else:
the importers stamp today's date in `_meta`, and OFAC's publish date is inside
every entry's `source`, so comparing whole files would open a pull request every
night and teach everyone to ignore it.

When a pull request opens
-------------------------
At once for a real change. For a list that was checked and has not changed, only
once its date is RENEW_AFTER_DAYS old, so the merged date stays inside the
report's seven-day warning without a pull request a night. If nobody merges, the
warning fires, which is correct: the deployed data is what screens a trace.

What is refused
---------------
A list left empty, or one that loses more than a tenth of its addresses (and more
than a handful), is put back and the run ends red; so is a small list (under 20)
that loses a third, and a list from which every address of one authority goes. A
source changing its format looks exactly like that. If a source really did remove them, run its importer by
hand and open the pull request yourself.

Additions and changes are gated too. A list is refused when any address it adds
or changes is a token contract, a DEX router, an exchange wallet that is not a
deposit address or a burn address (app/never_flag.py), when it adds, changes or
removes an address a demo uses (re-record the demos after a hand run), or when
it adds more than a quarter of its size (at least 50) in one night. Every
address moved to `mixer`, which ends a trace, is listed in full, and so is
every changed entry with its old and new category.

What is not here
----------------
The threat and exchange lists. Both are pinned to a fixed commit, so re-running
them reads the same data, and a new date on them would be false.

    cd backend && .venv/bin/python -m scripts.import_all_lists --summary lists.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, never_flag  # noqa: E402

RENEW_AFTER_DAYS = 5
SHRINK_SHARE = 0.10
SHRINK_MIN = 5
# Under this many addresses the rule above lets nearly all go (5 of 6), so a
# third is the limit instead.
SMALL_LIST = 20
IMPORTER_TIMEOUT_SECONDS = 3600
SHOWN_PER_LIST = 50
SHOWN_CHANGED = 200
ADDED_MAX_SHARE = 4  # a night may add at most a quarter of the list ...
ADDED_MIN = 50  # ... or this many, whichever is more

CHANGED = "changed"
DATES = "dates"


@dataclass(frozen=True)
class Family:
    """One importer and the files it writes."""

    name: str
    module: str  # in scripts/
    files: tuple[Path, ...]
    needs: tuple[str, ...] = ()  # config settings it cannot run without
    args: tuple[str, ...] = ()


def families() -> tuple[Family, ...]:
    chains = config.CHAINS
    return (
        Family("OFAC SDN list", "import_ofac_addresses",
               tuple(chains[c].risk_labels_path for c in ("ethereum", "bsc", "tron"))),
        Family("Other governments' sanctions lists", "import_intl_sanctions",
               tuple(chains[c].intl_sanctions_path for c in ("ethereum", "bsc", "tron")),
               needs=("ETHERSCAN_API_KEY",)),
        Family("Tether USDT freezes", "import_tether_freezes",
               tuple(chains[c].frozen_labels_path for c in ("ethereum", "tron")),
               needs=("ETHERSCAN_API_KEY",)),
        # Last: it carries over what the Ethereum files above now hold.
        Family("Sanctions carried to Polygon and Arbitrum", "port_evm_labels",
               tuple(chains[c].risk_labels_path for c in ("polygon", "arbitrum")),
               needs=("ETHERSCAN_API_KEY",), args=("--sanctions-only",)),
    )


@dataclass(frozen=True)
class Change:
    held_reviewed: str | None
    count: int
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    altered: list[str] = field(default_factory=list)
    # What the importer says it could not check (its _meta.unverified, bsc_not_checked).
    notes: dict[str, list[str]] = field(default_factory=dict)
    # address -> ((old category, entity), (new category, entity)) for every changed one.
    was: dict[str, tuple] = field(default_factory=dict)
    to_mixer: list[str] = field(default_factory=list)

    @property
    def real(self) -> bool:
        return bool(self.added or self.removed or self.altered)


@dataclass
class Outcome:
    family: Family
    status: str  # ok | failed | refused | skipped
    detail: str = ""
    changes: dict[Path, Change] = field(default_factory=dict)
    held: dict[Path, bytes | None] = field(default_factory=dict)

    def restore(self) -> None:
        for path, raw in self.held.items():
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(raw)


def _read(raw: bytes) -> dict:
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("labels"), dict):
        raise ValueError("no labels")
    return document


def _identities(document: dict) -> dict[str, tuple]:
    """address -> what it is said to be. `source` is left out: it carries dates."""
    return {address: (entry.get("category"), entry.get("entity"))
            for address, entry in document["labels"].items()
            if not address.startswith("_") and isinstance(entry, dict)}


def _refusal(before: dict[str, tuple], after: dict[str, tuple]) -> str | None:
    if before and not after:
        return f"left it empty (it held {len(before)} addresses)"
    lost = len(before.keys() - after.keys())
    if lost > SHRINK_MIN and lost > len(before) * SHRINK_SHARE:
        return f"removed {lost} of its {len(before)} addresses"
    if len(before) < SMALL_LIST and lost >= max(2, len(before) // 3):
        return f"removed {lost} of its {len(before)} addresses"
    return None


def _authorities(document: dict) -> dict[str, int]:
    counts = ((document.get("_meta") or {}).get("counts") or {}).get("by_authority") or {}
    return counts if isinstance(counts, dict) else {}


def _vanished(before: dict, after: dict) -> list[str]:
    """Authorities that listed addresses in `before` and list none in `after`."""
    new = _authorities(after)
    return sorted(a for a, n in _authorities(before).items() if n and not new.get(a))


def _chain_of(path: Path, document: dict) -> str:
    """The chain a list file is for: its _meta, else its name (risk_labels_tron.json -> tron)."""
    chain = (document.get("_meta") or {}).get("chain")
    if chain in config.CHAINS:
        return chain
    stem = path.stem
    return next((key for key in config.CHAINS if stem.endswith(f"_{key}")), config.DEFAULT_CHAIN.key)


_EVM = re.compile(r"0x[0-9a-fA-F]{40}")
_TRON = re.compile(r"(?<![A-Za-z0-9])T[1-9A-HJ-NP-Za-km-z]{33}(?![A-Za-z0-9])")


@lru_cache(maxsize=1)
def _demo_addresses() -> frozenset[str]:
    """Every address the demos use: DEMO.md and the recorded and expected demo data."""
    text = ""
    for path in (config.BACKEND_DIR.parent / "DEMO.md", *(config.DATA_DIR / name for name in (
            "recorded_demos.json", "demo_traces.json", "demo_expectations.json"))):
        try:
            text += path.read_text(encoding="utf-8")
        except OSError:
            continue
    return frozenset({a.lower() for a in _EVM.findall(text)} | set(_TRON.findall(text)))


def _gate(path: Path, before: dict[str, tuple], after: dict, change_added: list[str],
          change_altered: list[str], change_removed: list[str]) -> str | None:
    """Why a refreshed list must not go out unread, or None."""
    chain = _chain_of(path, after)
    touched = [*change_added, *change_altered]
    hits = never_flag.screen(chain, touched)
    if hits:
        return ("names infrastructure no list may name: "
                + "; ".join(f"{a} ({why})" for a, why in sorted(hits.items())))
    demo = sorted(set(touched + change_removed) & _demo_addresses())
    if demo:
        return (f"changes {len(demo)} address(es) a demo uses: {', '.join(demo)}; run it by hand "
                "and re-record with check_demos.py --record")
    if before and len(change_added) > max(ADDED_MIN, len(before) // ADDED_MAX_SHARE):
        return f"added {len(change_added)} to a list of {len(before)} in one night; run it by hand"
    return None


def run_module(family: Family) -> int:
    command = [sys.executable, "-m", f"scripts.{family.module}", *family.args]
    try:
        return subprocess.run(command, cwd=config.BACKEND_DIR, timeout=IMPORTER_TIMEOUT_SECONDS, check=False).returncode
    except subprocess.TimeoutExpired:
        print(f"{family.name}: gave up after {IMPORTER_TIMEOUT_SECONDS} seconds", flush=True)
        return 1


def run_family(family: Family, run: Callable[[Family], int] = run_module) -> Outcome:
    missing = [name for name in family.needs if not getattr(config, name, None)]
    if missing:
        return Outcome(family, "skipped", f"{', '.join(missing)} is not set")

    held = {path: path.read_bytes() if path.exists() else None for path in family.files}
    outcome = Outcome(family, "ok", held=held)
    code = run(family)
    if code != 0:
        outcome.restore()
        outcome.status, outcome.detail = "failed", f"the importer exited with code {code}"
        return outcome

    for path, raw in held.items():
        before = _read(raw) if raw is not None else {"labels": {}}
        old = _identities(before)
        try:
            after = _read(path.read_bytes())
            new = _identities(after)
        except (OSError, ValueError):
            problem = "wrote something that is not a list"
        else:
            problem = _refusal(old, new)
            if not problem and (gone := _vanished(before, after)):
                problem = f"no address is listed by {', '.join(gone)} any more"
            if not problem:
                problem = _gate(path, old, after, sorted(new.keys() - old.keys()),
                                sorted(a for a in new.keys() & old.keys() if new[a] != old[a]),
                                sorted(old.keys() - new.keys()))
        if problem:
            outcome.restore()
            outcome.status, outcome.detail, outcome.changes = "refused", f"{path.name}: {problem}", {}
            return outcome
        outcome.changes[path] = Change(
            held_reviewed=(before.get("_meta") or {}).get("last_reviewed"),
            count=len(new),
            added=sorted(new.keys() - old.keys()),
            removed=sorted(old.keys() - new.keys()),
            altered=sorted(a for a in new.keys() & old.keys() if new[a] != old[a]),
            notes={key: list(after["_meta"][key]) for key in ("unverified", "bsc_not_checked")
                   if isinstance((after.get("_meta") or {}).get(key), list) and after["_meta"][key]},
            was={a: (old[a], new[a]) for a in new.keys() & old.keys() if new[a] != old[a]},
            to_mixer=sorted(a for a, (category, _entity) in new.items()
                            if category == "mixer" and (old.get(a) or (None,))[0] != "mixer"),
        )
    return outcome


def _is_old(reviewed: str | None, today: date) -> bool:
    try:
        return (today - date.fromisoformat(reviewed)).days >= RENEW_AFTER_DAYS
    except (TypeError, ValueError):
        return True  # a list that cannot say when it was checked gets no benefit of the doubt


def reason_to_open(outcomes: list[Outcome], today: date) -> str | None:
    checked = [change for o in outcomes if o.status == "ok" for change in o.changes.values()]
    if any(change.real for change in checked):
        return CHANGED
    if any(_is_old(change.held_reviewed, today) for change in checked):
        return DATES
    return None


def settle(outcomes: list[Outcome], reason: str | None) -> None:
    """With no pull request to open, put back the files that only changed date."""
    if reason is None:
        for outcome in outcomes:
            if outcome.status == "ok":
                outcome.restore()


def has_problem(outcomes: list[Outcome]) -> bool:
    return any(o.status in ("failed", "refused") for o in outcomes)


def pr_title(outcomes: list[Outcome], reason: str | None) -> str:
    if reason != CHANGED:
        return "[B][R11] Refresh list dates: no address changed"
    changes = [c for o in outcomes for c in o.changes.values()]
    added, removed = sum(len(c.added) for c in changes), sum(len(c.removed) for c in changes)
    altered = sum(len(c.altered) for c in changes)
    return f"[B][R11] Refresh lists: {added} added, {removed} removed, {altered} changed"


def _addresses(title: str, addresses: list[str]) -> list[str]:
    if not addresses:
        return []
    lines = [f"{title}:", *[f"- `{a}`" for a in addresses[:SHOWN_PER_LIST]]]
    if len(addresses) > SHOWN_PER_LIST:
        lines.append(f"- ...and {len(addresses) - SHOWN_PER_LIST} more, in the diff")
    return [*lines, ""]


def render_summary(outcomes: list[Outcome], reason: str | None) -> str:
    """The pull request's body. Addresses and counts only, all read from the files."""
    lines = ["From the nightly list refresh (`backend/scripts/import_all_lists.py`).", ""]
    if reason == DATES:
        lines += ["No address changed. Merging this renews the lists' dates, so reports stay "
                  "inside their seven-day warning.", ""]
    lines += ["| List | File | Addresses | Added | Removed | Changed | Last merged date |",
              "|---|---|---|---|---|---|---|"]
    for outcome in outcomes:
        for path, c in outcome.changes.items():
            lines.append(f"| {outcome.family.name} | `{path.name}` | {c.count} | {len(c.added)} | "
                         f"{len(c.removed)} | {len(c.altered)} | {c.held_reviewed or 'none'} |")
    lines.append("")
    for outcome in outcomes:
        for path, c in outcome.changes.items():
            lines += _addresses(f"Added to `{path.name}`", c.added)
            lines += _addresses(f"Removed from `{path.name}`", c.removed)
            if c.to_mixer:  # a mixer ends a trace: every one is listed
                lines += [f"Added as or moved to `mixer` in `{path.name}` (a trace stops there):",
                          *[f"- `{a}` {c.was[a][0][0] + ' -> ' if a in c.was else ''}mixer" for a in c.to_mixer], ""]
            if c.was:
                shown = sorted(c.was)[:SHOWN_CHANGED]
                lines += [f"What changed in `{path.name}` (old -> new):",
                          *[f"- `{a}` {c.was[a][0][0]} / {c.was[a][0][1]} -> {c.was[a][1][0]} / {c.was[a][1][1]}"
                            for a in shown]]
                if len(c.was) > SHOWN_CHANGED:
                    lines.append(f"- ...and {len(c.was) - SHOWN_CHANGED} more, in the diff")
                lines.append("")
            lines += _addresses(f"Not re-checked in `{path.name}` (a check failed; the held placement was kept)",
                                c.notes.get("unverified", []))
            lines += _addresses(f"New in `{path.name}` with BSC not checked (filed on Ethereum only)",
                                c.notes.get("bsc_not_checked", []))
    for outcome in outcomes:
        if outcome.status != "ok":
            kept = "not run" if outcome.status == "skipped" else "the list already held was kept"
            lines.append(f"- **{outcome.family.name}: {outcome.status}.** {outcome.detail}; {kept}.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, help="write the pull request body here")
    args = parser.parse_args()

    outcomes = [run_family(family) for family in families()]
    reason = reason_to_open(outcomes, datetime.now(timezone.utc).date())
    settle(outcomes, reason)

    summary = render_summary(outcomes, reason)
    print(f"\nReason to open a pull request: {reason or 'none'}\n{summary}")
    if args.summary:
        args.summary.write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"open_pr={'true' if reason else 'false'}\ntitle={pr_title(outcomes, reason)}\n")
    return 1 if has_problem(outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
