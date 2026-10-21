# Auth and pool cleanup

2026-10-21. Both milestones ship together in #285, as asked in review. Stacked on #284 (`perf/workspace-one-call`). The live document on this subject. It replaces the
cold-start "known gaps" in `2026-10-10-page-load-performance.md` for the database side only. Bundle size stays there.

## 1. Goal

**Every request reaches the database through one pool whose limits are written down. Every "who may do what" rule
sits in one table a reviewer can read.**

Success means three things:

- A runaway REST query stops after a set time.
- A cold start runs no DDL against production.
- A reviewer can answer "can a CSO admin save a Funder Match run?" from `ARCHITECTURE.md` without reading code.

## 2. What is actually unclean: the evidence

The ten items raised in the conversation, each checked against production (Supabase `aqhhlorihtkcipntwycg`,
`pg_stat_statements` and `pg_stat_activity`, 2026-10-21) or the source.

| # | item | evidence | verdict |
|---|---|---|---|
| 1 | `saver.setup()` runs DDL on every cold start | `CREATE TABLE IF NOT EXISTS checkpoint_migrations` ran **3,771** times | **fix (M1)** |
| 2 | REST has no `statement_timeout` | only `sql/executor.py:72` and `repositories/matching.py:34` set one | **fix (M1)** |
| 3 | pool wait and connect timeouts not set | `make_pool` (`db/checkpointer.py:15`) passes neither, so the wait is psycopg's 30 s and the connect is unbounded | **fix (M1)** |
| 4 | no stale-connection check | a frozen Vercel instance thaws holding sockets the pooler may have closed | **fix (M1)** |
| 5 | no pool metrics | nothing logs or exposes `pool.get_stats()` | **fix (M1)** |
| 6 | permission rules scattered | the rules live in 5 `require_*` dependencies, `CallerScope` (`security.py:227`), `AGENT_ACCESS` (`lifespan.py:39`) and about 40 RLS policies, with no single list | **fix (M2)**, as docs only |
| 7 | AuthMiddleware opens a transaction per request | the lookup averages **0.66 ms** over 10,369 calls; the cost is about 3 round trips (BEGIN, SELECT, COMMIT) of about 1 ms each in bom1 | **defer**, see §8 |
| 8 | connections × instances can pass 60 | now **9** app connections, all idle, out of 60 | **defer** until a `max_clients` error appears |
| 9 | Import holds a connection while its tools run | `ADAPTERS` in `ingest/runner.py:158` is **empty**, and researchers' tools take short connections | **nothing to do** |
| 10 | `/api/me` is a separate call | fixed in #284 | **done** |
| — | `min_size=1` opens a connection at boot | `_verify_sql_catalog` opens one at boot anyway | **nothing to do** |

> **The rule:** a cleanup item ships only with a number behind it.
> **Example:** item 7 sounds bad ("a write transaction on every request"), but it is 0.66 ms of query. A cache for it
> would buy a few milliseconds and cost staff revocation lag (§8).
> **Why it matters:** "clean" changes that buy nothing still cost a review and a risk.

## 3. Blast radius

Built by hand from `CLAUDE.md`, `grep make_pool` and `grep _SET_CALLER`. No table, migration or catalog entry changes.

| surface | hop | why affected | status | notes |
|---|---|---|---|---|
| `db/checkpointer.py` `make_pool` | 0 | timeouts, `check=` | in scope | — |
| `matching/run.py`, `ingest/calls/run.py`, `ingest/news/run.py` | 1 | call `make_pool` with a small `max_size`; they get the same kwargs | in scope | CLI pools: the same timeouts are right there too |
| `db/pool.py` `_SET_CALLER` | 0 | gains `statement_timeout` | in scope | every REST route runs through it |
| Ask's SQL executor, `repositories/matching.py` | 1 | already `SET LOCAL statement_timeout`; theirs is set later in the transaction, so it wins | unaffected | — |
| `db/migrate.py` (`make migrate`) | 1 | runs the checkpointer migrations | in scope | — |
| `core/lifespan.py` | 1 | checks checkpoint tables instead of creating them | in scope | — |
| `main.py` `/health` | 1 | gains a `pool` block | in scope | open path; counts only, no names |
| `tests/test_cov_core_lifespan.py:226` | 1 | monkeypatches `make_pool` as `lambda url, size` | in scope | signature kept positional, so it still fits |
| `docs/ARCHITECTURE.md` §8, §11 | 1 | permission table, pool limits | in scope | — |
| frontend | 2 | nothing reads `/health`'s new field | unaffected | — |
| Neo4j, Supabase Storage, models | 2 | not touched | unaffected | — |

## 4. High-level design

```
request ─► AuthMiddleware ─► route ─► CallerPool.connection()
                                         │  BEGIN
                                         │  SELECT set_config(role), set_config(claims),
                                         │         set_config(statement_timeout)   ◄ new, same round trip
                                         ▼
                                   AsyncConnectionPool  (timeout=10s wait, connect_timeout=5s,
                                                         check=check_connection, max_idle=300s)  ◄ new
cold start ─► lifespan ─► pool.open ─► catalog check ─► checkpoint check (read-only) ◄ was: setup() DDL
make migrate ─► SQL files ─► PostgresSaver.setup()  ◄ new home for the DDL
```

**Key trade-off: `check=` costs one round trip per checkout.** That is about 1 ms in bom1. A request takes 1 to 3
connections. The other choice, `max_idle` alone, still hands out a dead socket after a thaw, and that request fails
outright. Paying 1 ms is better than failing a request. The check is a no-op `execute("")`.

## 5. Low-level design

### M1: pool hygiene

`backend/app/core/config.py` gets three settings, with defaults only there:

| setting | default | why |
|---|---|---|
| `db_pool_timeout_s` | `10` | a request waiting longer for a connection is already lost; fail with a 503, not after psycopg's 30 s |
| `db_connect_timeout_s` | `5` | the session pooler answers in ms; an unbounded connect hung containers on the IPv6 host before |
| `db_statement_timeout_ms` | `15000` | above any REST query in `pg_stat_statements` (Funder Match reads are 9–14 ms) |

In `backend/app/db/checkpointer.py`, `make_pool(database_url, max_size=None)` keeps its signature and passes:

- `timeout=settings.db_pool_timeout_s`;
- `check=AsyncConnectionPool.check_connection`;
- `max_idle=300`;
- `connect_timeout` inside `kwargs`.

In `backend/app/db/pool.py`, `_SET_CALLER` gains `set_config('statement_timeout', %s, true)`. That adds no round
trip, and the setting is transaction-local like the other two.

`open_checkpointer` stops calling `saver.setup()`. It runs `_verify_checkpointer(pool)` instead, which:

- reads `max(v) FROM checkpoint_migrations`;
- raises when that is not `len(AsyncPostgresSaver.MIGRATIONS) - 1`;
- gives an error that says `run make migrate`.

That is the same shape as `_verify_sql_catalog`: drift raises at boot.

> **The rule:** the checkpointer's DDL runs once, from `make migrate`, never from a request path.
> **Example:** a `langgraph-checkpoint-postgres` upgrade adds migration 10. Today, five instances cold-starting together
> all try to insert `v=10` and four crash on the primary key. After this change the deploy refuses to boot until
> someone runs `make migrate ENV=staging`, once.
> **Why it matters:** schema changes in production happen on purpose, after a backup, as `CLAUDE.md` already requires.

`backend/app/db/migrate.py` runs `PostgresSaver.from_conn_string(url).setup()` after the SQL files. It uses the sync
saver, which has the same `MIGRATIONS`.

`backend/app/main.py`'s `/health` returns `{"status": "ok", "pool": {size, available, waiting, requests_waiting,
connections_errors}}` from `pool.get_stats()`, or no `pool` key before the lifespan opens it. Vercel logs and `curl`
can then see pool pressure, and no new route is needed.

### M2: one permission table

Docs only, in `docs/ARCHITECTURE.md` §8. Rows are the actions; columns are anonymous, signed in, member, admin,
steward and staff. Each cell names its gate: the `require_*` dependency, the `CallerScope` method or the RLS policy.
For example:

| action | member | admin | steward | staff | enforced by |
|---|---|---|---|---|---|
| read the org's Funder Match | ✓ | ✓ | ✓ | ✓ | `require_principal` + RLS `app.my_org_ids()` |
| save a Funder Match run | — | ✓ | ✓ | ✓ | RLS `app.my_match_org_ids()` (`0042`) |
| edit a proposal | — | ✓ | ✓ | ✓ | `CallerScope.can_edit_proposal` + RLS (`0048`) |
| use Scout (Import) | — | — | ✓ | ✓ | `require_scout` |

A test (`tests/test_permission_table.py`) parses the table and asserts every `require_*` dependency named in
`app/api/routes/` appears in it, so a new gate cannot skip the table.

## 6. Security review

- **No new endpoint.** `/health` gains counts only: pool size and waits, no user, no query and no DSN.
- **`statement_timeout` tightens, never loosens.** Executor and matching still set their own, lower value later in the
  same transaction.
- **The checkpoint guard runs as the owner at boot**, as `_verify_sql_catalog` does. It reads one row.
- **The deferred auth cache (§8) would weaken revocation.** That is why it is deferred, not built.
- No PII, credentials or tokens are touched. Settings come from the environment through `Settings`, never from `.env`.

## 7. Testing

Unit tests never touch a database.

- `make_pool` passes `timeout`, `check`, `max_idle` and `connect_timeout`, checked on the pool object without opening it.
- `set_caller` sends three `set_config` calls, one of them `statement_timeout`, through a fake connection.
- `_verify_checkpointer` raises on a missing table, on `max(v)` behind, and on `max(v)` ahead. It passes when they are equal.
- `/health` with no pool and with a stub pool.
- The lifespan test's `make_pool` monkeypatch still fits.

Integration tests (`integration` mark):

- A `CallerPool` connection runs `SELECT pg_sleep(…)` past a lowered timeout and gets `QueryCanceled`.
- `migrate.py` leaves `checkpoint_migrations` at `len(MIGRATIONS) - 1`.

The edge case where zero means "unrecorded": `max(v)` being NULL means "never migrated", not version 0. The guard
reports the two differently.

## 8. Milestones

#### Milestone 1: pool hygiene and checkpointer DDL out of boot
- **Deliverable**: explicit pool limits, a REST statement timeout, pool stats on `/health`, checkpointer DDL in `make migrate`
- **Touches**: backend
- **Key tasks**:
  - [ ] the three settings
  - [ ] `make_pool` kwargs
  - [ ] `_SET_CALLER`
  - [ ] `_verify_checkpointer`
  - [ ] the setup call in `migrate.py`
  - [ ] the `/health` pool block
  - [ ] tests
  - [ ] the ARCHITECTURE §11 line
  - [ ] a CHANGELOG line
- **Acceptance criteria**:
  - `cd backend && pytest -m "not integration" && pytest -m integration -k "timeout or checkpoint"` passes.
  - `make up` boots.
  - After Deploy, `curl <backend>/health` shows `pool`.
  - `pg_stat_statements` shows `CREATE TABLE IF NOT EXISTS checkpoint_migrations` stop growing.
- **Deploy order**: run `make migrate ENV=staging` **before** Deploy. The guard passes today, because setup has run 3,771 times.

#### Milestone 2: the permission table
- **Deliverable**: one who-may-do-what table in ARCHITECTURE §8, held by a test
- **Touches**: docs, one backend test
- **Key tasks**:
  - [ ] walk every `require_*`, `CallerScope` method and `AGENT_ACCESS` entry
  - [ ] write the table
  - [ ] `test_permission_table.py`
- **Acceptance criteria**: `pytest tests/test_permission_table.py`. A reviewer answers the four example questions in §5 from the doc alone.

## 9. Open questions and risks

1. **Should the user lookup be cached (item 7)?** A 60-second cache keyed by `auth_user_id` saves about 3 ms per
   request. The cost: `require_staff` reads `is_staff` from that row. Example: Asha loses staff at 10:00:00 and keeps
   the Import pipeline routes until 10:01:00. RLS stays live through `app.is_staff()`. **Recommendation: no.** If
   wanted later, cache only the link from Supabase user to `users.id` and read `is_staff` live.
2. **Transaction pooler on port 6543 (item 8).** Deferred. It would also break the executor's `prepare=True`, the
   server-side refusal of multi-statement SQL that is one of the four layers in `docs/SQL_AGENT.md`. It is revisited
   only when Vercel logs show `max_clients`. The cheaper first step then is a lower `DB_POOL_MAX_SIZE`.
3. **`db_statement_timeout_ms = 15000`.** The limit applies to each statement, not to the route. Example: the proposal
   `.docx` export spends seconds in Python building the file, and none of that counts. Only a single SQL statement over
   15 s is cancelled. Owner-pool routes such as `/api/ingest/research` are not affected at all. Is any REST statement
   meant to run longer?
4. **Risk: a deploy before `make migrate`** after a langgraph upgrade now refuses to boot instead of migrating. That is
   intended, and the error message names the command.
