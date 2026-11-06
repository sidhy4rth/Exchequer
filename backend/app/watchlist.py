"""Watch an address and hear when funds leave it.

A freeze request only works while the money is still at the exchange, and
the window between a scam wallet receiving funds and cashing them out can be
hours. A trace answers "where did it go"; a watch answers "it is moving
now". The investigator watches the scam wallet, or a probable deposit
address, and the server reads what it sent since the last check, forward
from a cursor that only moves over records actually read. Every transfer
found becomes an alert, ranked by where it went:

  exchange  into a labelled exchange wallet: ask that exchange now
  risk      into a sanctioned, mixer, frozen or stolen-funds address
  moved     anywhere else: the funds are on the move
  more      a notice: more moved than one check read; check again or re-trace

Alerts show in the app for the browser that set the watch, and can also be
posted to a Slack, Discord or Google Chat webhook: exchange and flagged
transfers first, each on its own, then one digest of the rest, in the form
each host expects, with label text escaped so it can never ping a channel or
pass for a link. Webhooks go only to those hosts (plus any in
EXCHEQUER_WEBHOOK_HOSTS), over https, without following redirects: a
free-form URL would let anyone make this server call addresses inside its
own network. Their URLs are sealed at rest (webhook_vault.py).

What happened before the watch was set is not news, and everything after it
is: a new EVM watch starts at the chain's head block, a Tron watch at its
creation time, and a watch whose head could not be read takes the first read
as history only for transfers dated before it was set. Reads skip the
provider cache (api_budget.fresh_reads) -- the cache exists to repeat old
answers, and the watch exists to see new ones.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import threading
import time
import uuid
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import and_, case, delete, func, select, update

from . import config, models, ownership, webhook_vault
from .api_budget import TraceBudget, fresh_reads
from .chain_data import open_source
from .etherscan_client import normalize_address
from .exchange_matcher import get_matcher
from .input_rules import plain_text
from .risk_matcher import get_risk_matcher

logger = logging.getLogger(__name__)

MAX_WATCHES_PER_OWNER = 25
MAX_WATCHES_TOTAL = 500
# A watch nobody has listed or checked for this long gives up its slot when
# the server is full (and only then).
WATCH_IDLE_DAYS = 14
# list_watches marks the owner's watches as used at most this often.
TOUCH_EVERY_SECONDS = 3600
MIN_MANUAL_CHECK_SECONDS = 60
FETCH_LIMIT = 50  # records per read
# Forward reads one check may make before it stops and says how far it got.
MAX_PAGES_PER_CHECK = 3
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
_HOST_NAMES = {"hooks.slack.com": "Slack", "discord.com": "Discord", "discordapp.com": "Discord",
               "chat.googleapis.com": "Google Chat"}
_DISCORD = frozenset({"discord.com", "discordapp.com"})

# Where the money went decides what is seen first: in the list, in storage
# and on the webhook. Then how much, then when.
KIND_RANK = {"exchange": 0, "risk": 1, "moved": 2, "more": 3}
_EMOJI = {"exchange": "🏦", "risk": "⚠️", "moved": "➡️", "more": "ℹ️"}
_VERB = {"exchange": "sent to exchange wallet", "risk": "sent to flagged address", "moved": "moved"}
# Webhook delivery: this many exchange or flagged alerts get a post each, the
# rest one digest, so a check makes at most four posts (Discord allows five
# per two seconds). A 429 asking to wait up to MAX_RETRY_AFTER is retried
# once; the whole delivery gives up after DELIVERY_SECONDS.
URGENT_POSTS = 3
MAX_RETRY_AFTER = 5.0
DELIVERY_SECONDS = 8.0
# An alert its webhook did not take is posted with the next check of its
# watch, for this long; after that it counts as failed (it is in the app).
REDELIVER_SECONDS = 24 * 3600
# A claim older than this belongs to a check that died while posting (a
# delivery gives up after DELIVERY_SECONDS): its alerts are pending again.
CLAIM_STALE_SECONDS = 300


class WatchError(ValueError):
    """A watch that cannot be created as asked; the message says why."""


class WebhookFailed(Exception):
    """A webhook post the host did not accept; `retry_after` (s) on a 429."""

    def __init__(self, status: int, retry_after: float | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status, self.retry_after = status, retry_after


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


def client_hash(client: str | None) -> str | None:
    """The connection a watch was made from, hashed. An IPv6 address counts
    as its /64: one host can hold a whole /64 and pick any address in it."""
    if not client:
        return None
    try:
        ip = ipaddress.ip_address(client)
        key = str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)
    except ValueError:
        key = client
    return hashlib.sha256(b"exchequer-watch-client:" + key.encode()).hexdigest()


def _free_idle_slots(s: Any) -> None:
    """Stop the watches nobody has listed or checked for WATCH_IDLE_DAYS, and
    delete their alerts. Run only when the server is full."""
    idle = _iso_ago(WATCH_IDLE_DAYS * 86400)
    stale = select(models.Watch.id).where(
        models.Watch.active, func.coalesce(models.Watch.touched_at, models.Watch.created_at) < idle)
    ids = list(s.scalars(stale))
    if ids:
        s.execute(delete(models.Alert).where(models.Alert.watch_id.in_(ids)))
        s.execute(update(models.Watch).where(models.Watch.id.in_(ids)).values(active=False, webhook_url=None))
        s.flush()
        logger.info("Watchlist full: %d idle watches gave up their slots", len(ids))


def touch(owner: str, watch_ids: list[str] | None = None) -> None:
    """Mark the owner's watches as used (listed or checked), at most hourly."""
    now = _now()
    stmt = update(models.Watch).where(
        models.Watch.owner_hash == owner, models.Watch.active,
        models.Watch.touched_at.is_(None) | (models.Watch.touched_at < _iso_ago(TOUCH_EVERY_SECONDS)))
    if watch_ids is not None:
        stmt = stmt.where(models.Watch.id.in_(watch_ids))
    with models.session() as s:
        s.execute(stmt.values(touched_at=now))
        s.commit()


def create_watch(owner: str, address: str, chain_key: str | None, asset: str | None,
                 note: str = "", case_id: str | None = None, webhook_url: str | None = None,
                 read_head: Callable[[str, str], int | None] | None = None,
                 client: str | None = None) -> models.Watch:
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

    connection = client_hash(client)
    with models.session() as s:
        sealed = webhook_vault.seal(hook)
        existing = s.scalar(select(models.Watch).where(
            models.Watch.owner_hash == owner, models.Watch.active, models.Watch.address == address,
            models.Watch.chain == chain.key, models.Watch.asset == asset_symbol))
        if existing is not None:
            # Watching it again takes no new slot: it only replaces the
            # webhook (a leaked one too, at any watch count).
            existing.touched_at = created
            if hook:
                existing.webhook_url = sealed
            s.commit()
            s.refresh(existing)
            s.expunge(existing)
            return existing
        mine = s.scalar(select(func.count()).select_from(models.Watch)
                        .where(models.Watch.owner_hash == owner, models.Watch.active))
        if mine >= MAX_WATCHES_PER_OWNER:
            raise WatchError(f"This browser already watches {MAX_WATCHES_PER_OWNER} addresses; remove one first.")
        # Owner keys are free: one connection's share is counted across all
        # of them. Watches made before connections were recorded count for no one.
        if connection is not None:
            held = s.scalar(select(func.count()).select_from(models.Watch)
                            .where(models.Watch.client_hash == connection, models.Watch.active))
            if held >= config.WATCHES_PER_CLIENT:
                raise WatchError(f"This connection already watches {config.WATCHES_PER_CLIENT} addresses; "
                                 "stop one first.")
        total = s.scalar(select(func.count()).select_from(models.Watch).where(models.Watch.active))
        if total >= MAX_WATCHES_TOTAL:
            _free_idle_slots(s)
            total = s.scalar(select(func.count()).select_from(models.Watch).where(models.Watch.active))
        if total >= MAX_WATCHES_TOTAL:
            raise WatchError("The server is watching as many addresses as it can. Try again later.")
        watch = models.Watch(
            id=str(uuid.uuid4()), owner_hash=owner, chain=chain.key, asset=asset_symbol,
            address=address, note=(note or "")[:200], case_id=case_id, webhook_url=sealed,
            created_at=created, last_seen_block=start, active=True,
            client_hash=connection, touched_at=created,
        )
        s.add(watch)
        s.commit()
        s.refresh(watch)
        s.expunge(watch)
    nudge()  # a parked watcher takes its baseline now
    return watch


def watch_summary(watch: models.Watch, unread: int = 0) -> dict[str, Any]:
    hook = webhook_vault.reveal(watch.webhook_url)
    return {
        "watch_id": watch.id,
        "address": watch.address,
        "chain": watch.chain,
        "asset": watch.asset,
        "note": watch.note,
        "case_id": watch.case_id,
        "webhook": mask_webhook(hook),
        # Sealed under a key this server no longer has: it must be entered again.
        "webhook_unreadable": bool(watch.webhook_url) and hook is None,
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
        "tx_url": tx_url(chain_key, alert.tx_hash) if chain_key and alert.tx_hash else "",
        "alert_id": alert.id, "watch_id": alert.watch_id, "created_at": alert.created_at,
        "kind": alert.kind, "message": alert.message, "tx_hash": alert.tx_hash,
        "tx_time": alert.tx_time, "value": alert.value, "asset": alert.asset,
        "counterparty": alert.counterparty, "counterparty_label": alert.counterparty_label,
        "read": alert.read,
    }


def list_watches(owner: str) -> list[dict[str, Any]]:
    touch(owner)  # the owner still uses these: they keep their slots
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


def clear_webhook(owner: str, watch_id: str) -> models.Watch | None:
    """Stop posting a watch's alerts anywhere, and forget the URL; the watch
    goes on. None if the owner has no such watch."""
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is None or watch.owner_hash != owner or not watch.active:
            return None
        watch.webhook_url = None
        s.commit()
        s.refresh(watch)
        s.expunge(watch)
        return watch


def seal_legacy_hooks() -> int:
    """Seal the webhook URLs stored before sealing (or before the key was
    set). Run at startup; returns how many were sealed."""
    if not webhook_vault.sealing():
        return 0
    with models.session() as s:
        rows = list(s.scalars(select(models.Watch).where(
            models.Watch.webhook_url.is_not(None), models.Watch.webhook_url.not_like(webhook_vault.PREFIX + "%"))))
        for watch in rows:
            watch.webhook_url = webhook_vault.seal(watch.webhook_url) if watch.active else None
        s.commit()
        return len(rows)


def list_alerts(owner: str, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    with models.session() as s:
        stmt = select(models.Alert).where(models.Alert.owner_hash == owner)
        if unread_only:
            stmt = stmt.where(models.Alert.read.is_(False))
        # Unread exchange and flagged alerts first, however much moved since:
        # they are the ones a freeze request is sent on.
        urgent_first = case((and_(models.Alert.read.is_(False),
                                  models.Alert.kind.in_(("exchange", "risk"))), 0), else_=1)
        stmt = stmt.order_by(urgent_first, models.Alert.created_at.desc(),
                             models.Alert.tx_time.desc()).limit(limit)
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


def _cursor(chain: config.Chain, last_seen: int | None, created_at: str) -> int | None:
    """Where this check reads from; None for an EVM watch whose start is not known."""
    if chain.address_family == "tron" and (last_seen or 0) < _TRON_EPOCH_FLOOR:
        # Never read, or a cursor from the code that stored block numbers
        # (TRC-20 transfers carry none): read from when the watch was set.
        return _anchor(created_at)
    return last_seen or None  # 0 was an empty first read, not a position


def _reached(chain: config.Chain, through: int) -> str:
    if chain.address_family == "tron":
        from datetime import datetime, timezone
        return datetime.fromtimestamp(through, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"block {through}"


_GAP = (f"More movements than one read returns ({FETCH_LIMIT}) since the last check: some may be "
        "missing here; re-trace the wallet to see them all.")
_GAP_SINCE_SET = (f"More movements since this watch was set than one read returns ({FETCH_LIMIT}): "
                  "some may be missing here; re-trace the wallet to see them all.")


def _read(client: Any, chain: config.Chain, address: str, cursor: int | None,
          anchor: int) -> tuple[list[Any], int | None, str | None]:
    """(new transfers, where the cursor moves, a "more" notice or None).

    From a known cursor the read goes forward (read_outgoing_since): the
    cursor moves only over records actually read, so nothing between two
    checks can be skipped, whatever fills the pages. A provider without that
    read, or an EVM watch whose start is not known, reads the newest page;
    then only transfers after the cursor (or dated after the watch was set)
    are news, and a full page says some may be missing."""
    position = _position_of(chain)
    forward = getattr(client, "read_outgoing_since", None)
    if cursor is not None and forward is not None:
        got: list[Any] = []
        after, complete, cut = cursor, False, None
        for _ in range(MAX_PAGES_PER_CHECK):
            page = forward(address, after=after, limit=FETCH_LIMIT)
            got += [t for t in page.transfers if after < position(t) <= page.through]
            cut = getattr(page, "cut", None) or cut
            if page.through <= after:
                complete = page.complete
                break
            after = page.through
            if page.complete:
                complete = True
                break
        notes = []
        if cut is not None:
            # A block too full to read whole counts as read, or the cursor
            # would stall on it: say so rather than miss it quietly.
            notes.append(f"More records than one read returns sat at {_reached(chain, cut)}: some "
                         "transfers there may be missing here; re-trace the wallet to see them all.")
        if not complete:
            notes.append(f"Not everything since the last check was read in one go: this check reached "
                         f"{_reached(chain, after)}. Press Check now again to read on, or re-trace the wallet.")
        return got, after, " ".join(notes) or None

    transfers = client.get_outgoing_transactions(address, limit=FETCH_LIMIT)
    page_info = getattr(client, "newest_page_info", None)
    full, oldest = (page_info(address) if page_info else None) or (False, None)
    full = full or len(transfers) >= FETCH_LIMIT
    if oldest is None and transfers:
        oldest = min(int(t.timestamp or 0) for t in transfers)
    newest = max((position(t) for t in transfers), default=0)
    if cursor is not None:
        fresh = [t for t in transfers if position(t) > cursor]
        gap = full and len(fresh) == len(transfers)  # the page never reached the cursor
        return fresh, (max(cursor, newest) if fresh else cursor), (_GAP if gap else None)
    # An EVM watch whose head was not known when it was set (or a legacy
    # cursor of 0): what moved since it was set is news, only what came
    # before it is history, and an empty read leaves the start unknown.
    fresh = [t for t in transfers if int(t.timestamp or 0) >= anchor]
    gap = full and oldest is not None and oldest > anchor
    return fresh, (newest if transfers else None), (_GAP_SINCE_SET if gap else None)


def check_watch(watch_id: str, source: Source = open_source,
                post: Callable[[str, dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Read what one watch's address sent since its cursor; store and send any new ones.

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
        owner, last_seen = watch.owner_hash, watch.last_seen_block
        hook = webhook_vault.reveal(watch.webhook_url)  # None if it cannot be read
        case_id, created_at = watch.case_id, watch.created_at
    try:
        chain = config.get_chain(chain_key)
        cursor = _cursor(chain, last_seen, created_at)
        with fresh_reads(), source(chain, asset) as client:
            fresh, seen_block, notice = _read(client, chain, address, cursor, _anchor(created_at))
            unconfirmed = getattr(client, "confirmed_bound_applied", True) is False
    except Exception as exc:  # noqa: BLE001 -- recorded, retried next round
        _finish_check(watch_id, error=f"Could not read the address this round ({type(exc).__name__}).")
        logger.warning("Watch %s: provider failure: %s", watch_id, exc)
        if hook:  # the outbox does not wait for the chain
            _deliver_safely(watch_id, address, chain_key, case_id, post)
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
        more = _more_alert(watch_id, owner, asset, notice) if notice else None
        fresh.sort(key=lambda t: (position(t), t.hash))
        inferred = inferred_for(chain.key, (t.to_address for t in fresh), owner)
        new_alerts = _rank([_alert(watch_id, owner, chain, address, asset, t, inferred) for t in fresh])
        for a in [*new_alerts, *([more] if more is not None else [])]:
            a.delivery = "pending" if hook else None  # the outbox (_deliver_pending)
        out = [alert_summary(a, chain.key, case_id, inferred) for a in new_alerts]
        if more is not None:
            out.append(alert_summary(more, chain.key, case_id))
        if not _finish_check(watch_id, seen_block=seen_block, alerts=new_alerts, more=more,
                             expected=last_seen):
            return []  # removed while we were reading, or another check got there first
    except Exception as exc:  # noqa: BLE001 -- one watch must not stop the rest
        logger.exception("Watch %s: could not store this check", watch_id)
        _record_failure(watch_id, f"Could not store this round's alerts ({type(exc).__name__}).")
        out = []

    if hook:
        _deliver_safely(watch_id, address, chain.key, case_id, post)
    return out


def _deliver_safely(watch_id: str, address: str, chain_key: str, case_id: str | None,
                    post: Callable[[str, dict[str, Any]], None]) -> None:
    """_deliver_pending, never raising: what it did not post stays pending."""
    try:
        _deliver_pending(watch_id, address, chain_key, case_id, post)
    except Exception as exc:  # noqa: BLE001 -- stored; posted with the next check
        logger.exception("Watch %s: webhook delivery failed", watch_id)
        _note_webhook_failure(watch_id, f"Webhook: delivery failed ({type(exc).__name__}); "
                                        "the alerts are in the app.")


def _claim(at: float | None = None) -> str:
    """A delivery claim: 'c', when it was made (hex seconds), and a nonce;
    14 characters of the 16-character column."""
    return f"c{int(time.time() if at is None else at):08x}{uuid.uuid4().hex[:5]}"


def _claimed_at(delivery: str) -> int:
    try:
        return int(delivery[1:9], 16)
    except ValueError:
        return 0  # not a claim this code made: stale


def _deliver_pending(watch_id: str, address: str, chain_key: str, case_id: str | None,
                     post: Callable[[str, dict[str, Any]], None]) -> None:
    """Post this watch's alerts its webhook has not taken yet: this check's,
    and any left from earlier checks in the last day. They are claimed first,
    so two checks of one watch never post the same alert twice; a claim left
    by a check that died while posting is given up after CLAIM_STALE_SECONDS.
    The watch is read again first: one stopped, or whose webhook was removed
    or replaced, while the chain was being read posts nothing to the old URL."""
    claim = _claim()
    cutoff = _iso_ago(REDELIVER_SECONDS)
    Alert = models.Alert
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        hook = webhook_vault.reveal(watch.webhook_url) if watch is not None and watch.active else None
        if not hook:
            return
        stale = time.time() - CLAIM_STALE_SECONDS
        for a in list(s.scalars(select(Alert).where(Alert.watch_id == watch_id, Alert.delivery.like("c%")))):
            if _claimed_at(a.delivery) < stale:
                a.delivery = "pending"
        s.flush()
        mine = (Alert.watch_id == watch_id) & (Alert.delivery == "pending")
        s.execute(update(Alert).where(mine, Alert.created_at < cutoff).values(delivery="failed"))
        s.execute(update(Alert).where(mine, Alert.created_at >= cutoff).values(delivery=claim))
        s.commit()
        rows = list(s.scalars(select(Alert).where(Alert.watch_id == watch_id, Alert.delivery == claim)))
        todo = [alert_summary(a, chain_key, case_id) for a in _rank(rows)]
    if not todo:
        return
    sent: set[str] = set()
    try:
        sent = _deliver(watch_id, hook, address, todo, post)
    finally:  # what was not posted goes back in the outbox, whatever happened
        with models.session() as s:
            for state, ids in (("sent", sent), ("pending", [a["alert_id"] for a in todo if a["alert_id"] not in sent])):
                if ids:
                    s.execute(update(Alert).where(Alert.id.in_(ids), Alert.delivery == claim)
                              .values(delivery=state))
            s.commit()


def _rank(alerts: list[models.Alert]) -> list[models.Alert]:
    return sorted(alerts, key=lambda a: (KIND_RANK.get(a.kind, 9), -(a.value or 0.0), a.tx_time))


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
def _when(ts: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _line(alert: dict[str, Any], address: str) -> str:
    """One alert as a chat line, built from its fields. A URL inside label
    text is broken ("[:]//") so it can never become a link."""
    if alert["kind"] == "more":
        return f"{_EMOJI['more']} Exchequer watch on {address}: {alert['message']}"
    label = (alert["counterparty_label"] or "").replace("://", "[:]//")
    where = f"{label} ({alert['counterparty']})" if label else alert["counterparty"]
    return (f"{_EMOJI[alert['kind']]} Exchequer watch: {address} {_VERB[alert['kind']]}: "
            f"{alert['value']:g} {alert['asset']} to {where} at {_when(alert['tx_time'])}")


def _digest(rest: list[dict[str, Any]], address: str) -> str:
    """Everything not posted on its own, in one message."""
    urgent = sum(1 for a in rest if a["kind"] in ("exchange", "risk"))
    moved = [a for a in rest if a["kind"] == "moved"]
    parts = []
    if urgent:
        parts.append(f"+{urgent} more exchange or flagged transfer{'' if urgent == 1 else 's'}")
    if moved:
        big = max(moved, key=lambda a: a["value"])
        parts.append(f"{len(moved)} other movement{'' if len(moved) == 1 else 's'} (largest "
                     f"{big['value']:g} {big['asset']} at {_when(big['tx_time'])})")
    lines = [f"{_EMOJI['more']} Exchequer watch: {' and '.join(parts)} from {address} since the last "
             "check. Open the watchlist to see them."] if parts else []
    lines += [_line(a, address) for a in rest if a["kind"] == "more"]
    return "\n".join(lines)


def _slack(text: str) -> str:
    """Slack's escaping: only these three are markup in a message."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _discord(text: str) -> str:
    """Discord markdown and mentions shown as typed (mentions are also off)."""
    for ch in "\\*_~|>[]()#@`":
        text = text.replace(ch, "\\" + ch)
    return text


def webhook_payload(url: str, text: str, link: str = "") -> dict[str, Any]:
    """The body each host expects, and nothing else: Google Chat refuses
    unknown fields, Slack and Discord would render label markup live. Our own
    explorer link is added after the text is escaped."""
    host = (urlsplit(url).hostname or "").lower()
    tail = f" — {link}" if link else ""
    if host in _DISCORD:
        body = _discord(text)[: 1900 - len(tail)]
        return {"content": body + tail, "allowed_mentions": {"parse": []}}
    if host == "chat.googleapis.com":
        return {"text": text.replace("<", "‹").replace(">", "›") + tail}
    return {"text": _slack(text) + tail}  # Slack, and hosts the operator added


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _deliver(watch_id: str, hook: str, address: str, ranked: list[dict[str, Any]],
             post: Callable[[str, dict[str, Any]], None]) -> set[str]:
    """Post alerts: the first URGENT_POSTS exchange or flagged ones on their
    own, then one digest. A failure stops delivery and is written on the
    watch; the alerts are in the app either way. Returns the ids posted."""
    urgent = [a for a in ranked if a["kind"] in ("exchange", "risk")][:URGENT_POSTS]
    picked = {id(a) for a in urgent}
    rest = [a for a in ranked if id(a) not in picked]
    messages = [(_line(a, address), a["tx_url"], [a["alert_id"]]) for a in urgent]
    if rest:
        messages.append((_digest(rest, address), "", [a["alert_id"] for a in rest]))
    posted: set[str] = set()
    host = (urlsplit(hook).hostname or "").lower()
    name = _HOST_NAMES.get(host, host)
    spacing = 0.5 if host in _DISCORD else 1.0
    started = time.monotonic()
    for i, (text, link, ids) in enumerate(messages):
        left = sum(len(m[2]) for m in messages[i:])
        if time.monotonic() - started > DELIVERY_SECONDS:
            _note_webhook_failure(watch_id, f"Webhook: {name} was too slow; {left} alerts not posted "
                                            "(they are in the app).")
            return posted
        if i:
            _pause(spacing)
        payload = webhook_payload(hook, text, link)
        try:
            try:
                post(hook, payload)
            except WebhookFailed as exc:
                if exc.status != 429 or exc.retry_after is None or exc.retry_after > MAX_RETRY_AFTER:
                    raise
                _pause(exc.retry_after)
                post(hook, payload)
        except Exception as exc:  # noqa: BLE001 -- the alerts are stored either way
            why = (f"answered {exc.status}" if isinstance(exc, WebhookFailed)
                   else f"could not be reached ({type(exc).__name__})")
            logger.warning("Watch %s: webhook %s", watch_id, why)
            _note_webhook_failure(watch_id, f"Webhook: {name} {why}; {left} alerts not posted "
                                            "(they are in the app).")
            return posted
        posted.update(ids)
    return posted


def _note_webhook_failure(watch_id: str, error: str) -> None:
    """Say on the watch that its webhook failed, unless the check itself
    already recorded a provider error there: that one matters more."""
    with models.session() as s:
        watch = s.get(models.Watch, watch_id)
        if watch is not None and watch.last_error is None:
            watch.last_error = error[:300]
            s.commit()


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
            # Unread exchange and flagged alerts are kept first: newer dust
            # must never push out the alert that matters.
            urgent_first = case((and_(models.Alert.read.is_(False),
                                      models.Alert.kind.in_(("exchange", "risk"))), 0), else_=1)
            keep = (select(models.Alert.id).where(models.Alert.watch_id == watch_id)
                    .order_by(urgent_first, models.Alert.tx_time.desc(), models.Alert.created_at.desc())
                    .limit(MAX_ALERTS_PER_WATCH))
            s.execute(delete(models.Alert).where(models.Alert.watch_id == watch_id,
                                                 models.Alert.id.not_in(keep)))
        s.commit()
        return True


def _http() -> httpx.Client:
    return httpx.Client(timeout=5.0, follow_redirects=False)


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds a 429 asks to wait: the header, or Discord's JSON retry_after."""
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        pass
    try:
        value = response.json().get("retry_after")
        return max(0.0, float(value)) if value is not None else None
    except (ValueError, AttributeError, TypeError):
        return None


def post_webhook(url: str, payload: dict[str, Any]) -> None:
    """POST to an allowed webhook host. Re-validated here, never redirected.
    Raises WebhookFailed for any answer but a 2xx."""
    validate_webhook(url)
    with _http() as client:
        response = client.post(url, json=payload)
    if response.status_code == 429:
        raise WebhookFailed(429, _retry_after(response))
    if not 200 <= response.status_code < 300:
        raise WebhookFailed(response.status_code)


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

