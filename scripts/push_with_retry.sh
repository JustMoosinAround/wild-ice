#!/usr/bin/env bash
# Commit generated data and push it, rebasing over commits the phone made meanwhile
# (ratings/, prefs/). Usage: scripts/push_with_retry.sh [YYYY-MM-DD]
set -u

run_date="${1:-$(TZ=America/Anchorage date +%F)}"
sleep_s="${PUSH_RETRY_SLEEP:-5}"
attempts=5

# Stage only paths that exist: a missing pathspec makes `git add` stage nothing.
for p in site/data state; do
  if [ -e "$p" ]; then
    git add -A -- "$p" || exit 1
  fi
done

if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -q -m "data: ${run_date}" || exit 1

i=1
while [ "$i" -le "$attempts" ]; do
  echo "push attempt ${i}/${attempts}" >&2
  if git pull -q --rebase --autostash origin main && git push -q origin HEAD:main; then
    exit 0
  fi
  git rebase --abort >/dev/null 2>&1 || true
  if [ "$i" -lt "$attempts" ]; then
    sleep "$sleep_s"
  fi
  i=$((i + 1))
done
echo "push failed after ${attempts} attempts" >&2
exit 1
