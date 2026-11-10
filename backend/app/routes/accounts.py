"""Signing in, and the admin's accounts pages (accounts.py has the rules).

POST /auth/login, /auth/logout and /auth/password; GET /auth/me (the
officer, or {"demo": true} with no session). Admins only: /admin/units and
/admin/officers. POST /auth/bootstrap makes the first admin with
EXCHEQUER_BOOTSTRAP_TOKEN, and answers 404 when that is unset or an admin
exists. Every state-changing route here also needs the X-Exchequer-Request
header (accounts.CSRF_HEADER).

Sign-in is limited per client and per e-mail from that client
(rate_limit.py), and repeated failures make the next try wait longer, up to
half a minute. No account is ever locked, and failures from other clients
never hold a client back: that would let anyone shut an officer out.
"""
from __future__ import annotations

import hmac
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError

from .. import accounts, audit, config, rate_limit
from ..models import Officer, Unit

router = APIRouter()

EMAIL = r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$"
Role = Literal["officer", "supervisor", "admin"]  # accounts.OFFICER_ROLES


def _csrf(http: Request) -> None:
    if http.headers.get(accounts.CSRF_HEADER) != "1":
        raise HTTPException(status_code=403, detail=f"This request needs the {accounts.CSRF_HEADER} header.")


CSRF = [Depends(_csrf)]


def _session(http: Request) -> tuple[Officer, Unit]:
    found = accounts.signed_in(http.cookies.get(accounts.COOKIE))
    if found is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    return found


def _admin(http: Request) -> Officer:
    officer, _ = _session(http)
    if officer.must_change_password:
        raise HTTPException(status_code=403, detail="Change your temporary password first.")
    if officer.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can do this.")
    return officer


Admin = Annotated[Officer, Depends(_admin)]


def _client(http: Request) -> str:
    return rate_limit.client_ip(http.headers, http.client.host if http.client else None)


def _too_many(wait: float) -> HTTPException:
    return HTTPException(status_code=429, headers={"Retry-After": str(int(wait) + 1)},
                         detail=f"Too many sign-in attempts. Try again in {int(wait) + 1} seconds.")


def _pair(email: str, client: str) -> str:
    return f"{email} {client}"


def _held(client: str, email: str) -> float | None:
    """Seconds this client must wait before its next try for this e-mail, or None.

    It waits out its own failures. Failures for the e-mail from everywhere
    (guessing spread over many addresses) hold only a client that has failed
    for it too, so nobody can keep an officer out by failing for them."""
    pair = _pair(email, client)
    waits = [rate_limit.login_client_delay.wait(client), rate_limit.login_pair_delay.wait(pair)]
    if rate_limit.login_pair_delay.failures(pair):
        waits.append(rate_limit.login_email_delay.wait(email))
    return max((w for w in waits if w), default=None)


def _failed(client: str, email: str) -> None:
    rate_limit.login_client_delay.failed(client)
    rate_limit.login_pair_delay.failed(_pair(email, client))
    rate_limit.login_email_delay.failed(email)


def _admit(client: str, email: str) -> None:
    """Refuse a try while this client is waiting out failures or over its limits."""
    if wait := _held(client, email):
        raise _too_many(wait)
    wait = rate_limit.login_clients.check(client)
    if wait is None and (wait := rate_limit.login_emails.check(_pair(email, client))) is not None:
        rate_limit.login_clients.refund(client)
    if wait is not None:
        raise _too_many(wait)


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


@router.post("/auth/login", dependencies=CSRF)
def login(body: Login, http: Request, response: Response) -> dict[str, Any]:
    client, email = _client(http), accounts.normal_email(body.email)
    _admit(client, email)
    found = accounts.authenticate(email, body.password)
    if found is None:
        _failed(client, email)
        audit.record("auth.login_failed")
        raise HTTPException(status_code=401, detail=accounts.LOGIN_FAILED)
    officer, unit = found
    rate_limit.login_emails.refund(_pair(email, client))  # it counts failures only
    rate_limit.login_client_delay.succeeded(client)
    rate_limit.login_pair_delay.succeeded(_pair(email, client))
    rate_limit.login_email_delay.succeeded(email)
    local = http.url.hostname in ("localhost", "127.0.0.1", "::1")
    response.set_cookie(accounts.COOKIE, accounts.start_session(officer.id), path="/", httponly=True,
                        samesite="strict", secure=not local, max_age=int(accounts.SESSION_MAX.total_seconds()))
    audit.record("auth.login", detail={"officer_id": officer.id})
    return accounts.public(officer, unit)


@router.post("/auth/logout", dependencies=CSRF)
def logout(http: Request, response: Response) -> dict[str, bool]:
    token = http.cookies.get(accounts.COOKIE)
    officer_id = accounts.end_session(token) if token else None
    response.delete_cookie(accounts.COOKIE, path="/", httponly=True, samesite="strict")
    if officer_id is not None:
        audit.record("auth.logout", detail={"officer_id": officer_id})
    return {"signed_out": True}


@router.get("/auth/me")
def me(http: Request) -> dict[str, Any]:
    found = accounts.signed_in(http.cookies.get(accounts.COOKIE))
    return accounts.public(*found) if found else {"demo": True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/auth/password", dependencies=CSRF)
def change_password(body: PasswordChange, http: Request) -> dict[str, Any]:
    officer, unit = _session(http)
    if wait := _held(client := _client(http), officer.email):
        raise _too_many(wait)
    if not accounts.verify_password(body.current_password, officer.password_hash):
        _failed(client, officer.email)
        raise HTTPException(status_code=401, detail="The current password is wrong.")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=422, detail="Choose a password different from the current one.")
    accounts.set_password(officer.id, body.new_password, keep_token=http.cookies[accounts.COOKIE])
    audit.record("auth.password_change", detail={"officer_id": officer.id})
    return accounts.public(*accounts.get_officer(officer.id))


class Bootstrap(BaseModel):
    token: str = Field(max_length=256)
    email: str = Field(max_length=254, pattern=EMAIL)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    unit: str = Field(min_length=1, max_length=120)


async def _bootstrap_body(http: Request) -> Bootstrap:
    """404 before anything else while the route is closed, so neither the
    header check nor the body's validation shows that it exists."""
    if not config.BOOTSTRAP_TOKEN or await run_in_threadpool(accounts.admin_exists):
        raise HTTPException(status_code=404, detail="Not Found")
    _csrf(http)
    try:
        return Bootstrap.model_validate_json(await http.body())
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None


@router.post("/auth/bootstrap", include_in_schema=False)
def bootstrap(body: Annotated[Bootstrap, Depends(_bootstrap_body)], http: Request) -> dict[str, Any]:
    if (wait := rate_limit.login_clients.check(_client(http))) is not None:
        raise _too_many(wait)
    if not hmac.compare_digest(body.token.encode(), config.BOOTSTRAP_TOKEN.encode()):
        audit.record("auth.bootstrap_refused")
        raise HTTPException(status_code=403, detail="Not authorised.")
    unit = accounts.create_unit(body.unit)
    officer, _ = accounts.create_officer(body.email, body.name, unit.id, "admin", password=body.password)
    audit.record("auth.bootstrap", detail={"officer_id": officer.id, "unit_id": unit.id})
    return accounts.public(officer, unit)


# -- admin ------------------------------------------------------------------------
class NewUnit(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.post("/admin/units", dependencies=CSRF)
def new_unit(body: NewUnit, admin: Admin) -> dict[str, Any]:
    unit = accounts.create_unit(body.name)
    audit.record("admin.unit_create", detail={"by": admin.id, "unit_id": unit.id})
    return {"id": unit.id, "name": unit.name}


@router.get("/admin/units")
def list_units(admin: Admin) -> dict[str, Any]:
    return {"units": [{"id": u.id, "name": u.name} for u in accounts.units()]}


class NewOfficer(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL)
    name: str = Field(min_length=1, max_length=120)
    unit_id: int
    role: Role


@router.post("/admin/officers", dependencies=CSRF)
def new_officer(body: NewOfficer, admin: Admin) -> dict[str, Any]:
    """The new account and its temporary password, shown this once and never again."""
    try:
        officer, temp = accounts.create_officer(body.email, body.name, body.unit_id, body.role)
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except accounts.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    audit.record("admin.officer_create", detail={"by": admin.id, "officer_id": officer.id, "role": officer.role})
    return {"officer": accounts.public(*accounts.get_officer(officer.id)), "temporary_password": temp}


@router.get("/admin/officers")
def list_officers(admin: Admin) -> dict[str, Any]:
    return {"officers": [accounts.public(o, u) for o, u in accounts.officers()]}


class OfficerChange(BaseModel):
    role: Role | None = None
    unit_id: int | None = None
    active: bool | None = None
    reset_password: bool = False


@router.patch("/admin/officers/{officer_id}", dependencies=CSRF)
def change_officer(officer_id: int, body: OfficerChange, admin: Admin) -> dict[str, Any]:
    """Change a role, unit or active flag, or reset the password (a new
    temporary one, shown once). A reset or deactivation signs them out."""
    try:
        temp = accounts.change_officer(officer_id, body.role, body.unit_id, body.active, body.reset_password)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except accounts.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    audit.record("admin.officer_update", detail={"by": admin.id, "officer_id": officer_id,
                                                 **body.model_dump(exclude_none=True)})
    out: dict[str, Any] = {"officer": accounts.public(*accounts.get_officer(officer_id))}
    if temp:
        out["temporary_password"] = temp
    return out
