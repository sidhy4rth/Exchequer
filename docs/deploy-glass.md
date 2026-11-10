# Deploy day: shipping the Glass redesign

A checklist for the owner. Work through it top to bottom and tick each box.
Everything here uses free tiers: Render free, Neon free, Vercel Hobby and
GitHub Actions.

What ships: the Glass UI and app shell, the five case tabs (Flow, Timeline,
Entities, Evidence, Letters), the victim-share flow (`backend/app/victim_flow.py`),
urgent freeze letters, officer payment search (`POST /payments/search`, also
from New trace's "I don't have the payment hash"), the second-provider recheck
(`POST /trace/{id}/recheck`), the flow extras, instant exchangers, and:

- **officer accounts**: units, officers, supervisors and admins, an Admin page,
  and a unit's own per-officer limits (`backend/app/accounts.py`);
- **case references** and per-officer hourly and daily limits for a signed-in
  officer's traces, watches, rechecks and checks (`backend/app/case_refs.py`);
- **second-officer sign-off** of every urgent freeze letter;
- the owner's **console switch** (`EXCHEQUER_CONSOLE`);
- the hash-chained **audit log** (`backend/app/audit.py`, `GET /audit/verify`);
- the **watch cron** (`.github/workflows/watch-cron.yml`, `POST /watches/check-due`);
- the **citizen site** in `citizen/` with its backend in `citizen/api/`, and
  the officers' **Complaints** queue, where each complaint is claimed by a unit.

Everything is in one stack and needs nothing merged later. The order below
matters: Neon (step 2) comes **before** the merge, because accounts,
sign-offs, the audit log and complaints must outlast the free instance's sleep.

Two rules for the whole day:

- **The site stays up.** Judges open it at any time. Nothing below takes it
  down, and the console stays open (step 3.3).
- **Every merge to `main` deploys.** `render.yaml` sets `autoDeployTrigger:
  commit`, so Render builds and deploys each commit on `main` a few minutes
  after it lands.

---

## 0. The night before (10 minutes)

- [ ] In the Render dashboard, open the `exchequer` service and go to
      **Events**. Note the commit of the deploy that is live now (today
      `011b176`). That is your rollback point.
- [ ] Open `https://exchequer-6gnl.onrender.com/health` and check that `build`
      says the same commit.
- [ ] Neon is set up and live on the current build (step 2), so the merge
      starts on a store that lasts.
- [ ] GitHub → your avatar → Settings → Emails: **Keep my email addresses
      private** must be on. A merge commit made in the browser then carries
      your noreply address, which the `commit e-mails` check requires.

## 1. Merging the PR chain

The redesign arrives as a chain of pull requests, each one built on the one
before it. Merge them **in the order they are listed** in the chain (the first
PR's base is `main`, and each later PR's base is the PR before it).

For each PR, in order:

1. [ ] Check that every CI check on the PR is green. Branch protection refuses
       a red PR anyway.
2. [ ] Merge with **Create a merge commit**. Never squash or rebase: the later
       PRs in the chain are built on these exact commits, and a squash makes
       GitHub show them as conflicting.
3. [ ] If the next PR's base still names the branch you just merged, edit it
       to `main` (GitHub usually does this for you when the merged branch is
       deleted).
4. [ ] **Wait for that deploy to go live before you merge the next PR.**
       Reload `/health` until `build` shows the first 12 characters of the
       merge commit (Render takes about 5 to 10 minutes on the free plan). The
       **Site canary** workflow starts on every push to `main` and waits up to
       15 minutes for exactly that commit. If you merge the next PR before
       that, the earlier canary run can go red only because a newer commit
       replaced its commit. Waiting also tells you which merge broke
       something, if one does.

After the last merge:

- [ ] Render → Blueprints → the Exchequer Blueprint → **Manual sync**. It
      generates `EXCHEQUER_BOOTSTRAP_TOKEN` and `EXCHEQUER_WATCH_CRON_TOKEN`,
      and asks for `EXCHEQUER_CONSOLE`: enter **`open`** (step 3.3).
- [ ] GitHub → Settings → Branches → the `main` rule → required status checks:
      add **`accessibility (WCAG 2.2 AA)`** and **`citizen site tests + build`**.
      Both jobs are new in this redesign. Until you add them they run, but a red
      result does not block a merge. Today the required checks are `backend
      tests`, `migrations on Postgres`, `frontend tests + build`, `docker image
      builds and runs as non-root` and `commit e-mails`. Add the two new ones
      only after the chain has merged, because a required check that a PR
      does not run blocks that PR.

## 2. Neon: a real database (before the merge)

Today `DATABASE_URL` is blank on Render. The case store is then a SQLite file
on Render's temporary disk, so every stored case is lost when the free instance
sleeps (15 idle minutes). The recorded demos are not affected: they come from
files in the image. Officer accounts, sign-offs, the audit log and citizen
complaints all live in that store, so on SQLite the first admin, every officer
and every complaint would vanish at the first sleep. Set up Neon **before** the
merge, a day earlier if you can, on the build that is live now: one change at a
time. The citizen site's functions (step 4) use the same Neon database.

1. [ ] [neon.tech](https://neon.tech) → sign up (free plan) → **New project**.
       - Name: `exchequer`
       - Region: **AWS Asia Pacific (Singapore)**. It is the same region as the
         Render service, and you cannot change it later.
       - Leave the Postgres version at its default, and note the number. The
         nightly backup assumes 17 (step 5).
2. [ ] Project dashboard → **Connect**. Pick the default branch, the default
       database (`neondb`) and its owner role. **Turn connection pooling
       off** (the direct string, whose host has no `-pooler`). The app keeps
       its own pool of at most 10 connections (`models.POSTGRES_ENGINE_OPTIONS`),
       and the backup role below also uses a direct string. Copy the whole
       string, `postgresql://…neon.tech/neondb?sslmode=require…`. The app
       accepts both `postgres://` and `postgresql://` (`models._postgres_url`).
3. [ ] Render → `exchequer` → **Environment** → `DATABASE_URL` → paste it →
       **Save and deploy**. (It is already declared in `render.yaml` with
       `sync: false`, so it only needs a value.)
4. [ ] Render → **Logs**, while it deploys. On startup the app runs
       `alembic upgrade head` itself (`models.init_db`, called from
       `main._open_store`). There is no separate migration step. You should see:
       - `INFO alembic.runtime.migration: Running upgrade  -> 0001, …` and one
         line per migration after it (only the first time, on the empty
         database). On the build that is live today it ends with
         `… -> sec7_cap_4`. After the merge, the next start adds eight, in
         this order: `g4_recheck_1`, `g5_accounts_1`, `g5_signoff_1`,
         `g6_unit_limits_1`, `g5_audit_1`, `g6_citizen_1`, `g6_queue_1`,
         `g6_queue_2`. Each one only adds tables or columns;
       - `INFO app.models: Case store ready on postgresql at ep-….neon.tech`.
       This line is the one that matters.

       Warning signs:
       - `ERROR app.main: Case store unavailable: OperationalError: …`. The
         site still starts, without its store, and retries every 60 seconds.
         It logs `Case store reachable again` once it gets through. Usually
         this is a typo in the string, or the pooled string. Fix the variable
         and save again.
       - `Can't locate revision identified by '…'`. The database is ahead of
         the code. See **Rolling back** in step 6.

       Expected, not a problem: `ERROR app.access: THIS PUBLIC SITE IS OPEN: …`.
       That is the open console the judges use (step 3.3).
       `WARNING app.webhook_vault` or provider-key warnings are as today.
5. [ ] Check it from outside. Copy `EXCHEQUER_HEALTH_TOKEN` from Render →
       Environment, then:

       ```sh
       curl -s -H "Authorization: Bearer <EXCHEQUER_HEALTH_TOKEN>" \
         https://exchequer-6gnl.onrender.com/health/detail | python3 -m json.tool | grep -A3 case_store
       ```

       `"engine": "postgresql"` and `"temporary": false` mean cases now last.
       (`render.yaml` generates this token. If the call answers 404, the token
       is not set on the service. Render → Blueprint → **Manual sync**.)
6. [ ] Neon keeps the free plan's database small. The app caps stored results
       at 300 MB by default (`EXCHEQUER_MAX_STORED_BYTES`), well inside Neon's
       0.5 GB. Leave Neon's scale-to-zero on (the default) so idle hours cost
       nothing. The first request after a pause waits about a second while
       Neon wakes. Every connect gives up after 5 s and is retried, so a slow
       wake never hangs the site.

## 3. Render environment variables

`render.yaml` is the list of what the service is given. Two things to know:

- `generateValue: true`: Render makes a random value itself. You never type
  it. Read it in Environment when you need it.
- `sync: false`: Render asks you for the value. Blank is allowed.

A variable added to `render.yaml` **after** the service was created does not
reach it by itself. After a PR that adds one merges, go to Render → Blueprints
→ the Exchequer Blueprint → **Manual sync** (it generates the new
`generateValue` keys and asks for the new `sync: false` ones), or add it by
hand in Environment.

### 3.1 Already there, unchanged by the redesign

| Variable | How it is set | Note |
|---|---|---|
| `ETHERSCAN_API_KEY`, `NODEREAL_API_KEY`, `TRONGRID_API_KEY`, `TRONSCAN_API_KEY` | `sync: false` (you) | Provider keys, as today. |
| `DATABASE_URL` | `sync: false` (you) | Step 2. |
| `EXCHEQUER_SIGNING_KEY` | `generateValue` | Never change it: reports signed with it stop verifying. |
| `EXCHEQUER_HEALTH_TOKEN` | `generateValue` | Bearer token for `/health/detail` (and later `/audit/verify`). |
| `EXCHEQUER_WEBHOOK_KEY` | `generateValue` | Seals watch webhooks. Changing it means officers re-enter them. |
| `EXCHEQUER_DEMO_CODE` | `sync: false`, **leave blank** | Blank keeps live tracing open for the judges. |
| `EXCHEQUER_TRUST_PROXY` = `render`, `EXCHEQUER_PROXY_HOPS` = `3`, `EXCHEQUER_WARM_CACHE` = `0`, `EXCHEQUER_WATCHER` = `0`, `EXCHEQUER_BACKUPS` = `0` | fixed values in `render.yaml` | Leave as they are. |
| Secret File `label_store_token` | Render → Settings → Secret Files | Already set. The Docker build fails without it, and the old deploy stays up. |

### 3.2 New limits: nothing to set

The redesign adds limits with safe defaults, all in `backend/app/config.py`.
None is in `render.yaml`, and you do not need to set them:

| Variable | Default | What it limits |
|---|---|---|
| `EXCHEQUER_RECHECKS_PER_HOUR` | 6 | Rechecks one connection may run per hour. |
| `EXCHEQUER_RECHECKS_PER_HOUR_TOTAL` | 30 | Rechecks the whole site may run per hour. |
| `EXCHEQUER_MAX_RUNNING_RECHECKS` | 2 | Rechecks running at once. |
| `EXCHEQUER_OFFICER_TRACES_PER_HOUR` / `_PER_DAY` | 20 / 80 | Live traces one signed-in officer starts (batch rows and payment searches count as traces). |
| `EXCHEQUER_OFFICER_WATCHES_PER_HOUR` / `_PER_DAY` | 10 / 40 | Watches one officer adds. |
| `EXCHEQUER_OFFICER_RECHECKS_PER_HOUR` / `_PER_DAY` | 6 / 24 | Rechecks one officer runs. |
| `EXCHEQUER_OFFICER_CHECKS_PER_HOUR` / `_PER_DAY` | 30 / 120 | A watch's Check now, per officer. |
| `EXCHEQUER_WATCH_CRON_BATCH` | 10 | Due watches one scheduled call checks (step 3.5). |

An admin can give a unit its own officer limits on the Admin page (each
unit's **Limits** button) instead of changing these. The per-connection and
site-wide limits still apply on top.

`POST /payments/search` and `POST /trace/{id}/recheck` are guarded like a live
trace (`access.GUARDED`). While the demo code is blank they are open, and they
spend provider quota under the same daily meters. The recheck reads TronScan
(with `TRONSCAN_API_KEY`) or the public Ethereum nodes, never Etherscan.

### 3.3 Accounts and the console switch

Both are in `render.yaml`, so the Manual sync after the merge offers them:

| Variable | How it is set | Safe value | What it does |
|---|---|---|---|
| `EXCHEQUER_BOOTSTRAP_TOKEN` | `generateValue` | (generated) | Lets you create the **first admin** officer. `POST /auth/bootstrap` answers 404 when it is unset or once an admin exists. |
| `EXCHEQUER_CONSOLE` | `sync: false` | **`open`** (or blank, which means open) | `open`: anyone can trace live, as today. `officers`: every live or spending action (`POST /trace`, `/trace/jobs`, `/batches`, `/payments/search`, `/watches`, `/watches/{id}/check`, `/requests`, `/trace/{id}/recheck`, a sign-off, stopping a job, and a complaint's claim, status, reply or case link) needs a signed-in officer, and answers anyone else 403 "Sign in as an officer to trace live." A demo code does not open them in that mode. Recorded demos, `/verify`, the citizen site and every read stay open in both modes. `/health` and `/access` say which mode is on (`"console"`). |

**The console switch stays open for the judges.** When Render's Manual sync
asks for `EXCHEQUER_CONSOLE`, enter `open`. Switch to `officers` only after the
judges have been told (step 7).

**First admin (the bootstrap flow)**, once the merge is live:

1. [ ] Render → Blueprint → **Manual sync** so `EXCHEQUER_BOOTSTRAP_TOKEN` is
       generated. Copy it from Environment. It is never typed into the website.
2. [ ] On your laptop, put the request body in a file, so the token and the
       password stay out of your shell history, and send it once. The
       password needs 12 or more characters; `unit` names your own unit, which
       the call creates.

       ```sh
       cat > /tmp/bootstrap.json            # paste the line below, then Ctrl+D
       {"token": "<EXCHEQUER_BOOTSTRAP_TOKEN>", "email": "<your e-mail>", "name": "<your name>", "unit": "<your unit>", "password": "<a password of 12+ characters>"}

       curl -s -X POST https://exchequer-6gnl.onrender.com/auth/bootstrap \
         -H 'Content-Type: application/json' -H 'X-Exchequer-Request: 1' \
         --data @/tmp/bootstrap.json; echo
       rm /tmp/bootstrap.json
       ```

       It answers your new account (`"role": "admin"` and your unit). A 404
       means the token is not on the service yet, or an admin already exists;
       a 403, a wrong token; a 422, a field it refused (it names which).
3. [ ] Open `https://exchequer-6gnl.onrender.com/signin/investigator`, click
       to enter, and sign in with that e-mail and password. The sidebar shows
       your name and unit, and an **Admin** group.
4. [ ] **Admin** → add the units you need, then each officer (name, e-mail,
       unit, role). Each new account's temporary password is shown **once**,
       with Copy: hand it over in person or by phone. The officer chooses their
       own password at first sign-in. A unit's **Limits** button sets its
       own per-officer limits (step 3.2); leave them at the defaults to start.
5. [ ] Optional: delete `EXCHEQUER_BOOTSTRAP_TOKEN` from Render → Environment.
       The endpoint stays closed while an admin exists either way; a later
       Manual sync may generate a new value, which is harmless.

What a signed-in officer meets that a demo user does not: a **Case
reference** box (FIR, NCRP or GD number) before any live trace, payment
search, watch or recheck, their own hourly and daily limits, and the
**Second officer** card on an urgent freeze letter. A freeze letter is
"ready" only once a second officer or supervisor of the same unit signs it
off; until then it says it is awaiting approval and cannot be marked as sent.
Demo users, and the judges, see none of this change: they can still read and
copy every letter.

### 3.4 The audit log

No new variable. Every trace, export, letter, watch, sign-off, account change
and complaint action is a row, recorded as `officer:<id>` with the unit's id
for a signed-in officer and as the browser otherwise. `GET /audit/verify`
uses the existing `EXCHEQUER_HEALTH_TOKEN` as a bearer token. After the merge,
check:

```sh
curl -s -H "Authorization: Bearer <EXCHEQUER_HEALTH_TOKEN>" https://exchequer-6gnl.onrender.com/audit/verify
```

You should get `"ok": true`.

### 3.5 The watch cron

The **Watch checks** workflow (`.github/workflows/watch-cron.yml`) wakes the
site every 15 minutes and calls `POST /watches/check-due` with a bearer token,
which checks at most `EXCHEQUER_WATCH_CRON_BATCH` due watches. Set it up in
this order:

| Step | Where | Name | Value |
|---|---|---|---|
| 1 | Render | `EXCHEQUER_WATCH_CRON_TOKEN` | `generateValue`, made by the Manual sync. Unset, the endpoint answers 404. |
| 2 | GitHub → Settings → Environments → new `watch-cron` (deployment branches: `main` only) | secret `WATCH_CRON_TOKEN` | the same value as on Render |
| 3 | GitHub → Actions → **Watch checks** → Run workflow on `main` | | it must go green ("Checked (HTTP 200)") |
| 4 | GitHub repository variable | `WATCH_CRON` | `on`, last: the 15-minute schedule starts |

Leave `EXCHEQUER_WATCHER` at `0`. The cron replaces the in-process watcher,
which sleeps with the free instance. Each run wakes the instance, which
counts against Render's free hours; with `WATCH_CRON` unset nothing runs.

## 4. The citizen site on Vercel

The citizen site (`citizen/`) is its own Vercel project: static pages, plus
Python functions in `citizen/api/` that take complaints, sign a citizen in with
their NCRP number and tracking code, and look up one payment. The functions
share the Neon database but log in as **their own role**, which can touch only
the six citizen tables. `docs/citizen-deploy.md` is the reference; this step is
the order to do it in. Do it **after** the merge has deployed on Render with
Neon: the main app's migrations create the citizen tables, and you can only
grant on tables that exist.

### 4.1 The project

1. [ ] [vercel.com](https://vercel.com) → **Add New… → Project** → import
       `sidhy4rth/Exchequer`.
2. [ ] Project name: `exchequer-citizen` (it gives you
       `exchequer-citizen.vercel.app`; if that is taken, pick another and use
       it everywhere below).
3. [ ] **Root Directory: `citizen`**. Framework preset: Vite. Leave the build
       settings alone, because `citizen/vercel.json` sets them (`npm ci
       --ignore-scripts`, `npm run build`, output `dist`, and the security
       headers).
4. [ ] Settings → General → **Node.js Version: 24.x**, the version CI tests
       with (`.github/workflows/test.yml`, job `citizen`). The functions run
       on Python 3.12 with `citizen/api/requirements.txt`, and in Singapore
       (`sin1`), next to Neon and Render: `citizen/vercel.json` sets the
       region.
5. [ ] Do not deploy yet: first the database role and the two variables
       (4.2). Without them the pages work, but sending a complaint, signing in
       and the payment lookup say they "cannot take requests right now".
6. [ ] **Domain**: keep the free `*.vercel.app` address. A custom domain is
       optional, under Settings → Domains. Never use a name that looks like a
       police or government site. The pages say plainly what Exchequer is.
7. [ ] **Strict CSP check.** `citizen/vercel.json` sends
       `default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`.

       ```sh
       curl -sI https://exchequer-citizen.vercel.app/ | grep -i -E 'content-security-policy|x-content-type|referrer-policy|permissions-policy'
       curl -s -o /dev/null -w '%{http_code}\n' https://exchequer-citizen.vercel.app/learn   # 200 (deep links rewrite to index.html)
       ```

       Then open the site in Brave with DevTools → Console open. Visit `/`,
       `/right-now`, `/report`, `/report/pack` and `/learn`. There must be **no**
       "Refused to load" or "Content Security Policy" errors, and the fonts must
       be IBM Plex (they are served from the site itself, never inlined).
       In DevTools → Network, every request must go to the site's own
       address. On `/report/pack`, "save as PDF" uses the browser's print
       dialog; nothing is uploaded.
8. [ ] Vercel builds a preview for every pull request that touches the repo.
       That is fine and costs nothing on Hobby.

### 4.2 The citizen database role and variables

1. [ ] Check Render's log shows `… -> g6_queue_2` (step 2.4): the citizen
       tables exist.
2. [ ] Neon → **SQL Editor**, as the owner role (`neondb_owner`), run
       `citizen/api/citizen_role.sql` exactly as it is in the repository:

       ```sql
       CREATE ROLE exchequer_citizen LOGIN NOINHERIT CONNECTION LIMIT 20;
       GRANT USAGE ON SCHEMA public TO exchequer_citizen;
       GRANT SELECT, INSERT ON complaints, complaint_payments, complaint_messages, tracking_codes, citizen_sessions, citizen_attempts TO exchequer_citizen;
       GRANT UPDATE (wallet_match, updated_at) ON complaints TO exchequer_citizen;
       GRANT UPDATE (expires_at) ON citizen_sessions TO exchequer_citizen;
       GRANT UPDATE (count, first_at, last_at) ON citizen_attempts TO exchequer_citizen;
       ```

       Then give it a password, apart from that file:

       ```sql
       ALTER ROLE exchequer_citizen PASSWORD '<paste a long random one>';
       ```

       Make it with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
       Grant nothing else: no `ALL TABLES`, no DELETE, nothing on `cases`,
       `freeze_requests`, `watches`, `complaint_links` or `complaint_claims`
       (which unit claimed a complaint is for officers only). CI runs the same
       SQL on Postgres and checks the role can do the citizen flow and nothing
       else (`backend/scripts/check_citizen_role.py`).
3. [ ] Prove the role cannot read officer data. Still in the SQL Editor:

       ```sql
       SET ROLE exchequer_citizen;
       SELECT 1 FROM cases LIMIT 1;             -- must fail: permission denied for table cases
       SELECT 1 FROM complaint_claims LIMIT 1;  -- must fail too
       SELECT count(*) FROM complaints;         -- must work
       RESET ROLE;
       ```

4. [ ] Neon → Connect → role `exchequer_citizen` → copy the **pooled** string
       (the host with `-pooler`): each function call opens one short
       connection. (The main app on Render keeps the direct string, step 2.)
5. [ ] Vercel → `exchequer-citizen` → Settings → Environment Variables, for
       Production and Preview:
       - `CITIZEN_DATABASE_URL` = that string, as
         `postgresql://exchequer_citizen:<password>@<pooled host>/neondb?sslmode=require`;
       - `CITIZEN_SECRET` = 32 or more random characters
         (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`). It
         keys the hashes in the attempt counters; changing it later starts
         every counter again.
6. [ ] Deploy, then run the CSP check (4.1 step 7) again: the functions are on
       the same address, so `default-src 'self'` still covers them.
7. [ ] Send one test complaint from `/report/pack` with made-up details and
       note the reference and tracking code it shows **once**. Sign in at the
       site's sign-in page with that NCRP number and code: "My case" shows
       "Received". On the officers' site, **Complaints** lists it with the NCRP
       number masked and "Unclaimed"; open it, press **Claim for my unit**,
       reply, and the reply shows on the citizen's "My case". Then set its
       status to Closed.

## 5. GitHub: repository variables and environments

Settings → Secrets and variables → Actions → **Variables**. Today none is set.

| Variable | Set it to | When |
|---|---|---|
| `SITE_URL` | `https://exchequer-6gnl.onrender.com` | Optional: the workflows already default to it. Set it only if the site moves. |
| `EXPECT_HEALTH_TOKEN` | `1` | Now: makes the canary fail if `EXCHEQUER_HEALTH_TOKEN` ever drops off the service. |
| `EXPECT_WATCHER` | `0` | Now: makes the canary fail if the in-process watcher is ever switched on. |
| `EXPECT_DEMO_CODE` | `1` | **Not while the console is open.** Only after the demo code is set. |
| `STORE_BACKUP` | `on` | After Neon (step 2) **and** the `backup` environment below are set up, and one hand-started run is green. |
| `BACKUP_PG_MAJOR` | your Neon Postgres major version | Only if it is newer than 17. |
| `REFRESH_LISTS` | `on` | After the `lists` environment has its keys. |
| `WATCH_CRON` | `on` | Last, after the `watch-cron` environment and one green hand-started run (step 3.5). |

Settings → **Environments** (each with deployment branches = `main` only):

| Environment | Holds | Used by |
|---|---|---|
| `live-checks` (exists) | secret `DEMO_CODE`, only once you set a demo code | Demo health |
| `backup` (exists) | secret `NEON_BACKUP_URL` (the read-only `exchequer_backup` role's direct string; the SQL is in `docs/operations.md` → Backups), variable `BACKUP_AGE_RECIPIENT` (= `.github/backup-recipient.txt`) | Store backup |
| `lists` (exists) | secrets `ETHERSCAN_API_KEY` (a CI-only key, never Render's), optionally `NODEREAL_API_KEY`, `TRONGRID_API_KEY` | Refresh lists |
| `list-publish` (exists) | variable `LIST_BOT_APP_ID`, secret `LIST_BOT_KEY` (optional) | Refresh lists |
| `watch-cron` (new) | secret `WATCH_CRON_TOKEN` (step 3.5) | Watch checks |

Backup order, once Neon is live:

- [ ] Create the `exchequer_backup` role (`docs/operations.md` → Backups, step 1).
- [ ] Fill the `backup` environment.
- [ ] Actions → **Store backup** → Run workflow on `main`. It must go green and
      leave an artifact `store-<run id>`.
- [ ] Set `STORE_BACKUP` = `on`.

## 6. After each deploy: checks

Do these after the last merge of the chain (and quickly after any later
merge).

1. [ ] **Build.** `https://exchequer-6gnl.onrender.com/health` shows
       `"status": "ok"`, `"access": "open"` and a `build` equal to the first 12
       characters of the merge commit on `main` (`git rev-parse --short=12
       origin/main`).
2. [ ] **Demo 11, Flow tab.** Open `https://exchequer-6gnl.onrender.com/demo/11`
       (it opens on Flow). Check:
       - the "At an exchange" card says **up to 959.58** USDT at **Binance**
         (`Binance-Hot 7 · 959.58`): part of it came through wallets whose
         shares are only upper bounds, so it is never stated as fact;
       - the heading reads **6.4% can be acted on**, with "up to 9.7% counting
         money through wallets whose shares are only upper bounds" under it;
       - "Where tracing stopped" lists the 2-hop limit (8,732.34), the fan-out
         limit at TZ7L…9cNz (196.78) and the exchange (959.58).
3. [ ] **Letters.** On the Letters tab, the list starts with **Urgent freeze
       request to Binance**, then **Urgent freeze request to Tether**, before
       the two information letters. Every draft carries its DRAFT line, and
       an urgent one also says it awaits a second officer's approval. On the
       Flow tab, **Draft letter to Binance** opens the urgent freeze letter.
       The Binance information letter lists only the 2 transfers that can
       carry the traced funds, and says how many others it leaves out.
4. [ ] Glance at Timeline, Entities and Evidence on the same demo. Do **not**
       press "Re-read from a second provider" just to check: it is a real
       TronScan read and spends quota.
5. [ ] **Site canary.** Actions → **Site canary**: the run for the last push
       to `main` is green. It waits for that commit to go live, opens the
       console in a real browser and opens a stored case, and it never starts a
       trace. If it went red only because a later merge replaced its commit,
       run it again by hand (Run workflow).
6. [ ] **Demo health.** Actions → **Demo health** → Run workflow. It runs the
       `DEMO.md` traces against the live site through the API (these are real
       traces and spend a little quota) and must be green. It runs on its own
       every day at 07:00 IST.
7. [ ] **Accessibility.** Actions → **tests**, on the merge commit: the job
       **accessibility (WCAG 2.2 AA)** is green (axe on every page, both themes,
       desktop and phone), and so is **citizen site tests + build**.
8. [ ] Render → Logs: no `Case store unavailable`, no tracebacks.
9. [ ] **Accounts.** `/signin/investigator` signs your admin in; **Admin**
       lists your units and officers. Sign out from the sidebar.
10. [ ] **Audit log.** `GET /audit/verify` with the health token (step 3.4)
        answers `"ok": true`.
11. [ ] **Watch checks** (once `WATCH_CRON` is on): the latest scheduled run is
        green.
12. [ ] **Citizen site**: 4.1 step 7's checks, and Network shows only the
        site's own address, its `/api/` calls included.

### Rolling back

Fixing forward (a small PR, merged) is usually quicker and always safe. If the
site is broken for the judges **now**:

1. [ ] Render → `exchequer` → **Events** → the last good deploy (the one you
       noted in step 0) → **Rollback**. Render serves the old image within a few
       minutes. After a rollback, check Settings → **Auto-Deploy**. If Render
       has turned it off, turn it back on once `main` is fixed, or the next
       merge will not deploy.
2. [ ] **If the database is Neon, check the target before rolling back.** The
       redesign adds eight migrations, `g4_recheck_1` to `g6_queue_2` (step
       2.4). A build whose `init_db` logs "newer than this build: opened as it
       is" opens a store a later build migrated as it is, since migrations only
       add. Check the target with
       `git grep -c "newer than this build" <commit> -- backend/app/models.py`.
       If it prints nothing (as for `011b176`, today's live build), that build
       refuses a revision it has never seen: its startup fails with `Can't
       locate revision identified by 'g6_queue_2'`, and it keeps logging `Case
       store unavailable`: stored cases stop opening, although the recorded
       demos still work. Then roll the schema back too, from your laptop, in a
       checkout of the **newer** code (only it knows how to undo its own
       migrations), with the Neon owner string:

       ```sh
       cd ~/exchequer/backend          # a checkout of the newer commit
       DATABASE_URL='postgresql://…neon.tech/neondb?sslmode=require' \
         .venv/bin/python -m alembic downgrade sec7_cap_4
       ```

       `sec7_cap_4` is the last migration of `011b176`, today's live build. For
       a different rollback target, run `.venv/bin/python -m alembic heads` in
       a checkout of that target to get its revision. The rolled-back build
       retries its store every 60 seconds; within a minute the log says `Case
       store reachable again`. Do the Render rollback **first** and the
       downgrade second. The other way round, the newer build would run for a
       minute on a table missing the column it reads.

       A downgrade throws away what the undone migrations added: down to
       `sec7_cap_4` that is the kept rechecks, every unit, officer and session,
       the sign-offs, the audit log, and every citizen complaint, message,
       tracking code and claim. Think twice, take a Store backup run first, and
       tell the citizen site's users nothing is lost only if nothing was sent.
3. [ ] Make `main` match what is live: open a revert PR of the bad merge
       (GitHub → the merged PR → **Revert**), let CI pass, and merge it with a
       merge commit.

## 7. Telling the judges

**Nothing changes for them.** The link is the same, sign-in is the same
("click anywhere to enter", then the console), the recorded demos stay public
and open instantly, and live tracing stays open, because `EXCHEQUER_DEMO_CODE`
is blank and the console switch is `open`. They will see the new Glass look,
and a case opens on the Flow tab.

A message you can send:

> Exchequer has a new look today. Each case now opens on a Flow view of
> where the victim's money went, with tabs for the timeline, the wallets,
> the evidence and draft letters (urgent freeze letters first). Same link,
> no code needed, and the recorded demos work as before.

They must be told **before** either of these, and only on your decision:

- setting `EXCHEQUER_CONSOLE=officers` (step 3.3), which limits live tracing,
  watches, letters' sign-off and complaint work to signed-in officers;
- setting `EXCHEQUER_DEMO_CODE`, which asks for a code before a live trace.
  For the order of that change (the `live-checks` secret first, then Render,
  then `EXCHEQUER_REQUIRE_DEMO_CODE=1`, then `EXPECT_DEMO_CODE=1`), see
  `docs/operations.md` → A public demo.

In both cases the recorded demos stay open.
