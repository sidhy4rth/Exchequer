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
  IL   Israel NBCTF administrative seizure orders (terror financing), JP Japan
       Ministry of Finance, FR France Direction Generale du Tresor asset
       freezes -- read through OpenSanctions, which extracts the wallets from
       those publishers' own documents into structured data. OpenSanctions
       data is CC BY-NC 4.0: free for non-commercial use, with attribution.

Only a *current* measure counts. An Israeli seizure order with an end date in
the past has been lifted, and a wallet named only in lifted orders is left
out -- listing it would accuse someone the authority itself has released.

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
"""
from __future__ import annotations

import argparse
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
from app.risk_matcher import SANCTIONED  # noqa: E402
from scripts.import_threat_labels import used_on_bsc, used_on_ethereum  # noqa: E402

UK_URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
EU_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/"
    "content?token=dG9rZW4tMjAxNw"
)
OPENSANCTIONS = "https://data.opensanctions.org/datasets/latest/{dataset}/index.json"
OS_DATASETS = {
    "il_mod_crypto": "Israel NBCTF administrative seizure order",
    "jp_mof_sanctions": "Japan Ministry of Finance sanctions list",
    "fr_tresor_gels_avoir": "France Direction Generale du Tresor asset-freeze register",
}

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


def read_opensanctions(dataset: str, today: date) -> tuple[list[tuple[str, str | None, dict]], str]:
    index = json.loads(fetch(OPENSANCTIONS.format(dataset=dataset)))
    entities_url = next(r["url"] for r in index["resources"] if r["name"] == "entities.ftm.json")
    entities: dict[str, dict] = {}
    for line in fetch(entities_url).decode().splitlines():
        entity = json.loads(line)
        entities[entity["id"]] = entity

    # Which measures name each wallet, and whether any of them is still in force.
    measures: dict[str, list[dict]] = defaultdict(list)
    for entity in entities.values():
        if entity["schema"] == "Sanction":
            for target in entity["properties"].get("entity", []):
                measures[target].append(entity["properties"])

    out = []
    for wallet in entities.values():
        if wallet["schema"] != "CryptoWallet":
            continue
        props = wallet["properties"]
        active = [
            m for m in measures.get(wallet["id"], [])
            if not m.get("endDate") or min(m["endDate"]) >= today.isoformat()
        ]
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
                "entity": ", ".join(holders) or (f"NBCTF seizure order {order_ids[0]}" if order_ids else source),
                "authority": {"il_mod_crypto": "Israel", "jp_mof_sanctions": "Japan",
                              "fr_tresor_gels_avoir": "France"}[dataset],
                "source": f"{source} (via OpenSanctions)",
            }))
    return out, entities_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()

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
        held = merged.setdefault(key, {"entity": record["entity"], "authorities": [], "sources": []})
        if record["authority"] not in held["authorities"]:
            held["authorities"].append(record["authority"])
        if record["source"] not in held["sources"]:
            held["sources"].append(record["source"])

    # File each address under a chain.
    by_chain: dict[str, dict[str, dict]] = defaultdict(dict)
    unplaced = [a for a in merged if a.startswith("0x") and not (hints[a] - {"tron"})]
    print(f"\n{len(merged)} distinct addresses; {len(unplaced)} EVM addresses name no chain "
          "and are placed by where they have been used")
    used: dict[str, set[str]] = defaultdict(set)
    if unplaced:
        with EtherscanClient(chain_id=1) as eth:
            bsc = NoderealClient(chain_slug="bsc-mainnet") if config.NODEREAL_API_KEY else None
            try:
                for address in unplaced:
                    try:
                        if used_on_ethereum(eth, address):
                            used[address].add("ethereum")
                        if bsc and used_on_bsc(bsc, address):
                            used[address].add("bsc")
                    except (EtherscanError, NoderealError, ValueError) as exc:
                        print(f"  ! {address}: {str(exc)[:50]}")
                    print(f"  {address}  used on: {', '.join(sorted(used[address])) or 'neither'}")
            finally:
                if bsc:
                    bsc.close()

    for address, held in merged.items():
        if TRON.fullmatch(address):
            chains = {"tron"}
        else:
            chains = (hints[address] - {"tron"}) or used[address] or {"ethereum"}
        for chain_key in chains:
            by_chain[chain_key][address] = {
                "category": SANCTIONED,
                "entity": held["entity"],
                "label": held["entity"],
                "source": "; ".join(held["sources"]),
                "authorities": held["authorities"],
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
                    "law. Only measures still in force are included."
                ),
                "chain": chain_key,
                "last_reviewed": today.isoformat(),
                "counts": {"addresses": len(labels), "by_authority": dict(per_authority)},
                "regenerate_with": "cd backend && .venv/bin/python -m scripts.import_intl_sanctions",
                "schema": "labels maps an address to {category, entity, label, source, authorities}",
            },
            "labels": dict(sorted(labels.items())),
        }
        chain.intl_sanctions_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")

    if args.dry_run:
        print("\nDry run -- nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
