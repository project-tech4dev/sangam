# Parallel feature sandboxes

One feature at a time was the default because the local stack is a single compose
project on fixed ports. A sandbox is a second, third or fourth complete copy of it —
its own worktree, its own containers, its own Postgres — so an unfinished migration in
one costs nothing in another.

```bash
make sandbox-new SLUG=rls BASE=HEAD    # stand one up
make sandbox-ls                        # see them all
make sandbox-verify SLUG=rls           # smoke that one stack
make sandbox-rm SLUG=rls               # remove every trace of it
```

`BASE=HEAD` is needed only until this branch merges; after that `origin/master` is the
default and carries the harness.

## Why it is nearly free

Compose derives the project name from the directory basename. A worktree at
`../sangam-rls` is therefore project `sangam-rls`, and its containers, its default
bridge network and all four named volumes namespace themselves. There is no `-p`
anywhere, and `docker-compose.yml` must never gain a `name:` key, a `container_name:`,
or an absolute bind-mount path — each would silently break the isolation this rests on.

What actually collided was five fixed host ports and one browser-facing literal. Those
are now `${VAR:-<the current literal>}` tokens, so the main checkout with no sandbox
variables set produces a byte-identical `docker compose config`.

## Ports

Slot *N*, port = base + 10*N*. Slot 0 is the main checkout and keeps the bare literals.

| | slot 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| frontend | 3000 | 3010 | 3020 | 3030 |
| backend | 8010 | 8020 | 8030 | 8040 |
| postgres | 5433 | 5443 | 5453 | 5463 |
| neo4j http / bolt | 7474 / 7687 | 7484 / 7697 | 7494 / 7707 | 7504 / 7717 |

All five are reserved whether or not `GRAPH=1` is used, so adding the graph to a running
sandbox later can never collide with a neighbour.

The formula only ever produces ports ending `0/3/4/7`, which is why it misses `5432`
(dalgo-postgres) and `8000` (airbyte-proxy) — both held on a typical machine here.
**Slot 7 is the one exception**: its backend port is 8080. The allocator probes the port
and skips the slot while something holds it, jumping 6 → 8. That is correct behaviour,
not a bug, and there is deliberately no denylist file — a list would drift, which is the
thing deriving the slot avoids.

## Where the slot comes from

There is no registry. A free slot is the lowest *N* absent from the union of three
sources, each of which dies with the thing it describes:

1. **Each worktree's own `.sandbox` manifest**, found via `git worktree list`. Gitignored,
   non-secret, and deleted by `git worktree remove`, so it cannot outlive its worktree.
2. **Live compose projects** matching `sangam-*`, whose postgres container's published
   `5432/tcp` binding gives the slot back. This catches a stack whose directory was
   deleted by hand; a plain `docker compose down` leaves no containers but keeps the
   pgdata volume, which is why source 1 is needed and this alone is not enough.
3. **An actual connect probe** on all five ports. Ground truth, and unlike unprivileged
   `lsof` it sees ports held by other users — which is how slot 7 gets skipped.

A `mkdir`-based lock in the common git dir spans allocation through writing `.sandbox`,
so two `sandbox-new` runs at once cannot land on the same slot.

## The `.env`, and why nothing reads it

`.claude/settings.json` denies reading `.env`. The harness is built so that restriction
is never even approached: it `cp`s the main `.env` and appends a fenced override block.
Compose takes the **last** assignment of a duplicate key, so the block wins without
anything in the toolchain parsing a secret. The slot and ports go to a separate
non-secret `.sandbox` file, which is the only thing `ls`, `url`, `rm` and allocation read.

The block sets the five ports, `COMPOSE_FILE`, `COMPOSE_PROFILES`, `NEXT_PUBLIC_API_URL`,
an exact-origin `ALLOWED_ORIGINS`, an empty `NEO4J_URI`, `LOCAL_DB_HOST=postgres`, per-slot
Langfuse/LangSmith names, and a smaller `DB_POOL_MAX_SIZE` / `MAX_PARALLEL_RESEARCH`.

`NEO4J_URI` is read in compose as `${NEO4J_URI-bolt://neo4j:7687}` — a bare `-`, not `:-`.
A sandbox sets it *empty* to disable the graph, and `:-` would treat set-but-empty as
unset and hand the default straight back.

Any key `.env.example` has gained and the copy lacks is appended empty, so an older
sandbox does not silently miss a new variable.

### Supabase

If either `NEXT_PUBLIC_SUPABASE_URL` or `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` is unset
or empty, **both** get placeholders. `createServerClient` non-null-asserts each and
`@supabase/ssr` throws the same "URL and Key are required" on either being empty, so a
real URL beside an empty key 500s every page exactly like no config at all. Replacing
both keeps the pair coherent rather than mixing a real project with a fake key.

Sign-in does not work against placeholders — middleware redirects `/ask`, `/import` and
`/protected` to the login page — and even with real values inherited, the Supabase
project's redirect allowlist will not contain `localhost:3010`. A feature that genuinely
needs sign-in adds its sandbox port to Supabase by hand. Everything else renders.

## The database

```
up -d --wait postgres       (only postgres; the backend is deliberately not up yet)
  → pg_dump -Fc slot 0      (BEFORE touching the target, so a failure costs nothing)
  → DROP DATABASE … WITH (FORCE) + CREATE
  → pg_restore
```

The drop is necessary: the fresh `pgdata` volume has **already** run `db/init` on its
first boot, so the target is not empty and a plain restore aborts on the first
`CREATE TABLE`. `DROP`/`CREATE` beats `pg_restore --clean --if-exists` because all three
init scripts are database-scoped, whereas `--clean` emits a bare `DROP EXTENSION vector`
that fails while pgvector columns still depend on it.

It is safe only because the backend is not up yet — **that sequencing is load-bearing**.
`-U`/`-d` come from the container's own `$POSTGRES_USER`/`$POSTGRES_DB`, so slot 0 need
not be `sangam`/`sangam`.

Every failure path — slot 0 down, dump failed, restore failed — falls back to the
baseline plus `make up` (which migrates) plus `make seed`, and relaxes the smoke
documents floor to 0, because `make seed` creates no `documents` rows. `CLONE=0` takes
that path on purpose.

A clone cannot be greener than its source. When judging `sandbox-verify`, the question
is whether it fails *exactly* what the main stack's `make smoke` fails.

## Guards

Each fails closed, in code rather than by remembering:

- **`ENV=staging` in a sandbox** → `$(error)` at parse time, before any recipe runs.
  This is the highest-value guard here: the staging overlay passes an explicit `-f`,
  which overrides the sandbox's `COMPOSE_FILE` and silently drops
  `docker-compose.sandbox.yml`. Neo4j un-profiles and starts, while the backend points
  at the live managed Postgres with a half-built migration in the tree.
- **A host target against a stopped stack** → `require_running`, rather than silently
  probing slot 0's ports and reporting another stack's health as this one's.
- **A worktree with no `.env`** → `require_env`, which names the cause instead of
  compose's misleading "no such service: postgres".
- **A base ref predating the harness** → a preflight `cat-file` check, before the
  worktree is created rather than ten minutes into a build.
- **A dirty worktree on teardown** → refused, with the files listed. `FORCE=1` overrides.
- **A tenth sandbox** → refused, with the teardown hint.

## Teardown

`make sandbox-rm SLUG=x` runs `docker compose down -v --remove-orphans --rmi local` from
inside the worktree. Because that is project-scoped it removes `sangam-x_pgdata` and
**cannot** touch `sangam_pgdata`; the shared npm cache volume is declared `external`, so
`-v` leaves it alone. Then the worktree goes, and the branch with it unless it is
unmerged, in which case the `git branch -D` line is printed rather than run.

**The database goes with it.** Anything a sandbox ingested is gone unless committed or
dumped first.

## Cost

The first sandbox is 6-10 minutes: two image builds plus `npm ci` into an empty volume.
Later ones are ~2 minutes, because `sangam_shared_npm_cache` is external and shared and
Docker's layer cache is warm.

Memory, not ports, is the real ceiling. Roughly 1.5 GB per stack, plus ~768 MB with
`GRAPH=1` — which is why the graph is off by default. Three are comfortable on 16 GB and
four is the ceiling.

## What this deliberately does not do

- **No shared-Postgres mode.** `CREATE DATABASE … TEMPLATE` is near-instant and far
  lighter on RAM, but needs source and target in one cluster, which per-sandbox
  containers are not. It is the documented escape hatch if N containers prove too heavy.
- **No concurrency inside one session.** `EnterWorktree` moves the one session. A
  terminal per sandbox is the honest answer.
- **No fanning one feature across slots.** One agent per sandbox, one feature each;
  splitting a single feature across agents loses the API contract at many times the cost.
- **No port denylist file.** The probe is authoritative.
- **No remote or cloud sandboxes.** Local Docker only.
