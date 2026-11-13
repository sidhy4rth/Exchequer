"""Public facts about a scam site's domain (suite feature 4, OSINT slice 2).

For a domain on a case's identifier register (identifiers.py), fetch:
  - its RDAP registration record from the domain's own registry, found through
    IANA's RDAP bootstrap file: the registrar, when it was registered, when it
    expires, the registrar's abuse contact, its name servers;
  - its DNS records (A, AAAA, NS) from one fixed DNS-over-HTTPS resolver.

A domain registered days before the fraud is a lead, and the registrar is who a
takedown or a request for the customer's details goes to. It is never an identity:
the record names a registrar, not the person behind the site.

Safety. The server never fetches a URL an officer typed. It fetches only:
IANA's bootstrap file, the https RDAP base URL that file names for the domain's
TLD, and the fixed resolver below -- with a name that identifiers.domain() has
accepted (no IP address, no local or reserved name) as the only parameter.
Redirects are never followed.

Every response is kept with where it came from, when, its HTTP status and the
SHA-256 of its body as received, as evidence.py does for chain data, so a printed
fact can be checked against the bytes it came from. Behind config.OSINT_LOOKUPS.
Tests replace _get with recorded responses (tests/fixtures/osint/), which only
scripts/record_osint_fixtures.py writes, by hand.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import func, select

from . import identifiers, models
from .display_text import one_line
from .evidence import sha256_hex

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
DOH_URL = "https://cloudflare-dns.com/dns-query"
DNS_TYPES = ("A", "AAAA", "NS")
TIMEOUT_S = 8.0  # for one request
DEADLINE_S = 30.0  # for a whole lookup: up to 8 requests, however slowly a server answers
BODY_MAX = 512 * 1024  # an RDAP record is a few kB; more than this is not one
BOOTSTRAP_TTL_S = 24 * 3600
RDAP_TRIES = 4  # pay.shop.co.in -> shop.co.in -> co.in: the registry knows the registered name
LOOKUPS_PER_IDENTIFIER = 50
USER_AGENT = "Exchequer case tool (RDAP and DNS lookups for an investigation)"
_transport: httpx.BaseTransport | None = None  # tests set an httpx.MockTransport
_deadline = threading.local()  # .at: _clock() by which this thread's lookup must end
_clock = time.monotonic  # tests set a clock that a slow server moves on


class LookupError_(RuntimeError):
    """A lookup could not be made at all; the message says why, in words for the officer."""


class TooSlow(LookupError_):
    """The lookup ran past DEADLINE_S; what was fetched before it is kept."""


def _left() -> float:
    """Seconds left of this lookup's deadline (TIMEOUT_S outside a lookup); TooSlow when none are."""
    at = getattr(_deadline, "at", None)
    if at is None:
        return TIMEOUT_S
    left = at - _clock()
    if left <= 0:
        raise TooSlow(f"The lookup took longer than {DEADLINE_S:.0f} seconds, so it stopped.")
    return min(TIMEOUT_S, left)


def _get(url: str, params: dict[str, str] | None = None, accept: str = "application/json") -> tuple[int, bytes]:
    """GET `url` and give back (status, body). Never follows a redirect, and stops at the
    lookup's deadline even while a slow server is still sending. Replaced in tests."""
    with httpx.Client(timeout=_left(), follow_redirects=False, headers={"User-Agent": USER_AGENT},
                      transport=_transport) as client:
        with client.stream("GET", url, params=params, headers={"Accept": accept}) as response:
            body = b""
            for chunk in response.iter_bytes():
                _left()
                body += chunk
                if len(body) > BODY_MAX:
                    raise LookupError_(f"{urlsplit(url).hostname} sent more than {BODY_MAX // 1024} kB.")
            return response.status_code, body


def _now() -> str:
    return models.utc_now_iso()


def _record(source: str, url: str, status: int, body: bytes) -> dict[str, Any]:
    return {"source": source, "provider": urlsplit(url).hostname, "request": url, "status": status,
            "fetched_at": _now(), "sha256": sha256_hex(body), "bytes": len(body),
            "body": body.decode("utf-8", errors="replace")}


# -- the RDAP bootstrap: which registry answers for which TLD -------------------------------------
_bootstrap: dict[str, Any] = {"at": 0.0, "map": {}, "record": None}
_bootstrap_lock = threading.Lock()


def _parse_bootstrap(body: bytes) -> dict[str, str]:
    """TLD -> https RDAP base. An answer not shaped like IANA's file raises ValueError."""
    data = json.loads(body)
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, list):
        raise ValueError("not an RDAP bootstrap file")
    out: dict[str, str] = {}
    for service in services:
        if not (isinstance(service, list) and len(service) >= 2 and isinstance(service[0], list)
                and isinstance(service[1], list)):
            continue
        tlds, urls = service[0], service[1]
        https = [u for u in urls if isinstance(u, str) and urlsplit(u).scheme == "https" and urlsplit(u).hostname]
        if not https:
            continue
        base = https[0] if https[0].endswith("/") else https[0] + "/"
        for tld in tlds:
            out[str(tld).lower()] = base
    return out


def rdap_base(tld: str, records: list[dict[str, Any]]) -> str | None:
    """The https RDAP base URL IANA lists for `tld`, or None when the TLD has no RDAP service."""
    with _bootstrap_lock:
        if time.monotonic() - _bootstrap["at"] > BOOTSTRAP_TTL_S or not _bootstrap["map"]:
            status, body = _get(BOOTSTRAP_URL)
            record = _record("rdap-bootstrap", BOOTSTRAP_URL, status, body)
            if status != 200:
                raise LookupError_(f"IANA's list of registries answered {status}; try again later.")
            _bootstrap.update(at=time.monotonic(), map=_parse_bootstrap(body), record=record)
        bootstrap_record = dict(_bootstrap["record"])
    # The list is the same for every lookup: keep its hash, not its 30 kB, with each.
    bootstrap_record.pop("body", None)
    records.append(bootstrap_record)
    return _bootstrap["map"].get(tld)


# -- reading an RDAP record ---------------------------------------------------------------------
def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _vcard(entity: dict[str, Any], field: str) -> str:
    card = entity.get("vcardArray")
    if not (isinstance(card, list) and len(card) == 2 and isinstance(card[1], list)):
        return ""
    for item in card[1]:
        if isinstance(item, list) and len(item) >= 4 and item[0] == field and isinstance(item[3], str):
            return one_line(item[3]).strip()
    return ""


def _list(value: Any) -> list[Any]:
    """A JSON field that should be a list; anything else reads as empty."""
    return value if isinstance(value, list) else []


def _entities(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in _list(node.get("entities")) if isinstance(e, dict)]


def parse_rdap(body: bytes) -> dict[str, Any]:
    """The facts an officer needs from an RDAP domain record. Registrant details are
    not read: they are usually redacted, and the registrar is who can name its customer."""
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("not an RDAP record")
    events = {e.get("eventAction"): str(e.get("eventDate") or "")[:10]
              for e in _list(data.get("events")) if isinstance(e, dict)}
    registrar = next((e for e in _entities(data) if "registrar" in _list(e.get("roles"))), {})
    abuse = next((e for e in _entities(registrar) if "abuse" in _list(e.get("roles"))), {})
    iana_id = next((str(i.get("identifier")) for i in _list(registrar.get("publicIds"))
                    if isinstance(i, dict) and i.get("type") == "IANA Registrar ID"), "")
    return {
        "name": one_line(_text(data.get("ldhName"))).lower(),
        "registrar": _vcard(registrar, "fn"),
        "registrar_iana_id": iana_id,
        "registered_on": events.get("registration", ""),
        "expires_on": events.get("expiration", ""),
        "changed_on": events.get("last changed", ""),
        "abuse_email": _vcard(abuse, "email"),
        "abuse_phone": _vcard(abuse, "tel"),
        "status": [one_line(s) for s in _list(data.get("status")) if isinstance(s, str)],
        "name_servers": sorted(one_line(n["ldhName"]).lower().rstrip(".") for n in _list(data.get("nameservers"))
                               if isinstance(n, dict) and isinstance(n.get("ldhName"), str) and n["ldhName"]),
    }


def parse_dns(body: bytes, rtype: str) -> list[str]:
    """The records of `rtype` in a DNS-over-HTTPS JSON answer. One not shaped like one raises ValueError."""
    code = {"A": 1, "AAAA": 28, "NS": 2}[rtype]
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("not a DNS answer")
    return sorted({one_line(a["data"]).rstrip(".").lower() for a in _list(data.get("Answer"))
                   if isinstance(a, dict) and a.get("type") == code and isinstance(a.get("data"), str) and a["data"]})


# -- one lookup ----------------------------------------------------------------------------------
def look_up(name: str) -> dict[str, Any]:
    """RDAP and DNS facts about `name`, with every response kept. Raises LookupError_ only
    when nothing could be asked; a registry that does not know the name is a result.
    The whole lookup ends within DEADLINE_S; what was fetched by then is kept."""
    host = identifiers.domain(name)  # the same check that let it onto the register
    _deadline.at = _clock() + DEADLINE_S
    try:
        return _look_up(host)
    finally:
        _deadline.at = None


def _look_up(host: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    rdap: dict[str, Any] | None = None
    rdap_note = ""
    labels = host.split(".")
    try:
        base = rdap_base(labels[-1], records)
    except TooSlow:
        raise
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise LookupError_(f"IANA's list of registries could not be read ({type(exc).__name__}); try again later.") from exc
    if base is None:
        rdap_note = f"The .{labels[-1]} registry offers no RDAP service, so no registration record was fetched."
    else:
        for i in range(min(RDAP_TRIES, len(labels) - 1)):
            candidate = ".".join(labels[i:])
            url = base + "domain/" + quote(candidate, safe="")
            try:
                status, body = _get(url, accept="application/rdap+json")
            except TooSlow as exc:
                rdap_note = str(exc)
                break
            except (httpx.HTTPError, LookupError_) as exc:
                rdap_note = f"The registry could not be reached ({type(exc).__name__})."
                break
            records.append(_record("rdap", url, status, body))
            if status == 200:
                try:
                    rdap = parse_rdap(body)
                except (ValueError, TypeError, AttributeError):
                    rdap_note = "The registry's answer was not an RDAP record."
                break
            if status != 404:
                rdap_note = f"The registry answered {status}."
                break
        else:
            rdap_note = "The registry has no record of this domain or the domain it is part of."
    dns: dict[str, list[str]] = {}
    dns_note = ""
    for rtype in DNS_TYPES:
        try:
            status, body = _get(DOH_URL, params={"name": host, "type": rtype}, accept="application/dns-json")
        except TooSlow as exc:
            dns_note = str(exc)
            break
        except (httpx.HTTPError, LookupError_) as exc:
            dns_note = f"The DNS resolver could not be reached ({type(exc).__name__})."
            break
        records.append(_record("dns", f"{DOH_URL}?name={quote(host)}&type={rtype}", status, body))
        if status == 200:
            try:
                dns[rtype] = parse_dns(body, rtype)
            except (ValueError, TypeError, AttributeError):
                dns_note = "The DNS resolver's answer could not be read."
        else:
            dns_note = f"The DNS resolver answered {status}."
    return {"queried": host, "rdap": rdap, "rdap_note": rdap_note, "dns": dns, "dns_note": dns_note,
            "records": records}


# -- kept per identifier -------------------------------------------------------------------------
def _brief(r: models.DomainLookup) -> dict[str, Any]:
    """A lookup as the screen shows it: the facts and where each came from, not the raw bodies."""
    records = json.loads(r.records_json or "[]")
    return {
        "lookup_id": r.id, "identifier_id": r.identifier_id, "case_id": r.case_id, "queried": r.queried, "created_at": r.created_at,
        "by": r.by, **json.loads(r.summary_json or "{}"),
        "sources": [{k: rec.get(k) for k in ("source", "provider", "request", "status", "fetched_at", "sha256", "bytes")}
                    for rec in records],
    }


def _check_cap(s: Any, identifier_id: str) -> None:
    done = s.scalar(select(func.count()).select_from(models.DomainLookup)
                    .where(models.DomainLookup.identifier_id == identifier_id))
    if done >= LOOKUPS_PER_IDENTIFIER:
        raise identifiers.IdentifierError(f"This domain was already looked up {LOOKUPS_PER_IDENTIFIER} times.")


def run_and_keep(identifier_id: str, viewer: Any) -> dict[str, Any] | None:
    """Look up an active domain identifier the viewer may read and keep the result; None when there is none."""
    with models.session() as s:
        row = s.scalars(select(models.CaseIdentifier).where(
            models.CaseIdentifier.id == identifier_id, identifiers._readable(viewer))).first()
        if row is None:
            return None
        if row.kind != "domain":
            raise identifiers.IdentifierError("Only a website domain can be looked up.")
        if row.status != "active":
            raise identifiers.IdentifierError("This identifier was withdrawn; it is not looked up.")
        _check_cap(s, identifier_id)
        value, case_id, owner, unit = row.value, row.case_id, row.owner_hash, row.unit_id
    found = look_up(value)
    summary = {k: found[k] for k in ("rdap", "rdap_note", "dns", "dns_note")}
    with models.session() as s:
        # Counted again just before keeping it, so clicks made while this lookup ran are counted too.
        # Two lookups finishing in the same instant on two workers can still both pass: the cap
        # bounds how often one domain is asked about; it is not an exact count.
        _check_cap(s, identifier_id)
        r = models.DomainLookup(
            id=str(uuid.uuid4()), identifier_id=identifier_id, case_id=case_id, owner_hash=owner, unit_id=unit,
            queried=found["queried"], created_at=_now(), by=getattr(viewer, "id", None) or "unknown",
            summary_json=json.dumps(summary), records_json=json.dumps(found["records"]),
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return _brief(r)


def latest_for(identifier_ids: list[str]) -> dict[str, dict[str, Any]]:
    """The newest lookup of each identifier, by id. Callers pass only ids the viewer may read."""
    if not identifier_ids:
        return {}
    with models.session() as s:
        rows = s.scalars(select(models.DomainLookup).where(models.DomainLookup.identifier_id.in_(identifier_ids))
                         .order_by(models.DomainLookup.created_at)).all()
        return {r.identifier_id: _brief(r) for r in rows}  # later rows overwrite earlier ones
