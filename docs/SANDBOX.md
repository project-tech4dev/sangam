# Parallel feature sandboxes

A sandbox is a second, third or fourth complete copy of the local stack — its own
worktree, its own containers, its own Postgres — so an unfinished migration in one costs
nothing in another. `make sandbox-new SLUG=x` builds one and `make sandbox-rm SLUG=x`
removes every trace; `make help` lists the rest and `.claude/skills/sandbox/SKILL.md`
covers everyday use. This file is the internals.

## Why it is nearly free

Compose derives the project name from the directory basename. A worktree at
`../sangam-rls` is therefore project `sangam-rls`, and its containers, its default bridge
network and all four named volumes namespace themselves. There is no `-p` anywhere, and
`docker-compose.yml` must never gain a `name:` key, a `container_name:`, or an absolute
bind-mount path — each would silently break the isolation this rests on.

What actually collided was five fixed host ports and one browser-facing literal. Those are
now `${VAR:-<the current literal>}` tokens, so the main checkout with no sandbox variables
set produces a byte-identical `docker compose config`.

## Ports

Slot *N*, port = base + 10*N*. Slot 0 is the main checkout and keeps the bare literals.

| | slot 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| frontend | 3000 | 3010 | 3020 | 3030 |
| backend | 8010 | 8020 | 8030 | 8040 |
| postgres | 5433 | 5443 | 5453 | 5463 |
| neo4j http / bolt | 7474 / 7687 | 7484 / 7697 | 7494 / 7707 | 7504 / 7717 |

All five are reserved whether or not `GRAPH=1` is used, so adding the graph to a running
sandbox can never collide with a neighbour. The formula only produces ports ending
`0/3/4/7`, which is why it misses `5432` and `8000`, both commonly held here.

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
   `lsof` it sees ports held by other users — which is how slot 7, whose backend port
   would be 8080, gets skipped. A denylist file would drift, which is the thing deriving
   the slot avoids.

A `mkdir`-based lock in the common git dir spans allocation through writing `.sandbox`, so
two `sandbox-new` runs at once cannot land on the same slot.

## The `.env`, and why nothing reads it

`.claude/settings.json` denies reading `.env`, and the harness is built so that
restriction is never approached: it `cp`s the main `.env` and appends a fenced override
block. Compose takes the **last** assignment of a duplicate key, so the block wins without
anything parsing a secret. Slot and ports live in the separate non-secret `.sandbox` file,
which is all that allocation, `ls`, `url` and `rm` read.

`NEO4J_URI` is read in compose as `${NEO4J_URI-bolt://neo4j:7687}` — a bare `-`, not `:-`.
A sandbox sets it *empty* to disable the graph, and `:-` would treat set-but-empty as unset
and hand the default straight back.

Supabase is the one pair the block may invent. If *either* `NEXT_PUBLIC_SUPABASE_URL` or
`..._PUBLISHABLE_KEY` is unset or empty, **both** get placeholders: `@supabase/ssr` throws
on either being empty, so a real URL beside an empty key 500s every page exactly like no
config at all.

## The database

```
up -d --wait postgres       (only postgres; the backend is deliberately not up yet)
  → pg_dump -Fc slot 0      (BEFORE touching the target, so a failure costs nothing)
  → DROP DATABASE … WITH (FORCE) + CREATE
  → pg_restore
```

The drop is necessary: the fresh `pgdata` volume has **already** run `db/init` on its first
boot, so the target is not empty and a plain restore aborts on the first `CREATE TABLE`.
`DROP`/`CREATE` beats `pg_restore --clean --if-exists` because all three init scripts are
database-scoped, whereas `--clean` emits a bare `DROP EXTENSION vector` that fails while
pgvector columns still depend on it. It is safe only because the backend is not up yet —
**that sequencing is load-bearing**. `-U`/`-d` come from the container's own
`$POSTGRES_USER`/`$POSTGRES_DB`, so slot 0 need not be `sangam`/`sangam`.

Every failure path — slot 0 down, dump failed, restore failed — falls back to the baseline
plus `make up` (which migrates) plus `make seed`, and relaxes the smoke documents floor to
0, because `make seed` creates no `documents` rows. `CLONE=0` takes that path on purpose.
A clone cannot be greener than its source: when judging `sandbox-verify`, the question is
whether it fails *exactly* what the main checkout's `make smoke` fails.

If N Postgres containers ever prove too heavy, the escape hatch is one shared cluster with
a database per sandbox, cloned by `CREATE DATABASE … TEMPLATE` — near-instant, but it needs
source and target in one cluster and gives up the self-contained-stack model.
