"""Delete stored cases, keeping only the ones named.

The case store is evidence, so nothing deletes from it in normal operation.
This exists for one situation: traces run for measurement or seeding -- the
demo re-runs, the cost measurements -- went through the same endpoint as a
real trace and were stored beside the cases that matter, and the Related
cases panel then correlated a demo against dozens of copies of itself.

Because it deletes evidence it never guesses:
  * every case named to keep must be in the store, or nothing is deleted
    (a typo would otherwise keep nothing);
  * without --yes it only lists what would go;
  * a case with a freeze request is refused: the request is the officer's trail;
  * a SQLite store is copied first with SQLite's own backup, which includes
    the write-ahead log that a plain file copy misses, to <db>.bak-<timestamp>,
    and the copy's case count is checked before anything is deleted. Rename
    the copy back to undo a mistaken run;
  * any other store (Postgres) is refused unless --i-have-a-pg-dump says a
    dump was taken, since this script cannot back it up;
  * it never migrates: a store not at the current schema is refused.

    cd backend && .venv/bin/python -m scripts.prune_cases --keep <id> [--keep <id> ...]
    cd backend && .venv/bin/python -m scripts.prune_cases --keep-file ids.txt --yes
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, update  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import config, models  # noqa: E402

SHOWN = 20
CHUNK = 500  # ids per IN (...) list, well under SQLite's variable limit


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)]


def _schema_problem(engine: Engine) -> str | None:
    """Why the store must not be touched, if it is not at the current schema."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config(str(config.BACKEND_DIR / "alembic.ini"))).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current != head:
        return (f"Refusing: the store is at schema {current}, not {head}. Start the app "
                "(or run `alembic upgrade head`) first; this script never migrates.")
    return None


def _backup_sqlite(path: Path, expected: int) -> Path:
    """Copy a live SQLite store, write-ahead log included, and check the copy."""
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    src = sqlite3.connect(path)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(backup)
    try:
        held = check.execute("SELECT count(*) FROM cases").fetchone()[0]
    finally:
        check.close()
    if held < expected:
        raise RuntimeError(f"backup {backup} holds {held} cases, expected {expected}")
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="append", default=[], help="case id to keep (repeatable)")
    parser.add_argument("--keep-file", help="file with one case id per line")
    parser.add_argument("--yes", action="store_true", help="delete; without it the run only lists")
    parser.add_argument("--dry-run", action="store_true", help="list only (the default without --yes)")
    parser.add_argument("--i-have-a-pg-dump", action="store_true",
                        help="allow a non-SQLite store, after taking a pg_dump of it")
    args = parser.parse_args(argv)

    keep = set(args.keep)
    if args.keep_file:
        keep |= {line.strip() for line in Path(args.keep_file).read_text().splitlines() if line.strip()}
    if not keep:
        print("Refusing to delete everything: name at least one case to keep.")
        return 1

    engine = models.engine()
    print(f"case store: {engine.dialect.name} {engine.url.render_as_string(hide_password=True)}")
    sqlite = engine.dialect.name == "sqlite"
    if not sqlite and not args.i_have_a_pg_dump:
        print(f"Refusing: {engine.url.host} is not a SQLite store, so this script cannot back it up. "
              "Take a pg_dump first, then pass --i-have-a-pg-dump.")
        return 2
    problem = _schema_problem(engine)
    if problem:
        print(problem)
        return 2

    with Session(engine) as session:
        ids = list(session.scalars(select(models.Case.id)))
    missing = sorted(keep - set(ids))
    if missing:
        print(f"Refusing: {len(missing)} case(s) to keep are not in the store, so nothing is deleted: "
              f"{missing[:SHOWN]}")
        return 2
    to_delete = [i for i in ids if i not in keep]
    print(f"stored={len(ids)}  keep={len(keep)}  delete={len(to_delete)}")
    if not to_delete:
        print("nothing to delete")
        return 0

    with Session(engine) as session:
        requested: set[str] = set()
        for chunk in _chunks(to_delete):
            requested |= set(session.scalars(
                select(models.FreezeRequest.case_id).where(models.FreezeRequest.case_id.in_(chunk))))
    if requested:
        print(f"Refusing: {len(requested)} case(s) to delete have freeze requests; keep them too: "
              f"{sorted(requested)[:SHOWN]}")
        return 2

    for case_id in to_delete[:SHOWN]:
        print(f"  delete {case_id}")
    if len(to_delete) > SHOWN:
        print(f"  ... and {len(to_delete) - SHOWN} more")
    if args.dry_run or not args.yes:
        print("nothing deleted (add --yes to delete these)")
        return 0

    if sqlite:
        try:
            backup = _backup_sqlite(Path(engine.url.database), len(ids))
        except (sqlite3.Error, RuntimeError) as exc:
            print(f"Refusing: the backup failed, so nothing is deleted ({exc})")
            return 1
        print(f"backup written to {backup}")

    # One transaction: a watch on a deleted case is unlinked, never left
    # pointing at a case that no longer exists.
    with Session(engine) as session, session.begin():
        for chunk in _chunks(to_delete):
            session.execute(update(models.Watch).where(models.Watch.case_id.in_(chunk)).values(case_id=None))
            session.execute(delete(models.Case).where(models.Case.id.in_(chunk)))
    print(f"deleted {len(to_delete)} cases; {len(ids) - len(to_delete)} remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
