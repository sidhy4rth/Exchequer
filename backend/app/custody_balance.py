"""Custody balance check: does each custody address still hold what the asset register says? (feature 9, part 2)

The asset register (assets.py) records how much of each asset a case holds in the
unit's custody wallet. This reads each such address's current balance on chain
through the provider client the trace engine uses for that chain (Etherscan,
NodeReal or TronGrid: their shared pacers, daily allowances and evidence log), and
compares it with the register:

    match      the chain shows exactly what the register's held rows add up to
    mismatch   it shows more or less; the result says by how much, in words
    unchecked  this run could not tell (no address on a chain read here, an asset
               not read on that chain, the provider not configured or not answering)

Which address a row is held at: the custody wallet record it is linked to
(custody.py), else its own `held_at` when that is a valid address on its chain.
Rows still held, in custody, and readable by the viewer are counted, summed per
address and asset. Decimals come from config.CHAINS (the native coin's, or the
token's), never from the provider's answer. Amounts are exact decimals.

Each result keeps the provider's evidence records (request without the key,
SHA-256 of the answer, time). A balance is a moment, not a fact about the
address: the result says when it was read. Nothing here moves money or holds a key.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Callable

import httpx
from sqlalchemy import select

from . import config, models
from .api_budget import TraceStopped
from .chain_data import ProviderNotConfiguredError, open_source
from .custody import _readable
from .etherscan_client import EtherscanClient, EtherscanError, ProviderQuotaError, normalize_address
from .nodereal_client import NoderealClient, _hex_int
from .tron_client import TronClient

MATCH, MISMATCH, UNCHECKED = "match", "mismatch", "unchecked"
MAX_READS = 10  # address-asset pairs per run: each is a live provider read inside a request
BALANCE_OF = "0x70a08231"  # balanceOf(address), the ERC-20 selector
PROVIDER_NAMES = {"etherscan": "Etherscan", "nodereal": "NodeReal", "trongrid": "TronGrid"}


class Unreadable(Exception):
    """The provider's answer was not a balance; the message says so in plain words."""


def _text(d: Decimal) -> str:
    out = format(d, "f")
    return out.rstrip("0").rstrip(".") if "." in out else out


def _chain_of(raw: str) -> config.Chain | None:
    try:
        return config.get_chain(raw) if (raw or "").strip() else None
    except config.UnknownChainError:
        return None


def _places(s: Any, viewer: Any, case_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(groups to read, rows that cannot be read): the case's held custody rows by chain, address and asset."""
    rows = s.scalars(select(models.SeizedAsset).where(
        models.SeizedAsset.case_id == case_id, models.SeizedAsset.holder == "custody",
        models.SeizedAsset.status == "held", _readable(viewer, models.SeizedAsset))
        .order_by(models.SeizedAsset.seized_on, models.SeizedAsset.created_at)).all()
    linked: dict[str, models.CustodyWallet] = {}
    for w in s.scalars(select(models.CustodyWallet).where(
            models.CustodyWallet.case_id == case_id, _readable(viewer))).all():
        for asset_id in json.loads(w.asset_ids_json or "[]"):
            linked.setdefault(asset_id, w)
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    unplaced: list[dict[str, Any]] = []
    for r in rows:
        w = linked.get(r.id)
        chain = config.CHAINS.get(w.chain) if w else _chain_of(r.chain)
        address = w.address if w else (r.held_at or "").strip()
        if chain is None or not chain.validate_address(address, checksum=False):
            unplaced.append({"asset": r.asset, "register_amount": r.amount, "asset_ids": [r.id], "status": UNCHECKED,
                             "reason": "This row names no custody address on a chain Exchequer reads: link it to "
                                       "a custody wallet, or record the wallet's address and chain on the row."})
            continue
        key = (chain.key, normalize_address(address), r.asset.strip().upper())
        g = groups.setdefault(key, {"chain": chain.key, "chain_name": chain.name, "address": address,
                                    "asset": r.asset.strip().upper(), "total": Decimal(0), "asset_ids": [],
                                    "wallet_id": w.id if w else None})
        g["wallet_id"] = g["wallet_id"] or (w.id if w else None)
        g["total"] += Decimal(r.amount)
        g["asset_ids"].append(r.id)
    return list(groups.values()), unplaced


def _read_raw(client: Any, chain: config.Chain, address: str, token: config.Token | None) -> tuple[int, str]:
    """(balance in the asset's smallest unit, a note on how it was read) through the client's own request path."""
    if isinstance(client, EtherscanClient):
        params = {"module": "account", "action": "balance", "address": normalize_address(address), "tag": "latest"}
        if token is not None:
            params = {"module": "account", "action": "tokenbalance", "contractaddress": token.address,
                      "address": normalize_address(address), "tag": "latest"}
        result = client._request(params)
        if not isinstance(result, str) or not result.isdigit():
            raise Unreadable("Etherscan's answer was not a whole-number balance.")
        return int(result), "latest block"
    if isinstance(client, NoderealClient):
        block = hex(client.head_block())  # a fixed block: the answer is history, and says which block
        if token is None:
            result = client._rpc("eth_getBalance", [normalize_address(address), block])
        else:
            data = BALANCE_OF + normalize_address(address)[2:].rjust(64, "0")
            result = client._rpc("eth_call", [{"to": token.address, "data": data}, block])
        try:
            return _hex_int(result), f"block {int(block, 16)}"
        except EtherscanError as exc:
            raise Unreadable("NodeReal's answer was not a balance.") from exc
    if isinstance(client, TronClient):
        body = client._get(f"/v1/accounts/{address}", {})
        data = body.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise Unreadable("TronGrid has no account record for this address (never activated, or not answering).")
        account = data[0]
        if token is None:
            raw = account.get("balance", 0)  # TronGrid leaves `balance` out of an account holding no TRX
        else:
            raw = next((entry[token.address] for entry in account.get("trc20") or []
                        if isinstance(entry, dict) and token.address in entry), "0")
        try:
            return int(str(raw)), "latest block"
        except ValueError as exc:
            raise Unreadable("TronGrid's answer was not a whole-number balance.") from exc
    raise Unreadable("No balance reader for this chain's provider.")


def _why_not(exc: Exception, chain: config.Chain) -> str:
    provider = PROVIDER_NAMES.get(chain.provider, chain.provider)
    if isinstance(exc, ProviderNotConfiguredError):
        return f"{chain.name} has no data provider configured on this deployment."
    if isinstance(exc, (ProviderQuotaError, TraceStopped)):
        return f"Today's allowance at {provider} is spent; try again tomorrow."
    if isinstance(exc, Unreadable):
        return str(exc)
    return f"{provider} did not give a usable answer; try again later."


def compare(register: Decimal, on_chain: Decimal, asset: str) -> tuple[str, str]:
    """(status, the sentence a reader sees) for one address and asset."""
    if on_chain == register:
        return MATCH, f"The chain shows {_text(on_chain)} {asset}, as the register records."
    gap = _text(abs(on_chain - register))
    if on_chain < register:
        return MISMATCH, (f"Mismatch: the chain shows {_text(on_chain)} {asset}, {gap} {asset} less than the "
                          f"{_text(register)} {asset} the register records as held here.")
    return MISMATCH, (f"Mismatch: the chain shows {_text(on_chain)} {asset}, {gap} {asset} more than the "
                      f"{_text(register)} {asset} this case's register records as held here (another case's "
                      "money in the same wallet, or a transfer in not yet recorded, would show like this).")


def _check_one(g: dict[str, Any], opener: Callable[..., Any]) -> dict[str, Any]:
    chain = config.CHAINS[g["chain"]]
    out = {k: g[k] for k in ("chain", "chain_name", "address", "asset", "asset_ids", "wallet_id")}
    out.update(register_amount=_text(g["total"]), chain_amount=None, difference=None, provider=chain.provider,
               read_at=models.utc_now_iso(), evidence=[])
    token = None if g["asset"] == chain.native_symbol.upper() else chain.find_token(g["asset"])
    if token is None and g["asset"] != chain.native_symbol.upper():
        out.update(status=UNCHECKED, reason=f"{g['asset']} is not an asset Exchequer reads on {chain.name}.")
        return out
    decimals = token.decimals if token is not None else chain.native_decimals
    client = None
    try:
        client = opener(chain)
        client.max_retries = 1  # inside a request: one retry, not a trace's four
        raw, at = _read_raw(client, chain, g["address"], token)
    except (EtherscanError, TraceStopped, Unreadable, httpx.HTTPError) as exc:
        out.update(status=UNCHECKED, reason=_why_not(exc, chain))
    else:
        on_chain = Decimal(raw).scaleb(-decimals)
        status, reason = compare(g["total"], on_chain, g["asset"])
        out.update(status=status, reason=reason, chain_amount=_text(on_chain), read_from=at,
                   difference=_text(on_chain - g["total"]))
    finally:
        if client is not None:
            out["evidence"] = [r.to_dict() for r in client.evidence.records]
            client.close()
    return out


def read_all(viewer: Any, case_id: str, opener: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Read every custody address of the case and compare it with the register. `opener(chain)` gives
    the chain's provider client (chain_data.open_source unless a test passes its own)."""
    opener = opener or open_source
    with models.session() as s:
        if s.scalar(select(models.Case.id).where(models.Case.id == case_id)) is None:
            raise LookupError(case_id)
        groups, unplaced = _places(s, viewer, case_id)
    results = [_check_one(g, opener) for g in groups[:MAX_READS]]
    for g in groups[MAX_READS:]:
        results.append({**{k: g[k] for k in ("chain", "chain_name", "address", "asset", "asset_ids", "wallet_id")},
                        "register_amount": _text(g["total"]), "status": UNCHECKED, "evidence": [],
                        "reason": f"Not read: one check reads at most {MAX_READS} addresses and assets."})
    return results + unplaced


def counts(results: list[dict[str, Any]]) -> dict[str, int]:
    return {k: sum(1 for x in results if x.get("status") == k) for k in (MATCH, MISMATCH, UNCHECKED)}


# -- each run is kept -------------------------------------------------------------------------------
def run(viewer: Any, case_id: str, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    """read_all, stored as one run with its evidence, and returned as summary() gives it."""
    results = read_all(viewer, case_id, opener)
    with models.session() as s:
        r = models.CustodyBalanceCheck(
            id=str(uuid.uuid4()), owner_hash=viewer.owner_hash or "", case_id=case_id,
            officer_id=getattr(viewer, "officer_id", None), unit_id=getattr(viewer, "unit_id", None),
            checked_at=models.utc_now_iso(), checked_by=getattr(viewer, "id", None) or "unknown",
            results_json=json.dumps(results))
        s.add(r)
        s.commit()
        s.refresh(r)
        return summary(r)


def summary(r: models.CustodyBalanceCheck) -> dict[str, Any]:
    results = json.loads(r.results_json or "[]")
    return {"check_id": r.id, "case_id": r.case_id, "checked_at": r.checked_at, "checked_by": r.checked_by,
            "results": results, "counts": counts(results)}


def latest(viewer: Any, case_id: str) -> dict[str, Any] | None:
    """The newest run of this case the viewer may read, or None."""
    if getattr(viewer, "owner_hash", None) is None and getattr(viewer, "unit_id", None) is None:
        return None
    with models.session() as s:
        r = s.scalars(select(models.CustodyBalanceCheck).where(
            models.CustodyBalanceCheck.case_id == case_id, _readable(viewer, models.CustodyBalanceCheck))
            .order_by(models.CustodyBalanceCheck.checked_at.desc())).first()
        return summary(r) if r is not None else None
