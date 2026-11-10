"""What each citizen function does (citizen/api/<name>.py binds one each)."""
from __future__ import annotations

import re

from . import chain, codes, complaint, db, limits, web

COOKIE = "__Host-citizen"
WRONG = "That NCRP number and tracking code do not match. Check both and try again."
COULD_NOT_CHECK = "We could not check this payment right now. Please try again later."
FULL = ("This NCRP number already has as many complaints here as we can take. Call 1930 or add to your "
        "complaint on cybercrime.gov.in.")


def _cookie(token: str, max_age: int) -> str:
    return f"{COOKIE}={token}; Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=Strict"


def _signed_in(conn: db.DB, req: web.Request) -> str:
    """The complaint this request's session may read, or Refused 401."""
    token = req.cookie(COOKIE)
    row = token and conn.one("SELECT complaint_id, expires_at FROM citizen_sessions WHERE token_hash = ?",
                             codes.token_hash(token))
    if not row or row["expires_at"] <= web.now():
        raise web.Refused(401, "Please sign in again.")
    return row["complaint_id"]


def complaints(req: web.Request) -> web.Response:
    body = web.json_body(req, {"ncrp", "payments", *complaint.TEXT})
    ncrp, details, payments = complaint.read(body)
    with db.connect() as conn:  # a refused try rolls back: it is not counted
        limits.allow(conn, "complaint-client", web.client_ip(req))
        limits.allow(conn, "complaint-ncrp", ncrp)
        if conn.one("SELECT COUNT(*) AS n FROM tracking_codes WHERE ncrp = ?", ncrp)["n"] >= limits.CODES_PER_NCRP:
            raise web.Refused(409, FULL)
    with db.connect() as conn:
        return web.Response(201, complaint.store(conn, ncrp, details, payments))


def session(req: web.Request) -> web.Response:
    body = web.json_body(req, {"ncrp", "code"})
    if not isinstance(body.get("code"), str) or not body["code"].strip():
        raise web.Refused(400, "Give the tracking code you were shown when you sent your complaint.")
    ncrp = complaint.ncrp_number(body.get("ncrp"))
    client = web.client_ip(req)
    keys = {"signin-ncrp": web.keyed("signin-ncrp", ncrp), "signin-client": web.keyed("signin-client", client)}
    with db.connect() as conn:
        limits.allow(conn, "signin-client-all", client)
        wait = limits.signin_wait(conn, keys)
    if wait > 0:
        raise web.Refused(429, "Too many wrong tries. Please wait a little and try again.", retry_after=wait)
    with db.connect() as conn:
        rows = conn.all("SELECT complaint_id, salt, code_hash FROM tracking_codes WHERE ncrp = ? "
                        "ORDER BY created_at, complaint_id", ncrp)
        # Every code is checked, with no early stop, and padded to the same count.
        matched = [r["complaint_id"] for r in rows if codes.verify(body["code"], r["salt"], r["code_hash"])]
        for _ in range(limits.CODES_PER_NCRP - len(rows)):
            codes.waste_time()
        found = matched[0] if matched else None
        if not found:
            limits.signin_failed(conn, keys)
        else:
            limits.signin_cleared(conn, "signin-ncrp", keys["signin-ncrp"])
            token = codes.new_token()
            conn.run("INSERT INTO citizen_sessions (token_hash, complaint_id, created_at, expires_at) "
                     "VALUES (?, ?, ?, ?)", codes.token_hash(token), found, complaint._stamp(),
                     web.now() + limits.SESSION_SECONDS)
    if not found:
        raise web.Refused(401, WRONG)
    return web.Response(200, {"signed_in": True}, cookies=[_cookie(token, limits.SESSION_SECONDS)])


def my_case(req: web.Request) -> web.Response:
    with db.connect() as conn:
        return web.Response(200, complaint.view(conn, _signed_in(conn, req)))


def messages(req: web.Request) -> web.Response:
    body = web.json_body(req, {"body"})
    with db.connect() as conn:
        cid = _signed_in(conn, req)
        limits.allow(conn, "message-client", web.client_ip(req))
        limits.allow(conn, "message-case", cid)
    with db.connect() as conn:
        complaint.add_message(conn, cid, body.get("body"))
    return web.Response(201, {"sent": True})


def logout(req: web.Request) -> web.Response:
    token = req.cookie(COOKIE)
    if token:
        with db.connect() as conn:
            conn.run("UPDATE citizen_sessions SET expires_at = 0 WHERE token_hash = ?", codes.token_hash(token))
    return web.Response(200, {"signed_in": False}, cookies=[_cookie("", 0)])


def payment(req: web.Request) -> web.Response:
    args = req.args()
    network, digest = args.get("network", ""), args.get("hash", "").strip().lower()
    if network not in chain.NETWORKS:
        raise web.Refused(400, "Choose one of the networks listed.")
    if network == "tron":
        digest = digest.removeprefix("0x")
    if not re.fullmatch(r"(0x)?[0-9a-f]{64}", digest):
        raise web.Refused(400, "A transaction hash has 64 characters, 0 to 9 and a to f.")
    with db.connect() as conn:
        limits.allow(conn, "payment-client", web.client_ip(req))
    try:
        return web.Response(200, {"payment": chain.lookup(network, digest)})
    except chain.NotFound:
        raise web.Refused(404, "No payment with this hash was found on that network. Check the hash "
                               "and the network.") from None
    except chain.Unreadable:
        raise web.Refused(422, "This transaction is not a payment we can read here. Give its hash in "
                               "your complaint as it is.") from None
    except chain.CouldNotCheck:
        raise web.Refused(503, COULD_NOT_CHECK) from None
