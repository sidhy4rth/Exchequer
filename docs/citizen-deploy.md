# Deploying the citizen site

The citizen site (`citizen/`) is its own Vercel project with its own
address: static pages built with Vite, plus Python functions in
`citizen/api/` that take complaints and let a citizen sign in to read their
own case. It shares the free Neon Postgres with the main app, but connects as
a role of its own that can touch only the six citizen tables.

What a citizen can and cannot reach:

- They send a complaint (text details and payments only; screenshots never
  leave their device). It goes into the officers' review queue.
- They sign in with their NCRP number and the tracking code shown once when
  they sent it. They see a coarse status, what they sent, and the messages an
  officer chose to send. They can reply.
- They can look up one payment by its hash: from, to, amount, token and
  time, and nothing after it.
- They never see where money went, exchanges, labels, flags, watchlists,
  other complaints, letters or hit rates. A wallet two complaints paid, or a
  wallet a stored case reported, is tagged in `complaints.wallet_match` for
  officers only.
- No SMS and no e-mail are sent.

## 1. The tables

The main app's migrations own the schema (`backend/migrations`, revision
`g6_citizen_1`; the tables are described in `backend/app/complaints.py`).
They are created when the main app next starts on the Neon database, or by
hand:

```sh
cd backend && DATABASE_URL='<the owner URL from Neon>' alembic upgrade head
```

## 2. The citizen role

Run this once in Neon's SQL editor, as the database owner, after step 1. It
is `citizen/api/citizen_role.sql`; CI runs it on Postgres and checks the
role can do the citizen flow and nothing else
(`backend/scripts/check_citizen_role.py`).

```sql
-- The citizen functions' own database role: it reads and writes the six
-- citizen tables and nothing else -- no cases, letters, labels or watches,
-- and no DELETE anywhere. Run once, as the database owner, after the main
-- app has migrated (the tables must exist). Its password is set apart from
-- this file (docs/citizen-deploy.md).
CREATE ROLE exchequer_citizen LOGIN NOINHERIT CONNECTION LIMIT 20;
GRANT USAGE ON SCHEMA public TO exchequer_citizen;
GRANT SELECT, INSERT ON complaints, complaint_payments, complaint_messages, tracking_codes, citizen_sessions, citizen_attempts TO exchequer_citizen;
GRANT UPDATE (wallet_match, updated_at) ON complaints TO exchequer_citizen;
GRANT UPDATE (expires_at) ON citizen_sessions TO exchequer_citizen;
GRANT UPDATE (count, first_at, last_at) ON citizen_attempts TO exchequer_citizen;
```

Then give it a password, apart from that file, and keep it only in Vercel:

```sql
ALTER ROLE exchequer_citizen PASSWORD '<paste a long random one>';
```

A long random password: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
Neon refuses short ones.

The role gets SELECT and INSERT on the six tables, and UPDATE on only the
columns the functions change (the wallet-match tag, a session's expiry, the
attempt counters). It has no DELETE, no TRUNCATE, cannot create tables, and
cannot read `cases`, `watches`, `alerts`, `freeze_requests` or anything else.
A new table the main app adds later is not granted to it.

## 3. The Vercel project

Create a new project from the same GitHub repository:

| Setting | Value |
|---|---|
| Root Directory | `citizen` |
| Framework preset | Vite (from `citizen/vercel.json`) |
| Install / build | `npm ci --ignore-scripts` / `npm run build` (from `vercel.json`) |
| Function region | Singapore, `sin1` (`"regions"` in `vercel.json`; the closest to India on the free plan) |
| Python | 3.12, with `citizen/api/requirements.txt` |

Environment variables (Production and Preview):

| Variable | Value |
|---|---|
| `CITIZEN_DATABASE_URL` | `postgresql://exchequer_citizen:<password>@<Neon pooled host>/<db>?sslmode=require`. Use Neon's pooled address (the host with `-pooler`): each request opens one short connection. |
| `CITIZEN_SECRET` | 32 or more random characters. It keys the hashes of NCRP numbers and connections in the attempt counters, so neither is stored as itself. Changing it starts every counter again. |

Without either, the functions answer "cannot take requests right now".

`citizen/api/requirements.txt` pins psycopg and what it needs with the same
versions and hashes as `backend/requirements.txt` (a test checks they still
match), so pip installs in hash-checking mode. The backend's whole lock is
not used: it would install FastAPI and the rest for functions that need only
the standard library and a Postgres driver.

`citizen/.vercelignore` keeps `api/tests` out of the deployment (every file
under `api/` would otherwise become a function). Shared code is in
`api/_lib/`, which Vercel never serves.

The site's content policy (`default-src 'self'`) needs nothing more: the
pages call only their own `/api/` addresses. The functions send
`Cache-Control: no-store` and refuse any request without the `X-Citizen: 1`
header or from another origin; session cookies are `__Host-`, HttpOnly,
Secure, SameSite=Strict and last 30 minutes.

## 4. Limits

Kept in `citizen_attempts` (`citizen/api/_lib/limits.py`):

| What | Limit |
|---|---|
| Complaints per connection | 5 a day |
| Complaints per NCRP number | 3 a day, 8 in all (sign-in checks all 8) |
| Sign-in requests per connection | 60 an hour |
| Wrong codes per NCRP number | 5 free, then 30 s, 60 s, 2 min ... up to 1 hour between tries |
| Wrong codes per connection | 10 free, then the same growing wait |
| Replies | 10 a day per complaint, 30 a day per connection |
| Payment lookups | 20 an hour per connection |

A day with no tries starts a counter again, so nobody is locked out for
good. A connection on IPv6 is counted by its /64, since it can take a new
address in it for every request. Bodies are capped (24 KB for a complaint,
4 KB otherwise) and every field is checked and capped.

The payment lookup reads TronScan's public API for Tron and public RPC nodes
for Ethereum, BNB Smart Chain, Polygon and Arbitrum, with no API key. A
lookup has 8 seconds in all (each read gets at most 6, and only the time
left), inside the functions' 15-second limit. When they do not answer it says "We could not check
this payment right now."

## 5. Testing locally

Tests run on SQLite, migrated by the main app's own migrations, and never
touch the network (the payment lookup is stubbed):

```sh
cd citizen/api && ../../backend/.venv/bin/python -m pytest -q tests
```

They need the backend's dev packages (`backend/requirements-dev.txt`) for
pytest and alembic. To try the functions by hand, run `vercel dev` in
`citizen/` with `CITIZEN_DATABASE_URL=sqlite:////tmp/citizen.db` (migrate
that file first: `cd backend && EXCHEQUER_DB_PATH=/tmp/citizen.db alembic
upgrade head`) and `CITIZEN_SECRET` set.

## 6. Officers

The main app reads the queue (`complaints`, `complaint_payments`,
`complaint_messages`). `app.complaints.flag_case_matches()` tags complaints
whose paid wallet is a stored case's reported address. An officer's reply is
a `complaint_messages` row with `sender = 'officer'`; only those, and the
citizen's own, are shown back.

A complaint comes in claimed by no unit. A signed-in officer sees their
unit's complaints and the unclaimed ones, and claims one for their unit
(`complaint_claims`, officers only: the citizen role is never granted it)
before changing its status, replying or linking a case; then no other unit
sees it.
