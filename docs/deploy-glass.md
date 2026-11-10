# Deploy day: shipping the Glass redesign

A checklist for the owner. Work through it top to bottom and tick each box.
Everything here uses free tiers: Render free, Neon free, Vercel Hobby and
GitHub Actions.

What ships: the Glass UI and app shell, the five case tabs (Flow, Timeline,
Entities, Evidence, Letters), the victim-share flow (`backend/app/victim_flow.py`),
urgent freeze letters, officer payment search (`POST /payments/search`), the
second-provider recheck (`POST /trace/{id}/recheck`), the flow extras, and the
static citizen site in `citizen/`. Officer accounts, the audit log, the watch
cron and the citizen backend are still being built on other branches. Steps
that depend on them are marked **(coming with the … PRs)**. Do those steps
only after that PR has merged, and check the variable names against that PR's
own `render.yaml` and `docs/operations.md`.

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

- [ ] GitHub → Settings → Branches → the `main` rule → required status checks:
      add **`accessibility (WCAG 2.2 AA)`** and **`citizen site tests + build`**.
      Both jobs are new in this redesign. Until you add them they run, but a red
      result does not block a merge. Today the required checks are `backend
      tests`, `migrations on Postgres`, `frontend tests + build`, `docker image
      builds and runs as non-root` and `commit e-mails`. Add the two new ones
      only after the chain has merged, because a required check that a PR
      does not run blocks that PR.

## 2. Neon: a real database (needed before the accounts PRs)

Today `DATABASE_URL` is blank on Render. The case store is then a SQLite file
on Render's temporary disk, so every stored case is lost when the free instance
sleeps (15 idle minutes). The recorded demos are not affected: they come from
files in the image. Accounts, the audit log and citizen complaints all need a
store that lasts, so set up Neon before those PRs merge. You can do it before
or after the Glass chain merges. Doing it a day earlier, on the build that is
live now, means one change at a time.

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
         line per migration after it, ending with `… -> g4_recheck_1` once the
         Glass chain is in (only the first time, on the empty database);
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

### 3.2 New in the redesign: nothing to set

The redesign adds three limits for the second-provider recheck, all in
`backend/app/config.py` with safe defaults. None is in `render.yaml`, and you
do not need to set them:

| Variable | Default | What it limits |
|---|---|---|
| `EXCHEQUER_RECHECKS_PER_HOUR` | 6 | Rechecks one connection may run per hour. |
| `EXCHEQUER_RECHECKS_PER_HOUR_TOTAL` | 30 | Rechecks the whole site may run per hour. |
| `EXCHEQUER_MAX_RUNNING_RECHECKS` | 2 | Rechecks running at once. |

`POST /payments/search` and `POST /trace/{id}/recheck` are guarded like a live
trace (`access.GUARDED`). While the demo code is blank they are open, and they
spend provider quota under the same daily meters. The recheck reads TronScan
(with `TRONSCAN_API_KEY`) or the public Ethereum nodes, never Etherscan.

### 3.3 Coming with the accounts PRs

Names as planned. Confirm them against the accounts PRs' `render.yaml` when
they land.

| Variable | How it is set | Safe value | What it does |
|---|---|---|---|
| `EXCHEQUER_BOOTSTRAP_TOKEN` | `generateValue` | (generated) | Lets you create the **first admin** officer. `POST /auth/bootstrap` answers 404 when it is unset or once an admin exists. |
| `EXCHEQUER_CONSOLE` | `sync: false` | **`open`** (or blank, which means open) | `open`: anyone can trace live, as today. `officers`: live and spending actions (`POST /trace`, `/trace/jobs`, `/batches`, `/watches`, `/watches/{id}/check`, `/payments/search`, `/trace/{id}/recheck`, `/requests`, sign-off) need a signed-in officer. A demo code does not open them in that mode. Recorded demos, `/verify` and every read stay open in both modes. |

**The console switch stays open for the judges.** When Render's Manual sync
asks for `EXCHEQUER_CONSOLE`, enter `open`. Switch to `officers` only after the
judges have been told (step 7).

**First admin (the bootstrap flow)**, once the accounts PR is live:

1. [ ] Render → Blueprint → **Manual sync** so `EXCHEQUER_BOOTSTRAP_TOKEN` is
       generated. Copy it from Environment.
2. [ ] Call `POST /auth/bootstrap` once with that token and your e-mail, name
       and a password, exactly as the accounts PR's `docs/operations.md` shows
       (the state-changing auth routes also need its `X-Exchequer-Request`
       header). The token is never typed into the website.
3. [ ] Sign in at `/signin/investigator` as that admin. Change the password if
       asked, then create your unit and officers under **Admin**. Each new
       officer's temporary password is shown **once**.
4. [ ] Delete `EXCHEQUER_BOOTSTRAP_TOKEN` from Render → Environment. The
       endpoint is already dead once an admin exists; deleting the token also
       removes the secret.

### 3.4 Coming with the audit-log PR

No new variable. `GET /audit/verify` uses the existing
`EXCHEQUER_HEALTH_TOKEN` as a bearer token. After it lands, check:

```sh
curl -s -H "Authorization: Bearer <EXCHEQUER_HEALTH_TOKEN>" https://exchequer-6gnl.onrender.com/audit/verify
```

You should get `"ok": true`.

### 3.5 Coming with the watch-cron PR

| Where | Name | Value |
|---|---|---|
| Render | `EXCHEQUER_WATCH_CRON_TOKEN` | `generateValue`, made by Manual sync |
| GitHub environment `watch-cron` (deployment branches: `main` only) | secret `WATCH_CRON_TOKEN` | the same value as on Render |
| GitHub repository variable | `WATCH_CRON` | `on`, last, once the two above are set |

Leave `EXCHEQUER_WATCHER` at `0`. The cron replaces the in-process watcher,
which sleeps with the free instance.

## 4. The citizen site on Vercel

The static site (`citizen/`) can go live now. Its sign-in, "My case" and
complaint sending need the citizen backend **(coming with the citizen backend
PRs)**. Until then those pages say so.

### 4.1 Now: the static site

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
       with (`.github/workflows/test.yml`, job `citizen`).
5. [ ] No environment variables yet. Deploy.
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

### 4.2 Coming with the citizen backend PRs

The citizen backend adds Python functions in `citizen/api/` that share the Neon
database but log in as **their own role**, which can touch only the citizen
tables. The table and variable names below are from the plan. The PR's
`docs/citizen-deploy.md` is the final word; use its SQL if it differs.

1. [ ] Merge the citizen backend PR and **wait until Render has deployed it**:
       its migration creates the citizen tables, and you can only grant on
       tables that exist.
2. [ ] Neon → **SQL Editor**, as the owner role (`neondb_owner`):

       ```sql
       CREATE ROLE exchequer_citizen LOGIN PASSWORD '<long random password>';
       GRANT CONNECT ON DATABASE neondb TO exchequer_citizen;
       GRANT USAGE ON SCHEMA public TO exchequer_citizen;
       GRANT SELECT, INSERT, UPDATE ON
         complaints, complaint_payments, complaint_messages,
         tracking_codes, citizen_sessions, citizen_attempts
         TO exchequer_citizen;
       -- If those tables use serial ids, the role also needs their sequences:
       -- GRANT USAGE ON SEQUENCE <table>_id_seq TO exchequer_citizen;  (one per table)
       ```

       Make the password with `python3 -c 'import secrets;print(secrets.token_urlsafe(24))'`.
       Do **not** grant anything on `cases`, `freeze_requests`, `watches` or any
       other table. Do not use `ALL TABLES`.
3. [ ] Prove the role cannot read officer data. Still in the SQL Editor:

       ```sql
       SET ROLE exchequer_citizen;
       SELECT 1 FROM cases LIMIT 1;        -- must fail: permission denied for table cases
       SELECT count(*) FROM complaints;    -- must work
       RESET ROLE;
       ```

4. [ ] Neon → Connect → role `exchequer_citizen`, direct (pooling off) → copy
       the string.
5. [ ] Vercel → `exchequer-citizen` → Settings → Environment Variables:
       `CITIZEN_DATABASE_URL` = that string (Production and Preview). Add any
       other variable the PR's `docs/citizen-deploy.md` lists.
6. [ ] Settings → Functions → **Function Region: Singapore (`sin1`)**, next to
       Neon and Render (unless the PR's `vercel.json` already sets `regions`).
7. [ ] Redeploy, then run the CSP check (4.1 step 7) again: the functions are
       on the same address, so `default-src 'self'` still covers them.

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
| `WATCH_CRON` | `on` | **Coming with the watch-cron PR** (step 3.5). |

Settings → **Environments** (each with deployment branches = `main` only):

| Environment | Holds | Used by |
|---|---|---|
| `live-checks` (exists) | secret `DEMO_CODE`, only once you set a demo code | Demo health |
| `backup` (exists) | secret `NEON_BACKUP_URL` (the read-only `exchequer_backup` role's direct string; the SQL is in `docs/operations.md` → Backups), variable `BACKUP_AGE_RECIPIENT` (= `.github/backup-recipient.txt`) | Store backup |
| `lists` (exists) | secrets `ETHERSCAN_API_KEY` (a CI-only key, never Render's), optionally `NODEREAL_API_KEY`, `TRONGRID_API_KEY` | Refresh lists |
| `list-publish` (exists) | variable `LIST_BOT_APP_ID`, secret `LIST_BOT_KEY` (optional) | Refresh lists |
| `watch-cron` (new) | secret `WATCH_CRON_TOKEN` | **Coming with the watch-cron PR** |

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
       - the "At an exchange" card says **959.58** USDT at **Binance**
         (`Binance-Hot 7 · 959.58`);
       - the heading reads **9.7% can be acted on**;
       - "Where tracing stopped" lists the 2-hop limit (8,732.34), the fan-out
         limit at TZ7L…9cNz (196.78) and the exchange (959.58).
3. [ ] **Letters.** On the Letters tab, the list starts with **Urgent freeze
       request to Binance**, then **Urgent freeze request to Tether**, before
       the two information letters. Every draft carries its DRAFT line. On the
       Flow tab, **Draft letter to Binance** opens the urgent freeze letter.
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

### Rolling back

Fixing forward (a small PR, merged) is usually quicker and always safe. If the
site is broken for the judges **now**:

1. [ ] Render → `exchequer` → **Events** → the last good deploy (the one you
       noted in step 0) → **Rollback**. Render serves the old image within a few
       minutes. After a rollback, check Settings → **Auto-Deploy**. If Render
       has turned it off, turn it back on once `main` is fixed, or the next
       merge will not deploy.
2. [ ] **If the database is Neon, roll the schema back too.** The redesign adds
       a migration (`g4_recheck_1`, the `cases.recheck_json` column), and each
       accounts, audit or citizen PR will add more. An older build cannot start
       its store on a database a newer build migrated. Its startup
       `alembic upgrade head` fails with `Can't locate revision identified by
       'g4_recheck_1'`, and it keeps logging `Case store unavailable`: stored
       cases stop opening, although the recorded demos still work. Fix it from
       your laptop, in a checkout of the **newer** code (only it knows how to
       undo its own migrations), with the Neon owner string:

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

       A downgrade throws away what the undone migrations added. For
       `g4_recheck_1` that is only the kept rechecks. For the accounts or
       citizen migrations it will be officers and complaints, so think twice,
       and take a Store backup run first.
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

- setting `EXCHEQUER_CONSOLE=officers` (coming with the accounts PRs), which
  limits live tracing to signed-in officers;
- setting `EXCHEQUER_DEMO_CODE`, which asks for a code before a live trace.
  For the order of that change (the `live-checks` secret first, then Render,
  then `EXCHEQUER_REQUIRE_DEMO_CODE=1`, then `EXPECT_DEMO_CODE=1`), see
  `docs/operations.md` → A public demo.

In both cases the recorded demos stay open.
