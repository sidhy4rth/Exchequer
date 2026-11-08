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
| `DATABASE_URL` | — | A `postgres://` URL moves the case store to Postgres (needed on a host without a disk, such as Render's free plan). Unset, the store is the SQLite file above. The volume backups and `/admin/backup` apply to SQLite only; a Postgres store is copied off-site by the backup workflow (Backups). |
| `API_CACHE_PATH` | `provider_cache.db` beside the store | Provider response cache (24 h). `off` disables it. |
| `EXCHEQUER_SIGNING_KEY` | — | Base64 32-byte Ed25519 seed for signing reports. Without it a key is made on first start at `report_signing_key.pem` beside the store (mode 0600). |
| `EXCHEQUER_SIGNING_KEY_PATH` | `report_signing_key.pem` | Where that file lives. |
| `EXCHEQUER_MAX_RUNNING_TRACES` | 4 | Traces running at once, server-wide. |
| `EXCHEQUER_TRACES_PER_HOUR` | 30 | Traces one client may start per hour (a batch counts every row). `0` = no limit. |
| `EXCHEQUER_TRACE_MAX_ETHERSCAN_CALLS`, `_NODEREAL_CU`, `_TRONGRID_CALLS`, `_TRONSCAN_CALLS` | 600, 60000, 400, 100 | What one case (a trace and its follow-ons) may spend per provider, in requests (compute units on NodeReal). Past it the walk stops, marked truncated with the reason (`stopped_by: "budget"`). `0` = no limit. |
| `EXCHEQUER_ETHERSCAN_CALLS_PER_DAY`, `EXCHEQUER_TRONGRID_CALLS_PER_DAY`, `EXCHEQUER_TRONSCAN_CALLS_PER_DAY` | 60000, 50000, 20000 | What the whole site may spend per key in one UTC day: traces, watch checks and warm-ups together. Once spent, new traces on that chain get a 503 until 00:00 UTC. `0` = counted, not limited. `/health/detail` → `api_budget.meters` shows each key's spend (by digest). |
| `EXCHEQUER_NODEREAL_CU_PER_MONTH` / `EXCHEQUER_NODEREAL_CU_PER_DAY` | 10,000,000 / month × 0.9 ÷ 31 | NodeReal's monthly compute units, from the key's plan page; the daily allowance spreads 90% of it over the month. Set `_PER_DAY` to override. |
| `EXCHEQUER_CLIENT_SHARE_PERCENT` | 25 | The most of each day's allowance one connection may spend (`0` = no share). |
| `EXCHEQUER_DEMO_CODE` | — | Set, a live trace, a batch or a watch needs this code in the `X-Exchequer-Demo-Code` header; reading stays open. After 10 wrong codes in 15 minutes a client is refused (429), the right code included. The right code returns a pass (sent as `X-Exchequer-Demo-Pass`, valid `EXCHEQUER_DEMO_PASS_HOURS`, default 12) that is never locked out; changing the code revokes every pass. Use a long random value: `python -c 'import secrets;print(secrets.token_urlsafe(16))'`. Unset, nothing is guarded. See `backend/app/access.py`. |
| `EXCHEQUER_REQUIRE_DEMO_CODE` | off | Set once the code is in place: a deploy without `EXCHEQUER_DEMO_CODE` then refuses live tracing (503) instead of opening it. |
| `EXCHEQUER_PUBLIC` | on when Render or Railway says so | A public host without a demo code logs an error at every start. |
| `EXCHEQUER_WATCHES_PER_HOUR` | 20 | Watches one client may create per hour. `0` = no limit. |
| `EXCHEQUER_TRUST_PROXY` | `render` when Render sets `RENDER=true`, `1` on Railway, else off | Read the client address (the key of every per-client limit) from the proxy's headers. Only behind a proxy that sets them. `1`: `X-Real-IP`, else the last `X-Forwarded-For` entry (Railway). `render`: `EXCHEQUER_CLIENT_IP_HEADER` if the edge sent it, else entry `EXCHEQUER_PROXY_HOPS` from the right of `X-Forwarded-For`, else the leftmost entry (which a client can write; logged as a warning). `0` = never. |
| `EXCHEQUER_CLIENT_IP_HEADER` | `cf-connecting-ip` | In `render` mode, a header the edge sets to the connecting address and overwrites if the client sent one (Cloudflare's). `none` ignores it. |
| `EXCHEQUER_PROXY_HOPS` | 0 (not measured) | In `render` mode, how many proxies append to `X-Forwarded-For` after the client. Set it only from a measurement: `GET /health/detail` with `X-Exchequer-Probe-Me: <your public address>` answers `client_ip` with fingerprints (never addresses), whether each header equals you, and the value to set. Check from two networks. |
| `EXCHEQUER_API_DOCS` | on (off in the image) | `/docs`, `/redoc`, `/openapi.json`. |
| `EXCHEQUER_WATCHER` | off | Re-read watched addresses in the background. Only worth it on a host that stays awake: on one that sleeps when idle (Render's free plan) the watcher sleeps too, so on a temporary disk `1` is ignored and only `force` turns it on. The watchlist and `/health/detail` report the last check and call it stale after three missed intervals. |
| `EXCHEQUER_WATCH_INTERVAL` | 600 | Seconds between checks of one watch (minimum 60). |
| `EXCHEQUER_WEBHOOK_HOSTS` | — | Comma-separated hosts alert webhooks may post to, beyond Slack, Discord and Google Chat. |
| `EXCHEQUER_BACKUPS` | off | A daily snapshot of a SQLite store in `backups/` beside it. Ignored on a temporary disk (`force` overrides). |
| `EXCHEQUER_BACKUP_KEEP` | 7 | How many daily snapshots to keep. |
| `EXCHEQUER_BACKUP_TOKEN` | — | Bearer token for `GET /admin/backup`. Unset, the endpoint answers 404. |
| `EXCHEQUER_HEALTH_TOKEN` | — (`render.yaml` generates one) | Bearer token for `GET /health/detail`: key status, per-chain detail, API budget, warm-cache status, and under `runtime` which background jobs and proxy setting this instance actually runs with. Unset, the endpoint answers 404. Public `/health` says only `{"status": "ok"}` and `"access"` (`open`, `code` or `closed`); `/chains` is the public list of what the site can trace. |
| `EXCHEQUER_TEMPORARY_DISK` | on when Render sets `RENDER=true`, else off | Whether a restart wipes the disk. `/health/detail` → `storage` then marks a SQLite case store and the provider cache as temporary: on Render's free plan, an empty `DATABASE_URL` means every stored case is lost when the instance sleeps. `0` or `1` overrides the guess. |
| `EXCHEQUER_WARM_CACHE` | off | Trace the demo addresses at startup so they answer from cache. Ignored on a temporary disk or with the provider cache in memory only (`force` overrides). |

## Endpoints added in October 2026

| Endpoint | Purpose |
|---|---|
| `POST /trace/jobs`, `GET /trace/jobs/{id}`, `GET /trace/jobs/{id}/events` | Background trace with live progress (server-sent events). `POST /trace` still works and waits for the result. |
| `GET /trace/{id}/graph?format=graphml\|csv` | The case's transfer graph for Gephi, yEd, Maltego or a spreadsheet. |
| `GET /trace/{id}/report?format=pdf` | PDF report; the exact signed text is attached inside it. |
| `GET /signing-key`, `POST /verify` | The public key reports are signed with; check a text report, or an Exchequer PDF (its attached report, and whether its pages match it). Public. |
| `/watches`, `/alerts` | Watch an address; alerts when funds leave it. |
| `/requests`, `GET /trace/{id}/requests` | Freeze requests sent about a case and their status. |
| `/batches` | Trace up to 25 complaints and correlate them. |
| `GET /admin/backup` | A snapshot of a SQLite store, for a self-hosted off-site copy. Needs `EXCHEQUER_BACKUP_TOKEN`; 404 on Postgres. |

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

### Render (current host, since 26 Oct 2026)

`render.yaml` is a Blueprint for the free plan: Dashboard → New → Blueprint →
this repository. Render asks once for the provider keys and `DATABASE_URL`,
generates `EXCHEQUER_SIGNING_KEY` itself, and from then on deploys every push
to `main`. The free instance has no disk and sleeps after 15 idle minutes, so:

- the case store must be Postgres to keep anything: create a free project at
  neon.tech and paste its connection string as `DATABASE_URL`;
- the provider cache starts empty after each wake, and the warm-up is off
  (the recorded demos open instantly instead);
- the first visit after a sleep waits for the container to start; the
  monitoring workflows knock on `/health` before they check anything.

The image turns no background job on (watcher, snapshots, warm-up) and trusts
no proxy header: `render.yaml` sets what the service needs. Values added to
`render.yaml` after the service was created reach it only through a Blueprint
sync (Dashboard → the Blueprint → Manual sync) or by setting them by hand in
Environment; `/health/detail` shows what the instance runs with under
`runtime`, and the site canary fails when the health token or the watcher
setting has drifted.

The monitors read the site address from the repository variable `SITE_URL`
(`gh variable set SITE_URL --body https://<service>.onrender.com`).

### Railway (until October 2026)

`railway up` uploads the working directory, not the last commit, so deploy
from a clean checkout when the tree has uncommitted work. A new worktree is
not linked to a Railway project, and `railway up` in an unlinked folder
creates a new, empty project instead of deploying, so link it first:

```sh
git worktree add /tmp/exchequer-deploy origin/main
cd /tmp/exchequer-deploy
railway link --project <project id> --environment production --service exchequer
railway status            # must name the exchequer project before going on
railway up --detach
cd - && git worktree remove /tmp/exchequer-deploy
```

On first start after the October changes the store gains its new column and
tables by itself, and a signing key is created on the volume. Check
`/health`, `/signing-key` and one stored case afterwards. The CI job
"docker image builds and runs as non-root" builds and starts the image the
way Railway does before anything is deployed.

## A public demo

To put the site in front of the public without letting anyone spend the
provider quota, set `EXCHEQUER_DEMO_CODE` in Render's environment and the
same value as the secret `DEMO_CODE` of the GitHub environment `live-checks` (the Demo health job sends
it). Visitors then see the recorded demos, which open exactly as recorded,
and a box for the code; with it, the console traces as before. The code
stays in that browser tab only (`sessionStorage`) and is forgotten on sign
out. Share it with the people presenting, and change it after an event.
Order: set the `live-checks` environment secret `DEMO_CODE` first (`scripts/check_demos.py`
sends it), then `EXCHEQUER_DEMO_CODE` on Render with the same value, then
`EXCHEQUER_REQUIRE_DEMO_CODE=1` there too, and the repository variable
`EXPECT_DEMO_CODE=1` for the site canary. Until the code is set the site
stays open, and says so: every start logs `THIS PUBLIC SITE IS OPEN`, and
`/health` answers `"access": "open"` (`"code"` once set; `"closed"` if the
code is required but missing, when live tracing answers 503).

## Database schema

The schema lives in numbered Alembic migrations in `backend/migrations/`,
never in a hand-written `ALTER`. The app runs `alembic upgrade head` itself
at startup (`models.init_db`), so a deploy needs no extra step, on SQLite or
Postgres.

- **An existing store needs nothing done.** The baseline, `0001`, adopts any
  store an earlier build made: it creates only the tables, columns and
  indexes that are missing, and adds `cases.owner_hash` to a store older
  than ownership. Do **not** `alembic stamp` a store instead: on the oldest
  kind it would record a column without adding it.
- **The baseline cannot be downgraded.** Undoing it would drop every stored
  case; it raises instead.
- **Changing the schema** (from `backend/`): change `app/models.py`, then
  `alembic revision --autogenerate --rev-id 0002 -m "add x to y"`, read the
  generated file, and run `alembic upgrade head && alembic check`. Never edit
  a migration that has merged.
- **Two heads** (`alembic heads` prints two lines) means two branches each
  added a migration. The later one rebases, renumbers its `revision` and
  sets `down_revision` to the other. CI fails until there is one head.

CI runs the suite's migration tests on SQLite and the same migrations on a
real Postgres, including adopting a store made before migrations.

## Backups

The production store is Neon Postgres (`DATABASE_URL` on Render). Its
off-site copy is `.github/workflows/backup.yml`: every night at 03:00 IST it
runs `pg_dump --format=custom` against the database with a read-only role,
checks the archive holds the `cases` table, encrypts it with
[age](https://age-encryption.org) and keeps it as a workflow artifact for 14
days. The plain dump never leaves the runner, and the log prints no counts or
table contents. Until it is set up the job fails, so a night with no copy is
never green.

The dump holds every case, freeze request and alert webhook, so it is
encrypted to the public key in the `backup` environment's
`BACKUP_AGE_RECIPIENT` variable, which must equal `.github/backup-recipient.txt`
(the job refuses otherwise: a changed file cannot re-target the backups).
Only the matching private key (`~/.config/exchequer/backup-age-key.txt` on the
maintainer's machine -- keep a second copy offline) opens it. A new key pair
is `age-keygen -o <file>`, and `age-keygen -y <file>` prints the public half.

To switch the nightly copy on, once:

1. Neon console → SQL Editor, as the owner role, make a read-only role:

   ```sql
   CREATE ROLE exchequer_backup LOGIN PASSWORD '<long random password>';
   GRANT CONNECT ON DATABASE <database> TO exchequer_backup;  -- the name in DATABASE_URL
   GRANT USAGE ON SCHEMA public TO exchequer_backup;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO exchequer_backup;
   GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO exchequer_backup;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO exchequer_backup;
   ```

   Its connection string (Neon → Connect, role `exchequer_backup`, direct, not
   pooled) is `NEON_BACKUP_URL`.
2. GitHub → Settings → Environments → New environment `backup`. Deployment
   branches: selected, `main` only. Add the secret `NEON_BACKUP_URL` and the
   variable `BACKUP_AGE_RECIPIENT` (the contents of
   `.github/backup-recipient.txt`). If Neon's Postgres major version is newer
   than 17, set the repository variable `BACKUP_PG_MAJOR` to it.
3. Actions → Store backup → Run workflow (on `main`). It must be green with an
   artifact `store-<run id>`.

To restore (drill this once into a scratch Neon branch before relying on it):

```sh
age -d -i ~/.config/exchequer/backup-age-key.txt exchequer-<stamp>.pgdump.age > store.pgdump
pg_restore --no-owner --no-privileges --dbname="$SCRATCH_DATABASE_URL" store.pgdump
```

then point a local run at it (`DATABASE_URL=$SCRATCH_DATABASE_URL`) and open a
known case. To replace production, restore into a new Neon branch and switch
`DATABASE_URL` on Render to it. The signing key is not in the backup;
`EXCHEQUER_SIGNING_KEY` on Render keeps reports verifying.

A self-hosted SQLite store has two more copies: with `EXCHEQUER_BACKUPS` on (a
host with a lasting disk sets it) the server writes
`backups/exchequer-YYYY-MM-DD.db.gz` beside the store once a day and keeps the
last 7, and with `EXCHEQUER_BACKUP_TOKEN` set `GET /admin/backup` returns a
fresh snapshot for that host's own off-site job. Neither exists on a Postgres
store.

## Keys

If a provider key may have leaked, rotate it at the provider and update the
host's environment variable. Before October the HTTP client logged request URLs, keys
included, so keys used before then should be rotated once.

If the signing key is replaced, reports signed with the old key stop
verifying at `/verify` (they still verify offline against the old public
key, if it was kept).
