---
type: testing guide
title: Testing
description: How the backend test suite is split into unit tests (no database), integration tests (compose Postgres on :5433) and evals (real model calls that cost money), how the frontend Vitest suite and the per-component Codecov thresholds work, how CI and dependency review check every PR (CI never deploys), and which tests pin the system's architecture, security, tool-surface and proposal-copilot invariants.
tags: [testing, paging, registry, pytest, vitest, frontend, integration-tests, evals, ci, github-actions, codecov, coverage, architecture-tests, invariants, proposals, rls]
sources:
  - id: openwiki-source-164e2da859b5277df81c7d94
    resource: repo://.github/workflows/ci.yml
  - id: openwiki-source-cffc175ad16f1cf0f4a9e43f
    resource: repo://.github/workflows/dependency-review.yml
  - id: openwiki-source-6766b7a0c14857435d2077c9
    resource: repo://.github/workflows/deploy.yml
  - id: openwiki-source-fe3601d35ecee292c4d2b24d
    resource: repo://backend/app/agentkit/middleware.py
  - id: openwiki-source-10e08c1deca7d7728d8240c4
    resource: repo://backend/app/db/pool.py
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
  - id: openwiki-source-edebaaa991aec01704e84f6a
    resource: repo://backend/tests/evals/test_agent_evals.py
  - id: openwiki-source-e863856c857e426d63a2b3d8
    resource: repo://backend/tests/evals/test_import_calls.py
  - id: openwiki-source-d5d06fda351e6cb412c401d8
    resource: repo://backend/tests/evals/test_import_evals.py
  - id: openwiki-source-8ce79a18e6eab471015a75e0
    resource: repo://backend/tests/evals/test_run_stats.py
  - id: openwiki-source-f298183777e9f6b64bb1b60f
    resource: repo://backend/tests/test_agent_middleware.py
  - id: openwiki-source-bc3c2ebc658cef90ceb7a159
    resource: repo://backend/tests/test_agent_rls.py
  - id: openwiki-source-311a51435d74a84e6fc0f63c
    resource: repo://backend/tests/test_architecture.py
  - id: openwiki-source-32973df7d69d78ccef1499ff
    resource: repo://backend/tests/test_ask_budgets.py
  - id: openwiki-source-40274805d4a1f0905120868d
    resource: repo://backend/tests/test_audit.py
  - id: openwiki-source-0808792899dda5ae43456460
    resource: repo://backend/tests/test_caller_pool.py
  - id: openwiki-source-9d78480c624c25af8fc92fa1
    resource: repo://backend/tests/test_cov_agent_graph.py
  - id: openwiki-source-8df3702e94f4cc1a8901f88c
    resource: repo://backend/tests/test_cov_core_lifespan.py
  - id: openwiki-source-804c17c1cdc7ceed1bf73c82
    resource: repo://backend/tests/test_cov_repositories.py
  - id: openwiki-source-3fc2c8bed6b7ee0888a6c3eb
    resource: repo://backend/tests/test_deleted_documents.py
  - id: openwiki-source-62d4dd57642429b3aa7980e3
    resource: repo://backend/tests/test_harness.py
  - id: openwiki-source-1f8a01f7f723a9c4852239b4
    resource: repo://backend/tests/test_ingest_middleware.py
  - id: openwiki-source-c19bf12e33dd13dd52164b8e
    resource: repo://backend/tests/test_migration_integrity.py
  - id: openwiki-source-ca30f17cb9dd7937a8d05058
    resource: repo://backend/tests/test_paging.py
  - id: openwiki-source-fe6e4c3f43ca6fccc586454c
    resource: repo://backend/tests/test_prompt.py
  - id: openwiki-source-1a719932f8db409931d9e2ef
    resource: repo://backend/tests/test_proposal_agent.py
  - id: openwiki-source-3171911a670810234e4cc17c
    resource: repo://backend/tests/test_proposal_facts.py
  - id: openwiki-source-ab7099b7aa694a12e8caad1a
    resource: repo://backend/tests/test_proposal_finish.py
  - id: openwiki-source-f3633e1748b944ae1929d8a8
    resource: repo://backend/tests/test_proposal_form.py
  - id: openwiki-source-899c8be49aae16febe309b1e
    resource: repo://backend/tests/test_proposal_readers.py
  - id: openwiki-source-fd3f67613e110e15f2ff255f
    resource: repo://backend/tests/test_proposal_regex_linear.py
  - id: openwiki-source-339d8fb79805ceb04a42a9e6
    resource: repo://backend/tests/test_proposal_suggest.py
  - id: openwiki-source-0607cb79e3440fdec4d15b13
    resource: repo://backend/tests/test_proposals_work.py
  - id: openwiki-source-1b5480e092d7a09b76d2dff4
    resource: repo://backend/tests/test_registry_filters.py
  - id: openwiki-source-0eb35035a6a3d8b4021f5dac
    resource: repo://backend/tests/test_registry_sql.py
  - id: openwiki-source-7ad21629cd8f59763084adc2
    resource: repo://backend/tests/test_registry.py
  - id: openwiki-source-03cd5f1c2ac1a4db6357df24
    resource: repo://backend/tests/test_rfps.py
  - id: openwiki-source-e3d5b96924a7ab50f4e2652f
    resource: repo://backend/tests/test_rls.py
  - id: openwiki-source-b452c5f471e2aef0e36fb392
    resource: repo://backend/tests/test_scores.py
  - id: openwiki-source-b9b33576e920a6ec443c1309
    resource: repo://backend/tests/test_sql_catalog.py
  - id: openwiki-source-428476beae4aa2e70ded4bae
    resource: repo://backend/tests/test_sql_integration.py
  - id: openwiki-source-3e07dc90801342267034699a
    resource: repo://backend/tests/test_sql_validator.py
  - id: openwiki-source-77a336ada304965e7aa89c22
    resource: repo://backend/tests/test_storage.py
  - id: openwiki-source-15fedc74dfcdfee2ad718523
    resource: repo://backend/tests/test_tool_errors.py
  - id: openwiki-source-c9ec0e3b8ff5c20601084273
    resource: repo://backend/tests/test_vault.py
  - id: openwiki-source-a2371d6362e5db4bc834ad03
    resource: repo://CLAUDE.md
  - id: openwiki-source-5f7022cb75865b779a5792a0
    resource: repo://codecov.yml
  - id: openwiki-source-c1c958c5ad68d020fdee6247
    resource: repo://db/migrations/0053_deleted_documents.sql
  - id: openwiki-source-e2b923750735c644bf0f22f5
    resource: repo://frontend/app/api/copilotkit/%5B%5B...slug%5D%5D/route.ts
  - id: openwiki-source-0fdaa6836f51e708a4ee3903
    resource: repo://frontend/components/ui/__tests__/ListPage.test.tsx
  - id: openwiki-source-00263c26223c6a490764e0f6
    resource: repo://frontend/features/registry/__tests__/RegistryClient.test.tsx
  - id: openwiki-source-a8bd24489ee5c096845541ba
    resource: repo://frontend/lib/__tests__/copilotkit-route.test.ts
  - id: openwiki-source-4c6b88fce133b6d2e3039743
    resource: repo://frontend/lib/copilotkit-access.ts
  - id: openwiki-source-aa45754762425e69546840b0
    resource: repo://frontend/tests/setup.ts
  - id: openwiki-source-1d581b0a43d33a40ea0876c7
    resource: repo://frontend/vitest.config.mts
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "openwiki/0.7.2", at: "2026-11-11T11:11:22.403Z" }
verified:
  - by: openwiki/0.7.2
    at: 2026-11-11T11:11:22.403Z
---

# Testing

Backend tests live in `backend/tests/` and run with pytest. They fall into three tiers that differ in what they need and what they cost. Pytest is configured in `backend/pyproject.toml` with `asyncio_mode = "auto"`, so async tests need no decorator, and with two registered markers, `integration` and `eval`. The frontend has its own Vitest suite (see [Frontend tests](#frontend-tests-vitest)); it needs no database or network.

| Tier | Needs | Marker | Costs money | Runs by default |
|---|---|---|---|---|
| Unit | nothing (no DB, no model, no network) | none | no | yes |
| Integration | compose Postgres on `localhost:5433` | `integration` | no | yes, but skips if the DB is unreachable |
| Evals | compose Postgres, a provider API key, `--run-evals` | `eval` | yes | no, always skipped without the flag |

CI runs the first two backend tiers and the frontend suite on every pull request (see [CI](#ci-and-coverage)); it never runs evals.

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
npm test                       # vitest run
npm run coverage               # vitest run --coverage, as CI runs it
npm run lint                   # ESLint
npx tsc --noEmit               # type check
npm run build                  # type errors also surface here, never in `next dev`
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
| `frontend` | on Node 22: `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm run coverage` (Vitest with v8 coverage), an upload of `frontend/coverage/lcov.info` to Codecov with flag `frontend`, then `npm run build` |

Details that matter when a job goes red:

- The integration job runs with `-rs` so skips are listed: a test that skips with "Postgres not reachable" in CI means a broken job, not a pass. It deselects `test_migration_integrity.py::test_preserved_row_counts` and `::test_documents_sequence_advanced`, because those check a restore of the original dump (96 documents) that `make seed` never creates.
- Codecov uploads use OIDC (`id-token: write`) rather than a stored token; fork PRs get no OIDC (`use_oidc` is false for forks) and fall back to tokenless upload. There are three uploads per commit: flags `backend,backend-unit`, `backend,backend-integration` and `frontend`.
- Backend coverage is configured in `backend/pyproject.toml` (`[tool.coverage.run]`: `source = ["app"]`, `branch = true`, `relative_files = true`); frontend coverage in `frontend/vitest.config.mts` (see below). `codecov.yml` rewrites report paths (`app/` to `backend/app/`, and `lib/`, `features/`, `components/` to `frontend/...`).
- `codecov.yml` turns the global `project` and `patch` statuses **off** and gates the `backend` and `frontend` components separately (paths `backend/**` and `frontend/**`), so one side's figure cannot sink the other's. Each component has three checks: a **floor** (`floor-` prefix) requiring project coverage of at least 75%; a **drop rule** (`target: auto`, `threshold: 1%`) failing a PR that lowers coverage by more than 1% from the base commit; and a **patch** check requiring at least 75% of the lines the PR adds or changes. Flags carry forward when a job did not upload, and the PR comment lists flags, components and changed files.
- The pytest-cov, ruff (pinned `ruff==0.16.8`) and ignore rules (`B008` for FastAPI `Depends()`, `RUF012`, `UP046`) are in `backend/pyproject.toml`. The design plan is `docs/features/2026-10-16-ci.md`; it was revised in review to use Codecov instead of a self-hosted coverage job, so its `coverage` job description no longer matches `ci.yml`.

`ci.yml` cannot reach a model or a paid key, so evals are never part of it. Run them by hand.

## Frontend tests (Vitest)

`frontend/vitest.config.mts` defines two Vitest projects over the same `@` alias (the frontend root):

| Project | Files | Environment | Setup |
|---|---|---|---|
| `unit` | `**/*.test.ts` | `node` | none (pure modules such as URL-state helpers, row mappers, API clients, step logic) |
| `dom` | `**/*.test.tsx` | `jsdom` | `frontend/tests/setup.ts` |

A test that renders a component must therefore be `.tsx`. `tests/setup.ts` loads `jest-dom` matchers, mocks `next/navigation` with a mutable `navigation` object (tests set `pathname` and `search`; the router functions are `vi.fn()`) and `next/link` (a plain anchor), stubs `IntersectionObserver` (assigned, not stubbed, so `vi.unstubAllGlobals()` cannot remove it), and after each test calls `cleanup()` and resets the pathname, search params and router mocks. `node_modules` and `.next` are excluded.

Tests sit beside the code in `__tests__/` folders under `lib/`, `components/` and `features/` (ask, auth, home, ingest, registry, resources, settings, taxonomy, terms). The ones that guard shared contracts are the URL-state tests (`lib/__tests__/url-hooks.test.tsx`, `back-navigation.test.ts`, `safe-next-path.test.ts`), the auth and API-client tests (`lib/__tests__/auth.test.tsx`, `api-client.test.ts`, `server-auth.test.ts`, `supabase.test.ts`, plus `features/auth/__tests__`, which includes a login form with no Supabase keys), the Ask workspace and its views (`features/ask/__tests__/AskWorkspace.test.tsx`, funder match, RFP watch, proposals), and the Import screens (`features/ingest/__tests__` and its `components` and `lib` folders). See [Frontend](../architecture/frontend.md).

Two files pin the shared list pattern and its first user:

- **`components/ui/__tests__/ListPage.test.tsx`** covers the building blocks every list screen reuses. `BucketCards` marks the active bucket with `aria-pressed` and reports a pick; `FilterRow` renders nothing without filters and flags a moved filter with `data-set`; `SearchBox` reports typed text. `useShowMore` grows by a page and resets when its key changes. `ListMore` is empty with no rows, says "End of the list" at the end, offers at most one page more ("Show 3 more · 3 left", "Loading…" and disabled when busy) and, for its `IntersectionObserver` trigger, loads near the end only after the person has scrolled. `useCursorList` (keyset paging) follows `next_cursor` without repeating a row, keeps rows and reports the error when a page fails, does not keep the last key's page when a new key's first page fails, and drops an answer for a key that is no longer current. `usePagedList` (limit and offset) loads from offset 0 then the next offset until the total is shown, uses a server-rendered `first` page without fetching it again, restarts from offset 0 when the key changes and drops the old key's answer, does not show a row twice when the list shifted between pages (and reports `fetched`, so `ListMore` says "End of the list" rather than "1 left"), and resets `total`, `last` and `more` when a new key's first page fails.
- **`features/registry/__tests__/RegistryClient.test.tsx`** renders the Registry with `fetchRegistryPage` mocked (`vi.mock("@/features/registry/api")`) and a `first` page shaped like the server's `RegistryPage` (items, total, `counts`, `facets`). It checks bucket counts and profile links, that only the active bucket's own filters show (Registrations for CSOs, Funder type and approach for funders), filters read from the URL via the mocked `navigation.search`, filter changes written to the address as a replace that drops defaults, and that switching bucket resets the bucket-specific filters. The request tests assert what the server is asked: nothing on first render (the `first` page is used), one call once typing pauses (with `q`, `limit=25`, `offset=0`), a dropdown pick asks at once with the text typed so far, clearing a search with the filters asks once, and "Show 5 more · 5 left" asks for `offset=25` and keeps the cards and dropdown options from the first page when the later page carries empty `counts` and `facets`. Because `setUrlParams` writes jsdom's real history, which the shared setup does not reset, the file restores it itself in `afterEach`.

`lib/__tests__/copilotkit-route.test.ts` is a security test of the CopilotKit proxy route (`app/api/copilotkit/[[...slug]]/route.ts`). It imports the real `GET` and `POST` handlers, built exactly as the route builds the runtime, and calls them with no cookie or `Authorization`. `/info` must answer 200, while the runtime's in-memory thread store (`GET /threads`, `/threads/<id>/events`, `/threads/<id>/messages`, `POST /threads/clear`) must answer 404. The route's `onBeforeHandler` hook calls `allowRoute` in `lib/copilotkit-access.ts`, which serves only `info` and the `agent/*` methods the chat client uses (`run`, `connect`, `stop`, `suggest`) and throws a 404 `Response` for everything else, because chat history is read from the backend's `/api/threads` (under RLS), not from the runtime. If an upgrade adds a route to the runtime, this test fails until it is allowed or blocked deliberately.

Coverage uses the `v8` provider with `text-summary` and `lcov` reporters. Its `include` list is `lib/**`, `features/**` and `components/**` (`.ts` and `.tsx`), so **every source file counts whether or not a test imports it** and the figure is honest; test files, `__tests__` folders and `*.d.ts` are excluded. CI runs `npm run coverage` and uploads the `lcov.info`; the thresholds that fail a PR live in `codecov.yml` (75% floor, 1% drop, 75% patch for the `frontend` component), not in the Vitest config, so a local `npm run coverage` only reports a figure.

## Tier 1: unit tests (no database)

`backend/tests/conftest.py` is the scaffolding. `make_app(*routers)` builds a router-only FastAPI app with **no lifespan**, so there is no pool, no agent and no model. It overrides three dependencies:

- `get_current_user` returns the fixed `TEST_USER`.
- `get_principal` returns `DEV_USER` (an assert in `conftest.py` keeps `DEV_USER_ID` equal to `TEST_USER`).
- `get_pool` returns `_SentinelPool`, an object that raises `AssertionError` on any attribute access.

Routers take `PoolDep`, which builds a `CallerPool` over `Depends(get_pool)` (`app/db/pool.py`), so that single override covers every router. A unit test that reaches the database fails loudly, so the rule is: monkeypatch the `repositories/` function rather than the pool. The `client_for` fixture wraps `make_app` in an `httpx.AsyncClient` over `ASGITransport`.

When the test is *about* a repository function's SQL rather than a route, use the `recording_pool` fixture instead of monkeypatching. It returns the `RecordingPool` class: construct it with one list of rows per query you expect, and its `connection()` answers each `execute` with the next list, records `(sql, params)` in `calls` (`pool.sql` and `pool.params` are the first call's), and fails on any query beyond the scripted ones. This lets a test assert the query text, its bound parameters and how many round trips a function makes without a database.

An autouse fixture, `_plain_buckets`, deletes `STORAGE_BUCKET_SUFFIX` from the environment before every test, so a developer's shell (for example a `-local` suffix from `.env`) cannot rename the buckets the storage and vault tests expect. A test that wants a suffix sets it explicitly through `Settings(storage_bucket_suffix=...)`.

The `build_import` fixture builds the Import agent with `resolve_model` replaced by `FakeListChatModel` instances named after their model spec and `create_deep_agent` replaced by a capture function. Tests can then assert which model, subagents and middleware the builder handed over without calling any model. Other unit tests use `httpx.MockTransport` (Supabase Storage in `test_storage.py`) or a generated ES256 key and patched JWKS client (`test_security.py`) to exercise auth without a network.

### Storage and the Doc Vault (`test_storage.py`, `test_vault.py`)

These two files mix DB-free tests with `integration`-marked classes (check the decorators). The DB-free parts pin the trust boundary around uploaded files:

- **Storage client** (`test_storage.py`, against `httpx.MockTransport`): storage is enabled only when both `supabase_url` and `supabase_service_key` are set; a disabled client makes no request at all; failures are return values (`None` or `False`), never exceptions. `storage.owned_split` trusts a path only inside the row's own folder (`org-vault/<org_id>/...` only for that exact org id, so `org-vault/33/` does not match org 3; `staff-sources/` only for a non-public row with no org; `source-archive/` for the archive), so a row cannot claim another org's file. `vault_key` cuts long names but keeps the extension, because the vault reads a file's type from its key.
- **Bucket migration and suffix**: file-level checks on `db/migrations/0020_storage_buckets.sql` (both buckets created, both private, guarded by a `pg_namespace` check for plain Postgres, idempotent via `ON CONFLICT`), and a check that the vault bucket's allowed MIME types in migration 0055 equal `storage.VAULT_TYPES`. With `storage_bucket_suffix="-local"` every call (upload, download, sign, remove, list, move, trash) names the suffixed bucket while rows and callers keep the plain name; the suffix is dropped automatically when `database_url` points at the same Supabase project as the storage URL, so staging data keeps the plain buckets.
- **Vault routes** (`test_vault.py`, via `client_for`): a member gets a signed upload URL whose key leads with the org id (the RLS predicate); a type the vault cannot read is 415 before any URL is minted; a non-member and an unknown org both get 403 (existence is not leaked); unconfigured storage is 503. Confirming an upload refuses a key in another org's folder (403) or the archive bucket (400), a missing object (404), an already-recorded path (409, never read or removed), and a file whose bytes do not match its extension (`_bytes_match`; the object is removed and the response is 415), including a file just under the 50 MB limit. A file that cannot be read back gets 503 with no row and the object kept so the confirm can be retried; NUL bytes are stripped from extracted text. Downloads return a signed link, and another org's private document or a row pointing outside its org's folder is a 404, not a 403. Delete is staff-only and maps `DocumentInUse` to 409, `FileNotRemoved` to 502 and `RowNotRemoved` to 500; `_remove_vault_file` never removes a path outside the caller's own vault folder. A repository-level delete that RLS quietly refuses (zero rows) touches no file, and a commit that fails after the file went raises `RowNotRemoved` and logs the path of the lost file. The same file also holds the document list's paging tests (see [Server-side paging](#server-side-paging-test_pagingpy-and-the-list-tests)): `list_documents` passes its filters through `fetch_page`, and `GET /api/documents` answers with the `{items, total, limit, offset}` page.

The `integration`-marked classes prove the SQL these tests otherwise monkeypatch: `TestWhoMayTouchAnOrgsVault` (a member reads and writes, a steward reads but cannot write, an outsider gets nothing, staff write without membership) and `TestDeleteVaultUpload` (row and file go together; a document with chunks, or used by a proposal as its draft, template or budget, is refused before the file is touched; only a private `vault_upload` is deleted). They use `_PoolOf` from `test_storage.py`, which dresses the fixture's connection as a pool so the repository runs inside the rolled-back transaction.

`test_deleted_documents.py` (`pytestmark = pytest.mark.integration`) pins the audit trigger from migration `0053_deleted_documents.sql`: every `DELETE FROM documents` writes the whole old row, as `to_jsonb`, into `deleted_documents` whoever deletes it and however, and a delete the repository refuses (`FileNotRemoved`) logs nothing.

### Server-side paging (`test_paging.py` and the list tests)

Every list screen is paged in Postgres through `repositories/paging.fetch_page` (design in [Data and Migrations](../architecture/data-and-migrations.md#server-side-paging); the RFP list is in [RFP Watch](../architecture/rfp-watch.md)). The tests pin it at three levels, and all but the last need no database:

- **`test_paging.py`** drives `fetch_page` with a `recording_pool`. It appends `LIMIT %(limit)s OFFSET %(offset)s` and adds `limit` and `offset` to the bound params; reads `total` from the first row, so a non-empty page costs exactly one query; an empty first page is total 0 with no second query; a page past the end runs one `SELECT count(*) AS total FROM (...) listed` with the original params so the list's total is still reported (0 for an empty list). The SQL must end in `ORDER BY ... id` (an `id` with `DESC` or `NULLS LAST` still counts), and `fetch_page` raises `ValueError` matching `ORDER BY` **before any query** for a missing unique tie-breaker, a trailing `;`, its own `LIMIT`, a trailing comment (including one that happens to end in `id`) or an `ORDER BY` only inside a subquery. A parametrized test then calls each of the ten paged list functions (`contacts`, `documents`, `funders`, `meta.list_tags`, `meta.list_locations`, `orgs`, `partner_lines`, `programs`, `rfps`, `scores`) and relies on that guard, so a new or edited list whose sort does not end in a unique id fails; add a new list function to the `LISTS` table.
- **Per-resource tests** check that a list passes its filters and its `limit` and `offset` through `fetch_page`, again with `recording_pool`: `test_rfps.py` (`status`, `deadline_before`), `test_scores.py` (`org`, `rubric`) and `test_vault.py` (`list_documents` with `org`, `doc_type`, `user_id`; the exact param set is asserted). Their route tests monkeypatch the repository to return `(rows, total)` and assert the `{items, total, limit, offset}` envelope; `GET /api/scores` answers 422, not a silent clamp, for an out-of-range `limit`, and `GET /api/registry` for `limit` 0 or 101 or a negative `offset`.
- **`test_registry.py`** (unit) covers the `GET /api/registry` route: query parameters become a `Filters` value (`type=cso` is kind `org`, any unknown type is `all`), research counts are read for the page's rows only and not at all for an empty page, a failed research read leaves the page up, and the row's themes lead with the tags most of its programmes carry with lenses left out. `test_registry_filters.py` parses `frontend/features/registry/rows.ts` and requires its `NORTH_EAST` list to equal the backend's, because the SQL filter and the browser must agree (it skips if the frontend is not checked out).
- **`test_registry_sql.py`** (`integration`) runs `registry_page_sql` against Postgres, inside the rolled-back `db` fixture with a throwaway `world` of three CSOs and two funders whose names carry a random token, so `q=<token>` isolates them on a seeded database. It pins ordering (CSOs first, then funders, each A to Z ignoring case), every filter (kind, theme, population, SDG, `where` as `ne`, `out` or one state, registrations for CSOs only, funder type and approach for funders only), search over aliases, programmes and states inside a word, combined filters, and that `total` counts every match whatever the page. The cards and dropdown counts cover the whole Registry only on the first page: a later page returns empty `counts` and `facets`, and an `EXPLAIN` of its SQL shows the facet counting cut from the plan. Registrations are read through the owner pool for the page's orgs only (one query, `org_id = ANY(%(ids)s)`), not at all for a page of funders, and a registrations filter asks only for the orgs it keeps. A last test requires `entity_tag_domains` to give the same domains as a recursive walk up the tag tree.

### Coverage tests (`test_cov_*.py`)

A large family of files named `test_cov_<area>.py` exists to cover code that the behaviour-focused suites do not reach, so the Codecov floors and patch checks hold. They follow the unit rules: hand-built state and requests, fakes in place of Neo4j, Supabase Storage, Langfuse and the model, and monkeypatched repositories. Areas include Ask's graph tool and middleware hooks, SQL tools, the lifespan boot wiring (`test_cov_core_lifespan.py`), the migration runner and replicator, Import's tools, middleware, access and contract checks, the news and RFP pipelines, promotion, the matcher and the proposal route, tools and readers. `backend/tests/cov_ingest_fakes.py` supplies a scripted pool (`ScriptConn`: each query is answered by the first rule whose text it contains) and a `running_as(scope)` context manager for the Import tool tests. A few of these files carry `pytestmark = pytest.mark.integration` (migration runner, matcher, promotion, repositories, writer, reshelve/undo) and use the shared `db` fixture, so they run only in the integration job; the rest run in `backend-unit`. They do not replace the invariant tests below: change a rule in the invariant file first and treat a `test_cov_` failure as a behaviour change to review, not a number to restore.

### Architecture rules (`test_architecture.py`)

`test_architecture.py` checks the code-boundary rules from `CLAUDE.md` over the source with `ast`, so they cannot drift into prose. It needs no database and reads every file under `backend/app/`:

- **R1**: only an agent's builder (`app/ask/agent.py`, `app/ingest/agent.py`, `app/proposals/agent.py`, `app/ingest/news/verify.py`) may import from a `tools/` package; Ask's SQL engine under `app.ask.tools.sql` is exempt because it is not a tool.
- **R2**: an import inside a function needs a reason. Only cold-start paths (`app/api/routes/`, `app/core/lifespan.py`, `app/db/migrate.py`, `app/integrations/`, `app/ingest/news/`, `app/ingest/calls/`) may use them, plus a `CYCLES` set that "a later PR may shrink, never grow"; a second test fails if a listed cycle is no longer lazy.
- **R3**: the three agents (`ask`, `ingest`, `proposals`) import each other only through an explicit shared list (the SQL catalog, and Import's brief, geography, reading rules, source guards and reading tools that Pitch reuses); everything else shared lives in `agentkit/` or `core/`. A subprocess test also asserts that importing `app.main` loads neither `deepagents` nor `langchain`, so a cold start stays light.
- **R4**: no file under `app/` is over 800 lines, except the catalog (one entry per table) and `finding_types.py`.
- **R6**: every top-level function or class (undecorated, not `main`) is named somewhere else in `app/`, `seed/` or `scripts/`; tests do not count as callers, so dead code fails.

### Proposal copilot suites (unit, no database)

The Sangam Pitch agent's safeguards are pinned by a family of unit tests, none marked `integration`. They follow the design rule "the agent proposes, code checks" from [Proposal Copilot](../architecture/proposal-copilot.md): the tests call the pure rule modules and tool coroutines directly, and monkeypatch `repositories.proposals` functions (`save`, `org_of`, `user_name`) and `context.current` instead of touching a pool.

- **`test_proposals_work.py`** pins `work.apply`, the one way a proposal changes. Paths outside the allowed shapes (`summary`, `log`, `work`, unknown gates, unknown sections or fact ids, `stage` jumps, `sources`, a blank `title`) raise `BadChange`. A batch is atomic: if one change of several is refused, nothing is applied or logged. A section change must carry the `rev` it was read at, and a stale one raises `StaleSection` naming the current text and who changed it. A section's `rev` goes up once per save, and different sections do not clash. Every change is logged with who, `via`, `run_id`, path, `from`, `to`, facts and reason, with long values cut in the log but kept whole in the section. A step goes back by patch and forward only with `advance=True`, one step at a time. The summary is recomputed from the new work.
- **`test_proposal_agent.py`** covers `proposal_chat_access` through a small app built with `make_app`: admins and stewards run their own chat on a proposal, a member gets 403, a stranger gets 404 (so existence is not leaked), a thread that is not `proposal-<id>-<user id>` for that proposal is 404, and two editors get two chats that neither can open. It also checks that `advance_step` refuses a reader before `repo.save` is reached and otherwise names what is missing (`NOT YET: ...`), and what the model is told: the stable context block is deterministic and holds no written text, the live block carries the screen and the reader's read-only status, teammates' changes appear but not the caller's own, and only Anthropic gets the `cache_control` breakpoint. `test_the_agent_has_its_nine_tools_and_read_file_only` builds the real agent with an `InMemorySaver` and asserts the tools node holds exactly `add_facts`, `advance_step`, `ask_user`, `read_file`, `read_files`, `read_match`, `read_org_record`, `read_proposal`, `suggest_edit` and `write_section` (its name says nine and the list has ten because `read_file` is counted apart). It also covers the `nothing_to_answer` guard (a run whose history ends on an assistant reply ends without calling the model, a new human message is answered, a pending tool call is not treated as an answer, and an empty history jumps to the end), and `test_pitch_runs_the_guard` spies on `create_agent` to assert the guard sits in the Pitch agent's main middleware stack. The file ends with a security check that a local `dev:` test sign-in is refused with 401 once Supabase is configured.
- **`test_proposal_form.py`** pins filling a funder's own form: `form.check` keeps the form's order, numbers and groups, gives codes `T1`, `T2`, ..., merges a label-less heading into the one before and caps long text; a PDF reaches Anthropic as a `document` block and a Word form as text, and any other type raises `form.Unreadable`. The fill check (`fill.check`) refuses an added or changed figure (`added 2500`) or an answer over the form's character or word limit, but allows a cut, a figure from another part and a new `[Add: ...]` gap. `fill.resolve` gives every heading an outcome (`answered`, `add` or `you_fill`): a refused answer becomes a plain `[Add: ...]` mark and is logged, tables and annexes are always left for the person, `skip` headings and second-phase questions on a first-phase proposal are dropped, and an over-limit answer is trimmed at sentence (or semicolon, never comma) boundaries or refused. `form.read` runs against a `FakeModel` and patched storage: only the first 100 pages (`MAX_PAGES`) of a PDF are sent, and a form with no usable copy, an undownloadable file or no written questions says why. The fill call is one model call and returns nothing when the model fails. The generated Word file carries the form's headings and highlights what is left.
- **`test_proposal_regex_linear.py`** is a performance guard for the proposal regexes CodeQL flagged as polynomial: each (`trace.GAP`, `readiness._GAP`, `fill._GAP`, `fill._YOU`, `assemble._LEFT`, `trace.extract`, `trace.drop_cites`, the lakh/crore amount parsers) must finish on a 50,000-character hostile string in under a second, and the rewritten functions are compared with the old regex on realistic input so behaviour did not change.
- **Companion files** cover the rule modules: `test_proposal_facts.py` (source colours: registry and vault green, web and derived amber, `you_said` said, an unknown origin raises; when `ask_user` may ask (a missing element, a disagreement between equally strong sources, only the organisation's call on an amount) and the ask gate that refuses a gap open with a teammate; fact checks per origin and de-duplication), `test_proposal_writing.py` (trace check per paragraph, section order, grade-to-score mapping, `missing` and `untraced` never set from outside), `test_proposal_suggest.py` (the passage must appear exactly once; untraced wording is refused before the person sees it; `KEPT`, `SAVED` and `FEEDBACK` outcomes; a teammate's newer save refuses "use"), `test_proposal_finish.py` (the polish check refuses any changed figure, year, place, name or gap, and `polished` and `versions` are writable only by their own routes), `test_proposal_readers.py` (the compiled reader tool sets: file reader, funder reader and, when a Tavily key is set, a public researcher that reads the web and no file; none asks, writes or launches; the public researcher is never built without a search key; a `PublicGuard` refuses searches naming the organisation and keeps each page read for the quote check; one file per file reader, the busy lock, the 30-minute stale limit, and step 2's exit check) and `test_proposal_review.py` (how a corrected or set-aside fact propagates to the parts citing it and what stops `ready`).

## Tier 2: integration tests (database)

Integration tests connect to `TEST_DATABASE_URL`, defaulting to `postgresql://sangam:sangam@localhost:5433/sangam` (the compose Postgres published port). Each file declares its own DSN and fixture, and each fixture does `pytest.skip("compose Postgres not reachable on localhost:5433")` on `OperationalError` after a 3-second connect timeout. So on a machine with no database the suite stays green by skipping rather than failing, and `pytest -m "not integration"` avoids even the connection attempts.

Isolation is by rollback. The shared `db` fixture in `conftest.py` opens a non-autocommit connection and rolls back afterwards; `test_rls.py` runs each test inside `connection.transaction(force_rollback=True)`. Test rows never persist. The exception is `test_agent_rls.py`, which needs a real pool (the agent's SQL executor reads `app.db.pool.pool`), so it commits rows tagged with a per-run `MARKER` and deletes them in a `finally` block.

The marker is applied either per file with `pytestmark = pytest.mark.integration` (`test_rls.py`, `test_agent_rls.py`, `test_sql_integration.py`, `test_registry_sql.py`, `test_migration_integrity.py`, `test_deleted_documents.py`, `test_import_undo.py`, `test_news_rls.py`, `test_news_store.py`, `test_news_stories_sql.py`, `test_profile_facts_sql.py`) or per test (`test_caller_pool.py`, `test_news_pipeline.py`, `test_storage.py`, `test_locations_seed.py`, `test_taxonomy_seed.py`, `test_vault.py` and a few import tests). Files with per-test marks mix DB-free and DB-backed cases, so check the decorator rather than assuming a whole file needs Postgres. Applying the marker consistently matters: `-m "not integration"` only excludes what is marked.

The data under test must already be loaded: run `make up` (which migrates) and `make seed` first. CI builds the same state without Docker (baseline SQL, migrations, `seed.seed`, `seed.taxonomy_seed`) and lists skips with `-rs`; `test_locations_seed.py` and `test_taxonomy_seed.py` mix DB-free file checks (for example 36 states and 784 districts in the LGD files) with `integration`-marked seed tests that run in a rolled-back transaction. `test_migration_integrity.py` asserts seeded facts, for example at least 96 `documents` rows (a floor, because the importer adds more), exactly 29 `graph_ingest_log` rows, stable seed-order ids (`kabil` = 9, `bdf` = 10, `axis-bank-foundation` = 1, `tata-trusts` = 4) and that the `documents` id sequence has advanced past the restored rows. It fails if migrations and seeds drifted apart. See [Data and Migrations](../architecture/data-and-migrations.md).

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

- **gold SQL**: the case's `gold_sql` is run against the database and compared with the agent's results by `sql_compare.gold_satisfied`. Every query the agent ran is tried, not only the last, since agents work in steps. If the agent ran no query, the answer must contain the gold values. `sql_compare` normalises numbers (700, 700.0 and `Decimal('700')` agree), matches labels loosely, and is itself covered by the DB-free `test_sql_compare.py`.
- `expected_value`, `must_mention`, `must_not_mention`.
- `required_citations` and `forbidden_citations`; slug-based markers are resolved to ids via `slug_ids`, and `kind:*` forbids any citation of that kind.
- `must_decline`, matched against a deliberately narrow list of non-possession phrases so the check cannot pass on any sentence.
- **Budgets**: `max_calls` (per tool) and `max_large_result_reads` (reads of `/large_tool_results`, meaning a tool reply did not fit) fail the case. `max_seconds` and token counts are only reported as warnings or scores, never failures.

A case with `expected_failure` becomes `xfail(strict=True)`. When the underlying data bug is fixed the case passes, pytest reports XPASS as a failure, and the marker gets deleted, so the suite is never permanently red.

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

`create_deep_agent` is a preset that adds eight filesystem tools and, whenever any subagent is declared, a `general-purpose` subagent carrying the main agent's whole tool list. `test_harness.py` pins how `app/agentkit/harness.py` takes both back:

- The harness profile is installed idempotently, resolves for the configured model, disables the general-purpose subagent, and does **not** decide tools (profiles are per provider and global, while Import needs `read_file` for skills and Ask must not have it, so the surface is per-agent middleware).
- The replacement `FilesystemMiddleware` registers only `read_file`, or `read_file` plus `ls` when `SKILL_READING_TOOLS` is kept. Nothing that writes (`write_file`, `edit_file`, `delete`, `execute`) is in either set. `execute` is named in `FILESYSTEM_TOOLS` and excluded, because it is advertised as a sandbox shell on an agent that reads untrusted web pages.
- **Ask Sangam** has no `task` tool (no subagents) and exactly these tools: `db_list_tables`, `db_describe_table`, `db_profile_column`, `db_query`, `search_graph` and `compare_fit` (its six), plus the skill readers `read_file` and `ls`, eight in all (`test_ask_sangam_holds_its_six_tools_and_the_skill_readers`). There is no `fetch_url` tool. See [Ask Sangam](../architecture/ask-sangam.md).
- Neither agent can have `write_file`, `edit_file`, `delete`, `execute`, `glob` or `grep`.
- **Import** has four subagents (`entity-researcher`, `vault-reader`, `catalog-writer`, `workbook-reader`). The advertised-list test, `test_import_advertises_exactly_its_two_subagents`, is misnamed: it asserts only that `entity-researcher` and `catalog-writer` appear in the `task` description and that `general-purpose` does not. It does not check an exact set. It parses the advertised list instead of substring-searching, since deepagents boilerplate mentions `general-purpose` generically. The exact set of four is asserted separately, on the compiled subagents, in `test_both_subagents_are_compiled_and_found`.

### Ask limits, audit and tool-error backstop (unit, no database)

Four DB-free files pin the code-level limits on the agents rather than their prompts:

- **`test_audit.py`** pins the post-answer SQL audit. `collect_turn` reads the question, executed SQL, result and answer of the current turn only (a new human message resets it, so one turn's SQL is never audited against the next answer); `executed_sql` takes the SQL from the `db_query` artifact, or from the `executed:` line of older or failed results (a `db_query rejected:` message yields none). The audit makes no model call when no audit model is configured, when no SQL ran (curated-tool turns are free) or when there is no answer yet. Verdicts are `ok` or `warn` with a caveat; JSON wrapped in prose is still read and a `warn` without a caveat is treated as `ok`. It fails open: a raising model, an unresolvable model spec, an unparseable reply or malformed JSON all return `None` rather than breaking the turn. A final test shows an appended `CAVEAT_PREFIX` message is not mistaken for the answer, the same rule the eval harness relies on.

- **`test_agent_middleware.py`** pins `clear_old_tool_results` (shared, in `app/agentkit/middleware.py`; the SQL-attempt counter is Ask's, in `app/ask/middleware.py`) so clearing old tool output keeps the prompt prefix stable and the provider's prompt cache usable. Below `TOOL_RESULT_CLEAR_TRIGGER_TOKENS` nothing is cleared. Past it, the cleared set moves at most once per `TOOL_RESULTS_CLEAR_STEP` of growth, what is sent stays under the trigger however long the turn, the latest `TOOL_RESULTS_KEPT` results stay, and `compare_fit` results are never cleared. A test keeps the old fixed-setting configuration as a regression showing it broke the cache on nearly every call. It also checks `count_failed_sql_attempts`: failed `db_profile_column` calls count against the SQL retry budget like `db_query` ones, a successful profile never counts, and its rejections start `db_profile_column rejected:`.
- **`test_ask_budgets.py`** pins `compare_fit_refusal` (repeating the same arguments is refused, a call with explicit `funder_ids` is a different call, a fourth call is refused with "3 calls", and a new human question resets the budget) and `model_call_cap` (the turn ends with the `_CAPPED` message at the cap). It builds the real Ask stack with a spy on `create_agent` to assert a `ModelFallbackMiddleware` on the `research_model`, summarisation on the `utility_model`, a `CompareFitBudget` in the stack, and the cap's exit edge reaching `__end__` or an `after_agent` hook so the audit still runs. When `MODEL` and `RESEARCH_MODEL` are the same, no fallback is added.
- **`test_tool_errors.py`** pins `tool_errors()`: a tool that raises answers the model with an error `ToolMessage` naming the tool and exception type (`db_query failed: RuntimeError.`) and never the message text, so secrets do not leak; a `GraphInterrupt` still pauses. It spies on every compiled middleware stack and asserts exactly one `ToolErrorMiddleware` on Ask, on Import and each of its four subagents, and on the Pitch agent and its readers (the test builds it without a search key, so the agent plus two readers, three stacks).

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

- The catalog allowlists 37 tables, and `KNOWN_EXCLUDED` holds 22 more that exist in the database but are deliberately withheld (`backend/app/ask/tools/sql/catalog.py`). The tests do not pin those counts. They pin the membership rules below.
- `test_sql_catalog.py` asserts what the catalog must **not** contain: chat checkpoint tables, `users`, `threads`, `schema_migrations`, `graph_ingest_log` (declared in `KNOWN_EXCLUDED`), the `contacts.email` and `contacts.phone` columns, `chunks.embedding`, and that `SELECT *` expansion cannot bring withheld or heavy columns back. It also checks that citation kinds stay within `org`, `funder`, `activity`, `score`, `news` (the frontend union), and that the import-time `_self_check` really rejects a dangling foreign key.
- `test_sql_validator.py` (DB-free) lists what must be refused: anything not a single SELECT, writes hidden in CTEs, `SELECT INTO`, locking clauses, multiple statements (including a smuggled `RESET ROLE`), unknown or withheld tables even inside CTEs or union arms, cross-schema references, a CTE shadowing a real table, and dangerous functions such as `pg_read_file`, `pg_sleep` and `lo_import`. Comment payloads never survive regeneration.
- `test_sql_integration.py` proves the server-side guards against real Postgres with the validator bypassed: **catalog vs schema** (`test_no_drift` fails when a catalogued table or column is missing from the live database, and every live base table must be either catalogued or in `KNOWN_EXCLUDED`, so a migration adding a table forces an explicit decision), read-only transactions refuse writes, `statement_timeout` fires, neither setting leaks onto the pooled connection that the LangGraph checkpointer also writes through, and the simple versus extended wire protocol difference is why `prepare=True` is mandatory. A DB-free test caps executor concurrency below `db_pool_max_size`.
- `test_prompt.py` ties the prompt to the code: every citation marker kind the tools emit (literal `[kind:{` strings in `app/ask/tools/` plus `CITE_COLUMNS`) appears in `SYSTEM_PROMPT`, every registered tool name appears in the prompt, the retry budget stated in the prompt equals `MAX_SQL_ATTEMPTS` in `app/ask/middleware.py`, and the prompt's table map lists every catalog table with its description.

### Roles and row-level security

`test_rls.py` builds a world (orgs A and B, a hidden org, one person per role, private contacts, documents, chunks, proposals and a thread) and queries it as each caller by setting the Postgres role and `request.jwt.claims` exactly as `CallerPool` does per request (`_as` runs `set_config('role', ...)` and `set_config('request.jwt.claims', ...)`). It pins that private rows reach only the owning org and staff, hidden orgs reach only staff, signed-out callers cannot touch org-private tables at all, threads reach only their owner and staff, stewards read but cannot write their org, an admin sees the rest of the org, an org keeps its last admin, admins and members belong to one org only, saved match runs cannot be forged, edited or deleted, and Import tables are staff-only. Proposal-specific rules sit in the same file: a proposal reaches only its org and staff, only admins, stewards and staff may insert or update one (a blocked `INSERT` raises `InsufficientPrivilege`, while a blocked `UPDATE` silently changes no row), and every role in the org, plus staff, may upload to the org's document vault. This is the database-side half of the edit rule that the unit tests above check in Python.

`test_agent_rls.py` proves that the Ask agent's SQL runs as the caller. It sets `agent_caller` to a `("authenticated", claims)` identity and runs validated SQL through `PsycopgExecutor`: a member of Org A sees its own private document and not Org B's, nor a staff-only `funder_activity` row; a signed-in user with no organisation sees no private row; with no caller set (`agent_caller` of `None`) the agent reads as `anon` and also sees none; the connection returns to the pool as the owner with claims cleared; and every catalogued column is `SELECT`-able by `authenticated`, since the chat runs as the caller and an unreadable column would break `SELECT *`. See [Ask Sangam](../architecture/ask-sangam.md). `test_caller_pool.py` checks that a request runs as `anon` or `authenticated` with the token subject, that the connection returns to the pool as the owner with claims cleared, and that a permission error becomes a 403 with `{"detail": "Not allowed"}`. `test_security.py` covers JWT verification, and `test_import_roles.py` covers what members, stewards and staff may run, save and see in Import. See [Auth, Roles and RLS](../architecture/auth-roles-rls.md).

### Migrations

Schema changes are protected by three separate checks: the catalog-drift tests above, `test_migration_integrity.py` for seeded data after migrating, and file-level checks such as `test_storage.py` reading `db/migrations/0020_storage_buckets.sql` to assert both buckets are created (it skips if the file is not reachable). `make up` runs migrations before the backend starts because the backend's `_verify_sql_catalog` refuses to boot against an unmigrated database.

## Writing and changing tests

- Unit-test a router with `client_for(router)` and monkeypatch its repository function. If code under test touches the pool, the sentinel will fail it.
- Proposal rules belong in pure-function unit tests over a `work` dict (`work.apply`, `trace.check`, `steps.exit_check`); a new agent tool also needs adding to the pinned tool list in `test_proposal_agent.py`, and a new editing rule must be mirrored in `test_rls.py`.
- A new or changed paged list needs its sort to end in a unique `id` and to be added to `LISTS` in `test_paging.py`; assert its filters and paging params with `recording_pool`, and keep SQL-behaviour tests (as in `test_registry_sql.py`) in the integration tier. A frontend list built on `ListPage` hooks is tested with a mocked fetcher and a `first` page, as in `RegistryClient.test.tsx`.
- A DB-backed test must carry `pytest.mark.integration`, skip on `OperationalError`, and roll back.
- Moving code between `ask/`, `ingest/`, `proposals/`, `agentkit/` and `core/`, adding a lazy import or a file past 800 lines is checked by `test_architecture.py`; fix the structure rather than extending its allow-lists.
- A frontend component test goes in a sibling `__tests__/` folder as `.test.tsx` (jsdom, shared Next mocks); a pure module gets `.test.ts` (node). New source files under `lib/`, `features/` or `components/` count toward coverage even when untested.
- Adding a table needs a catalog entry or a `KNOWN_EXCLUDED` entry, or `test_every_live_table_is_either_catalogued_or_knowingly_excluded` fails. Adding an agent tool needs it named in the prompt and in the pinned tool-set tests.
- Adding an eval case means a line in `cases/golden.jsonl` (or `cases/import/`) with an `id`, optional `tags`, and the gates described above. Keep `canary` for cheap, stable cases.
- Running the migration runner outside Docker needs `MIGRATIONS_DIR` (it defaults to the container path `/srv/db/migrations`). Environment selection for databases is covered in [Environments](../operations/environments.md).
