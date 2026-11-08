#!/usr/bin/env bash
# Every new commit's author and committer use a GitHub noreply address
# (r1-secrets-history-4): the repository is public, and a personal e-mail in
# commit metadata cannot be taken back. Usage: check_commit_emails.sh <base> <head>
# Prints only the short commit ids, never the address it refused.
set -euo pipefail
base=$1 head=$2
# A force-push leaves the old tip unknown: check what main does not have.
git cat-file -e "$base^{commit}" 2>/dev/null || base=origin/main
bad=0
while read -r sha author committer; do
  for email in "$author" "$committer"; do
    case "$email" in
      *@users.noreply.github.com|noreply@github.com) ;;
      *) echo "::error::commit ${sha:0:12} carries an e-mail that is not a GitHub noreply address; set git config user.email to your <id>+<login>@users.noreply.github.com and amend it."
         bad=1; break ;;
    esac
  done
done < <(git log --format='%H %ae %ce' "$base..$head")
exit $bad
