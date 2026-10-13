---
type: testing guide
title: Testing
description: How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how to run each tier, and which tests pin the system's security and tool-surface invariants.
tags: [testing, pytest, integration-tests, evals, invariants]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-13T18:20:59.385Z
sources:
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-539ff1e55b1e385204a4bb93
    resource: repo://backend/tests/conftest.py
  - id: openwiki-source-39f5427f53dfb7fd20ac77cf
    resource: repo://backend/tests/evals/cases/import/canary.jsonl
  - id: openwiki-source-525d2a082ef8772e1fe91f69
    resource: repo://backend/tests/evals/conftest.py
  - id: openwiki-source-9cd890b23995672427c6c8c4
    resource: repo://backend/tests/evals/harness.py
  - id: openwiki-source-28c0299addb344bf8508c6d2
    resource: repo://backend/tests/evals/import_harness.py
  - id: openwiki-source-edebaaa991aec01704e84f6a
    resource: repo://backend/tests/evals/test_agent_evals.py
  - id: openwiki-source-d5d06fda351e6cb412c401d8
    resource: repo://backend/tests/evals/test_import_evals.py
  - id: openwiki-source-0808792899dda5ae43456460
    resource: repo://backend/tests/test_caller_pool.py
  - id: openwiki-source-62d4dd57642429b3aa7980e3
    resource: repo://backend/tests/test_harness.py
  - id: openwiki-source-1f8a01f7f723a9c4852239b4
    resource: repo://backend/tests/test_ingest_middleware.py
  - id: openwiki-source-c19bf12e33dd13dd52164b8e
    resource: repo://backend/tests/test_migration_integrity.py
  - id: openwiki-source-fe6e4c3f43ca6fccc586454c
    resource: repo://backend/tests/test_prompt.py
  - id: openwiki-source-e3d5b96924a7ab50f4e2652f
    resource: repo://backend/tests/test_rls.py
  - id: openwiki-source-b9b33576e920a6ec443c1309
    resource: repo://backend/tests/test_sql_catalog.py
  - id: openwiki-source-428476beae4aa2e70ded4bae
    resource: repo://backend/tests/test_sql_integration.py
  - id: openwiki-source-3e07dc90801342267034699a
    resource: repo://backend/tests/test_sql_validator.py
  - id: openwiki-source-a2371d6362e5db4bc834ad03
    resource: repo://CLAUDE.md
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-10-13T18:20:59.385Z" }
---

# Testing

All tests live in `backend/tests/` and run with pytest. They fall into three tiers that differ in what they need and what they cost. Pytest is configured in `backend/pyproject.toml` with `asyncio_mode = "auto"`, so async tests need no decorator, and with two registered markers, `integration` and `eval`.

| Tier | Needs | Marker | Costs money | Runs by default |
|---|---|---|---|---|
| Unit | nothing (no DB, no model, no network) | none | no | yes |
| Integration | compose Postgres on `localhost:5433` | `integration` | no | yes, but skips if the DB is unreachable |
| Evals | compose Postgres, a provider API key, `--run-evals` | `eval` | yes | no, always skipped without the flag |

```mermaid
flowchart TD
    A["pytest in backend/"] --> B["Unit tests: stub app, sentinel pool, fakes"]
    A --> C["Integration tests: real Postgres, rolled back"]
    A --> D["tests/evals: real agent, real model"]
    C -->|"DB unreachable"| S["skipped, not failed"]
    D -->|"no --run-evals"| S
    D -->|"no provider key"| S
```

The diagram shows how each tier degrades when its prerequisite is missing.

## Commands

From `backend/`:

```bash
pytest                         # unit + integration (evals skip themselves)
pytest tests/test_orgs.py      # one file
pytest -k "score"              # one pattern
pytest -m "not integration"    # skip everything needing Postgres on :5433
ruff check .                   # line-length 110, target py312
```

From the repo root, evals go through `make`:

```bash
make evals                     # golden questions through the real agent (COSTS MONEY, ~10c/case)
make evals TAG=canary          # the cheap subset
make evals TAG=import          # Import canaries: one funder, one NGO, ~15 min, needs TAVILY_API_KEY
```

`make evals` sources `.env` quietly (it carries the provider key), `cd`s into `backend/`, sets `TEST_DATABASE_URL` to `postgresql://sangam:sangam@localhost:5433/sangam`, and runs `.venv/bin/python -m pytest tests/evals --run-evals [--eval-tag TAG] -q`. It runs on the **host venv**, not in a container, because the backend image installs runtime dependencies only and has no pytest. `make smoke` is a separate end-to-end check of the running stack (`SMOKE_SKIP_LLM=1` skips its one real agent call); it is not part of pytest.

## Tier 1: unit tests (no database)

`backend/tests/conftest.py` is the scaffolding. `make_app(*routers)` builds a router-only FastAPI app with **no lifespan**, so there is no pool, no agent and no model. It overrides three dependencies:

- `get_current_user` returns the fixed `TEST_USER`.
- `get_principal` returns `DEV_USER` (an assert in `conftest.py` keeps `DEV_USER_ID` equal to `TEST_USER`).
- `get_pool` returns `_SentinelPool`, an object that raises `AssertionError` on any attribute access.

Because routers resolve the pool through `Depends(get_pool)`, that single override covers every router. A unit test that reaches the database fails loudly, so the rule is: monkeypatch the `repositories/` function rather than the pool. The `client_for` fixture wraps `make_app` in an `httpx.AsyncClient` over `ASGITransport`.

The `build_import` fixture builds the Import agent with `resolve_model` replaced by `FakeListChatModel` instances named after their model spec and `create_deep_agent` replaced by a capture function. Tests can then assert which model, subagents and middleware the builder handed over without calling any model. Other unit tests use `httpx.MockTransport` (Supabase Storage in `test_storage.py`) or a generated ES256 key and patched JWKS client (`test_security.py`) to exercise auth without a network.

## Tier 2: integration tests (database)

Integration tests connect to `TEST_DATABASE_URL`, defaulting to `postgresql://sangam:sangam@localhost:5433/sangam` (the compose Postgres published port). Each file declares its own DSN and fixture, and each fixture does `pytest.skip("compose Postgres not reachable on localhost:5433")` on `OperationalError` after a 3-second connect timeout. So on a machine with no database the suite stays green by skipping rather than failing, and `pytest -m "not integration"` avoids even the connection attempts.

Isolation is by rollback. The shared `db` fixture in `conftest.py` opens a non-autocommit connection and rolls back afterwards; `test_rls.py` runs each test inside `connection.transaction(force_rollback=True)`. Test rows never persist.

The marker is applied either per file with `pytestmark = pytest.mark.integration` (`test_rls.py`, `test_sql_integration.py`, `test_migration_integrity.py`, `test_import_undo.py`, `test_news_rls.py`, `test_news_store.py`, `test_news_stories_sql.py`) or per test (`test_caller_pool.py`, `test_news_pipeline.py`, `test_storage.py`, `test_locations_seed.py`, `test_taxonomy_seed.py`, `test_vault.py` and a few import tests). Files with per-test marks mix DB-free and DB-backed cases, so check the decorator rather than assuming a whole file needs Postgres. Applying the marker consistently matters: `-m "not integration"` only excludes what is marked.

The data under test must already be loaded: run `make up` (which migrates) and `make seed` first. `test_migration_integrity.py` asserts seeded facts, for example at least 96 `documents` rows (a floor, because the importer adds more), exactly 29 `graph_ingest_log` rows, stable seed-order ids (`kabil` = 9, `bdf` = 10, `axis-bank-foundation` = 1, `tata-trusts` = 4) and that the `documents` id sequence has advanced past the restored rows. It fails if migrations and seeds drifted apart. See [Data and Migrations](../architecture/data-and-migrations.md).

## Tier 3: evals (real model calls)

`backend/tests/evals/` runs questions through the **real agent**, so every case spends money (roughly 10 cents each) and takes real time. The gating lives in `tests/evals/conftest.py`:

- `--run-evals` and `--eval-tag` are registered with `pytest_addoption`. Without `--run-evals`, `pytest_collection_modifyitems` adds a skip marker to every test with the `eval` keyword.
- The gate is a conftest flag rather than an `addopts -m "not eval"` filter on purpose: a command-line `-m` replaces the `-m` in addopts, so `pytest -m integration` would otherwise start billing model calls.
- The `eval_settings` fixture skips when the API key for the configured provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GOOGLE_API_KEY`, chosen from the prefix of `Settings().model`) is not set.
- The `slug_ids` and `db` fixtures skip when Postgres is unreachable; unlike tier 2 they are session-scoped and read live `orgs` and `funders` ids, so evals run against your real seeded data, not a rolled-back fixture.

### Ask evals (`test_agent_evals.py`)

Cases come from `cases/golden.jsonl` (10 cases at the time of writing, 8 tagged `canary`). `load_cases(tag)` reads every `*.jsonl` directly under `cases/` and filters by `--eval-tag`. Each case runs `build_agent` with an `InMemorySaver`, a recursion limit of 60 and a 180-second wall-clock timeout (added after a hung model request blocked a suite for hours). The harness extracts the SQL the agent actually executed from `db_query` tool messages (`executed: ...` lines) and the `[kind:id]` citation markers from the final answer, ignoring the audit's appended caveat message.

Scoring (`harness.score`) applies whatever gates a case declares:

- **gold SQL**: the case's `gold_sql` is run against the database and compared with the agent's results by `sql_compare.gold_satisfied`. Every query the agent ran is tried, not only the last, since agents work in steps. If the agent ran no query, the answer must contain the gold values. `sql_compare` normalises numbers (700, 700.0 and `Decimal('700')` agree), matches labels loosely, and is itself covered by the DB-free `test_sql_compare.py`.
- `expected_value`, `must_mention`, `must_not_mention`.
- `required_citations` and `forbidden_citations`; slug-based markers are resolved to ids via `slug_ids`, and `kind:*` forbids any citation of that kind.
- `must_decline`, matched against a deliberately narrow list of non-possession phrases so the check cannot pass on any sentence.

A case with `expected_failure` becomes `xfail(strict=True)`. When the underlying data bug is fixed the case passes, pytest reports XPASS as a failure, and the marker gets deleted, so the suite is never permanently red.

### Import canaries (`test_import_evals.py`)

`cases/import/canary.jsonl` holds one funder (Axis Bank Foundation) and one NGO (The Ant). They sit in a subdirectory, so `load_cases` for the Ask suite never sees them. The Import test only parametrises cases **when `--eval-tag` is given and matches**, so a bare `make evals` stays the cheap Ask suite and never starts a 15-minute import. Both cases carry the tags `import` and `canary`, so `TAG=canary` also selects them. They skip if no Tavily key is set. `TAG=import` selects only them.

`import_harness.run_import` builds the Import agent as staff, runs it with a 900-second timeout, and answers the `choose_sources` human-in-the-loop pause with public web plus the library, asserting that no other pause occurs. The test then judges the saved `entity_research` row: correct `entity_kind`, non-empty findings, at least one expected concept, every gap having a `blocked` or `not_stated` reason with detail, tagged findings carrying a `tag_note`, and the researcher's `fact_count` matching the stored findings. See [Sangam Import and Scout](../architecture/sangam-import-scout.md).

## Invariants the tests pin

These tests exist so a library upgrade, a migration or a refactor cannot silently weaken a guarantee. Most are DB-free.

### Tool surfaces (`test_harness.py`)

`create_deep_agent` is a preset that adds eight filesystem tools and, whenever any subagent is declared, a `general-purpose` subagent carrying the main agent's whole tool list. `test_harness.py` pins how `app/agent/harness.py` takes both back:

- The harness profile is installed idempotently, resolves for the configured model, disables the general-purpose subagent, and does **not** decide tools (profiles are per provider and global, while Import needs `read_file` for skills and Ask must not have it, so the surface is per-agent middleware).
- The replacement `FilesystemMiddleware` registers only `read_file`, or `read_file` plus `ls` when `SKILL_READING_TOOLS` is kept. Nothing that writes (`write_file`, `edit_file`, `delete`, `execute`) is in either set. `execute` is named in `FILESYSTEM_TOOLS` and excluded, because it is advertised as a sandbox shell on an agent that reads untrusted web pages.
- **Ask Sangam** has no `task` tool (no subagents) and exactly these tools: `db_list_tables`, `db_describe_table`, `db_profile_column`, `db_query`, `search_graph`, `fetch_url`, `compare_fit`, plus the skill readers `read_file` and `ls`. See [Ask Sangam](../architecture/ask-sangam.md).
- Neither agent can have `write_file`, `edit_file`, `delete`, `execute`, `glob` or `grep`.
- **Import** advertises exactly `entity-researcher` and `catalog-writer` in its `task` description and never `general-purpose` (the test parses the advertised list instead of substring-searching, since deepagents boilerplate mentions the name generically).

### Subagent tool lists

The parent's restricted filesystem does not reach an isolated subagent, so the tests inspect each compiled subagent graph (found in the `task` tool's closure; an upgrade that moves them fails the test rather than passing silently). The pinned sets are:

| Subagent | Tools |
|---|---|
| `entity-researcher` | `research_goals`, `funder_dossier`, `list_library_documents`, `read_library_document`, `read_source_rows`, `search_public_sources`, `read_page`, `fetch_document`, `read_document_pages`, `save_research`, `read_file` |
| `catalog-writer` | `promote_research`, `funder_dossier`, `read_file` |
| `vault-reader` | `list_vault_documents`, `read_vault_document`, `research_goals`, `save_vault_findings`, `read_file` |
| `workbook-reader` | compiled and present; checked against the shared no-write, no-`ls` rules |

Further rules pinned here: no subagent has `ls` (skills are the supervisor's), the vault reader has no web tool (private text never shares a context with a web tool), and once `read_source_rows` has been used the researcher's `read_page` is refused with `STAFF_LOCK_REPLY`. With no sources chosen it is refused with `REFUSED: no sources`.

### Models, skills and middleware

- Each Import subagent runs on its tier: strong main model, mid `research_model` for researcher and vault reader, cheap `utility_model` for writer and workbook reader. A blank model variable takes its default, `off` disables `sql_audit_model`, and builders do not mutate the module-level subagent specs. `test_ingest_middleware.py` pins the fallback chain between tiers (a fallback to the same model is skipped) and the researcher's reading and model-call budgets coming from settings.
- Skills ship inside `app/ingest/skills`, are one directory deep, have `name` equal to the directory, descriptions of at most 1024 characters that say "use when", and the supervisor's skill set is pinned as a literal set (`entity-record`, `catalog-mapping`, `catalog-write-report`, `funder-scan-for-fundraisers`, `ngo-brief-for-funders`) with the researcher's two (`funder-intake-research`, `ngo-credential-research`) one level down. Only the researcher declares skills.

### SQL catalog and validator

The SQL tool is the agent's only door to the database, so its guards are tested at several layers:

- `test_sql_catalog.py` asserts what the catalog must **not** contain: chat checkpoint tables, `users`, `threads`, `schema_migrations`, `graph_ingest_log` (declared in `KNOWN_EXCLUDED`), the `contacts.email` and `contacts.phone` columns, `chunks.embedding`, and that `SELECT *` expansion cannot bring withheld or heavy columns back. It also checks that citation kinds stay within `org`, `funder`, `activity`, `score`, `news` (the frontend union), and that the import-time `_self_check` really rejects a dangling foreign key.
- `test_sql_validator.py` (DB-free) lists what must be refused: anything not a single SELECT, writes hidden in CTEs, `SELECT INTO`, locking clauses, multiple statements (including a smuggled `RESET ROLE`), unknown or withheld tables even inside CTEs or union arms, cross-schema references, a CTE shadowing a real table, and dangerous functions such as `pg_read_file`, `pg_sleep` and `lo_import`. Comment payloads never survive regeneration.
- `test_sql_integration.py` proves the server-side guards against real Postgres with the validator bypassed: **catalog vs schema** (`test_no_drift` fails when a catalogued table or column is missing from the live database, and every live base table must be either catalogued or in `KNOWN_EXCLUDED`, so a migration adding a table forces an explicit decision), read-only transactions refuse writes, `statement_timeout` fires, neither setting leaks onto the pooled connection that the LangGraph checkpointer also writes through, and the simple versus extended wire protocol difference is why `prepare=True` is mandatory. A DB-free test caps executor concurrency below `db_pool_max_size`.
- `test_prompt.py` ties the prompt to the code: every citation marker kind the tools emit appears in `SYSTEM_PROMPT`, every registered tool name appears in the prompt, and the retry budget stated in the prompt equals `MAX_SQL_ATTEMPTS` in the middleware.

### Roles and row-level security

`test_rls.py` builds a world (orgs A and B, a hidden org, one person per role, private contacts, documents, chunks, proposals and a thread) and queries it as each caller by setting the Postgres role and `request.jwt.claims` exactly as `CallerPool` does per request. It pins that private rows reach only the owning org and staff, hidden orgs reach only staff, signed-out callers cannot touch org-private tables at all, threads reach only their owner and staff, stewards read but cannot write their org, an admin sees the rest of the org, an org keeps its last admin, admins and members belong to one org only, saved match runs cannot be forged, edited or deleted, and Import tables are staff-only. `test_caller_pool.py` checks that a request runs as `anon` or `authenticated` with the token subject, that the connection returns to the pool as the owner with claims cleared, and that a permission error becomes a 403 with `{"detail": "Not allowed"}`. `test_security.py` covers JWT verification, and `test_import_roles.py` covers what members, stewards and staff may run, save and see in Import. See [Auth, Roles and RLS](../architecture/auth-roles-rls.md).

### Migrations

Schema changes are protected by three separate checks: the catalog-drift tests above, `test_migration_integrity.py` for seeded data after migrating, and file-level checks such as `test_storage.py` reading `db/migrations/0020_storage_buckets.sql` to assert both buckets are created (it skips if the file is not reachable). `make up` runs migrations before the backend starts because the backend's `_verify_sql_catalog` refuses to boot against an unmigrated database.

## Writing and changing tests

- Unit-test a router with `client_for(router)` and monkeypatch its repository function. If code under test touches the pool, the sentinel will fail it.
- A DB-backed test must carry `pytest.mark.integration`, skip on `OperationalError`, and roll back.
- Adding a table needs a catalog entry or a `KNOWN_EXCLUDED` entry, or `test_every_live_table_is_either_catalogued_or_knowingly_excluded` fails. Adding an agent tool needs it named in the prompt and in the pinned tool-set tests.
- Adding an eval case means a line in `cases/golden.jsonl` (or `cases/import/`) with an `id`, optional `tags`, and the gates described above. Keep `canary` for cheap, stable cases.
- Running the migration runner outside Docker needs `MIGRATIONS_DIR` (it defaults to the container path `/srv/db/migrations`). Environment selection for databases is covered in [Environments](../operations/environments.md).
