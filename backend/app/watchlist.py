"""Watch an address and hear when funds leave it.

A freeze request only works while the money is still at the exchange, and
the window between a scam wallet receiving funds and cashing them out can be
hours. A trace answers "where did it go"; a watch answers "it is moving
now". The investigator watches the scam wallet, or a probable deposit
address, and the server re-reads its outgoing transfers on a schedule. Every
transfer newer than the last one seen becomes an alert, ranked by where it
went:

  exchange  into a labelled exchange wallet: ask that exchange now
  risk      into a sanctioned, mixer, frozen or stolen-funds address
  moved     anywhere else: the funds are on the move

Alerts show in the app for the browser that set the watch, and can also be
posted to a Slack, Discord or Google Chat webhook. Webhooks go only to those
hosts (plus any in EXCHEQUER_WEBHOOK_HOSTS), over https, without following
redirects: a free-form URL would let anyone make this server call addresses
inside its own network.

What happened before the watch was set is not news, and everything after it
is: a new EVM watch starts at the chain's head block, a Tron watch at its
creation time, and a watch whose head could not be read takes the first read
as history only for transfers dated before it was set. Reads skip the
provider cache (api_budget.fresh_reads) -- the cache exists to repeat old
answers, and the watch exists to see new ones.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, select, update

from . import config, models, ownership
from .api_budget import TraceBudget, fresh_reads
from .chain_data import open_source
from .etherscan_client import normalize_address
from .exchange_matcher import get_matcher
from .input_rules import plain_text
from .risk_matcher import get_risk_matcher

logger = logging.getLogger(__name__)

MAX_WATCHES_PER_OWNER = 25
MAX_WATCHES_TOTAL = 500
MIN_MANUAL_CHECK_SECONDS = 60
FETCH_LIMIT = 50  # newest outgoing transfers read per check
# Clock drift allowed between this server and the chain when a watch's
# creation time is the line between history and news.
ANCHOR_SKEW_SECONDS = 60
# How long creating a watch may wait for the chain's head block.
HEAD_READ_SECONDS = 5.0
# Alerts kept per watch, newest first. Every check of a busy wallet can store a
# page of them and nothing else removes them; 500 watches x 200 bounds the
# table at about 100k rows on the free database.
MAX_ALERTS_PER_WATCH = 200

DEFAULT_WEBHOOK_HOSTS = frozenset({
    "hooks.slack.com", "discord.com", "discordapp.com", "chat.googleapis.com",
})


class WatchError(ValueError):
    """A watch that cannot be created as asked; the message says why."""


def webhook_hosts() -> frozenset[str]:
    extra = {h.strip().lower() for h in config.WEBHOOK_EXTRA_HOSTS.split(",") if h.strip()}
    return DEFAULT_WEBHOOK_HOSTS | extra


def validate_webhook(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    try:
        # An unclosed [ or a port that is not a number in range raises here.
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise WatchError("A webhook must be an https:// URL on an allowed host.") from exc
    if parts.scheme != "https" or not parts.hostname:
        raise WatchError("A webhook must be an https:// URL.")
    if parts.hostname.lower() not in webhook_hosts() or port not in (None, 443) or parts.username:
        raise WatchError(
            "Webhooks can go to Slack (hooks.slack.com), Discord (discord.com) or Google Chat "
            "(chat.googleapis.com). Ask the operator to allow another host."
        )
    return url


def mask_webhook(url: str | None) -> str | None:
    """Enough to recognise a webhook, not enough to post to it."""
    if not url:
        return None
    return f"https://{urlsplit(url).hostname}/…"


def _now() -> str:
    return models.utc_now_iso()


def tx_url(chain_key: str, tx_hash: str) -> str:
    """The transaction on the chain's public explorer."""
    try:
        chain = config.get_chain(chain_key)
    except config.UnknownChainError:
        return ""
    if chain.address_family == "tron":
        return f"{chain.explorer_url}/#/transaction/{tx_hash}"
    return f"{chain.explorer_url}/tx/{tx_hash}"


# ---------------------------------------------------------------------------
# Creating and listing
# ---------------------------------------------------------------------------
def chain_head(chain_key: str, asset: str, source: Any = None) -> int | None:
    """The chain's newest block now: where a new EVM watch starts reading.

    One request, fresh, under a few seconds' deadline; None if it cannot be
    had (the watch then dates its first read instead). A Tron watch's cursor
    is a time, so it needs none."""
    try:
        chain = config.get_chain(chain_key)
        if chain.address_family == "tron":
            return None
        with fresh_reads(), (source or open_source)(chain, asset) as client:
            read = getattr(client, "head_block", None)
            if read is None:
                return None
            client.budget = TraceBudget(HEAD_READ_SECONDS, 0.0)
            head = int(read())
        return head if head > 0 else None
    except Exception as exc:  # noqa: BLE001 -- the watch is made either way
        logger.info("Could not read the %s head for a new watch: %s", chain_key, type(exc).__name__)
        return None


def _anchor(created_at: str) -> int:
    """When a watch was set, as a Unix time, less the allowed clock drift."""
    from datetime import datetime
    return int(datetime.fromisoformat(created_at).timestamp()) - ANCHOR_SKEW_SECONDS


def create_watch(owner: str, address: str, chain_key: str | None, asset: str | None,
                 note: str = "", case_id: str | None = None, webhook_url: str | None = None,
                 read_head: Callable[[str, str], int | None] | None = None) -> models.Watch:
    try:
        chain = config.get_chain(chain_key)
    except config.UnknownChainError as exc:
        raise WatchError(str(exc)) from exc
    address = address.strip()
    if not chain.validate_address(address):
        raise WatchError(f"'{address}' is not a valid {chain.name} address. Expected {chain.address_hint(address)}.")
    asset_symbol = (asset or chain.native_symbol).strip().upper()
    if asset_symbol != chain.native_symbol.upper() and chain.find_token(asset_symbol) is None:
        raise WatchError(f"{chain.name} has no traceable asset called '{asset_symbol}'.")
    hook = validate_webhook(webhook_url)
    address = normalize_address(address)
    # Where the watch starts, read before the store is opened: a Tron cursor
    # is the creation time, an EVM one the head block now (None if unknown).
    created = _now()
    if chain.address_family == "tron":
        start: int | None = _anchor(created)
    else:
        start = read_head(chain.key, asset_symbol) if read_head else None

    with models.session() as s:
        mine = s.scalar(select(func.count()).select_from(models.Watch)
                        .where(models.Watch.owner_hash == owner, models.Watch.active))
        if mine >= MAX_WATCHES_PER_OWNER:
            raise WatchError(f"This browser already watches {MAX_WATCHES_PER_OWNER} addresses; remove one first.")
        total = s.scalar(select(func.count()).select_from(models.Watch).where(models.Watch.active))
        if total >= MAX_WATCHES_TOTAL:
            raise WatchError("The server is watching as many addresses as it can. Try again later.")
        existing = s.scalar(select(models.Watch).where(
            models.Watch.owner_hash == owner, models.Watch.active, models.Watch.address == address,
            models.Watch.chain == chain.key, models.Watch.asset == asset_symbol))
        if existing is not None:
            if hook:
                existing.webhook_url = hook
                s.commit()
            s.refresh(existing)
            s.expunge(existing)
            return existing
        watch = models.Watch(
            id=str(uuid.uuid4()), owner_hash=owner, chain=chain.key, asset=asset_symbol,
            address=address, note=(note or "")[:200], case_id=case_id, webhook_url=hook,
            created_at=created, last_seen_block=start, active=True,
        )
        s.add(watch)
        s.commit()
        s.refresh(watch)
        s.expunge(watch)
    nudge()  # a parked watcher takes its baseline now
    return watch


def watch_summary(watch: models.Watch, unread: int = 0) -> dict[str, Any]:
    return {
        "watch_id": watch.id,
        "address": watch.address,
        "chain": watch.chain,
        "asset": watch.asset,
        "note": watch.note,
        "case_id": watch.case_id,
        "webhook": mask_webhook(watch.webhook_url),
        "created_at": watch.created_at,
        "last_checked_at": watch.last_checked_at,
        "baseline_set": watch.last_seen_block is not None,
        "last_error": watch.last_error,
        "unread_alerts": unread,
    }


def alert_summary(alert: models.Alert, chain_key: str | None = None,
                  case_id: str | None = None, inferred: Inferred | None = None) -> dict[str, Any]:
    exchange = (exchange_of(chain_key, alert.counterparty, inferred)
                if chain_key and alert.kind == "exchange" else None)
    return {
        "chain": chain_key,
        "case_id": case_id,
        "exchange": exchange,
        "tx_url": tx_url(chain_key, alert.tx_hash) if chain_key else "",
        "alert_id": alert.id, "watch_id": alert.watch_id, "created_at": alert.created_at,
        "kind": alert.kind, "message": alert.message, "tx_hash": alert.tx_hash,
        "tx_time": alert.tx_time, "value": alert.value, "asset": alert.asset,
        "counterparty": alert.counterparty, "counterparty_label": alert.counterparty_label,
        "read": alert.read,
    }


def list_watches(owner: str) -> list[dict[str, Any]]:
    with models.session() as s:
        watches = list(s.scalars(select(models.Watch).where(
            models.Watch.owner_hash == owner, models.Watch.active).order_by(models.Watch.created_at.desc())))
        unread = dict(s.execute(
            select(models.Alert.watch_id, func.count()).where(
                models.Alert.owner_hash == owner, models.Alert.read.is_(False)
            ).group_by(models.Alert.watch_id)).all())
        return [watch_summary(w, unread.get(w.id, 0)) for w in watches]


def get_owned_watch(owner: str, watch_id: str) -> models.Watch | None:
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or watch.owner_hash != owner or not watch.active:
            return None
        s.expunge(watch)
        return watch


def remove_watch(owner: str, watch_id: str) -> bool:
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or watch.owner_hash != owner or not watch.active:
            return False
        watch.active = False
        watch.webhook_url = None
        s.commit()
        return True


def list_alerts(owner: str, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    with models.session() as s:
        stmt = select(models.Alert).where(models.Alert.owner_hash == owner)
        if unread_only:
            stmt = stmt.where(models.Alert.read.is_(False))
        stmt = stmt.order_by(models.Alert.created_at.desc(), models.Alert.tx_time.desc()).limit(limit)
        alerts = list(s.scalars(stmt))
        watches = {w.id: (w.chain, w.case_id) for w in s.scalars(select(models.Watch).where(
            models.Watch.id.in_({a.watch_id for a in alerts})))}
    # Exchange alerts name their exchange; an inferred one only from the
    # owner's own or the demo cases.
    asked: dict[str, set[str]] = {}
    for a in alerts:
        chain_key = watches.get(a.watch_id, (None, None))[0]
        if chain_key and a.kind == "exchange":
            asked.setdefault(chain_key, set()).add(a.counterparty)
    inferred = {chain_key: inferred_for(chain_key, parties, owner) for chain_key, parties in asked.items()}
    out = []
    for a in alerts:
        chain_key, case_id = watches.get(a.watch_id, (None, None))
        out.append(alert_summary(a, chain_key, case_id, inferred.get(chain_key)))
    return out


def mark_read(owner: str, alert_ids: list[str] | None = None) -> int:
    with models.session() as s:
        stmt = select(models.Alert).where(models.Alert.owner_hash == owner, models.Alert.read.is_(False))
        if alert_ids:
            stmt = stmt.where(models.Alert.id.in_(alert_ids))
        alerts = list(s.scalars(stmt))
        for a in alerts:
            a.read = True
        s.commit()
        return len(alerts)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------
Source = Callable[[config.Chain, str], Any]


# address -> (exchange, "own" | "demo"), from inferred_for.
Inferred = dict[str, tuple[str, str]]
_LOOKUP_CHUNK = 500


def inferred_for(chain_key: str, counterparties: Iterable[str], owner: str | None) -> Inferred:
    """Which of `counterparties` a case `owner` may see inferred to be an
    exchange deposit address: address -> (exchange, scope).

    Label files only name hot wallets and known deposit addresses; most
    deposit addresses are found by inference during a trace, and a watched
    wallet paying one of those is paying an exchange. Only the owner's own
    traces ("own") and the public demo cases ("demo") count, as in every
    cross-case computation (ownership.py): an inference from another
    browser's trace -- which anyone can plant -- never labels this owner's
    alerts. One indexed query per 500 addresses; no case is loaded."""
    keys = sorted({normalize_address(c) for c in counterparties if c})
    if not keys:
        return {}
    row = models.InferredDeposit
    demo = models.InferredDeposit.owner_hash.is_(None) & func.lower(row.seed_address).in_(
        sorted(ownership.demo_addresses()))
    visible = demo | (row.owner_hash == owner) if owner else demo
    found: Inferred = {}
    with models.session() as s:
        for i in range(0, len(keys), _LOOKUP_CHUNK):
            stmt = (select(row.address, row.exchange, row.owner_hash)
                    .where(row.chain == chain_key, row.address.in_(keys[i:i + _LOOKUP_CHUNK]), visible)
                    .order_by(row.id.desc()))
            for address, exchange, row_owner in s.execute(stmt):
                scope = "own" if owner and row_owner == owner else "demo"
                if address not in found or (scope == "own" and found[address][1] == "demo"):
                    found[address] = (exchange, scope)
    return found


def _classify(chain_key: str, counterparty: str, inferred: Inferred | None = None) -> tuple[str, str]:
    """(kind, label) for where a transfer went."""
    risk = get_risk_matcher(chain_key).lookup(counterparty)
    if risk:
        return "risk", f"{str(risk.get('category', 'flagged')).title()}: {risk.get('label') or risk.get('entity') or ''}".strip()
    exch = get_matcher(chain_key).lookup(counterparty)
    if exch:
        return "exchange", exch.get("label") or exch.get("exchange") or "exchange"
    hit = (inferred or {}).get(normalize_address(counterparty)) if counterparty else None
    if hit:
        exchange, scope = hit
        where = "inferred" if scope == "own" else "inferred in a demo case"
        return "exchange", f"probable {exchange} deposit address ({where})"
    return "moved", ""


def exchange_of(chain_key: str, counterparty: str, inferred: Inferred | None = None) -> str | None:
    """The exchange a counterparty belongs to, by label file or by an
    inference in `inferred` (inferred_for, already scoped to the owner)."""
    if not counterparty:
        return None
    try:
        exch = get_matcher(chain_key).lookup(counterparty)
    except config.UnknownChainError:
        return None
    if exch:
        return exch.get("exchange")
    hit = (inferred or {}).get(normalize_address(counterparty))
    return hit[0] if hit else None


# Any real Tron timestamp is after this (2001); block numbers are far below it.
_TRON_EPOCH_FLOOR = 1_000_000_000


def _position_of(chain: config.Chain) -> Callable[[Any], int]:
    """How far along the chain a transfer is, for "newer than last seen".

    The block number on EVM chains. On Tron, the time: TronGrid's TRC-20
    endpoint returns no block number (every USDT transfer reads as block 0),
    so a block cursor would never see one as new. The watch's
    last_seen_block column then holds a Unix time."""
    if chain.address_family == "tron":
        return lambda t: int(t.timestamp or 0)
    return lambda t: int(t.block_number or 0)


def check_watch(watch_id: str, source: Source = open_source,
                post: Callable[[str, dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Read one watch's newest outgoing transfers; store and send any new ones.

    Returns the new alerts. A provider failure is recorded on the watch and
    tried again next round, never raised."""
    post = post or post_webhook
    # Read what the check needs, then let go of the database: the provider can
    # take seconds (longer with retries), and an open SQLite transaction for
    # that long would block every case being saved meanwhile.
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or not watch.active:
            return []
        address, asset, chain_key = watch.address, watch.asset, watch.chain
        owner, last_seen, hook = watch.owner_hash, watch.last_seen_block, watch.webhook_url
        case_id, created_at = watch.case_id, watch.created_at
    try:
        chain = config.get_chain(chain_key)
        with fresh_reads(), source(chain, asset) as client:
            transfers = client.get_outgoing_transactions(address, limit=FETCH_LIMIT)
            unconfirmed = getattr(client, "confirmed_bound_applied", True) is False
            page_info = getattr(client, "newest_page_info", None)
            full_page, oldest = (page_info(address) if page_info else None) or (False, None)
    except Exception as exc:  # noqa: BLE001 -- recorded, retried next round
        _finish_check(watch_id, error=f"Could not read the address this round ({type(exc).__name__}).")
        logger.warning("Watch %s: provider failure: %s", watch_id, exc)
        return []
    if unconfirmed:
        # The head could not be read, so the newest rows may not have settled:
        # no alert and no cursor move on them; next round tries again.
        _finish_check(watch_id, error="Could not read the chain's newest block this round.")
        return []

    # Everything after the read is guarded too: a check that cannot classify
    # or store what it read records that and moves on (r2-g2-watchlist-alerts-0-7).
    try:
        position = _position_of(chain)
        newest = max((position(t) for t in transfers), default=0)
        read_cursor = last_seen  # the stored cursor, which _finish_check moves only from
        anchor = _anchor(created_at)
        more: models.Alert | None = None
        if chain.address_family == "tron" and (last_seen or 0) < _TRON_EPOCH_FLOOR:
            # Never read, or a cursor from the code that stored block numbers
            # (TRC-20 transfers carry none): read from when the watch was set.
            last_seen = anchor
        if last_seen:
            fresh = [t for t in transfers if position(t) > last_seen]
            seen_block: int | None = max(last_seen, newest) if fresh else last_seen
        else:
            # An EVM watch whose head was not known when it was set (or a
            # legacy cursor of 0): what moved since it was set is news, and
            # only what came before it is history.
            fresh = [t for t in transfers if int(t.timestamp or 0) >= anchor]
            seen_block = newest if transfers else None
            if full_page and oldest and oldest > anchor:
                more = _more_alert(watch_id, owner, asset, "More movements since this watch was set "
                                   f"than one read returns ({FETCH_LIMIT}): some may be missing here; "
                                   "re-trace the wallet to see them all.")
        fresh.sort(key=lambda t: (position(t), t.hash))
        inferred = inferred_for(chain.key, (t.to_address for t in fresh), owner)
        new_alerts = [_alert(watch_id, owner, chain, address, asset, t, inferred) for t in fresh]
        out = [alert_summary(a, chain.key, case_id, inferred) for a in new_alerts]
        if more is not None:
            out.append(alert_summary(more, chain.key, case_id))
        if not _finish_check(watch_id, seen_block=seen_block, alerts=new_alerts, more=more,
                             expected=read_cursor):
            return []  # removed while we were reading, or another check got there first
    except Exception as exc:  # noqa: BLE001 -- one watch must not stop the rest
        logger.exception("Watch %s: could not store this check", watch_id)
        _record_failure(watch_id, f"Could not store this round's alerts ({type(exc).__name__}).")
        return []

    if hook and out:
        for alert in out[:10]:
            emoji = {"exchange": "🏦", "risk": "⚠️", "moved": "➡️", "more": "ℹ️"}[alert["kind"]]
            text = f"{emoji} Exchequer watch: {alert['message']} — {alert['tx_url']}"
            try:
                post(hook, {"text": text, "content": text[:1900], "alert": alert})
            except Exception as exc:  # noqa: BLE001 -- the alert is stored either way
                logger.warning("Watch %s: webhook failed: %s", watch_id, type(exc).__name__)
    return out


# Column sizes the store enforces (Postgres does; SQLite does not).
_LABEL_LEN = models.Alert.__table__.c.counterparty_label.type.length
_PARTY_LEN = models.Alert.__table__.c.counterparty.type.length
_HASH_LEN = models.Alert.__table__.c.tx_hash.type.length
_MESSAGE_LEN = 1000


def _alert(watch_id: str, owner: str, chain: config.Chain, address: str, asset: str,
           t: Any, inferred: Inferred | None = None) -> models.Alert:
    """One transfer as an alert. Provider fields and label text come from
    outside, so each is cut to its column and stripped of control characters."""
    to = plain_text(t.to_address, _PARTY_LEN)
    tx_hash = plain_text(t.hash, _HASH_LEN)
    kind, label = _classify(chain.key, to, inferred)
    label = plain_text(label, _LABEL_LEN)
    where = f"{label} ({to})" if label else to
    verb = {"exchange": "sent to exchange wallet", "risk": "sent to flagged address",
            "moved": "moved"}[kind]
    message = plain_text(f"{address} {verb}: {t.value_native:g} {asset} to {where} in tx {tx_hash}",
                         _MESSAGE_LEN)
    return models.Alert(
        id=str(uuid.uuid4()), watch_id=watch_id, owner_hash=owner,
        created_at=_now(), kind=kind, message=message, tx_hash=tx_hash,
        tx_time=int(t.timestamp), value=float(t.value_native), asset=asset,
        counterparty=to, counterparty_label=label, read=False,
    )


def _more_alert(watch_id: str, owner: str, asset: str, message: str) -> models.Alert:
    """The watch's one "more" row: movements a check knows of but did not
    read. Its id is fixed per watch, so a later notice replaces it."""
    from datetime import datetime, timezone
    return models.Alert(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"exchequer-watch-more:{watch_id}")),
        watch_id=watch_id, owner_hash=owner, created_at=_now(), kind="more",
        message=plain_text(message, _MESSAGE_LEN), tx_hash="",
        tx_time=int(datetime.now(tz=timezone.utc).timestamp()), value=0.0, asset=asset,
        counterparty="", counterparty_label="", read=False,
    )


def _record_failure(watch_id: str, error: str) -> None:
    """A check that read the chain but could not store what it found. The
    time and the reason are written on their own; the cursor stays, so the
    watch goes to the back of the queue, the Check-now cooldown applies, and
    the same transfers are tried again next time."""
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or not watch.active:
            return
        watch.last_checked_at = _now()
        watch.last_error = error[:300]
        s.commit()


def _finish_check(watch_id: str, seen_block: int | None = None, error: str | None = None,
                  alerts: list[models.Alert] | None = None, more: models.Alert | None = None,
                  expected: int | None = None) -> bool:
    """Record a check's outcome in one short transaction. False if the watch is
    gone, or if its cursor is no longer `expected` (what this check read).

    Two checks of one watch can overlap: the watcher's round and a Check now,
    or two instances during a deploy. Both read the same cursor and the same
    new transfers; the cursor moves only from the value this check read
    (compare-and-set), so the second stores and posts nothing and a slower
    check can never move the cursor back."""
    with models.session() as s:
        stmt = (update(models.Watch).where(models.Watch.id == watch_id, models.Watch.active.is_(True))
                .values(last_checked_at=_now(), last_error=error))
        if error is None and seen_block is not None:
            stmt = (stmt.where(models.Watch.last_seen_block.is_not_distinct_from(expected))
                    .values(last_seen_block=seen_block))
        if s.execute(stmt.execution_options(synchronize_session=False)).rowcount != 1:
            s.rollback()
            return False
        s.add_all(alerts or [])
        if more is not None:
            s.merge(more)  # replaces the watch's earlier "more" row, read or not
        s.flush()
        if alerts:
            keep = (select(models.Alert.id).where(models.Alert.watch_id == watch_id)
                    .order_by(models.Alert.tx_time.desc(), models.Alert.created_at.desc())
                    .limit(MAX_ALERTS_PER_WATCH))
            s.execute(delete(models.Alert).where(models.Alert.watch_id == watch_id,
                                                 models.Alert.id.not_in(keep)))
        s.commit()
        return True


def post_webhook(url: str, payload: dict[str, Any]) -> None:
    """POST to an allowed webhook host. Re-validated here, never redirected."""
    validate_webhook(url)
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        client.post(url, json=payload).raise_for_status()


def due_watch_ids(interval_seconds: float) -> list[str]:
    cutoff = models.utc_now_iso() if interval_seconds <= 0 else _iso_ago(interval_seconds)
    with models.session() as s:
        stmt = select(models.Watch.id).where(models.Watch.active).where(
            (models.Watch.last_checked_at.is_(None)) | (models.Watch.last_checked_at <= cutoff))
        return list(s.scalars(stmt.order_by(models.Watch.last_checked_at.is_not(None),
                                            models.Watch.last_checked_at)))


def _iso_ago(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def seconds_since_check(watch: models.Watch) -> float | None:
    if not watch.last_checked_at:
        return None
    from datetime import datetime, timezone
    return (datetime.now(tz=timezone.utc) - datetime.fromisoformat(watch.last_checked_at)).total_seconds()


# How many missed intervals make the watcher "stale": long enough to ride out
# a slow round, short enough to say so within half an hour at the default.
STALE_AFTER_INTERVALS = 3


def watcher_status(owner: str | None = None) -> dict[str, Any]:
    """What the watcher has actually done, not what it is set to do (R30).

    On a host that sleeps when idle, as Render's free plan does, the watcher
    sleeps with it: a watch set at noon is not checked overnight, and the
    panel used to say "checked about every ten minutes" regardless. This reads
    the newest check from the store, so it survives a restart, and calls it
    stale when watches exist, checks are on, and none has run for three
    intervals -- or, for a watch never checked, since it was made.

    With `owner`, only that browser's watches count; without, the whole site
    (for the operator's /health/detail only)."""
    interval = config.WATCH_INTERVAL_SECONDS
    with models.session() as s:
        active = models.Watch.active.is_(True)
        if owner is not None:
            active = active & (models.Watch.owner_hash == owner)
        count = s.scalar(select(func.count()).select_from(models.Watch).where(active)) or 0
        last = s.scalar(select(func.max(models.Watch.last_checked_at)).where(active))
        never = s.scalar(select(func.min(models.Watch.created_at)).where(active)
                         .where(models.Watch.last_checked_at.is_(None)))
    # The newest check; with none yet, the oldest watch still waiting for one.
    # (ISO-8601 UTC strings in one format, so they compare as text.)
    reference = last or never
    stale = bool(config.WATCHER_ENABLED and count and reference
                 and reference < _iso_ago(STALE_AFTER_INTERVALS * interval))
    return {
        "enabled": config.WATCHER_ENABLED,
        "running": _thread is not None and _thread.is_alive(),
        "interval_seconds": interval,
        "active_watches": count,
        "last_check_at": last,
        "stale": stale,
    }


# ---------------------------------------------------------------------------
# The background poller
# ---------------------------------------------------------------------------
_stop = threading.Event()
# Set when a watch is created (nudge) or the watcher stops: wakes a watcher
# parked because there was nothing to watch.
_wake = threading.Event()
_thread: threading.Thread | None = None


def nudge() -> None:
    _wake.set()


def _round(interval: float) -> int:
    """Check every due watch, unchecked first, then the longest unchecked.
    Returns how many watches are active. One query to find them. Each watch
    fails on its own: one that raises is logged and the round goes on."""
    cutoff = _iso_ago(interval)
    with models.session() as s:
        active = s.execute(select(models.Watch.id, models.Watch.last_checked_at)
                           .where(models.Watch.active)).all()
    due = sorted((w for w in active if w.last_checked_at is None or w.last_checked_at <= cutoff),
                 key=lambda w: (w.last_checked_at is not None, w.last_checked_at or ""))
    for watch_id, _ in due:
        if _stop.is_set():
            break
        try:
            check_watch(watch_id)
        except Exception:  # noqa: BLE001 -- one watch must not stop the rest
            logger.exception("Watch %s: check failed", watch_id)
    return len(active)


def _loop(interval: float) -> None:
    """Rounds a full interval apart; with no watch at all, no query until one
    is created. A free hosted Postgres scales to zero after a few idle
    minutes, and a query every minute kept it awake for as long as the site was."""
    logger.info("Watchlist: checking watched addresses every %d s", interval)
    while not _stop.is_set():
        _wake.clear()  # before the round: a watch created during it wakes the next
        active = None
        try:
            active = _round(interval)
        except Exception:  # noqa: BLE001 -- the store itself; the loop must outlive it
            logger.exception("Watchlist round failed")
        if _stop.is_set():
            break
        _wake.wait(None if active == 0 else interval)


def start_in_background() -> None:
    global _thread
    if not config.WATCHER_ENABLED or (_thread is not None and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(config.WATCH_INTERVAL_SECONDS,),
                               name="watchlist", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()

