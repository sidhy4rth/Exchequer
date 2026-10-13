"""The trace pipeline: one reported address in, one finished case out.

`run_trace` builds the transfer graph from the chain's provider, screens it
against the risk lists, matches exchanges (labelled, then inferred deposit
addresses), detects patterns and swaps, scores the result and estimates how
much of it is the reported funds. The HTTP layer (app/routes) and the
warm-up both call it; nothing here knows about requests or storage."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import networkx as nx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from . import config, log_safety
from .chain_data import ProviderNotConfiguredError, UnknownAssetError, open_source
from .etherscan_client import (
    EtherscanConfigError,
    EtherscanError,
    EtherscanRateLimitError,
    normalize_address,
)
from .deposit_inference import describe as describe_inference, infer_deposit_addresses
from .exchange_matcher import ExchangeMatcher, get_matcher, get_router_matcher
from .swap_detection import describe as describe_swap, detect_swaps
from .graph_builder import (
    INCOMING,
    OUTGOING,
    InvalidAddressError,
    InvalidDirectionError,
    TraceConfig,
    build_trace_graph,
    graph_to_dict,
)
from .pattern_detection import PatternConfig, detect_patterns, flag_names
from .risk_matcher import MIXER, REPORTED, RiskMatcher, get_risk_matcher
from .tron_tags import LiveTronExchanges, TronScanTags
from .prorata import estimate as estimate_prorata
from .scoring import principal_path, score_case


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class TraceRequest(BaseModel):
    address: str = Field(..., description="The victim-reported wallet address")
    max_depth: int | None = Field(
        None, ge=1, le=6, description="Override the hop limit (default 4, capped at 6)"
    )
    chain: str | None = Field(
        None,
        description=(
            "Which chain to trace on: 'ethereum' or 'bsc'. Defaults to the "
            "server's configured chain. The same address can exist on both, "
            "so this is never inferred from the address itself."
        ),
    )
    asset: str | None = Field(
        None,
        description=(
            "Which currency to follow: the chain's native symbol (ETH, BNB) or "
            "a stablecoin (USDT, USDC). One asset per trace -- 1 BNB and 1 USDT "
            "are not comparable, so a graph mixing them could not be scored. "
            "Defaults to the chain's native currency."
        ),
    )
    time_budget_seconds: int | None = Field(
        None, ge=10, le=600,
        description=(
            "Optional wall-clock cap. With it set the walk stops expanding once "
            "the time is spent and returns what it has, marked truncated with the "
            "reason. Without it the trace runs until the depth, fan-out and size "
            "limits stop it, however long that takes on the provider's free tier."
        ),
    )
    direction: str = Field(
        OUTGOING,
        pattern="^(outgoing|incoming)$",
        description=(
            "Which way to follow the money. 'outgoing' (default) chases where "
            "the reported address sent funds, answering which exchange they "
            "were cashed out at. 'incoming' walks backwards to the addresses "
            "that funded it -- on a scammer's wallet those senders are "
            "candidate victims of the same operation."
        ),
    )
    follow_swaps: bool = Field(
        True,
        description=(
            "When a forward trace finds the funds swapped at a DEX router into "
            "a stablecoin this chain carries (USDT, USDC), also trace that "
            "stablecoin from the wallet that swapped, starting at the swap. "
            "Each trace keeps its own asset, amounts and score."
        ),
    )
    save: bool = Field(
        True,
        description=(
            "Store the result as a case. The daily demo health check sets this "
            "false, so re-running the demos never fills the case history or "
            "makes a demo look like a repeat complaint."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _trace_path(
    graph: nx.DiGraph, seed: str, target: str, direction: str = OUTGOING
) -> list[dict[str, Any]]:
    """The shortest chain of addresses between the reported address and
    `target`, with the amount moved at each step. This is what goes in the
    report.

    Always read in the direction the money moved, so a reverse trace's path
    runs from the exchange down to the reported address rather than being
    printed backwards. The same route the score was computed along, so the
    report and the confidence working never describe two different paths.
    """
    source, destination = (seed, target) if direction == OUTGOING else (target, seed)
    try:
        path = principal_path(graph, source, destination)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    steps: list[dict[str, Any]] = []
    for i, node in enumerate(path):
        node_data = graph.nodes[node]
        step: dict[str, Any] = {
            "address": node,
            "depth": i,
            "label": node_data.get("label"),
            "exchange": node_data.get("exchange"),
            "flags": sorted(node_data.get("flags", [])),
        }
        if i > 0:
            edge = graph.edges[path[i - 1], node]
            step["value_native"] = round(edge.get("value_native", 0.0), 6)
            step["tx_count"] = edge.get("tx_count", 0)
            step["first_seen"] = edge.get("first_seen")
            step["last_seen"] = edge.get("last_seen")
            step["tx_hashes"] = [t.get("hash") for t in edge.get("transactions", [])][:20]
        steps.append(step)
    return steps


def _all_transfers(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """Every individual transfer in the trace, for the report's appendix.

    Kept out of `graph`, which the frontend draws as aggregate edges, and
    stored with the case so that anything the report says can be re-checked
    on a public explorer months later without re-tracing.
    """
    rows: list[dict[str, Any]] = []
    for src, dst, data in graph.edges(data=True):
        for tx in data.get("transactions", []):
            rows.append({
                "hash": tx.get("hash"),
                "from": src,
                "to": dst,
                "value_native": round(tx.get("value_native", 0.0), 6),
                "timestamp": tx.get("timestamp"),
                "internal": bool(tx.get("internal", False)),
            })
    rows.sort(key=lambda r: (r["timestamp"] or 0, r["hash"] or ""))
    return rows


def _hops_covered(graph: nx.DiGraph) -> int:
    """The deepest address the graph actually contains.

    Not the same as TraceResult.depth_reached, which counts how deep the walk
    *expanded* -- at max_depth=1 the addresses one hop out are found and then
    never expanded, so depth_reached is 0 while the graph plainly spans a hop.
    Reporting that to a user reads as "traced 11 addresses across 0 hops".
    """
    return max((data.get("depth", 0) for _, data in graph.nodes(data=True)), default=0)


def _direct_senders(graph: nx.DiGraph, seed: str) -> list[dict[str, Any]]:
    """Addresses that paid the reported address directly, largest first.

    This is what a reverse trace is actually for. If the reported address
    belongs to a scammer, these are the people who sent money to it, and each
    one is a candidate victim of the same operation.

    Deliberately named for what is observable. These addresses *funded the
    reported address*; calling them victims would be an inference this tool
    cannot support from transaction data alone, since a sender may equally be
    the scammer's own wallet, an exchange withdrawal, or an unrelated payment.
    """
    senders: list[dict[str, Any]] = []
    for sender, _, edge in graph.in_edges(seed, data=True):
        data = graph.nodes[sender]
        senders.append(
            {
                "address": sender,
                "value_native": round(edge.get("value_native", 0.0), 6),
                "tx_count": edge.get("tx_count", 0),
                "first_seen": edge.get("first_seen"),
                "last_seen": edge.get("last_seen"),
                # A sender that is itself a labelled exchange is not a victim:
                # it is a withdrawal, and saying so prevents the obvious
                # misreading of this list.
                "exchange": data.get("exchange"),
                "risk_category": data.get("risk_category"),
            }
        )
    senders.sort(key=lambda item: item["value_native"], reverse=True)
    return senders


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
STATEMENT_ROWS = 25


def _wallet_statement(client: Any, address: str) -> dict[str, Any] | None:
    """The reported address's latest credits and debits, newest first.

    Read from the same provider as the trace (the outgoing side is usually a
    cache hit, since the walk just asked for it). A provider that cannot list
    incoming transfers, or fails, costs the statement, never the trace.
    """
    def rows(txs: list[Any], counterparty: str) -> list[dict[str, Any]]:
        return [{"tx": t.hash, "time": t.timestamp, "amount": round(t.value_native, 6),
                 "counterparty": getattr(t, counterparty)} for t in txs[:STATEMENT_ROWS]]
    try:
        sent = client.get_outgoing_transactions(address, limit=STATEMENT_ROWS)
        # Read deeper than the rows shown: address-poisoning dust can arrive by
        # the dozen and would otherwise push every real credit off the list.
        received = (client.get_incoming_transactions(address, limit=STATEMENT_ROWS * 4)
                    if hasattr(client, "get_incoming_transactions") else [])
    except Exception as exc:  # noqa: BLE001 -- a statement is never worth a failed trace
        logger.warning("Wallet statement for %s failed: %s", address, exc)
        return None
    debits = rows(sent, "to_address")
    credits = [{"tx": t.hash, "time": t.timestamp, "amount": round(t.value_native, 6),
                "counterparty": t.from_address} for t in received]
    # Address poisoning: a stranger sends dust from an address whose first and
    # last characters copy one this wallet really paid, hoping the owner later
    # copies the lookalike from their history. Marked, never hidden.
    paid = {(d["counterparty"] or "").lower() for d in debits}
    shapes = {(p[:6], p[-4:]) for p in paid if p}
    for row in credits:
        c = (row["counterparty"] or "").lower()
        row["lookalike"] = bool(c) and c not in paid and (c[:6], c[-4:]) in shapes
    lookalikes = [r for r in credits if r["lookalike"]]
    return {
        "debits": debits,
        "credits": [r for r in credits if not r["lookalike"]][:STATEMENT_ROWS],
        "poisoning": lookalikes[:10],
        "rows_per_side": STATEMENT_ROWS,
        "lookalikes": len(lookalikes),
    }


# How many swaps one trace will follow into another asset. Each follow-on is a
# whole trace -- a second set of provider requests -- so it is capped the way
# receipts are.
MAX_FOLLOW_ONS = 2


def run_trace(request: TraceRequest, seed_window: int | None = None) -> dict[str, Any]:
    """Run one trace and return the full result, without storing it.

    `seed_window` is set only for a follow-on trace after a swap: the time rule
    then applies to the starting wallet too (see build_trace_graph).

    Everything the endpoint does except the case record: the endpoint gives
    the result a case id and saves it; the startup warm-up runs the demo
    addresses through this and keeps nothing, so the provider responses are
    cached without a row appearing in the case store.
    """
    address = request.address.strip()
    direction = request.direction

    # Which chain. Never inferred from the address: an EVM address is valid on
    # every EVM chain, and the same address can hold funds on both Ethereum and
    # BSC with entirely unrelated histories. Guessing would silently trace the
    # wrong ledger.
    try:
        chain = config.get_chain(request.chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Edge case: malformed address, or an address from the wrong family. The
    # check is per chain: a 0x address is well formed but meaningless on Tron,
    # and telling the user which format this chain expects is more use than
    # calling it invalid.
    if not chain.validate_address(address):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{address}' is not a valid {chain.name} address. "
                f"Expected {chain.address_hint()}."
            ),
        )

    seed = normalize_address(address)
    matcher = get_matcher(chain.key)
    risk_matcher = get_risk_matcher(chain.key)
    routers = get_router_matcher(chain.key)
    trace_config = TraceConfig(
        max_depth=request.max_depth or config.TRACE_MAX_DEPTH,
        time_budget_seconds=float(request.time_budget_seconds) if request.time_budget_seconds else None,
    )

    # Which asset this trace follows. Everything downstream -- edge values,
    # pattern thresholds, the confidence score, the report -- is denominated in
    # this one asset.
    asset_symbol = (request.asset or chain.native_symbol).strip().upper()
    token = chain.find_token(asset_symbol)
    is_native = token is None

    live: LiveTronExchanges | None = None
    try:
        with open_source(chain, asset_symbol) as client:
            # On Tron, a wallet no label file names is asked about: TronScan's
            # own tag, read live, attributes it when it names an exchange.
            if chain.key == "tron":
                live = LiveTronExchanges(
                    TronScanTags(config.TRONSCAN_API_KEY, evidence=getattr(client, "evidence", None)),
                    matcher.is_exchange,
                )
            result = build_trace_graph(
                seed,
                client,
                cfg=trace_config,
                # Three quite different reasons to stop. An exchange is where
                # the trail *ends*: the funds arrived, and those wallets have
                # millions of unrelated transactions. A mixer is where the trail
                # *breaks*: its payouts come from a commingled pool, so
                # expanding through one would invent a path the transactions do
                # not support. A swap router is where the trail *changes
                # asset*: the funds came straight back to the sender as a
                # different token, and a router contract has no outgoing
                # transfers of its own to follow anyway.
                is_terminal=lambda a: (
                    matcher.is_exchange(a) or risk_matcher.is_terminal(a) or routers.is_exchange(a)
                    or (live is not None and live.is_exchange(a))
                ),
                direction=direction,
                seed_window=seed_window,
            )
            if live is not None:
                # The last hop is never checked during the walk; ask now, then
                # attribute against the file's labels plus what TronScan named.
                live.sweep(result.graph)
                if live.found:
                    matcher = ExchangeMatcher({**matcher._labels, **live.found}, chain=chain.key)
                if live.warnings:
                    # A label file's entry always outranks the explorer's warning.
                    risk_matcher = RiskMatcher({**live.risk_labels(REPORTED), **risk_matcher._labels},
                                               chain=chain.key)
            # Swaps. Reads one receipt per router-bound transfer (capped) so
            # the response can say what asset the money became.
            swaps = detect_swaps(
                result.graph, routers,
                receipt_of=getattr(client, "get_transaction_receipt", None),
                chain=chain, asset_symbol=asset_symbol,
                asset_contract=token.address if token else None,
            ) if direction == OUTGOING else []
            # Attribution. Exact label-file matches first, then addresses whose
            # outgoing history is nothing but sweeps into one of those labelled
            # wallets -- inferred deposit addresses. The inference runs while
            # the provider is still open so it can record the address's
            # current balance as evidence (forward traces only: a reverse
            # trace fetches inflows, and the rule reads outflows).
            matches = matcher.annotate(result.graph, direction)
            inferred = []
            if direction == OUTGOING:
                inferred = infer_deposit_addresses(
                    result.graph, matcher,
                    balance_of=getattr(client, "get_balance_native", None),
                )
            # Every provider response the trace was computed from, hashed on
            # arrival. Taken while the client is still open, after the last
            # call that could add to it (the balance reads above).
            # Pro-rata: how much of the reported funds likely reached the
            # exchange, reading what else joined them in each wallet on the path.
            prorata = None
            lead = ExchangeMatcher.primary_match(matches + inferred)
            if direction == OUTGOING and lead is not None and lead.address != seed:
                try:
                    lead_path = principal_path(result.graph, seed, lead.address)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    lead_path = []
                prorata = estimate_prorata(result.graph, lead_path,
                                           getattr(client, "get_incoming_between", None))
            # The reported wallet's own statement: what it received and sent in
            # this asset, whether or not anything could be followed onward.
            statement = _wallet_statement(client, seed) if seed_window is None else None
            # A provider that searches a block range (NodeReal) says how far
            # back it looked when it found nothing, so "sent nothing" is never
            # claimed for history the search did not reach.
            searched_since = None
            floor = (getattr(client, "searched_from", None) or {}).get(seed)
            if floor is not None and hasattr(client, "block_time"):
                searched_since = client.block_time(floor)
            deep = (getattr(client, "deep_searched", None) or {}).get(seed)
            evidence = client.evidence.manifest() if hasattr(client, "evidence") else None
            # Whether contract-moved value was part of the data, for the
            # limitations paragraph. Only the Etherscan native path reads it.
            internal_read = bool(getattr(client, "include_internal", False)) and is_native
    except UnknownAssetError as exc:
        # Edge case: the request named an asset this chain does not carry.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        # Edge case: the chain has no usable data provider. That is a fixable
        # server configuration problem, not an upstream failure.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EtherscanConfigError as exc:
        # Edge case: no API key configured.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EtherscanRateLimitError as exc:
        # Edge case: Etherscan rate limit survived all retries.
        raise HTTPException(
            status_code=429,
            detail=(
                "Etherscan rate limit reached and did not clear after retries. "
                "Wait a few seconds and try again."
            ),
        ) from exc
    except EtherscanError as exc:
        # Edge case: any other upstream failure. The full message (which can
        # quote the provider's response body) goes to the log; the caller gets
        # the provider and the short reason only.
        logger.warning("Provider failure on %s: %s", chain.key, log_safety.redact(str(exc)))
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not reach the blockchain data provider "
                f"({type(exc).__name__.removesuffix('Error')}). Try again in a minute."
            ),
        ) from exc
    except InvalidAddressError as exc:  # defensive; validated above
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidDirectionError as exc:  # defensive; the request model validates it
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if live is not None:
            live.tags.close()

    graph = result.graph

    # Patterns, score. An inferred deposit address one hop before the hot
    # wallet is the address a lawful request must name, so it leads when it
    # is closer; a label-file match wins any tie.
    matches = matches + inferred
    primary = ExchangeMatcher.primary_match(matches)
    # Sanctions / mixer screening. Runs after exchange annotation so a node
    # that is somehow on both lists keeps both sets of tags.
    risk_matches = risk_matcher.annotate(graph, direction)
    findings = detect_patterns(
        graph, PatternConfig(native_symbol=asset_symbol), matcher.is_exchange
    )
    confidence = score_case(
        graph,
        seed,
        primary,
        findings,
        max_depth=trace_config.max_depth,
        truncated=result.truncated,
        native_symbol=asset_symbol,
        direction=direction,
        internal_transfers_read=internal_read,
        prorata=prorata,
    )

    # Swaps into a stablecoin this chain carries are followed as their own
    # traces, before the message is written, so the message can say where the
    # money went after it changed asset.
    follow_ons: list[dict[str, Any]] = []
    if direction == OUTGOING and request.follow_swaps and seed_window is None and swaps:
        follow_ons = _follow_swaps(request, chain, asset_symbol, graph, swaps, trace_config.max_depth,
                                   seconds_spent=result.seconds_elapsed or 0.0)
    followed = next((f for f in follow_ons if (f.get("result") or {}).get("exchange")), None)

    # Edge case: the address has never sent anything. Not an error -- a finding.
    message: str | None = None
    if result.edge_count == 0:
        others = [chain.native_symbol] + [t.symbol for t in chain.tokens]
        others = [a for a in others if a != asset_symbol]
        alternatives = f" — try {' or '.join(others)}." if others else "."
        since = (
            f" since {datetime.fromtimestamp(searched_since, tz=timezone.utc):%d %b %Y}"
            if searched_since else ""
        )
        if direction == OUTGOING and since:
            message = (
                f"No {asset_symbol} with value was sent by this address in the history "
                f"searched ({chain.name}{since}). "
                + ("Its earlier sends were located and read too, and none moved "
                   f"{asset_symbol}. " if deep else "")
                + "It may have only received funds, or the money may have moved as a "
                "different asset" + alternatives
            )
        elif direction == OUTGOING:
            message = (
                f"This address sent no {asset_symbol} with value, so there is "
                f"nothing to trace in {asset_symbol}. It may have only received "
                "funds, or the money may have moved as a different asset"
                + alternatives
            )
        elif since:
            message = (
                f"No {asset_symbol} with value reached this address in the history "
                f"searched ({chain.name}{since}). Earlier deposits are outside what a "
                "reverse trace on this chain reads; a forward trace from the sender "
                "finds them" + "."
            )
        else:
            message = (
                f"This address received no {asset_symbol} with value, so there "
                f"is nothing to trace back in {asset_symbol}. It may have only "
                "sent funds, or the money may have arrived as a different asset"
                + alternatives
            )
    elif primary is None and any(m.category == MIXER for m in risk_matches):
        # Edge case: the trail did not go cold, it was deliberately cut. Saying
        # "no exchange found" here would understate what was actually
        # discovered, which is that the funds were sent to a tumbler.
        mixers = [m for m in risk_matches if m.category == MIXER]
        names = sorted({m.entity for m in mixers})
        message = (
            f"The trace stopped at {'a mixer' if len(mixers) == 1 else 'mixers'} "
            f"({', '.join(names)}) rather than at an exchange. Funds entering a "
            "mixer are paid out from a commingled pool, so transfers leaving it "
            "cannot be linked to this deposit by on-chain evidence and following "
            "them would manufacture a trail. Routing funds through a mixer is "
            "itself a substantive finding and is grounds for escalation."
        )
    elif primary is None and followed is not None:
        # Edge case: no exchange in this asset, but the money changed asset
        # and the follow-on trace found where it went. The answer is the
        # follow-on's, scored within its own asset and said to be so.
        swap, found = followed["swap"], followed["result"]
        hops = found["hop_count"]
        message = (
            f"No exchange was reached in {asset_symbol}, but the funds were swapped: "
            f"{swap['sender']} exchanged {swap['amount_in']:.4f} {asset_symbol} for "
            f"{followed['asset']} at {swap['router_label']}. Exchequer followed the "
            f"{followed['asset']} from the swap: it reached {found['exchange']} "
            f"({found['exchange_label']}) in {hops} hop{'s' if hops != 1 else ''}, "
            f"confidence {found['confidence']:.2f} — scored within the "
            f"{followed['asset']} trace alone, since {asset_symbol} and "
            f"{followed['asset']} amounts are not comparable."
        )
    elif primary is None and any(s.get("output_read") for s in swaps):
        # Edge case: the trail did not go cold, it changed asset. Saying which
        # asset and where to resume is the whole point of detecting it.
        first = next(s for s in swaps if s.get("output_read"))
        others = len([s for s in swaps if s.get("output_read")]) - 1
        message = (
            f"No exchange was reached in {asset_symbol}, but the funds were swapped: "
            f"{first['sender']} exchanged {first['amount_in']:.4f} {asset_symbol} for "
            f"{first['asset_out']} at {first['router_label']}"
            + (f" (and {others} more swap{'s' if others != 1 else ''} were found)" if others else "")
            + f". This trace follows {asset_symbol} and ends there; "
            + (
                f"Exchequer followed the {first['asset_out']} from the swap as its own trace "
                "(see the follow-on) and it reached no known exchange either."
                if any(f["address"] == first["sender"] and f["asset"] == first["asset_out"]
                       and f.get("result") for f in follow_ons)
                else f"re-run it on {first['asset_out']} from {first['sender']} to follow the money further."
            )
        )
    elif primary is None and direction == INCOMING:
        # Edge case: no exchange upstream. On a reverse trace that is a minor
        # result -- the senders are what was being looked for.
        senders = graph.in_degree(seed)
        hops = _hops_covered(graph)
        message = (
            f"Traced {result.node_count} addresses back across "
            f"{hops} hop{'s' if hops != 1 else ''}. {senders} address"
            f"{'es' if senders != 1 else ''} funded the reported address "
            "directly. None of the upstream addresses matched a known exchange "
            "wallet, so the funds could not be traced back to a point of "
            "purchase or withdrawal."
        )
    elif primary is None:
        # Edge case: traced fine, but nothing matched a known exchange.
        hops = _hops_covered(graph)
        message = (
            f"Traced {result.node_count} addresses across {hops} "
            f"hop{'s' if hops != 1 else ''}, but none matched a known exchange "
            "wallet. The funds may not have reached an exchange yet, may have "
            "gone to one not in the label database, or may lie beyond the hop "
            "limit."
        )

    payload: dict[str, Any] = {
        # -- the documented API contract --
        "case_id": None,  # set by the endpoint when the case is stored
        "graph": graph_to_dict(graph),
        "exchange": primary.exchange if primary else None,
        "confidence": confidence.score,
        "flags": flag_names(findings),
        "hop_count": primary.depth if primary else result.depth_reached,
        # -- supporting detail, used by the sidebar and the report --
        "address": seed,
        "direction": direction,
        "chain": chain.key,
        "chain_name": chain.name,
        "chain_id": chain.chain_id,
        "native_symbol": asset_symbol,
        "chain_native_symbol": chain.native_symbol,
        "asset": asset_symbol,
        "asset_is_native": is_native,
        "asset_contract": token.address if token else None,
        "explorer_url": chain.explorer_url,
        "created_at": None,  # set with the case id
        "message": message,
        "statement": statement,
        "prorata": prorata,
        "exchange_address": primary.address if primary else None,
        "exchange_label": primary.label if primary else None,
        # True when the attribution names an inferred deposit address rather
        # than a label-file wallet. The evidence is in `matches` and the
        # sentence in `inference_notes`.
        "attribution_inferred": bool(primary and primary.inferred),
        "inferred_deposits": [m.to_dict() for m in inferred],
        "inference_notes": [describe_inference(m, asset_symbol) for m in inferred],
        "value_received_native": (
            round(primary.value_received_native, 6) if primary else None
        ),
        "matches": [m.to_dict() for m in matches],
        # Sanctions / mixer screening. `risk_flags` mirrors `flags` so the
        # frontend can render both the same way; `risk_notes` are report-ready
        # sentences so neither the UI nor the report has to re-phrase them.
        "risk_matches": [m.to_dict() for m in risk_matches],
        "risk_flags": sorted({m.category for m in risk_matches}),
        "risk_notes": [m.describe(asset_symbol) for m in risk_matches],
        "findings": [f.to_dict() for f in findings],
        # Transfers into DEX routers, with what came back where the receipt
        # showed it. The graph edge carries the same record as `swap`.
        "swaps": swaps,
        "swap_notes": [describe_swap(s) for s in swaps],
        # Tron only: wallets attributed from TronScan's tag at trace time.
        "live_tags": live.summary() if live is not None else None,
        # Traces that continued in the swap's output asset. Each carries its
        # own complete result, so its score and amounts stay in one asset.
        "follow_ons": follow_ons,
        "followed_attribution": (
            {
                "asset": followed["asset"],
                "address": followed["address"],
                "swap_tx": followed["swap"].get("tx"),
                "exchange": followed["result"]["exchange"],
                "exchange_label": followed["result"]["exchange_label"],
                "exchange_address": followed["result"]["exchange_address"],
                "attribution_inferred": followed["result"]["attribution_inferred"],
                "confidence": followed["result"]["confidence"],
                "hop_count": followed["result"]["hop_count"],
            }
            if followed else None
        ),
        "confidence_detail": confidence.to_dict(),
        "trace_path": (
            _trace_path(graph, seed, primary.address, direction) if primary else []
        ),
        # Only populated on a reverse trace: the seed has no inbound edges when
        # the walk ran outward.
        "direct_senders": _direct_senders(graph, seed),
        "transfers": _all_transfers(graph),
        "depth_reached": result.depth_reached,
        "max_depth": trace_config.max_depth,
        # The clock, if the caller set one, and what it cost: how long the walk
        # took and how many reached addresses it left unexpanded.
        "time_budget_seconds": request.time_budget_seconds,
        "seconds_elapsed": result.seconds_elapsed,
        "addresses_unexpanded_by_time": result.addresses_unexpanded_by_time,
        "addresses_expanded": result.addresses_expanded,
        "transfers_excluded_by_time": result.transfers_excluded_by_time,
        "api_calls": result.api_calls,
        # Hash-and-timestamp of every response above; see app/evidence.py.
        "evidence": evidence,
        "truncated": result.truncated,
        "truncation_reasons": result.truncation_reasons,
        "warnings": result.warnings,
    }
    return payload


def _follow_swaps(
    request: TraceRequest,
    chain: config.Chain,
    asset_symbol: str,
    graph: Any,
    swaps: list[dict[str, Any]],
    max_depth: int,
    seconds_spent: float = 0.0,
) -> list[dict[str, Any]]:
    """Trace the output asset of each swap into a stablecoin this chain carries.

    One follow-on per (wallet, output asset), at most MAX_FOLLOW_ONS, over the
    hops the original trace had left beyond the swapping wallet (at least one).
    The follow-on starts at the swap: the time rule excludes anything the
    wallet sent in the new asset before the swap's output arrived. It follows
    everything the wallet sent in that asset afterwards, which may include
    money that was not the swap's output; the swap's amount is kept beside the
    result so a reader can compare. Follow-ons never follow further swaps.

    A time budget covers the whole case, not each trace: follow-ons share what
    the original trace left of it, and one that would start with less than the
    minimum budget is recorded as not traced rather than run over the limit.
    """
    traceable = {t.symbol for t in chain.tokens}
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for swap in swaps:
        asset_out = swap.get("asset_out")
        if not swap.get("output_read") or asset_out not in traceable or asset_out == asset_symbol:
            continue
        key = (swap["sender"], asset_out)
        if key in seen:
            continue
        seen.add(key)
        if len(out) >= MAX_FOLLOW_ONS:
            break
        depth_at = (graph.nodes.get(swap["sender"]) or {}).get("depth", 0)
        remaining = max(1, max_depth - depth_at)
        follow = {"swap": swap, "asset": asset_out, "address": swap["sender"], "max_depth": remaining}
        budget = None
        if request.time_budget_seconds:
            budget = int(request.time_budget_seconds - seconds_spent)
            if budget < 10:
                follow["error"] = "not traced: the case's time budget was spent before this swap could be followed"
                out.append(follow)
                continue
        sub = TraceRequest(
            address=swap["sender"], chain=chain.key, asset=asset_out, max_depth=remaining,
            direction=OUTGOING, time_budget_seconds=budget, follow_swaps=False,
        )
        try:
            follow["result"] = run_trace(sub, seed_window=swap.get("timestamp"))
            seconds_spent += follow["result"].get("seconds_elapsed") or 0.0
        except HTTPException as exc:
            # A follow-on that fails must not cost the trace that found it.
            follow["error"] = str(exc.detail)
        out.append(follow)
    return out
