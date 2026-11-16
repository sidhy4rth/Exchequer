#!/usr/bin/env bash
# Reads the paths a pull request changes, one per line, on stdin, and prints
# "true" when every one is documentation, otherwise "false" (test.yml's
# `changes` job). Documentation is a file under docs/ or a Markdown file at the
# repository root. A Markdown file anywhere else (backend/, frontend/,
# citizen/, .github/) is not: it ships in the image or a build, or a script
# may read it. No paths at all, or a path git had to quote, is "false" too: in
# any doubt everything runs.
set -euo pipefail

seen=0
while IFS= read -r path || [ -n "$path" ]; do
  [ -n "$path" ] || continue
  seen=1
  case "$path" in
    \"*) echo false; exit 0 ;;  # git quotes an unusual name; do not guess
    docs/*) ;;
    */*) echo false; exit 0 ;;
    *.md) ;;
    *) echo false; exit 0 ;;
  esac
done

if [ "$seen" = 1 ]; then echo true; else echo false; fi
