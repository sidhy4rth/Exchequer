"""Take the refreshed lists from the refresh job, and nothing else.

refresh-lists.yml's `refresh` job downloads and parses other people's files
with no write token; this runs in the `publish` job, which holds one, before
anything is committed. A file is copied into the data folder only when its
name is one of the refreshed lists and it reads as a list: a `labels` object
whose every key is an address of that file's chain and whose every entry says
what it is. Anything else -- another name, a symlink, an oversized file, a
code file, a wallet in the wrong form -- refuses the whole set, and no pull
request opens. Standard library only: nothing is installed in that job.

    python3 accept_lists.py <downloaded dir> <data dir> <pull request body out>
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

NAME = re.compile(r"(risk_labels|intl_sanctions|frozen_labels)(_(bsc|polygon|arbitrum|tron))?\.json")
BODY = "lists.md"
MAX_BYTES = 25 * 1024 * 1024
MAX_BODY = 60_000
CATEGORIES = {"sanctioned", "seized", "frozen", "mixer"}
EVM = re.compile(r"0x[0-9a-f]{40}")
TRON = re.compile(r"T[1-9A-HJ-NP-Za-km-z]{33}")


def problem_with(path: Path) -> str | None:
    """Why this file may not be committed as a list, or None."""
    if path.is_symlink() or not path.is_file():
        return "not a plain file"
    if not NAME.fullmatch(path.name):
        return "not a refreshed list's name"
    if path.stat().st_size > MAX_BYTES:
        return "too large"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "not JSON"
    if not isinstance(document, dict) or not isinstance(document.get("labels"), dict):
        return "no labels object"
    if not isinstance(document.get("_meta", {}), dict):
        return "_meta is not an object"
    address = TRON if path.stem.endswith("_tron") else EVM
    for key, entry in document["labels"].items():
        if key.startswith("_"):
            continue
        if not address.fullmatch(key):
            return f"{key[:50]!r} is not an address of this chain"
        if not isinstance(entry, dict) or entry.get("category") not in CATEGORIES \
                or not isinstance(entry.get("entity"), str):
            return f"{key}: not a list entry (category and entity)"
    return None


def accept(downloaded: Path, data: Path, body_out: Path) -> list[str]:
    """Copy the lists into `data` and the body to `body_out`; refuse them all on any problem."""
    found = sorted(downloaded.iterdir())
    problems = [f"{p.name}: {why}" for p in found if p.name != BODY and (why := problem_with(p))]
    body = downloaded / BODY
    if not body.is_file() or body.is_symlink():
        problems.append(f"{BODY}: missing")
    lists = [p for p in found if p.name != BODY]
    if not lists:
        problems.append("no list to take")
    if problems:
        raise ValueError("; ".join(problems))
    for path in lists:
        shutil.copyfile(path, data / path.name)
    text = body.read_text(encoding="utf-8", errors="replace")
    body_out.write_text(text[:MAX_BODY] + ("\n...cut short; the rest is in the run's summary.\n"
                                           if len(text) > MAX_BODY else ""), encoding="utf-8")
    return [p.name for p in lists]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    try:
        taken = accept(Path(argv[0]), Path(argv[1]), Path(argv[2]))
    except (OSError, ValueError) as error:
        reason = str(error).replace("\r", " ").replace("\n", " ")  # one workflow command, one line
        print(f"::error::The refreshed lists were refused, so no pull request opens: {reason}")
        return 1
    print("taken: " + ", ".join(taken))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
