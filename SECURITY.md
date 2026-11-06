# Security

## Reporting a problem

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting on this repository (Security → Report a
vulnerability), and I will reply within a few days.

## What the deployed site protects, and what it does not

Exchequer has no accounts. What it does instead:

- **Cases are private to the browser that traced them.** Each browser sends a
  random owner key; the history list shows only that browser's cases plus the
  demo cases. A case id is a random UUID and a link to it works as the
  permission to read it, so share case links only with people who should see
  the case. Correlation reads only your own cases, the demo cases and the one
  whose link you hold; nobody else's case enters it, so none of it can show.
  See `backend/app/ownership.py`.
- **Starting traces is rate limited** per client (30 an hour by default) and
  capped server-wide, because every trace spends the deployment's provider
  quota. See `backend/app/rate_limit.py`.
- **A public deployment can require a demo code** (`EXCHEQUER_DEMO_CODE`) for
  everything that spends the provider quota or keeps running afterwards: live
  traces, batches and watches. Reading -- recorded demos, a stored case by its
  link -- stays open. The code is compared in constant time and a client gets
  10 wrong tries per 15 minutes. The right code returns a signed pass that the
  console sends instead, so a browser that entered it is never locked out by
  someone else's wrong guesses on the same network. It is a shared demo
  secret, not an account: make it long and random. Creating watches is also
  rate limited per client. See `backend/app/access.py`.
- **Reports are signed.** Every text report ends in a SHA-256 content hash and
  an Ed25519 signature made with the server's key. Anyone can check one at
  `/verify` or offline with the key from `/signing-key`. See
  `backend/app/signing.py`.
- **API keys never reach the logs**: HTTP client logging is turned down and
  every log line is scrubbed. See `backend/app/log_safety.py`.
- Every response carries a content security policy and the usual hardening
  headers; the interactive API docs are off on the deployed image; the app
  runs as an unprivileged user.

There are no accounts yet, and the site says so: the front door and a banner
on every page read "Demo mode", and choosing the investigator or citizen view
grants nothing. Without `EXCHEQUER_DEMO_CODE`, anyone who can reach the site
can run a trace; with it, live tracing needs the code. Accounts and roles
come with R23.

## Keys and secrets

Provider keys live in `backend/.env` locally and in the platform's variables
when deployed; neither is committed. The report-signing key is made on first
start beside the case store (`report_signing_key.pem`, mode 0600) or comes
from `EXCHEQUER_SIGNING_KEY`. If a key may have leaked, rotate it at the
provider and update the variable; for the signing key, previously issued
reports will then verify only against the old public key.

`GET /admin/backup` returns the whole store. It exists only when
`EXCHEQUER_BACKUP_TOKEN` is set, compares the bearer token in constant time,
and the nightly copy it feeds is encrypted before it is stored. See
`docs/operations.md`, "Backups".
