#!/usr/bin/env bash
# Deploy on the instance itself: check out a ref, build both images, migrate, restart. Setup: docs/DEPLOY_AWS.md.
# Usage: deploy/aws/deploy.sh [ref]   (default origin/master; MIGRATE=0 skips migrations)
set -euo pipefail

# One function, so bash has read the whole file before the checkout below replaces it.
main() {
  ref="${1:-origin/master}"
  here="$(cd "$(dirname "$0")" && pwd)"
  repo="$(cd "$here/../.." && pwd)"
  cd "$repo"

  test -f "$here/.env" || { echo "$here/.env is missing; see docs/DEPLOY_AWS.md Step 4"; exit 1; }
  git diff --quiet && git diff --cached --quiet || { echo "the checkout has local changes; commit or discard them first"; exit 1; }

  git fetch --quiet origin
  git checkout --quiet --detach "$ref"
  sha="$(git rev-parse --short HEAD)"
  echo "deploying $sha ($ref)"

  cd "$here"
  # Build while the old containers keep serving; the only downtime is the restart below.
  docker compose build --pull
  if [ "${MIGRATE:-1}" = "1" ]; then
    docker compose run --rm --no-deps backend python -m app.db.migrate
  fi

  logs() { docker compose logs --tail=100 backend; }
  docker compose up -d --remove-orphans || { echo "restart failed"; logs; exit 1; }
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile

  for _ in $(seq 1 30); do
    if [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q backend)")" = "healthy" ]; then
      echo "$sha $(date -u +%FT%TZ) $ref" >> "$here/deployed.txt"
      docker image prune -f >/dev/null
      echo "backend healthy at $sha"
      exit 0
    fi
    sleep 5
  done
  echo "backend did not become healthy"; logs; exit 1
}
main "$@"
