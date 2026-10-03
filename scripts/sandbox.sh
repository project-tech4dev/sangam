#!/usr/bin/env bash
# One git worktree plus one isolated Docker stack per feature. docs/SANDBOX.md
# has the design; this script never reads .env, only copies and appends to it.
#
#   scripts/sandbox.sh new <slug> [--graph] [--base <ref>] [--no-clone]
#   scripts/sandbox.sh ls
#   scripts/sandbox.sh url    <slug>
#   scripts/sandbox.sh verify <slug>
#   scripts/sandbox.sh rm     <slug> [--force]

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON="$(git -C "$SELF_DIR" rev-parse --path-format=absolute --git-common-dir)"
MAIN_ROOT="$(dirname "$GIT_COMMON")"     # the MAIN worktree, even when run from a sandbox

BASE_FRONTEND=3000 BASE_BACKEND=8010 BASE_PG=5433
BASE_NEO4J_HTTP=7474 BASE_NEO4J_BOLT=7687
STRIDE=10 SLOT_MIN=1 SLOT_MAX=9

SHARED_NPM_CACHE=sangam_shared_npm_cache
LOCK_DIR="$GIT_COMMON/sangam-sandbox.lock"

die()  { printf '%s\n' "$*" >&2; exit 1; }
note() { printf '  %s\n' "$*"; }

# ---------------------------------------------------------------- slot maths
# All five ports are reserved even without --graph, so adding it later cannot collide.
slot_ports() {
  local n=$1
  echo $((BASE_FRONTEND+n*STRIDE)) $((BASE_BACKEND+n*STRIDE)) $((BASE_PG+n*STRIDE)) \
       $((BASE_NEO4J_HTTP+n*STRIDE)) $((BASE_NEO4J_BOLT+n*STRIDE))
}

port_free() { ! nc -z -G 1 127.0.0.1 "$1" >/dev/null 2>&1; }

# Three sources, each of which dies with the thing it describes. No registry.
claimed_slots() {
  # (a) each worktree's own manifest — removed by `git worktree remove`
  git -C "$MAIN_ROOT" worktree list --porcelain \
    | awk '/^worktree /{print $2}' \
    | while read -r wt; do
        [ -f "$wt/.sandbox" ] && sed -n 's/^SANDBOX_SLOT=\([0-9]\{1,2\}\)$/\1/p' "$wt/.sandbox"
      done
  # (b) compose projects, running or not: catches a hand-deleted worktree directory.
  docker compose ls -a --format json 2>/dev/null \
    | python3 -c 'import json,sys
try: rows = json.load(sys.stdin)
except Exception: sys.exit(0)
for r in rows:
    n = r.get("Name", "")
    if n.startswith("sangam-"): print(n)' 2>/dev/null \
    | while read -r proj; do
        p=$(docker inspect -f \
          '{{range $k,$v := .HostConfig.PortBindings}}{{if eq $k "5432/tcp"}}{{range $v}}{{.HostPort}}{{end}}{{end}}{{end}}' \
          "${proj}-postgres-1" 2>/dev/null || true)
        if [ -n "$p" ] && [ "$p" -gt "$BASE_PG" ] 2>/dev/null; then
          echo $(( (p - BASE_PG) / STRIDE ))
        fi
      done
}

allocate_slot() {
  local claimed n p all_free
  claimed=" $(claimed_slots | sort -u | tr '\n' ' ') "
  for n in $(seq "$SLOT_MIN" "$SLOT_MAX"); do
    [[ "$claimed" == *" $n "* ]] && continue
    all_free=1
    for p in $(slot_ports "$n"); do
      # Insurance against someone editing a base constant onto a live port.
      if [ "$p" = 5432 ] || [ "$p" = 8000 ]; then
        die "slot $n would bind $p (dalgo/airbyte) — fix the base constants in $0"
      fi
      port_free "$p" || { all_free=0; break; }
    done
    [ "$all_free" -eq 1 ] && { echo "$n"; return 0; }
  done
  {
    echo "no free slot in $SLOT_MIN..$SLOT_MAX."
    echo "claimed:${claimed}"
    echo "Slot 7's backend port is 8080, often taken on this machine; the probe"
    echo "skips it automatically and that is not a fault."
    echo "Tear one down with:  make sandbox-rm SLUG=<slug>"
  } >&2
  return 1
}

# mkdir is atomic. Held from allocation until .sandbox exists, after which
# source (a) makes the claim visible to a concurrent run.
acquire_lock() {
  local tries=0
  until mkdir "$LOCK_DIR" 2>/dev/null; do
    tries=$((tries+1))
    [ "$tries" -gt 60 ] && die "another sandbox run holds $LOCK_DIR (stale? rmdir it)"
    sleep 1
  done
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
}

release_lock() { rmdir "$LOCK_DIR" 2>/dev/null || true; trap - EXIT; }

# ------------------------------------------------------------------- helpers
slugify() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9]\{1,\}/-/g' -e 's/^-//' -e 's/-$//' | cut -c1-24
}

worktree_for() {
  local wt="$MAIN_ROOT/../sangam-$1"
  [ -f "$wt/.sandbox" ] || die "no sandbox '$1' (see: make sandbox-ls)"
  (cd "$wt" && pwd)
}

# ----------------------------------------------------------------- env files
write_env() {
  local wt=$1 slot=$2 slug=$3 graph=$4
  local fp=$((BASE_FRONTEND+slot*STRIDE)) bp=$((BASE_BACKEND+slot*STRIDE))
  local pp=$((BASE_PG+slot*STRIDE))
  local nh=$((BASE_NEO4J_HTTP+slot*STRIDE)) nb=$((BASE_NEO4J_BOLT+slot*STRIDE))
  local profiles=localdb neo4j_uri=
  [ "$graph" = 1 ] && { profiles=localdb,graph; neo4j_uri=bolt://neo4j:7687; }

  cp -p "$MAIN_ROOT/.env" "$wt/.env"      # copied, never read
  chmod 600 "$wt/.env"

  cat >>"$wt/.env" <<EOF

# =============================================================================
# SANDBOX OVERRIDE BLOCK — appended by scripts/sandbox.sh.
# Compose takes the LAST assignment of a duplicate key, so this block wins.
# =============================================================================
SANDBOX_SLOT=$slot
SANDBOX_SLUG=$slug

# Layers docker-compose.sandbox.yml without an -f on every command.
COMPOSE_FILE=docker-compose.yml:docker-compose.sandbox.yml
COMPOSE_PROFILES=$profiles

# slot N = base + N*10. Slot 0, the main checkout, keeps the bare defaults.
FRONTEND_PORT=$fp
BACKEND_PORT=$bp
PG_PORT=$pp
NEO4J_HTTP_PORT=$nh
NEO4J_BOLT_PORT=$nb

# Baked into the browser bundle, so it must name THIS stack's backend port.
NEXT_PUBLIC_API_URL=http://localhost:$bp
# Exact origin, not a regex: a trailing \$ here is interpolation-ambiguous.
ALLOWED_ORIGINS=http://localhost:$fp
ALLOWED_ORIGIN_REGEX=

# Empty = the graph self-disables. Compose reads \${NEO4J_URI-...} without the
# colon, so set-but-empty stays empty rather than taking the default.
NEO4J_URI=$neo4j_uri

# The bundled container, always: never inherit a managed URL from the copy.
LOCAL_DATABASE_URL=
LOCAL_DB_HOST=postgres
LOCAL_DB_PORT=5432

# Keep sandbox traffic out of the main project's traces.
LANGSMITH_PROJECT=sangam-$slug
LANGFUSE_TRACING_ENVIRONMENT=sandbox-$slug

# Smaller footprint: N stacks share one Docker Desktop memory budget.
DB_POOL_MAX_SIZE=5
MAX_PARALLEL_RESEARCH=3
EOF

  # Both, not just the URL: @supabase/ssr throws on either being empty, so a real
  # URL beside an empty key 500s identically. grep -q decides without printing.
  if ! grep -qs '^NEXT_PUBLIC_SUPABASE_URL=..*' "$wt/.env" \
     || ! grep -qs '^NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=..*' "$wt/.env"; then
    cat >>"$wt/.env" <<'EOF'

# Dummy but NON-EMPTY, or every page 500s. Sign-in will not work against these;
# /ask and /import redirect to login, the rest of the site renders.
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_sandbox_placeholder
EOF
    note "Supabase: placeholder values (the main .env is missing the URL or the key)"
  fi

  # Append any key .env.example has gained that this copy lacks, so an older
  # sandbox does not silently miss a new variable. Reads .env.example only.
  local key added=0
  while IFS= read -r key; do
    grep -q "^${key}=" "$wt/.env" || { printf '%s=\n' "$key" >>"$wt/.env"; added=$((added+1)); }
  done < <(sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' "$MAIN_ROOT/.env.example" | sort -u)
  [ "$added" -gt 0 ] && note "added $added key(s) that .env.example has and the copy lacked"

  # Non-secret manifest: the ONLY file ls/url/rm/allocation read.
  cat >"$wt/.sandbox" <<EOF
SANDBOX_SLOT=$slot
SANDBOX_SLUG=$slug
SANDBOX_PROJECT=sangam-$slug
SANDBOX_GRAPH=$graph
SANDBOX_CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FRONTEND_PORT=$fp
BACKEND_PORT=$bp
PG_PORT=$pp
NEO4J_HTTP_PORT=$nh
NEO4J_BOLT_PORT=$nb
EOF
}

link_tooling() {
  local wt=$1 s
  # Gitignored, so a fresh worktree lacks them. Symlinked so one update reaches
  # every sandbox; .gitignore drops the trailing slash so symlinks still match.
  ln -sfn "$MAIN_ROOT/.agents" "$wt/.agents"
  [ -f "$MAIN_ROOT/skills-lock.json" ] && ln -sfn "$MAIN_ROOT/skills-lock.json" "$wt/skills-lock.json"
  [ -d "$MAIN_ROOT/backend/.venv" ] && ln -sfn "$MAIN_ROOT/backend/.venv" "$wt/backend/.venv"

  mkdir -p "$wt/.claude/skills"
  # -P keeps each relative target (resolves via the .agents symlink); -n spares
  # tracked first-party skills.
  for s in "$MAIN_ROOT"/.claude/skills/*; do
    [ -e "$s" ] || continue
    cp -RPn "$s" "$wt/.claude/skills/" 2>/dev/null || true
  done
}

# -------------------------------------------------------------------- the db
# The volume already ran db/init, so the target is not empty. DROP/CREATE rather
# than --clean, whose bare DROP EXTENSION vector fails under live pgvector columns.
reset_database() {
  ( cd "$1" && docker compose exec -T postgres sh -c '
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
        -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
        -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""' >/dev/null )
}

baseline_from_init() {
  # The same three files, in the same order, that a first boot would run. They
  # are mounted read-only at /docker-entrypoint-initdb.d by the base compose.
  ( cd "$1" && docker compose exec -T postgres sh -c '
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -f /docker-entrypoint-initdb.d/01_extensions.sql \
        -f /docker-entrypoint-initdb.d/02_schema.sql \
        -f /docker-entrypoint-initdb.d/03_dev_user.sql' >/dev/null )
}

# 0 = cloned slot 0.  1 = caller must migrate + seed onto a baseline schema.
clone_from_slot0() {
  local wt=$1 src dump
  dump="$MAIN_ROOT/db/backups/sandbox-$(date +%Y%m%d-%H%M%S)/slot0.dump"
  # One trap covers every exit path, Ctrl-C included. Assign before arming or
  # set -u makes the trap the error; release_lock has already cleared EXIT.
  CLONE_DUMP_DIR="$(dirname "$dump")"
  trap 'rm -rf "$CLONE_DUMP_DIR" 2>/dev/null || true' EXIT

  src="$(cd "$MAIN_ROOT" && docker compose ps -q postgres 2>/dev/null || true)"
  if [ -z "$src" ] || [ "$(docker inspect -f '{{.State.Running}}' "$src" 2>/dev/null)" != true ]; then
    note "slot 0 Postgres is not running — building from the baseline instead"
    return 1
  fi

  # Dump BEFORE touching the target, so a failure here costs nothing. -U/-d from
  # the container's own env: slot 0 need not be sangam/sangam.
  mkdir -p "$CLONE_DUMP_DIR"
  if ! docker exec -i "$src" sh -c \
      'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' >"$dump"; then
    note "pg_dump of slot 0 failed — building from the baseline instead"; return 1
  fi
  [ -s "$dump" ] || { note "slot 0 dump is empty — building from the baseline instead"; return 1; }

  reset_database "$wt"

  # pg_restore with no filename reads stdin.
  if ! ( cd "$wt" && docker compose exec -T postgres sh -c '
          pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-owner --no-acl --exit-on-error' <"$dump" >/dev/null ); then
    note "pg_restore failed — rebuilding from the baseline instead"
    # --exit-on-error leaves a HALF-restored database, so drop it a second time:
    # the baseline's bare CREATE TABLEs would otherwise hit tables that exist.
    reset_database "$wt"
    baseline_from_init "$wt"
    return 1
  fi
  note "database: clone of slot 0 ($(du -h "$dump" | cut -f1))"
  return 0
}

# -------------------------------------------------------------------- new
cmd_new() {
  local raw=${1:-}
  [ -n "$raw" ] || die "usage: sandbox.sh new <slug> [--graph] [--base <ref>] [--no-clone]"
  shift
  local graph=0 base=origin/master do_clone=1
  while [ $# -gt 0 ]; do
    case $1 in
      --graph)    graph=1 ;;
      --no-clone) do_clone=0 ;;
      --base)     base=${2:?--base needs a ref}; shift ;;
      *)          die "unknown flag: $1" ;;
    esac
    shift
  done

  local slug; slug=$(slugify "$raw")
  [ -n "$slug" ] || die "slug '$raw' reduces to nothing; use a-z0-9 and hyphens"
  local wt="$MAIN_ROOT/../sangam-$slug"
  [ -e "$wt" ] && die "$wt already exists (make sandbox-ls, or make sandbox-rm SLUG=$slug)"

  # Everything that can refuse runs before anything that creates: a die() after
  # `worktree add` strands a worktree with no .sandbox, which `rm` cannot find.
  [ -f "$MAIN_ROOT/.env" ] || die \
"$MAIN_ROOT/.env is missing. In the main checkout:
    cp .env.example .env     # then fill ANTHROPIC_API_KEY
A sandbox inherits its keys from it."

  git -C "$MAIN_ROOT" fetch --quiet origin 2>/dev/null || note "fetch skipped (offline?)"
  git -C "$MAIN_ROOT" rev-parse --verify --quiet "$base^{commit}" >/dev/null \
    || die "--base $base is not a commit this repository knows"
  # A base predating the harness has neither the overlay nor the port tokens, so
  # compose would fail or bind slot 0's ports. Caught here, not mid-build.
  git -C "$MAIN_ROOT" cat-file -e "$base:docker-compose.sandbox.yml" 2>/dev/null \
    || die "base '$base' predates the sandbox harness (no docker-compose.sandbox.yml).
Until feat/dev-harness-parallel-sandboxes is merged, pass the branch explicitly:
    make sandbox-new SLUG=$slug BASE=HEAD"

  acquire_lock
  git -C "$MAIN_ROOT" worktree prune     # inside the lock: it mutates shared metadata
  local slot; slot=$(allocate_slot) || exit 1
  local fp=$((BASE_FRONTEND+slot*STRIDE)) bp=$((BASE_BACKEND+slot*STRIDE))

  echo "── sandbox $slug → slot $slot ──────────────────────"
  git -C "$MAIN_ROOT" worktree add -b "sandbox/$slug" "$wt" "$base"
  wt=$(cd "$wt" && pwd)          # …/sangam/../sangam-a → …/sangam-a, for printing
  note "worktree $wt on sandbox/$slug from $base"

  write_env "$wt" "$slot" "$slug" "$graph"
  link_tooling "$wt"
  docker volume create "$SHARED_NPM_CACHE" >/dev/null   # idempotent; external
  note "env written, tooling linked, npm cache shared"
  release_lock

  # Explicit: a cold build is minutes, and `up` doing it silently looks like a hang.
  echo "── building (6-10 min cold, ~2 min warm) ───────────"
  ( cd "$wt" && docker compose build backend frontend )
  ( cd "$wt" && docker compose up -d --wait postgres )

  local min_docs=96
  if [ "$do_clone" = 1 ] && clone_from_slot0 "$wt"; then
    :
  else
    # Every path here leaves the baseline present, so these two steps are identical.
    ( cd "$wt" && make up )
    ( cd "$wt" && make seed )
    min_docs=0                    # `make seed` creates no documents rows
    note "database: baseline + migrate + seed (no documents; smoke floor relaxed)"
  fi
  ( cd "$wt" && make up )         # idempotent; brings the rest up with --wait

  # Banner before the verdict, never conditional: the stack is what `new` delivers.
  # Gating it on a green smoke hid the URLs on every clone-path sandbox.
  cat <<EOF

── sandbox $slug is up (slot $slot) ───────────────────
  frontend   http://localhost:$fp
  backend    http://localhost:$bp/docs
  postgres   localhost:$((BASE_PG+slot*STRIDE))
  worktree   $wt   (branch sandbox/$slug)

  work on it here:  cd $wt && claude "<the idea>"
  tear it down:     make sandbox-rm SLUG=$slug

── verifying ───────────────────────────────────────
EOF
  if SMOKE_MIN_DOCUMENTS=$min_docs SMOKE_SKIP_LLM="${SMOKE_SKIP_LLM:-1}" cmd_verify "$slug"; then
    return 0
  fi
  cat <<EOF

The stack is up; it is smoke that failed. A clone is never greener than its
source, so compare before concluding anything is wrong with this sandbox:

    make smoke                      # in the main checkout, from $MAIN_ROOT
    cd $wt && make logs

Matching failures mean the sandbox is fine and slot 0 has the problem.
EOF
  return 1
}

# -------------------------------------------------------- verify / ls / url
cmd_verify() {
  local wt fp bp
  wt=$(worktree_for "${1:?usage: sandbox.sh verify <slug>}")
  # Ports from the running stack, never a file. `|| true` is load-bearing: under
  # set -e a failed substitution exits before the guard below can explain why.
  fp=$(cd "$wt" && docker compose port frontend 3000 2>/dev/null | cut -d: -f2) || true
  bp=$(cd "$wt" && docker compose port backend  8000 2>/dev/null | cut -d: -f2) || true
  if [ -z "$fp" ] || [ -z "$bp" ]; then
    ( cd "$wt" && docker compose ps --format 'table {{.Service}}\t{{.Status}}' ) || true
    die "sandbox $1 has no published frontend/backend port — bring it up with:
    cd $wt && make up"
  fi
  ( cd "$wt" \
    && BACKEND_URL="http://localhost:$bp" FRONTEND_URL="http://localhost:$fp" \
       SMOKE_SKIP_LLM="${SMOKE_SKIP_LLM:-1}" \
       SMOKE_MIN_DOCUMENTS="${SMOKE_MIN_DOCUMENTS:-96}" \
       bash scripts/smoke.sh )
}

cmd_ls() {
  printf '%-5s %-22s %-28s %-7s %s\n' SLOT SLUG BRANCH UP URLS
  git -C "$MAIN_ROOT" worktree list --porcelain | awk '/^worktree /{print $2}' \
  | while read -r wt; do
      [ -f "$wt/.sandbox" ] || continue
      ( set -a; . "$wt/.sandbox"; set +a
        up=$(cd "$wt" && docker compose ps --status running -q 2>/dev/null | wc -l | tr -d ' ')
        printf '%-5s %-22s %-28s %-7s %s\n' \
          "$SANDBOX_SLOT" "$SANDBOX_SLUG" \
          "$(git -C "$wt" rev-parse --abbrev-ref HEAD)" "$up svc" \
          "http://localhost:$FRONTEND_PORT  http://localhost:$BACKEND_PORT/docs" )
    done
  printf '\n  slot 0 (main, %s)\n       http://localhost:3000  http://localhost:8010/docs\n' "$MAIN_ROOT"
}

cmd_url() {
  local wt; wt=$(worktree_for "${1:?usage: sandbox.sh url <slug>}")
  ( set -a; . "$wt/.sandbox"; set +a
    echo "frontend http://localhost:$FRONTEND_PORT"
    echo "backend  http://localhost:$BACKEND_PORT/docs"
    echo "postgres localhost:$PG_PORT"
    [ "$SANDBOX_GRAPH" = 1 ] && echo "neo4j    http://localhost:$NEO4J_HTTP_PORT"
    true )
}

cmd_rm() {
  local slug=${1:?usage: sandbox.sh rm <slug> [--force]} force=0
  [ "${2:-}" = --force ] && force=1
  local wt; wt=$(worktree_for "$slug")
  # `next dev` rewrites tracked next-env.d.ts on every boot, so any worktree that
  # ran the frontend is dirty by it alone — excluded, or FORCE=1 becomes habit.
  if [ -n "$(git -C "$wt" status --porcelain -- ':(exclude)frontend/next-env.d.ts')" ] \
     && [ "$force" != 1 ]; then
    git -C "$wt" status --short -- ':(exclude)frontend/next-env.d.ts'
    die "uncommitted changes in $wt — commit or push them, or pass FORCE=1"
  fi
  # Project-scoped: removes sangam-<slug>_pgdata, cannot touch sangam_pgdata.
  ( cd "$wt" && docker compose down -v --remove-orphans --rmi local ) || true
  # worktree remove runs its own dirty check, ignoring the pathspec above. Restore
  # that one generated file rather than --force, which discards real work too.
  git -C "$wt" checkout -- frontend/next-env.d.ts 2>/dev/null || true
  if [ "$force" = 1 ]; then
    git -C "$MAIN_ROOT" worktree remove --force "$wt"
  else
    git -C "$MAIN_ROOT" worktree remove "$wt"
  fi
  git -C "$MAIN_ROOT" branch -d "sandbox/$slug" 2>/dev/null \
    || echo "branch sandbox/$slug kept (unmerged). Delete it with: git branch -D sandbox/$slug"
  echo "sandbox $slug removed"
}

case "${1:-}" in
  new)    shift; cmd_new "$@" ;;
  ls)     cmd_ls ;;
  url)    shift; cmd_url "$@" ;;
  verify) shift; cmd_verify "$@" ;;
  rm)     shift; cmd_rm "$@" ;;
  *)      sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
