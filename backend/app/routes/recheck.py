"""A case's cited transfers, reread from a second provider (second_provider.py).

    POST /trace/{case_id}/recheck   reread them now; the result is kept with the case
    GET  /trace/{case_id}/recheck   the last recheck ("checked_at": null before the first)

POST is gated like POST /trace: the demo code (access.GUARDED), an hourly limit
per connection and for the whole site, the provider's daily allowance (the
site's and this connection's share), one recheck running per connection and
config.RECHECKS_RUNNING for the site, and an audit record. Only the browser
that traced a case may recheck it. A recorded demo (id "demo-<n>",
routes/demos.py) and a public demo case belong to nobody: anyone may recheck
one, and the result is returned, never kept, so no visitor can change what the
next one sees. A recheck that got no answer at all (every read failed) is
returned and not kept either, so an outage never replaces the last good one.
GET is open to whoever holds the case's link, like the case itself: it shows
hashes the case already lists.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import audit, case_privacy, case_refs, config, models, ownership, rate_limit, second_provider
from ..auth import CurrentUser
from . import demos

logger = logging.getLogger(__name__)
router = APIRouter()

DEMO_ID = re.compile(r"^demo-(\d{1,3})$")
# The connections with a recheck running now (one each at most).
_running: set[str] = set()
_running_lock = threading.Lock()


def take_slot(client: str) -> str | None:
    """Take a running slot for `client`, or say why not; give it back with release_slot."""
    with _running_lock:
        if client in _running:
            return "A recheck from this connection is still running. Wait for it to finish."
        if len(_running) >= config.RECHECKS_RUNNING > 0:
            return f"{config.RECHECKS_RUNNING} rechecks are already running. Try again in a minute."
        _running.add(client)
    return None


def release_slot(client: str) -> None:
    with _running_lock:
        _running.discard(client)


def _target(case_id: str, owner: str | None) -> tuple[dict[str, Any], bool]:
    """(the result to recheck, whether the recheck is kept with it)."""
    demo = DEMO_ID.match(case_id)
    if demo:
        row = demos._recordings().get(int(demo.group(1)))
        if row is None:
            raise HTTPException(status_code=404, detail=f"No recording for demo {demo.group(1)}")
        return row["result"], False
    case = models.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    if ownership.is_public(case.owner_hash, case.address):
        return case.result, False
    if not case_privacy.is_owner(case.owner_hash, owner):
        raise HTTPException(status_code=403, detail="Only the browser that traced this case can recheck it.")
    return case.result, True


class RecheckRequest(BaseModel):
    # Required of a signed-in officer when the case was traced under none.
    case_ref: case_refs.CaseRef = None


@router.post("/trace/{case_id}/recheck")
def recheck(case_id: str, user: CurrentUser, http: Request, sent: RecheckRequest | None = None) -> dict[str, Any]:
    """Reread the transfers the case cites on its route to the exchange, at most
    second_provider.RECHECK_MAX_TRANSFERS, and say of each whether the second
    provider matches, differs, does not have it, or could not be read. A
    signed-in officer's recheck runs under the case's reference, or one sent."""
    result, keep = _target(case_id, user.owner_hash)
    # The case's own reference only when this officer reads it in full: a
    # public case another unit traced is rechecked under the officer's own.
    given = sent.case_ref if sent else None
    known = None if user.demo or given or DEMO_ID.match(case_id) else case_refs.known(models.get_case(case_id), user)
    ref = case_refs.required(user, given or known, "recheck")
    chain_key, cited = second_provider.cited_transfers(result)
    if not cited:
        raise HTTPException(status_code=400, detail="This case cites no transfers on a route to an exchange, "
                                                    "so there is nothing to recheck.")
    if chain_key not in second_provider.PROVIDERS:
        chain = config.CHAINS[chain_key].name if chain_key in config.CHAINS else "another chain"
        raise HTTPException(status_code=400, detail=f"A second-provider recheck covers Ethereum and Tron cases; "
                                                    f"this one is on {chain}.")
    if not second_provider.rereadable(chain_key, cited):
        raise HTTPException(status_code=400, detail="None of the transfers this case cites can be reread yet: "
                                                    "native TRX and transfers moved by a contract call are not.")
    client = rate_limit.client_ip(http.headers, http.client.host if http.client else None)
    spent = second_provider.allowance_spent(chain_key, client)
    if spent is not None:
        wait, who = spent
        whose = "This site has used" if who == "site" else "This connection has used its share of"
        name = second_provider.PROVIDERS[chain_key][1]
        raise HTTPException(status_code=503, headers={"Retry-After": str(wait)},
                            detail=f"{whose} today's {name} allowance. Try again after 00:00 UTC.")
    busy = take_slot(client)
    if busy is not None:
        raise HTTPException(status_code=429, headers={"Retry-After": "30"}, detail=busy)
    try:
        officer = case_refs.spender(user, "recheck")
        refused = rate_limit.charge(rate_limit.rechecks, rate_limit.rechecks_total, client, officer=officer)
        if refused is not None:
            case_refs.refused(officer, refused)
            wait, who = refused
            started = (f"This site has run {config.RECHECKS_PER_HOUR_TOTAL} rechecks" if who == "site"
                       else f"This connection has run {config.RECHECKS_PER_HOUR_PER_CLIENT} rechecks")
            raise HTTPException(status_code=429, headers={"Retry-After": str(int(wait))},
                                detail=f"{started} in the last hour. Try again in {int(wait // 60) + 1} min.")
        rechecked = second_provider.recheck(result, client)
    finally:
        release_slot(client)

    demo = DEMO_ID.match(case_id)
    body = {"case_id": None if demo else case_id, **rechecked}
    if demo:
        body["recorded_demo"] = int(demo.group(1))
    saved = False
    if keep and body["counts"]["error"] < body["checked"]:  # something answered
        try:
            saved = models.save_recheck(case_id, body)
        except Exception:  # noqa: BLE001 -- the answer is still shown; only keeping it failed
            logger.exception("Could not keep the recheck of case %s", case_id)
    audit.record("case.recheck", case_id=None if demo else case_id,
                 detail={"chain": chain_key, "checked": body["checked"], **body["counts"], "saved": saved,
                         **({"case_ref": case_refs.mask(ref)} if ref else {})})
    return {**body, "saved": saved}


@router.get("/trace/{case_id}/recheck")
def last_recheck(case_id: str) -> dict[str, Any]:
    """The case's last recheck as POST returned it, or "checked_at": null when
    none is kept (a recorded demo's never is)."""
    if DEMO_ID.match(case_id):
        return {"case_id": None, "checked_at": None, "transfers": []}
    found, kept = models.recheck_for(case_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"No case with id {case_id}")
    audit.record("case.recheck_read", case_id=case_id)
    return kept or {"case_id": case_id, "checked_at": None, "transfers": []}
