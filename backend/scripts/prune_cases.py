"""Delete stored cases, keeping only the ones named.

The case store is evidence, so nothing deletes from it in normal operation.
This exists for one situation: traces run for measurement or seeding -- the
demo re-runs, the cost measurements -- went through the same endpoint as a
real trace and were stored beside the cases that matter, and the Related
cases panel then correlated a demo against dozens of copies of itself.

The database file is copied to tracechain.db.bak-<timestamp> first, so a
mistaken run can be undone by renaming the copy back.

    cd backend && .venv/bin/python -m scripts.prune_cases --keep <id> [--keep <id> ...]
    cd backend && .venv/bin/python -m scripts.prune_cases --keep-file ids.txt --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import config, models  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="append", default=[], help="case id to keep (repeatable)")
    parser.add_argument("--keep-file", help="file with one case id per line")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    keep = set(args.keep)
    if args.keep_file:
        keep |= {line.strip() for line in Path(args.keep_file).read_text().splitlines() if line.strip()}
    if not keep:
        print("Refusing to delete everything: name at least one case to keep.")
        return 1

    models.init_db()
    with Session(models._engine) as session:
        ids = list(session.scalars(select(models.Case.id)))
    missing = keep - set(ids)
    to_delete = [i for i in ids if i not in keep]
    print(f"stored={len(ids)}  keep={len(keep & set(ids))}  delete={len(to_delete)}")
    if missing:
        print(f"  ! {len(missing)} id(s) to keep are not in the store: {sorted(missing)[:3]}...")
    if args.dry_run or not to_delete:
        print("nothing deleted")
        return 0

    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = config.DB_PATH.with_name(f"{config.DB_PATH.name}.bak-{stamp}")
    shutil.copy2(config.DB_PATH, backup)
    print(f"backup written to {backup}")

    with Session(models._engine) as session:
        session.execute(delete(models.Case).where(models.Case.id.in_(to_delete)))
        session.commit()
    print(f"deleted {len(to_delete)} cases; {len(keep & set(ids))} remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
