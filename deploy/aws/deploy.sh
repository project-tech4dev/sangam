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

  # Every run shares this checkout, so a second deploy stops rather than build from a moving tree.
  exec 9>"$here/.deploy.lock"
  flock -n 9 || { echo "another deploy is running"; exit 1; }

  test -f "$here/.env" || { echo "$here/.env is missing; see docs/DEPLOY_AWS.md Step 4"; exit 1; }
  git diff --quiet && git diff --cached --quiet || { echo "the checkout has local changes; commit or discard them first"; exit 1; }

  git fetch --quiet origin
  git checkout --quiet --detach "$ref"
  sha="$(git rev-parse --short HEAD)"
  echo "deploying $sha ($ref)"

  cd "$here"
  # Images are tagged by commit; :latest, which a bare `docker compose up -d` runs, moves only once this deploy is healthy.
  export TAG="$sha"
  # Build while the old containers keep serving; the only downtime is the restart below.
  docker compose build --pull
  if [ "${MIGRATE:-1}" = "1" ]; then
    docker compose run --rm --no-deps backend python -m app.db.migrate
  fi

  logs() { docker compose logs --tail=100 backend frontend; }
  docker compose up -d --remove-orphans || { echo "restart failed"; logs; exit 1; }
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile

  health() { docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }
  for _ in $(seq 1 30); do
    if [ "$(health backend)" = "healthy" ] && [ "$(health frontend)" = "healthy" ]; then
      for svc in backend frontend; do
        docker tag "ghcr.io/project-tech4dev/sangam-$svc:$sha" "ghcr.io/project-tech4dev/sangam-$svc:latest"
      done
      echo "$sha $(date -u +%FT%TZ) $ref" >> "$here/deployed.txt"
      # Keep a week of commit images for a quick rollback.
      docker image prune -af --filter "until=168h" >/dev/null
      echo "healthy at $sha"
      exit 0
    fi
    sleep 5
  done
  echo "not healthy after 150 s; :latest still names the last good deploy"; logs; exit 1
}
main "$@"
