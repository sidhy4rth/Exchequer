# Running Exchequer

What the deployed service needs, what it stores, and what each switch does.
The README explains what the tool finds; this file is for whoever keeps it up.

## Environment

| Variable | Default | What it does |
|---|---|---|
| `ETHERSCAN_API_KEY` | — | Ethereum, Polygon and Arbitrum traces. |
| `NODEREAL_API_KEY` | — | BNB Chain traces. |
| `TRONGRID_API_KEY` | — | Raises the Tron rate limit (Tron works without it). |
| `TRONSCAN_API_KEY` | — | Live TronScan tag lookup on Tron traces. |
| `EXCHEQUER_DB_PATH` | `exchequer.db` (`/data/exchequer.db` in the image) | The case store: cases, watches, alerts, freeze requests, batches. SQLite in WAL mode. |
| `API_CACHE_PATH` | `provider_cache.db` beside the store | Provider response cache (24 h). `off` disables it. |
| `EXCHEQUER_SIGNING_KEY` | — | Base64 32-byte Ed25519 seed for signing reports. Without it a key is made on first start at `report_signing_key.pem` beside the store (mode 0600). |
| `EXCHEQUER_SIGNING_KEY_PATH` | `report_signing_key.pem` | Where that file lives. |
| `EXCHEQUER_MAX_RUNNING_TRACES` | 4 | Traces running at once, server-wide. |
| `EXCHEQUER_TRACES_PER_HOUR` | 30 | Traces one client may start per hour (a batch counts every row). `0` = no limit. |
| `EXCHEQUER_TRUST_PROXY` | off (on in the image) | Read the client address from `X-Real-IP` / `X-Forwarded-For`. Only behind a proxy that sets them. |
| `EXCHEQUER_API_DOCS` | on (off in the image) | `/docs`, `/redoc`, `/openapi.json`. |
| `EXCHEQUER_WATCHER` | off (on in the image) | Re-read watched addresses in the background. |
| `EXCHEQUER_WATCH_INTERVAL` | 600 | Seconds between checks of one watch (minimum 60). |
| `EXCHEQUER_WEBHOOK_HOSTS` | — | Comma-separated hosts alert webhooks may post to, beyond Slack, Discord and Google Chat. |
| `EXCHEQUER_WARM_CACHE` | off (on in the image) | Trace the demo addresses at startup so they answer from cache. |

## Endpoints added in October 2026

| Endpoint | Purpose |
|---|---|
| `POST /trace/jobs`, `GET /trace/jobs/{id}`, `GET /trace/jobs/{id}/events` | Background trace with live progress (server-sent events). `POST /trace` still works and waits for the result. |
| `GET /trace/{id}/graph?format=graphml\|csv` | The case's transfer graph for Gephi, yEd, Maltego or a spreadsheet. |
| `GET /trace/{id}/report?format=pdf` | PDF report; the exact signed text is attached inside it. |
| `GET /signing-key`, `POST /verify` | The public key reports are signed with; check a text report. Public. |
| `/watches`, `/alerts` | Watch an address; alerts when funds leave it. |
| `/requests`, `GET /trace/{id}/requests` | Freeze requests sent about a case and their status. |
| `/batches` | Trace up to 25 complaints and correlate them. |

## Who sees what

There are no accounts. Each browser sends a random owner key
(`X-Exchequer-Owner`); cases, watches, alerts, freeze requests and batches
belong to the key that made them, stored as its SHA-256. Demo cases (stored
before ownership existed, address in `backend/data/demo_traces.json`) are
public. A case id or job id is random and works as the permission to read
that one case or job. See `backend/app/ownership.py` and `SECURITY.md`.

Clearing a browser's site data loses its history list (the cases remain and
open by link). Moving to real accounts later means mapping owner hashes to
users; nothing else changes.

## Deploying

`railway up` uploads the working directory, not the last commit, so deploy
from a clean checkout when the tree has uncommitted work:

```sh
git worktree add /tmp/exchequer-deploy main
cd /tmp/exchequer-deploy && railway up --detach
cd - && git worktree remove /tmp/exchequer-deploy
```

On first start after the October changes the store gains its new column and
tables by itself, and a signing key is created on the volume. Check
`/health`, `/signing-key` and one stored case afterwards. The CI job
"docker image builds and runs as non-root" builds and starts the image the
way Railway does before anything is deployed.

## Keys

If a provider key may have leaked, rotate it at the provider and update the
Railway variable. Before October the HTTP client logged request URLs, keys
included, so keys used before then should be rotated once.

If the signing key is replaced, reports signed with the old key stop
verifying at `/verify` (they still verify offline against the old public
key, if it was kept).
