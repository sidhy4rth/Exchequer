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

The first check of a new watch only records where the history ends; what
happened before the watch was set is not news. Reads skip the provider cache
(api_budget.fresh_reads) -- the cache exists to repeat old answers, and the
watch exists to see new ones.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, func, select, update

from . import config, models
from .api_budget import fresh_reads
from .chain_data import open_source
from .etherscan_client import normalize_address
from .exchange_matcher import get_matcher
from .risk_matcher import get_risk_matcher

logger = logging.getLogger(__name__)

MAX_WATCHES_PER_OWNER = 25
MAX_WATCHES_TOTAL = 500
MIN_MANUAL_CHECK_SECONDS = 60
FETCH_LIMIT = 50  # newest outgoing transfers read per check
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
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise WatchError("A webhook must be an https:// URL.")
    if parts.hostname.lower() not in webhook_hosts() or parts.port not in (None, 443) or parts.username:
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
def create_watch(owner: str, address: str, chain_key: str | None, asset: str | None,
                 note: str = "", case_id: str | None = None, webhook_url: str | None = None) -> models.Watch:
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
            created_at=_now(), active=True,
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
                  case_id: str | None = None) -> dict[str, Any]:
    return {
        "chain": chain_key,
        "case_id": case_id,
        "exchange": exchange_of(chain_key, alert.counterparty) if chain_key and alert.kind == "exchange" else None,
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
        return [alert_summary(a, *watches.get(a.watch_id, (None, None))) for a in alerts]


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


_inferred_cache: dict[str, Any] = {"version": None, "by_chain": {}}
_inferred_lock = threading.Lock()


def inferred_deposits(chain_key: str) -> dict[str, str]:
    """address -> exchange, for every deposit address a stored case inferred.

    Label files only name hot wallets and known deposit addresses; most
    deposit addresses are found by inference during a trace. A watched wallet
    paying one of those is paying an exchange, and should say so. Rebuilt
    only when a case has been stored since."""
    with _inferred_lock:
        if _inferred_cache["version"] != models.store_version():
            by_chain: dict[str, dict[str, str]] = {}
            for case in models.all_cases():
                result = case.result
                chain = result.get("chain") or "ethereum"
                for match in result.get("inferred_deposits") or []:
                    if match.get("address") and match.get("exchange"):
                        by_chain.setdefault(chain, {})[normalize_address(match["address"])] = match["exchange"]
            _inferred_cache.update(version=models.store_version(), by_chain=by_chain)
        return _inferred_cache["by_chain"].get(chain_key, {})


def _classify(chain_key: str, counterparty: str) -> tuple[str, str]:
    """(kind, label) for where a transfer went."""
    risk = get_risk_matcher(chain_key).lookup(counterparty)
    if risk:
        return "risk", f"{str(risk.get('category', 'flagged')).title()}: {risk.get('label') or risk.get('entity') or ''}".strip()
    exch = get_matcher(chain_key).lookup(counterparty)
    if exch:
        return "exchange", exch.get("label") or exch.get("exchange") or "exchange"
    inferred = inferred_deposits(chain_key).get(normalize_address(counterparty)) if counterparty else None
    if inferred:
        return "exchange", f"probable {inferred} deposit address (inferred)"
    return "moved", ""


def exchange_of(chain_key: str, counterparty: str) -> str | None:
    """The exchange a counterparty belongs to, by label file or inference."""
    if not counterparty:
        return None
    try:
        exch = get_matcher(chain_key).lookup(counterparty)
    except config.UnknownChainError:
        return None
    if exch:
        return exch.get("exchange")
    return inferred_deposits(chain_key).get(normalize_address(counterparty))


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
        case_id = watch.case_id
    chain = config.get_chain(chain_key)
    try:
        with fresh_reads(), source(chain, asset) as client:
            transfers = client.get_outgoing_transactions(address, limit=FETCH_LIMIT)
    except Exception as exc:  # noqa: BLE001 -- recorded, retried next round
        _finish_check(watch_id, error=f"Could not read the address this round ({type(exc).__name__}).")
        logger.warning("Watch %s: provider failure: %s", watch_id, exc)
        return []

    position = _position_of(chain)
    newest = max((position(t) for t in transfers), default=0)
    new_alerts: list[models.Alert] = []
    if last_seen is None or (chain.address_family == "tron" and last_seen < _TRON_EPOCH_FLOOR):
        # First check: the baseline. History before the watch is not news.
        # A Tron watch whose cursor is below any real timestamp was baselined
        # by block number, which TRC-20 transfers do not carry; start again.
        seen_block = newest
    else:
        fresh = sorted((t for t in transfers if position(t) > last_seen),
                       key=lambda t: (position(t), t.hash))
        for t in fresh:
            to = t.to_address or ""
            kind, label = _classify(chain.key, to)
            where = f"{label} ({to})" if label else to
            verb = {"exchange": "sent to exchange wallet", "risk": "sent to flagged address",
                    "moved": "moved"}[kind]
            message = f"{address} {verb}: {t.value_native:g} {asset} to {where} in tx {t.hash}"
            new_alerts.append(models.Alert(
                id=str(uuid.uuid4()), watch_id=watch_id, owner_hash=owner,
                created_at=_now(), kind=kind, message=message, tx_hash=t.hash,
                tx_time=int(t.timestamp), value=float(t.value_native), asset=asset,
                counterparty=to, counterparty_label=label, read=False,
            ))
        seen_block = max(last_seen, newest) if fresh else last_seen
    out = [alert_summary(a, chain.key, case_id) for a in new_alerts]
    if not _finish_check(watch_id, seen_block=seen_block, alerts=new_alerts, expected=last_seen):
        return []  # removed while we were reading, or another check got there first

    if hook and out:
        for alert in out[:10]:
            emoji = {"exchange": "🏦", "risk": "⚠️", "moved": "➡️"}[alert["kind"]]
            text = f"{emoji} Exchequer watch: {alert['message']} — {alert['tx_url']}"
            try:
                post(hook, {"text": text, "content": text[:1900], "alert": alert})
            except Exception as exc:  # noqa: BLE001 -- the alert is stored either way
                logger.warning("Watch %s: webhook failed: %s", watch_id, type(exc).__name__)
    return out


def _finish_check(watch_id: str, seen_block: int | None = None, error: str | None = None,
                  alerts: list[models.Alert] | None = None, expected: int | None = None) -> bool:
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


def watcher_status() -> dict[str, Any]:
    """What the watcher has actually done, not what it is set to do (R30).

    On a host that sleeps when idle, as Render's free plan does, the watcher
    sleeps with it: a watch set at noon is not checked overnight, and the
    panel used to say "checked about every ten minutes" regardless. This reads
    the newest check from the store, so it survives a restart, and calls it
    stale when watches exist, checks are on, and none has run for three
    intervals -- or, for a watch never checked, since it was made."""
    interval = config.WATCH_INTERVAL_SECONDS
    with models.session() as s:
        active = models.Watch.active.is_(True)
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
    Returns how many watches are active. One query to find them."""
    cutoff = _iso_ago(interval)
    with models.session() as s:
        active = s.execute(select(models.Watch.id, models.Watch.last_checked_at)
                           .where(models.Watch.active)).all()
    due = sorted((w for w in active if w.last_checked_at is None or w.last_checked_at <= cutoff),
                 key=lambda w: (w.last_checked_at is not None, w.last_checked_at or ""))
    for watch_id, _ in due:
        if _stop.is_set():
            break
        check_watch(watch_id)
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
        except Exception:  # noqa: BLE001 -- the loop must outlive one bad round
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

