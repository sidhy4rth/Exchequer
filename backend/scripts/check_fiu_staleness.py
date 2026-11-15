"""Warn when data/fiu_ind_status.json's sources are due a re-check.

Every FIU-IND note prints "Exchequer last checked the sources on <checked_on>",
and the sources are re-checked at least every fiu_ind_status.STALE_AFTER_DAYS
days. The test suite checks that rule against a fixed day, so it never fails by
itself; this script checks it against the real date. CI runs it in the backend
tests (.github/workflows/test.yml) and once a week with no commit needed
(.github/workflows/fiu-staleness.yml).

It only warns: it prints what to do (the procedure is in docs/flag-rollout.md,
under EXCHEQUER_FIU_IND_NOTE) and ALWAYS exits 0, so an old date never blocks
a merge. On GitHub Actions the warning is also an annotation on the run.

    python scripts/check_fiu_staleness.py   # from backend/
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import fiu_ind_status  # noqa: E402


def main(today: date | None = None) -> int:
    """Print the warning, or that the date is recent; always 0."""
    today = today or date.today()
    why = fiu_ind_status.staleness(today)
    if why is None:
        print(f"{fiu_ind_status.STATUS_FILE}: sources checked within {fiu_ind_status.STALE_AFTER_DAYS} days "
              f"of {today.isoformat()}")
        return 0
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=FIU-IND sources due a re-check::{why}")
    print(f"WARNING: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
