"""Which test files each CI shard runs (test.yml's "backend tests").

CI runs the suite on three runners at once, each with
EXCHEQUER_TEST_SHARD=<k>/<n>. Every runner collects the whole suite, then
conftest.py keeps only the tests in the files this module gives shard k.
The split is a function of the file names and their sizes alone, so every
runner works out the same split, and each file lands in exactly one shard:
together the shards run every test the full run would. Unset, nothing is
deselected (a local run, or any run outside CI).
"""
from __future__ import annotations

import os
from pathlib import Path

ENV = "EXCHEQUER_TEST_SHARD"


def parse(value: str | None) -> tuple[int, int] | None:
    """"2/3" -> (2, 3); unset or empty -> None. Anything else is an error,
    never a silent full or empty run."""
    if not value:
        return None
    k, sep, n = value.partition("/")
    if not (sep and k.isdigit() and n.isdigit() and 1 <= int(k) <= int(n)):
        raise ValueError(f"{ENV} must look like 2/3 (shard 2 of 3), not {value!r}")
    return int(k), int(n)


def split(sizes: dict[str, int], n: int) -> list[set[str]]:
    """Split files (name -> size in bytes) into n shards of about equal size:
    the largest file first, each into the shard with the fewest bytes so far
    (ties to the lower shard). A file's size stands in for its run time."""
    shards: list[set[str]] = [set() for _ in range(n)]
    load = [0] * n
    for name in sorted(sizes, key=lambda f: (-sizes[f], f)):
        i = min(range(n), key=lambda s: (load[s], s))
        shards[i].add(name)
        load[i] += sizes[name]
    return shards


def keep(files: set[Path], value: str | None = None) -> set[Path] | None:
    """The files this run keeps, or None to keep everything."""
    shard = parse(os.environ.get(ENV) if value is None else value)
    if shard is None:
        return None
    k, n = shard
    by_name = {f.name: f for f in files}
    if len(by_name) != len(files):
        raise ValueError("two test files share a name; the shard split needs unique names")
    chosen = split({name: f.stat().st_size for name, f in by_name.items()}, n)[k - 1]
    return {by_name[name] for name in chosen}
