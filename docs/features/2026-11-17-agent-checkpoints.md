# Agent checkpoints: save only what can resume (#310) — Draft v1

## In plain words

Every agent step saves the whole run so far to Postgres. That made checkpoints 98% of Sangam Dev's database (~1 GB),
and most of it was Import's researchers, whose findings are already rows. We stop saving what nothing reopens
(M1, M2), measure what is left (M3, M4), clean up once what was saved before that (M5), and keep it visible (M6). The bigger
redesigns in #310 (#420, a separate pool, save-at-end) are built only if the measurements say so.

## 1. Goal

**An Import should leave a few MB of checkpoints, not 169 MB, and what was saved before that is cleaned up once.**

Success, in numbers checked with one saved query (`make checkpoint-sizes`):

- After M1+M2, a one-organisation Import leaves no subagent namespace except the catalog-writer's.
- After M5, Sangam Dev's checkpoint rows drop by most of the ~1 GB, and every chat still reopens with all its messages.
- A thread past 20 MB shows up in Langfuse without anyone running SQL.

## 2. What we found (evidence)

| finding | evidence | consequence |
|---|---|---|
| Subagent steps are most of the bytes | local: 18 MB of 18.5 MB in subagent namespaces; Dev: 143 of the largest thread's 169 MB | M1 (done) |
| A researcher's files move up into Scout's state | `files` is not in deepagents' `_EXCLUDED_STATE_KEYS`; only the vault-reader has `DropFilesOnExit` | M2 |
| `messages` and `files` are **delta channels**, snapshot every 50 updates | `type(g.channels["messages"])` is `DeltaChannel` on Ask, Import and Pitch; `deepagents/graph.py:78`, `filesystem.py:1300` | a naive "keep latest" prune empties chats; M5 deletes whole namespaces only |
| The Postgres saver has no prune | `AsyncPostgresSaver.aprune` raises `NotImplementedError` | M5 is a hand-run `DELETE` of whole subagent namespaces |
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
| Ask chat reopen (`routes/threads.py::thread_messages` → `aget_state`) | 1 | reads the checkpoint the cleanup keeps | in scope | M5's acceptance check |
| Import live status (`ingest/live_status.py`) and the past-imports list (`ImportThreads.tsx`, reads `threads`, reopens from the checkpoint) | 1 | same | in scope | M5 |
| Pitch chats (`proposal-<id>-<user>`) | 1 | same | in scope | M5 |
| A catalog-writer paused at approval | 1 | its checkpoint is how it resumes | in scope | M5 skips a paused thread |
| `threads` table | 1 | rows stay; only checkpoints change | unaffected | v1 deletes no thread |
| Langfuse | 2 | new score per Import turn | in scope | M6 |
| Frontend | 2 | nothing new on screen | unaffected | no design-system change |

## 4. High-level design

```
Scout (supervisor) ── checkpointed every step (chat reopens, approvals resume)
 ├─ entity-researcher ── no checkpoint (M1 ✓)  ── drops its files on exit (M2 ◄ new)
 ├─ workbook-reader   ── no checkpoint (M1 ✓)  ── drops its files on exit (M2 ◄ new)
 ├─ vault-reader      ── no checkpoint (M1 ✓)  ── already drops its files
 └─ catalog-writer    ── checkpointed: its approval card is an interrupt

once, by hand, after M1 is deployed ── scripts/sql/prune_subagent_checkpoints.sql   ◄ M5
                     for each thread idle > 6 h and not paused:
                       delete every subagent namespace             (whole namespace: safe)

end of each Import turn ── checkpoint_mb score on the Langfuse trace               ◄ M6
```

**Key trade-off, no scheduler.** A nightly prune was planned first. After M1 only the catalog-writer still saves a
subagent namespace, and its runs are a few steps, so a cron would find almost nothing. What is left is the backlog
from before M1, which one hand-run script clears: no route, no secret, no new code in `app/`.

## 5. Low-level design

- **M2** — `ingest/agent.py`: `DropFilesOnExit()` in the researcher's and workbook-reader's middleware.
  `tests/test_harness.py`: a test that these three subagents carry it, beside the checkpoint test.
- **M3** — `scripts/sql/checkpoint_sizes.sql` (read-only; bytes by thread, top-level vs subagent, channel; optional
  `THREAD=`) and a `make checkpoint-sizes [ENV=staging] [THREAD=...]` target through `scripts/db-url.sh`.
- **M5** — `scripts/sql/prune_subagent_checkpoints.sql`, run with `psql` like `checkpoint_sizes.sql`. It picks
  threads whose latest top-level checkpoint is over 6 h old and has no `__interrupt__` write, prints what it would
  delete, and deletes from all three tables `WHERE checkpoint_ns <> ''` only when run with `-v apply=1`.
- **M6** — after an Import turn, one indexed query (`sum(octet_length(blob)) WHERE thread_id = %s`) sent as
  `checkpoint_mb` through `integrations/tracing.py::score_answer`.

## 6. Security review

- No new endpoint, table or secret, and nothing added to the SQL catalog.
- The cleanup runs by hand as the database owner (checkpoints have no RLS). It deletes by `thread_id` and namespace
  and never reads message content.

## 7. Testing

- Unit (no database): the subagent stacks (M1, M2).
- M5, on the local database first: the dry run's list, then the delete, then three old chats (one Ask, one Import,
  one Pitch) reopen with every message, and a paused thread keeps its subagent namespace.
- Paid: M4 only.

## 8. Milestones

Summary: one PR per milestone, each stacked on the last, with a review stop between them.

| M | issue | ships | priority |
|---|---|---|---|
| M1 | #310 fix 1 | researchers and readers write no checkpoints | PR #421 |
| M2 | #415 | every subagent drops its files on exit | PR #422, stacked on #421 |
| M3 | #416 | `make checkpoint-sizes` | PR #423, stacked on #422 |
| M4 | #417 | before/after numbers; decides M7 | closed: numbers on hand, no paid run |
| M5 | #418 | one-off cleanup of Dev's old subagent namespaces (runbook) | PR, stacked on #424; Dev after deploy |
| M6 | #419 | `checkpoint_mb` per Import turn in Langfuse | PR, stacked on #423 |
| M7 | #420, #310 fixes 4, 5 | only what M4's rules call for | none: #420 closed, fix 5 not needed, fix 4 open |

#### Milestone 1: subagents write no checkpoints ✓
- **Deliverable**: entity-researcher, vault-reader and workbook-reader built with `checkpointer=False`; writer kept.
- **Acceptance**: `pytest tests/test_harness.py -k Checkpointed` passes. Commit `29c8c8d6`.

#### Milestone 2: drop a subagent's files on exit (#415) ✓
- **Deliverable**: after a researcher returns, Scout's `files` holds none of its pages.
- **Touches**: backend.
- **Key tasks**: [x] add `DropFilesOnExit` to the researcher (before its rubric), workbook-reader and writer [x] test the three stacks carry it
  [x] test that a parent keeps its own files and gets none of an unsaved subagent's
- **Acceptance**: `pytest tests/test_harness.py` passes.

#### Milestone 3: one saved size query (#416) ✓
- **Deliverable**: `make checkpoint-sizes` prints bytes by thread, namespace and channel.
- **Touches**: scripts, Makefile.
- **Key tasks**: [x] the SQL file [x] the target [x] a line in `make help`
- **Acceptance**: `make checkpoint-sizes` shows `subagent | messages | 17 MB` locally. Done: the Import thread is
  480 kB top level and 19 MB in 3 subagent runs.
- **Note**: from a worktree, set `COMPOSE_PROJECT_NAME=sangam`, or compose looks for a Postgres of its own.

#### Milestone 4: measure (#417)
- **Deliverable**: numbers on #310 from two paid one-organisation Imports on the same funder with a long annual
  report: one on master, one on M2's branch (`make dev-backend` + `make dev-frontend` from the worktree).
- **Touches**: nothing in code.
- **Decision rules, written before measuring:**
  - #420 (pages to Storage): build if the top-level `files` channel is over 5 MB or 10% of the run's bytes.
  - Fix 5 (save at end): build if top-level bytes per one-organisation run stay over 10 MB.
  - Fix 4 (own pool): build if `/health` shows pool waits during the next real 8-organisation run with Ask in use.
- **Acceptance**: both runs' `make checkpoint-sizes` output and wall-clock time posted on #310.
- **Outcome**: closed without the paid runs. A local Import saved before M1 and M2, a worst case, held 480 kB at the
  top level, 398 kB of it Scout's `files` (first misread as none: delta channels are saved as writes, not blobs);
  Dev's largest thread was ~3 MB per organisation. Fix 5 is "no". #420's 5 MB arm is far off; its 10% arm is met
  only because the total is now that small, so it is judged on bytes and left closed (numbers on #417). The gap, a run where Scout reads a long report itself, is watched by M6 on real Imports.

#### Milestone 5: one-off cleanup of Dev (#418)
- **Deliverable**: Dev's subagent namespaces from before M1 are gone, and its disk shrinks. Runs once, after M1 is deployed.
- **Touches**: one SQL file; no code in `app/`.
- **Runbook**:
  1. `make checkpoint-sizes ENV=staging` (before), and `make db-backup ENV=staging`.
  2. `make prune-checkpoints ENV=staging`: the dry run, listing threads and bytes it would delete.
  3. `make prune-checkpoints ENV=staging APPLY=1`.
  4. `pg_repack` the three tables (or `VACUUM FULL` in a quiet hour: it locks them).
  5. `make checkpoint-sizes ENV=staging` (after); reopen three old chats (one Ask, one Import, one Pitch).
- **Acceptance**: steps 1–5 on the local database first, then on Dev, with the before/after numbers posted on #418.
- **Local, done**: `make prune-checkpoints APPLY=1` took the old Import thread from 20 MB to 480 kB, and it reopens with
  the same 15 messages and files. `tests/test_prune_checkpoints.py` holds the same on real LangGraph checkpoints, and a
  paused thread keeps its namespace and resumes (it fails without the `__interrupt__` guard).

#### Milestone 6: size per Import turn (#419)
- **Deliverable**: `checkpoint_mb` on each `sangam_import` trace (`CheckpointSize`, an `after_agent` hook on Scout only).
- **Touches**: backend.
- **Acceptance**: a local Import shows the score in Langfuse; a unit test checks it is sent once per turn.

#### Milestone 7: what M4 calls for
Nothing: #420 is closed and fix 5 is not needed. Fix 4 stays in #310, judged on a real 8-organisation run with Ask in use.

## 9. Open questions and risks

- **Delete old Import threads entirely?** #310 suggests after 30 days. It is a product call: past imports would
  vanish from `/import`. v1 deletes no thread; M5 alone removes ~85% of the largest one.
- **Top-level growth.** Scout still saves every step and nothing trims it. Keeping back to the last snapshot needs
  blob deserialisation and is the risky part; fix 5 or deleting old threads is decided by M4's numbers.
- **Running and paused threads.** A thread idle less than 6 h, or paused on an `__interrupt__`, is skipped.

## Known gaps — what this does not make true

- It does not shrink Dev's disk until `pg_repack`/`VACUUM FULL` runs (M5's runbook, step 4).
- Nothing cleans checkpoints on its own: a subagent that starts checkpointing again would grow unseen until M6.
- It does not stop the supervisor saving every step; M4's numbers say that costs ~3 MB per organisation.
- Checkpoint writes still share the pool with REST and `db_query`; that is fix 4, decided in M4.
