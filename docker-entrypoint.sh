#!/bin/sh
# Start the app as the unprivileged `app` user when that is possible.
#
# The platform mounts the /data volume owned by root, so the container starts
# as root, hands /data to `app`, and drops to it for uvicorn. Every step falls
# back to the old behaviour (running as root) rather than failing: a volume
# that refuses chown, or a missing setpriv, must not take the site down.
set -u
CMD="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"

if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1 && id app >/dev/null 2>&1; then
  mkdir -p /data
  chown -R app:app /data 2>/dev/null
  if setpriv --reuid=app --regid=app --init-groups sh -c 'test -w /data' 2>/dev/null; then
    # shellcheck disable=SC2086
    exec setpriv --reuid=app --regid=app --init-groups $CMD
  fi
  echo "entrypoint: /data is not writable as user app; running as root" >&2
fi
# shellcheck disable=SC2086
exec $CMD
