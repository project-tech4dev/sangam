#!/bin/sh
# node_modules is a named volume that outlives the container. The stamp records
# which manifests filled it, so we reinstall only when they actually change.
set -e

STAMP=/app/node_modules/.deps-stamp
want=$(cat /app/package.json /app/package-lock.json | md5sum | cut -d' ' -f1)
have=$(cat "$STAMP" 2>/dev/null || echo none)

if [ "$want" = "$have" ]; then
  echo "frontend: dependencies unchanged, skipping install"
else
  echo "frontend: dependencies changed ($have -> $want), reinstalling"
  # npm ci empties node_modules itself, and validates the lockfile before it
  # touches anything — so a bad lockfile leaves the old tree intact.
  npm ci --no-audit --no-fund
  # Turbopack's dev cache outlives the deps it was built against. Explicit if,
  # not `[ -d ] &&`: under set -e a false test would exit the script.
  if [ -d /app/.next ]; then
    find /app/.next -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
  # Written last: a failed install leaves no stamp, so the next boot retries.
  echo "$want" > "$STAMP"
fi

exec "$@"
