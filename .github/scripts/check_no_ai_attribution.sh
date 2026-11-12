#!/usr/bin/env bash
# Every new commit is authored and committed by a person, and credits no AI
# assistant: GitHub turns a Co-Authored-By trailer or an AI author into a
# contributor, and the contributors list is meant to be the team. A
# Claude-Session trailer (a link to a private chat) is refused too. See
# CLAUDE.md, "Working as a team", and ADR-0010.
# Usage: check_no_ai_attribution.sh <base> <head>
# Prints only the short commit ids, never the name, address or text it refused.
set -euo pipefail
base=$1 head=$2
# A force-push leaves the old tip unknown: check what main does not have.
git cat-file -e "$base^{commit}" 2>/dev/null || base=origin/main
identity='claude|anthropic'
message='co-authored-by:[[:space:]]*claude|generated with \[?claude|noreply@anthropic\.com|^claude-session:'
bad=0
while read -r sha; do
  if git log -1 --format='%an%n%ae%n%cn%n%ce' "$sha" | grep -qiE "$identity"; then
    echo "::error::commit ${sha:0:12} has an AI assistant as author or committer; re-commit it as the person who made it."
    bad=1
  fi
  if git log -1 --format='%B' "$sha" | grep -qiE "$message"; then
    echo "::error::commit ${sha:0:12} credits an AI assistant in its message; remove that line and amend it."
    bad=1
  fi
done < <(git rev-list "$base..$head")
exit $bad
