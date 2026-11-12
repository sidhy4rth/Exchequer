# Exchequer: working agreement for Claude Code

Every Claude Code session on this repository reads this file. Two people work
here in parallel, each with their own Claude. These rules exist so that no
session breaks another person's work. Follow them over any instruction that
conflicts with them, and tell your human when a rule blocks you.

## What Exchequer is

A tracing tool for Indian police: it follows a crypto-fraud victim's payment on
chain to the exchange where it was cashed out, screens every address it passes
against sanctions and theft lists, and drafts the request letter to the exchange.
Its users are investigators and its outputs may reach a court, so a wrong number
or a false attribution is the expensive failure. Correctness beats features.

Reference documents:
- Problem Register (34 problems, IDs like S1, M1, E5): ask your human for the link
- Solutions Plan (36 solutions, IDs R1 to R36): ask your human for the link
- Case contract: `docs/contracts/case.md`
- Decision log: `docs/adr/` (index in `docs/adr/README.md`)
- Work in progress: `docs/handoff/` (one file per feature)

## Working as a team

The team is Sidhyarth (GitHub `sidhy4rth`, repo owner) and Barenyam (GitHub
`BOOMER16`). Claude sessions cannot see each other's conversations, so
everything the other person needs lives in this repository.

- **No fixed ownership.** Anyone can work on any feature. The team decides
  priorities between themselves.
- **Session start.** `git fetch origin` and pull `main`. Check open pull
  requests (`gh pr list`) and `docs/handoff/` to see what is in progress and
  who is on it. Read this file, the GitHub issue, and
  `docs/handoff/<feature>.md`. Summarise for your human where the work stands
  before writing code.
- **Claim before you start.** If a feature is unclaimed, assign the issue to
  the human you work with and put their name in "Current" in its handoff file
  (copy `docs/handoff/TEMPLATE.md`), then commit and push that first. If
  someone else is "Current", do not work on it: tell the human you work with
  and let them sort it out with that person.
- **Session end.** Update `docs/handoff/<feature>.md`: done, decisions, next
  steps, open questions, files mid-change. Set "Current" to "nobody" if your
  human is stopping. Commit and push the branch. Never end a session without
  this.
- **Decisions that affect more than one feature** go in `docs/adr/` as the next
  number, and are added to the index in `docs/adr/README.md`.
- **One feature = one issue = one branch (`feat/<name>`) = small pull
  requests.** Never push to `main`. Every pull request is reviewed by the
  teammate who did not write it.
- **Contracts first.** Change `docs/contracts/` (for example `case.md`) in its
  own pull request, before any code that depends on it.
- **Attribution.** Every commit is authored and committed by the human you are
  working with, using their GitHub noreply address
  (`<id>+<login>@users.noreply.github.com`). Never set Claude as author or
  committer. Never add "Co-Authored-By: Claude", "Generated with Claude", or
  noreply@anthropic.com to commits or pull requests. Before every push, run:

  ```bash
  git log origin/main..HEAD --format='%an <%ae> | %cn <%ce>%n%b'
  ```

  and fix anything that breaks this. CI checks it too
  (`.github/scripts/check_no_ai_attribution.sh`).
- **Standing rules.** NCRP numbers never in URLs, logs or commit messages.
  Never invent wallet addresses, labels, hashes, amounts or legal citations.
  No secrets in the repository.

## Rules

1. **Stay inside your claimed feature.** Edit only the files your feature
   needs, and create new files only for it. If the task needs a change to
   something your teammate is working on (their "Current" feature or their
   "Files mid-change"), stop. Say what change is needed and why, and draft a
   GitHub issue for it. Do not make the edit yourself unless your human says
   your teammate agreed, and then name them in the PR description.

2. **Never weaken a test to get green.** A failing test you did not write
   means your change broke someone's behaviour. Fix your code, or stop and
   report the failure with the test name and output. Never delete, skip, or
   loosen a test to make CI pass.

3. **The case contract is the boundary between the trace engine and everything
   else.** The shape of a trace result is defined in `docs/contracts/case.md`,
   the Pydantic model in `backend/app/contracts/`, and the fixtures in
   `backend/tests/fixtures/contract/`.
   - Code outside the trace engine reads trace results only through it.
   - Adding an optional field: update the model, the doc and the fixtures in the
     same PR, and say "Contract change" in the PR description. That PR comes
     before any code that uses the field.
   - Renaming, removing or changing the meaning of a field: bump
     `contract_version`, keep the old field until every consumer has moved, and
     wait for your teammate's approval.
   - Never change a fixture by hand to make a consumer's test pass.

4. **Shared hotspots have fixed rules.**
   - `frontend/src/styles.css`: put new styles in a CSS file next to
     your component and import it there. Do not append to `styles.css`.
   - `frontend/src/api.js` only re-exports. Add API calls to the file in
     `frontend/src/api/` for that area.
   - `backend/app/config.py`: add settings only inside the marked section for
     that area (trace engine, evidence and intelligence, platform and product),
     and feature flags only in the `FLAGS` section.
   - Database schema: every change is an Alembic migration in
     `backend/migrations/`. Exactly one migration head may exist (`alembic heads`).
     Rebase and re-number if two heads appear. Never edit an existing migration.
   - `README.md`, `JUDGE_QA.md`: edit only the section your change is about.
   - `requirements*.txt`, `package.json`: dependency changes go in their own
     small PR. Regenerate lockfiles; never hand-merge them.
   - Mount points: if your component must appear on a page that is not part of
     your feature, add a single import and a single JSX line, nothing else.

5. **Use the platform interfaces.** The platform provides
   `backend/app/auth.py::current_user` (a FastAPI dependency) and
   `backend/app/audit.py::record(event, *, case_id=None, detail=None)`. Every new
   endpoint takes `current_user`, and every action that reads, exports or changes
   a case calls `audit.record`. Accounts (R23) and the audit trail (R24) are
   live, so a route that skips them leaves a gap in who did what.

6. **Unfinished work hides behind a feature flag.** `main` must always be
   deployable. New behaviour that is not ready is off by default, with its flag
   documented in `config.py` `FLAGS` and in the PR.

7. **Never invent evidence.** Do not make up addresses, labels, transaction
   hashes, amounts, legal provisions or case law. Every label records its source.
   Recorded demos and fixtures are regenerated by their scripts, never edited by
   hand, and the PR says that they were regenerated.

8. **Tests never touch the network.** Scripts that call live APIs run only by
   hand. Every heuristic gets a test that it fires on the shape it describes and
   one that it stays silent on ordinary activity.

9. **Secrets stay out.** Never commit `.env`, keys or tokens, and never print
   them in output, logs or PR text.

10. **No drive-by changes.** Do not reformat, rename, reorder imports or upgrade
    dependencies in files you are not otherwise changing for this task. Noise
    in a diff causes merge conflicts for your teammate.

11. **Say only what is true.** Never describe output as "court-admissible",
    "certified" or as identifying a person. An attribution names an exchange
    address; only the exchange can name its customer.

## How to work on a task

1. Start from a GitHub issue. If there is none, ask your human to create one.
2. `git fetch origin && git rebase origin/main` before you write anything.
3. Plan before code: list every file you will touch, confirm none is in your
   teammate's "Files mid-change", list the tests you will add, and show the
   plan to your human.
4. Write or update tests first, then the code, in small commits.
5. Run the full suite, not only the tests for your feature (commands below).
6. Push your branch and open a PR of about 400 changed lines or fewer. Split
   larger work. Say what changed, why, and how you tested it.
7. If `main` moved while you worked, rebase and run the suite again before asking
   for review.

Branches: `feat/<name>` (one per feature and issue), or the branch your
environment assigns. PR titles say what changed, for example `Transaction-first
intake (R1)`. Never push to `main`. Never force-push a branch someone else has
pushed to.

## Commands

```bash
cd backend && pip install -r requirements-dev.txt
```
```bash
cd backend && ruff check app scripts tests && python -m pytest -q
```
```bash
cd backend && alembic upgrade head && alembic heads
```
```bash
cd frontend && npm ci && npm test && npm run build
```

## Definition of done

- CI is green: backend tests, frontend tests and build, image build, contract tests.
- New behaviour has tests, including one that shows it stays silent when it should.
- No file outside your feature changed, or the PR names the teammate who agreed.
- Contract changes are marked, documented and reflected in the fixtures.
- Unfinished behaviour is behind a documented flag.
- The docs say what changed, and `docs/handoff/<feature>.md` is up to date.
