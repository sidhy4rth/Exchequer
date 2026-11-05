"""Build data/gambling_labels*.json: wallets controlled by gambling platforms.

What a match means: the funds reached a wallet that a casino or betting
platform controls -- its hot wallet, or a per-user deposit address that sweeps
into it. Like an exchange, the platform holds the account behind that wallet,
so the investigator's next step is a lawful request to the platform for the
account holder. It is an attribution of the wallet, not a designation, and not
a finding that anyone broke the law.

Sources
-------
  Hot wallets   the block explorer's own "Gambling" tags and platform name tags
                (Etherscan/BscScan via dawsbot/eth-labels), in the hunt's
                raw/gambling_seeds.json.
  Deposit       on-chain sweep evidence: a sender that moved USDT/USDC into a
  addresses     labelled hot wallet at least MIN_SWEEPS times (raw/gambling_evm_run*.json;
                Tron: mukesh/gambling_tron.json). Each row keeps a sample tx.
A hot wallet is only written for a chain where deposits were seen sweeping into
it, so a label is never asserted on a chain with no evidence. Anything already
labelled as an exchange in data/exchange_labels*.json is skipped: one address,
one attribution.

    cd backend && .venv/bin/python -m scripts.import_gambling_labels --hunt-dir ~/exchequer-flagged
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CHAIN_FILES = {
    "ethereum": ("gambling_labels.json", "exchange_labels.json"),
    "bsc": ("gambling_labels_bsc.json", "exchange_labels_bsc.json"),
    "polygon": ("gambling_labels_polygon.json", "exchange_labels_polygon.json"),
    "arbitrum": ("gambling_labels_arbitrum.json", "exchange_labels_arbitrum.json"),
    "tron": ("gambling_labels_tron.json", "exchange_labels_tron.json"),
}
ROUTER_FILES = {"ethereum": "router_labels.json", "bsc": "router_labels_bsc.json"}
EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
TRON = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def norm(address: str) -> str | None:
    a = (address or "").strip()
    if EVM.match(a):
        return a.lower()
    if TRON.match(a):
        return a
    return None


def platform_of(name_tag: str) -> str:
    return re.split(r"[:\s]", name_tag.strip())[0] or "Gambling platform"


def build(seeds: list[dict], deposits: list[dict], tron_rows: dict, exchange: dict[str, set[str]]) -> dict[str, dict]:
    """{chain: {address: record}} from hunt outputs. Pure function: no I/O, easy to test."""
    seed_name = {s["address"].lower(): (platform_of(s.get("nameTag", "")), s.get("nameTag", "")) for s in seeds}
    out: dict[str, dict] = {c: {} for c in CHAIN_FILES}
    for d in deposits:
        chain = d.get("chain")
        a = norm(d.get("address", ""))
        hot = norm(d.get("hot_wallet", ""))
        if chain not in out or not a or a in exchange.get(chain, set()):
            continue
        out[chain][a] = {
            "category": "gambling",
            "entity": d.get("platform") or "Gambling platform",
            "label": f"{d.get('platform')} deposit address",
            "source": (f"Swept {d.get('sweeps')}x {d.get('token')} into {d.get('platform')} hot wallet {hot} "
                       f"(sample tx {d.get('tx')}, {d.get('date')})"),
        }
        # the hot wallet is evidenced on this chain by the sweeps into it
        if hot and hot in seed_name and hot not in exchange.get(chain, set()):
            plat, tag = seed_name[hot]
            out[chain].setdefault(hot, {
                "category": "gambling", "entity": plat, "label": f"{plat} hot wallet",
                "source": f"Block explorer gambling tag “{tag}” (via dawsbot/eth-labels)",
            })
    for key, r in (tron_rows or {}).items():
        if not isinstance(r, dict):
            continue
        a = norm(r.get("address") or key)
        if not a or not a.startswith("T") or a in exchange.get("tron", set()):
            continue
        plat = r.get("platform") or "Gambling platform"
        is_hot = r.get("role") == "hot_wallet"
        out["tron"][a] = {
            "category": "gambling", "entity": plat,
            "label": f"{plat} {'hot wallet' if is_hot else 'deposit address'}",
            "source": (r.get("source") or "TronScan tag") if is_hot else
                      f"Swept {r.get('sweeps', '?')}x USDT into {plat} hot wallet {r.get('hot_wallet')} (sample tx {r.get('tx')})",
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hunt-dir", default=str(Path.home() / "exchequer-flagged"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    hunt = Path(args.hunt_dir).expanduser()
    seeds = json.loads((hunt / "raw/gambling_seeds.json").read_text())
    extra = hunt / "raw/gambling_seeds_extra.json"   # platform wallets found later (e.g. Cloudbet via DappRadar)
    if extra.exists():
        seeds += json.loads(extra.read_text())
    deposits: list[dict] = []
    for f in sorted(glob.glob(str(hunt / "raw/gambling_evm_run*.json"))):
        deposits += list(json.loads(Path(f).read_text()).values())
    # BigQuery sweep graph: level 1 = deposits of known hot wallets; level 2 = deposits of sibling hot wallets
    # (receivers that many level-1 deposit addresses also sweep into). Platform is inherited from the seed;
    # siblings are named "<platform> (sibling wallet)" via the level-1 deposit that links them.
    seed_platform = {s["address"].lower(): platform_of(s.get("nameTag", "")) for s in seeds}
    for f in sorted(glob.glob(str(hunt / "raw/bq_gambling_eth_*.json"))):
        rows = json.loads(Path(f).read_text())
        dep_platform = {r["address"]: seed_platform.get(r["hot_wallet"]) for r in rows.values() if r.get("level") == 1}
        sib_platform: dict[str, str] = {}
        for r in rows.values():
            if r.get("level") == 1:
                deposits.append({**r, "platform": seed_platform.get(r["hot_wallet"], "Gambling platform")})
        # a sibling's platform: majority platform of the level-1 deposits that also sweep into it is not in the
        # output, so fall back to the generic name; the source line still cites the sweep evidence.
        ok_path = hunt / "raw/gambling_siblings_ok.json"
        sib_ok = set(json.loads(ok_path.read_text())) if ok_path.exists() else set()
        for r in rows.values():
            # level 2 only for sibling wallets that were vetted (not an exchange, not a contract/router)
            if r.get("level") == 2 and r["hot_wallet"] in sib_ok:
                plat = sib_platform.setdefault(r["hot_wallet"], dep_platform.get(r["address"]) or "Gambling platform")
                deposits.append({**r, "platform": plat,
                                 "sibling": True})
    tron_path = hunt / "mukesh/gambling_tron.json"
    tron_rows = json.loads(tron_path.read_text()) if tron_path.exists() else {}
    exchange = {}
    for chain, (_, ex_file) in CHAIN_FILES.items():
        p = DATA / ex_file
        exchange[chain] = set(json.loads(p.read_text()).get("labels", {})) if p.exists() else set()
        # A DEX router carries every user's swap, so users sweeping into a casino
        # through it must not make it a casino deposit (the 1inch v4 router did).
        rp = DATA / ROUTER_FILES.get(chain, "")
        if chain in ROUTER_FILES and rp.exists():
            exchange[chain] |= {k.lower() for k in json.loads(rp.read_text()).get("labels", {})}
    # Deposit "sweeps" that were really address-poisoning (zero/dust transfers from lookalikes of genuine
    # deposit addresses, or addresses on our poisoning lists) must never be labelled as gambling.
    sp = hunt / "raw/gambling_suspect_poisoners.json"
    suspects = set(json.loads(sp.read_text())) if sp.exists() else set()
    deposits = [d for d in deposits if (d.get("address") or "").lower() not in suspects]
    built = build(seeds, deposits, tron_rows, exchange)
    for chain_labels in built.values():
        for a in [a for a in chain_labels if a in suspects]:
            del chain_labels[a]
    for chain, labels in built.items():
        fname = CHAIN_FILES[chain][0]
        doc = {
            "_meta": {
                "description": "Wallets controlled by gambling platforms (casino/betting hot wallets and the per-user "
                               "deposit addresses that sweep into them). A match is an attribution, like an exchange: "
                               "the platform holds the account and can identify its holder on a lawful request.",
                "provenance": "Hot wallets: block explorer gambling tags via dawsbot/eth-labels. Deposit addresses: "
                              "on-chain sweeps (>=2) of USDT/USDC into those hot wallets. Built by "
                              "backend/scripts/import_gambling_labels.py.",
                "verification_note": "Each deposit row cites a sample sweep transaction. Not a designation and not a "
                                     "finding of wrongdoing by anyone.",
                "chain": chain, "last_reviewed": date.today().isoformat(),
                "counts": {"gambling": len(labels)},
                "regenerate_with": "cd backend && .venv/bin/python -m scripts.import_gambling_labels --hunt-dir <hunt dir>",
                "schema": "labels maps an address to {category, entity, label, source}",
            },
            "labels": dict(sorted(labels.items())),
        }
        print(f"{fname}: {len(labels)} gambling wallets")
        if not args.dry_run:
            (DATA / fname).write_text(json.dumps(doc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
