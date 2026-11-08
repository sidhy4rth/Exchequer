"""The trace pipeline: one reported address in, one finished case out.

`run_trace` builds the transfer graph from the chain's provider, screens it
against the risk lists, matches exchanges (labelled, then inferred deposit
addresses), detects patterns and swaps, scores the result and estimates how
much of it is the reported funds. The HTTP layer (app/routes) and the
warm-up both call it; nothing here knows about requests or storage."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import networkx as nx
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from . import config, log_safety, progress
from .api_budget import PROVIDER_NAMES, BudgetSpent, Cancelled, TraceBudget, TraceStopped, current_budget
from .chain_data import ProviderNotConfiguredError, UnknownAssetError, allowance_spent, open_source
from .contracts import upgrade as upgrade_to_contract
from .provenance import capture as capture_provenance
from .payment_intake import (
    PaymentError,
    PaymentRef,
    intake_record,
    leg_warnings,
    normalize_hash,
    reported_amount,
    resolve_payments,
    review_payments,
    window_anchor,
)
from .etherscan_client import (
    ProviderQuotaError,
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
from .scoring import principal_path, reach_bottlenecks, score_case, seed_outflow
from .tracing_methods import compare as compare_methods, read_once


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
# An NCRP acknowledgement number: ASCII digits only (no letters, spaces,
# control or direction-changing characters).
_NCRP = re.compile(r"[0-9]{10,20}")


class TraceRequest(BaseModel):
    # No address is near 128 characters; a longer one is refused before it is read.
    address: str = Field(..., max_length=128, description="The victim-reported wallet address")
    max_depth: int | None = Field(
        None, ge=1, le=6,
        description="Override the hop limit (default 4). Never deeper than the server's ceiling (6 by default)",
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
            "A shorter wall-clock cap than the server's. The walk stops expanding "
            "once the time is spent and returns what it has, marked truncated with "
            "the reason. Without it the server's default applies (180 s unless "
            "configured), and no request may run longer than the server's maximum."
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
    payments: list[PaymentRef] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "The victim's payments, by transaction hash (R1, behind "
            "EXCHEQUER_TX_INTAKE). Each must be an incoming transfer to "
            "`address` in the traced asset; the trace then starts when the "
            "first one arrived, and reported_amount is their sum. Outgoing "
            "traces only."
        ),
    )
    ncrp_ack: str | None = Field(
        None, max_length=64,
        description=(
            "The NCRP complaint acknowledgement number, recorded with the case "
            "as entered by the requester: 10 to 20 digits."
        ),
    )

    victim_address: str | None = Field(
        None, max_length=100,
        description=(
            "The victim's own paying wallet, if the complaint gives it. Sent with "
            "`payments` only: each payment's sender is compared with it, and a "
            "payment from another wallet is warned about in the case."
        ),
    )

    @field_validator("victim_address", mode="before")
    @classmethod
    def _victim_blank(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("ncrp_ack", mode="before")
    @classmethod
    def _ncrp_shape(cls, value: Any) -> Any:
        # Digits only: free text here was shown on the case page as "NCRP
        # <value>", lending a police reference to any anonymous trace.
        if value is None or not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return None
        if not _NCRP.fullmatch(value):
            raise ValueError("An NCRP acknowledgement number is 10 to 20 digits.")
        return value


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
                # The block lets a reader re-find the transfer on any node
                # (case contract v2, docs/contracts/case.md).
                "block": tx.get("block_number"),
            })
    rows.sort(key=lambda r: (r["timestamp"] or 0, r["hash"] or ""))
    return rows


def appendix_sha256(rows: list[dict[str, Any]]) -> str:
    """SHA-256 over every transfer of a trace, one canonical JSON line each
    (sorted keys, no spaces) in _all_transfers order (docs/contracts/case.md)."""
    lines = "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in rows)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _appendix(rows: list[dict[str, Any]], keep_edges: set[tuple[str, str]],
              keep_to: set[str]) -> dict[str, Any]:
    """The transfers a case lists, and what it commits to about all of them.

    The appendix listed every transfer on every followed edge, so a dense
    cluster made a 21 MB case. Past config.TRANSFERS_APPENDIX_MAX it keeps
    every transfer on `keep_edges` (the route to the exchange and the
    reported address's own hops) and into `keep_to` (each matched or
    inferred exchange address, whose transfers a letter lists), then the
    largest of the rest by value. The full count and a hash over all of
    them are kept, so the case still commits to every transfer."""
    limit = config.TRANSFERS_APPENDIX_MAX
    listed = rows
    if limit and len(rows) > limit:
        must = [r for r in rows if (r["from"], r["to"]) in keep_edges or r["to"] in keep_to]
        kept = {id(r) for r in must}
        rest = sorted((r for r in rows if id(r) not in kept), key=lambda r: -(r["value_native"] or 0))
        chosen = {id(r) for r in must + rest[:max(0, limit - len(must))]}
        listed = [r for r in rows if id(r) in chosen]  # in the full list's order
    return {"transfers": listed, "transfers_total": len(rows), "transfers_omitted": len(rows) - len(listed),
            "transfers_sha256": appendix_sha256(rows)}


def _appendix_edges(graph: nx.DiGraph, seed: str, direction: str, primary: Any) -> set[tuple[str, str]]:
    """The edges whose every transfer a case lists: the reported address's own
    (out of it, or into it on a reverse trace) and each on the route to the exchange."""
    edges = set(graph.out_edges(seed) if direction == OUTGOING else graph.in_edges(seed))
    if primary is not None:
        source, destination = (seed, primary.address) if direction == OUTGOING else (primary.address, seed)
        try:
            path = principal_path(graph, source, destination)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            path = []
        edges |= set(zip(path, path[1:], strict=False))
    return edges


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


def _wallet_statement(client: Any, address: str, window_start: int | None = None) -> dict[str, Any] | None:
    """The reported address's latest credits and debits, newest first.

    Read from the same provider as the trace (the outgoing side is usually a
    cache hit, since the walk just asked for it). A provider that cannot list
    incoming transfers, or fails, costs the statement, never the trace.

    `window_start` (a payment trace) marks each row from before the first
    payment arrived with `before_window`: shown, never hidden, since the
    officer may still want to see what the wallet did beforehand.
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
    statement = {
        "debits": debits,
        "credits": [r for r in credits if not r["lookalike"]][:STATEMENT_ROWS],
        "poisoning": lookalikes[:10],
        "rows_per_side": STATEMENT_ROWS,
        "lookalikes": len(lookalikes),
    }
    if window_start is not None:
        statement["window_start"] = window_start
        for row in debits + credits:
            row["before_window"] = (row["time"] or 0) < window_start
    return statement


# How many swaps one trace will follow into another asset. Each follow-on is a
# whole trace -- a second set of provider requests -- so it is capped the way
# receipts are.
MAX_FOLLOW_ONS = 2


def check_request(request: TraceRequest) -> tuple[config.Chain, str]:
    """The checks a trace can fail before it reads anything: the chain, the
    address and the asset. Run by the endpoints before a trace is admitted,
    so a typo is refused without spending the caller's hourly allowance,
    and again by run_trace itself. Returns the chain and the stripped address."""
    address = request.address.strip()

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
        # Quoted short: the error repeats what was typed, never all of it.
        shown = address if len(address) <= 64 else address[:64] + "…"
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{shown}' is not a valid {chain.name} address. "
                f"Expected {chain.address_hint(address)}."
            ),
        )

    asset = (request.asset or chain.native_symbol).strip().upper()
    if asset != chain.native_symbol.upper() and chain.find_token(asset) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{chain.name} has no traceable asset called '{asset}'. "
                f"Available: {chain.native_symbol}, " + ", ".join(t.symbol for t in chain.tokens)
            ),
        )
    # Today's provider allowance for the whole site (api_budget.UnitMeter):
    # once it is used up, a new trace is refused before it is admitted.
    wait = allowance_spent(chain)
    if wait is not None:
        raise HTTPException(status_code=503, detail=allowance_used_up(chain), headers={"Retry-After": str(wait)})
    # Payments (R1) are checked here too, before anything is spent: the flag
    # must be on, and a payment starts a trace of where the money went.
    if request.payments:
        if not config.TX_INTAKE:
            raise HTTPException(
                status_code=400,
                detail="Tracing from payment hashes is not switched on (EXCHEQUER_TX_INTAKE).",
            )
        if request.direction != OUTGOING:
            raise HTTPException(
                status_code=400,
                detail="Payments start a trace of where the money went: use direction 'outgoing'.",
            )
        seen: set[str] = set()
        for ref in request.payments:
            key = normalize_hash(ref.tx_hash)
            if key in seen:
                raise HTTPException(status_code=400, detail=f"Payment {ref.tx_hash} is listed twice.")
            seen.add(key)
    # The victim's own wallet is only ever compared with their payments. Never
    # echoed back: it is the complaint's, not the reported address.
    if request.victim_address is not None:
        if not request.payments:
            raise HTTPException(
                status_code=400,
                detail="The victim's wallet is compared with their payments: send it with the payment hashes.",
            )
        if not chain.validate_address(request.victim_address):
            raise HTTPException(
                status_code=400,
                detail=f"The victim's wallet is not a valid {chain.name} address. Expected {chain.address_hint()}.",
            )
        if normalize_address(request.victim_address) == normalize_address(address):
            raise HTTPException(
                status_code=400,
                detail="The victim's wallet is the reported wallet: enter the wallet the victim paid from.",
            )
    return chain, address


def allowance_used_up(chain: config.Chain) -> str:
    name = PROVIDER_NAMES.get(chain.provider, chain.provider)
    return (f"Today's {name} allowance for this site is used up, so live tracing on {chain.name} "
            "resumes at 00:00 UTC. Stored cases and the verified examples still open.")


def _seed_cap(intake: dict[str, Any] | None, seed_amount: float | None,
              seed_amount_basis: str | None, seed_share: float | None = None,
              ) -> tuple[float | None, str | None]:
    """What the traced figure may never exceed, and why: the victim's reported
    payments on an intake trace, or what the swaps returned on a follow-on.
    With `seed_share` below 1 a follow-on's cap is only the traced money's
    share of that output ("swap_share"): the swapping wallet added its own."""
    if intake and intake.get("payments"):
        return reported_amount(intake["payments"]), "reported_amount"
    if seed_amount is not None and seed_amount > 0:
        if seed_share is not None and seed_share < 1:
            return round(float(seed_amount) * seed_share, 6), "swap_share"
        return float(seed_amount), seed_amount_basis or "swap_output"
    return None, None


def _materiality(graph: nx.DiGraph, seed: str, direction: str, matches: list,
                 untraced: list[dict[str, Any]], intake: dict[str, Any] | None,
                 seed_amount: float | None = None, seed_amount_basis: str | None = None,
                 ) -> tuple[dict[str, Any], dict[str, float]]:
    """Each match's share of what the reported address sent, and the case's
    materiality record (pipeline.run_trace fills in the primary's figures).

    Share = the most value that could have reached the match along a shortest
    path (scoring.reach_bottlenecks) / a denominator: the victim's reported
    payments for an intake trace, the swap's output for a follow-on, else the
    reported wallet's outflow as the trace saw it (scoring.seed_outflow)."""
    reach = reach_bottlenecks(graph, seed, direction)
    outflow = seed_outflow(graph, seed, direction, untraced)
    cap, cap_basis = _seed_cap(intake, seed_amount, seed_amount_basis)
    denominator, basis = (cap, cap_basis) if cap else (outflow, "seed_outflow")
    shares: dict[str, float] = {}
    for m in matches:
        if m.address == seed:
            shares[m.address] = 1.0
        elif denominator:
            shares[m.address] = min(1.0, reach.get(m.address, 0.0) / denominator)
    threshold = config.ATTRIBUTION_MATERIAL_SHARE
    material = sorted({m.exchange for m in matches if shares.get(m.address, 0.0) >= threshold})
    return {
        "basis": basis,
        "denominator": round(denominator or 0.0, 6),
        "seed_outflow": round(outflow, 6),
        "threshold": threshold,
        "majority": config.ATTRIBUTION_MAJORITY_SHARE,
        "primary_share": None,
        "primary_reach": None,
        "reach_method": "path_upper_bound",
        "material_exchanges": material,
        "multiple_exchanges": len(material) > 1,
        "reach": reach,
    }, shares


# How the 502 below names the provider (an exception's class name read as
# "ProviderResponse" or "TronResponse" once failures had kinds).
_PROVIDER_NAMES = {"etherscan": "Etherscan", "nodereal": "NodeReal", "trongrid": "TronGrid"}


def run_trace(request: TraceRequest, seed_window: int | None = None,
              budget: TraceBudget | None = None, depth_offset: int = 0,
              seed_amount: float | None = None, seed_amount_basis: str | None = None,
              *, is_follow_on: bool = False, seed_share: float | None = None) -> dict[str, Any]:
    """Run one trace and return the full result, without storing it.

    `seed_window` is a time rule for the starting wallet (see
    build_trace_graph): a follow-on after a swap passes the swap's time, and a
    payment trace sets it from the first payment. `is_follow_on` says this
    trace follows a swap: it then keeps no wallet statement and follows no
    further swaps. The two were once one test (`seed_window is None`), which
    switched both off for every payment trace too. For a follow-on,
    `depth_offset` is the swapping wallet's hops from the reported address, so
    the follow-on's hop proximity counts from there, and `seed_amount` what the
    swaps returned: the follow-on's amounts are capped at it, because the wallet
    may have sent on money that was not the swap's. `seed_share` is the most
    of the swaps' input the traced money can have been; the pro-rata start is
    that share of `seed_amount`, while which exchange got the money is still
    read against the whole output.

    Everything the endpoint does except the case record: the endpoint gives
    the result a case id and saves it; the startup warm-up runs the demo
    addresses through this and keeps nothing, so the provider responses are
    cached without a row appearing in the case store.
    """
    chain, address = check_request(request)
    direction = request.direction

    seed = normalize_address(address)
    matcher = get_matcher(chain.key)
    risk_matcher = get_risk_matcher(chain.key)
    routers = get_router_matcher(chain.key)
    # Every trace has a wall clock (api_budget.TraceBudget): the server's default
    # unless the request asks for less, never above its maximum.
    budget = budget or current_budget() or TraceBudget.for_request(request.time_budget_seconds)
    # The budget is the case's, shared with follow-ons: this trace reports its own part.
    units_before = budget.usage()
    # The operator's ceiling wins over the request (and over the default).
    max_depth = min(request.max_depth or config.TRACE_MAX_DEPTH, config.TRACE_MAX_DEPTH_CEILING)
    trace_config = TraceConfig(
        max_depth=max_depth,
        # R5: every branch carrying a share of the funds, not the top ten.
        branch_min_share=config.TRACE_BRANCH_MIN_SHARE_PERCENT / 100 if config.TAINT_EXPANSION else None,
        max_branches_hard=config.TRACE_MAX_BRANCHES_HARD,
        # The walk stops at the case's walk deadline, shared with any follow-on.
        time_budget_seconds=max(0.001, budget.walk_remaining()),
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
            try:
                client.budget = budget  # checked before every request the client makes
            except AttributeError:
                pass
            # A provider that searches a bounded window (NodeReal) may look
            # further back for the reported address alone, never for a hop.
            if hasattr(client, "allow_deep_search"):
                client.allow_deep_search(seed)
            # On Tron, a wallet no label file names is asked about: TronScan's
            # own tag, read live, attributes it when it names an exchange.
            if chain.key == "tron":
                live = LiveTronExchanges(
                    TronScanTags(config.TRONSCAN_API_KEY, evidence=getattr(client, "evidence", None)),
                    matcher.is_exchange,
                    # ADR-0006: a tag names an exchange only for an account, never a contract.
                    is_contract=getattr(client, "is_contract", None) or (lambda a: None),
                )
                live.tags.budget = budget
            # R1: read the victim's payments from the chain first. They must be
            # incoming transfers to the reported wallet, and the walk then reads
            # that wallet only from when the first one arrived.
            intake = None
            seed_block = None
            payer_warnings: list[str] = []
            if request.payments:
                try:
                    payments = resolve_payments(
                        client, seed, request.payments, chain_key=chain.key,
                        asset=asset_symbol, limit=config.TX_INTAKE_LOOKUP_LIMIT,
                    )
                except PaymentError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                # Who paid each one, and whether it was the victim's own wallet.
                payer_warnings = review_payments(
                    payments, victim_address=request.victim_address,
                    exchange_of=matcher.lookup, router_of=routers.lookup,
                )
                intake = intake_record(payments, request.ncrp_ack, request.victim_address)
                # Read the wallet from the first payment's block, not from its
                # newest page (Etherscan) or the oldest inflow the lookup saw
                # (NodeReal).
                seed_window, seed_block = window_anchor(payments)
                anchor = getattr(client, "set_arrival", None)
                if anchor is not None and seed_block:
                    anchor(seed, seed_block)
            budget.walking = True  # the walk may spend only part of each request budget
            try:
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
                    seed_window_block=seed_block,
                )
            finally:
                budget.walking = False
            walk_stopped_by = budget.stopped_by
            if request.max_depth and request.max_depth > max_depth:
                result.warnings.append(
                    f"Depth capped at {max_depth} hops by this server; the request asked for {request.max_depth}."
                )
            if getattr(client, "confirmed_bound_applied", True) is False:
                # The head could not be read, so the newest rows were kept uncut.
                result.warnings.append(
                    "The chain's newest block could not be read, so the newest blocks may include "
                    "unconfirmed transfers that a reorganisation could still drop."
                )
            if intake is not None:
                # A payment hash that carried several transfers says so (5-2),
                # as does a payment not from the victim's own wallet (5-3).
                result.warnings.extend(leg_warnings(intake["payments"]) + payer_warnings)
            if live is not None:
                # The last hop is never checked during the walk; ask now, then
                # attribute against the file's labels plus what TronScan named.
                live.sweep(result.graph)
                file_matcher = matcher
                if live.found:
                    matcher = ExchangeMatcher({**matcher._labels, **live.found}, chain=chain.key)
                if live.warnings:
                    # A label file's entry always outranks the explorer's warning.
                    risk_matcher = RiskMatcher({**live.risk_labels(REPORTED), **risk_matcher._labels},
                                               chain=chain.key, store=risk_matcher.store)
            progress.report(stage="screening", addresses=result.graph.number_of_nodes())
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
            progress.report(stage="attributing")
            inferred = []
            if direction == OUTGOING:
                # Only a label file's wallet is a sweep destination: an inference
                # resting on an explorer tag read live would be two guesses deep.
                inferred = infer_deposit_addresses(
                    result.graph, matcher if live is None else file_matcher,
                    balance_of=getattr(client, "get_balance_native", None),
                    native_symbol=chain.native_symbol,
                    # Dust is measured in the traced asset; a wallet the risk
                    # lists name (a poisoning lookalike) is not unlabelled.
                    asset=asset_symbol, is_flagged=risk_matcher.is_flagged,
                )
            # Every provider response the trace was computed from, hashed on
            # arrival. Taken while the client is still open, after the last
            # call that could add to it (the balance reads above).
            # Pro-rata: how much of the reported funds likely reached the
            # exchange, reading what else joined them in each wallet on the path.
            prorata = None
            methods = None
            # Follow the money: each match's share of what the reported address
            # sent picks the case's exchange, not its hop count alone (one dust
            # transfer used to name any exchange, or an innocent deposit address).
            materiality, shares = _materiality(result.graph, seed, direction, matches + inferred,
                                               result.untraced, intake, seed_amount, seed_amount_basis)
            # The figure is never more than the victim reported paying, or
            # than the traced money's part of what the swaps returned (follow-on).
            cap, cap_basis = _seed_cap(intake, seed_amount, seed_amount_basis, seed_share)
            lead = ExchangeMatcher.primary_match(matches + inferred, shares)
            if lead is not None:
                materiality["primary_share"] = round(shares.get(lead.address, 0.0), 4)
                materiality["primary_reach"] = round(materiality["reach"].get(lead.address, 0.0), 6)
            if direction == OUTGOING and lead is not None and lead.address != seed:
                try:
                    lead_path = principal_path(result.graph, seed, lead.address)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    lead_path = []
                # One read of each wallet's flows in its window, shared by
                # pro-rata and R4: pro-rata needs what the wallet paid out too,
                # to net out coins it got back (W -> X -> W).
                flows = getattr(client, "get_flows_between", None)
                flows = read_once(flows) if flows else None
                prorata = estimate_prorata(result.graph, lead_path,
                                           getattr(client, "get_incoming_between", None), flows_between=flows,
                                           seed_cap=cap, cap_basis=cap_basis)
                # R4: FIFO and LIBR beside pro-rata, on the same path. Before
                # the evidence manifest below, so their reads are in it.
                if config.TRACING_METHODS and lead_path:
                    methods = compare_methods(result.graph, lead_path, flows, prorata, seed_cap=cap)
            # The reported wallet's own statement: what it received and sent in
            # this asset, whether or not anything could be followed onward.
            statement = (None if is_follow_on else
                         _wallet_statement(client, seed, window_start=seed_window if intake else None))
            # A provider that searches a block range (NodeReal) says how far
            # back it looked when it found nothing, so "sent nothing" is never
            # claimed for history the search did not reach.
            searched_since = None
            floor = (getattr(client, "searched_from", None) or {}).get(seed)
            if floor is not None and hasattr(client, "block_time"):
                searched_since = client.block_time(floor)
            deep = (getattr(client, "deep_searched", None) or {}).get(seed)
            if budget.stopped_by in ("time", "budget") and walk_stopped_by is None:
                # A read after the walk was refused: each stage keeps going without it.
                result.note_truncation(
                    f"the case's {'time limit' if budget.stopped_by == 'time' else 'request budget'} ran out "
                    "in the reads after the walk, so some later figures (swap receipts, balances, pro-rata "
                    "windows, the wallet statement) may be missing"
                )
            evidence = client.evidence.manifest() if hasattr(client, "evidence") else None
            # Whether contract-moved value was part of the data, for the
            # limitations paragraph. Only the Etherscan native path reads it.
            internal_read = bool(getattr(client, "include_internal", False)) and is_native
    except Cancelled as exc:
        raise HTTPException(status_code=409, detail="The trace was stopped by the person who started it.") from exc
    except BudgetSpent as exc:
        # The reported address itself could not be read within the budget
        # (deeper addresses just truncate the walk). Fixed sentences only.
        name = PROVIDER_NAMES.get(exc.provider, exc.provider)
        if exc.scope == "trace":
            detail = (f"The reported address could not be read within this case's {name} request budget. "
                      "Try a smaller depth.")
        elif exc.scope == "client":
            detail = (f"This connection has used its share of today's {name} allowance, so it cannot start "
                      f"live traces on {chain.name} until 00:00 UTC. Stored cases and the verified examples "
                      "still open.")
        else:
            detail = allowance_used_up(chain)
        raise HTTPException(status_code=429 if exc.scope == "client" else 503, detail=detail) from exc
    except TraceStopped as exc:
        # The reported address itself could not be read before the case's
        # time ran out (deeper addresses just truncate the walk). A fixed
        # sentence: never provider text.
        raise HTTPException(
            status_code=503,
            detail=(f"The reported address could not be read before the trace's {exc.reason} "
                    f"of {budget.walk_seconds:g} s. Try again in a few minutes."),
        ) from exc
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
    except ProviderQuotaError as exc:
        # The provider's daily or monthly allowance is spent: waiting seconds
        # will not help, and the officer should know what still works.
        raise HTTPException(
            status_code=503,
            detail=(f"The {chain.name} data provider's quota is used up for now, so live tracing on "
                    f"{chain.name} is paused until it resets. Stored cases and the verified examples still open."),
        ) from exc
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
                f"({_PROVIDER_NAMES.get(chain.provider, chain.provider)}). Try again in a minute."
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
    primary = lead  # chosen once, above, so pro-rata and the case name the same address
    if primary is not None and prorata and prorata.get("status") == "estimated" and materiality["denominator"]:
        # A follow-on's estimate counts only the traced share of the swaps'
        # output; the denominator is the whole output, so compare like with like.
        scale = seed_share if seed_share is not None and 0 < seed_share < 1 else 1.0
        reached = prorata["estimated"] / scale
        materiality["primary_reach"] = round(min(reached, materiality["denominator"]), 6)
        materiality["primary_share"] = round(min(1.0, reached / materiality["denominator"]), 4)
        materiality["reach_method"] = "prorata"
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
        materiality=materiality,
        depth_offset=depth_offset,
    )

    # Swaps into a stablecoin this chain carries are followed as their own
    # traces, before the message is written, so the message can say where the
    # money went after it changed asset.
    # This trace's own requests, before any follow-on spends from the same budget.
    provider_units = budget.usage_since(units_before)
    stopped_by = ("budget" if result.addresses_unexpanded_by_budget else
                  "time" if result.addresses_unexpanded_by_time else
                  budget.stopped_by if budget.stopped_by in ("time", "budget") else None)
    follow_ons: list[dict[str, Any]] = []
    if direction == OUTGOING and request.follow_swaps and not is_follow_on and swaps:
        follow_ons = _follow_swaps(request, chain, asset_symbol, graph, swaps, trace_config.max_depth,
                                   budget=budget, seed=seed,
                                   reported=reported_amount(intake["payments"]) if intake else None)
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
        if graph.nodes[seed].get("history_capped"):
            # The read stopped at its record limit (spam can fill it), so
            # "sent nothing" or "received nothing" is not a claim it can make.
            verb = "sent" if direction == OUTGOING else "received"
            message = (
                f"The newest records read for this address held no {asset_symbol} it {verb} with value, "
                f"and the rest of its history was not read (the read stopped at its record limit), so "
                f"Exchequer cannot say it {verb} nothing. It may have moved the money in older records, "
                "or as a different asset" + alternatives
            )
        elif direction == OUTGOING and since:
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
    elif primary is None and any(m.category == MIXER and m.is_terminal for m in risk_matches):
        # Edge case: the trail did not go cold, it was deliberately cut. Saying
        # "no exchange found" here would understate what was actually
        # discovered, which is that the funds were sent to a tumbler. A mixer
        # tag the trace went past (not a pinned pool) is not that.
        mixers = [m for m in risk_matches if m.category == MIXER and m.is_terminal]
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
        # R4, behind EXCHEQUER_TRACING_METHODS: FIFO and LIBR beside pro-rata.
        # The contract reads its figures into `estimates`.
        "tracing_methods": methods,
        "exchange_address": primary.address if primary else None,
        "exchange_label": primary.label if primary else None,
        # True when the attribution names an inferred deposit address rather
        # than a label-file wallet. The evidence is in `matches` and the
        # sentence in `inference_notes`.
        "attribution_inferred": bool(primary and primary.inferred),
        "inferred_deposits": [m.to_dict() for m in inferred],
        "inference_notes": [describe_inference(m, chain.native_symbol) for m in inferred],
        "value_received_native": (
            round(primary.value_received_native, 6) if primary else None
        ),
        "matches": [{**m.to_dict(),
                     "share": round(shares.get(m.address, 0.0), 4),
                     "reach_native": round(materiality["reach"].get(m.address, 0.0), 6),
                     "material": shares.get(m.address, 0.0) >= materiality["threshold"]}
                    for m in matches],
        # How much of what the reported address sent reached the attributed
        # exchange, and on what basis; also which exchanges received a
        # material share (more than one: a letter may be needed to each).
        "materiality": {k: v for k, v in materiality.items() if k != "reach"},
        # Sanctions / mixer screening. `risk_flags` mirrors `flags` so the
        # frontend can render both the same way; `risk_notes` are report-ready
        # sentences so neither the UI nor the report has to re-phrase them.
        "risk_matches": [m.to_dict() for m in risk_matches],
        "risk_flags": sorted({m.category for m in risk_matches}),
        "risk_notes": [m.describe(asset_symbol) for m in risk_matches],
        # The label-store build this trace screened against (None: it had
        # none), so a later report names the build that made, or missed, a flag.
        "label_store": risk_matcher.store_entry(),
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
        # transfers, transfers_total, transfers_omitted, transfers_sha256 (_appendix).
        **_appendix(_all_transfers(graph), _appendix_edges(graph, seed, direction, primary),
                    {m.address for m in matches}),
        "depth_reached": result.depth_reached,
        "max_depth": trace_config.max_depth,
        # The clock, if the caller set one, and what it cost: how long the walk
        # took and how many reached addresses it left unexpanded.
        "time_budget_seconds": request.time_budget_seconds,
        # The limit this trace actually ran under, and whether it cut the walk short.
        "time_limit_seconds": budget.walk_seconds,
        # "time" or "budget" when either cut this trace short (truncation_reasons says where).
        "stopped_by": stopped_by,
        "seconds_elapsed": result.seconds_elapsed,
        "addresses_unexpanded_by_time": result.addresses_unexpanded_by_time,
        "addresses_unexpanded_by_budget": result.addresses_unexpanded_by_budget,
        # What this trace spent per provider ({requests, units, case_limit, unit}),
        # follow-ons apart; the limit is the whole case's.
        "provider_units": provider_units,
        "addresses_expanded": result.addresses_expanded,
        # Busy wallets also read from when the funds arrived (graph_builder).
        "read_from_arrival": result.read_from_arrival,
        # What the walk did not follow, with its value (brake 2; R5).
        "untraced": result.untraced,
        "transfers_excluded_by_time": result.transfers_excluded_by_time,
        # Network requests this trace sent (provider_units), not addresses read;
        # cache hits are in the evidence manifest instead.
        "api_calls": sum(u["requests"] for u in provider_units.values()),
        "addresses_read": result.addresses_read,
        # Hash-and-timestamp of every response above; see app/evidence.py.
        "evidence": evidence,
        "truncated": result.truncated,
        "truncation_reasons": result.truncation_reasons,
        "warnings": result.warnings,
    }
    if intake is not None:
        payload["intake"] = intake
        payload["reported_amount"] = reported_amount(intake["payments"])
    # What this trace ran with, so its report can say so after a deploy (provenance.py).
    payload["provenance"] = capture_provenance(
        chain.key, follow_swaps=request.follow_swaps, max_follow_ons=MAX_FOLLOW_ONS,
        live_tags=bool(live is not None and getattr(live.tags, "enabled", False)))
    # Every result leaves here under the case contract (contracts/case_v2.py):
    # the v1 fields above, untouched, plus the v2 fields the other lanes read.
    return upgrade_to_contract(payload)


def _traced_into(flow: nx.DiGraph, seed: str, wallet: str) -> float:
    """The most of the reported wallet's money that could have reached
    `wallet` through the trace: the maximum flow, each edge's value its
    capacity. The widest single route would undercount money that split and
    joined again, and this is a ceiling."""
    if seed not in flow or wallet not in flow:
        return 0.0
    return float(nx.maximum_flow_value(flow, seed, wallet))


def _swap_groups(swaps: list[dict[str, Any]], traceable: set[str], asset_symbol: str,
                 ) -> dict[tuple[str, str], dict[str, Any]]:
    """Every read swap's traceable outputs, grouped by (wallet, asset): the
    swaps in each group, what they returned and what went into them. One
    receipt paying the same token twice is one output; a transaction seen on
    two router edges adds its input, never its output again."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for swap in swaps:
        if not swap.get("output_read"):
            continue
        got: dict[str, float] = {}
        for o in swap.get("outputs") or [{"asset": swap.get("asset_out"), "amount": swap.get("amount_out")}]:
            if o.get("asset") in traceable and o.get("asset") != asset_symbol and o.get("amount") is not None:
                got[o["asset"]] = got.get(o["asset"], 0.0) + float(o["amount"])
        paid_in, total = float(swap.get("amount_in") or 0.0), sum(got.values()) or 1.0
        for asset_out, amount in got.items():
            g = groups.setdefault((swap["sender"], asset_out), {"swaps": [], "out": 0.0, "in": 0.0, "bought": 0.0})
            g["in"] += paid_in
            # The part of this input that bought this asset (stablecoins, so
            # comparable): what ranks a decoy output below the real one.
            g["bought"] += paid_in * amount / total
            if swap.get("tx") and any(s.get("tx") == swap["tx"] for s in g["swaps"]):
                continue
            g["swaps"].append({**swap, "asset_out": asset_out, "amount_out": amount})
            g["out"] += amount
    return groups


def _follow_swaps(
    request: TraceRequest,
    chain: config.Chain,
    asset_symbol: str,
    graph: Any,
    swaps: list[dict[str, Any]],
    max_depth: int,
    budget: TraceBudget | None = None,
    seed: str | None = None,
    reported: float | None = None,
) -> list[dict[str, Any]]:
    """Trace the output asset of each swap into a stablecoin this chain carries.

    One follow-on per (wallet, output asset), at most MAX_FOLLOW_ONS, over the
    hops the original trace had left beyond the swapping wallet (at least one).
    The follow-on starts at that wallet's first swap into the asset: the time
    rule excludes anything it sent in the new asset before. It follows
    everything the wallet sent in that asset afterwards, which may include
    money that was not the swaps' output, so its amounts are capped (`cap`):
    at what all those swaps returned, and, where the traced money was only
    part of what went into them, at that share of it. The share is the most
    of the reported wallet's money (at most `reported`, the victim's payments,
    on a payment trace) that could have reached the swapping wallet, over
    what it swapped. An address-only trace's own swaps are taken whole: its
    starting figure is everything the reported wallet sent.

    Follow-ons are chosen by how much traced money went into them, not by the
    order the swaps were found, so a dust swap or a decoy output cannot take
    the place of the real one. `route` is the original asset's path from the
    reported address (`seed`) to the swapping wallet, for the letter.
    Follow-ons never follow further swaps.

    A time budget covers the whole case, not each trace: follow-ons share what
    the original trace left of it, and one that would start with less than the
    minimum budget is recorded as not traced rather than run over the limit.
    """
    groups = _swap_groups(swaps, {t.symbol for t in chain.tokens}, asset_symbol)
    flow = None
    ranked = []
    for (sender, asset_out), g in groups.items():
        if seed is None or sender == seed:
            traced = reported
        else:
            if flow is None:
                flow = nx.DiGraph()
                flow.add_edges_from((u, v, {"capacity": float(d.get("value_native") or 0.0)})
                                    for u, v, d in graph.edges(data=True))
            traced = _traced_into(flow, seed, sender)
            if reported is not None:
                traced = min(traced, reported)
        share = min(1.0, traced / g["in"]) if traced is not None and g["in"] > 0 else None
        ranked.append((g["bought"] * (share if share is not None else 1.0), sender, asset_out, g, traced, share))
    # Most traced money first; ties keep the order the swaps were found in.
    ranked.sort(key=lambda r: -r[0])

    out: list[dict[str, Any]] = []
    for _, sender, asset_out, g, traced, share in ranked[:MAX_FOLLOW_ONS]:
        group = sorted(g["swaps"], key=lambda s: s.get("timestamp") or 0)
        swap = max(group, key=lambda s: s["amount_out"])  # the swap the letter names
        returned = round(g["out"], 6)
        cap, basis = _seed_cap(None, returned, "swap_output", share)
        depth_at = (graph.nodes.get(sender) or {}).get("depth", 0)
        remaining = max(1, max_depth - depth_at)
        follow = {"swap": swap, "asset": asset_out, "address": sender, "max_depth": remaining,
                  "route": _trace_path(graph, seed, sender, OUTGOING) if seed else [],
                  # What the follow-on may state, and why (see the docstring).
                  "cap": {"amount": cap, "basis": basis, "swap_output": returned,
                          "swap_input": round(g["in"], 6),
                          "traced_in": round(traced, 6) if traced is not None else None,
                          "share": round(share, 6) if share is not None else None, "swaps": len(group)}}
        if len(group) > 1:
            follow["swaps"] = [{k: s.get(k) for k in ("tx", "timestamp", "router_label", "amount_in", "amount_out")}
                               for s in group]
        starts = [s["timestamp"] for s in group if s.get("timestamp") is not None]
        # One clock for the whole case: a follow-on uses what is left of it.
        if budget is not None and budget.walk_over():
            follow["error"] = "not traced: the case's time budget was spent before this swap could be followed"
            out.append(follow)
            continue
        if budget is not None and budget.stopped_by == "budget":
            follow["error"] = ("not traced: the case's provider request budget was spent before this swap "
                               "could be followed")
            out.append(follow)
            continue
        sub = TraceRequest(
            address=sender, chain=chain.key, asset=asset_out, max_depth=remaining,
            direction=OUTGOING, follow_swaps=False,
        )
        progress.report(stage="following_swap", follow_asset=asset_out)
        try:
            follow["result"] = run_trace(sub, seed_window=min(starts) if starts else None, budget=budget,
                                         depth_offset=depth_at, seed_amount=returned,
                                         seed_amount_basis="swap_output", is_follow_on=True, seed_share=share)
        except HTTPException as exc:
            if budget is not None and budget.cancelled:
                raise  # a stop ends the whole case, follow-ons included
            # A follow-on that fails must not cost the trace that found it.
            follow["error"] = str(exc.detail)
        except Exception:  # noqa: BLE001 -- nor may any other failure
            logger.exception("Follow-on trace of %s after a swap failed", asset_out)
            follow["error"] = ("not traced: the follow-on could not be traced because of an unexpected "
                               "error; the original trace above is complete")
        out.append(follow)
    return out
