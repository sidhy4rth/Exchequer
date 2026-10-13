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
from sqlalchemy import func, select

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
        raise WatchError(f"'{address}' is not a valid {chain.name} address. Expected {chain.address_hint()}.")
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


def alert_summary(alert: models.Alert, chain_key: str | None = None) -> dict[str, Any]:
    return {
        "chain": chain_key,
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
        chains = dict(s.execute(select(models.Watch.id, models.Watch.chain).where(
            models.Watch.id.in_({a.watch_id for a in alerts}))).all())
        return [alert_summary(a, chains.get(a.watch_id)) for a in alerts]


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


def _classify(chain_key: str, counterparty: str) -> tuple[str, str]:
    """(kind, label) for where a transfer went."""
    risk = get_risk_matcher(chain_key).lookup(counterparty)
    if risk:
        return "risk", f"{str(risk.get('category', 'flagged')).title()}: {risk.get('label') or risk.get('entity') or ''}".strip()
    exch = get_matcher(chain_key).lookup(counterparty)
    if exch:
        return "exchange", exch.get("label") or exch.get("exchange") or "exchange"
    return "moved", ""


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
    chain = config.get_chain(chain_key)
    try:
        with fresh_reads(), source(chain, asset) as client:
            transfers = client.get_outgoing_transactions(address, limit=FETCH_LIMIT)
    except Exception as exc:  # noqa: BLE001 -- recorded, retried next round
        _finish_check(watch_id, error=f"Could not read the address this round ({type(exc).__name__}).")
        logger.warning("Watch %s: provider failure: %s", watch_id, exc)
        return []

    newest = max((t.block_number for t in transfers), default=0)
    new_alerts: list[models.Alert] = []
    if last_seen is None:
        # First check: the baseline. History before the watch is not news.
        seen_block = newest
    else:
        fresh = sorted((t for t in transfers if t.block_number > last_seen),
                       key=lambda t: (t.block_number, t.hash))
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
    out = [alert_summary(a, chain.key) for a in new_alerts]
    if not _finish_check(watch_id, seen_block=seen_block, alerts=new_alerts):
        return []  # removed while we were reading

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
                  alerts: list[models.Alert] | None = None) -> bool:
    """Record a check's outcome in one short transaction. False if the watch is gone."""
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or not watch.active:
            return False
        watch.last_checked_at = _now()
        watch.last_error = error
        if error is None and seen_block is not None:
            watch.last_seen_block = seen_block
        s.add_all(alerts or [])
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


# ---------------------------------------------------------------------------
# The background poller
# ---------------------------------------------------------------------------
_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop(interval: float) -> None:
    logger.info("Watchlist: checking watched addresses every %d s", interval)
    while not _stop.is_set():
        try:
            for watch_id in due_watch_ids(interval):
                if _stop.is_set():
                    break
                check_watch(watch_id)
        except Exception:  # noqa: BLE001 -- the loop must outlive one bad round
            logger.exception("Watchlist round failed")
        _stop.wait(min(60.0, interval))


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

