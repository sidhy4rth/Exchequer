"""Who is calling: the one place an endpoint learns it.

Every endpoint written from now on takes the caller as a dependency:

    from ..auth import CurrentUser

    @router.post("/things")
    def make_thing(user: CurrentUser): ...

With a live session cookie (accounts.py) the caller is that signed-in
officer, with their role and unit. Without one it is the demo identity built
from what the browser already sends, its owner key (ownership.py), exactly
as before accounts existed: the recorded demos and every flow that never
signs in keep working. Either way `user.owner_hash` is what this browser's
cases are stored under, so a route can filter by owner through it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from . import accounts, ownership

# Every role; an officer account holds one of accounts.OFFICER_ROLES, and the
# demo user is an officer.
ROLES = ("officer", "supervisor", "admin", "analyst", "auditor", "expert", "citizen")
DEMO_UNIT = "demo"


@dataclass(frozen=True)
class User:
    id: str                 # stable for this caller; "anonymous" without an owner key
    role: str               # one of ROLES
    unit: str               # the police unit whose cases this user works on
    owner_hash: str | None  # SHA-256 of the browser's owner key, as stored cases carry it
    demo: bool = True       # True unless an officer has signed in
    officer_id: int | None = None
    unit_id: int | None = None  # the unit's id when signed in; its cases read as the caller's


def is_page_load(request: Request) -> bool:
    """A browser opening the URL, as opposed to the app's own fetch(): browsers
    send Sec-Fetch-Mode, and an older one still asks for text/html."""
    mode = request.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return "text/html" in request.headers.get("accept", "")


def current_user(request: Request) -> User:
    """The caller, as a FastAPI dependency: the signed-in officer, else the
    demo identity. An officer with a temporary password must change it
    (POST /auth/password) before anything else; until then a page load
    (a reload, a shared link) is the demo caller, so the route serves the app
    page, where the change can be made, instead of this refusal."""
    owner = ownership.owner_hash_from_headers(request.headers)
    found = accounts.signed_in(request.cookies.get(accounts.COOKIE)) if accounts.COOKIE in request.cookies else None
    if found is not None and not (found[0].must_change_password and is_page_load(request)):
        officer, unit = found
        if officer.must_change_password:
            raise HTTPException(status_code=403, detail="Change your temporary password first.")
        return User(id=f"officer-{officer.id}", role=officer.role, unit=unit.name, owner_hash=owner,
                    demo=False, officer_id=officer.id, unit_id=unit.id)
    return User(
        # A prefix of the hash, never the key: ids end up in logs.
        id=f"demo-{owner[:12]}" if owner else "anonymous",
        role="officer",
        unit=DEMO_UNIT,
        owner_hash=owner,
    )


# What a route's parameter is annotated with. The Annotated form, not
# `= Depends(current_user)`: FastAPI recommends it, and ruff's B008 rejects
# a function call as a default.
CurrentUser = Annotated[User, Depends(current_user)]
