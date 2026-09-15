"""Measure the laundering heuristics against real wallets.

The peel-chain and amount-split rules are fixed arithmetic with thresholds
this project chose. This script answers the question a judge will ask about
them: on wallets publicly documented as fraud proceeds, how often do they
fire, and on ordinary wallets, how often do they fire when they should not?

It runs the real trace pipeline -- the same traversal, exchange matching and
pattern detection main.py uses -- over the two corpora in
data/validation/corpus.json, then re-runs pattern detection on the resulting
graphs with every threshold combination in a small grid and reports, per
pattern and per point, how many positives and how many controls fired.

Every provider response is recorded into data/validation/snapshot_*.json.gz on
a --refresh run and served from there otherwise, so the experiment runs
offline, needs no key, and gives the same numbers every time. The snapshot is
what the README table was generated from; regenerate with:

    cd backend && .venv/bin/python -m scripts.validate_patterns
    cd backend && .venv/bin/python -m scripts.validate_patterns --refresh   # re-fetch

Read the numbers for what they are. A positive is a wallet documented as
holding illicit funds, not a wallet documented as laundering them in one of
these two shapes, so "fired on N of P positives" measures how often the shape
appears near documented-illicit wallets, not the rule's recall against ground
truth. A control that fires is a false positive in the sense that matters: an
innocent wallet a report would have flagged.
"""
from __future__ import annotations

import argparse
import gzip
import itertools
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.deposit_inference import infer_deposit_addresses  # noqa: E402
from app.etherscan_client import EtherscanClient, EtherscanError, Transaction  # noqa: E402
from app.exchange_matcher import ExchangeMatcher, get_matcher  # noqa: E402
from app.graph_builder import TraceConfig, build_trace_graph  # noqa: E402
from app.pattern_detection import (  # noqa: E402
    AMOUNT_SPLIT,
    PEEL_CHAIN,
    PatternConfig,
    detect_patterns,
)
from app.risk_matcher import get_risk_matcher  # noqa: E402

VALIDATION_DIR = config.DATA_DIR / "validation"
CORPUS_PATH = VALIDATION_DIR / "corpus.json"
RESULTS_PATH = VALIDATION_DIR / "results.json"

# Compact on-disk form of one outgoing transfer.
FIELDS = ("hash", "from_address", "to_address", "value_wei", "timestamp", "block_number")


def snapshot_path(chain: str, asset: str) -> Path:
    return VALIDATION_DIR / f"snapshot_{chain}_{asset.lower()}.json.gz"


class RecordingClient:
    """Wraps a live client and remembers every outgoing list it served."""

    def __init__(self, real: EtherscanClient, store: dict[str, list]) -> None:
        self.real = real
        self.store = store

    def get_outgoing_transactions(self, address: str, limit: int | None = None):
        txs = self.real.get_outgoing_transactions(address, limit=limit)
        self.store[address] = [
            [tx.hash, tx.from_address, tx.to_address, str(tx.value_wei), tx.timestamp, tx.block_number]
            for tx in txs
        ]
        return txs

    def get_incoming_transactions(self, address: str, limit: int | None = None):
        raise NotImplementedError("validation traces run forward only")


class SnapshotClient:
    """Serves the recorded lists; an address never fetched is a fetch failure."""

    def __init__(self, store: dict[str, list], asset: str) -> None:
        self.store = store
        self.asset = asset

    def get_outgoing_transactions(self, address: str, limit: int | None = None):
        rows = self.store.get(address)
        if rows is None:
            raise EtherscanError(f"{address} is not in the offline snapshot; run with --refresh")
        out = []
        for h, src, dst, wei, ts, block in rows:
            wei = int(wei)
            out.append(Transaction(
                hash=h, from_address=src, to_address=dst,
                value_native=wei / 10**18, value_wei=wei, timestamp=ts,
                block_number=block, is_error=False, asset=self.asset,
            ))
        return out


def load_snapshot(path: Path) -> dict[str, list]:
    if not path.exists():
        return {}
    with gzip.open(path, "rt") as fh:
        return json.load(fh)["addresses"]


def save_snapshot(path: Path, store: dict[str, list], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        json.dump({"_meta": meta, "addresses": store}, fh)


def trace_one(seed: str, client, matcher: ExchangeMatcher, risk, depth: int):
    """One forward trace, exactly as main.trace() would run it."""
    result = build_trace_graph(
        seed,
        client,
        cfg=TraceConfig(max_depth=depth),
        is_terminal=lambda a: matcher.is_exchange(a) or risk.is_terminal(a),
    )
    matches = matcher.annotate(result.graph)
    return result, matches


# Threshold grid. The defaults are in the grid so the current operating point
# appears in the table alongside the alternatives.
PEEL_GRID = {
    "low_activity_max": [2, 3, 4, 6],
    "min_chain_intermediates": [2, 3],
    "min_hop_retention": [0.3, 0.5, 0.7, 0.9],
}
SPLIT_GRID = {
    "min_split_branches": [3, 4, 5],
    "forward_band": [(0.5, 1.10), (0.7, 1.10), (0.8, 1.05), (0.9, 1.02)],
    "max_single_branch_share": [0.9, 0.8, 0.6],
}


def grid_points(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*grid.values())]


def config_for(point: dict) -> PatternConfig:
    cfg = PatternConfig()
    if "forward_band" in point:
        lo, hi = point["forward_band"]
        cfg = replace(cfg, min_forwarded_ratio=lo, max_forwarded_ratio=hi)
    rest = {k: v for k, v in point.items() if k != "forward_band"}
    return replace(cfg, **rest)


def fired(graph, cfg: PatternConfig, matcher: ExchangeMatcher, pattern: str) -> bool:
    return any(f.pattern == pattern for f in detect_patterns(graph, cfg, matcher.is_exchange))


def sweep(graphs: dict[str, tuple[str, object]], matcher: ExchangeMatcher, pattern: str, grid: dict) -> list[dict]:
    """graphs: address -> (corpus, graph). Returns one row per grid point."""
    positives = [g for c, g in graphs.values() if c == "positive"]
    controls = [g for c, g in graphs.values() if c == "control"]
    rows = []
    for point in grid_points(grid):
        cfg = config_for(point)
        tp = sum(fired(g, cfg, matcher, pattern) for g in positives)
        fp = sum(fired(g, cfg, matcher, pattern) for g in controls)
        rows.append({
            **{k: (list(v) if isinstance(v, tuple) else v) for k, v in point.items()},
            "positives_fired": tp,
            "controls_fired": fp,
            "recall": round(tp / len(positives), 3) if positives else None,
            "precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
        })
    return rows


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    head = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = ["| " + " | ".join(str(r[c]) for c in columns) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-fetch from the provider")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="trace only the first N of each corpus")
    args = parser.parse_args()

    corpus = json.loads(CORPUS_PATH.read_text())
    entries = [("positive", e) for e in corpus["positives"]] + [("control", e) for e in corpus["controls"]]
    if args.limit:
        entries = [x for x in entries if x[0] == "positive"][: args.limit] + \
                  [x for x in entries if x[0] == "control"][: args.limit]

    # One chain and one asset per run; the corpus is Ethereum / ETH today.
    chain, asset = "ethereum", "ETH"
    matcher = get_matcher(chain)
    risk = get_risk_matcher(chain)
    path = snapshot_path(chain, asset)
    store = load_snapshot(path)

    if args.refresh:
        if not config.ETHERSCAN_API_KEY:
            print("ETHERSCAN_API_KEY is not set")
            return 1
        live = EtherscanClient(chain_id=1)
        client = RecordingClient(live, store)
    else:
        client = SnapshotClient(store, asset)

    default = PatternConfig(native_symbol=asset)
    per_address: list[dict] = []
    graphs: dict[str, tuple[str, object]] = {}
    started = time.time()

    for index, (corpus_name, item) in enumerate(entries, 1):
        seed = item["address"]
        t0 = time.time()
        try:
            result, matches = trace_one(seed, client, matcher, risk, args.depth)
        except EtherscanError as exc:
            per_address.append({"address": seed, "corpus": corpus_name, "error": str(exc)[:120]})
            print(f"[{index}/{len(entries)}] {corpus_name:<8} {seed}  ERROR {str(exc)[:60]}")
            continue
        findings = detect_patterns(result.graph, default, matcher.is_exchange)
        patterns = sorted({f.pattern for f in findings})
        primary = ExchangeMatcher.primary_match(matches)
        # Deposit-address inference, measured the same way: a control *seed*
        # is a wallet known not to be a deposit address, so the rule firing
        # on one is a false positive. Firing on a deeper node is recorded but
        # cannot be scored -- nothing is known about those wallets either way.
        inferred = infer_deposit_addresses(result.graph, matcher)
        inferred_seed = any(m.address == seed for m in inferred)
        record = {
            "address": seed,
            "corpus": corpus_name,
            "why": item.get("why"),
            "nodes": result.node_count,
            "edges": result.edge_count,
            "outgoing_counterparties": result.graph.out_degree(seed),
            "exchange": primary.exchange if primary else None,
            "patterns": patterns,
            "pattern_addresses": {
                f.pattern: f.addresses[:4] for f in findings
            },
            "inferred_deposit_nodes": [m.address for m in inferred],
            "seed_inferred_as_deposit": inferred_seed,
            "api_calls": result.api_calls,
            "seconds": round(time.time() - t0, 1),
        }
        per_address.append(record)
        graphs[seed] = (corpus_name, result.graph)
        print(f"[{index}/{len(entries)}] {corpus_name:<8} {seed}  nodes={result.node_count:<4} "
              f"exch={primary.exchange if primary else '-':<12} patterns={','.join(patterns) or '-'}"
              f"  ({record['seconds']}s)")
        if args.refresh and index % 5 == 0:
            save_snapshot(path, store, {"chain": chain, "asset": asset, "depth": args.depth,
                                        "partial": True})

    if args.refresh:
        save_snapshot(path, store, {
            "chain": chain, "asset": asset, "depth": args.depth,
            "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "addresses": len(store),
            "note": "outgoing value-bearing transfers, newest first, as served by Etherscan txlist",
        })
        print(f"\nsnapshot: {len(store)} addresses -> {path}")

    # -- summary at the defaults ----------------------------------------------
    traced = [r for r in per_address if "error" not in r]
    active = [r for r in traced if r["outgoing_counterparties"] > 0]
    print(f"\ntraced {len(traced)} of {len(entries)} wallets in {time.time() - started:.0f}s; "
          f"{len(active)} had at least one outgoing transfer")

    summary: dict[str, dict] = {}
    for corpus_name in ("positive", "control"):
        rows = [r for r in active if r["corpus"] == corpus_name]
        summary[corpus_name] = {
            "wallets_with_outflow": len(rows),
            "wallets_traced": len([r for r in traced if r["corpus"] == corpus_name]),
            PEEL_CHAIN: sorted(r["address"] for r in rows if PEEL_CHAIN in r["patterns"]),
            AMOUNT_SPLIT: sorted(r["address"] for r in rows if AMOUNT_SPLIT in r["patterns"]),
            "reached_exchange": len([r for r in rows if r["exchange"]]),
            "seed_inferred_as_deposit": sorted(r["address"] for r in rows if r["seed_inferred_as_deposit"]),
            "traces_with_an_inferred_node": len([r for r in rows if r["inferred_deposit_nodes"]]),
            "inferred_nodes_total": sum(len(r["inferred_deposit_nodes"]) for r in rows),
        }
    print("\nAt the current defaults:")
    print(markdown_table([
        {
            "corpus": name,
            "wallets with outflow": s["wallets_with_outflow"],
            "peel chain fired": len(s[PEEL_CHAIN]),
            "amount split fired": len(s[AMOUNT_SPLIT]),
            "reached a labelled exchange": s["reached_exchange"],
            "seed inferred as deposit address": len(s["seed_inferred_as_deposit"]),
            "traces with an inferred deposit node": s["traces_with_an_inferred_node"],
        }
        for name, s in summary.items()
    ], ["corpus", "wallets with outflow", "peel chain fired", "amount split fired",
        "reached a labelled exchange", "seed inferred as deposit address",
        "traces with an inferred deposit node"]))
    for name, s in summary.items():
        for pattern in (PEEL_CHAIN, AMOUNT_SPLIT):
            for address in s[pattern]:
                record = next(r for r in traced if r["address"] == address)
                print(f"  {name:<8} {pattern:<12} {address}  {record['why']}")

    # -- threshold sweep --------------------------------------------------------
    active_graphs = {a: g for a, g in graphs.items()
                     if next(r for r in traced if r["address"] == a)["outgoing_counterparties"] > 0}
    peel_rows = sweep(active_graphs, matcher, PEEL_CHAIN, PEEL_GRID)
    split_rows = sweep(active_graphs, matcher, AMOUNT_SPLIT, SPLIT_GRID)

    print("\nPeel chain, by threshold:")
    print(markdown_table(peel_rows, ["low_activity_max", "min_chain_intermediates",
                                     "min_hop_retention", "positives_fired", "controls_fired",
                                     "recall", "precision"]))
    print("\nAmount split, by threshold:")
    print(markdown_table(split_rows, ["min_split_branches", "forward_band",
                                      "max_single_branch_share", "positives_fired",
                                      "controls_fired", "recall", "precision"]))

    RESULTS_PATH.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "depth": args.depth,
        "chain": chain, "asset": asset,
        "defaults": {k: v for k, v in default.__dict__.items() if k != "native_symbol"},
        "summary": summary,
        "per_address": per_address,
        "sweep": {PEEL_CHAIN: peel_rows, AMOUNT_SPLIT: split_rows},
    }, indent=2) + "\n")
    print(f"\nwrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
