#!/bin/sh
# Start the app as the unprivileged `app` user when that is possible.
#
# The platform mounts the /data volume owned by root, so the container starts
# as root, hands /data to `app`, and drops to it for uvicorn. Every step falls
# back to the old behaviour (running as root) rather than failing: a volume
# that refuses chown, or a missing setpriv, must not take the site down.
set -u
# --ws none: no route speaks WebSocket, so no WebSocket parser faces the
# network. --no-server-header: no version banner on every response.
CMD="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --ws none --no-server-header"

if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1 && id app >/dev/null 2>&1; then
  mkdir -p /data
  chown -R app:app /data 2>/dev/null
  if setpriv --reuid=app --regid=app --init-groups sh -c 'test -w /data' 2>/dev/null; then
    # The app user has no home of its own, and setpriv keeps root's
    # HOME=/root, which uid 10001 may not read. libpq looks there for an
    # optional client certificate and refuses to connect on "Permission
    # denied", so point HOME at the volume the app user now owns.
    export HOME=/data
    # shellcheck disable=SC2086
    exec setpriv --reuid=app --regid=app --init-groups $CMD
  fi
  echo "entrypoint: /data is not writable as user app; running as root" >&2
fi
# shellcheck disable=SC2086
exec $CMD
