# Migrations

Every schema change is a numbered migration here; `alembic heads` must print
exactly one. The app runs `upgrade head` at every boot (models.init_db), so a
migration runs on the production Postgres while the previous instance is still
serving it.

That is why each migration runs under `models.guard_migrations`: on Postgres it
waits for any other migrator (an advisory lock), gives up after 120 s, and fails
any DDL that cannot get its table lock within 5 s. A failed boot then starts
without the store and retries (main.py), instead of queueing every live query
on that table behind the waiting DDL.

Write migrations that fit inside that:

- Add columns nullable, or with a constant default (no table rewrite on
  Postgres 11+).
- Create an index on a large table with `postgresql_concurrently=True` inside
  `with op.get_context().autocommit_block():` (that block commits first, so it
  runs outside the lock and the timeouts: make it the migration's last step).
- No type change, rename or rewrite of a large table in one step; widen small
  tables only (`watches`, `alerts` are small; `cases` is not).
- Test it on SQLite (the suite) and let CI run it on Postgres, twice, and with
  two migrators at once.
