#!/bin/sh
# Starts MISTER PLIS in its container as the user misterplis (uid 1000, or MISTER_PLIS_UID / MISTER_PLIS_GID to match
# the owner of the folders on the host). A volume folder Docker made itself belongs to root: it is given to that user
# once, so the server can write there. Folders that belong to someone else already are left as they are.
set -e
uid="${MISTER_PLIS_UID:-1000}"
gid="${MISTER_PLIS_GID:-$uid}"
if [ "$(id -u)" = "0" ]; then
  for d in "$MISTER_PLIS_HOME" /storage /backup; do
    if [ -d "$d" ] && [ "$(stat -c %u "$d")" = "0" ] && [ "$uid" != "0" ]; then
      # /backup only while it is empty (a NAS share keeps the owner the NAS gives it); a failure is only a warning
      if [ "$d" != "/backup" ] || [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
        chown -R "$uid:$gid" "$d" 2>/dev/null || echo "mister-plis: couldn't give $d to uid $uid — check its owner on the host" >&2
      fi
    fi
  done
  exec setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"
fi
exec "$@"
