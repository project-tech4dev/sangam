#!/usr/bin/env bash
# Print the effective DATABASE_URL for the selected compose environment.
#
# Compose is the single source of truth: it already resolves the LOCAL_DB_* /
# STAGING_DB_* interpolation, including the :? guards that fail when a staging
# variable is unset. This script surfaces compose's own error message rather
# than letting a downstream parser choke on empty input.
#
# Usage: scripts/db-url.sh docker compose [-f ...] [-f ...]

set -uo pipefail

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <compose command...>" >&2
  exit 2
fi

config=$("$@" config --format json 2>&1)
status=$?

if [[ $status -ne 0 ]]; then
  # Compose already explains what is missing (e.g. "set STAGING_DB_HOST in .env").
  printf '%s\n' "$config" >&2
  exit "$status"
fi

url=$(printf '%s' "$config" | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except ValueError:
    sys.exit("could not parse compose config output")
env = doc.get("services", {}).get("backend", {}).get("environment", {})
url = env.get("DATABASE_URL", "")
if not url:
    sys.exit("backend service has no DATABASE_URL in the resolved compose config")
print(url)
')
status=$?

[[ $status -eq 0 ]] || exit "$status"
printf '%s\n' "$url"
