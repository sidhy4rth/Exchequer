"""A complaint: the pack's text fields and payments, checked and capped the
way the pack's form checks them (citizen/src/pages/Pack.jsx, with
checkHash in citizen/src/hash.js), and what a signed-in citizen may read
back of it.

A citizen sees only what they sent, a coarse status and the messages. Never
where the money went, labels, flags, other complaints or anything officers
note: wallet_match in particular is for officers only.
"""
from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
import uuid
from datetime import datetime, timezone

from . import codes, web
from .db import DB

TEXT = {"name": 100, "mobile": 20, "started": 40, "app": 120, "link": 300, "contacts": 600, "upi": 600,
        "story": 4000}
PAY = {"hash": 300, "amount": 32, "token": 24, "network": 40, "paidAt": 40, "wallet": 100}
MULTILINE = {"contacts", "upi", "story"}
MAX_PAYMENTS = 20
OTHER = "Another network"
NETWORKS = ("Tron (TRC20)", "Ethereum (ERC20)", "BNB Smart Chain (BEP20)", "Polygon", "Arbitrum", OTHER)
HASH = re.compile(r"^(0x)?[0-9a-f]{64}$", re.I)
# One hash with words or a link around it, as in "TxID: ..." (hash.js INSIDE).
INSIDE = re.compile(r"(?:^|[^0-9a-f])((?:0x)?[0-9a-f]{64})(?![0-9a-f])", re.I)
KEPT = 100  # the longest hash or wallet stored, as typed on another network
WALLET = re.compile(r"^(T[1-9A-HJ-NP-Za-km-z]{33}|0x[0-9a-f]{40})$", re.I)
NCRP = re.compile(r"^[A-Z0-9]{8,20}$")
STATUS = {"received": "Received", "with_cell": "With a cyber cell", "investigating": "Under investigation",
          "closed": "Closed"}
MESSAGE_CAP = 2000


def plain(value, cap: int, field: str, multiline: bool = False) -> str:
    """A string with control and direction marks taken out, trimmed, at most `cap` long."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise web.Refused(400, f"{field} must be text.")
    keep = "\n" if multiline else ""
    text = "".join(c for c in value if c in keep or unicodedata.category(c)[0] != "C").strip()
    if len(text) > cap:
        raise web.Refused(400, f"{field} is too long: at most {cap} characters.")
    return text


def ncrp_number(value) -> str:
    text = re.sub(r"[\s-]", "", value).upper() if isinstance(value, str) else ""
    if not NCRP.fullmatch(text):
        raise web.Refused(400, "Give the NCRP acknowledgement number from cybercrime.gov.in "
                               "(8 to 20 letters and digits).")
    return text


def tx_hash(raw: str) -> str | None:
    """The hash checkHash (citizen/src/hash.js) reads in `raw`, lower case:
    as typed, split across lines, or the one 64-character run in words or a
    link. None when there is no single hash in it."""
    text = re.sub(r"\s", "", raw)
    if re.fullmatch(r"(0x)?[0-9a-f]*", text, re.I):
        return text.lower() if HASH.fullmatch(text) else None
    runs = {m.lower() for m in INSIDE.findall(raw)} or {m.lower() for m in INSIDE.findall(text)}
    return runs.pop() if len(runs) == 1 else None


def _payment(raw, n: int) -> dict | None:
    if not isinstance(raw, dict) or set(raw) - set(PAY):
        raise web.Refused(400, f"Payment {n} could not be read. Only text details are sent.")
    p = {k: plain(raw.get(k), cap, f"Payment {n} {k}") for k, cap in PAY.items()}
    if not any(p.values()):
        return None
    if p["network"] and p["network"] not in NETWORKS:
        raise web.Refused(400, f"Payment {n}: choose a network from the list.")
    amount = re.sub(r"[,\s]", "", p["amount"])
    if amount and not (re.fullmatch(r"\d+\.?\d*|\.\d+", amount) and float(amount) > 0):
        raise web.Refused(400, f"Payment {n}: write the amount as a number.")
    p["amount"] = amount
    elsewhere = p["network"] == OTHER
    p["wallet"] = re.sub(r"\s", "", p["wallet"])  # spaces a copy carries along, as the form ignores them
    if WALLET.fullmatch(re.sub(r"\s", "", p["hash"])):
        raise web.Refused(400, f"Payment {n}: that is a wallet address, not a transaction hash.")
    if elsewhere:
        p["hash"] = re.sub(r"\s", "", p["hash"])
    elif p["hash"]:
        p["hash"] = tx_hash(p["hash"]) or ""
        if not p["hash"]:
            raise web.Refused(400, f"Payment {n}: a transaction hash has 64 characters, 0 to 9 and a to f.")
    if p["wallet"] and not (WALLET.fullmatch(p["wallet"]) or elsewhere):
        raise web.Refused(400, f"Payment {n}: that does not look like a wallet address.")
    if p["wallet"].lower().startswith("0x") and not elsewhere:
        p["wallet"] = p["wallet"].lower()
    for k in ("hash", "wallet"):
        if len(p[k]) > KEPT:
            raise web.Refused(400, f"Payment {n} {k} is too long: at most {KEPT} characters.")
    return p


def read(body: dict) -> tuple[str, dict, list[dict]]:
    """(NCRP number, text fields, payments), or Refused."""
    ncrp = ncrp_number(body.get("ncrp"))
    details = {k: plain(body.get(k), cap, k, k in MULTILINE) for k, cap in TEXT.items()}
    if details["mobile"] and not re.fullmatch(r"(?:\+?91|0)?[6-9]\d{9}", re.sub(r"[\s-]", "", details["mobile"])):
        raise web.Refused(400, "Give a 10-digit mobile number, or leave it empty.")
    raw = body.get("payments") or []
    if not isinstance(raw, list) or len(raw) > MAX_PAYMENTS:
        raise web.Refused(400, f"Send at most {MAX_PAYMENTS} payments.")
    payments = [p for p in (_payment(r, i + 1) for i, r in enumerate(raw)) if p]
    return ncrp, details, payments


def ordered_id() -> str:
    """Sorts in the order written, so payments and messages read back in order."""
    return f"{time.time_ns():020d}{secrets.token_hex(8)}"


def _stamp() -> str:
    return datetime.fromtimestamp(web.now(), tz=timezone.utc).isoformat(timespec="seconds")


def store(db: DB, ncrp: str, details: dict, payments: list[dict]) -> dict:
    """Saves the complaint; {reference, tracking_code}, the code's only showing."""
    cid, reference, code, t = str(uuid.uuid4()), codes.new_reference(), codes.new_code(), _stamp()
    db.run("INSERT INTO complaints (id, reference, ncrp, status, details_json, wallet_match, created_at, updated_at) "
           "VALUES (?, ?, ?, 'received', ?, NULL, ?, ?)", cid, reference, ncrp, json.dumps(details), t, t)
    for p in payments:
        db.run("INSERT INTO complaint_payments (id, complaint_id, tx_hash, amount, token, network, paid_at, wallet) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ordered_id(), cid, p["hash"], p["amount"], p["token"],
               p["network"], p["paidAt"], p["wallet"])
    salt, digest = codes.hash_code(code)
    db.run("INSERT INTO tracking_codes (complaint_id, ncrp, salt, code_hash, created_at) VALUES (?, ?, ?, ?, ?)",
           cid, ncrp, salt, digest, t)
    flag_shared_wallets(db, cid, [p["wallet"] for p in payments if p["wallet"]])
    return {"reference": reference, "tracking_code": code}


def flag_shared_wallets(db: DB, cid: str, wallets: list[str]) -> None:
    """Tags "complaint" on this and every other complaint that paid one of
    `wallets`. For officers only: nothing here reaches the citizen."""
    others = {r["complaint_id"] for w in set(wallets) for r in db.all(
        "SELECT DISTINCT complaint_id FROM complaint_payments WHERE wallet = ? AND complaint_id <> ?", w, cid)}
    if not others:
        return
    for other in sorted(others | {cid}):
        row = db.one("SELECT wallet_match FROM complaints WHERE id = ?", other)
        tags = ",".join(sorted({t for t in (row["wallet_match"] or "").split(",") if t} | {"complaint"}))
        db.run("UPDATE complaints SET wallet_match = ?, updated_at = ? WHERE id = ?", tags, _stamp(), other)


def view(db: DB, cid: str) -> dict:
    """What a signed-in citizen sees of their own complaint, and nothing else."""
    row = db.one("SELECT reference, status, details_json, created_at FROM complaints WHERE id = ?", cid)
    payments = db.all("SELECT tx_hash, amount, token, network, paid_at, wallet FROM complaint_payments "
                      "WHERE complaint_id = ? ORDER BY id", cid)
    messages = db.all("SELECT sender, body, created_at FROM complaint_messages WHERE complaint_id = ? "
                      "AND sender IN ('citizen', 'officer') ORDER BY created_at, id", cid)
    status = row["status"] if row["status"] in STATUS else "received"
    details = json.loads(row["details_json"])
    return {
        "reference": row["reference"], "sent_at": row["created_at"],
        "status": {"key": status, "text": STATUS[status]},
        "sent": {k: str(details.get(k, "")) for k in TEXT},
        "payments": [{"hash": p["tx_hash"], "amount": p["amount"], "token": p["token"], "network": p["network"],
                      "paidAt": p["paid_at"], "wallet": p["wallet"]} for p in payments],
        "messages": [{"from": "You" if m["sender"] == "citizen" else "Cyber cell", "body": m["body"],
                      "at": m["created_at"]} for m in messages],
    }


def add_message(db: DB, cid: str, body) -> None:
    text = plain(body, MESSAGE_CAP, "The message", multiline=True)
    if not text:
        raise web.Refused(400, "Write a message first.")
    db.run("INSERT INTO complaint_messages (id, complaint_id, sender, body, created_at) VALUES (?, ?, 'citizen', ?, ?)",
           ordered_id(), cid, text, _stamp())
