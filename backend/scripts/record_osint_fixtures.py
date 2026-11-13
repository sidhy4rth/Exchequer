"""Record the live RDAP and DNS responses test_domain_lookup.py replays (run by hand only).

    cd backend && python -m scripts.record_osint_fixtures

Looks up a few public domains for real through app.domain_lookup and writes every
response it received, unchanged, to tests/fixtures/osint/responses.json, keyed by
the request. Tests never touch the network (CLAUDE.md rule 8): they replay this
file. Never edit it by hand; run this again to refresh it, and say so in the PR.

The domains are ones whose registration is public and stable:
  example.com      reserved by IANA, registered through the .com registry (Verisign)
  www.example.com  stripped to example.com by the register, so the same record
  sub.example.com  not a registered name: the registry answers 404, then example.com
  nixi.in          the operator of the .in registry, through the .in RDAP service
"""
from __future__ import annotations

import json
from pathlib import Path

from app import domain_lookup

DOMAINS = ("example.com", "sub.example.com", "nixi.in")
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "osint" / "responses.json"


def main() -> None:
    seen: dict[str, dict[str, object]] = {}
    real = domain_lookup._get

    def recording(url: str, params: dict[str, str] | None = None, accept: str = "application/json") -> tuple[int, bytes]:
        status, body = real(url, params=params, accept=accept)
        key = url if not params else f"{url}?" + "&".join(f"{k}={v}" for k, v in params.items())
        seen[key] = {"status": status, "body": body.decode("utf-8")}
        return status, body

    domain_lookup._get = recording
    try:
        for name in DOMAINS:
            found = domain_lookup.look_up(name)
            print(name, "rdap:", (found["rdap"] or {}).get("registered_on"), found["rdap_note"] or "",
                  "| dns:", {k: len(v) for k, v in found["dns"].items()}, found["dns_note"] or "")
    finally:
        domain_lookup._get = real
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(seen)} responses to {OUT}")


if __name__ == "__main__":
    main()
