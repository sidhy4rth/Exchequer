"""Build data/risk_labels*.json from OFAC's published SDN list.

Provenance is the whole point of this script. Exchequer's exchange labels
come from explorer tags, which are an attribution by a third party. A sanctions
label is stronger than that and must be sourced accordingly: the U.S. Treasury
publishes the Specially Designated Nationals list as XML, each entry carrying
the designated entity, the sanctions programs it falls under, and any digital
currency addresses recorded against it. That file is the authority. Nothing
here infers, guesses or copies from a blog post.

    https://www.treasury.gov/ofac/downloads/sdn.xml

What this establishes: the U.S. Treasury published this address as belonging to
the named designated entity, as of the recorded publication date.
What it does NOT establish: that receiving funds from a sanctioned address
makes the recipient culpable, or that the designation is current in Indian law.
An investigator uses it as a lead and an escalation trigger, not a verdict.

Chain assignment
----------------
Each address is filed under the chain OFAC's own idType names -- "Digital
Currency Address - ETH" goes to Ethereum, "- TRX" to Tron, "- BSC" to BNB
Smart Chain. Where the idType names a token rather than a chain (USDT, USDC)
the address format decides the family and the original idType is recorded in
the entry, so a reader can always see what the source actually said.

A sanctioned 0x address is deliberately NOT copied onto every EVM chain. An
externally-owned address is controlled by the same key everywhere, but a
contract address is not -- the Tornado Cash pools are contracts, and asserting
they exist on BSC because they exist on Ethereum would be exactly the kind of
manufactured claim this tool refuses to make elsewhere.

Mixer classification
--------------------
Every address here is on the SDN list, so every one of them is sanctioned.
`category` splits off the subset that are tumblers, because that carries an
extra consequence in the tracer: a trace must STOP at a mixer, since its
payouts come from a commingled pool and have no established link to the
deposit we arrived on. That split is this project's editorial judgement,
applied by matching the designated entity's name against MIXER_ENTITIES below,
and is recorded as such. The sanctions fact itself is never editorial.

    cd backend && .venv/bin/python -m scripts.import_ofac_addresses
    cd backend && .venv/bin/python -m scripts.import_ofac_addresses --dry-run
    cd backend && .venv/bin/python -m scripts.import_ofac_addresses --sdn-file sdn.xml
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import is_evm_address, is_tron_address, normalize_address  # noqa: E402
from app.risk_matcher import MIXER, SANCTIONED  # noqa: E402

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"
NS = {"s": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"}

# OFAC records crypto addresses in an id whose type begins with this.
ID_TYPE_PREFIX = "Digital Currency Address - "

# Which of OFAC's currency codes belong to a chain Exchequer traces. Codes
# for chains we do not cover (XBT, XMR, LTC, ZEC ...) are counted and reported
# but not written -- a Bitcoin address in an Ethereum label file could only
# ever produce a false negative or a confusing report.
CODE_TO_CHAIN = {
    "ETH": "ethereum",
    "ETC": None,       # Ethereum Classic is a different ledger, not traced
    "USDT": None,      # token, not a chain: resolved by address format below
    "USDC": None,      # token, not a chain: resolved by address format below
    "TRX": "tron",
    "BSC": "bsc",
    "BNB": "bsc",
    "ARB": None,       # Arbitrum, not traced
}

# Designated entities that operate as tumblers. Matching is on the entity name
# OFAC publishes. See the module docstring: this split is editorial, the
# sanctions designation behind it is not.
MIXER_ENTITIES = re.compile(
    r"(tornado\s*cash|blender\.io|sinbad\.io|chipmixer|helix|bitcoin\s*fog|"
    r"cryptomixer|mixer|tumbler)",
    re.IGNORECASE,
)


def entity_name(entry: ET.Element) -> str:
    """The designated party's name, however OFAC recorded it."""
    last = (entry.findtext("s:lastName", default="", namespaces=NS) or "").strip()
    first = (entry.findtext("s:firstName", default="", namespaces=NS) or "").strip()
    return " ".join(part for part in (first, last) if part) or "(unnamed SDN entry)"


def programs(entry: ET.Element) -> list[str]:
    """The sanctions programs the entry falls under, e.g. CYBER2, DPRK3."""
    return [
        (p.text or "").strip()
        for p in entry.findall("s:programList/s:program", NS)
        if (p.text or "").strip()
    ]


def parse(sdn_xml: Path) -> tuple[dict[str, dict], dict[str, int], str]:
    """Extract every digital-currency address from the SDN list.

    Returns (addresses-by-chain, skipped-code counts, publication date).
    """
    tree = ET.parse(sdn_xml)
    root = tree.getroot()

    published = (
        root.findtext("s:publshInformation/s:Publish_Date", default="", namespaces=NS) or ""
    ).strip() or "unknown"

    by_chain: dict[str, dict] = defaultdict(dict)
    skipped: dict[str, int] = defaultdict(int)

    for entry in root.findall("s:sdnEntry", NS):
        name = entity_name(entry)
        progs = programs(entry)
        category = MIXER if MIXER_ENTITIES.search(name) else SANCTIONED

        for id_el in entry.findall("s:idList/s:id", NS):
            id_type = (id_el.findtext("s:idType", default="", namespaces=NS) or "").strip()
            if not id_type.startswith(ID_TYPE_PREFIX):
                continue

            code = id_type[len(ID_TYPE_PREFIX):].strip().upper()
            address = (id_el.findtext("s:idNumber", default="", namespaces=NS) or "").strip()
            if not address:
                continue

            chain_key = CODE_TO_CHAIN.get(code, None)
            if chain_key is None:
                # Either a token code, or a chain we do not trace. The address
                # format is the only reliable discriminator, so use it -- but
                # only to pick a family we actually cover.
                if is_tron_address(address):
                    chain_key = "tron"
                elif is_evm_address(address) and code in ("USDT", "USDC"):
                    # An 0x token designation. Ethereum is where these are
                    # recorded; the original idType is kept in the entry so the
                    # assumption is visible rather than buried here.
                    chain_key = "ethereum"
                else:
                    skipped[code] += 1
                    continue

            chain = config.CHAINS.get(chain_key)
            if chain is None or not chain.validate_address(address):
                skipped[code] += 1
                continue

            by_chain[chain_key][normalize_address(address)] = {
                "category": category,
                "entity": name,
                "label": f"{name} ({code})" if code not in ("ETH", "TRX", "BNB") else name,
                "source": f"OFAC SDN list, published {published}",
                "ofac_programs": progs,
                "ofac_id_type": id_type,
            }

    return dict(by_chain), dict(skipped), published


def write_chain_file(chain_key: str, labels: dict[str, dict], published: str, dry_run: bool) -> None:
    chain = config.CHAINS[chain_key]
    path = chain.risk_labels_path
    if path is None:
        print(f"  {chain_key}: no risk_labels_filename configured; skipped")
        return

    counts = defaultdict(int)
    for meta in labels.values():
        counts[meta["category"]] += 1

    document = {
        "_meta": {
            "description": (
                "Addresses on the U.S. Treasury's Specially Designated Nationals "
                "list that Exchequer screens a trace against. A match tells an "
                "investigator the funds touched a designated entity, which is the "
                "point at which a fraud case acquires an international dimension."
            ),
            "provenance": (
                "Extracted directly from OFAC's published SDN XML "
                f"({SDN_URL}) by backend/scripts/import_ofac_addresses.py. "
                "Every entry keeps the sanctions programs and the exact idType "
                "OFAC recorded, so any label here can be checked against the "
                "source document."
            ),
            "verification_note": (
                "This establishes that the U.S. Treasury published the address "
                "against the named designated entity as of the publication date. "
                "It does NOT establish that a counterparty who received funds "
                "from it is culpable, nor that the designation has force in "
                "Indian law. It is a lead and an escalation trigger, not a verdict."
            ),
            "category_note": (
                "Every address in this file is sanctioned. 'mixer' marks the "
                "subset that are tumblers, which is Exchequer's own editorial "
                "classification of the designated entity's name, and which "
                "additionally stops a trace: a mixer pays out from a commingled "
                "pool, so transfers leaving it have no established link to the "
                "deposit that arrived."
            ),
            "chain": chain_key,
            "ofac_publish_date": published,
            "last_reviewed": datetime.now(timezone.utc).date().isoformat(),
            "counts": {SANCTIONED: counts[SANCTIONED], MIXER: counts[MIXER]},
            "regenerate_with": (
                "cd backend && .venv/bin/python -m scripts.import_ofac_addresses"
            ),
            "schema": (
                "labels maps an address to {category, entity, label, source, "
                "ofac_programs, ofac_id_type}"
            ),
        },
        "labels": dict(sorted(labels.items())),
    }

    print(
        f"  {chain_key:<9} {len(labels):>4} addresses "
        f"({counts[SANCTIONED]} sanctioned, {counts[MIXER]} mixer) -> {path.name}"
    )
    if dry_run:
        return
    path.write_text(json.dumps(document, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sdn-file",
        type=Path,
        help="Use a local copy of sdn.xml instead of downloading (the file is ~29MB)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be written, write nothing"
    )
    args = parser.parse_args()

    if args.sdn_file:
        sdn_path = args.sdn_file
        if not sdn_path.is_file():
            print(f"No such file: {sdn_path}", file=sys.stderr)
            return 1
        print(f"Reading OFAC SDN list from {sdn_path}")
    else:
        sdn_path = Path(config.BACKEND_DIR) / "sdn.xml"
        print(f"Downloading OFAC SDN list from {SDN_URL} (~29MB, this is slow)")
        try:
            with httpx.stream("GET", SDN_URL, timeout=600.0, follow_redirects=True) as r:
                r.raise_for_status()
                with sdn_path.open("wb") as fh:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            print(f"Could not download the SDN list: {exc}", file=sys.stderr)
            return 1

    try:
        by_chain, skipped, published = parse(sdn_path)
    except ET.ParseError as exc:
        print(f"sdn.xml is not parseable XML: {exc}", file=sys.stderr)
        return 1

    total = sum(len(v) for v in by_chain.values())
    print(f"\nOFAC SDN list published {published}")
    print(f"Found {total} addresses on chains Exchequer traces:\n")

    for chain_key in config.CHAINS:
        write_chain_file(chain_key, by_chain.get(chain_key, {}), published, args.dry_run)

    if skipped:
        ignored = ", ".join(f"{code} x{n}" for code, n in sorted(skipped.items()))
        print(f"\nIgnored (chains not traced): {ignored}")

    if args.dry_run:
        print("\nDry run -- nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
