"""Build data/validation/corpus.json: the wallets the heuristics are measured on.

Two corpora, every address fetched from a named source and none hand-typed:

  positives   Wallets publicly documented as holding fraud or theft proceeds.
              Sources: the OFAC SDN addresses already in data/risk_labels.json
              (Lazarus Group and other designated individuals, with exchanges
              and OTC services excluded because those are cash-out points, not
              proceeds); Etherscan's own "Phish / Hack" label as scraped into
              dappcenter/etherscan-labels at a pinned commit; and the WazirX
              (July 2024) attacker addresses as published in CloudSEK's
              incident write-up.

  controls    Ordinary active wallets with no fraud association, from the same
              pinned brianleect/etherscan-labels dataset the exchange importer
              uses: investment funds, mining-pool payout wallets, charities,
              payment processors, OTC desks, trading firms, company treasuries
              and airdrop distributors. Mining pools, payment processors and
              airdrop distributors are there on purpose -- they fan out by
              design, which is exactly the shape the amount-split rule looks
              for, so they are the wallets most likely to expose a false
              positive.

Every candidate is then checked on chain for contract bytecode, because the
trace follows an account's own transfers and a contract's outflows are
internal transactions the trace cannot see: a contract in either corpus would
trivially "not fire" and flatter the numbers. Contracts are dropped and
listed. Addresses that appear in the exchange label file are dropped from the
controls for the same reason -- the trace stops at them.

    cd backend && .venv/bin/python -m scripts.build_validation_corpus
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.etherscan_client import (  # noqa: E402
    EtherscanClient,
    EtherscanError,
    is_evm_address,
    normalize_address,
)
from app.exchange_matcher import get_matcher  # noqa: E402

OUT_PATH = config.DATA_DIR / "validation" / "corpus.json"

# Same dataset and commit as scripts/import_exchange_labels.py.
LABELS_REPO = "brianleect/etherscan-labels"
LABELS_COMMIT = "923aba72c7e2d0682f7ae6194b6140bd90668dc9"
LABELS_URL = (
    f"https://raw.githubusercontent.com/{LABELS_REPO}/{LABELS_COMMIT}"
    "/data/etherscan/accounts"
)

# Etherscan's "Phish / Hack" label, as scraped by a second public dataset.
PHISH_REPO = "dappcenter/etherscan-labels"
PHISH_COMMIT = "d547040b8bf65577945bcc53cec62a96945cc705"
PHISH_URL = (
    f"https://raw.githubusercontent.com/{PHISH_REPO}/{PHISH_COMMIT}"
    "/src/hack-addresses.json"
)

# CloudSEK's incident write-up names the attacker addresses in prose.
WAZIRX_URL = "https://www.cloudsek.com/blog/wazirx-incident-explained"

# OFAC entities that are services (an exchange, an OTC desk, a KYC-evasion
# vendor) rather than holders of proceeds. Matched against the entity name.
OFAC_SERVICE = re.compile(r"garantex|chatex|suex|secondeye|exchange|otc", re.IGNORECASE)

# Control categories and how many of each to take, deterministic by address.
CONTROL_CATEGORIES: dict[str, tuple[int, str]] = {
    "fund": (16, "investment fund treasury"),
    "mining": (12, "mining-pool payout wallet: fans out to miners by design"),
    "charity": (8, "charity donation wallet"),
    "payments": (6, "payment processor: fans out to merchants by design"),
    "otc": (6, "OTC trading desk"),
    "trading": (6, "trading firm"),
    "company-funds": (6, "company treasury wallet"),
    "airdrop-distributor": (6, "airdrop distributor: fans out to recipients by design"),
    "ethereum-foundation": (2, "Ethereum Foundation wallet"),
}
POSITIVE_CAPS = {"ofac": 20, "phish-hack": 20}
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def fetch(url: str) -> bytes:
    # Some publishers refuse urllib's default agent string outright.
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Exchequer corpus builder)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_json(url: str):
    return json.loads(fetch(url))


def entry(address: str, source: str, url: str, why: str, **extra) -> dict:
    return {
        "address": normalize_address(address),
        "chain": "ethereum",
        "asset": "ETH",
        "source": source,
        "source_url": url,
        "why": why,
        **extra,
    }


def positives_from_ofac() -> list[dict]:
    path = config.CHAINS["ethereum"].risk_labels_path
    document = json.loads(path.read_text())
    out = []
    for address, meta in sorted(document["labels"].items()):
        if OFAC_SERVICE.search(meta["entity"]):
            continue
        out.append(entry(
            address,
            "OFAC SDN list via backend/data/risk_labels.json",
            "https://www.treasury.gov/ofac/downloads/sdn.xml",
            f"designated entity: {meta['entity']} ({', '.join(meta.get('ofac_programs', []))})",
            entity=meta["entity"],
        ))
    return out[: POSITIVE_CAPS["ofac"]]


def positives_from_phish() -> list[dict]:
    raw = fetch_json(PHISH_URL)
    items = raw.items() if isinstance(raw, dict) else (
        ((x.get("address") or x.get("Address") or ""), x) for x in raw
    )
    out = []
    for address, meta in sorted(items, key=lambda kv: str(kv[0]).lower()):
        if not is_evm_address(str(address)):
            continue
        name = meta.get("name") or meta.get("nameTag") or meta.get("label") or "" \
            if isinstance(meta, dict) else str(meta)
        out.append(entry(
            address,
            f"Etherscan 'Phish / Hack' label via {PHISH_REPO} @ {PHISH_COMMIT[:10]}",
            PHISH_URL,
            f"labelled Phish / Hack by Etherscan{': ' + name if name else ''}",
        ))
        if len(out) >= POSITIVE_CAPS["phish-hack"]:
            break
    return out


def positives_from_wazirx() -> list[dict]:
    text = fetch(WAZIRX_URL).decode("utf-8", "replace")
    out = []
    for match in ADDRESS_RE.finditer(text):
        context = text[max(0, match.start() - 120): match.start()].lower()
        if "hacker" in context or "attacker" in context or "secondary" in context \
                or "tertiary" in context:
            out.append(entry(
                match.group(0),
                "CloudSEK, 'WazirX Incident: Explained', 19 July 2024",
                WAZIRX_URL,
                "named as an attacker address in the WazirX (Indian exchange) hack of 18 July 2024",
            ))
    seen: set[str] = set()
    unique = []
    for item in out:
        if item["address"] not in seen:
            seen.add(item["address"])
            unique.append(item)
    return unique


def controls_from_labels() -> list[dict]:
    out = []
    for category, (cap, why) in CONTROL_CATEGORIES.items():
        raw = fetch_json(f"{LABELS_URL}/{category}.json")
        taken = 0
        for address, meta in sorted(raw.items()):
            if not is_evm_address(address):
                continue
            out.append(entry(
                address,
                f"Etherscan label '{category}' via {LABELS_REPO} @ {LABELS_COMMIT[:10]}",
                f"{LABELS_URL}/{category}.json",
                why,
                label=meta.get("name", "") if isinstance(meta, dict) else str(meta),
                category=category,
            ))
            taken += 1
            if taken >= cap:
                break
    return out


def drop_contracts(client: EtherscanClient, items: list[dict]) -> tuple[list[dict], list[str]]:
    kept, dropped = [], []
    for item in items:
        try:
            code = client._request({
                "module": "proxy", "action": "eth_getCode",
                "address": item["address"], "tag": "latest",
            })
        except (EtherscanError, ValueError) as exc:
            print(f"  ! {item['address']}: {str(exc)[:60]}")
            dropped.append(item["address"] + "  (could not check)")
            continue
        if isinstance(code, str) and len(code) > 2:
            dropped.append(item["address"] + "  (contract)")
            continue
        item["verified"] = "no contract bytecode (eth_getCode) at time of build"
        kept.append(item)
    return kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    if not config.ETHERSCAN_API_KEY:
        print("ETHERSCAN_API_KEY is not set; the bytecode check needs it.")
        return 1

    print("Fetching positives ...")
    positives = positives_from_ofac() + positives_from_phish()
    unavailable: list[str] = []
    try:
        wazirx = positives_from_wazirx()
    except (OSError, ValueError) as exc:
        # Recorded rather than silently skipped: the corpus must say what it
        # could not include.
        unavailable.append(f"WazirX attacker addresses: {WAZIRX_URL} could not be fetched ({exc})")
        wazirx = []
    positives += wazirx
    print(f"  {len(positives)} candidates ({len(wazirx)} WazirX)")
    print("Fetching controls ...")
    controls = controls_from_labels()
    matcher = get_matcher("ethereum")
    before = len(controls)
    controls = [c for c in controls if not matcher.is_exchange(c["address"])]
    print(f"  {len(controls)} candidates ({before - len(controls)} were exchange labels)")

    # A wallet cannot be in both corpora.
    positive_addresses = {p["address"] for p in positives}
    controls = [c for c in controls if c["address"] not in positive_addresses]

    print("Checking for contract bytecode ...")
    with EtherscanClient(chain_id=1) as client:
        positives, dropped_p = drop_contracts(client, positives)
        controls, dropped_c = drop_contracts(client, controls)
    for line in dropped_p + dropped_c:
        print("  -", line)

    document = {
        "_meta": {
            "description": (
                "Wallets the laundering heuristics are measured against. "
                "Positives are publicly documented as fraud or theft proceeds; "
                "controls are ordinary active wallets with no fraud association. "
                "Every address was fetched from the source recorded on it and "
                "checked for contract bytecode; none was typed by hand."
            ),
            "built": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "regenerate_with": "cd backend && .venv/bin/python -m scripts.build_validation_corpus",
            "sources": {
                "ofac": "backend/data/risk_labels.json (OFAC SDN XML)",
                "phish-hack": f"{PHISH_REPO} @ {PHISH_COMMIT}",
                "wazirx": WAZIRX_URL,
                "controls": f"{LABELS_REPO} @ {LABELS_COMMIT}",
            },
            "dropped_as_contracts": dropped_p + dropped_c,
            "unavailable_sources": unavailable,
            "counts": {"positives": len(positives), "controls": len(controls)},
        },
        "positives": positives,
        "controls": controls,
    }
    print(f"\npositives: {len(positives)}   controls: {len(controls)}")
    if args.dry_run:
        return 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(document, indent=2) + "\n")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
