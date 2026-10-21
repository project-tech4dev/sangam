---
type: testing guide
title: Testing
description: How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how the frontend Vitest suite runs, how the CI workflow, dependency review and per-component Codecov 75% gates check every PR (CI never deploys), the test_cov_* coverage push, and which tests pin the system's security, tool-surface and proposal-copilot invariants.
tags: [testing, pytest, vitest, frontend, integration-tests, evals, sql-compare, ci, github-actions, codecov, coverage, invariants, proposals, rls]
sources:
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-cffc175ad16f1cf0f4a9e43f
    resource: repo://.github/workflows/dependency-review.yml
  - id: openwiki-source-6766b7a0c14857435d2077c9
    resource: repo://.github/workflows/deploy.yml
  - id: openwiki-source-813dbe9c3eeb378112388ccd
    resource: repo://backend/app/agent/middleware.py
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-539ff1e55b1e385204a4bb93
    resource: repo://backend/tests/conftest.py
  - id: openwiki-source-f02e0c938485b68ec56ef289
    resource: repo://backend/tests/cov_ingest_fakes.py
  - id: openwiki-source-39f5427f53dfb7fd20ac77cf
    resource: repo://backend/tests/evals/cases/import/canary.jsonl
  - id: openwiki-source-525d2a082ef8772e1fe91f69
    resource: repo://backend/tests/evals/conftest.py
  - id: openwiki-source-ad5342182b8b95a0dc091458
    resource: repo://backend/tests/evals/experiment.py
  - id: openwiki-source-9cd890b23995672427c6c8c4
    resource: repo://backend/tests/evals/harness.py
  - id: openwiki-source-28c0299addb344bf8508c6d2
    resource: repo://backend/tests/evals/import_harness.py
  - id: openwiki-source-78f442ef4d6533894276f5c3
    resource: repo://backend/tests/evals/sql_compare.py
  - id: openwiki-source-edebaaa991aec01704e84f6a
    resource: repo://backend/tests/evals/test_agent_evals.py
  - id: openwiki-source-e863856c857e426d63a2b3d8
    resource: repo://backend/tests/evals/test_import_calls.py
  - id: openwiki-source-d5d06fda351e6cb412c401d8
    resource: repo://backend/tests/evals/test_import_evals.py
  - id: openwiki-source-8ce79a18e6eab471015a75e0
    resource: repo://backend/tests/evals/test_run_stats.py
  - id: openwiki-source-4938b2b765d15256cece6bc9
    resource: repo://backend/tests/evals/test_sql_compare.py
  - id: openwiki-source-f298183777e9f6b64bb1b60f
    resource: repo://backend/tests/test_agent_middleware.py
  - id: openwiki-source-bc3c2ebc658cef90ceb7a159
    resource: repo://backend/tests/test_agent_rls.py
  - id: openwiki-source-32973df7d69d78ccef1499ff
    resource: repo://backend/tests/test_ask_budgets.py
  - id: openwiki-source-40274805d4a1f0905120868d
    resource: repo://backend/tests/test_audit.py
  - id: openwiki-source-0808792899dda5ae43456460
    resource: repo://backend/tests/test_caller_pool.py
  - id: openwiki-source-bea84748782ab0bf06fe9192
    resource: repo://backend/tests/test_cov_core_egress.py
  - id: openwiki-source-e5554658094627ddf1bb9942
    resource: repo://backend/tests/test_cov_db_migrate.py
  - id: openwiki-source-61df798cf075d4a6db550265
    resource: repo://backend/tests/test_cov_promote.py
  - id: openwiki-source-166fab4e004d0e4e6c342010
    resource: repo://backend/tests/test_cov_writer.py
  - id: openwiki-source-62d4dd57642429b3aa7980e3
    resource: repo://backend/tests/test_harness.py
  - id: openwiki-source-1f8a01f7f723a9c4852239b4
    resource: repo://backend/tests/test_ingest_middleware.py
  - id: openwiki-source-c19bf12e33dd13dd52164b8e
    resource: repo://backend/tests/test_migration_integrity.py
  - id: openwiki-source-fe6e4c3f43ca6fccc586454c
    resource: repo://backend/tests/test_prompt.py
  - id: openwiki-source-1a719932f8db409931d9e2ef
    resource: repo://backend/tests/test_proposal_agent.py
  - id: openwiki-source-ab7099b7aa694a12e8caad1a
    resource: repo://backend/tests/test_proposal_finish.py
  - id: openwiki-source-899c8be49aae16febe309b1e
    resource: repo://backend/tests/test_proposal_readers.py
  - id: openwiki-source-339d8fb79805ceb04a42a9e6
    resource: repo://backend/tests/test_proposal_suggest.py
  - id: openwiki-source-0607cb79e3440fdec4d15b13
    resource: repo://backend/tests/test_proposals_work.py
  - id: openwiki-source-e3d5b96924a7ab50f4e2652f
    resource: repo://backend/tests/test_rls.py
  - id: openwiki-source-b9b33576e920a6ec443c1309
    resource: repo://backend/tests/test_sql_catalog.py
  - id: openwiki-source-428476beae4aa2e70ded4bae
    resource: repo://backend/tests/test_sql_integration.py
  - id: openwiki-source-3e07dc90801342267034699a
    resource: repo://backend/tests/test_sql_validator.py
  - id: openwiki-source-15fedc74dfcdfee2ad718523
    resource: repo://backend/tests/test_tool_errors.py
  - id: openwiki-source-a2371d6362e5db4bc834ad03
    resource: repo://CLAUDE.md
  - id: openwiki-source-5f7022cb75865b779a5792a0
    resource: repo://codecov.yml
  - id: openwiki-source-46e3a6139ce071cd8d5f3b62
    resource: repo://docs/features/2026-10-21-coverage-75.md
  - id: openwiki-source-aa45754762425e69546840b0
    resource: repo://frontend/tests/setup.ts
  - id: openwiki-source-1d581b0a43d33a40ea0876c7
    resource: repo://frontend/vitest.config.mts
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-10-21T19:40:05.698Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-10-21T19:40:05.698Z
---

# Testing

Backend tests live in `backend/tests/` and run with pytest; frontend tests are Vitest files colocated with the code (see [Frontend Vitest suite](#frontend-vitest-suite)). The backend falls into three tiers that differ in what they need and what they cost. Pytest is configured in `backend/pyproject.toml` with `asyncio_mode = "auto"`, so async tests need no decorator, and with two registered markers, `integration` and `eval`.

| Tier | Needs | Marker | Costs money | Runs by default |
|---|---|---|---|---|
| Unit | nothing (no DB, no model, no network) | none | no | yes |
| Integration | compose Postgres on `localhost:5433` | `integration` | no | yes, but skips if the DB is unreachable |
| Evals | compose Postgres, a provider API key, `--run-evals` | `eval` | yes | no, always skipped without the flag |

CI runs the first two tiers, plus the frontend Vitest suite, on every pull request (see [CI](#ci-and-coverage)); it never runs evals.

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
pytest --cov                   # with coverage (pytest-cov is in the dev group)
ruff check .                   # line-length 110, target py312
```

From `frontend/`:

```bash
npm test                       # vitest run (both projects)
npm run coverage               # vitest run --coverage; what CI runs (v8 provider, writes coverage/lcov.info)
npm run lint                   # ESLint
npx tsc --noEmit               # type check
npm run build                  # type errors surface here and never in `next dev`
```

From the repo root, evals go through `make`:

```bash
make evals                     # every Ask case through the real agent (COSTS MONEY, ~10c/case; includes the ~$0.90 cost case)
make evals TAG=canary          # the cheap subset
make evals TAG=cost            # cases with call budgets (Better Life Foundation, ~$0.90 a run)
make evals TAG=import          # Import canaries: one funder, one NGO, ~15 min, needs TAVILY_API_KEY
make evals K=org-count         # one case, by pytest -k
```

`make evals` sources `.env` quietly (it carries the provider key, and the recipe line is `@`-prefixed so it is not echoed into scrollback), `cd`s into `backend/`, sets `TEST_DATABASE_URL` (the compose Postgres on `localhost:5433` by default, the managed database when `ENV=staging`), and runs `.venv/bin/python -m pytest tests/evals --run-evals [--eval-tag TAG] [-k K] -q`. `TAG` maps to `--eval-tag` and `K` to `-k`. It also sets `LANGFUSE_TRACING_ENVIRONMENT=eval` and `LANGFUSE_RELEASE` to the short git SHA. It runs on the **host venv**, not in a container, because the backend image installs runtime dependencies only and has no pytest. `make smoke` is a separate end-to-end check of the running stack (`SMOKE_SKIP_LLM=1` skips its one real agent call); it is not part of pytest.

## CI and coverage

Three workflows live in `.github/workflows/`, and only one of them can deploy.

- **`ci.yml`** runs on every pull request and every push to `master`. It has read-only `contents` permission, a concurrency group per ref with `cancel-in-progress`, and a timeout on each job. It **deploys nothing**.
- **`dependency-review.yml`** runs on pull requests, uses `actions/dependency-review-action@v4` with `fail-on-severity: high` and comments in the PR only on failure. It checks only what the PR's lockfile changes add; already-open advisories stay in GitHub's Dependabot alerts.
- **`deploy.yml`** is `workflow_dispatch` only (Actions → Deploy → Run workflow). Nothing deploys automatically: no push, merge or CI success triggers it. See [Deploy and Vendors](../operations/deploy-and-vendors.md).

`ci.yml` has four jobs:

| Job | What it runs |
|---|---|
| `backend-lint` | `uv sync --frozen`, then `ruff check . --output-format=github` |
| `backend-unit` | `pytest -m "not integration" --cov --cov-report=xml -q`, then uploads `backend/coverage.xml` to Codecov with flag `backend-unit` |
| `backend-integration` | a `pgvector/pgvector:pg17` service container published on `5433`; applies `db/init/*.sql` with `psql`, then `python -m app.db.migrate` (with `MIGRATIONS_DIR` set to the workspace's `db/migrations`), `seed.seed` and `seed.taxonomy_seed`, then `pytest -m integration --cov --cov-report=xml -q -rs`; uploads with flag `backend-integration` |
| `frontend` | on Node 22: `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm run coverage` (the Vitest suite with v8 coverage), an upload of `frontend/coverage/lcov.info` to Codecov with flag `frontend`, then `npm run build` |

Details that matter when a job goes red:

- The integration job runs with `-rs` so skips are listed: a test that skips with "Postgres not reachable" in CI means a broken job, not a pass. It deselects `test_migration_integrity.py::test_preserved_row_counts` and `::test_documents_sequence_advanced`, because those check a restore of the original dump (96 documents) that `make seed` never creates.
- Three jobs (`backend-unit`, `backend-integration`, `frontend`) upload to Codecov with OIDC (`id-token: write`, `use_oidc` is on unless the PR comes from a fork) rather than a stored token; fork PRs get no OIDC and fall back to tokenless upload. The flags are `backend,backend-unit`, `backend,backend-integration` and `frontend`; the shared `backend` flag is what the README badge reads.
- Backend coverage is configured in `backend/pyproject.toml` (`[tool.coverage.run]`: `source = ["app"]`, `branch = true`, `relative_files = true`), so the unit and integration `coverage.xml` files are relative to `backend/`. Frontend coverage is configured in `frontend/vitest.config.mts` and its `lcov.info` paths are relative to `frontend/`. `codecov.yml` rewrites both (`app/` to `backend/app/`, and `lib/`, `features/`, `components/` to their `frontend/` paths) so files line up with the repository.
- `codecov.yml` merges the uploads into one report per commit and turns the global `project` and `patch` statuses **off**; the gates are per **component** (`backend` for `backend/**`, `frontend` for `frontend/**`) so one side's figure cannot sink the other's. Each component has three statuses: a `floor-` project check that coverage stays at or above 75%, a project check against the base commit (`target: auto`, `threshold: 1%`, so a PR may not lower coverage by more than 1%) and a patch check that at least 75% of the lines the PR adds or changes are covered. Flags carry forward when a job did not upload. The PR comment shows diff, flags, components and files.
- The pytest-cov, ruff (pinned `ruff==0.16.8`) and ignore rules (`B008` for FastAPI `Depends()`, `RUF012`, `UP046`) are in `backend/pyproject.toml`. The design plan is `docs/features/2026-10-16-ci.md`; it was revised in review to use Codecov instead of a self-hosted coverage job, so its `coverage` job description no longer matches `ci.yml`.

`ci.yml` cannot reach a model or a paid key, so evals are never part of it. Run them by hand.

### The 75% coverage push

`docs/features/2026-10-21-coverage-75.md` records why the gates are 75%. Measured before the work, the backend merged unit+integration figure was about 60% (the gap was almost all Sangam Import: `promote.py`, `writer.py`, `staff_sources.py`, `news/pipeline.py`, `ingest/tools/*`, `calls/pull.py`) and the frontend was about 1%, because it had no DOM environment. The plan shipped as stacked PRs (a bar-raising PR, backend tests, frontend tests) and its results are recorded as backend 60% to 94% and frontend 1% to 97%. The patch gate is 75% on both sides, and the project target is 75% once each side got there.

Rules the plan held throughout, which still apply when adding tests:

- **No `omit` or `exclude` to lift the figure.** Every source file counts; the Vitest config likewise includes every file under `lib/`, `features/` and `components/` whether tested or not.
- **Integration tests build their own rows** in the rolled-back `db` fixture. CI's Postgres is fresh (baseline, migrations, `seed.seed`, `seed.taxonomy_seed`), so a test leaning on seeded or locally-imported rows fails there. The plan names three that already did locally, for example districts counting 952 locally against 784 on a fresh seed.
- **Unit tests monkeypatch `repositories/` functions, never the pool**, and assert that agent tools return `"<tool> failed: ..."` rather than raise.

The bulk of the backend push is the `backend/tests/test_cov_*.py` files, named by the area they cover, with a one-line docstring saying what is faked. They fall in two groups:

- **Unit (no database, fakes only)**: the Ask and Import middleware hooks driven directly with hand-built state (`test_cov_agent_middleware.py`, `test_cov_ingest_middleware.py`), SQL discovery tools against a fake executor (`test_cov_agent_sql_tools.py`), `search_graph` with a fake Graphiti client, `download_file` and `read_pdf` over a fake HTTP transport, the egress guard refusing private, loopback and metadata hosts with a fake resolver (`test_cov_core_egress.py`), lifespan boot wiring (`test_cov_core_lifespan.py`), the migration runner and `replicate` over fake connections, Storage and tracing clients against `httpx.MockTransport` or a fake Langfuse SDK, Import's research, catalog, pipeline and library/vault tools, news, calls and staff-workbook pipelines, and the proposals routes, tools, readers and context. Import tool tests share `backend/tests/cov_ingest_fakes.py`: `ScriptConn` and `ScriptPool` answer each query from the first rule whose substring it contains (the last answer repeats), record every statement, and `BrokenPool` proves a tool returns its failure instead of raising when the database is down.
- **Integration (real Postgres, rolled back)**: `test_cov_promote.py`, `test_cov_promote_org.py`, `test_cov_promote_extra.py`, `test_cov_writer.py`, `test_cov_matcher.py`, `test_cov_matching_repo.py`, `test_cov_repositories.py` and `test_cov_reshelve_undo.py` carry a file-level `integration` mark, plus one marked test in `test_cov_db_migrate.py`. They exercise the hand-written SQL the unit tier cannot reach: for example `promote()` end to end (findings in, catalog rows out, every hold and merge reported, with archiving faked because CI has no Supabase) and the writers' gate and tier-ranked org rows.

## Frontend Vitest suite

`frontend/vitest.config.mts` defines two Vitest **projects** that share one `@` alias to the frontend root:

| Project | Matches | Environment | Setup |
|---|---|---|---|
| `unit` | `**/*.test.ts` | node | none |
| `dom` | `**/*.test.tsx` | jsdom | `tests/setup.ts` |

So a test that renders a component must be a `.tsx` file; pure modules (`lib/`, `features/*/lib/` such as citations, toolLabels, board, sourcePick, filtersUrl) are `.test.ts` in node. Tests live in colocated `__tests__/` directories, over seventy files covering `lib/` (API client, auth, Supabase client, URL hooks, safe next-path), the `components/ui` primitives and `NavBar`, and the feature areas (Ask workspace and views, Funder Match, Proposals, Media, Import cards and board, Registry lists and profiles, Settings and members, Taxonomy, auth, home, terms).

`tests/setup.ts` (dom project only) loads `@testing-library/jest-dom/vitest` and installs the shared Next mocks. A mutable `navigation` object backs mocked `useRouter`, `usePathname`, `useSearchParams` and `useParams` (plus `redirect` and `notFound`), so a test sets `navigation.pathname` or `navigation.search` before rendering and asserts `navigation.router.push`. `next/link` becomes a plain `<a>`. jsdom has no `IntersectionObserver`, so a no-op class is assigned (not stubbed, so `vi.unstubAllGlobals()` cannot remove it); a test that needs observer callbacks replaces it. After each test it runs Testing Library `cleanup()`, resets the path and query, and resets the router mocks, so state never leaks between tests.

Coverage uses the v8 provider with `text-summary` and `lcov` reporters, including every `ts`/`tsx` file under `lib/`, `features/` and `components/` and excluding tests, `__tests__` directories and `.d.ts` files. CI runs it as `npm run coverage`; the `frontend` component's 75% gates apply to it (see [CI and coverage](#ci-and-coverage)). The plan also lists Supabase client and CopilotKit hooks as shared mocks; those are mocked in the tests that need them rather than in `setup.ts`.

## Tier 1: unit tests (no database)

`backend/tests/conftest.py` is the scaffolding. `make_app(*routers)` builds a router-only FastAPI app with **no lifespan**, so there is no pool, no agent and no model. It overrides three dependencies:

- `get_current_user` returns the fixed `TEST_USER`.
- `get_principal` returns `DEV_USER` (an assert in `conftest.py` keeps `DEV_USER_ID` equal to `TEST_USER`).
- `get_pool` returns `_SentinelPool`, an object that raises `AssertionError` on any attribute access.

Because routers resolve the pool through `Depends(get_pool)`, that single override covers every router. A unit test that reaches the database fails loudly, so the rule is: monkeypatch the `repositories/` function rather than the pool. The `client_for` fixture wraps `make_app` in an `httpx.AsyncClient` over `ASGITransport`.

The `build_import` fixture builds the Import agent with `resolve_model` replaced by `FakeListChatModel` instances named after their model spec and `create_deep_agent` replaced by a capture function. Tests can then assert which model, subagents and middleware the builder handed over without calling any model. Other unit tests use `httpx.MockTransport` (Supabase Storage in `test_storage.py`) or a generated ES256 key and patched JWKS client (`test_security.py`) to exercise auth without a network.

### Proposal copilot suites (unit, no database)

The Sangam Pitch agent's safeguards are pinned by a family of unit tests, none marked `integration`. They follow the design rule "the agent proposes, code checks" from [Proposal Copilot](../architecture/proposal-copilot.md): the tests call the pure rule modules and tool coroutines directly, and monkeypatch `repositories.proposals` functions (`save`, `org_of`, `user_name`) and `context.current` instead of touching a pool.

- **`test_proposals_work.py`** pins `work.apply`, the one way a proposal changes. Paths outside the allowed shapes (`summary`, `log`, `work`, unknown gates, unknown sections or fact ids, `stage` jumps, `sources`, a blank `title`) raise `BadChange`. A batch is atomic: if one change of several is refused, nothing is applied or logged. A section change must carry the `rev` it was read at, and a stale one raises `StaleSection` naming the current text and who changed it. A section's `rev` goes up once per save, and different sections do not clash. Every change is logged with who, `via`, `run_id`, path, `from`, `to`, facts and reason, with long values cut in the log but kept whole in the section. A step goes back by patch and forward only with `advance=True`, one step at a time. The summary is recomputed from the new work.
- **`test_proposal_agent.py`** covers `proposal_chat_access` through a small app built with `make_app`: admins and stewards run their own chat on a proposal, a member gets 403, a stranger gets 404 (so existence is not leaked), a thread that is not `proposal-<id>-<user id>` for that proposal is 404, and two editors get two chats that neither can open. It also checks that `advance_step` refuses a reader before `repo.save` is reached and otherwise names what is missing (`NOT YET: ...`), and what the model is told: the stable context block is deterministic and holds no written text, the live block carries the screen and the reader's read-only status, teammates' changes appear but not the caller's own, and only Anthropic gets the `cache_control` breakpoint. `test_the_agent_has_its_nine_tools_and_read_file_only` builds the real agent with an `InMemorySaver` and asserts the tools node holds exactly `add_facts`, `advance_step`, `ask_user`, `read_file`, `read_files`, `read_match`, `read_org_record`, `read_proposal`, `suggest_edit` and `write_section` (its name says nine and the list has ten because `read_file` is counted apart). It also covers the `nothing_to_answer` guard (a run whose history ends on an assistant reply ends without calling the model, a new human message is answered, a pending tool call is not treated as an answer, and an empty history jumps to the end), and `test_pitch_runs_the_guard` spies on `create_agent` to assert the guard sits in the Pitch agent's main middleware stack. The file ends with a security check that a local `dev:` test sign-in is refused with 401 once Supabase is configured.
- **`test_proposal_readers.py`** pins the readers' code-only safeguards. There are three kinds: one reader per ticked org file (tools `read_vault_document`, `read_brief`, `add_facts`, `read_file`), a funder reader (`read_brief`, `list_funder_documents`, `read_funder_document`, `read_template`, `add_facts`, `read_file`) and a **public research** reader (`search_public_sources`, `read_page`, `fetch_document`, `read_document_pages`, `add_facts`, `read_file`). The file readers and funder reader get no web tool, `ask_user`, `task`, `write_file` or `execute`, and the public reader is not built at all without a Tavily key (its button then says public research is unavailable). Each file reader may open only its own document (another ticked file is `REFUSED`) and the funder reader opens none of the org's files. `readers.pending` decides what a press reads: every ticked file plus the funder at first, only what failed on a retry, a second press while one is running raises `Busy` ("Admin started reading the files 2 min ago"), and a reader stuck past 31 minutes counts as stale and is read again (the limit is 30). The public search runs alone from its own button, neither blocks the other, its task text carries no figure from the org's files and says never to search for the org's name, and `PublicGuard` refuses a search naming the org (whole word only, so `SeSTAR` passes), keeps each page it read (keyed so `www.` and a trailing slash match) for the quote check, and records hosts that did not open. Only `via="agent"` may write `readers.*` marks (`BadChange` otherwise), and step 2's exit check requires the files to be read, waits while they are running, ignores a public search alone, and lets a failed file or a still-running public search through.
- **Companion files** cover the rule modules: `test_proposal_facts.py` (source colours, when `ask_user` may ask, fact checks per origin and de-duplication), `test_proposal_writing.py` (trace check per paragraph, section order, grade-to-score mapping, `missing` and `untraced` never set from outside), `test_proposal_suggest.py` (the passage must appear exactly once; untraced wording is refused before the person sees it; `KEPT`, `SAVED` and `FEEDBACK` outcomes; a teammate's newer save refuses "use"), `test_proposal_finish.py` (the polish check refuses any changed figure, year, place, name or gap, and `polished` and `versions` are writable only by their own routes) and `test_proposal_review.py` (how a corrected or set-aside fact propagates to the parts citing it and what stops `ready`). The `test_cov_proposals_*` files add coverage-push tests over the context block, pure assembly and gates, the `/api/proposals` routes against a faked in-memory repository, `readers.read` with fake reader graphs, and each tool's refusals (`add_facts`, `ask_user`, `write_section`, `read_proposal`, `advance_step`, the reading tools).

## Tier 2: integration tests (database)

Integration tests connect to `TEST_DATABASE_URL`, defaulting to `postgresql://sangam:sangam@localhost:5433/sangam` (the compose Postgres published port). Each file declares its own DSN and fixture, and each fixture does `pytest.skip("compose Postgres not reachable on localhost:5433")` on `OperationalError` after a 3-second connect timeout. So on a machine with no database the suite stays green by skipping rather than failing, and `pytest -m "not integration"` avoids even the connection attempts.

Isolation is by rollback. The shared `db` fixture in `conftest.py` opens a non-autocommit connection and rolls back afterwards; `test_rls.py` runs each test inside `connection.transaction(force_rollback=True)`. Test rows never persist. The exception is `test_agent_rls.py`, which needs a real pool (the agent's SQL executor reads `app.db.pool.pool`), so it commits rows tagged with a per-run `MARKER` and deletes them in a `finally` block.

The marker is applied either per file with `pytestmark = pytest.mark.integration` (`test_rls.py`, `test_agent_rls.py`, `test_sql_integration.py`, `test_migration_integrity.py`, `test_import_undo.py`, `test_news_rls.py`, `test_news_store.py`, `test_news_stories_sql.py`, `test_profile_facts_sql.py`) or per test (`test_caller_pool.py`, `test_news_pipeline.py`, `test_storage.py`, `test_locations_seed.py`, `test_taxonomy_seed.py`, `test_vault.py` and a few import tests). Files with per-test marks mix DB-free and DB-backed cases, so check the decorator rather than assuming a whole file needs Postgres. Applying the marker consistently matters: `-m "not integration"` only excludes what is marked.

Newer integration tests (the `test_cov_*` files) create their own rows inside that rolled-back transaction instead of leaning on seed data, which is what keeps them green on CI's fresh database. Some older ones still read seeded rows, so the data under test must already be loaded: run `make up` (which migrates) and `make seed` first. CI builds the same state without Docker (baseline SQL, migrations, `seed.seed`, `seed.taxonomy_seed`) and lists skips with `-rs`; `test_locations_seed.py` and `test_taxonomy_seed.py` mix DB-free file checks (for example 36 states and 784 districts in the LGD files) with `integration`-marked seed tests that run in a rolled-back transaction. `test_migration_integrity.py` asserts seeded facts, for example at least 96 `documents` rows (a floor, because the importer adds more), exactly 29 `graph_ingest_log` rows, stable seed-order ids (`kabil` = 9, `bdf` = 10, `axis-bank-foundation` = 1, `tata-trusts` = 4) and that the `documents` id sequence has advanced past the restored rows. It fails if migrations and seeds drifted apart. See [Data and Migrations](../architecture/data-and-migrations.md).

## Tier 3: evals (real model calls)

`backend/tests/evals/` runs questions through the **real agent**, so every case spends money (roughly 10 cents each) and takes real time. The gating lives in `tests/evals/conftest.py`:

- `--run-evals` and `--eval-tag` are registered with `pytest_addoption`. Without `--run-evals`, `pytest_collection_modifyitems` adds a skip marker to every test with the `eval` keyword.
- The gate is a conftest flag rather than an `addopts -m "not eval"` filter on purpose: a command-line `-m` replaces the `-m` in addopts, so `pytest -m integration` would otherwise start billing model calls.
- The `eval_settings` fixture skips when the API key for the configured provider (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GOOGLE_API_KEY`, chosen from the prefix of `Settings().model`) is not set.
- The `slug_ids` and `db` fixtures skip when Postgres is unreachable; unlike tier 2 they are session-scoped and read live `orgs` and `funders` ids, so evals run against your real seeded data, not a rolled-back fixture. Both open **read-only** connections (`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`), because `ENV=staging` points evals at the managed database.
- `pytest_terminal_summary` prints a per-case table (pass/fail, tool calls, model calls, tokens, seconds, tool-call breakdown) and the Langfuse run URL, or "Langfuse off" when no run was recorded.

### Ask evals (`test_agent_evals.py`)

Cases come from `cases/golden.jsonl` (11 cases at the time of writing: 8 tagged `canary`, two `safety` refusals, and one `cost` case, Better Life Foundation). `load_cases(tag)` reads every `*.jsonl` directly under `cases/` and filters by `--eval-tag`. Only the cases pytest actually selected (`-k`, `--eval-tag`, a node id) are run, so a narrowed run bills only those. Each case runs `build_agent` with an `InMemorySaver`, a recursion limit of 60 and, by default, a 180-second wall-clock timeout (added after a hung model request blocked a suite for hours; a case may override it with `timeout_seconds`, as the cost case does with 600). Each case opens its own small read-only pool and installs it as `app.db.pool.pool`; cases run strictly one at a time (`MAX_CONCURRENCY = 1`) because the agent's tools share that module-level pool. The harness runs as the staff dev user (`agent_caller` is set to the `DEV_USER` identity) so the agent reads what the owner-run gold SQL reads. It also resets `caveats_given` and sets `chat_user_id` to the dev user, because `compare_fit` refuses an unset chat user as someone who may not run a match. It extracts the SQL the agent actually executed from `db_query` tool messages (`executed: ...` lines) and the `[kind:id]` citation markers (kinds `org`, `funder`, `activity`, `grant`, `score`, `news`, `graph`) from the final answer, ignoring the audit's appended caveat message (`CAVEAT_PREFIX`), which is a second `AIMessage` and would otherwise be scored as the answer. A timeout fails the case with a message saying the model request hung or the agent looped.

Scoring (`harness.score`) applies whatever gates a case declares:

- **gold SQL**: the case's `gold_sql` is run against the database and compared with the agent's results by `sql_compare.gold_satisfied`. Every query the agent ran is tried, not only the last, since agents work in steps. If the agent ran no query, the answer must contain the gold values. The comparison lives in `tests/evals/sql_compare.py` and is described below.
- `expected_value`, `must_mention`, `must_not_mention`.
- `required_citations` and `forbidden_citations`; slug-based markers are resolved to ids via `slug_ids`, and `kind:*` forbids any citation of that kind.
- `must_decline`, matched against a deliberately narrow list of non-possession phrases so the check cannot pass on any sentence.
- **Budgets**: `max_calls` (per tool) and `max_large_result_reads` (reads of `/large_tool_results`, meaning a tool reply did not fit) fail the case. `max_seconds` and token counts are only reported as warnings or scores, never failures.

A case with `expected_failure` becomes `xfail(strict=True)`. When the underlying data bug is fixed the case passes, pytest reports XPASS as a failure, and the marker gets deleted, so the suite is never permanently red.

### The gold-SQL comparator (`sql_compare.py`)

`gold_satisfied(gold_rows, agent_rows, answer)` decides whether the agent's result answers what the gold SQL answers. It is pure Python, so `tests/evals/test_sql_compare.py` tests it with no model and no database and it runs in the normal unit suite. Its rules:

- **Cells**: numbers are normalised to floats (700, 700.0, `Decimal('700')` and `'700'` agree, with a relative tolerance of 1e-6), strings compare case-insensitively, and `None` equals only `None`. A label may match by substring when the shorter side has at least three characters, so gold `assam` matches an agent's `Assam (state)` but `a` does not match everything.
- **Scalar gold** (one row, one column): the value must appear in the agent's result (or equal its row count, for "7 states" answered by seven rows) **and** be stated in the narrated answer, since the answer is what carries the claim to the user.
- **Single-row gold** (a `LIMIT 1` top or bottom question): the gold row's cells need only appear within some agent row, because agents often show the whole ranking and narrate the winner, and the gold row's text labels must appear in the answer.
- **Multi-row gold**: some selection of the agent's columns (permutations, only when the agent's rows are at most `MAX_PROJECTION_WIDTH` = 6 wide) must equal the gold rows as an order-insensitive multiset. Extra columns are fine because agents enrich; extra or missing **rows** fail, since over-retrieval is the failure this guards against.
- **Label-tolerant fallback**: if the agent invented its own category labels ("Oct-Dec 2025" for gold "Q3"), the comparison falls back to the numeric cells, provided they are unambiguous and the gold labels still appear in the answer.
- `agent_values` strips the source and id columns (`PROVENANCE_PREFIX`, `CITE_PREFIX`) the validator adds to the agent's own SQL before the re-run rows are compared.

### Langfuse experiments and run stats

`run_stats` counts tool calls, model calls, input, output and cache tokens and large-result reads from the message list alone (a message without usage metadata is not a model call). With Langfuse keys set, `experiment.run_cases` runs the selected cases **once** as a dataset experiment on `ask-golden`, named `branch-sha` and filed under the `eval` environment, so two runs compare side by side with their cost and never mix with real traffic. `golden.jsonl` stays the source of truth; the dataset is a copy upserted by case id (`ask:<id>`). Each item gets a `passed` score plus numeric scores for the stats and a per-tool `calls.<tool>`, and the run gets a `pass_rate`. Without keys the same cases run as a plain loop, untraced. `tests/evals/test_run_stats.py` covers this counting, the budgets and the dataset sync on recorded messages and a fake Langfuse client: it carries no `eval` mark, needs no model or database, and runs in the normal unit suite.

### Import canaries (`test_import_evals.py`)

`cases/import/canary.jsonl` holds one funder (Axis Bank Foundation, `import-funder-axis`) and one NGO (The Ant, `import-ngo-the-ant`). They sit in a subdirectory, so `load_cases` for the Ask suite never sees them. The Import test only parametrises cases **when `--eval-tag` is given and matches**, so a bare `make evals` stays the cheap Ask suite and never starts a 15-minute import. Both cases carry the tags `import` and `canary`, so `TAG=canary` also selects them; `TAG=import` selects only them. A case skips when no Tavily key is available, either `TAVILY_API_KEY` in the environment or `tavily_api_key` in settings, because `search_public_sources` would have nothing to search.

Each case line carries an `expect_kind` (`funder` or `org`), `expect_concepts_any` and a `max_calls` budget keyed by tool name, either bare (`task`) or qualified by agent (`entity-researcher.save_research`). Both canaries allow one `choose_sources`, no `run_import_now`, at most two `task` calls and at most three researcher `save_research` calls.

`import_harness.run_import` sets the caller scope to staff, builds the Import agent with an `InMemorySaver`, and runs it under a 900-second timeout (`IMPORT_CASE_TIMEOUT_SECONDS`; an Ask case gets 180). It answers the `choose_sources` human-in-the-loop pause with public web plus the library (`SOURCES`), and raises if the run pauses on anything else or keeps pausing after three rounds, since another pause would mean a write the case never asked for. A `ToolCalls` callback counts every tool call, subagents included, under both `tool` and `agent.tool` (the agent comes from `lc_agent_name`, `supervisor` by default). The test uses its own pool (up to 6 connections) because researchers run in parallel and each reads and saves.

The test then judges the saved `entity_research` row, found by entity name among rows researched since the case started. Failures are collected and reported together:

- any tool called more often than `max_calls` allows (`call_failures`), because the path was wrong even if the row looks right;
- wrong `entity_kind`, no findings, or none of the expected concepts;
- a gap whose `reason` is not `blocked` or `not_stated`, or that has no detail;
- a tagged `program`, `identity` or `org_identity` finding with themes, populations or lenses but no `tag_note`;
- no researcher summary for the row's slug, or a summary `fact_count` that differs from the stored findings.

A missing row, or a timeout, fails the case outright. `tests/evals/test_import_calls.py` is the DB-free, model-free companion: it runs a scripted supervisor and researcher (`GenericFakeChatModel` subclass) through `create_deep_agent` to prove a subagent's calls are counted under its own name, and checks that only a call over its budget fails (a `max_calls` of 0 forbids the tool, and a case with no `max_calls` never fails). It carries no `eval` mark and runs in the normal unit suite. See [Sangam Import and Scout](../architecture/sangam-import-scout.md).

## Invariants the tests pin

These tests exist so a library upgrade, a migration or a refactor cannot silently weaken a guarantee. Most are DB-free.

### Tool surfaces (`test_harness.py`)

`create_deep_agent` is a preset that adds eight filesystem tools and, whenever any subagent is declared, a `general-purpose` subagent carrying the main agent's whole tool list. `test_harness.py` pins how `app/agent/harness.py` takes both back:

- The harness profile is installed idempotently, resolves for the configured model, disables the general-purpose subagent, and does **not** decide tools (profiles are per provider and global, while Import needs `read_file` for skills and Ask must not have it, so the surface is per-agent middleware).
- The replacement `FilesystemMiddleware` registers only `read_file`, or `read_file` plus `ls` when `SKILL_READING_TOOLS` is kept. Nothing that writes (`write_file`, `edit_file`, `delete`, `execute`) is in either set. `execute` is named in `FILESYSTEM_TOOLS` and excluded, because it is advertised as a sandbox shell on an agent that reads untrusted web pages.
- **Ask Sangam** has no `task` tool (no subagents) and exactly these tools: `db_list_tables`, `db_describe_table`, `db_profile_column`, `db_query`, `search_graph` and `compare_fit` (its six), plus the skill readers `read_file` and `ls`, eight in all (`test_ask_sangam_holds_its_six_tools_and_the_skill_readers`). There is no `fetch_url` tool. See [Ask Sangam](../architecture/ask-sangam.md).
- Neither agent can have `write_file`, `edit_file`, `delete`, `execute`, `glob` or `grep`.
- **Import** has four subagents (`entity-researcher`, `vault-reader`, `catalog-writer`, `workbook-reader`). The advertised-list test, `test_import_advertises_exactly_its_two_subagents`, is misnamed: it asserts only that `entity-researcher` and `catalog-writer` appear in the `task` description and that `general-purpose` does not. It does not check an exact set. It parses the advertised list instead of substring-searching, since deepagents boilerplate mentions `general-purpose` generically. The exact set of four is asserted separately, on the compiled subagents, in `test_both_subagents_are_compiled_and_found`.

### Ask limits, audit and tool-error backstop (unit, no database)

Four DB-free files pin the code-level limits on the agents rather than their prompts:

- **`test_audit.py`** pins the post-answer SQL audit. `collect_turn` reads the question, executed SQL, result and answer of the current turn only (a new human message resets it, so one turn's SQL is never audited against the next answer); `executed_sql` takes the SQL from the `db_query` artifact, or from the `executed:` line of older or failed results (a `db_query rejected:` message yields none). The audit makes no model call when no audit model is configured, when no SQL ran (curated-tool turns are free) or when there is no answer yet. Verdicts are `ok` or `warn` with a caveat; JSON wrapped in prose is still read and a `warn` without a caveat is treated as `ok`. It fails open: a raising model, an unresolvable model spec, an unparseable reply or malformed JSON all return `None` rather than breaking the turn. A final test shows an appended `CAVEAT_PREFIX` message is not mistaken for the answer, the same rule the eval harness relies on.

- **`test_agent_middleware.py`** pins `clear_old_tool_results` so clearing old tool output keeps the prompt prefix stable and the provider's prompt cache usable. Below `TOOL_RESULT_CLEAR_TRIGGER_TOKENS` nothing is cleared. Past it, the cleared set moves at most once per `TOOL_RESULTS_CLEAR_STEP` of growth, what is sent stays under the trigger however long the turn, the latest `TOOL_RESULTS_KEPT` results stay, and `compare_fit` results are never cleared. A test keeps the old fixed-setting configuration as a regression showing it broke the cache on nearly every call. It also checks `count_failed_sql_attempts`: failed `db_profile_column` calls count against the SQL retry budget like `db_query` ones, a successful profile never counts, and its rejections start `db_profile_column rejected:`.
- **`test_ask_budgets.py`** pins `compare_fit_refusal` (repeating the same arguments is refused, a call with explicit `funder_ids` is a different call, a fourth call is refused with "3 calls", and a new human question resets the budget) and `model_call_cap` (the turn ends with the `_CAPPED` message at the cap). It builds the real Ask stack with a spy on `create_agent` to assert a `ModelFallbackMiddleware` on the `research_model`, summarisation on the `utility_model`, a `CompareFitBudget` in the stack, and the cap's exit edge reaching `__end__` or an `after_agent` hook so the audit still runs. When `MODEL` and `RESEARCH_MODEL` are the same, no fallback is added.
- **`test_tool_errors.py`** pins `tool_errors()`: a tool that raises answers the model with an error `ToolMessage` naming the tool and exception type (`db_query failed: RuntimeError.`) and never the message text, so secrets do not leak; a `GraphInterrupt` still pauses. It spies on every compiled middleware stack and asserts exactly one `ToolErrorMiddleware` on Ask, on Import and each of its four subagents, and on the Pitch agent and its two readers.

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

- Each Import subagent runs on its tier: strong main model, mid `research_model` for researcher and vault reader, cheap `utility_model` for writer and workbook reader. A blank model variable takes its default, `off` disables `sql_audit_model`, and builders do not mutate the module-level subagent specs. `test_ingest_middleware.py` pins the fallback chain between tiers (a fallback to the same model is skipped), the researcher's reading limit (`ReadingLimit`, researcher only) and model-call limit coming from settings, and that the writer has a call limit while the workbook-reader has none.
- Skills ship inside `app/ingest/skills`, are one directory deep, have `name` equal to the directory, descriptions of at most 1024 characters that say "use when", and the supervisor's skill set is pinned as a literal set (`entity-record`, `catalog-mapping`, `catalog-write-report`, `funder-scan-for-fundraisers`, `ngo-brief-for-funders`) with the researcher's two (`funder-intake-research`, `ngo-credential-research`) one level down. Only the researcher declares skills.

### SQL catalog and validator

The SQL tool is the agent's only door to the database, so its guards are tested at several layers:

- The catalog allowlists 37 tables, and `KNOWN_EXCLUDED` holds 22 more that exist in the database but are deliberately withheld (`backend/app/agent/tools/sql/catalog.py`). The tests do not pin those counts. They pin the membership rules below.
- `test_sql_catalog.py` asserts what the catalog must **not** contain: chat checkpoint tables, `users`, `threads`, `schema_migrations`, `graph_ingest_log` (declared in `KNOWN_EXCLUDED`), the `contacts.email` and `contacts.phone` columns, `chunks.embedding`, and that `SELECT *` expansion cannot bring withheld or heavy columns back. It also checks that citation kinds stay within `org`, `funder`, `activity`, `score`, `news` (the frontend union), and that the import-time `_self_check` really rejects a dangling foreign key.
- `test_sql_validator.py` (DB-free) lists what must be refused: anything not a single SELECT, writes hidden in CTEs, `SELECT INTO`, locking clauses, multiple statements (including a smuggled `RESET ROLE`), unknown or withheld tables even inside CTEs or union arms, cross-schema references, a CTE shadowing a real table, and dangerous functions such as `pg_read_file`, `pg_sleep` and `lo_import`. Comment payloads never survive regeneration.
- `test_sql_integration.py` proves the server-side guards against real Postgres with the validator bypassed: **catalog vs schema** (`test_no_drift` fails when a catalogued table or column is missing from the live database, and every live base table must be either catalogued or in `KNOWN_EXCLUDED`, so a migration adding a table forces an explicit decision), read-only transactions refuse writes, `statement_timeout` fires, neither setting leaks onto the pooled connection that the LangGraph checkpointer also writes through, and the simple versus extended wire protocol difference is why `prepare=True` is mandatory. A DB-free test caps executor concurrency below `db_pool_max_size`.
- `test_prompt.py` ties the prompt to the code: every citation marker kind the tools emit appears in `SYSTEM_PROMPT`, every registered tool name appears in the prompt, and the retry budget stated in the prompt equals `MAX_SQL_ATTEMPTS` in the middleware.

### Roles and row-level security

`test_rls.py` builds a world (orgs A and B, a hidden org, one person per role, private contacts, documents, chunks, proposals and a thread) and queries it as each caller by setting the Postgres role and `request.jwt.claims` exactly as `CallerPool` does per request (`_as` runs `set_config('role', ...)` and `set_config('request.jwt.claims', ...)`). It pins that private rows reach only the owning org and staff, hidden orgs reach only staff, signed-out callers cannot touch org-private tables at all, threads reach only their owner and staff, stewards read but cannot write their org, an admin sees the rest of the org, an org keeps its last admin, admins and members belong to one org only, saved match runs cannot be forged, edited or deleted, and Import tables are staff-only. Proposal-specific rules sit in the same file: a proposal reaches only its org and staff, only admins, stewards and staff may insert or update one (a blocked `INSERT` raises `InsufficientPrivilege`, while a blocked `UPDATE` silently changes no row), and every role in the org, plus staff, may upload to the org's document vault. This is the database-side half of the edit rule that the unit tests above check in Python.

`test_agent_rls.py` proves that the Ask agent's SQL runs as the caller. It sets `agent_caller` to a `("authenticated", claims)` identity and runs validated SQL through `PsycopgExecutor`: a member of Org A sees its own private document and not Org B's, nor a staff-only `funder_activity` row; a user with no organisation sees no private row; with no caller the agent reads as `anon`; the connection returns to the pool as the owner with claims cleared; and every catalogued column is `SELECT`-able by `authenticated`, since the chat runs as the caller and an unreadable column would break `SELECT *`. See [Ask Sangam](../architecture/ask-sangam.md). `test_caller_pool.py` checks that a request runs as `anon` or `authenticated` with the token subject, that the connection returns to the pool as the owner with claims cleared, and that a permission error becomes a 403 with `{"detail": "Not allowed"}`. `test_security.py` covers JWT verification, and `test_import_roles.py` covers what members, stewards and staff may run, save and see in Import. See [Auth, Roles and RLS](../architecture/auth-roles-rls.md).

### Migrations

Schema changes are protected by three separate checks: the catalog-drift tests above, `test_migration_integrity.py` for seeded data after migrating, and file-level checks such as `test_storage.py` reading `db/migrations/0020_storage_buckets.sql` to assert both buckets are created (it skips if the file is not reachable). `make up` runs migrations before the backend starts because the backend's `_verify_sql_catalog` refuses to boot against an unmigrated database.

## Writing and changing tests

- Unit-test a router with `client_for(router)` and monkeypatch its repository function. If code under test touches the pool, the sentinel will fail it.
- Proposal rules belong in pure-function unit tests over a `work` dict (`work.apply`, `trace.check`, `steps.exit_check`); a new agent tool also needs adding to the pinned tool list in `test_proposal_agent.py`, and a new editing rule must be mirrored in `test_rls.py`.
- A DB-backed test must carry `pytest.mark.integration`, skip on `OperationalError`, roll back, and build the rows it asserts on rather than depend on seed data. Patches are gated at 75% covered lines per component, so new code needs tests in the same PR; do not add `omit` or `exclude` to move the figure.
- A frontend test that renders a component must be `.test.tsx` (jsdom, shared Next mocks); a pure module gets `.test.ts` (node). Set `navigation.pathname` or `navigation.search` from `tests/setup.ts` rather than mocking `next/navigation` again.
- Adding a table needs a catalog entry or a `KNOWN_EXCLUDED` entry, or `test_every_live_table_is_either_catalogued_or_knowingly_excluded` fails. Adding an agent tool needs it named in the prompt and in the pinned tool-set tests.
- Adding an eval case means a line in `cases/golden.jsonl` (or `cases/import/`) with an `id`, optional `tags`, and the gates described above. Keep `canary` for cheap, stable cases.
- Running the migration runner outside Docker needs `MIGRATIONS_DIR` (it defaults to the container path `/srv/db/migrations`). Environment selection for databases is covered in [Environments](../operations/environments.md).
