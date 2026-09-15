"""TraceChain FastAPI application.

Endpoints:
    POST /trace                     trace a reported address
    GET  /trace/{case_id}           retrieve a stored case
    GET  /trace/{case_id}/report    exportable report (json or text)
    GET  /cases                     history of past traces
    GET  /exchanges                 what the label database covers
    GET  /health                    liveness + configuration check
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import api_budget, chain_data, config, models
from .chain_data import (
    ProviderNotConfiguredError,
    UnknownAssetError,
    open_source,
    provider_status,
)
from .etherscan_client import (
    EtherscanConfigError,
    EtherscanError,
    EtherscanRateLimitError,
    is_valid_address,
    normalize_address,
)
from .exchange_matcher import ExchangeMatcher, get_matcher
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
from .report import build_report, render_text_report
from .risk_matcher import MIXER, SANCTIONED, get_risk_matcher
from .scoring import principal_path, score_case

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    models.init_db()
    for key, chain in config.CHAINS.items():
        matcher = get_matcher(key)
        if not len(matcher):
            logger.warning(
                "No exchange labels for %s -- traces on that chain will graph "
                "but never attribute",
                chain.name,
            )
    for key, chain in config.CHAINS.items():
        risk = get_risk_matcher(key)
        if len(risk):
            counts = risk.counts_by_category()
            logger.info(
                "%s: screening against %d sanctioned and %d mixer addresses",
                chain.name, counts[SANCTIONED], counts[MIXER],
            )
        else:
            logger.warning(
                "No risk labels for %s -- traces on that chain will not be "
                "screened against sanctions or mixer lists",
                chain.name,
            )
    for key, status in provider_status().items():
        if status["ready"]:
            logger.info("%s: ready via %s", status["name"], status["provider"])
        else:
            logger.warning("%s unavailable: %s", status["name"], status["detail"])
    yield


app = FastAPI(
    title="TraceChain",
    description=(
        "Traces cryptocurrency fraud from a victim-reported wallet address to "
        "the exchange it was cashed out through."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# The React dev server runs on a different origin during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        steps.append(step)
    return steps


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
@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe, plus the configuration facts that break demos."""
    chains = provider_status()
    for key, status in chains.items():
        status["exchange_labels"] = len(get_matcher(key))
        status["risk_labels"] = get_risk_matcher(key).counts_by_category()
    return {
        "status": "ok",
        "etherscan_key_configured": bool(config.ETHERSCAN_API_KEY),
        "default_chain": config.DEFAULT_CHAIN.key,
        "chain_id": config.DEFAULT_CHAIN.chain_id,
        "max_depth": config.TRACE_MAX_DEPTH,
        # Kept for the existing frontend status line: labels on the default chain.
        "exchange_labels_loaded": len(get_matcher()),
        "risk_labels_loaded": len(get_risk_matcher()),
        "chains": chains,
        # Why a trace was slow. On the free tiers the provider, not the
        # traversal, is what costs the seconds: a high `rate_limit_penalties`
        # means the key is being refused and every refusal costs a backoff,
        # while a high cache `hit_rate` means repeat work is already free.
        "api_budget": api_budget.budget_stats(),
    }


@app.get("/exchanges")
def exchanges(chain: str | None = Query(None, description="ethereum or bsc")) -> dict[str, Any]:
    """What the attribution database covers.

    Exposed so a user can see immediately whether a null attribution means
    "the funds went nowhere known" or "we do not have labels for that exchange".
    """
    try:
        selected = config.get_chain(chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    matcher = get_matcher(selected.key)
    return {
        "chain": selected.key,
        "chain_name": selected.name,
        "count": len(matcher),
        "exchanges": matcher.exchanges,
    }


@app.get("/risk-labels")
def risk_labels(chain: str | None = Query(None, description="ethereum, bsc or tron")) -> dict[str, Any]:
    """What the sanctions and mixer screening covers.

    The counterpart to /exchanges, and exposed for the same reason: without it
    a trace reporting no sanctions hit is ambiguous between "nothing in this
    trace is listed" and "this chain has no risk labels loaded at all". Those
    two answers are very different and an investigator has to be able to tell
    them apart.
    """
    try:
        selected = config.get_chain(chain)
    except config.UnknownChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    matcher = get_risk_matcher(selected.key)
    return {
        "chain": selected.key,
        "chain_name": selected.name,
        "count": len(matcher),
        "counts_by_category": matcher.counts_by_category(),
        "entities": matcher.entities,
        "screened": len(matcher) > 0,
    }


@app.post("/trace")
def trace(request: TraceRequest) -> dict[str, Any]:
    """Trace funds to or from a reported address.

    Outgoing answers "where did the victim's money go"; incoming answers "who
    sent money to this address", which on a scammer's wallet enumerates the
    other people who paid it.
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
    trace_config = TraceConfig(
        max_depth=request.max_depth or config.TRACE_MAX_DEPTH,
    )

    # Which asset this trace follows. Everything downstream -- edge values,
    # pattern thresholds, the confidence score, the report -- is denominated in
    # this one asset.
    asset_symbol = (request.asset or chain.native_symbol).strip().upper()
    token = chain.find_token(asset_symbol)
    is_native = token is None

    try:
        with open_source(chain, asset_symbol) as client:
            result = build_trace_graph(
                seed,
                client,
                cfg=trace_config,
                # Two quite different reasons to stop. An exchange is where the
                # trail *ends*: the funds arrived, and those wallets have
                # millions of unrelated transactions. A mixer is where the trail
                # *breaks*: its payouts come from a commingled pool, so
                # expanding through one would invent a path the transactions do
                # not support.
                is_terminal=lambda a: matcher.is_exchange(a) or risk_matcher.is_terminal(a),
                direction=direction,
            )
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
        # Edge case: any other upstream failure.
        raise HTTPException(
            status_code=502, detail=f"Could not reach the blockchain data provider: {exc}"
        ) from exc
    except InvalidAddressError as exc:  # defensive; validated above
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidDirectionError as exc:  # defensive; the request model validates it
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    graph = result.graph

    # Attribution, patterns, score.
    matches = matcher.annotate(graph, direction)
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
    )

    # Edge case: the address has never sent anything. Not an error -- a finding.
    message: str | None = None
    if result.edge_count == 0:
        others = [chain.native_symbol] + [t.symbol for t in chain.tokens]
        others = [a for a in others if a != asset_symbol]
        alternatives = f" — try {' or '.join(others)}." if others else "."
        if direction == OUTGOING:
            message = (
                f"This address sent no {asset_symbol} with value, so there is "
                f"nothing to trace in {asset_symbol}. It may have only received "
                "funds, or the money may have moved as a different asset"
                + alternatives
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
            "them would manufacture a trail. Use of a sanctioned mixer is itself "
            "a substantive finding and is grounds for escalation."
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

    case_id = models.new_case_id()
    created_at = models.utc_now_iso()

    payload: dict[str, Any] = {
        # -- the documented API contract --
        "case_id": case_id,
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
        "created_at": created_at,
        "message": message,
        "exchange_address": primary.address if primary else None,
        "exchange_label": primary.label if primary else None,
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
        "confidence_detail": confidence.to_dict(),
        "trace_path": (
            _trace_path(graph, seed, primary.address, direction) if primary else []
        ),
        # Only populated on a reverse trace: the seed has no inbound edges when
        # the walk ran outward.
        "direct_senders": _direct_senders(graph, seed),
        "depth_reached": result.depth_reached,
        "addresses_expanded": result.addresses_expanded,
        "transfers_excluded_by_time": result.transfers_excluded_by_time,
        "api_calls": result.api_calls,
        "truncated": result.truncated,
        "truncation_reasons": result.truncation_reasons,
        "warnings": result.warnings,
    }

    try:
        models.save_case(case_id, seed, payload, created_at=created_at)
    except Exception as exc:  # storage must never lose a completed trace
        logger.exception("Failed to persist case %s", case_id)
        payload.setdefault("warnings", []).append(
            f"Result could not be saved to the case database: {exc}"
        )

    return payload


@app.get("/trace/{case_id}")
def get_trace(case_id: str) -> dict[str, Any]:
    """Retrieve a previously traced case."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    return case.result


@app.get("/trace/{case_id}/report")
def get_report(
    case_id: str,
    format: str = Query("json", pattern="^(json|text)$", description="json or text"),
):
    """Exportable summary suitable for a law-enforcement handoff."""
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")

    report = build_report(case)
    if format == "text":
        return PlainTextResponse(
            render_text_report(report),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="tracechain-{case_id[:8]}.txt"'
                )
            },
        )
    return report


@app.get("/cases")
def cases(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """History of past traces, most recent first."""
    records = models.list_cases(limit=limit)
    return {"count": len(records), "cases": [c.summary() for c in records]}


# ---------------------------------------------------------------------------
# Static frontend
#
# In development the Vite dev server serves the UI and proxies /api here. In
# the deployed image there is no Vite: the built bundle is copied in and served
# by this app, so the UI and the API share one origin. That removes CORS, the
# second deployment, and any need for the frontend to know a backend URL.
#
# This block is registered last on purpose. FastAPI matches routes in
# definition order, so /health, /trace and the rest are already claimed before
# the catch-all below sees a request.
# ---------------------------------------------------------------------------
FRONTEND_DIR = config.BACKEND_DIR.parent / "frontend" / "dist"

if FRONTEND_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the single-page app for any path the API did not claim.

        The UI routes on the client (/trace/0x…, /case/<id>), so a deep link
        opened directly or reloaded must still return index.html rather than a
        404 -- the router then reads the URL and renders the right screen.
        """
        # A real file (favicon, manifest) is served as itself.
        candidate = (FRONTEND_DIR / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        # The shell must never be cached: a stale index.html keeps pointing at
        # asset hashes from a previous build, and the old bundle then calls the
        # wrong API base and reports the backend as unreachable.
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    logger.info("Serving frontend from %s", FRONTEND_DIR)
else:
    logger.info("No built frontend at %s -- API only", FRONTEND_DIR)
