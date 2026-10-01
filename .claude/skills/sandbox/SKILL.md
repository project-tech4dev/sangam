---
name: sandbox
description: "INVOKE THIS SKILL when someone wants to try an idea without disturbing the stack they are already running, or wants more than one feature in flight at once — phrased as 'in a sandbox', 'spin up', 'try X without breaking Y', or just a second idea while a first is unfinished. Covers standing up an isolated worktree plus Docker stack on its own ports and database, handing the idea to an agent inside it, and tearing it down. Uses the make sandbox-* targets."
---

<oneliner>
A sandbox is one git worktree at `../sangam-<slug>` plus one whole Docker stack —
frontend, backend, Postgres — on its own ports, with its own copy of the database.
Three or four run side by side, so a half-finished migration in one costs nothing
in another. `make sandbox-new SLUG=x` builds it; `make sandbox-rm SLUG=x` removes
every trace.
</oneliner>

<this_file_is_tracked>
Unlike its neighbours in `.claude/skills/`, this is a real file, not a symlink into
`.agents/`. Those are installed tooling, gitignored and refreshed by `npx skills`;
this one is first-party and committed, so it travels with a clone. `.gitignore`
excludes `.claude/skills/*` per entry and re-admits this directory — do not
"tidy" it back into a symlink, and do not re-collapse the gitignore pattern.
</this_file_is_tracked>

<when_to_use>
Worth a sandbox when the idea touches something shared and slow to undo:

- a schema change — a migration, a `db/init` edit, anything under `db/`
- the seed data, or a long ingest you want to run and keep
- `docker-compose.yml`, the Makefile, or anything that changes how the stack boots
- a second or third idea while the first is still unfinished and running

Not worth it otherwise. A one-file frontend change, a prompt edit, a repository
function — those are a branch in the main checkout, which costs nothing and starts
instantly. A sandbox costs 6-10 minutes on the first build and ~1.5 GB of memory
while it runs. Say that before starting one, not after.
</when_to_use>

<creating>
```bash
make sandbox-new SLUG=<short-name>          # the usual case
make sandbox-new SLUG=x GRAPH=1             # also start Neo4j (+768 MB)
make sandbox-new SLUG=x BASE=<ref>          # branch from something other than origin/master
make sandbox-new SLUG=x CLONE=0             # skip the clone: baseline + migrate + seed
```

Derive the slug from the idea — `rls`, `funder-dedupe`, `score-v2`. Short, lowercase,
hyphenated; the script slugifies and truncates, but a name you chose reads better in
`make sandbox-ls` than one it derived.

**Never invent a slot number or a port.** Allocation is the script's job and it reads
live state to do it. Report what it printed; do not predict it beforehand.

When it finishes, tell the user three things: the slot and its URLs, whether the
database was cloned from the main stack or rebuilt from the baseline (the script says
which), and the branch name `sandbox/<slug>`.
</creating>

<handing_off_the_idea>
Three ways, and the second is the only one that gives genuine concurrency.

1. **One idea, this session.** `EnterWorktree path="../sangam-<slug>"`, which is legal
   because `git worktree add` already registered the path. Never call
   `ExitWorktree action:"remove"` — it refuses a worktree entered by path, and teardown
   is `make sandbox-rm` anyway.

2. **Several at once — the reason sandboxes exist.** `EnterWorktree` moves the one
   session, so it *cannot* run three ideas in parallel. Print a copy-paste line per
   sandbox and let the user open a terminal for each:
   ```
   cd ../sangam-<slug> && claude "<the idea>"
   ```
   Say plainly that this is the only route to parallel agents rather than implying the
   session can do it.

3. **Fire-and-forget.** A background subagent pinned to the worktree, checked on with
   `ListAgents` / `SendMessage`.

Whichever mode, the brief names: the slot, the branch and what it was based on, the
three URLs, that Postgres is a private clone so destructive SQL and migrations are
fine, that Neo4j is off unless `GRAPH=1` and graph features self-disable, that `make`
targets run in that directory already hit that stack and need no extra flags, and that
nothing is ever run with `ENV=staging`.
</handing_off_the_idea>

<inspecting>
```bash
make sandbox-ls                   # every sandbox: slot, branch, running services, URLs
make sandbox-url SLUG=x           # one sandbox's URLs
make sandbox-verify SLUG=x        # smoke against that stack (LLM=1 to include the agent call)
```

Inside the worktree every ordinary target already targets that stack — `make up`,
`make logs`, `make psql`, `make seed`, `make smoke` — because the compose project name
comes from the directory and the ports come from that directory's `.env`. There is no
per-sandbox flag to remember and nothing to pass.

`make sandbox-verify` compares against the *main* stack, not against perfection: a
clone cannot be greener than its source. If slot 0 fails a check, every clone of it
fails the same check. The question to ask is "does it fail exactly what slot 0 fails",
and `make smoke` in the main checkout answers it.
</inspecting>

<teardown>
```bash
make sandbox-rm SLUG=x            # refuses a dirty worktree
make sandbox-rm SLUG=x FORCE=1    # discards uncommitted work
```

This removes the containers, the images built for it, that stack's volumes, the
worktree and the branch. It is project-scoped, so it cannot touch the main stack's
data. **The database goes with it** — anything a sandbox ingested or imported is gone
unless it was committed or dumped first. Push the branch before removing it if the
work matters.
</teardown>

<enforced_elsewhere>
These are enforced in code, not by remembering them. Named here so a failure is
recognisable rather than mysterious:

- `ENV=staging` in a sandbox → the Makefile's `$(error)`, at parse time, before any
  recipe runs. The overlay's explicit `-f` would override the sandbox's `COMPOSE_FILE`
  and point the backend at the live managed database.
- A host target run against a stopped stack → `require_running`, which refuses rather
  than silently probing slot 0's ports and reporting another stack's health as this one's.
- A worktree with no `.env` → `require_env`, which names the real cause instead of
  compose's "no such service: postgres".
- A tenth sandbox → `allocate_slot`, which refuses and prints the teardown hint.
- A dirty worktree on teardown → `cmd_rm`, which lists the files and stops.
- A base ref predating the harness → a preflight `cat-file` check, before the worktree
  is created rather than ten minutes into a build.

What is *not* enforceable, and so is your job to say out loud: roughly 1.5 GB of Docker
memory per stack and another 0.8 GB with `GRAPH=1`, so three are comfortable and four
is the ceiling on a 16 GB machine.
</enforced_elsewhere>

<failure_modes>
**Slot 7 gets skipped.** Its backend port would be 8080, which is usually held by
something else on a developer machine. Allocation jumps from 6 to 8 and that is
correct — the probe is authoritative. Do not "fix" it, and do not add a denylist file;
a list would drift, which is exactly what deriving the slot avoids.

**`BASE=origin/master` is refused until this branch merges.** The sandbox `.env` names
`docker-compose.sandbox.yml`, which master does not have yet. Pass `BASE=HEAD`.

**`git worktree add` does not carry a dirty tree.** Neither `BASE=origin/master` nor
`BASE=HEAD` brings uncommitted work across. Commit first if the sandbox should build
on something in progress.

**The first build is 6-10 minutes**, two images plus `npm ci` into an empty volume;
later ones are ~2 minutes because the npm cache is shared. Warn before starting.

**Supabase sign-in does not work in a sandbox.** It gets placeholder values when the
main `.env` has none, and even with real ones the project's redirect allowlist will not
contain `localhost:3010`. A feature that genuinely needs sign-in adds its sandbox port
to Supabase by hand. Everything else renders.
</failure_modes>
