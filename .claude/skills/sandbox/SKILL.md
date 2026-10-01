---
name: sandbox
description: "INVOKE THIS SKILL when someone wants a second or third feature in flight at once, or wants to try an idea touching the database, the seed or compose without disturbing the stack they are already running — phrased as 'in a sandbox', 'spin up', 'try X without breaking Y', or simply a new idea while an earlier one is unfinished. NOT for a one-file change, a prompt edit or a repository function: those are a branch in the main checkout, which costs nothing and starts instantly. Covers standing up an isolated worktree plus Docker stack on its own ports and database, handing the idea to an agent inside it, and tearing it down. Uses the make sandbox-* targets."
---

<oneliner>
A sandbox is one git worktree at `../sangam-<slug>` plus one whole Docker stack —
frontend, backend, Postgres — on its own ports with its own copy of the database.
Three run side by side, so a half-finished migration in one costs nothing in another.
</oneliner>

<procedure>
You are invoked with an idea. Work these in order.

1. **Gate it.** A sandbox earns its cost only if the idea touches `db/` (a migration or
   the baseline), the seed data, a long ingest worth keeping, or `docker-compose.yml` /
   the `Makefile` — or if another idea is already running and unfinished. If none of
   those hold, say a branch in the main checkout is cheaper and starts now, and stop.

2. **Quote the cost before running, not after.** 6-10 minutes for the first build,
   ~2 minutes once the npm cache is warm, ~1.5 GB of memory while it runs.

3. **Build it.** Derive a short lowercase slug from the idea — `rls`, `funder-dedupe`,
   `score-v2` — then run the command in `<creating>`.

4. **Read the exit correctly.** The URL banner means the stack is up. A non-zero exit
   *after* that banner is smoke failing, not creation failing. See `<failure_modes>`.

5. **Report three things:** the slot and its URLs, whether the database was cloned from
   the main stack or rebuilt from the baseline (the script says which), and the branch
   name `sandbox/<slug>`.

6. **Hand the idea off** per `<handing_off>`.
</procedure>

<creating>
```bash
make sandbox-new SLUG=x BASE=HEAD      # the usual case — see BASE in <failure_modes>
make sandbox-new SLUG=x GRAPH=1        # also start Neo4j (+768 MB)
make sandbox-new SLUG=x BASE=<ref>     # branch from something other than origin/master
make sandbox-new SLUG=x CLONE=0        # skip the clone: baseline + migrate + seed
```

**Never invent a slot number or a port.** The script derives both from live state.
Report what it printed; do not predict it beforehand or repeat a number from this file.

The script slugifies and truncates whatever you pass, but a slug you chose from the idea
reads better in `make sandbox-ls` than one it derived.
</creating>

<handing_off>
**Default, one idea — enter it and start work.** `EnterWorktree path="../sangam-<slug>"`,
then begin on the idea. This is legal because `git worktree add` already registered the
path. Never call `ExitWorktree action:"remove"`: it refuses a worktree entered by path,
and teardown is `make sandbox-rm` anyway.

**Only when the user named more than one idea, or asked for parallel agents** —
`EnterWorktree` moves the one session, so it cannot run two ideas at once. Print one line
per sandbox, enter none of them, and say plainly that a terminal each is the only route
to genuine concurrency:

```
cd ../sangam-<slug> && claude "<the idea>"
```

Either way, the brief names: the slot, the branch and what it was based on, the three
URLs, that Postgres is a private clone so destructive SQL and migrations are fine, that
Neo4j is off unless `GRAPH=1` and graph features self-disable, that `make` targets run in
that directory already hit that stack with no extra flags, and that nothing is ever run
with `ENV=staging`.
</handing_off>

<inspecting>
```bash
make sandbox-ls                  # every sandbox: slot, branch, running services, URLs
make sandbox-url SLUG=x          # one sandbox's URLs
make sandbox-verify SLUG=x       # smoke that stack (LLM=1 adds the real agent call)
```

Inside the worktree every ordinary target already hits that stack — `make up`, `logs`,
`psql`, `seed`, `smoke`. There is no per-sandbox flag to remember.

Judge `sandbox-verify` against slot 0, not against perfection: a clone cannot be greener
than its source. If `make smoke` in the main checkout fails the same check, the sandbox
is fine and slot 0 has the problem — say which it is.
</inspecting>

<teardown>
```bash
make sandbox-rm SLUG=x           # refuses a dirty worktree
make sandbox-rm SLUG=x FORCE=1   # discards uncommitted work
```

Removes the containers, the images built for it, that stack's volumes, the worktree and
the branch. It is project-scoped and cannot touch the main stack's data. **The database
goes with it** — anything the sandbox ingested is gone unless committed or dumped. Push
the branch before removing it if the work matters.
</teardown>

<enforced_elsewhere>
Enforced in code, not by remembering. Listed so a failure is recognisable, not mysterious:

- `ENV=staging` in a sandbox → the Makefile's `$(error)`, at parse time, before any recipe.
- A host target against a stopped stack → `require_running`.
- A worktree with no `.env` → `require_env`, which names the real cause.
- A tenth sandbox → `allocate_slot` refuses, with the teardown hint.
- A dirty worktree on teardown → `cmd_rm` lists the files and stops.
- A base ref predating the harness → a preflight `cat-file` check, before the build.

Not enforceable, so it is your job to say it out loud: ~1.5 GB of Docker memory per stack
and another ~0.8 GB with `GRAPH=1`. Three are comfortable, four is the ceiling, and the
budget is Docker's allocation rather than the host's RAM —
`docker info --format '{{.MemTotal}}'`. Build them one at a time.
</enforced_elsewhere>

<failure_modes>
**Non-zero exit after the URL banner** — smoke failed, not creation. The stack is up and
usable. Compare against `make smoke` in the main checkout before calling it broken.

**Every frontend check returns `000`** — under memory pressure `next dev` shuts down
cleanly, so there is no exit 137 and nothing in the logs. `docker compose ps -a` shows
`frontend Exited (0)` and `make up` brings it straight back. Check this before suspecting
the code.

**`BASE=origin/master` is refused** until `feat/dev-harness-parallel-sandboxes` merges —
master has no `docker-compose.sandbox.yml` yet, so pass `BASE=HEAD`. *(Delete this entry
and the `BASE=HEAD` note above when that branch merges.)*

**`git worktree add` carries no uncommitted work.** Commit first if the sandbox should
build on something in progress.

**Slot 7 is skipped, 6 → 8.** Its backend port would be 8080, usually held. That is
correct; do not "fix" it and do not add a denylist file.

**Supabase sign-in does not work in a sandbox** — it gets placeholder values, and the
redirect allowlist contains no `localhost:3010`. Everything except sign-in renders.

`docs/SANDBOX.md` has the reasoning behind all of these.
</failure_modes>
