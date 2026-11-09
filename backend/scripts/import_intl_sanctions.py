"""Build data/intl_sanctions*.json: crypto addresses other governments have listed.

OFAC is one government. A fraud case that touches a wallet the UK, the EU or
Israel has frozen or seized is just as much an escalation, and several of
those lists name addresses OFAC does not -- Israel's counter-terror seizure
orders alone name hundreds of Tron USDT wallets. This importer collects them.

Sources, every one a government publication
-------------------------------------------
  UK   FCDO UK Sanctions List (CSV). Addresses sit in the free-text "Other
       Information" and "Statement of Reasons" fields of the entry they are
       listed against.
  EU   Consolidated list of persons subject to EU financial sanctions (XML).
       Addresses sit in the entity's <remark>.
  IL   Israel NBCTF seizure and forfeiture orders (terror financing), JP Japan
       Ministry of Finance, FR France Direction Generale du Tresor asset
       freezes -- read through OpenSanctions, which extracts the wallets from
       those publishers' own documents into structured data. OpenSanctions
       data is CC BY-NC 4.0: free for non-commercial use, with attribution.

Only a *current* measure counts. An Israeli seizure order with an end date in
the past has been lifted, and a wallet named only in lifted orders is left
out -- listing it would accuse someone the authority itself has released.
An order that is in force but dated records `valid_until`, its last day, and
the screen stops matching it after that day even if no refresh has run.

A seizure order is not a sanctions designation: it is one government's
temporary measure against a wallet. Israel's orders are therefore filed as
`seized`, and only an address some list designates is `sanctioned` (an
address on both keeps `sanctioned` and names both).

Offline re-check
----------------
`--recheck DATASET --from-file PATH` re-screens the held files' entries from
one OpenSanctions dataset against a local copy of its entities.ftm.json, with
no network: listings whose measures have all ended are removed, the rest are
re-read from the copy. Nothing else in the files changes.

Chain assignment
----------------
The same discipline as import_ofac_addresses.py: a Base58 T-address is Tron;
a 0x address goes to the chain the source names ("ETH:", "BNB:", "BSC:").
Where the source names only a token (USDT) or nothing, the address is filed
under each EVM chain it has actually been used on -- one call per chain --
and under Ethereum if it has been used on neither. Bitcoin and other chains
Exchequer does not trace are counted and skipped.

    cd backend && .venv/bin/python -m scripts.import_intl_sanctions
    cd backend && .venv/bin/python -m scripts.import_intl_sanctions --dry-run
    cd backend && .venv/bin/python -m scripts.import_intl_sanctions \
        --recheck il_mod_crypto --from-file entities.ftm.json --version <artifact url>
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError, normalize_address  # noqa: E402
from app.nodereal_client import NoderealClient, NoderealError  # noqa: E402
from app.risk_matcher import SANCTIONED, SEIZED  # noqa: E402
from scripts.import_threat_labels import used_on_bsc, used_on_ethereum  # noqa: E402

UK_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
EU_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/"
    "content?token=dG9rZW4tMjAxNw"
)
OPENSANCTIONS = "https://data.opensanctions.org/datasets/latest/{dataset}/index.json"
OS_DATASETS = {
    "il_mod_crypto": "Israel NBCTF seizure or forfeiture order",
    "jp_mof_sanctions": "Japan Ministry of Finance sanctions list",
    "fr_tresor_gels_avoir": "France Direction Generale du Tresor asset-freeze register",
}

AUTHORITY = {"il_mod_crypto": "Israel", "jp_mof_sanctions": "Japan", "fr_tresor_gels_avoir": "France"}
# Authorities whose listings here are seizure orders, not designations.
SEIZURE_AUTHORITIES = frozenset({"Israel"})

EVM = re.compile(r"0x[0-9a-fA-F]{40}")
TRON = re.compile(r"(?<![A-Za-z0-9])T[1-9A-HJ-NP-Za-km-z]{33}(?![A-Za-z0-9])")
# The chain a source names just before an address: "ETH: 0x..", "(7) BNB: 0x..".
TAG_BEFORE = re.compile(r"\b(ETH|ERC-?20|BNB|BSC|BEP-?20|TRX|TRC-?20|USDT|USDC)\W{0,4}$", re.IGNORECASE)
TAG_TO_CHAIN = {"eth": "ethereum", "erc20": "ethereum", "bnb": "bsc", "bsc": "bsc",
                "bep20": "bsc", "trx": "tron", "trc20": "tron"}


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Exchequer/1.0"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def chain_hint(text_before: str, default: str | None = None) -> str | None:
    """'ethereum'/'bsc'/'tron' if the text just before an address names it."""
    match = TAG_BEFORE.search(text_before[-16:])
    if match:
        return TAG_TO_CHAIN.get(match.group(1).lower().replace("-", ""))
    return default


def addresses_in(text: str, default_hint: str | None = None) -> list[tuple[str, str | None]]:
    """(address, chain hint or None) for every EVM or Tron address in `text`."""
    found = []
    for pattern in (EVM, TRON):
        for match in pattern.finditer(text):
            hint = "tron" if pattern is TRON else chain_hint(text[: match.start()], default_hint)
            found.append((match.group(), hint))
    return found


# -- one reader per source; each yields (address, hint, record) --------------------
def read_uk() -> list[tuple[str, str | None, dict]]:
    text = fetch(UK_URL).decode("utf-8-sig")
    lines = text.splitlines()
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[1:]))))  # line 1 is "Report Date"
    report_date = lines[0].split(":", 1)[-1].strip()
    out = []
    for row in rows:
        if row.get("Name type") != "Primary Name":
            continue
        name = " ".join(row.get(f"Name {i}", "").strip() for i in (1, 2, 3, 4, 5, 6)).split()
        name = " ".join(name) or row.get("Unique ID", "")
        body = f"{row.get('Other Information', '')} {row.get('UK Statement of Reasons', '')}"
        # "Byex is associated with the following Ethereum crypto addresses: ..."
        default = "ethereum" if re.search(r"\bEthereum\b", body) and not re.search(r"\b(BNB|BSC|Binance)\b", body) else None
        for address, hint in addresses_in(body, default):
            out.append((address, hint, {
                "entity": name,
                "authority": "United Kingdom",
                "source": (
                    f"UK Sanctions List (FCDO) as of {report_date}, "
                    f"{row.get('Regime Name', '').strip()}, entry {row.get('Unique ID', '')}"
                ),
            }))
    return out


def read_eu() -> list[tuple[str, str | None, dict]]:
    xml = fetch(EU_URL).decode("utf-8")
    out = []
    for block in re.findall(r"<sanctionEntity\b.*?</sanctionEntity>", xml, re.S):
        remarks = " ".join(re.findall(r"<remark>(.*?)</remark>", block, re.S))
        if not (EVM.search(remarks) or TRON.search(remarks)):
            continue
        name = re.search(r'wholeName="([^"]+)"', block)
        regulation = re.search(r'numberTitle="([^"]+)"', block)
        for address, hint in addresses_in(remarks):
            out.append((address, hint, {
                "entity": name.group(1) if name else "(unnamed EU entry)",
                "authority": "European Union",
                "source": (
                    "EU consolidated financial sanctions list, Regulation "
                    f"{regulation.group(1) if regulation else 'unspecified'}"
                ),
            }))
    return out


def _end_of(value: str) -> date | None:
    """The last day a FollowTheMoney date covers: '2026' -> 31 Dec, '2026-11' -> 30 Nov.

    FtM dates may be partial, and comparing them as text called '2026-11' over
    on 5 November. None if it cannot be read.
    """
    text = str(value).strip()[:10]
    try:
        if len(text) == 4:
            return date(int(text), 12, 31)
        if len(text) == 7:
            year, month = int(text[:4]), int(text[5:])
            return date(year, month, calendar.monthrange(year, month)[1])
        return date.fromisoformat(text)
    except ValueError:
        return None


def _last_day(measure: dict) -> date | None:
    """When a measure ends: its latest readable end date, or None if it is open-ended.

    An end date that cannot be read counts as open-ended: dropping a measure
    still in force would release someone the authority has not.
    """
    ends = [d for d in map(_end_of, measure.get("endDate") or []) if d]
    return max(ends) if ends else None


def _in_force(measure: dict, today: date) -> bool:
    last = _last_day(measure)
    return last is None or last >= today


def _valid_until(active: list[dict]) -> str | None:
    """The last day any in-force measure covers, or None if one has no end."""
    ends = [_last_day(m) for m in active]
    return max(ends).isoformat() if ends and all(ends) else None


def read_opensanctions(dataset: str, today: date) -> tuple[list[tuple[str, str | None, dict]], str]:
    index = json.loads(fetch(OPENSANCTIONS.format(dataset=dataset)))
    entities_url = next(r["url"] for r in index["resources"] if r["name"] == "entities.ftm.json")
    # The index is third-party data: follow only an https link to OpenSanctions' own host.
    if not str(entities_url).startswith("https://data.opensanctions.org/"):
        raise ValueError(f"{dataset}: unexpected entities URL {entities_url!r}")
    return opensanctions_rows(dataset, fetch(entities_url).decode(), today), entities_url


def opensanctions_rows(dataset: str, text: str, today: date) -> list[tuple[str, str | None, dict]]:
    """(address, hint, record) for every wallet in one dataset's entities.ftm.json in force on `today`."""
    entities: dict[str, dict] = {}
    for line in text.splitlines():
        if line.strip():
            entity = json.loads(line)
            entities[entity["id"]] = entity

    # Which measures name each wallet, and whether any of them is still in force.
    measures: dict[str, list[dict]] = defaultdict(list)
    unreadable = 0
    for entity in entities.values():
        if entity["schema"] == "Sanction":
            props = entity["properties"]
            unreadable += sum(1 for d in props.get("endDate") or [] if _end_of(d) is None)
            for target in props.get("entity", []):
                measures[target].append(props)
    if unreadable:
        print(f"  {dataset}: {unreadable} unreadable end dates, read as open-ended")

    out = []
    for wallet in entities.values():
        if wallet["schema"] != "CryptoWallet":
            continue
        props = wallet["properties"]
        active = [m for m in measures.get(wallet["id"], []) if _in_force(m, today)]
        if measures.get(wallet["id"]) and not active:
            continue  # every measure naming it has been lifted
        holders = [entities[h]["caption"] for h in props.get("holder", []) if h in entities]
        order_ids = sorted({i for m in active for i in m.get("authorityId", [])})
        currency = (props.get("currency") or [""])[0].upper()
        hint = TAG_TO_CHAIN.get(currency.lower())
        for key in props.get("publicKey", []):
            if not (EVM.fullmatch(key) or TRON.fullmatch(key)):
                continue
            source = OS_DATASETS[dataset]
            if order_ids:
                source += f" {', '.join(order_ids)}"
            out.append((key, "tron" if TRON.fullmatch(key) else hint, {
                "entity": ", ".join(holders) or (f"NBCTF order {order_ids[0]}" if order_ids else source),
                "authority": AUTHORITY[dataset],
                "source": f"{source} (via OpenSanctions)",
                "valid_until": _valid_until(active),
            }))
    return out


def held_placements() -> dict[str, set[str]]:
    """address -> the EVM chains whose held intl file lists it now."""
    out: dict[str, set[str]] = defaultdict(set)
    for chain_key, chain in config.CHAINS.items():
        path = chain.intl_sanctions_path
        if chain_key == "tron" or path is None or not path.exists():
            continue
        try:
            labels = json.loads(path.read_text(encoding="utf-8")).get("labels") or {}
        except (OSError, ValueError):
            continue
        for address in labels:
            out[address].add(chain_key)
    return out


def category_for(authorities: list[str]) -> str:
    """`seized` when every authority listing it only seized it; else `sanctioned`."""
    return SEIZED if authorities and set(authorities) <= SEIZURE_AUTHORITIES else SANCTIONED


def entry_valid_until(ends: list[str | None]) -> str | None:
    """An entry lapses only when every listing behind it does: None if any is open-ended."""
    return max(ends) if ends and all(ends) else None


def _key(address: str) -> str:
    return address if TRON.fullmatch(address) else normalize_address(address)


def recheck(dataset: str, entities_path: Path, version: str, today: date, dry_run: bool = False) -> int:
    """Re-screen the held files' listings from `dataset` against a local copy of it. No network."""
    authority = AUTHORITY[dataset]
    fresh: dict[str, dict] = {}
    for address, _hint, record in opensanctions_rows(dataset, entities_path.read_text(encoding="utf-8"), today):
        held = fresh.setdefault(_key(address), {"entity": record["entity"], "sources": [], "ends": []})
        if record["source"] not in held["sources"]:
            held["sources"].append(record["source"])
        held["ends"].append(record["valid_until"])

    for chain_key, chain in config.CHAINS.items():
        path = chain.intl_sanctions_path
        if path is None or not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        labels: dict[str, dict] = document["labels"]
        removed: list[str] = []
        renewed = 0
        for address in list(labels):
            entry = labels[address]
            if authority not in entry.get("authorities", []):
                continue
            others = [a for a in entry["authorities"] if a != authority]
            kept = [s for s in entry["source"].split("; ") if not s.startswith(f"{authority} ")]
            new = fresh.get(address)
            if new is None and not others:
                del labels[address]
                removed.append(address)
                continue
            if new is None:
                entry["authorities"], entry["source"] = others, "; ".join(kept)
            else:
                renewed += 1
                entry["source"] = "; ".join([*kept, *new["sources"]])
                if not others:
                    entry["entity"] = entry["label"] = new["entity"]
            entry["category"] = category_for(entry["authorities"])
            until = entry_valid_until(new["ends"]) if new is not None and not others else None
            if until:
                entry["valid_until"] = until
            else:
                entry.pop("valid_until", None)
        meta = document.setdefault("_meta", {})
        meta.setdefault("opensanctions_versions", {})[dataset] = version
        meta.setdefault("rechecked", {})[dataset] = {
            "date": today.isoformat(), "version": version, "removed": len(removed),
            "removed_addresses": sorted(removed),
            "note": (f"{authority} listings re-screened offline against this version; every "
                     "listing whose measures had all ended was removed. Other authorities' "
                     "listings were not re-read, so last_reviewed is unchanged."),
        }
        meta["counts"] = _counts(labels)
        meta["schema"] = SCHEMA
        print(f"  {chain_key:<9} {len(labels):>4} addresses; {authority}: {renewed} re-read, "
              f"{len(removed)} removed (every measure ended)")
        if not dry_run:
            document["labels"] = dict(sorted(labels.items()))
            path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if dry_run:
        print("\nDry run -- nothing written.")
    return 0


SCHEMA = ("labels maps an address to {category, entity, label, source, authorities}, plus valid_until "
          "(the last day it is in force) when every listing behind it has an end date; category is "
          "seized when only seizure orders name it, sanctioned otherwise")


def _counts(labels: dict[str, dict]) -> dict:
    return {
        "addresses": len(labels),
        "by_authority": dict(Counter(a for m in labels.values() for a in m["authorities"])),
        "by_category": dict(Counter(m["category"] for m in labels.values())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--recheck", choices=sorted(OS_DATASETS),
                        help="re-screen the held files' entries from this dataset, offline")
    parser.add_argument("--from-file", type=Path, help="with --recheck: a local copy of its entities.ftm.json")
    parser.add_argument("--version", default="", help="with --recheck: the artifact URL the copy came from")
    parser.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    args = parser.parse_args()
    today = args.today or datetime.now(timezone.utc).date()
    if args.recheck:
        if not args.from_file:
            parser.error("--recheck needs --from-file")
        return recheck(args.recheck, args.from_file, args.version or str(args.from_file.name), today, args.dry_run)

    listings: list[tuple[str, str | None, dict]] = []
    versions: dict[str, str] = {}
    for label, reader in (("UK", read_uk), ("EU", read_eu)):
        rows = reader()
        print(f"{label:<22} {len(rows):>5} address mentions")
        listings += rows
    for dataset in OS_DATASETS:
        rows, url = read_opensanctions(dataset, today)
        versions[dataset] = url
        print(f"{dataset:<22} {len(rows):>5} addresses in force")
        listings += rows

    # One record per address: every authority that lists it, in one source line.
    merged: dict[str, dict] = {}
    hints: dict[str, set[str]] = defaultdict(set)
    for address, hint, record in listings:
        key = address if TRON.fullmatch(address) else normalize_address(address)
        if hint:
            hints[key].add(hint)
        held = merged.setdefault(key, {"entity": record["entity"], "authorities": [], "sources": [], "ends": []})
        held["ends"].append(record.get("valid_until"))
        if record["authority"] not in held["authorities"]:
            held["authorities"].append(record["authority"])
        if record["source"] not in held["sources"]:
            held["sources"].append(record["source"])

    # File each address under a chain. A check that fails is unknown, never
    # "not used": the address keeps the placement the held files give it.
    placed = held_placements()
    by_chain: dict[str, dict[str, dict]] = defaultdict(dict)
    unplaced = [a for a in merged if a.startswith("0x") and not (hints[a] - {"tron"})]
    print(f"\n{len(merged)} distinct addresses; {len(unplaced)} EVM addresses name no chain "
          "and are placed by where they have been used")
    used: dict[str, set[str]] = defaultdict(set)
    unverified: list[str] = []  # a check failed; the held placement was kept
    bsc_not_checked: list[str] = []  # new, BSC not checked; filed on Ethereum only
    if unplaced:
        with EtherscanClient(chain_id=1) as eth:
            bsc = NoderealClient(chain_slug="bsc-mainnet") if config.NODEREAL_API_KEY else None
            try:
                for address in unplaced:
                    held_on = placed.get(address, set())
                    try:
                        if used_on_ethereum(eth, address):
                            used[address].add("ethereum")
                    except (EtherscanError, ValueError) as exc:
                        print(f"  ! {address} on Ethereum: {str(exc)[:50]}")
                        if not held_on:
                            print("Could not place a new address; nothing written. Re-run.", file=sys.stderr)
                            return 1
                        used[address] |= held_on & {"ethereum"}
                        unverified.append(address)
                    if bsc is None:
                        # No key: carry the held BSC placement over rather than drop it.
                        if "bsc" in held_on:
                            used[address].add("bsc")
                        elif not held_on:
                            bsc_not_checked.append(address)
                    else:
                        try:
                            if used_on_bsc(bsc, address):
                                used[address].add("bsc")
                        except (NoderealError, ValueError) as exc:
                            print(f"  ! {address} on BSC: {str(exc)[:50]}")
                            if held_on:
                                used[address] |= held_on & {"bsc"}
                                unverified.append(address)
                            else:
                                bsc_not_checked.append(address)
                    print(f"  {address}  used on: {', '.join(sorted(used[address])) or 'neither'}")
            finally:
                if bsc:
                    bsc.close()
    if unverified or bsc_not_checked:
        print(f"\nunverified (held placement kept): {len(set(unverified))}; "
              f"new, BSC not checked (filed on Ethereum): {len(bsc_not_checked)}")

    for address, held in merged.items():
        if TRON.fullmatch(address):
            chains = {"tron"}
        else:
            chains = (hints[address] - {"tron"}) or used[address] or {"ethereum"}
        until = entry_valid_until(held["ends"])
        for chain_key in chains:
            by_chain[chain_key][address] = {
                "category": category_for(held["authorities"]),
                "entity": held["entity"],
                "label": held["entity"],
                "source": "; ".join(held["sources"]),
                "authorities": held["authorities"],
                **({"valid_until": until} if until else {}),
            }

    for chain_key, chain in config.CHAINS.items():
        labels = by_chain.get(chain_key, {})
        per_authority = Counter(a for m in labels.values() for a in m["authorities"])
        print(f"  {chain_key:<9} {len(labels):>4} addresses  {dict(per_authority)}")
        if args.dry_run or chain.intl_sanctions_path is None:
            continue
        document = {
            "_meta": {
                "description": (
                    "Crypto addresses on sanctions and seizure lists published by "
                    "governments other than the U.S. A match means the funds touched "
                    "a wallet a government has frozen or seized."
                ),
                "provenance": (
                    f"UK: {UK_URL}. EU: {EU_URL}. Israel (NBCTF), Japan (MOF) and "
                    "France (DG Tresor) via OpenSanctions, which extracts them from "
                    "each publisher's own documents; OpenSanctions data is licensed "
                    "CC BY-NC 4.0. Built by backend/scripts/import_intl_sanctions.py."
                ),
                "opensanctions_versions": versions,
                "verification_note": (
                    "Each entry is copied from a government publication and names "
                    "every authority that lists it. It establishes that the "
                    "government froze or seized the address as of the review date; "
                    "it does NOT establish that a counterparty who received funds "
                    "from it is culpable, nor that the measure has force in Indian "
                    "law. Only measures still in force are included, and a dated one "
                    "stops matching after its valid_until."
                ),
                "chain": chain_key,
                "last_reviewed": today.isoformat(),
                "counts": _counts(labels),
                **({"unverified": sorted(set(unverified) & set(labels))} if set(unverified) & set(labels) else {}),
                **({"bsc_not_checked": sorted(set(bsc_not_checked) & set(labels))}
                   if set(bsc_not_checked) & set(labels) else {}),
                "regenerate_with": "cd backend && .venv/bin/python -m scripts.import_intl_sanctions",
                "schema": SCHEMA,
            },
            "labels": dict(sorted(labels.items())),
        }
        chain.intl_sanctions_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")

    if args.dry_run:
        print("\nDry run -- nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
