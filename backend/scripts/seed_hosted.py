"""Replay the DEMO.md traces against a hosted instance so its case store is
not empty on the day -- demo 10's related-cases panel needs the two sibling
phishing wallets to have been traced.

    .venv/bin/python -m scripts.seed_hosted https://<host>

Runs each trace in demo_traces.json in order (shared intermediaries hit the
response cache, so the set takes a couple of minutes), and prints one line
per trace.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    host = sys.argv[1].rstrip("/")

    def post(path: str, body: dict, timeout: int = 600):
        req = urllib.request.Request(f"{host}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=timeout))

    seeds = json.loads((Path(__file__).parent / "demo_traces.json").read_text())
    for s in seeds:
        t = time.time()
        try:
            d = post("/trace", s)
            print(f"  {s['address'][:12]} {s['direction']:8} d{s['max_depth']} | {time.time() - t:5.1f}s | "
                  f"{str(d.get('exchange')):9} conf {d.get('confidence')} | nodes {len(d['graph']['nodes'])}")
        except Exception as exc:  # keep going; one failed trace should not stop the seed
            print(f"  {s['address'][:12]} FAILED {exc}")
    print("stored cases:", json.load(urllib.request.urlopen(f"{host}/cases"))["count"])


if __name__ == "__main__":
    main()
