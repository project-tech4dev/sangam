# Agent checkpoints: save only what can resume (#310) — Draft v1

## In plain words

Every agent step saves the whole run so far to Postgres. That made checkpoints 98% of Sangam Dev's database (~1 GB),
and most of it was Import's researchers, whose findings are already rows. We stop saving what nothing reopens
(M1, M2), measure what is left (M3, M4), clean up what is already saved (M5), and keep it visible (M6). The bigger
redesigns in #310 (#420, a separate pool, save-at-end) are built only if the measurements say so.

## 1. Goal

**An Import should leave a few MB of checkpoints, not 169 MB, and old ones should be cleaned up on their own.**

Success, in numbers checked with one saved query (`make checkpoint-sizes`):

- After M1+M2, a one-organisation Import leaves no subagent namespace except the catalog-writer's.
- After M5, Sangam Dev's checkpoint rows drop by most of the ~1 GB, and every chat still reopens with all its messages.
- A thread past 20 MB shows up in Langfuse without anyone running SQL.

## 2. What we found (evidence)

| finding | evidence | consequence |
|---|---|---|
| Subagent steps are most of the bytes | local: 18 MB of 18.5 MB in subagent namespaces; Dev: 143 of the largest thread's 169 MB | M1 (done) |
| A researcher's files move up into Scout's state | `files` is not in deepagents' `_EXCLUDED_STATE_KEYS`; only the vault-reader has `DropFilesOnExit` | M2 |
| `messages` and `files` are **delta channels**, snapshot every 50 updates | `type(g.channels["messages"])` is `DeltaChannel` on Ask, Import and Pitch; `deepagents/graph.py:78`, `filesystem.py:1300` | a naive "keep latest" prune empties chats (M5) |
| The Postgres saver has no prune | `AsyncPostgresSaver.aprune` raises `NotImplementedError` | we write it (M5) |
| `DELETE` does not shrink the disk | Postgres only marks the space reusable | M5's runbook adds `pg_repack` / `VACUUM FULL` |

> **The rule:** never drop part of a namespace's checkpoint chain; drop a whole namespace, or keep back to its last snapshot.
> **Example:** Priya's Ask chat has 70 checkpoints; its last snapshot is at #50. Keeping only #70 makes her chat open empty, with no error.
> **Why it matters:** the failure is silent, and the data is gone.

## 3. Blast radius

Built by hand from `CLAUDE.md`, `core/lifespan.py` and a grep for `aget_state`; the checkpoint tables are not in the SQL catalog.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | 0 | what we stop writing and delete | in scope | not in the SQL catalog; Ask cannot read them |
| Import agent (`ingest/agent.py`) | 1 | subagent build, files dropped | in scope | M1, M2 |
| Ask chat reopen (`routes/threads.py::thread_messages` → `aget_state`) | 1 | reads the checkpoint a prune keeps | in scope | M5's acceptance test |
| Import live status (`ingest/live_status.py`) and the past-imports list (`ImportThreads.tsx`, reads `threads`, reopens from the checkpoint) | 1 | same | in scope | M5 |
| Pitch chats (`proposal-<id>-<user>`) | 1 | same | in scope | M5 |
| A catalog-writer paused at approval | 1 | its checkpoint is how it resumes | in scope | M5 never touches a paused thread |
| `threads` table | 1 | rows stay; only checkpoints change | unaffected | v1 deletes no thread |
| Langfuse | 2 | new score per Import turn | in scope | M6 |
| `backend/vercel.json` crons | 2 | daily prune | in scope | M5 |
| Frontend | 2 | nothing new on screen | unaffected | no design-system change |

## 4. High-level design

```
Scout (supervisor) ── checkpointed every step (chat reopens, approvals resume)
 ├─ entity-researcher ── no checkpoint (M1 ✓)  ── drops its files on exit (M2 ◄ new)
 ├─ workbook-reader   ── no checkpoint (M1 ✓)  ── drops its files on exit (M2 ◄ new)
 ├─ vault-reader      ── no checkpoint (M1 ✓)  ── already drops its files
 └─ catalog-writer    ── checkpointed: its approval card is an interrupt

daily, 02:00 IST ── POST /internal/prune-checkpoints (Vercel cron, CRON_SECRET)   ◄ M5
                     for each thread idle > 6 h and not paused:
                       1. delete every subagent namespace          (whole namespace: safe)
                       2. top level: keep back to the last snapshot (M5b, only if M4 says so)

end of each Import turn ── checkpoint_mb score on the Langfuse trace               ◄ M6
```

**Key trade-off, scheduler.** A Vercel cron route over pg_cron: deciding which checkpoint is a snapshot means
deserialising blobs, which is Python; local Postgres has no pg_cron; and `backend/vercel.json` already runs a cron.
The cost is one new secret (`CRON_SECRET`) and one connection from the shared pool for the run, bounded by a batch size.

## 5. Low-level design

- **M2** — `ingest/agent.py`: `DropFilesOnExit()` in the researcher's and workbook-reader's middleware.
  `tests/test_harness.py`: a test that these three subagents carry it, beside the checkpoint test.
- **M3** — `scripts/sql/checkpoint_sizes.sql` (read-only; bytes by thread, top-level vs subagent, channel; optional
  `THREAD=`) and a `make checkpoint-sizes [ENV=staging] [THREAD=...]` target through `scripts/db-url.sh`.
- **M5** — `app/db/prune.py`: `prune(pool, *, idle_hours, batch)`. Per thread, in its own transaction:
  skip if the latest top-level checkpoint has an `__interrupt__` write or the thread changed within `idle_hours`;
  else `DELETE` from all three tables `WHERE thread_id = %s AND checkpoint_ns <> ''`.
  Route `POST /internal/prune-checkpoints` in `api/routes/maintenance.py`, refusing anything without
  `Authorization: Bearer $CRON_SECRET`; `make prune-checkpoints [ENV=staging] [DRY=1]` calls the same function.
  Settings in `core/config.py`: `CRON_SECRET`, `PRUNE_IDLE_HOURS` (6), `PRUNE_BATCH` (50).
  A test that fails if any built graph gains a delta channel the prune does not know about.
- **M6** — after an Import turn, one indexed query (`sum(octet_length(blob)) WHERE thread_id = %s`) sent as
  `checkpoint_mb` through `integrations/tracing.py::score_answer`.

## 6. Security review

- The cron route is the only new endpoint. It is not under `/api`, takes no input, and refuses without the bearer
  secret, compared in constant time. The secret comes from the environment.
- No new table, nothing added to the SQL catalog, no PII read: the prune deletes by `thread_id` and namespace only.
- The prune runs as the owner pool (checkpoints have no RLS); it never reads message content.

## 7. Testing

- Unit (no database): the subagent stacks (M1, M2); the route refuses a missing or wrong secret; the skip rules on
  a fake cursor (paused, recent, idle).
- Integration (`integration` mark, compose Postgres): build a thread with the real saver past 50 updates, prune, and
  assert `aget_state` returns the same messages and files before and after; a paused writer thread is untouched.
- Paid: M4 only.

## 8. Milestones

Summary: one PR per milestone, each stacked on the last, with a review stop between them.

| M | issue | ships | priority |
|---|---|---|---|
| M1 | #310 fix 1 | researchers and readers write no checkpoints | PR #421 |
| M2 | #415 | researcher and workbook-reader drop files on exit | PR, stacked on #421 |
| M3 | #416 | `make checkpoint-sizes` | high |
| M4 | #417 | before/after numbers; decides M7 | high |
| M5 | #418 | daily prune of subagent namespaces | high |
| M6 | #419 | `checkpoint_mb` per Import turn in Langfuse | low |
| M7 | #420, #310 fixes 4, 5 | only what M4's rules call for | low |

#### Milestone 1: subagents write no checkpoints ✓
- **Deliverable**: entity-researcher, vault-reader and workbook-reader built with `checkpointer=False`; writer kept.
- **Acceptance**: `pytest tests/test_harness.py -k Checkpointed` passes. Commit `29c8c8d6`.

#### Milestone 2: drop a subagent's files on exit (#415) ✓
- **Deliverable**: after a researcher returns, Scout's `files` holds none of its pages.
- **Touches**: backend.
- **Key tasks**: [x] add `DropFilesOnExit` to two stacks, before the researcher's rubric [x] test the three stacks carry it
  [x] test that a parent keeps its own files and gets none of an unsaved subagent's
- **Acceptance**: `pytest tests/test_harness.py` passes.

#### Milestone 3: one saved size query (#416)
- **Deliverable**: `make checkpoint-sizes` prints bytes by thread, namespace and channel.
- **Touches**: scripts, Makefile.
- **Key tasks**: [ ] the SQL file [ ] the target [ ] a line in `make help`
- **Acceptance**: `make checkpoint-sizes THREAD=import-208baf8a-…` shows `subagent | messages | 17 MB` locally.

#### Milestone 4: measure (#417)
- **Deliverable**: numbers on #310 from two paid one-organisation Imports on the same funder with a long annual
  report: one on master, one on M2's branch (`make dev-backend` + `make dev-frontend` from the worktree).
- **Touches**: nothing in code.
- **Decision rules, written before measuring:**
  - #420 (pages to Storage): build if the top-level `files` channel is over 5 MB or 10% of the run's bytes.
  - Fix 5 (save at end): build if top-level bytes per one-organisation run stay over 10 MB.
  - Fix 4 (own pool): build if `/health` shows pool waits during the next real 8-organisation run with Ask in use.
- **Acceptance**: both runs' `make checkpoint-sizes` output and wall-clock time posted on #310.

#### Milestone 5: daily prune (#418)
- **Deliverable**: subagent namespaces of idle, unpaused threads are deleted every night; Dev cleaned once.
- **Touches**: backend, `backend/vercel.json`, Makefile.
- **Key tasks**: [ ] `app/db/prune.py` [ ] the route and secret [ ] `make prune-checkpoints DRY=1`
  [ ] the delta-channel guard test [ ] the integration test [ ] runbook: backup Dev, run, `pg_repack` the three tables
- **Acceptance**: integration test passes; on Dev, before/after row bytes and table size posted on #418, and three
  old chats (one Ask, one Import, one Pitch) reopen with every message.

#### Milestone 6: size per Import turn (#419)
- **Deliverable**: `checkpoint_mb` on each `sangam_import` trace.
- **Touches**: backend.
- **Acceptance**: a local Import shows the score in Langfuse; a unit test checks it is sent once per turn.

#### Milestone 7: what M4 calls for
Planned only once M4 has numbers; each becomes its own Draft.

## 9. Open questions and risks

- **Delete old Import threads entirely?** #310 suggests after 30 days. It is a product call: past imports would
  vanish from `/import`. v1 deletes no thread; M5 alone removes ~85% of the largest one.
- **Top-level trim (M5b).** Keeping back to the last snapshot needs blob deserialisation and is the risky part;
  built only if M4 shows top-level bytes still large.
- **Running and paused threads.** A thread idle less than 6 h, or with an `__interrupt__` write, is skipped at any age.
- **langgraph upgrades** may change how delta channels snapshot; the guard test fails first.
- **Two paid runs** in M4 (needs `TAVILY_API_KEY`).

## Known gaps — what this does not make true

- It does not shrink Dev's disk until `pg_repack`/`VACUUM FULL` runs (M5's runbook).
- It does not stop the supervisor saving every step; that is fix 5, decided in M4.
- Checkpoint writes still share the pool with REST and `db_query`; that is fix 4, decided in M4.
