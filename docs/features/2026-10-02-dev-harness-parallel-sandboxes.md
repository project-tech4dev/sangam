# Dev harness: parallel feature sandboxes

Status: approved 2026-10-02, implementation in progress on
`feat/dev-harness-parallel-sandboxes`. Milestones below map one-to-one onto PRs; each
carries its own exit gate.

## Context

Sangam's local stack is a single fixed-port Docker compose project: frontend `3000`,
backend `8010`, Postgres `5433`, Neo4j `7474`/`7687`, compose project `sangam` (auto-named
from the directory). Exactly one copy can run at a time, so working on two features means
stashing, rebuilding, and re-seeding between them — and anything half-finished in the
database is lost on the switch.

The ask: a `/sandbox`-style skill, invoked with an idea, that stands up an isolated
worktree + stack on its own ports with its own database, then hands the idea to an agent
working inside it. Target: 3+ features in flight at once.

## Confirmed decisions

| Question | Answer |
|---|---|
| Worktree location | Sibling dirs — `../sangam-<slug>/` |
| Neo4j per sandbox | Off by default; `--graph` opts in (graph disables itself cleanly) |
| After the stack is up | Stand up, verify, then start an agent on the idea in that worktree |
| Database seeding | Clone slot 0 via `pg_dump`, falling back to init + migrate + seed |

## Observed starting state

- `docker compose ls` → one project, `sangam`, config `/Users/siddhantsingh/Documents/sangam/docker-compose.yml`
- Containers follow the default `sangam-<service>-1` naming (no `container_name:` overrides),
  so `COMPOSE_PROJECT_NAME` should namespace containers *and* named volumes cleanly.
  Fixed host ports are the collision to solve.
- Other local stacks already hold ports: Airbyte and Langfuse compose projects exist on this
  machine, so the offset scheme must avoid their ranges.

## Constraints the harness must respect (confirmed)

**Ports.** `5432` and `8000` are already taken on this machine by `dalgo-postgres` and
`airbyte-proxy` — compose comments say so explicitly. Slot 0 holds 3000/8010/5433/7474/7687.
Any offset scheme must dodge all of these.

**A fresh database is baseline + migrate, in that order.** `db/init/02_schema.sql` is 42 bare
`CREATE TABLE`s with no `IF NOT EXISTS` — it runs once against an empty DB or it aborts.
Migrations (`0001`–`0020`) carry everything after. The backend's `_verify_sql_catalog` *raises*
when the catalog's 40 tables don't match the DB's, and `make up` now uses `--wait`, so
**migrations must land before the backend is considered up** or the stack fails to start.

**The frontend 500s without Supabase vars.** `frontend/lib/supabase/middleware.ts` throws
without `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, and compose does
not currently pass them. A sandbox that boots the frontend must supply them — dummy values are
enough to get 200s.

**`make` echoes recipe lines and has leaked a DB password once.** Any new target touching a
connection string gets an `@` prefix, following `make evals` / `make client-docs`.

**`ENV=staging` must stay untouched.** `make up ENV=staging` points the local stack at the
managed Postgres that serves the deployed app. The sandbox overlay must never be able to
combine with it — guard like the existing `require_local`.

**Supabase Storage is global.** `fetch_document` archives to the shared cloud bucket regardless
of which Postgres the backend is on, so a sandbox running ingest still writes to shared storage.
Worth stating, not worth solving here.

**Precedent for throwaway databases already exists** (`.memory/STATE.md`): `CREATE DATABASE
migratetest`, apply `db/init/*.sql`, run against it with an overridden `DATABASE_URL`, drop
afterwards. The harness generalises this.

## Skill conventions to follow

Project skills live in `.agents/skills/<name>/SKILL.md` and are symlinked from
`.claude/skills/<name>`. Frontmatter is exactly two fields, `name` (must equal the directory
name) and `description` (double-quoted, one line, shaped `INVOKE THIS SKILL when <trigger>.
Covers <scope>. Uses the <X> CLI tool.`). Bodies use pseudo-XML section tags, not `#` headings,
and ship no helper scripts — the mechanism belongs in `scripts/` and `make`, per the project's
own "constraints never live in skills" rule.

## What actually collides

Good news first: compose declares no `name:`, no `container_name:`, and no `networks:`, and
`COMPOSE_PROJECT_NAME` appears nowhere in the repo. The project name is derived from the
directory basename, so a worktree at `../sangam-<slug>/` gets its own containers, its own
default bridge network, and its own `pgdata` / `neo4jdata` / `frontend_node_modules` /
`frontend_next` volumes **for free**. The compose object graph needs no renaming.

That leaves a short, specific list. **All line numbers below are verified against `master`**,
which is what sandbox worktrees branch from.

**Five fixed host ports** — the stack simply won't start twice:
`docker-compose.yml:115` `"3000:3000"`, `:84` `"8010:8000"`, `:13` `"5433:5432"`,
`:33` `"7474:7474"`, `:34` `"7687:7687"`.

**One browser-facing literal** — the stack starts but is wrong: `docker-compose.yml:110`
`NEXT_PUBLIC_API_URL: http://localhost:8010` is baked into the bundle at build time, so
sandbox B's UI would call sandbox A's API. (`:76` `ALLOWED_ORIGINS` is already
`${ALLOWED_ORIGINS:-…}` and needs no compose change — only a value.)

**One destructive cross-stack bug, which exists today:** `Makefile:247` is literally
`docker volume rm sangam_pgdata`. Run `make db-upgrade` from any worktree and it deletes the
*main* stack's database. This gets fixed regardless of the rest of the harness.
(`db-reset` at `:221` is already safe — `docker compose down -v` is project-scoped.)

**Host-side targets pin the default ports:** `make smoke` (`:137`) never passes the
`BACKEND_URL` / `FRONTEND_URL` that `scripts/smoke.sh:8-9` already honours; `evals` (`:149`),
`client-docs` (`:158`) and `dev-backend` (`:264`) pin `localhost:5433`; `db-backup`
(`:236-237`) curls `localhost:8010`; `dev-frontend` (`:269`) pins `localhost:8000`.

**Smoke has three exact-equality assertions**, not one: `scripts/smoke.sh:55-57` asserts
`scores: d['total'] == 8`, `grants: d['total'] == 4` and `documents: d['total'] >= 96`. A
`pg_dump` clone of a slot 0 that has ever run Sangam Import fails the first two; a
baseline+seed sandbox has **no** documents at all and fails the third. All three need
relaxing for one script to serve both database paths.

**A fresh worktree is missing everything gitignored:** no `.env` (so no
`COMPOSE_PROFILES=localdb`, which means **Postgres never starts**), no `.agents/` or
`.claude/skills/`, no `backend/.venv`.

**Not a problem after all:** compose at `:111-112` *already* forwards
`NEXT_PUBLIC_SUPABASE_URL` / `..._PUBLISHABLE_KEY`, and `:140` already declares a
`frontend_npm_cache` volume. The ~20 bare `docker compose` calls are correctly scoped by the
directory-derived project name, so they need no `-p`; they are a pre-existing `ENV=staging`
issue and several (`db-push-remote` at `:196`) are *deliberately* bare. Out of scope.

**Shared-by-design, worth knowing not fixing:** Supabase Storage buckets, and
`LANGSMITH_PROJECT` / `LANGFUSE_TRACING_ENVIRONMENT` merging every sandbox's traces into one
bucket unless varied per slot.

## What to borrow from dalgo

`dalgo-core` itself turns out to have **no** Docker, port, or database tooling — its own
`CLAUDE.md` calls it "the orchestration/harness repo… contains no application code." Port
conflicts over there are resolved by a human editing a number and leaving a comment. So the
borrowings come from its siblings, and most of the good ones are from the vendored Langfuse
checkout rather than Dalgo's own code.

**Take these:**

1. **`additionalDirectories` in `.claude/settings.json`** (`dalgo-core`), which Dalgo uses for
   `../DDP_backend`, `../webapp_v2`, `../.dalgo-worktrees`. Scoped to **handoff mode 3 only**:
   modes 1 and 2 don't need it (`EnterWorktree` moves the session's cwd; a new terminal starts
   inside the worktree), but a background subagent pinned from the main checkout does. Dalgo's
   entries are literal paths and glob support is unverified, so M4 writes the literal
   `../sangam-<slug>` into the **main** checkout's `.claude/settings.local.json` — and only if
   mode 3 is kept; drop the borrow with it otherwise.
2. **`ports: !override`** (from a local edit to `langfuse/docker-compose.override.yml`). Compose
   *appends* port lists across override files rather than replacing them, so a naive override
   silently keeps the conflicting binding. If we ever use an overlay file instead of `${VAR:-}`
   interpolation, this tag is mandatory.
3. **`compose up -d --wait --wait-timeout <n>` plus `trap dump_diagnostics ERR`**
   (`langfuse/scripts/agents/start-cursor-cloud.sh`). Replaces hand-rolled sleep loops, and on
   any failure dumps `compose ps -a` + per-service logs. `Makefile:174`'s `sleep 5` in
   `db-reset` is the thing this replaces.
4. **`ensure_env_defaults()`** (`langfuse/.agents/setup`) — appends only the keys a `.env` is
   *missing* from the example file. It reads `.env.example`, never `.env`, so it sits exactly
   inside our read restriction. **In M2**, as the generalisation of the Supabase-placeholder
   `grep -qs` check: the same mechanism keeps an existing sandbox current when a new variable
   lands in `.env.example`.
5. **The "What's Intentionally NOT Included" table** (`dalgo-core/README.md`) — a negative-space
   section listing what the harness deliberately won't do, each with a one-line reason. Realised
   as *What this deliberately does not do*, below.

**Take, but not here:** the **`127.0.0.1:` prefix on every published port**
(`langfuse/docker-compose.dev.yml`) — loopback-only, which this stack wants given the backend
has no auth. It cannot ride in M1, whose exit gate is a byte-identical `docker compose config`;
it changes the binding for slot 0 too. Its own PR, or M5.

**Noted, not taken:**

- **`CREATE DATABASE … TEMPLATE`** (`DDP_backend/ddpui/core/trial/warehouse_provision.py`) is a
  genuinely better clone mechanism than `pg_dump` — near-instant, with a `pg_terminate_backend`
  retry loop for the one real race, and an empirical note (verified 2026-07-29, PG 15.16) that
  concurrent clones from one source do *not* serialize. It needs source and target in the **same
  cluster**, which per-sandbox Postgres containers aren't. It only becomes available if we
  switch to one shared Postgres with a database per sandbox — lighter on RAM, but it breaks the
  self-contained-stack model and the `-U sangam -d sangam` hardcoding in `Makefile:165,182-185,
  204-208`. Flagged as the escape hatch if N containers prove too heavy.
- **`env -i` + `--env-file /dev/null` hermetic compose** (`start-cursor-cloud.sh`) — our design
  depends on compose reading the per-worktree `.env`, so sealing interpolation would defeat it.
- **Dalgo's own worktree automation** is prose in a skill, not a script, and is multi-repo. The
  single-repo case is simpler.

**One warning worth heeding,** from `dalgo-core/.claude/skills/executing-feature-plans`: *"Do
not split implementation across subagents… coding is tightly coupled, agents coordinate poorly
in real time, and you'd lose the API contract while paying ~15× the tokens."* That is about
splitting *one* feature across agents. One agent per sandbox, one feature each, is the opposite
and is fine — but it argues against the harness ever fanning a single feature out across slots.

## Approach

Four pieces. Nothing renames a compose object; the directory basename does that work.

**1. Slot arithmetic.** Slot `N ∈ 1..9`, every port `= base + 10N`. Slot 0 is the main
checkout and keeps the bare literals.

| | slot 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| frontend | 3000 | 3010 | 3020 | 3030 |
| backend | 8010 | 8020 | 8030 | 8040 |
| postgres | 5433 | 5443 | 5453 | 5463 |
| neo4j http / bolt | 7474 / 7687 | 7484 / 7697 | 7494 / 7707 | 7504 / 7717 |

Validated against every container on this machine (`docker inspect`, running and exited) plus
live `lsof`: the formula only produces `…0/3/4/7`-ending ports, so it misses `5432`
(dalgo-postgres), `8000` (airbyte-proxy), `5434`/`3006` (langfuse), `3005` (deep-agent-app),
`8123`/`9000` entirely. **One collision: slot 7's backend port is 8080**, currently held. It
is not special-cased — the port probe skips slot 7 while 8080 is listening and allows it when
it isn't. A denylist file would be a registry that drifts, which is the thing being avoided.

**2. Slot allocation from three derived sources, no registry file.** Union of:

- **(a)** `git worktree list --porcelain` → each worktree's own `.sandbox` manifest (slot,
  slug, ports, project, graph flag). Gitignored, non-secret, and `git worktree remove` deletes
  it — it cannot outlive the worktree it describes.
- **(b)** `docker compose ls -a --format json` → projects matching `^sangam-` → `docker
  inspect <proj>-postgres-1` for its `5432/tcp` host binding → `slot = (port−5433)/10`. Catches
  a stack whose worktree directory was hand-deleted.
- **(c)** `nc -z 127.0.0.1 <port>` on all five of the slot's ports. Ground truth, and
  owner-independent unlike unprivileged `lsof`. Catches foreign occupants like 8080.

Lowest `N` absent from (a) ∪ (b) with all five ports free per (c). (a) and (b) catch
claimed-but-stopped stacks; plain `docker compose down` leaves no containers but keeps the
pgdata volume, which is exactly why (a) is needed and (b) alone is not. A `mkdir`-based lock
in `$GIT_COMMON_DIR` is held from allocation until `.sandbox` is written; `git worktree prune`
runs in the preflight.

Deliberately: the slot lives in `.sandbox`, **not** in each worktree's `.env`. Same
derivation, but nothing in the toolchain ever reads a `.env` — which keeps the design clear of
the `.claude/settings.json` deny rules rather than merely technically outside them. `.env` is
write-only to this harness: `cp`'d, then appended to.

**3. Compose parameterization — eight tokens, every default the current literal.**

```diff
-      - "5433:5432"                                 # postgres
+      - "${PG_PORT:-5433}:5432"
-      - "7474:7474"  /  - "7687:7687"               # neo4j
+      - "${NEO4J_HTTP_PORT:-7474}:7474"  /  - "${NEO4J_BOLT_PORT:-7687}:7687"
-      NEO4J_URI: bolt://neo4j:7687                  # backend
+      NEO4J_URI: ${NEO4J_URI-bolt://neo4j:7687}
-      - "8010:8000"                                 # backend
+      - "${BACKEND_PORT:-8010}:8000"
-      NEXT_PUBLIC_API_URL: http://localhost:8010    # frontend
+      NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:${BACKEND_PORT:-8010}}
-      - "3000:3000"                                 # frontend
+      - "${FRONTEND_PORT:-3000}:3000"
```

`NEO4J_URI` uses `-`, not `:-`, on purpose: a sandbox sets it *empty* to disable the graph, and
`:-` would treat set-but-empty as unset and hand the default back. The nested default in
`NEXT_PUBLIC_API_URL` derives it from `BACKEND_PORT` so the two cannot drift — same construct
already proven at `docker-compose.yml:56`. **Both healthchecks stay untouched**: they probe
`localhost:8000` / `localhost:3000` *inside* the container, and parameterizing them is the
classic error. No `name:` key, no `-p`, no `container_name:` — ever.

New `docker-compose.sandbox.yml`, selected via `COMPOSE_FILE` in the sandbox's own `.env` so
bare `docker compose` inside the worktree picks it up with no `-f` to remember:

- `neo4j: profiles: ["graph"]` — off per sandbox (768 MB of heap+pagecache and two ports each).
  The profile lives in the **overlay**, not the base, because slot 0's `.env` carries only
  `COMPOSE_PROFILES=localdb` and putting it in the base would stop the main stack's Neo4j.
- `backend: depends_on: neo4j: {condition: service_healthy, required: false}` — without
  `required: false`, `up` refuses to start the backend when the profile is inactive. `depends_on`
  is a mapping, so the base file's `postgres` entry survives the override.
- `frontend_npm_cache: {name: sangam_shared_npm_cache, external: true}` — one shared npm cache
  across sandboxes, `external` so a teardown's `down -v` can never delete it. This is the main
  cold-start lever; without it every sandbox does a cold `npm ci` from the network.

Alternatives rejected: `profiles` in the base file breaks slot 0; `--scale neo4j=0` fails the
backend's `service_healthy`; an alpine sleeper still burns a container and a healthcheck.

**4. `scripts/sandbox.sh`** — `new | ls | url | verify | rm`, resolving the main checkout via
`git rev-parse --git-common-dir` so it works when invoked from inside a sandbox.

`new <slug> [--graph] [--base <ref>] [--no-clone]`: prune → lock → allocate → `git worktree
add -b sandbox/<slug> ../sangam-<slug> origin/master` → write `.env` + `.sandbox` → symlink
tooling → build → bring up → clone the DB → `make up` → verify → print URLs.

- **The env overlay**: `cp -p` the main `.env`, `chmod 600`, then append a clearly-fenced
  override block. Compose takes the **last** assignment of a duplicate key, so the block wins
  without this script parsing a secret. The block sets `COMPOSE_FILE`, `COMPOSE_PROFILES`, the
  five ports, `NEXT_PUBLIC_API_URL`, `ALLOWED_ORIGINS` (exact origin, and `ALLOWED_ORIGIN_REGEX=`
  cleared — a trailing `$` in a compose `.env` value is interpolation-ambiguous), `NEO4J_URI=`,
  `LOCAL_DATABASE_URL=` / `LOCAL_DB_HOST=postgres` (so a managed URL is never inherited),
  per-slot `LANGSMITH_PROJECT` / `LANGFUSE_TRACING_ENVIRONMENT`, and smaller
  `DB_POOL_MAX_SIZE=5` / `MAX_PARALLEL_RESEARCH=3`. A missing main `.env` is a hard error
  pointing at `cp .env.example .env`, not a silent boot with no Postgres.
  Placeholder Supabase values are appended **only** if `grep -qs '^NEXT_PUBLIC_SUPABASE_URL=..*'`
  finds nothing — `grep -q` prints nothing, so this decides without exposing the value.
- **Tooling symlinks**: `.agents/` and `skills-lock.json` symlinked (not copied) so one
  `npx skills` update reaches every sandbox; `.claude/skills/*` copied with `cp -RPn` to keep
  each entry's relative target and not clobber tracked first-party skills;
  `backend/.venv` symlinked so `make evals` / `client-docs` have a host interpreter.
  **This needs a `.gitignore` fix first.** `.gitignore:21` is `.agents/` and `:8` is `.venv/`,
  and a trailing slash matches **directories only** — git treats a symlink as a file. Verified
  in a scratch repo: with those patterns, `ln -s realdir .agents` shows as `?? .agents`. Left
  alone, every sandbox is dirty from birth and `rm` refuses without `--force` every time. Drop
  both trailing slashes (`.agents`, `.venv`), which matches files and directories alike.
- **The database.** `up -d --wait postgres` only, then `pg_dump -Fc` slot 0 **before** touching
  the target so a failure costs nothing, then `DROP DATABASE … WITH (FORCE)` + `CREATE`, then
  `pg_restore`. The drop is necessary because the fresh `pgdata` volume has *already* run
  `db/init` on first boot, so the target is **not empty** and a plain restore aborts on the
  first `CREATE TABLE`. `DROP`/`CREATE` beats `pg_restore --clean --if-exists` because all
  three init scripts are database-scoped, whereas `--clean` emits a bare `DROP EXTENSION vector`
  that fails while pgvector columns still depend on it. Safe only because the backend is not up
  yet — that sequencing is load-bearing.
  Every failure path (slot 0 down, dump failed, restore failed) falls back to **baseline +
  `make up` + `make seed`** and relaxes the documents floor to 0, because `make seed` creates no
  `documents` rows. `-U`/`-d` come from the container's own `$POSTGRES_USER`/`$POSTGRES_DB`, so
  slot 0 need not be `sangam`/`sangam`.
- **Reuse, not reimplementation**: bring-up is `make up` (already three-phase —
  `postgres` → `migrate ENV=local` → everything, with `--wait` — because `_verify_sql_catalog`
  raises on drift); verification is `scripts/smoke.sh` with `BACKEND_URL`/`FRONTEND_URL`, and
  the ports are read from `docker compose port frontend 3000` rather than from a file, so they
  cannot drift from what the stack actually published.
- `rm` refuses a dirty worktree without `--force`, then `docker compose down -v --remove-orphans
  --rmi local` (project-scoped, so it removes `sangam-<slug>_pgdata` and **cannot** touch
  `sangam_pgdata`), `git worktree remove`, and `git branch -d` with a kept-if-unmerged notice.

## Milestones

All of this lands on a **fresh branch off `origin/master`** — not the current
`perf/scope-copilotkit-to-agent-routes`. Step 0, before any code: commit this plan as
`docs/features/2026-10-02-dev-harness-parallel-sandboxes.md` on that branch.

**M1 — Parameterize, changing nothing.** The eight compose tokens;
`docker-compose.sandbox.yml`; `PROJECT = $(shell docker compose config --format json | …)`
replacing the literal in `Makefile:247`; a `PG_HOST_PORT`/`BACKEND_HOST_PORT`/`FRONTEND_HOST_PORT`
block read from `docker compose port` and threaded through `smoke`, `evals`, `client-docs`,
`db-backup`, `dev-backend`, plus a `require_running` guard; the three `smoke.sh` assertion
relaxations with `SMOKE_MIN_DOCUMENTS`; `.env.example` documents the new keys.
*Exit gate:* in the main checkout, `docker compose config` is byte-identical before and after
(diff across a stash), `"name": "sangam"` and the five published ports unchanged;
`make down && make up && make smoke` green. **No sandbox code in this PR** — it must be
provably a no-op.

**M2 — `sandbox.sh` and the `make sandbox-*` targets.** The script, slot allocation, the lock,
worktree add, the env overlay, tooling symlinks, bring-up ordering, the clone and its fallback;
`sandbox-new` / `-ls` / `-verify` / `-rm`; `.sandbox` in `.gitignore`.
*Exit gate:* three sandboxes live at once on slots 1/2/3; `make sandbox-verify` green on all
three with `SMOKE_SKIP_LLM=1`; `make smoke` in the main checkout still green; `docker volume ls
| grep pgdata` shows four distinct volumes; `make sandbox-rm SLUG=<b>` leaves the rest green and
`sangam_pgdata` intact. Exercise the fallback once: `sandbox-new SLUG=cold --no-clone` green.
And — the assertion that catches the symlink bug above and anything else `link_tooling` leaks —
**`git status --porcelain` is empty in a freshly created sandbox**; confirm with
`git check-ignore -v .agents backend/.venv` inside it.

**M3 — Guards, each demonstrated failing closed.** `ENV=staging` refused at parse time in a
sandbox; `require_running`; a new `require_env` on `up` so a worktree with no `.env` fails with
the `cp .env.example` instruction instead of compose's misleading "no such service: postgres"
(which is what an unset `COMPOSE_PROFILES` produces today); `rm` refuses a dirty tree and lists
the files; slot exhaustion prints the teardown hint.
*Exit gate:* `make migrate ENV=staging` in a sandbox errors before any recipe runs; `make smoke`
with that stack down says "needs this stack up" instead of silently probing slot 0's ports —
this is the one that would otherwise green-light a broken sandbox; a tenth `sandbox new` is
refused.

**M4 — The skill and the docs.** The `.gitignore` per-entry change;
`.claude/skills/sandbox/SKILL.md`; `docs/SANDBOX.md` with the port table, the clone/fallback
decision tree and the memory budget; CLAUDE.md quick-reference lines next to the existing port
documentation.
*Exit gate:* from a clean session, "try `<idea>` in a sandbox" triggers the skill, which runs
`make sandbox-new`, reports real URLs, enters the worktree and starts on the idea. In a fresh
clone, `git status` shows `.claude/skills/sandbox/SKILL.md` tracked and the installed skills
still ignored.

**M5 (optional) — Compose hygiene.** The bare `docker compose` calls → `$(COMPOSE)` only where
`ENV` should matter, with a one-line comment at each deliberate exception; `DEV_BACKEND_PORT`
for host-mode `dev-backend`/`dev-frontend`.
*Exit gate:* `make seed ENV=staging` and `make psql ENV=staging` behave as documented; every
remaining bare `docker compose` in the Makefile carries a comment saying why.

## The skill

`.claude/skills/sandbox/SKILL.md`, following the house conventions above — two frontmatter
fields, pseudo-XML sections, no helper scripts (the mechanism is `scripts/sandbox.sh` and
`make`).

Making it tracked needs a **per-entry** exclusion, because git never descends into an excluded
directory and so `!.claude/skills/sandbox/` after `.claude/skills/` could never match:

```diff
-.claude/skills/
+.claude/skills/*
+!.claude/skills/sandbox/
```

It must be a **real file**, not the usual symlink into `.agents/` — `.agents/` stays ignored and
a committed symlink's target would not travel. That is the right distinction anyway (first-party
skill vs. installed tooling); note the divergence in the file's own header so nobody "fixes" it.

Sections: `<oneliner>`; `<when_to_use>` (use a sandbox when the idea touches the schema, the
seed, or compose; a one-file frontend change is cheaper on a branch in the main checkout);
`<creating>` (`make sandbox-new SLUG=x [GRAPH=1] [BASE=HEAD]`, derive the slug from the idea,
**never invent a slot number**, report slot/URLs/whether the DB was cloned or rebuilt);
`<handing_off_the_idea>`; `<inspecting>` (`make sandbox-ls`, `sandbox-verify`, and the fact that
inside the worktree every ordinary target already targets that stack); `<teardown>`;
`<enforced_elsewhere>`; `<failure_modes>`.

Per the project's "constraints never live in skills" rule, `<enforced_elsewhere>` names each
enforcer rather than asking the model to behave: `ENV=staging` → the Makefile's `$(error)`;
stack-down host targets → `require_running`; a tenth slot → `allocate_slot`; a dirty worktree →
`cmd_rm`. It carries only the facts that *aren't* enforceable: ~1.5 GB of Docker memory per
stack (+0.8 GB with `GRAPH=1`), so three is comfortable and four is the ceiling on 16 GB; and
the database is a copy, so nothing a sandbox does reaches the main stack and nothing survives
`sandbox-rm`.

**Handoff.** Three modes, and the skill states the limitation plainly rather than pretending:

1. *One idea, this session (default)* — `EnterWorktree path="../sangam-<slug>"`, which is legal
   because `git worktree add` registered the path. Never `ExitWorktree action:"remove"` (it
   refuses a `path`-entered worktree); teardown is `make sandbox-rm`.
2. *Three or more concurrent (the stated target)* — `EnterWorktree` moves the one session, so it
   **cannot** deliver concurrency. Print a copy-paste line per sandbox:
   `cd ../sangam-<slug> && claude "<the idea>"`. This is the only route to genuinely parallel
   agents.
3. *Fire-and-forget* — a background subagent pinned to the worktree, checked on via
   `ListAgents` / `SendMessage`.

The brief in all three names the slot, branch, base, the three URLs, that Postgres is a private
clone so destructive SQL and migrations are fine, that Neo4j is off and graph features
self-disable, that `make` targets in that directory already hit that stack, and that nothing is
ever run with `ENV=staging`.

## Critical files

| File | Change |
|---|---|
| `docker-compose.yml` | 8 tokens → `${VAR:-<current literal>}` at `:13`, `:33-34`, `:80`, `:84`, `:110`, `:115` |
| `docker-compose.sandbox.yml` | new — the neo4j profile, `required: false`, the external npm cache |
| `scripts/sandbox.sh` | new — `new`/`ls`/`url`/`verify`/`rm` |
| `Makefile` | `PROJECT` + `$(PROJECT)_pgdata` at `:247`; the `*_HOST_PORT` block + `require_running` threaded through `:137`, `:149`, `:158`, `:236-237`, `:264`; the `ENV=staging` guard; four `sandbox-*` targets (`@`-prefixed where they touch a connection string) |
| `scripts/smoke.sh` | `:55-57` — `== 8` → `>= 8`, `== 4` → `>= 4`, `96` → `${SMOKE_MIN_DOCUMENTS:-96}` |
| `.gitignore` | drop the trailing slashes on `:21 .agents/` and `:8 .venv/` (M2); per-entry `.claude/skills/*` + negation, add `.sandbox` (M4) |
| `.claude/settings.local.json` | M4, only if handoff mode 3 is kept — `additionalDirectories` entry per sandbox |
| `.claude/skills/sandbox/SKILL.md` | new |
| `docs/SANDBOX.md`, `CLAUDE.md`, `.env.example` | document it |

Reused rather than rebuilt: `make up`'s existing three-phase `--wait` bring-up;
`scripts/smoke.sh`'s `BACKEND_URL`/`FRONTEND_URL` (honoured since it was written, never passed);
`scripts/db-url.sh` (reads `docker compose config`, so it follows any project automatically);
the `require_local` guard as the model for the staging guard; `backend/app/db/migrate.py` via
`make migrate`.

## Verification

1. **M1 is a no-op.** `docker compose config > /tmp/after.yml`, `git stash`, same again to
   `/tmp/before.yml`, `diff` them — empty. Then `make down && make up && make smoke` green in
   the main checkout.
2. **Three at once.** `make sandbox-new SLUG=a`, `=b`, `=c`. `make sandbox-ls` shows slots 1/2/3
   with distinct ports. Open all three frontends; confirm each UI's network tab calls **its own**
   backend port (this is what catches a `NEXT_PUBLIC_API_URL` mistake, which smoke cannot).
   `make sandbox-verify SLUG=a|b|c` green.
3. **Isolation.** In sandbox `a`: `make psql` → `DROP TABLE orgs CASCADE`. Main checkout's
   `make smoke` still green; `make sandbox-verify SLUG=b` still green.
4. **Teardown is surgical.** `make sandbox-rm SLUG=a`; `docker volume ls | grep pgdata` still
   shows `sangam_pgdata` and the `b`/`c` volumes; `../sangam-a` gone from `git worktree list`;
   slot 1 reusable by the next `sandbox-new`.
5. **Guards.** In a sandbox: `make migrate ENV=staging` errors at parse time; `make down && make
   smoke` refuses instead of probing slot 0; `sandbox-rm` on a dirty tree refuses and lists the
   files; a tenth `sandbox-new` is refused with the teardown hint.
6. **Fallback path.** `make sandbox-new SLUG=cold --no-clone` with slot 0 down — must reach
   baseline + migrate + seed and pass smoke with the relaxed documents floor.
7. **The skill end to end.** New session, `/sandbox` with a real idea; confirm it allocates,
   reports real URLs, enters the worktree, and begins work there.

## What this deliberately does not do

- **No shared-Postgres mode.** `CREATE DATABASE … TEMPLATE` (Dalgo's
  `warehouse_provision.py`) is near-instant and far lighter on RAM, but needs source and target
  in one cluster, which per-sandbox containers aren't, and it breaks the self-contained-stack
  model plus the `-U sangam -d sangam` hardcoding. It is the documented escape hatch if N
  containers prove too heavy.
- **No concurrency inside one session.** See handoff mode 2 — a separate terminal per sandbox is
  the honest answer.
- **No fanning one feature across slots.** Per
  `dalgo-core/.claude/skills/executing-feature-plans`, splitting a single feature across agents
  loses the API contract at ~15× the tokens. One agent per sandbox, one feature each.
- **No sandboxed Supabase auth.** With placeholder values, `middleware.ts`'s
  `PROTECTED_PREFIXES` redirects `/ask` to `/auth/login`, and smoke's `curl -sL` would score the
  login page as a 200. With real values inherited, the project's redirect allowlist still won't
  contain `localhost:3010`. A feature needing real sign-in adds its sandbox port to Supabase by
  hand. Documented, not papered over.
- **No port denylist file.** The probe is authoritative; a list would drift.
- **No remote or cloud sandboxes.** Local Docker only.

## Risks

- **Cold start is 6–10 minutes** for the first sandbox (two image builds + `npm ci` into an empty
  `frontend_node_modules`), ~2 minutes warm. The shared npm cache is the main lever. Tell the
  user before starting, not after.
- **Memory, not ports, is the real ceiling on 3+.** `DB_POOL_MAX_SIZE=5` and
  `MAX_PARALLEL_RESEARCH=3` in the override block help; `GRAPH=1` costs another ~768 MB each,
  which is the real reason graph-off is the default.
- **`ENV=staging` from a sandbox is worse than a wrong database.** The staging overlay passes an
  explicit `-f`, which **overrides `COMPOSE_FILE`** from the sandbox's `.env` and silently drops
  `docker-compose.sandbox.yml` — Neo4j un-profiles and starts, while the backend points at the
  live managed Postgres with a half-built migration in the tree. The `$(error)` guard is the
  highest-value line in M3.
- **`git worktree add` does not carry a dirty tree.** Neither `BASE=origin/master` nor
  `BASE=HEAD` brings uncommitted work. Commit before sandboxing work you want to build on.
- **An absolute path, a `name:` key, or a `container_name:` in compose would break isolation
  silently.** Every bind mount today is relative (`./backend/app`, `./seed`, `./db`,
  `./frontend`), which is the whole reason this works and why `MIGRATIONS_DIR=/srv/db/migrations`
  needs nothing. Worth a comment in `docker-compose.sandbox.yml`.
- **Slot 7 will look broken.** Its backend port is 8080, held on this machine; allocation jumps
  6 → 8 and that is correct. Say so in `<failure_modes>` or someone will "fix" it.
- **`make` echoes recipe lines** and has leaked a password once. Every new target touching a
  connection string gets `@`.
