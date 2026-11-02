"""Who is calling: the one place an endpoint learns it.

Every endpoint written from now on takes the caller as a dependency:

    from ..auth import CurrentUser

    @router.post("/things")
    def make_thing(user: CurrentUser): ...

There are no accounts yet, so `current_user` returns a demo identity built
from what the browser already sends: its owner key (ownership.py). That makes
`user.owner_hash` exactly what this browser's cases are stored under, so a
route can filter by owner through it today. R23 replaces the body of
`current_user` with a real sign-in; the fields of `User` stay, and no route
changes when it lands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from . import ownership

# The roles R23 brings. Until then everyone is a demo officer.
ROLES = ("officer", "supervisor", "analyst", "auditor", "expert", "citizen")
DEMO_UNIT = "demo"


@dataclass(frozen=True)
class User:
    id: str                 # stable for this caller; "anonymous" without an owner key
    role: str               # one of ROLES
    unit: str               # the police unit whose cases this user works on
    owner_hash: str | None  # SHA-256 of the browser's owner key, as stored cases carry it
    demo: bool = True       # True until R23: nobody has signed in


def current_user(request: Request) -> User:
    """The caller, as a FastAPI dependency. A demo identity until R23."""
    owner = ownership.owner_hash_from_headers(request.headers)
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
