# CSO schema, evidence tiers and aliases — Implementation Plan

> **For agentic workers:** REQUIRED: execute this plan with superpowers:subagent-driven-development — a fresh implementer subagent per task, a fresh reviewer subagent checking each task before the next starts, and a whole-branch review at the end. Do not use executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every fact Import writes about a CSO an **evidence tier**: `source_type` and `evidence` columns on `orgs`, `org_identifiers`, `org_financials`, `org_locations`, `contacts`, `programs` and `metrics`. Writers follow one precedence rule: a weaker source never overwrites a stronger one, and disagreements are reported under `conflicts`. Also:
- `orgs` gains `website`, `description`, `aliases`, `staff_count` and `staff_count_note`.
- `org_identifiers` gets a surrogate key and a registration **status**. This lets a 12A *application* be recorded with no number, and `credential_events` folds into it.
- `org_financials` gains `foreign_unspent`.
- `program_locations` is dropped.
- `resolve_org` gains an alias step and name normalisation.
- The org API, the Diligence tab, the seed, the catalog and the docs move with the schema.

**Architecture:**
- **Migration.** One forward-only file, `db/migrations/0033_cso_consolidation.sql`. It adds the columns and, through a loop, the tier columns with their CHECKs. Then it:
  - re-keys `org_identifiers`;
  - copies the latest verified `credential_events` row per (org, credential) onto the identifier's status, inserting an open row where no identifier exists;
  - backfills `source_type = 'seed'` on rows the seed wrote;
  - refuses to drop a non-empty `program_locations`, then drops both tables.
- **Precedence.** Lives in one place, `app/ingest/writer.py`:
  - `SOURCE_PRECEDENCE` and `_may_overwrite(stored_source, incoming_source)`;
  - `_ranked()`, the per-column rule: fill a blank, keep an equal value, overwrite only when strictly stronger, and otherwise return the disagreement;
  - `_upsert_ranked()`, which every org-side writer uses.

  The funder path keeps #99's `_upsert` untouched.
- **Research findings.**
  - Org-only findings require `source_type` and `evidence_tier`. The table column is `evidence`, but on a finding `evidence` is already the quoted sentence.
  - The shared `program`, `metric` and `contact` findings carry the two fields optionally, and the org promote path holds back a finding without them.
  - Identifiers become their own fact rows, written by `write_org_identifier` in `ORG_WRITE_ORDER`, each with its own source.
- **Matcher.** `resolve_org` gains an alias step that reads `orgs.aliases` and a normalised-name step (`name_key`) computed in Python over the trigram candidates.

**Tech Stack:** PostgreSQL 17 + pgvector (compose), raw psycopg 3 (no ORM), FastAPI, Pydantic v2, pytest (`asyncio_mode = "auto"`), Next.js 16 / TypeScript (no frontend test runner: `tsc`, `eslint` and grep assertions).

**Spec:** features-plans/data-model/2026-10-07-cso-model-consolidation.md (§1, §2 except grants, §3; C1–C3, C5 (program_locations), C6, C7, C11; C14 only as the `prior_research` source type)

## Global Constraints

- **Base branch.** Start from `origin/master` after #99's three PRs have merged. Run this precondition check first, and stop if any line fails:
  ```bash
  docker info >/dev/null 2>&1 && echo "docker up"                                   # the daemon must run
  git -C /Users/vinod/GitHub/sangam fetch origin
  git -C /Users/vinod/GitHub/sangam show origin/master:db/migrations/0031_funder_consolidation.sql >/dev/null && echo "#99 (b) in"
  git -C /Users/vinod/GitHub/sangam show origin/master:db/migrations/0032_staff_sources_bucket.sql >/dev/null && echo "#99 (c) in"
  git -C /Users/vinod/GitHub/sangam ls-tree --name-only origin/master db/migrations/ | grep -c '^db/migrations/0033'   # expect 0
  git -C /Users/vinod/GitHub/sangam show origin/master:backend/tests/conftest.py | grep -c 'class RecordingConn'          # expect 1
  git -C /Users/vinod/GitHub/sangam show origin/master:backend/app/ingest/expectations.py | grep -c 'columns: tuple'       # expect >= 1
  git -C /Users/vinod/GitHub/sangam show origin/master:backend/app/ingest/writer.py | grep -c 'def new_aliases'          # expect 1
  git -C /Users/vinod/GitHub/sangam show origin/master:backend/app/ingest/promote.py | grep -c 'def _validated(.*report' # expect 1 (may wrap; then grep 'report: dict')
  ```
  This plan relies on these post-#99 names:
  - `RecordingConn` and `RecordingPool`, with the fixtures `recording_conn` and `recording_pool`, in `backend/tests/conftest.py`;
  - `ConceptSpec.columns` and `ConceptSpec.row_filter`;
  - `writer.new_aliases(held, found, name)`;
  - `promote._validated(findings, concept, report)`;
  - the `funder_activity` table.
- **Line numbers.** Every line number below is from master `3c59d28`, before #99. #99 rewrites much of `writer.py`, `promote.py`, `matcher.py` and `expectations.py`, so **locate code by symbol**, not by line.
- **Never edit `/Users/vinod/GitHub/sangam`.** It serves a running dev site. Work in a worktree:
  ```bash
  git -C /Users/vinod/GitHub/sangam worktree add /Users/vinod/GitHub/sangam-cso-schema -b feat/cso-schema-evidence origin/master
  cd /Users/vinod/GitHub/sangam-cso-schema
  ```
- **Never migrate the shared dev database `sangam`.** All integration work runs against a scratch clone, `sangam_cso`, on the same Postgres container (`sangam-postgres-1`).
- **Test commands.** The host has no pytest. Save this file **outside the worktree** (never commit it) and start every command with `source /Users/vinod/GitHub/cso-env.sh &&`:
  ```bash
  # /Users/vinod/GitHub/cso-env.sh
  WT=/Users/vinod/GitHub/sangam-cso-schema
  _run() { docker run --rm --network sangam_default -v "$WT":/w -w /w/backend "$@"; }
  bt()  { _run --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  bti() { _run -e TEST_DATABASE_URL=postgresql://sangam:sangam@postgres:5432/sangam_cso --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  mig() { _run -e DATABASE_URL="host=postgres user=sangam password=sangam dbname=sangam_cso" -e MIGRATIONS_DIR=/w/db/migrations --entrypoint python sangam-backend:latest -m app.db.migrate "$@"; }
  seed_cso() { _run -e DATABASE_URL="postgresql://sangam:sangam@postgres:5432/sangam_cso" --entrypoint sh sangam-backend:latest -c "cd /w && python -m seed.seed"; }
  bpy() { _run --entrypoint python sangam-backend:latest -c "$1"; }
  psql_cso() { docker exec -i sangam-postgres-1 psql -U sangam -d sangam_cso "$@"; }
  ```
  - Before Task 1, record the baseline with `bt -m "'not integration'" -q`.
  - In this plan, **"green" means 0 failed**. The passed count grows with each task.
  - `ruff check .` runs on the host from `backend/`, with line-length 110.
  - The frontend is checked **in the worktree**: `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit && npm run lint`.
- **Conventions** (CLAUDE.md, `db/migrations/README.md`):
  - Schema changes go only in `db/migrations/`.
  - A destructive migration carries a note saying why the data makes it safe.
  - Never edit an applied migration. 0006, 0025 and 0027 keep naming the dropped tables, and their `to_regclass` guards make that harmless.
  - Unit tests never touch a database. Use `client_for`, monkeypatch `repositories/`, or `recording_conn`.
  - Integration tests carry `pytestmark = pytest.mark.integration`.
  - Agent tools never raise, and they cite every row.
  - Adding to the catalog is a security decision, and `verify_against_db()` raises on drift.
- **Expected red.** After Task 1 applies 0033 to `sangam_cso`, `tests/test_sql_integration.py::TestCatalogMatchesReality::test_no_drift` fails there until Task 2, because the catalog still lists `credential_events` and `program_locations`. Run it in Task 2, not before.
- **Interim breakage, on purpose.** Between Task 1 and Task 7, `writer._write_org_identifiers` still says `ON CONFLICT (id_type, id_value) DO NOTHING`. Against a migrated database that raises, because the primary key it named is gone. No unit test reaches a database, and Task 7 deletes the function. Do not run a real promotion of an org before Task 7.
- **Imports in `test_cso_evidence.py`.** Tasks 4–9 append mid-file imports marked `# noqa: E402`, so each task's test block reads on its own. If `ruff check` objects (for example I001), hoist them to the top import block. Do not change the names.
- **Commits.** Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Migration number.** `0033`. #99 holds `0031` and `0032`, and PR (e) of this spec will take `0034`. If another branch lands `0033` first, rename this file at merge time and update `MIGRATION` in its test.

## Review Focus

Six failure modes the unit suite can pass straight through. Each has a named test in the task that owns it.

1. **Precedence lets a weaker source overwrite a stronger one.** For example, an aggregator overwriting audited figures, or a `prior_research` value overwriting a staff dataset. The failure can also be indirect: a weak value fills a blank, lowers the row's tier, and so lets a mid-tier source overwrite the audited values.
   - Task 1: `test_an_unverifiable_source_must_be_claimed`.
   - Task 3: `test_an_aggregator_is_never_evidenced`.
   - Task 4: `test_the_order`, `test_a_weaker_source_never_overwrites`, `test_a_weaker_fill_keeps_the_stronger_tier`, `test_a_mid_tier_source_cannot_correct_what_a_weaker_one_filled`.
   - Task 8: `test_an_aggregator_income_never_replaces_the_audited_one`, at integration level.
2. **Alias collisions merge two CSOs.** An alias shared by two orgs, a spelling another org already answers to, or a normalisation that throws away the part of a name that tells two chapters apart.
   - Task 6: `test_an_alias_two_orgs_share_resolves_neither`, `test_brackets_keep_their_content`, `test_a_normalised_name_two_orgs_share_resolves_neither`, `test_a_spelling_another_org_answers_to_is_held`.
3. **Uniqueness on open identifiers (NULL `id_value`), and `ON CONFLICT` inference after the re-key.** A second open row of one type, a number another org holds, two value-less findings in one payload, or any `ON CONFLICT (id_type, id_value)` without the partial-index predicate. Each of these raises, and that aborts the whole promotion or seed.
   - Task 1: `test_one_open_registration_per_org_and_type`, `test_a_number_is_one_row_whoever_holds_it`.
   - Task 7: `test_an_application_becomes_the_registration`, `test_a_number_another_org_holds_is_a_conflict_not_a_crash`, `test_two_open_findings_of_one_type_are_one_row`.
   - Task 9: `test_the_seed_names_the_partial_index`, plus a real `seed_cso` run.
4. **The `credential_events` copy loses a status.** An event value mapped to nothing, an event with no identifier row, or a blocked check replacing a known status.
   - Task 1: `test_each_event_becomes_a_status` (parametrised over all twelve event values), `test_an_event_with_no_identifier_becomes_an_open_row`, `test_a_blocked_check_never_replaces_a_known_status`, `test_only_verified_events_set_a_status`.
5. **The Diligence tab still says "Verified", or the hero says "on file" for a `not_found` row.**
   - Task 11: grep assertions over `ProfileTabs.tsx` and `page.tsx`, `tsc`, and `test_status_labels_cover_every_status`, which checks that the TS label map and the SQL CHECK list agree.
6. **A row a person entered is overwritten.** Rows with `source_type IS NULL` are manual API contacts and rows written before tiers. They must be filled, never overwritten.
   - Task 4: `test_an_unranked_row_is_filled_never_overwritten`.
   - Task 1: `test_seed_rows_are_the_weakest_tier`, which also checks that a non-seed row stays NULL.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `db/migrations/0033_cso_consolidation.sql` | create | All of §1 and §2 that is in scope. Org columns, tier columns and CHECKs, the `org_identifiers` re-key, the `credential_events` copy, the seed backfill, the drops, an access note |
| `backend/tests/test_cso_consolidation_migration.py` | create | Integration. The copy (rolled back, on a pre-0033 DB), the post-state, RLS |
| `backend/tests/test_cso_evidence.py` | create | Unit. Tier vocabulary, precedence, ranked writer, org writer, matcher, identifiers, facts, dossier |
| `backend/tests/test_cso_promote_integration.py` | create | Integration. Two promotions against `sangam_cso`: the audited figure survives an aggregator |
| `backend/app/agent/tools/sql/catalog.py` | modify | Tier columns on 7 tables, the new columns, `doc_type` note, tier defect. Removes `credential_events` and `program_locations` |
| `backend/app/ingest/expectations.py` | modify | `TIER` exclusion, a `columns` allowlist that may name an `INTERNAL` column, `org_identifier` spec, `REQUIRED`, docstring count |
| `backend/app/ingest/records.py` | modify | `SOURCE_TYPES`, `SourceType`, `FindingSourceType`, `EvidenceTier`, `ALWAYS_CLAIMED`, `check_tier`, `Tiered`. Org records gain fields. New `OrgIdentifierRecord`, `IDENTIFIER_STATUSES`, `check_registration` |
| `backend/app/ingest/research_records.py` | modify | `Sourced`, `OptionallySourced`, `ORG_DOC_TYPES`. Org findings gain fields. `PromotionReport.conflicts` |
| `backend/app/ingest/writer.py` | modify | `SOURCE_PRECEDENCE`, `Tier`, `Conflict`, `_may_overwrite`, `_ranked`, `_upsert_ranked`, `write_org`, `org_alias_holders`, `write_org_identifier`, the ranked org fact writers, the org branch of the shared writers. Deletes `_write_org_identifiers` and `_blanks` |
| `backend/app/ingest/promote.py` | modify | `report["conflicts"]`, `org_from`, `_reconcile_org_aliases`, `_tier_of`, `ORG_WRITE_ORDER`, `CONCEPT_RECORDS`, `RENAMED`, `_row_identity`, branches. Deletes `_hold_unstorable` |
| `backend/app/ingest/matcher.py` | modify | `name_key`, `resolve_org` alias and normalised steps |
| `backend/app/ingest/brief.py` | modify | Headlines for identifiers with no number, the tier, `foreign_unspent`, the identity fields |
| `backend/app/ingest/tools/catalog_tools.py` | modify | Org dossier head and sections, `promote_research` printing conflicts, docstring |
| `backend/app/repositories/orgs.py`, `backend/app/schemas/orgs.py` | modify | Darpan LATERAL, the new detail fields, identifier status |
| `backend/tests/test_orgs.py`, `backend/tests/test_ingest.py`, `backend/tests/test_sql_catalog.py` | modify | Detail shape, the rewritten org-writer tests, `EVIDENCE` set, `apart`, catalog guards |
| `seed/seed.py`, `seed/graph_seed.py` | modify | `source_type = 'seed'`, the partial-index `ON CONFLICT`, numberless identifiers in graph text |
| `frontend/lib/api/types.ts`, `frontend/features/registry/identifierStatus.ts` (create), `frontend/features/registry/ProfileTabs.tsx`, `frontend/app/registry/[slug]/page.tsx` | modify | Status labels instead of "Verified", website, aliases, staff |
| `backend/app/ingest/prompts/entity_researcher.md`, `backend/app/ingest/instructions.md`, `backend/app/ingest/skills/catalog-mapping/SKILL.md`, `backend/app/ingest/skills/catalog-write-report/SKILL.md` | modify | Tier fields, identifier status, the precedence rule replacing "fills blanks only", conflicts |
| `docs/DATA_PLATFORM.md`, `docs/INGEST.md`, `docs/SQL_AGENT.md`, `CLAUDE.md`, `README.md` | modify | Table lists and counts |

**Not in this PR:**
- (e) owns `grants`, `grant_locations`, `funder_activity`'s new columns and the `/api/grants` view.
- (f) owns the aggregator registry entries, `manual_aggregator`, the `org_grant_intelligence` registry entry (C14), `record_registry_check`, the `ngo-credential-research` rewrite and `docs/SKILLS.md`.

**Checked and unchanged:** `backend/app/ingest/extractor.py` (funder-only), `backend/app/repositories/contacts.py` (manual contacts stay unranked, by design), and `backend/tests/test_migration_integrity.py`. Its `org_identifiers WHERE id_type = 'fcra'` query still holds.

---

### Task 1: Migration 0033 and its integration tests

**Files:**
- Create: `db/migrations/0033_cso_consolidation.sql`
- Create: `backend/tests/test_cso_consolidation_migration.py`

**Interfaces:**
- **Consumes:**
  - `org_identifiers` (02_schema.sql:69-77; 0001:37-43; 0006:5-8), primary key `org_identifiers_pkey (id_type, id_value)`;
  - `credential_events` (0006);
  - `program_locations` (02_schema.sql:359; 0001:90);
  - `users.auth_user_id` and `users.is_staff` (0023–0026);
  - policy `org_identifiers_read` (0027).
- **Produces:**
  - columns `source_type` and `evidence` on the 7 tables. `source_type` has a CHECK over the 8 values. Constraints `<table>_tier_pair` (both or neither) and `<table>_unverifiable_claimed` (`aggregator` and `prior_research` ⇒ `claimed`);
  - `orgs.website`, `description`, `aliases text[] NOT NULL DEFAULT '{}'`, `staff_count`, `staff_count_note`;
  - `org_financials.foreign_unspent`;
  - `org_identifiers.id` (PK), nullable `id_value`, `status`, `valid_from`, `valid_until`, `checked_at`, `checked_by`, `check_method`, `evidence_document_id`, `application_ref`;
  - the indexes `org_identifiers_value_uq` and `org_identifiers_open_uq`.

- [ ] **Step 1: Create the scratch database at the base migration head.**
  ```bash
  docker exec sangam-postgres-1 sh -c 'createdb -U sangam sangam_cso && pg_dump -U sangam sangam | psql -q -U sangam -d sangam_cso'
  source /Users/vinod/GitHub/cso-env.sh && mig --status && mig
  psql_cso -tc "select max(version) from schema_migrations"
  ```
  Expected: `--status` lists everything after the dev DB's head through `0032_staff_sources_bucket` as pending, and `mig` applies them. The last line prints `0032_staff_sources_bucket`.

- [ ] **Step 2: Write the failing copy tests.** Create `backend/tests/test_cso_consolidation_migration.py`:
  ```python
  """0033: CSO consolidation part one — evidence tiers, org columns, registrations with a status.

  The copy is tested by running the migration inside a rolled-back transaction on a database that has
  not had it yet; the result is tested on one that has. Run against the scratch clone
  (TEST_DATABASE_URL=…/sangam_cso), never the shared dev database.
  """

  from __future__ import annotations

  import json
  import os
  from pathlib import Path
  from uuid import uuid4

  import psycopg
  import pytest
  from psycopg import errors
  from psycopg.rows import dict_row

  DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
  MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0033_cso_consolidation.sql"
  DROPPED = ("credential_events", "program_locations")
  TIERED = ("orgs", "org_identifiers", "org_financials", "org_locations", "contacts", "programs", "metrics")

  pytestmark = pytest.mark.integration


  @pytest.fixture
  def conn():
      try:
          connection = psycopg.connect(DSN, connect_timeout=3, row_factory=dict_row)
      except psycopg.OperationalError:
          pytest.skip("compose Postgres not reachable")
      with connection:
          yield connection


  def _applied(conn) -> bool:
      return conn.execute("SELECT to_regclass('public.credential_events') AS t").fetchone()["t"] is None


  @pytest.fixture
  def before(conn):
      if _applied(conn):
          pytest.skip("0033 is already applied here; the copy is tested on a database before it")
      with conn.transaction(force_rollback=True):
          yield conn


  @pytest.fixture
  def after(conn):
      if not _applied(conn):
          pytest.skip("0033 is not applied here yet")
      with conn.transaction(force_rollback=True):
          yield conn


  def _one(conn, sql, params=()):
      return conn.execute(sql, params).fetchone()


  def _org(conn, name, extractor_version=None):
      return _one(
          conn,
          "INSERT INTO orgs (slug, name, extractor_version) VALUES (%s, %s, %s) RETURNING id",
          (f"cso-{uuid4().hex[:8]}", name, extractor_version),
      )["id"]


  def _migrate(conn):
      conn.execute(MIGRATION.read_text(encoding="utf-8"))


  def _event(conn, org_id, credential, event, *, verified=True, date="2024-04-01", valid_until=None,
             funder_id=None):
      conn.execute(
          "INSERT INTO credential_events (org_id, funder_id, credential, event, event_date, valid_until, "
          "verified, source_url, source_name) VALUES (%s, %s, %s, %s, %s, %s, %s, "
          "'https://ngo.example/cert', 'ngo-site')",
          (org_id, funder_id, credential, event, date, valid_until, verified),
      )


  EVENT_STATUS = [
      ("registered", "registered"), ("renewed", "registered"), ("checked_active", "registered"),
      ("restored", "registered"), ("expired", "expired"), ("suspended", "suspended"),
      ("cancelled", "cancelled"), ("surrendered", "surrendered"), ("not_available", "not_available"),
      ("not_found", "not_found"), ("check_blocked", "check_blocked"),
      ("superseded", "registered"),        # status untouched; is_current goes false
  ]


  @pytest.mark.parametrize(("event", "status"), EVENT_STATUS)
  def test_each_event_becomes_a_status(before, event, status):
      conn = before
      org = _org(conn, "Gramya Vikash Trust")
      conn.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, 'fcra', %s)",
                   (org, f"FC{uuid4().hex[:8]}"))
      _event(conn, org, "fcra", event, valid_until="2027-03-31")
      _migrate(conn)
      row = _one(conn, "SELECT status, valid_until, is_current, checked_at FROM org_identifiers "
                       "WHERE org_id = %s AND id_type = 'fcra'", (org,))
      assert row["status"] == status
      if event == "superseded":
          assert row["is_current"] is False and row["valid_until"] is None
      else:
          assert str(row["valid_until"]) == "2027-03-31" and row["checked_at"] is not None


  def test_an_event_with_no_identifier_becomes_an_open_row(before):
      conn = before
      org = _org(conn, "Gramya Vikash Trust")
      _event(conn, org, "csr1", "not_available")
      _migrate(conn)
      rows = conn.execute("SELECT id_value, status, source_url FROM org_identifiers "
                          "WHERE org_id = %s AND id_type = 'csr1'", (org,)).fetchall()
      assert rows == [{"id_value": None, "status": "not_available", "source_url": "https://ngo.example/cert"}]


  def test_a_blocked_check_never_replaces_a_known_status(before):
      conn = before
      org = _org(conn, "Gramya Vikash Trust")
      conn.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, 'fcra', %s)",
                   (org, f"FC{uuid4().hex[:8]}"))
      _event(conn, org, "fcra", "cancelled", date="2023-01-01")
      _event(conn, org, "fcra", "check_blocked", date="2025-01-01")    # newer, and says nothing
      _migrate(conn)
      assert _one(conn, "SELECT status FROM org_identifiers WHERE org_id = %s AND id_type = 'fcra'",
                  (org,))["status"] == "cancelled"


  def test_only_verified_events_set_a_status(before):
      conn = before
      org = _org(conn, "Gramya Vikash Trust")
      conn.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, '12a', %s)",
                   (org, f"AA{uuid4().hex[:8]}"))
      _event(conn, org, "12a", "registered", date="2020-01-01")
      _event(conn, org, "12a", "cancelled", date="2024-01-01", verified=False)
      _migrate(conn)
      assert _one(conn, "SELECT status FROM org_identifiers WHERE org_id = %s AND id_type = '12a'",
                  (org,))["status"] == "registered"


  def test_funder_events_are_discarded(before):
      conn = before
      funder = _one(conn, "INSERT INTO funders (slug, name) VALUES (%s, 'Acme Foundation') RETURNING id",
                    (f"cso-{uuid4().hex[:8]}",))["id"]
      _event(conn, None, "pan", "registered", funder_id=funder)
      _migrate(conn)
      assert _one(conn, "SELECT to_regclass('public.credential_events') AS t")["t"] is None


  def test_seed_rows_are_the_weakest_tier(before):
      conn = before
      seeded = _org(conn, "Seeded Society", extractor_version="seed-v2")
      imported = _org(conn, "Imported Society", extractor_version="research/v2")
      _migrate(conn)
      tiers = {r["id"]: (r["source_type"], r["evidence"]) for r in conn.execute(
          "SELECT id, source_type, evidence FROM orgs WHERE id = ANY(%s)", ([seeded, imported],)).fetchall()}
      assert tiers == {seeded: ("seed", "claimed"), imported: (None, None)}


  def test_a_program_location_stops_the_migration(before):
      conn = before
      org = _org(conn, "Gramya Vikash Trust")
      program = _one(conn, "INSERT INTO programs (org_id, name) VALUES (%s, 'Livelihoods') RETURNING id",
                     (org,))["id"]
      location = _one(conn, "SELECT id FROM locations LIMIT 1")["id"]
      conn.execute("INSERT INTO program_locations (program_id, location_id) VALUES (%s, %s)", (program, location))
      with pytest.raises(errors.RaiseException, match="program_locations"):
          with conn.transaction():
              _migrate(conn)
  ```
- [ ] **Step 3: Run them. They fail.** `source /Users/vinod/GitHub/cso-env.sh && bti tests/test_cso_consolidation_migration.py -q` → 18 errors: `FileNotFoundError … 0033_cso_consolidation.sql`.

- [ ] **Step 4: Write the migration.** Create `db/migrations/0033_cso_consolidation.sql`:
  ```sql
  -- CSO consolidation, part one. Spec: features-plans/data-model/2026-10-07-cso-model-consolidation.md
  -- §1 and §2 (C1-C3, C5, C6, C7; C14's prior_research source type). grants -> funder_activity and
  -- grant_locations are PR (e), the next migration.
  --
  --   7 CSO tables       + source_type, evidence: the evidence tier every Import write carries (C7)
  --   orgs               + website, description, aliases, staff_count, staff_count_note (C1)
  --   org_financials     + foreign_unspent (C6)
  --   org_identifiers    a surrogate key, a status, and a number that may not exist yet (C2, C3)
  --   credential_events  folded into org_identifiers.status, then dropped (C2)
  --   program_locations  dropped: 0 rows, no writer (C5)
  --
  -- DESTRUCTIVE: drops credential_events and program_locations. Safe because the latest verified event per
  -- (org, credential) is copied onto org_identifiers first - into an open row where no identifier exists -
  -- and funder events are history funders no longer keep (0031, D1). program_locations has no home, so it
  -- stops the migration if it holds anything.
  --
  -- Numbered after #99's 0031 and 0032. Renumber at merge if another branch takes 0033.
  -- Before running against Supabase: SELECT count(*) on both dropped tables, and take a backup.

  -- 0. Refuse to drop what this file cannot carry across.
  DO $$
  DECLARE n bigint;
  BEGIN
    SELECT count(*) INTO n FROM program_locations;
    IF n > 0 THEN
      RAISE EXCEPTION 'program_locations holds % rows and nothing replaces it; move them by hand before 0033', n;
    END IF;
  END $$;

  -- 1. Columns the test CSO's sources state and the tables could not hold (C1, C6).
  ALTER TABLE orgs
    ADD COLUMN website text,
    ADD COLUMN description text,
    ADD COLUMN aliases text[] NOT NULL DEFAULT '{}',
    ADD COLUMN staff_count integer CHECK (staff_count >= 0),
    ADD COLUMN staff_count_note text;               -- e.g. "20+ full-time professionals (team page)"
  ALTER TABLE org_financials
    ADD COLUMN foreign_unspent numeric;             -- FC unutilised at year end (FCRA return); INR

  -- 2. The evidence tier (C7). NULL means not ranked: a person entered the row, or it predates tiers.
  -- Import fills such a row's blanks and never overwrites it. Strongest first: registry = manual_check >
  -- org_document > funder > staff_dataset > prior_research > aggregator > seed (app/ingest/writer.py).
  DO $$
  DECLARE t text;
  BEGIN
    FOREACH t IN ARRAY ARRAY['orgs', 'org_identifiers', 'org_financials', 'org_locations', 'contacts',
                             'programs', 'metrics'] LOOP
      EXECUTE format(
        'ALTER TABLE public.%I '
        'ADD COLUMN source_type text CHECK (source_type IN (''registry'', ''org_document'', ''funder'', '
        '''staff_dataset'', ''manual_check'', ''prior_research'', ''aggregator'', ''seed'')), '
        'ADD COLUMN evidence text CHECK (evidence IN (''evidenced'', ''claimed'')), '
        'ADD CONSTRAINT %I CHECK ((source_type IS NULL) = (evidence IS NULL)), '
        'ADD CONSTRAINT %I CHECK (source_type IS NULL OR source_type NOT IN (''aggregator'', ''prior_research'') '
        'OR evidence = ''claimed'')',
        t, t || '_tier_pair', t || '_unverifiable_claimed');
    END LOOP;
  END $$;

  -- 3. org_identifiers: one row per registration, with or without a number yet (C3).
  ALTER TABLE org_identifiers DROP CONSTRAINT org_identifiers_pkey;
  ALTER TABLE org_identifiers
    ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ALTER COLUMN id_value DROP NOT NULL,
    ADD COLUMN status text NOT NULL DEFAULT 'registered' CHECK (status IN
      ('applied', 'provisional', 'registered', 'expired', 'suspended', 'cancelled',
       'surrendered', 'not_available', 'not_found', 'check_blocked')),
    ADD COLUMN valid_from date,
    ADD COLUMN valid_until date,
    ADD COLUMN checked_at timestamptz,
    ADD COLUMN checked_by uuid REFERENCES users(id),
    ADD COLUMN check_method text CHECK (check_method IN
      ('document', 'registry', 'manual_check', 'aggregator')),
    ADD COLUMN evidence_document_id bigint REFERENCES documents(id),
    ADD COLUMN application_ref text;                -- e.g. a Form 10AB acknowledgement number
  CREATE UNIQUE INDEX org_identifiers_value_uq ON org_identifiers (id_type, id_value)
    WHERE id_value IS NOT NULL;
  CREATE UNIQUE INDEX org_identifiers_open_uq ON org_identifiers (org_id, id_type)
    WHERE id_value IS NULL;

  -- 4. credential_events -> the identifier row's status (C2). Only verified events ever set a status (0006),
  -- so only they are copied: the latest per (org, credential). A check that could not be made never replaces
  -- a known status, so check_blocked is chosen only when it is the only verified event of its type.
  CREATE TEMP TABLE _latest_event ON COMMIT DROP AS
  SELECT DISTINCT ON (org_id, credential)
    org_id, credential, valid_until, notes, source_url, source_name, fetched_at, as_of, document_id,
    archive_url, recorded_by, recorded_at,
    CASE event
      WHEN 'renewed' THEN 'registered' WHEN 'checked_active' THEN 'registered'
      WHEN 'restored' THEN 'registered'
      WHEN 'superseded' THEN NULL                  -- not a status: the number on file was replaced
      ELSE event
    END AS status
  FROM credential_events
  WHERE org_id IS NOT NULL AND verified
  ORDER BY org_id, credential, (event = 'check_blocked'), event_date DESC, recorded_at DESC, id DESC;

  UPDATE org_identifiers oi SET is_current = false
  FROM _latest_event e
  WHERE e.status IS NULL AND oi.org_id = e.org_id AND oi.id_type = e.credential;

  UPDATE org_identifiers oi SET
    status = e.status,
    valid_until = coalesce(e.valid_until, oi.valid_until),
    checked_at = e.recorded_at,
    checked_by = e.recorded_by,
    evidence_document_id = coalesce(oi.evidence_document_id, e.document_id),
    notes = coalesce(oi.notes, e.notes)
  FROM _latest_event e
  WHERE e.status IS NOT NULL AND oi.org_id = e.org_id AND oi.id_type = e.credential;

  -- A status with no identifier row - a CSR-1 that is 'not_available', say - becomes an open row.
  INSERT INTO org_identifiers (org_id, id_type, id_value, status, valid_until, checked_at, checked_by,
    evidence_document_id, notes, source_url, source_name, fetched_at, as_of, document_id, archive_url)
  SELECT e.org_id, e.credential, NULL, e.status, e.valid_until, e.recorded_at, e.recorded_by,
    e.document_id, e.notes, e.source_url, e.source_name, e.fetched_at, e.as_of, e.document_id, e.archive_url
  FROM _latest_event e
  WHERE e.status IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM org_identifiers oi WHERE oi.org_id = e.org_id AND oi.id_type = e.credential);

  DO $$
  DECLARE n bigint;
  BEGIN
    SELECT (SELECT count(*) FROM credential_events) - (SELECT count(*) FROM _latest_event) INTO n;
    IF n > 0 THEN
      RAISE NOTICE '% credential_events rows are history (unverified, superseded by a later event, or a '
                   'funder''s) and are not carried over', n;
    END IF;
  END $$;

  -- 5. What the seed wrote is the weakest tier. Recognised by what seed.py stamps on it; everything else
  -- stays NULL (unranked). seed.py writes source_type itself from now on (it upserts identifiers and
  -- contacts with DO NOTHING, so a database seeded before this needs the backfill).
  UPDATE orgs SET source_type = 'seed', evidence = 'claimed' WHERE extractor_version LIKE 'seed-%';
  UPDATE org_identifiers SET source_type = 'seed', evidence = 'claimed' WHERE verified;
  UPDATE org_locations SET source_type = 'seed', evidence = 'claimed'
    WHERE source_url IS NULL AND source_name IS NULL;
  UPDATE contacts SET source_type = 'seed', evidence = 'claimed'
    WHERE org_id IS NOT NULL AND extractor_version IS NULL AND source_name IS DISTINCT FROM 'manual';

  -- 6. Drop.
  DROP TABLE credential_events;
  DROP TABLE program_locations;

  -- 7. Access (#92). No table is new. The SELECT that 0025 granted on each changed table covers its new
  -- columns, and org_identifiers keeps org_identifiers_read (is_public, the org's own people, staff). The
  -- identity sequence is never granted: only the owner writes org_identifiers.
  ```
- [ ] **Step 5: Run the copy tests. They pass.** `bti tests/test_cso_consolidation_migration.py -q` → `18 passed`. That is 12 parametrised, plus 6.
- [ ] **Step 6: Apply 0033 to the scratch database and add the post-state tests.** `mig` reports `0033_cso_consolidation` applied. Append to the test file:
  ```python
  def test_the_old_tables_are_gone(after):
      for table in DROPPED:
          assert _one(after, "SELECT to_regclass(%s) AS t", (f"public.{table}",))["t"] is None, table


  @pytest.mark.parametrize("table", TIERED)
  def test_an_unverifiable_source_must_be_claimed(after, table):
      cols = {r["column_name"] for r in after.execute(
          "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)).fetchall()}
      assert {"source_type", "evidence"} <= cols
      checks = " ".join(r["def"] for r in after.execute(
          "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conrelid = %s::regclass",
          (table,)).fetchall())
      assert "prior_research" in checks and "aggregator" in checks and "claimed" in checks


  def test_an_aggregator_row_is_refused_as_evidenced(after):
      org = _org(after, "Gramya Vikash Trust")
      for tier in (("aggregator", "evidenced"), ("prior_research", "evidenced"), ("registry", None)):
          with pytest.raises(errors.CheckViolation):
              with after.transaction():
                  after.execute("UPDATE orgs SET source_type = %s, evidence = %s WHERE id = %s", (*tier, org))


  def test_one_open_registration_per_org_and_type(after):
      org = _org(after, "Gramya Vikash Trust")
      after.execute("INSERT INTO org_identifiers (org_id, id_type, status, application_ref) "
                    "VALUES (%s, '12a', 'applied', 'ACK-1')", (org,))
      after.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, '12a', %s)",
                    (org, f"AA{uuid4().hex[:8]}"))                # a numbered row beside it is fine
      with pytest.raises(errors.UniqueViolation):
          with after.transaction():
              after.execute("INSERT INTO org_identifiers (org_id, id_type, status) VALUES (%s, '12a', 'applied')",
                            (org,))


  def test_a_number_is_one_row_whoever_holds_it(after):
      a, b = _org(after, "Gramya Vikash Trust"), _org(after, "Gramya Vikas Society")
      after.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, 'pan', 'AAATG1234K')", (a,))
      with pytest.raises(errors.UniqueViolation):
          with after.transaction():
              after.execute("INSERT INTO org_identifiers (org_id, id_type, id_value) VALUES (%s, 'pan', 'AAATG1234K')",
                            (b,))


  def test_a_status_outside_the_list_is_refused(after):
      org = _org(after, "Gramya Vikash Trust")
      with pytest.raises(errors.CheckViolation):
          with after.transaction():
              after.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status) "
                            "VALUES (%s, 'pan', 'AAATG9999K', 'valid')", (org,))


  def test_a_private_number_still_reaches_only_its_org_and_staff(after):
      conn = after
      org = _org(conn, "Gramya Vikash Trust")
      conn.execute("INSERT INTO org_identifiers (org_id, id_type, id_value, status, is_public) "
                   "VALUES (%s, 'pan', 'AAATG5555K', 'registered', true), (%s, 'fcra', 'FC5555', 'check_blocked', false)",
                   (org, org))
      staff = uuid4()
      conn.execute("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true)",
                   (f"cso-{staff}@rls.test", staff))

      def seen(role, claims):
          with conn.transaction(force_rollback=True):
              conn.execute("SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                           (role, claims))
              return {(r["id_type"], r["status"]) for r in conn.execute(
                  "SELECT id_type, status FROM org_identifiers WHERE org_id = %s", (org,)).fetchall()}

      assert seen("anon", "") == {("pan", "registered")}
      assert seen("authenticated", json.dumps({"sub": str(staff)})) == {("pan", "registered"),
                                                                         ("fcra", "check_blocked")}
  ```
- [ ] **Step 7: Run.** `bti tests/test_cso_consolidation_migration.py -q` → `18 skipped` (the `before` tests, now that 0033 is applied) and `13 passed` (1 + 7 parametrised + 5). `bt -m "'not integration'" -q` → 0 failed, since no code changed.
- [ ] **Step 8: Commit.**
  ```bash
  git add db/migrations/0033_cso_consolidation.sql backend/tests/test_cso_consolidation_migration.py
  git commit -m "feat(db): 0033 — evidence tiers, org columns, registrations with a status" -m "Seven CSO tables gain source_type and evidence; orgs gains website, description, aliases and staff; org_identifiers gets a surrogate key and a status, absorbing credential_events; org_financials gains foreign_unspent; program_locations is dropped." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

### Task 2: Catalog — the tier columns, the two drops, and the tier stays out of research targets

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py`. Change the `credential_events` (line 88) and `program_locations` (line 683) entries, the `documents` `doc_type` column (line 125), and the column lists of the 7 tables.
- Modify: `backend/app/ingest/expectations.py`. Add `TIER` after `PROVENANCE`, and change `expected_fields`.
- Modify: `backend/app/ingest/skills/catalog-mapping/SKILL.md` (line 45).
- Modify: `backend/tests/test_sql_catalog.py`, `backend/tests/test_ingest.py`

**Interfaces:**
- **Produces:**
  - `catalog._SOURCE_TYPES: tuple[str, ...]` (8 values, the CHECK enum's order);
  - `catalog._TIER: tuple[Column, Column]`;
  - `catalog._TIER_DEFECT: str`;
  - `expectations.TIER = frozenset({"source_type", "evidence"})`, which `expected_fields()` never emits;
  - `CATALOG` loses `credential_events` and `program_locations`.

- [ ] **Step 1: Failing tests.** Append to `backend/tests/test_sql_catalog.py`:
  ```python
  import re
  from pathlib import Path

  CSO_TABLES = ("orgs", "org_identifiers", "org_financials", "org_locations", "contacts", "programs", "metrics")
  SOURCE_TYPES = ("registry", "org_document", "funder", "staff_dataset", "manual_check", "prior_research",
                  "aggregator", "seed")
  DROPPED_IN_0033 = ("credential_events", "program_locations")


  class TestEvidenceTiers:
      @pytest.mark.parametrize("table", CSO_TABLES)
      def test_every_cso_table_carries_the_tier(self, table):
          assert cat.COLUMNS[table]["source_type"].values == SOURCE_TYPES
          assert cat.COLUMNS[table]["evidence"].values == ("evidenced", "claimed")

      @pytest.mark.parametrize("table", CSO_TABLES)
      def test_a_claimed_value_is_never_presented_as_fact(self, table):
          text = " ".join(cat.DEFECTS[table]).lower()
          assert "aggregator" in text and "claimed" in text and "never" in text

      def test_the_cso_document_types_are_named(self):
          note = cat.COLUMNS["documents"]["doc_type"].note
          for doc_type in ("trust_deed", "registration_certificate", "exemption_order", "exemption_application",
                           "csr1_approval", "fcra_certificate", "fcra_return", "audit_report", "annual_report",
                           "policy", "manual_check_evidence"):
              assert doc_type in note
          assert cat.COLUMNS["documents"]["doc_type"].values == ()      # free text: a note, not a CHECK


  @pytest.mark.parametrize("table", DROPPED_IN_0033)
  def test_a_table_0033_dropped_is_neither_catalogued_nor_excused(table):
      assert table not in cat.TABLE_NAMES and table not in cat.KNOWN_EXCLUDED


  def test_no_module_names_a_table_0033_dropped():
      root = Path(cat.__file__).resolve().parents[3]          # backend/app
      gone = re.compile(r"\b(credential_events|program_locations)\b")
      hits = [
          f"{p.relative_to(root)}:{i}"
          for p in root.rglob("*") if p.suffix in {".py", ".md"}
          for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
          if gone.search(line)
      ]
      assert not hits, hits
  ```
  Then append to `TestExpectationsComeFromTheSchema` in `backend/tests/test_ingest.py`:
  ```python
      def test_the_tier_is_never_a_research_field(self):
          """source_type and evidence are filled from the finding's own source_type and evidence_tier.
          As columns they would ask for `evidence`, which on a finding is the quoted sentence."""
          from app.ingest.expectations import TIER

          for concept in CONCEPT_TABLES:
              assert not {f.name for f in expected_fields(concept)} & TIER, concept
  ```
  Run `bt tests/test_sql_catalog.py tests/test_ingest.py -q` → failures (`KeyError: 'source_type'`, `ImportError: TIER`). The guard test lists `catalog.py` and `catalog-mapping/SKILL.md`.
- [ ] **Step 2: Add the tier to the catalog.** Above `_TABLES`, add:
  ```python
  # The evidence tier (C7), on every CSO table Import writes. Values are the CHECK enums of 0033, verbatim.
  _SOURCE_TYPES = ('registry', 'org_document', 'funder', 'staff_dataset', 'manual_check', 'prior_research',
                   'aggregator', 'seed')
  _TIER = (
      Column("source_type", "text", note="the kind of source the row's values came from. Strongest first: registry = manual_check > org_document > funder > staff_dataset > prior_research > aggregator > seed. NULL = not ranked: entered by a person, or written before tiers", values=_SOURCE_TYPES),
      Column("evidence", "text", note="'evidenced' only when a document itself states the fact (a certificate, an audited statement, a dated return); 'claimed' otherwise. aggregator and prior_research rows are always 'claimed'", values=('evidenced', 'claimed')),
  )
  _TIER_DEFECT = (
      "source_type and evidence describe the ROW: the strongest source that has written to it. A blank filled "
      "later by a weaker source is not labelled separately, so for one value's own source read the research "
      "record. A row whose evidence is 'claimed' - every aggregator and prior_research row among them - is "
      "never presented as fact: say 'claimed by <source_type>' beside it, and never let it settle an "
      "eligibility question."
  )
  ```
  Then:
  - Append `*_TIER` as the last entries of `columns=` for `contacts`, `metrics`, `org_financials`, `org_locations`, `orgs` and `programs`.
  - For `org_identifiers`, add `*_TIER` after `Column("notes", "text")`. Task 7 adds the identifier columns after it, in DDL order.
  - Add `_TIER_DEFECT` to each table's `defects=` tuple. For `contacts`, `org_identifiers`, `org_locations` and `programs`, which have no `defects=`, add `defects=(_TIER_DEFECT,),`.
- [ ] **Step 3: Remove the two tables and annotate `doc_type`.**
  - Delete the `credential_events` and `program_locations` `Table(...)` entries.
  - Replace the `documents` column `Column("doc_type", "text")` with:
  ```python
              Column("doc_type", "text", note="free text. A CSO's own: trust_deed, registration_certificate, exemption_order (12AB/80G: Forms 10AC/10AD), exemption_application (a Form 10AB acknowledgement), csr1_approval, fcra_certificate, fcra_return, audit_report, annual_report, policy, manual_check_evidence (a screenshot or archive of a registry check). A funder's: annual_report, csr_annexure, brsr, funder_eligibility, proposal_template, source_dataset"),
  ```
  If `_self_check()` raises on import, an FK in another table names a dropped table. None does on master, so fix only what it names.
- [ ] **Step 4: Keep the tier out of research targets.** In `expectations.py`, after `PROVENANCE`:
  ```python
  # The evidence tier (C7). Columns on the seven CSO tables, filled from a finding's own source_type and
  # evidence_tier: never derived as targets, because `evidence` on a finding is the quoted sentence.
  TIER = frozenset({"source_type", "evidence"})
  ```
  and in `expected_fields`, extend the skip line to `if name == "id" or name in PROVENANCE or name in TIER or name in INTERNAL or column.heavy:`. If #99 rewrote that line, keep its shape and add `or name in TIER`.
- [ ] **Step 5: Reword the skill line.** In `backend/app/ingest/skills/catalog-mapping/SKILL.md`, replace the `credential_events` row (line 45) with:
  ```markdown
  | whether any of the above is applied for, registered, expired, cancelled, suspended, or could not be checked | `org_identifiers.status` on the identifier's own row — `applied` (a Form 10AB acknowledgement, `application_ref`), `registered`, `expired`, `cancelled`, `suspended`, `not_found`, `check_blocked` (never means valid) |
  ```
- [ ] **Step 6: Run.**
  - `bt tests/test_sql_catalog.py tests/test_ingest.py -q` → all pass. The org concepts' model-vs-table tests are unchanged, because the tier is excluded.
  - `bt -m "'not integration'" -q` → 0 failed.
  - `bti tests/test_sql_integration.py::TestCatalogMatchesReality -q` → `2 passed`, against `sangam_cso`.
  - `cd backend && ruff check .` → clean.
- [ ] **Step 7: Commit.** `git add -A backend && git commit -m "feat(sql): catalogue the evidence tier; drop credential_events and program_locations" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 3: The tier vocabulary reaches findings and records

**Files:**
- Modify: `backend/app/ingest/records.py`. Add the constants after `FISCAL_YEAR`. Change `ProgramRecord`, `MetricRecord`, `ContactRecord`, `OrgRecord`, `OrgFinancialsRecord` and `OrgLocationRecord`.
- Modify: `backend/app/ingest/research_records.py`. Change `ProgramFinding`, `MetricFinding`, `ContactFinding`, the four `Org*Finding`s, `DocumentFinding.doc_type`, and add `ORG_DOC_TYPES`.
- Modify: `backend/app/ingest/promote.py`. Change `org_from`, the `org_financials` / `org_location` / `metric` / `contact` branches of `_write_facts`, and `_write_programs`.
- Modify: `backend/tests/test_ingest.py`. Change the `EVIDENCE` set of `TestFindingsAreShapedLikeTheRowsTheyBecome`, the `TestTheOrgWriter.rec` helper, and every org finding dict.
- Create: `backend/tests/test_cso_evidence.py`

**Interfaces:**
- **Produces:**
  - `records.SOURCE_TYPES: tuple[str, ...]`;
  - `records.SourceType` (Literal of 8), `records.FindingSourceType` (Literal of 6: no `manual_check`, no `seed`), `records.EvidenceTier`;
  - `records.ALWAYS_CLAIMED = frozenset({"aggregator", "prior_research"})`;
  - `records.check_tier(source_type: str | None, evidence_tier: str | None) -> None`, which raises `ValueError`;
  - `records.Tiered` (mixin with optional `source_type` and `evidence_tier`);
  - `research_records.Sourced` (required fields) and `research_records.OptionallySourced`;
  - `research_records.ORG_DOC_TYPES: tuple[str, ...]`.
- **Changes:** the four org records require `source_type: SourceType` and `evidence_tier: EvidenceTier`, and `ProgramRecord`, `MetricRecord` and `ContactRecord` carry them optionally.

- [ ] **Step 1: Failing tests.** Create `backend/tests/test_cso_evidence.py`:
  ```python
  """CSO evidence tiers (C7), precedence, aliases (C11) and registrations with a status (C2, C3)."""

  from __future__ import annotations

  from datetime import UTC, date, datetime

  import pytest
  from pydantic import ValidationError

  from app.ingest.expectations import concepts_for
  from app.ingest.research_records import FINDING_MODELS

  NOW = datetime(2026, 10, 7, tzinfo=UTC)
  BASE = {"evidence": "The audited statement for 2023-24 states this plainly.",
          "source_url": "https://ngo.example/audit-2023-24.pdf", "confidence": "high"}
  TIER = {"source_type": "org_document", "evidence_tier": "evidenced"}
  MINIMAL = {
      "org_identity": {"name": "Gramya Vikash Trust"},
      "org_identifier": {"id_type": "pan", "id_value": "AAATG1234K"},
      "org_financials": {"fiscal_year": "FY2023-24"},
      "org_location": {"state": "Assam"},
  }
  ORG_ONLY = tuple(MINIMAL)
  SHARED = ("program", "metric", "contact")


  def finding(concept, **kw):
      body = {**BASE, "concept": concept, **MINIMAL.get(concept, {}), **kw}
      return FINDING_MODELS[concept].model_validate(body)


  def prov(**kw):
      return {"source_url": "https://ngo.example/ar", "source_name": "ngo-site", "fetched_at": NOW, **kw}


  class TestEveryCsoFindingNamesItsSource:
      @pytest.mark.parametrize("concept", ORG_ONLY)
      def test_an_org_finding_without_a_tier_is_refused(self, concept):
          with pytest.raises(ValidationError, match="source_type"):
              finding(concept)

      @pytest.mark.parametrize("concept", ORG_ONLY)
      def test_an_org_finding_with_a_tier_is_kept(self, concept):
          assert finding(concept, **TIER).source_type == "org_document"

      def test_a_shared_finding_may_omit_it_for_a_funder(self):
          assert finding("metric", name="Households reached", value=1200).source_type is None

      def test_a_funder_finding_has_no_tier(self):
          for concept in set(concepts_for("funder")) - set(SHARED) - {"document"}:
              assert "source_type" not in FINDING_MODELS[concept].model_fields, concept

      @pytest.mark.parametrize("source", ["aggregator", "prior_research"])
      def test_an_aggregator_is_never_evidenced(self, source):
          with pytest.raises(ValidationError, match="claimed"):
              finding("org_financials", source_type=source, evidence_tier="evidenced")
          assert finding("org_financials", source_type=source, evidence_tier="claimed").evidence_tier == "claimed"

      @pytest.mark.parametrize("source", ["manual_check", "seed"])
      def test_research_cannot_claim_a_staff_or_seed_source(self, source):
          with pytest.raises(ValidationError):
              finding("org_identity", source_type=source, evidence_tier="claimed")

      def test_a_record_mirrors_the_rule(self):
          from app.ingest.records import OrgFinancialsRecord

          with pytest.raises(ValidationError, match="claimed"):
              OrgFinancialsRecord(entity_name="Gramya Vikash Trust", fiscal_year="FY2023-24",
                                  source_type="aggregator", evidence_tier="evidenced", **prov())

      def test_half_a_tier_is_refused(self):
          from app.ingest.records import MetricRecord

          with pytest.raises(ValidationError, match="both or neither"):
              MetricRecord(entity_name="Gramya Vikash Trust", name="Households", value=1.0,
                           source_type="org_document", **prov())

      def test_the_vocabulary_is_the_catalogs(self):
          from app.agent.tools.sql.catalog import COLUMNS
          from app.ingest.records import SOURCE_TYPES

          assert set(SOURCE_TYPES) == set(COLUMNS["orgs"]["source_type"].values)

      def test_the_cso_document_types_are_the_catalogs(self):
          from app.agent.tools.sql.catalog import COLUMNS
          from app.ingest.research_records import ORG_DOC_TYPES

          for doc_type in ORG_DOC_TYPES:
              assert doc_type in COLUMNS["documents"]["doc_type"].note
  ```
  Run `bt tests/test_cso_evidence.py -q` → failures (import errors, then missing validation).
- [ ] **Step 2: The vocabulary.** In `records.py`, after `FISCAL_YEAR`:
  ```python
  # The evidence tier (C7). Research may name the six kinds a researcher can read. 'manual_check' is a staff
  # member's registry check (recorded by its own tool) and 'seed' is seed.py's, so a model can claim neither.
  SOURCE_TYPES: tuple[str, ...] = ("registry", "org_document", "funder", "staff_dataset", "manual_check",
                                   "prior_research", "aggregator", "seed")
  SourceType = Literal["registry", "org_document", "funder", "staff_dataset", "manual_check",
                       "prior_research", "aggregator", "seed"]
  FindingSourceType = Literal["registry", "org_document", "funder", "staff_dataset", "prior_research",
                              "aggregator"]
  EvidenceTier = Literal["evidenced", "claimed"]
  # Sources whose values can never be evidence on their own: an aggregator's listing, and the team's earlier
  # dossiers (C14) until their cited link is re-read. The tables CHECK the same rule.
  ALWAYS_CLAIMED = frozenset({"aggregator", "prior_research"})


  def check_tier(source_type: str | None, evidence_tier: str | None) -> None:
      """Both or neither, and an unverifiable source is only ever claimed. 0033 CHECKs both rules, and a
      CheckViolation aborts a whole promotion, so the records refuse first."""
      if (source_type is None) != (evidence_tier is None):
          raise ValueError("source_type and evidence_tier come together: name both or neither")
      if source_type in ALWAYS_CLAIMED and evidence_tier != "claimed":
          raise ValueError(f"a {source_type} value is always 'claimed', never 'evidenced'")


  class Tiered(BaseModel):
      """The evidence tier on a record. Optional here; the org records make it required, and the org
      promote path holds back a shared-table record that has none."""

      source_type: SourceType | None = None
      evidence_tier: EvidenceTier | None = None

      @model_validator(mode="after")
      def _a_whole_tier(self) -> Tiered:
          check_tier(self.source_type, self.evidence_tier)
          return self
  ```
  Then:
  - Change `class ProgramRecord(Provenance)`, `MetricRecord(Provenance)` and `ContactRecord(Provenance)` to `(Provenance, Tiered)`.
  - Change `OrgRecord`, `OrgFinancialsRecord` and `OrgLocationRecord` to `(Provenance, Tiered)`, and add these two lines as the last fields of each:
  ```python
      source_type: SourceType
      evidence_tier: EvidenceTier
  ```
- [ ] **Step 3: The findings.** In `research_records.py`, import `ALWAYS_CLAIMED`, `EvidenceTier`, `FindingSourceType` and `check_tier` from `app.ingest.records`. #99 already imports from it, so extend that import. Before the org section, add:
  ```python
  _SOURCE_TYPE_HELP = (
      "the KIND of source: registry (a government registry page read directly) · org_document (the CSO's own "
      "document or site) · funder (a funder's page or CSR filing naming the CSO) · staff_dataset (a "
      "staff-uploaded sheet) · prior_research (the team's earlier dossier, not yet re-read at its source) · "
      "aggregator (Give.do, GuideStar and the like)"
  )
  _EVIDENCE_TIER_HELP = (
      "'evidenced' only when the document itself states the fact: a certificate, an audited statement, a dated "
      "return. A sentence on a web page is 'claimed'. aggregator and prior_research are always 'claimed'"
  )


  class Sourced(BaseModel):
      """What kind of source a CSO finding came from (C7). The writer ranks on it: a weaker source never
      overwrites a stronger one. Required on every org-only concept."""

      source_type: FindingSourceType = Field(description=_SOURCE_TYPE_HELP)
      evidence_tier: EvidenceTier = Field(description=_EVIDENCE_TIER_HELP)

      @model_validator(mode="after")
      def _tier(self) -> Sourced:
          check_tier(self.source_type, self.evidence_tier)
          return self


  class OptionallySourced(BaseModel):
      """The same two fields on a concept both kinds share. A funder's row has no tier; an organisation's
      programme, metric or contact without one is held back at promotion."""

      source_type: FindingSourceType | None = Field(default=None, description="REQUIRED for an org. " + _SOURCE_TYPE_HELP)
      evidence_tier: EvidenceTier | None = Field(default=None, description="REQUIRED for an org. " + _EVIDENCE_TIER_HELP)

      @model_validator(mode="after")
      def _tier(self) -> OptionallySourced:
          check_tier(self.source_type, self.evidence_tier)
          return self


  # A CSO's documents, by doc_type. Free text in the schema; listed so a researcher names them one way.
  ORG_DOC_TYPES: tuple[str, ...] = (
      "trust_deed", "registration_certificate", "exemption_order", "exemption_application", "csr1_approval",
      "fcra_certificate", "fcra_return", "audit_report", "annual_report", "policy", "manual_check_evidence",
  )
  ```
  Then:
  - Change the bases: `ProgramFinding(FindingBase, OptionallySourced)`, `MetricFinding(FindingBase, OptionallySourced)`, `ContactFinding(FindingBase, OptionallySourced)`, `OrgIdentityFinding(FindingBase, Sourced)`, `OrgIdentifierFinding(FindingBase, Sourced)`, `OrgFinancialsFinding(YearlyFinding, Sourced)`, `OrgLocationFinding(PlacedFinding, Sourced)`. `ALWAYS_CLAIMED` is imported for the dossier and brief wording in later tasks; drop the import if ruff flags it as unused at this point.
  - Change `DocumentFinding.doc_type`'s description to `"a funder's: annual_report | csr_annexure | brsr | …; a CSO's: " + " | ".join(ORG_DOC_TYPES)`. Move `ORG_DOC_TYPES` above `DocumentFinding` so it is defined first.
- [ ] **Step 4: Promote passes the tier through.** In `promote.py`:
  - **`org_from`.** Inside `OrgRecord(...)`, add `source_type=anchor.get("source_type"), evidence_tier=anchor.get("evidence_tier"),`. An anchor without them raises `ValidationError`, which is a `ValueError`, so `org_from` returns `None`.
  - **`_promote_org`.** Change the first reason to: `"no org_identity or org_identifier finding with a source_type and evidence_tier to build an organisation from (research saved before evidence tiers is re-researched, not promoted)"`.
  - **`_write_facts`.** In the `org_financials` and `org_location` record constructors, add `source_type=f.source_type, evidence_tier=f.evidence_tier,`. In the `metric` and `contact` constructors, add `source_type=getattr(f, "source_type", None), evidence_tier=getattr(f, "evidence_tier", None),`.
  - **`_write_programs`.** In the `ProgramRecord(...)` constructor, add the same two keywords.
- [ ] **Step 5: The existing tests.**
  - In `backend/tests/test_ingest.py`, change `TestFindingsAreShapedLikeTheRowsTheyBecome.EVIDENCE` to `frozenset({"concept", "evidence", "source_url", "source_name", "confidence", "basis", "source_type", "evidence_tier"})`.
  - Leave `TestNothingResearchedIsSilentlyDropped.EVIDENCE` unchanged on purpose: the two fields must reach a record.
  - Change `TestTheOrgWriter.rec` to `return OrgRecord(**{"name": "Goonj", "source_type": "org_document", "evidence_tier": "claimed", **prov(), **kw})`.
  - Find every other org finding dict or org record constructor with `grep -n "org_identity\|org_identifier\|org_financials\|org_location\|OrgRecord(\|OrgFinancialsRecord(\|OrgLocationRecord(" backend/tests/*.py`. Add `"source_type": "org_document", "evidence_tier": "claimed"` to each one that is meant to validate. The funder-only fixture in `TestPromotionRefusesWhatItCannotWrite` needs nothing.
- [ ] **Step 6: Run.**
  - `bt tests/test_cso_evidence.py -q` → all pass.
  - `bt -m "'not integration'" -q` → 0 failed. In particular, `test_every_finding_field_reaches_a_record[org_*]`, `[metric]`, `[contact]` and `[program]` pass, because records carry `source_type` and `evidence_tier`.
  - `ruff check .` → clean.
- [ ] **Step 7: Commit.** `git add -A backend && git commit -m "feat(ingest): every CSO finding names its source type and evidence tier" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 4: Precedence — one rule, one ranked writer

**Files:**
- Modify: `backend/app/ingest/writer.py`. Add a section after `_plain` and imports (`MappingProxyType`, `Mapping`).
- Modify: `backend/tests/test_cso_evidence.py`

**Interfaces:**
- **Produces:**
  - `SOURCE_PRECEDENCE: Mapping[str, int]`;
  - `Tier(NamedTuple)` with fields `source_type: str` and `evidence: str`;
  - `Conflict(NamedTuple)` with fields `table`, `row`, `column`, `stored`, `stored_source`, `stored_url`, `incoming`, `incoming_source`, `incoming_url`, and the method `.describe() -> str`;
  - `_may_overwrite(stored_source: str | None, incoming_source: str) -> bool`;
  - `_ranked(existing: dict, proposed: dict, stored_source: str | None, incoming_source: str) -> tuple[dict[str, dict], list[tuple[str, Any, Any]]]`;
  - `RANKED_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of")`;
  - `async _upsert_ranked(conn, table: str, key: dict, values: tuple[str, ...], proposed: dict, provenance: dict, tier: Tier, document_id: int | None, *, row: str) -> tuple[str, dict, list[Conflict]]`.

- [ ] **Step 1: Failing tests** (append to `test_cso_evidence.py`):
  ```python
  from app.ingest.writer import (  # noqa: E402
      SOURCE_PRECEDENCE, Conflict, Tier, _may_overwrite, _upsert_ranked,
  )

  PROV = {"source_url": "https://ngo.example/audit.pdf", "source_name": "ngo-site", "fetched_at": NOW,
          "as_of": "FY2023-24"}
  KEY = {"org_id": 9, "fiscal_year": "FY2023-24"}
  VALUES = ("total_income", "foreign_unspent", "notes")


  def stored(source, **values):
      return {**dict.fromkeys(VALUES), **values, "source_type": source, "source_url": "https://stored.example"}


  async def ranked(conn, source, evidence, **proposed):
      return await _upsert_ranked(conn, "org_financials", KEY, VALUES, {**dict.fromkeys(VALUES), **proposed},
                                  PROV, Tier(source, evidence), 3, row="[org:9] FY2023-24")


  class TestPrecedence:
      @pytest.mark.parametrize(("stored_source", "incoming", "ok"), [
          ("aggregator", "org_document", True), ("org_document", "aggregator", False),
          ("seed", "aggregator", True), ("registry", "manual_check", False), ("manual_check", "registry", False),
          ("org_document", "org_document", False), ("funder", "staff_dataset", False),
          ("staff_dataset", "funder", True), ("staff_dataset", "prior_research", False),
          ("aggregator", "prior_research", True), ("prior_research", "aggregator", False),
          ("prior_research", "staff_dataset", True), (None, "registry", False),
      ])
      def test_the_order(self, stored_source, incoming, ok):
          assert _may_overwrite(stored_source, incoming) is ok

      def test_every_source_type_is_ranked(self):
          from app.ingest.records import SOURCE_TYPES

          assert set(SOURCE_PRECEDENCE) == set(SOURCE_TYPES)

      def test_an_unknown_source_is_refused(self):
          with pytest.raises(ValueError, match="unknown source_type"):
              _may_overwrite("seed", "blog")


  class TestTheRankedWriter:
      async def test_a_new_row_carries_its_tier(self, recording_conn):
          conn = recording_conn([None])
          status, _, conflicts = await ranked(conn, "org_document", "evidenced", total_income=5_000_000.0)
          assert (status, conflicts) == ("added", [])
          assert conn.sql[1].startswith("INSERT INTO org_financials") and "source_type, evidence" in conn.sql[1]
          assert {"org_document", "evidenced", 3} <= set(conn.params[1])

      async def test_a_weaker_source_never_overwrites(self, recording_conn):
          conn = recording_conn([stored("org_document", total_income=5_000_000)])
          status, changes, conflicts = await ranked(conn, "aggregator", "claimed", total_income=6_200_000.0)
          assert (status, changes) == ("matched", {})
          assert [(c.column, c.stored, c.incoming) for c in conflicts] == [("total_income", 5_000_000, 6_200_000.0)]
          assert not any(q.startswith("UPDATE") for q in conn.sql)

      async def test_a_stronger_source_replaces_a_weaker_one(self, recording_conn):
          conn = recording_conn([stored("aggregator", total_income=6_200_000)])
          status, changes, conflicts = await ranked(conn, "org_document", "evidenced", total_income=5_000_000.0)
          assert (status, set(changes), conflicts) == ("updated", {"total_income"}, [])
          update = conn.sql[1]
          assert "total_income = %s" in update and "source_type = %s" in update and "source_url = %s" in update

      async def test_equals_that_disagree_are_a_conflict(self, recording_conn):
          conn = recording_conn([stored("org_document", total_income=5_000_000)])
          status, _, conflicts = await ranked(conn, "org_document", "evidenced", total_income=5_100_000.0)
          assert status == "matched" and len(conflicts) == 1

      async def test_a_weaker_fill_keeps_the_stronger_tier(self, recording_conn):
          conn = recording_conn([stored("registry", total_income=5_000_000)])
          status, changes, _ = await ranked(conn, "aggregator", "claimed", foreign_unspent=100_000.0)
          assert (status, set(changes)) == ("updated", {"foreign_unspent"})
          assert "foreign_unspent = %s" in conn.sql[1] and "source_type" not in conn.sql[1]

      async def test_a_mid_tier_source_cannot_correct_what_a_weaker_one_filled(self, recording_conn):
          """The cost of a row-level tier, pinned: the aggregator's fill now reads as registry-strength, so
          the CSO's own document cannot replace it. It is reported for a person, never silently kept."""
          conn = recording_conn([stored("registry", total_income=5_000_000, foreign_unspent=100_000)])
          status, _, conflicts = await ranked(conn, "org_document", "evidenced", foreign_unspent=80_000.0)
          assert status == "matched" and conflicts[0].column == "foreign_unspent"

      async def test_an_unranked_row_is_filled_never_overwritten(self, recording_conn):
          conn = recording_conn([stored(None, total_income=5_000_000)])
          status, changes, conflicts = await ranked(conn, "registry", "evidenced",
                                                    total_income=7_000_000.0, notes="audited")
          assert (status, set(changes)) == ("updated", {"notes"})
          assert len(conflicts) == 1 and "source_type" not in conn.sql[1]

      async def test_the_same_value_twice_is_matched_with_no_conflict(self, recording_conn):
          conn = recording_conn([stored("org_document", total_income=5_000_000)])
          assert await ranked(conn, "org_document", "evidenced", total_income=5_000_000.0) == ("matched", {}, [])

      def test_a_conflict_names_both_values_and_both_sources(self):
          text = Conflict("org_financials", "[org:9] FY2023-24", "total_income", 5_000_000, "org_document",
                          "https://ngo.example/audit.pdf", 6_200_000, "aggregator",
                          "https://aggregator.example/ngo").describe()
          for part in ("5000000", "6200000", "org_document", "aggregator", "https://ngo.example/audit.pdf",
                       "https://aggregator.example/ngo", "[org:9]", "kept"):
              assert part in text
  ```
  Run `bt tests/test_cso_evidence.py -q` → `ImportError`.
- [ ] **Step 2: Implement.** In `writer.py`, add `from collections.abc import Mapping` and `from types import MappingProxyType`, and after `_plain`:
  ```python
  # --- Evidence tiers (C7) -------------------------------------------------------
  #
  # Strongest first: registry = manual_check > org_document > funder > staff_dataset > prior_research >
  # aggregator > seed. A weaker source never overwrites a stronger one; a stronger one replaces it; equals
  # that disagree are a conflict a person settles. Filling a blank is never an overwrite. The tier is the
  # ROW's: the strongest source that has written to it, so a weaker source's fill keeps the stronger label.
  SOURCE_PRECEDENCE: Mapping[str, int] = MappingProxyType({
      "registry": 7, "manual_check": 7, "org_document": 6, "funder": 5,
      "staff_dataset": 4, "prior_research": 3, "aggregator": 2, "seed": 1,
  })
  RANKED_PROVENANCE = ("source_url", "source_name", "fetched_at", "as_of")


  class Tier(NamedTuple):
      source_type: str
      evidence: str


  class Conflict(NamedTuple):
      """A disagreement the writer kept rather than resolved: both values, both sources."""

      table: str
      row: str
      column: str
      stored: Any
      stored_source: str | None
      stored_url: str | None
      incoming: Any
      incoming_source: str
      incoming_url: str | None

      def describe(self) -> str:
          return (
              f"{self.table} {self.row}: {self.column} is {self.stored!r} "
              f"({self.stored_source or 'unranked'}, {self.stored_url or 'no source url'}) and this research "
              f"says {self.incoming!r} ({self.incoming_source}, {self.incoming_url or 'no source url'}). "
              f"The stored value was kept — a person decides."
          )


  def _may_overwrite(stored_source: str | None, incoming_source: str) -> bool:
      """Whether a value from incoming_source may replace a DIFFERENT stored value.

      Strictly stronger only. NULL stored means not ranked - a person entered the row, or it predates
      tiers - and Import fills its blanks but never overwrites it, the rule every org row lived under
      before C7.
      """
      if incoming_source not in SOURCE_PRECEDENCE:
          raise ValueError(f"unknown source_type {incoming_source!r}")
      if stored_source is None:
          return False
      return SOURCE_PRECEDENCE[incoming_source] > SOURCE_PRECEDENCE[stored_source]


  def _ranked(
      existing: dict[str, Any], proposed: dict[str, Any], stored_source: str | None, incoming_source: str
  ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, Any, Any]]]:
      """(columns to write as {col: {old, new}}, disagreements kept as (col, stored, incoming))."""
      write: dict[str, dict[str, Any]] = {}
      kept: list[tuple[str, Any, Any]] = []
      for col, new in proposed.items():
          if new is None:
              continue
          old = existing.get(col)
          if old is None:
              write[col] = {"old": None, "new": _plain(new)}
          elif _diff({col: old}, {col: new}):
              if _may_overwrite(stored_source, incoming_source):
                  write[col] = {"old": _plain(old), "new": _plain(new)}
              else:
                  kept.append((col, _plain(old), _plain(new)))
      return write, kept


  async def _upsert_ranked(
      conn: Any, table: str, key: dict[str, Any], values: tuple[str, ...], proposed: dict[str, Any],
      provenance: dict[str, Any], tier: Tier, document_id: int | None, *, row: str,
  ) -> tuple[str, dict, list[Conflict]]:
      """_upsert under the precedence rule. Returns (added | updated | matched, changes, conflicts).

      Provenance and the tier move only when the incoming source took the row (strictly stronger and wrote
      something); a fill from a weaker or equal source leaves them. Table and column names come from
      module constants, never a caller; only values are parameterised.
      """
      where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
      existing = await (
          await conn.execute(
              f"SELECT {', '.join(values)}, source_type, source_url FROM {table} WHERE {where}",
              tuple(key.values()),
          )
      ).fetchone()
      if existing is None:
          cols = list(key) + [c for c in values if proposed.get(c) is not None]
          cols += [c for c, v in provenance.items() if v is not None] + ["source_type", "evidence"]
          vals = [*key.values(), *(proposed[c] for c in values if proposed.get(c) is not None),
                  *(v for v in provenance.values() if v is not None), tier.source_type, tier.evidence]
          if document_id is not None:
              cols.append("document_id")
              vals.append(document_id)
          await conn.execute(
              f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", tuple(vals)
          )
          return "added", {c: {"old": None, "new": _plain(v)} for c, v in zip(cols, vals, strict=True)}, []

      stored_source = existing["source_type"]
      write, kept = _ranked(dict(existing), {c: proposed.get(c) for c in values}, stored_source, tier.source_type)
      conflicts = [
          Conflict(table, row, c, old, stored_source, existing["source_url"], new, tier.source_type,
                   provenance.get("source_url"))
          for c, old, new in kept
      ]
      if not write:
          return "matched", {}, conflicts
      sets = {c: proposed[c] for c in write}
      if _may_overwrite(stored_source, tier.source_type):
          sets.update({c: v for c, v in provenance.items() if v is not None})
          sets.update(source_type=tier.source_type, evidence=tier.evidence)
      await conn.execute(
          f"UPDATE {table} SET {', '.join(f'{c} = %s' for c in sets)}, "
          f"document_id = coalesce(document_id, %s) WHERE {where}",
          (*sets.values(), document_id, *key.values()),
      )
      return "updated", write, conflicts
  ```
- [ ] **Step 3: Run.** `bt tests/test_cso_evidence.py -q` → all pass. `bt -m "'not integration'" -q` → 0 failed. `ruff check .` → clean.
- [ ] **Step 4: Commit.** `git add -A backend && git commit -m "feat(ingest): one precedence rule for CSO facts; disagreements become conflicts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 5: Identity — website, description, aliases and staff reach `orgs`; `write_org` follows precedence; promotion reports conflicts

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (the `orgs` `Table`)
- Modify: `backend/app/ingest/records.py` (`OrgRecord`, new `_distinct_names`)
- Modify: `backend/app/ingest/research_records.py` (`OrgIdentityFinding`, `PromotionReport`)
- Modify: `backend/app/ingest/writer.py`. Change `ORG_UPDATABLE` and `write_org`, and delete `_blanks`. Rewrite the org-side comment above `ORG_UPDATABLE`.
- Modify: `backend/app/ingest/promote.py`. Change the report dict in `promote`, `org_from`, `_promote_org`, and the website branch of `_hold_unstorable`.
- Modify: `backend/app/ingest/tools/catalog_tools.py`. Change the `promote_research` output loop, its docstring, and the org `head` in the dossier.
- Modify: `backend/tests/test_ingest.py` (`TestTheOrgWriter`), `backend/tests/test_cso_evidence.py`

**Interfaces:**
- **Produces:**
  - `orgs` catalog columns `website`, `description`, `aliases` (`text[]`), `staff_count` (`integer`) and `staff_count_note`, inserted before `*_TIER`;
  - `OrgIdentityFinding` and `OrgRecord` fields under the same names;
  - `ORG_UPDATABLE = ("org_kind", "legal_form", "registration_date", "website", "description", "staff_count", "staff_count_note")`;
  - `write_org(conn, rec, match) -> tuple[str, int, dict, list[Conflict]]`;
  - `report["conflicts"]: list[str]`, on both kinds;
  - `PromotionReport.conflicts: list[str]`.
- **Consumes:** `new_aliases` from #99, and `_ranked`, `_may_overwrite`, `Tier`, `Conflict` from Task 4.

- [ ] **Step 1: Failing tests.** Append to `test_cso_evidence.py`:
  ```python
  from app.ingest.matcher import Match  # noqa: E402
  from app.ingest.writer import ORG_UPDATABLE, write_org  # noqa: E402


  def org(**kw):
      from app.ingest.records import OrgRecord

      return OrgRecord(**{"name": "Gramya Vikash Trust", "source_type": "org_document",
                          "evidence_tier": "evidenced", **prov(), **kw})


  def held_org(source="seed", **kw):
      return {"name": "Gramya Vikash Trust", "aliases": [], "source_type": source,
              "source_url": "https://ngodarpan.gov.in/search", **dict.fromkeys(ORG_UPDATABLE),
              "org_kind": "cso", **kw}


  class TestTheIdentityColumns:
      def test_identity_offers_the_new_columns(self):
          from app.ingest.expectations import expected_fields

          names = {f.name for f in expected_fields("org_identity")}
          assert {"website", "description", "aliases", "staff_count", "staff_count_note"} <= names
          assert not names & {"source_type", "evidence"}

      def test_aliases_drop_blanks_and_repeats(self):
          assert org(aliases=[" GVT ", "", "gvt", "Gramya Vikas Trust"]).aliases == ["GVT", "Gramya Vikas Trust"]


  class TestTheOrgWriterRanks:
      async def test_a_stronger_source_replaces_the_seed(self, recording_conn):
          conn = recording_conn([held_org(legal_form="Society")])
          status, _, changes, conflicts = await write_org(conn, org(legal_form="Public Charitable Trust"),
                                                          Match("exact", 9))
          assert (status, set(changes), conflicts) == ("updated", {"legal_form"}, [])
          update = next(q for q in conn.sql if q.startswith("UPDATE orgs"))
          assert "legal_form = %s" in update and "source_type = %s" in update

      async def test_an_aggregator_never_replaces_the_cso_s_own_document(self, recording_conn):
          conn = recording_conn([held_org("org_document", staff_count=20)])
          status, _, _, conflicts = await write_org(
              conn, org(staff_count=45, source_type="aggregator", evidence_tier="claimed"), Match("exact", 9))
          assert status == "matched" and conflicts[0].column == "staff_count"
          assert not any(q.startswith("UPDATE orgs") for q in conn.sql)

      async def test_a_blank_is_filled_by_any_source(self, recording_conn):
          conn = recording_conn([held_org("org_document")])
          status, _, changes, _ = await write_org(
              conn, org(website="https://gvt.example", source_type="aggregator", evidence_tier="claimed"),
              Match("exact", 9))
          assert (status, set(changes)) == ("updated", {"website"})
          assert "source_type" not in next(q for q in conn.sql if q.startswith("UPDATE orgs"))

      async def test_aliases_are_appended_never_replaced(self, recording_conn):
          conn = recording_conn([held_org("org_document", aliases=["GVT"])])
          status, _, changes, _ = await write_org(conn, org(aliases=["gvt", "Gramya Vikas Trust"]), Match("alias", 9))
          assert status == "updated" and changes["aliases"]["new"] == ["GVT", "Gramya Vikas Trust"]
          update = next(i for i, q in enumerate(conn.sql) if q.startswith("UPDATE orgs"))
          assert "aliases = aliases || %s::text[]" in conn.sql[update]
          assert ["Gramya Vikas Trust"] in conn.params[update]

      async def test_a_new_org_carries_its_tier_and_aliases(self, recording_conn):
          conn = recording_conn([None, {"id": 42}])
          status, org_id, _, _ = await write_org(conn, org(aliases=["GVT"], staff_count=20), Match("none"))
          assert (status, org_id) == ("added", 42)
          i = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO orgs"))
          assert "source_type" in conn.sql[i] and "aliases" in conn.sql[i]
          assert {"org_document", "evidenced", 20} <= set(p for p in conn.params[i] if not isinstance(p, list))
          assert ["GVT"] in conn.params[i]


  async def test_promotion_reports_conflicts_beside_held(monkeypatch):
      from app.ingest import promote as promote_mod
      from app.ingest.writer import Conflict

      async def fake_resolve(conn, name, identifiers=None):
          return Match("exact", 9)

      async def fake_write(conn, rec, match):
          return "matched", 9, {}, [Conflict("orgs", "[org:9]", "staff_count", 20, "org_document", "u1", 45,
                                             "aggregator", "u2")]

      async def nothing(*a, **k):
          return {}

      monkeypatch.setattr(promote_mod, "resolve_org", fake_resolve)
      monkeypatch.setattr(promote_mod, "write_org", fake_write)
      monkeypatch.setattr(promote_mod, "_reconcile_org_aliases", lambda conn, r, m, rep: _same(r), raising=False)
      for name in ("_write_documents", "_write_programs", "_write_facts", "_link_research"):
          monkeypatch.setattr(promote_mod, name, nothing)
      row = {"id": 1, "slug": "gvt", "entity_name": "Gramya Vikash Trust", "canonical_name": None,
             "entity_kind": "org", "researched_at": NOW, "schema_version": 2, "website": None,
             "findings": [{"concept": "org_identity", "name": "Gramya Vikash Trust", **BASE, **TIER}]}
      report = await promote_mod.promote(None, row)
      assert report["held"] == [] and "staff_count" in report["conflicts"][0]


  async def _same(record):
      return record
  ```
  Run `bt tests/test_cso_evidence.py -q` → failures.
- [ ] **Step 2: Catalog.** In the `orgs` `Table`, insert before `*_TIER`:
  ```python
              Column("website", "text", note="the organisation's own site"),
              Column("description", "text", note="a few sentences in the organisation's own words; claimed unless a document states it"),
              Column("aliases", "text[]", note="every other spelling a source used: short names, filings, aggregators. Match names against these too"),
              Column("staff_count", "integer", note="people employed, as the source states; staff_count_note says what was counted and where"),
              Column("staff_count_note", "text", note="e.g. '20+ full-time professionals (team page)'. Differing counts across sources are reported as conflicts, not averaged"),
  ```
- [ ] **Step 3: Records and the finding.**
  - In `records.py`, above `OrgRecord`:
    ```python
    def _distinct_names(v: list[str]) -> list[str]:
        """Each spelling once, case-insensitively, in the order found; blanks dropped."""
        out: list[str] = []
        seen: set[str] = set()
        for name in (n.strip() for n in v):
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
        return out
    ```
  - In `OrgRecord`, replace the class docstring with `"""An NGO. Its identifiers are separate facts (OrgIdentifierRecord); `identifiers` here is only the type-to-number map the matcher resolves on."""`.
  - In `OrgRecord`, after `registration_date`, add:
    ```python
        website: str | None = None
        description: str | None = None
        aliases: list[str] = Field(default_factory=list)
        staff_count: int | None = Field(default=None, ge=0)
        staff_count_note: str | None = None

        _names = field_validator("aliases")(lambda v: _distinct_names(v))
    ```
  - In `research_records.py`, change `OrgIdentityFinding`'s docstring to `"""An NGO, not a funder."""` and add after `registration_date`:
  ```python
      website: str | None = Field(default=None, description="the organisation's own site")
      description: str | None = Field(default=None, description="a few sentences in its own words")
      aliases: list[str] = Field(
          default_factory=list,
          description="every other spelling a source used: short names, filings, aggregators. Never another "
                      "organisation's name",
      )
      staff_count: int | None = Field(
          default=None, ge=0, description="as the source states; '20+' is 20, with the wording in staff_count_note"
      )
      staff_count_note: str | None = Field(
          default=None,
          description="what was counted and where, e.g. '20+ full-time professionals (team page)'. A different "
                      "count from another page is its own finding",
      )
  ```
  - In `PromotionReport`, after `held_back`:
  ```python
      conflicts: list[str] = Field(
          default_factory=list,
          description="a source that disagrees with a stored value: both values and both sources, verbatim. "
                      "The stored value was kept",
      )
  ```
- [ ] **Step 4: `write_org`.**
  - Replace the comment block above `ORG_UPDATABLE` with:
    ```python
    # --- The org side ------------------------------------------------------------
    #
    # Precedence, not fill-only (C7): every org writer ranks on the evidence tier. A blank is always filled, a
    # stronger source replaces a weaker one, and anything else that differs is returned as a Conflict for a
    # person. The funder writers above keep their own rule and never see a tier.
    ```
  - Change `ORG_UPDATABLE` as in Interfaces.
  - Delete `_blanks`.
  - Replace `write_org` with:
  ```python
  async def write_org(
      conn: Any, rec: OrgRecord, match: Match
  ) -> tuple[str, int, dict, list[Conflict]]:
      """Returns (status, org_id, changes, conflicts). Status is added | updated | matched.

      Aliases are appended, never replaced: a spelling one source used is still a way to find this
      organisation. Identifiers are not written here: each is its own finding with its own source.
      """
      proposed = {c: getattr(rec, c) for c in ORG_UPDATABLE}
      provenance = {c: getattr(rec, c) for c in ORG_PROVENANCE}
      tier = Tier(rec.source_type, rec.evidence_tier)
      if match.resolved:
          existing = await (
              await conn.execute(
                  f"SELECT name, aliases, source_type, source_url, {', '.join(ORG_UPDATABLE)} "
                  "FROM orgs WHERE id = %s",
                  (match.entity_id,),
              )
          ).fetchone()
          write, kept = _ranked(dict(existing), proposed, existing["source_type"], tier.source_type)
          conflicts = [
              Conflict("orgs", f"[org:{match.entity_id}]", c, old, existing["source_type"],
                       existing["source_url"], new, tier.source_type, rec.source_url)
              for c, old, new in kept
          ]
          held = list(existing["aliases"] or [])
          added = new_aliases(held, rec.aliases, existing["name"])
          if not write and not added:
              return "matched", match.entity_id, {}, conflicts
          sets = {c: proposed[c] for c in write}
          if write and _may_overwrite(existing["source_type"], tier.source_type):
              sets.update({c: v for c, v in provenance.items() if v is not None})
              sets.update(source_type=tier.source_type, evidence=tier.evidence)
          clauses = [f"{c} = %s" for c in sets]
          values = list(sets.values())
          changes = dict(write)
          if added:
              clauses.append("aliases = aliases || %s::text[]")
              values.append(added)
              changes["aliases"] = {"old": held, "new": [*held, *added]}
          await conn.execute(
              f"UPDATE orgs SET {', '.join(clauses)} WHERE id = %s", (*values, match.entity_id)
          )
          await _write_org_identifiers(conn, match.entity_id, rec)
          return "updated", match.entity_id, changes, conflicts

      slug = await _free_slug(conn, slugify(rec.name), "orgs")
      row = await (
          await conn.execute(
              "INSERT INTO orgs (slug, name, org_kind, legal_form, registration_date, website, description, "
              "aliases, staff_count, staff_count_note, registry_status, source_type, evidence, source_url, "
              "source_name, fetched_at, as_of, content_hash, extractor_version) "
              "VALUES (%s, %s, COALESCE(%s, 'cso'), %s, %s, %s, %s, %s, %s, %s, 'placeholder', %s, %s, "
              "%s, %s, %s, %s, %s, %s) RETURNING id",
              (slug, rec.name, rec.org_kind, rec.legal_form, rec.registration_date, rec.website,
               rec.description, new_aliases([], rec.aliases, rec.name), rec.staff_count,
               rec.staff_count_note, tier.source_type, tier.evidence, *provenance.values()),
          )
      ).fetchone()
      await _write_org_identifiers(conn, row["id"], rec)
      return "added", row["id"], {"name": {"old": None, "new": rec.name}}, []
  ```
  `_write_org_identifiers` stays until Task 7, which removes both calls.
- [ ] **Step 5: Promote and the tool.**
  - **Report dict.** In `promote()`, add `"conflicts": []` to the report dict. Next to the existing `report["held"] = list(dict.fromkeys(report["held"]))`, add `report["conflicts"] = list(dict.fromkeys(report["conflicts"]))`.
  - **`org_from`.**
    - Add `website=(identity or {}).get("website") or row.get("website"), description=(identity or {}).get("description"), aliases=(identity or {}).get("aliases") or [], staff_count=(identity or {}).get("staff_count"), staff_count_note=(identity or {}).get("staff_count_note"),`.
    - Delete the docstring sentence "The website is deliberately absent: …".
  - **`_promote_org`.** Replace the three lines `status, org_id, _, conflicts = await write_org(conn, record, match)`, `report["entity"] = {...}` and `report["held"].extend(conflicts)` with:
  ```python
      record = await _reconcile_org_aliases(conn, record, match, report)
      status, org_id, _, conflicts = await write_org(conn, record, match)
      report["entity"] = {"kind": "org", "status": status, "id": org_id, "name": record.name}
      report["conflicts"].extend(c.describe() for c in conflicts)
  ```
    Then:
    - Change the docstring's "write_org fills blanks instead of winning" to "write_org ranks by evidence tier".
    - Add a temporary pass-through, which Task 6 replaces:
    ```python
    async def _reconcile_org_aliases(conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]) -> OrgRecord:
        return record
    ```
    with `from app.ingest.matcher import Match` (promote already imports `resolve_org` from there).
  - **`_hold_unstorable`.** Delete its `if row.get("website"):` branch. Task 7 deletes the rest.
  - **`promote_research` in `catalog_tools.py`.** After the `held back:` loop, add:
  ```python
              for conflict in r.get("conflicts", []):
                  lines.append(f"    conflict: {conflict}")
  ```
    Then:
    - In the docstring's NGO sentence, change "an NGO's reach orgs, org_identifiers, org_financials and org_locations" to "an NGO's reach orgs, org_identifiers, org_financials and org_locations under the evidence-tier precedence rule — a disagreement is reported as a conflict, never resolved silently".
    - Change the org `head` in `funder_dossier` to `"id, name, slug, registry_status, org_kind, legal_form, registration_date, cohort, website, aliases, staff_count, staff_count_note, source_type, evidence"`.
- [ ] **Step 6: The existing org-writer tests.** In `backend/tests/test_ingest.py`'s `TestTheOrgWriter`:
  - **Delete `test_an_existing_org_is_filled_not_overwritten`.** This is deliberate: C7 replaces fill-only with precedence, and Task 5's `TestTheOrgWriterRanks` covers both directions.
  - **Change the stored row dicts in the other tests.** `test_nothing_to_fill_writes_nothing_at_all` and `test_an_unstated_kind_is_not_a_finding_that_contradicts_one` build their rows as `{"name": "Goonj", "aliases": [], "source_type": "org_document", "source_url": "https://goonj.org", **dict.fromkeys(ORG_UPDATABLE), "org_kind": <as before>, "legal_form": "Trust"}`. Import `ORG_UPDATABLE` from `app.ingest.writer`.
  - **Assertions.** Keep their assertions. The `conflicts` they compare to is still `[]`.
- [ ] **Step 7: Run.** `bt tests/test_cso_evidence.py tests/test_ingest.py -q` → pass. `bt -m "'not integration'" -q` → 0 failed. `ruff check .` → clean.
- [ ] **Step 8: Commit.** `git add -A backend && git commit -m "feat(ingest): an organisation's website, description, aliases and staff; write_org ranks instead of filling" -m "Promotion reports conflicts beside held, with both values and both sources." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 6: Matching on aliases and normalised names (C11); a spelling another org answers to is held

**Files:**
- Modify: `backend/app/ingest/matcher.py` (`resolve_org`; new `name_key`)
- Modify: `backend/app/ingest/writer.py` (new `org_alias_holders`)
- Modify: `backend/app/ingest/promote.py` (replace the pass-through `_reconcile_org_aliases`)
- Modify: `backend/tests/test_cso_evidence.py`

**Interfaces:**
- **Produces:**
  - `matcher.name_key(name: str) -> str`;
  - `resolve_org(conn, name: str, identifiers: dict[str, str] | None = None) -> Match`, with the steps identifier → exact → alias → normalised name or alias (`"alias"`), plus boilerplate (`"boilerplate"`) → trigram;
  - `writer.org_alias_holders(conn, spellings: list[str], org_id: int | None) -> dict[str, dict]`, keyed on the lower-cased spelling, with `{"id", "name"}`;
  - `promote._reconcile_org_aliases(conn, record: OrgRecord, match: Match, report: dict) -> OrgRecord`.
- **Query order** that `resolve_org` issues, which the tests queue. Each step runs only when the one before it did not resolve:
  1. one `fetchone` per identifier;
  2. exact name, `fetchone`;
  3. alias, `fetchall`, `LIMIT 2`;
  4. candidates, `fetchall` (`id, name, aliases`);
  5. trigram scoring, `fetchall`.

- [ ] **Step 1: Failing tests** (append):
  ```python
  from app.ingest.matcher import name_key, resolve_org  # noqa: E402


  class TestNameKey:
      @pytest.mark.parametrize(("a", "b"), [
          ("North East Network", "Northeast Network"), ("The North-East Network", "NORTH EAST NETWORK"),
          ("Gramya Vikash Trust.", "Gramya Vikash Trust"), ("Seba (Kheti) Trust", "Seba Kheti Trust"),
      ])
      def test_spellings_of_one_name_share_a_key(self, a, b):
          assert name_key(a) == name_key(b)

      def test_brackets_keep_their_content(self):
          """Two chapters of one CSO differ only inside the brackets; dropping the content would merge them."""
          assert name_key("Seva Mandir (Assam)") != name_key("Seva Mandir (Bihar)")

      def test_the_inside_of_a_word_is_left_alone(self):
          assert name_key("Theatre for Change") == "theatre for change"


  class TestResolveOrg:
      async def test_an_alias_resolves(self, recording_conn):
          conn = recording_conn([None, [{"id": 4}]])
          assert await resolve_org(conn, "GVT") == Match("alias", 4)
          assert "unnest(aliases)" in conn.sql[1]

      async def test_an_alias_two_orgs_share_resolves_neither(self, recording_conn):
          conn = recording_conn([None, [{"id": 4}, {"id": 5}], [], []])
          assert (await resolve_org(conn, "GVT")).method == "none"

      async def test_a_normalised_name_resolves(self, recording_conn):
          conn = recording_conn([None, [], [{"id": 6, "name": "North East Network", "aliases": []}]])
          assert await resolve_org(conn, "The Northeast Network") == Match("alias", 6)

      async def test_a_normalised_alias_resolves(self, recording_conn):
          conn = recording_conn([None, [], [{"id": 6, "name": "NEN", "aliases": ["North-East Network"]}]])
          assert await resolve_org(conn, "Northeast Network") == Match("alias", 6)

      async def test_a_normalised_name_two_orgs_share_resolves_neither(self, recording_conn):
          conn = recording_conn([None, [], [{"id": 6, "name": "North East Network", "aliases": []},
                                            {"id": 7, "name": "Northeast Network", "aliases": []}], []])
          assert (await resolve_org(conn, "North-East Network")).method == "none"

      async def test_two_chapters_do_not_merge(self, recording_conn):
          conn = recording_conn([None, [], [{"id": 6, "name": "Seva Mandir (Assam)", "aliases": []}], []])
          assert (await resolve_org(conn, "Seva Mandir (Bihar)")).method == "none"

      async def test_an_identifier_still_comes_first(self, recording_conn):
          conn = recording_conn([{"org_id": 5}])
          assert await resolve_org(conn, "Goonj", {"12a": "AAATG5219M"}) == Match("identifier", 5)
          assert "FROM org_identifiers" in conn.sql[0]


  class TestAnotherOrgsSpellingIsHeld:
      async def test_a_spelling_another_org_answers_to_is_held(self, recording_conn):
          from app.ingest.promote import _reconcile_org_aliases

          conn = recording_conn([[{"id": 3, "name": "RGVN Trust", "lname": "rgvn trust", "laliases": ["rgvn"]}]])
          report = {"held": []}
          out = await _reconcile_org_aliases(conn, org(aliases=["RGVN", "GVT"]), Match("exact", 9), report)
          assert out.aliases == ["Gramya Vikash Trust", "GVT"]
          assert "[org:3]" in report["held"][0] and "'RGVN'" in report["held"][0]

      async def test_the_research_spelling_becomes_an_alias(self, recording_conn):
          from app.ingest.promote import _reconcile_org_aliases

          out = await _reconcile_org_aliases(recording_conn([[]]), org(name="Gramya Vikas Trust"),
                                             Match("alias", 9), {"held": []})
          assert out.aliases[0] == "Gramya Vikas Trust"
  ```
  Run → failures.
- [ ] **Step 2: Matcher.** In `matcher.py`, add after `same_but_for_boilerplate`:
  ```python
  def name_key(name: str) -> str:
      """One spelling per CSO name, for comparison only (C11).

      Folds 'North East' / 'North-East' / 'Northeast', drops a standalone 'The', and turns brackets and
      punctuation into spaces. Bracket CONTENT is kept: 'Seva Mandir (Assam)' and 'Seva Mandir (Bihar)'
      are two chapters, and the brackets are all that tells them apart.
      """
      folded = re.sub(r"north[\s\-]*east", "northeast", name.lower())
      return " ".join(t for t in re.findall(r"[a-z0-9]+", folded) if t != "the")
  ```
  In `resolve_org`:
  - Replace the docstring with:
    ```python
        """Identifier, exact name, alias, normalised name or alias, boilerplate, then trigram.

        Aliases are orgs.aliases (0033). A spelling two organisations share - as an alias or as a normalised
        name - resolves neither and falls through to the trigram step, which proposes rather than merges.
        """
    ```
  - Keep the identifier and exact steps.
  - Replace the boilerplate block with:
    ```python
        rows = await (
            await conn.execute(
                "SELECT id FROM orgs WHERE EXISTS "
                "(SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(%s)) ORDER BY id LIMIT 2",
                (name,),
            )
        ).fetchall()
        if len(rows) == 1:
            return Match("alias", rows[0]["id"])

        rows = await (
            await conn.execute(
                "SELECT id, name, aliases FROM orgs WHERE similarity(name, %s) >= %s "
                "OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE similarity(a, %s) >= %s)",
                (name, TRIGRAM_FLOOR, name, TRIGRAM_FLOOR),
            )
        ).fetchall()
        key = name_key(name)
        same = {r["id"] for r in rows if key in {name_key(n) for n in (r["name"], *(r.get("aliases") or []))}}
        if len(same) == 1:
            return Match("alias", same.pop())
        if not same:
            for row in rows:
                if same_but_for_boilerplate(name, row["name"]):
                    return Match("boilerplate", row["id"], 1.0)
    ```
    The trigram scoring block below it is unchanged.
  - If #99 rewrote the docstring of `resolve_org` to say orgs have no alias step, this replaces it.
- [ ] **Step 3: `org_alias_holders`.** In `writer.py`, after `write_org`:
  ```python
  async def org_alias_holders(conn: Any, spellings: list[str], org_id: int | None) -> dict[str, dict]:
      """lower(spelling) -> {"id", "name"} of ANOTHER organisation that answers to it, by name or alias."""
      lowered = sorted({s.lower() for s in spellings if s})
      if not lowered:
          return {}
      rows = await (
          await conn.execute(
              "SELECT id, name, lower(name) AS lname, "
              "ARRAY(SELECT lower(a) FROM unnest(aliases) AS a) AS laliases FROM orgs "
              "WHERE id IS DISTINCT FROM %s AND (lower(name) = ANY(%s) "
              "OR EXISTS (SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = ANY(%s)))",
              (org_id, lowered, lowered),
          )
      ).fetchall()
      out: dict[str, dict] = {}
      for r in rows:
          for spelling in sorted({r["lname"], *(r["laliases"] or [])} & set(lowered)):
              out.setdefault(spelling, {"id": r["id"], "name": r["name"]})
      return out
  ```
- [ ] **Step 4: `_reconcile_org_aliases`.** Replace the pass-through in `promote.py`, and import `org_alias_holders`:
  ```python
  async def _reconcile_org_aliases(
      conn: Any, record: OrgRecord, match: Match, report: dict[str, Any]
  ) -> OrgRecord:
      """The spellings to add as aliases: the research's own name and its aliases, less any that another
      organisation already answers to. Those are held for a person - an alias two organisations share
      resolves neither, so writing it would make both harder to find and merge nothing."""
      wanted = [record.name, *record.aliases]
      holders = await org_alias_holders(conn, wanted, match.entity_id)
      for spelling in wanted:
          holder = holders.get(spelling.lower())
          if holder is not None:
              report["held"].append(
                  f"alias {spelling!r} is already the name or an alias of {holder['name']!r} "
                  f"[org:{holder['id']}], so it is not added to {record.name!r}. Two organisations "
                  f"sharing a spelling is a decision for a person."
              )
      kept = [s for s in wanted if s.lower() not in holders]
      return record.model_copy(update={"aliases": kept})
  ```
  `write_org` already passes `rec.aliases` through `new_aliases(held, …, stored name)`, so the record's own name is added only when it differs from the stored one.
- [ ] **Step 5: Requeue older fakes.** The new alias `fetchall` sits between the exact step and the candidate step, so any existing test that drives `resolve_org` past the exact step needs one more `[]` queued after the exact reply. A candidate row without `aliases` is fine, because the loop uses `r.get("aliases")`. Find them with `grep -n "resolve_org" backend/tests/*.py`.
  - On master the only hit is #99's `test_resolve_org_still_reads_org_identifiers`, which resolves on the identifier step and needs no change.
  - Requeue any other hit #99 added.
- [ ] **Step 6: Run.** `bt tests/test_cso_evidence.py tests/test_ingest.py -q` → pass. `TestMatchingOnTheDistinctivePartOfAName` is unchanged. Full unit tier → 0 failed. `ruff check .` → clean.
- [ ] **Step 7: Commit.** `git add -A backend && git commit -m "feat(ingest): resolve_org matches aliases and normalised names; shared spellings are held" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 7: Registrations with a status — `org_identifier` becomes its own fact row

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (the `org_identifiers` `Table`)
- Modify: `backend/app/ingest/expectations.py`. Change `CONCEPTS["org_identifier"]`, `REQUIRED["org_identifier"]` and `expected_fields`.
- Modify: `backend/app/ingest/records.py`. Add `IDENTIFIER_STATUSES`, `NEEDS_A_NUMBER`, `check_registration` and `OrgIdentifierRecord`, and add it to `Record`.
- Modify: `backend/app/ingest/research_records.py` (`OrgIdentifierFinding`)
- Modify: `backend/app/ingest/writer.py`. Add `ORG_IDENTIFIER_VALUES` and `write_org_identifier`. Delete `_write_org_identifiers` and both of its calls in `write_org`.
- Modify: `backend/app/ingest/promote.py`. Change `ORG_WRITE_ORDER`, `CONCEPT_RECORDS`, `RENAMED`, `_row_identity`, `_write_facts` (new branch), `org_from` (match map) and `_promote_org`. Delete `_hold_unstorable`.
- Modify: `backend/app/ingest/brief.py` (the `org_identifier` headline)
- Modify: `backend/app/ingest/tools/catalog_tools.py` (the `org_identifiers` dossier section)
- Modify: `backend/tests/test_ingest.py` (`apart`, `test_twelve_a_and_eighty_g_reach_org_identifiers`), `backend/tests/test_cso_evidence.py` (`MINIMAL["org_identifier"]`)

**Interfaces:**
- **Produces:**
  - catalog `org_identifiers`: `primary_key=('id',)`, with columns after `*_TIER` in DDL order: `id`, `status` (values = the 10), `valid_from`, `valid_until`, `checked_at`, `checked_by`, `check_method` (values = the 4), `evidence_document_id`, `application_ref`, and a `ForeignKey("evidence_document_id", "documents.id")`. `checked_by` has no FK entry, because `users` is excluded;
  - `ConceptSpec("org_identifiers", …, columns=("id_type", "id_value", "status", "valid_from", "valid_until", "check_method", "application_ref", "notes"))`;
  - `REQUIRED["org_identifier"] = {"id_type", "status"}`;
  - `records.IDENTIFIER_STATUSES: tuple[str, ...]`, `records.NEEDS_A_NUMBER: frozenset[str]`, `records.check_registration(id_value, application_ref, status) -> None`;
  - `OrgIdentifierRecord`;
  - `ORG_IDENTIFIER_VALUES`;
  - `write_org_identifier(conn, rec: OrgIdentifierRecord, org_id: int, document_id: int | None) -> tuple[str, dict, list[Conflict]]`, where the status is `added`, `updated`, `matched` or `held`;
  - `ORG_WRITE_ORDER = ("org_identifier", "org_financials", "org_location", "metric", "contact")`.

- [ ] **Step 0: Pin the post-#99 shapes this task touches.** Run `grep -n "def _row_identity" -A3 backend/app/ingest/promote.py` and `grep -rn "_row_identity(" backend/tests`.
  - The tests below call `_row_identity(concept, f, program_id, state_id, district_id, sector_id)` with six positional arguments, as on master.
  - If #99 changed the parameter list, write the calls below to match it, and add the `org_identifier` branch in the same style.
- [ ] **Step 1: Failing tests.** In `test_cso_evidence.py`, replace the `MINIMAL` line `"org_identifier": {"id_type": "pan", "id_value": "AAATG1234K"},` with `"org_identifier": {"id_type": "pan", "id_value": "AAATG1234K", "status": "registered"},`. Then append:
  ```python
  from app.ingest.writer import write_org_identifier  # noqa: E402


  def ident(**kw):
      from app.ingest.records import OrgIdentifierRecord

      return OrgIdentifierRecord(**{"entity_name": "Gramya Vikash Trust", "id_type": "12a",
                                    "source_type": "org_document", "evidence_tier": "evidenced",
                                    **prov(), **kw})


  def stored_id(**kw):
      return {"id": 11, "org_id": 9, "id_value": None, "status": "applied", "valid_from": None,
              "valid_until": None, "application_ref": "ACK-77", "check_method": "document", "notes": None,
              "source_type": "org_document", "source_url": "https://ngo.example/10ab.pdf", **kw}


  class TestRegistrationsHaveAStatus:
      def test_the_finding_offers_the_status_and_its_dates(self):
          from app.ingest.expectations import expected_fields

          fields = {f.name: f for f in expected_fields("org_identifier")}
          assert set(fields) == {"id_type", "id_value", "status", "valid_from", "valid_until", "check_method",
                                 "application_ref", "notes"}
          assert fields["status"].required and not fields["id_value"].required

      def test_an_application_needs_no_number(self):
          rec = finding("org_identifier", id_type="12a", id_value=None, status="applied",
                        application_ref="ACK-77", **TIER)
          assert rec.id_value is None

      @pytest.mark.parametrize("status", ["registered", "expired", "cancelled"])
      def test_a_registration_needs_its_number(self, status):
          with pytest.raises(ValidationError, match="number"):
              finding("org_identifier", id_value=None, status=status, **TIER)

      def test_research_cannot_record_a_manual_check(self):
          with pytest.raises(ValidationError):
              finding("org_identifier", check_method="manual_check", **TIER)

      def test_concepts_listing_columns_add_no_internal_one_but_this(self):
          from app.ingest.expectations import CONCEPTS, INTERNAL

          for name, spec in CONCEPTS.items():
              if spec.columns is None:
                  continue
              extra = set(spec.columns) & INTERNAL
              assert extra == ({"valid_from"} if name == "org_identifier" else set()), name


  class TestTheIdentifierWriter:
      async def test_an_application_is_an_open_row(self, recording_conn):
          conn = recording_conn([None, [], None])
          status, _, _ = await write_org_identifier(conn, ident(status="applied", application_ref="ACK-77"), 9, None)
          assert status == "added"
          insert = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO org_identifiers"))
          assert None in conn.params[insert] and "applied" in conn.params[insert]

      async def test_an_application_becomes_the_registration(self, recording_conn):
          conn = recording_conn([None, stored_id()])
          status, changes, conflicts = await write_org_identifier(
              conn, ident(id_value="AAATG1234KE20241", status="registered", source_type="registry"), 9, None)
          assert (status, conflicts) == ("updated", [])
          assert {"id_value", "status"} <= set(changes)
          assert not any(q.startswith("INSERT") for q in conn.sql)
          assert "WHERE id = %s" in next(q for q in conn.sql if q.startswith("UPDATE org_identifiers"))

      async def test_an_equal_source_saying_registered_is_a_conflict(self, recording_conn):
          conn = recording_conn([None, stored_id()])
          _, changes, conflicts = await write_org_identifier(
              conn, ident(id_value="AAATG1234KE20241", status="registered"), 9, None)
          assert set(changes) == {"id_value"} and conflicts[0].column == "status"

      async def test_a_number_another_org_holds_is_a_conflict_not_a_crash(self, recording_conn):
          conn = recording_conn([stored_id(org_id=3, id_value="AAATG1234K", status="registered", source_type="seed")])
          status, _, conflicts = await write_org_identifier(
              conn, ident(id_type="pan", id_value="AAATG1234K", status="registered"), 9, None)
          assert status == "held" and "[org:3]" in conflicts[0].describe()
          assert not any(q.startswith(("INSERT", "UPDATE")) for q in conn.sql)

      async def test_a_blocked_check_never_replaces_a_known_status(self, recording_conn):
          conn = recording_conn([None, [stored_id(id_value="FC1234", status="registered", application_ref=None)]])
          status, _, conflicts = await write_org_identifier(
              conn, ident(id_type="fcra", status="check_blocked", source_type="registry"), 9, None)
          assert (status, conflicts) == ("matched", [])

      async def test_the_same_registration_twice_is_matched(self, recording_conn):
          """Re-promotion changes nothing, even when a source spells the number in lower case."""
          held = stored_id(id_value="AAATG1234K", status="registered", application_ref=None, check_method=None)
          conn = recording_conn([held])
          assert await write_org_identifier(
              conn, ident(id_type="pan", id_value="aaatg1234k", status="registered"), 9, None
          ) == ("matched", {}, [])

      async def test_an_aggregator_listing_does_not_upgrade_an_application(self, recording_conn):
          conn = recording_conn([None, stored_id()])
          _, _, conflicts = await write_org_identifier(
              conn, ident(id_value="AAATG1234KE20241", status="registered", source_type="aggregator",
                          evidence_tier="claimed"), 9, None)
          assert conflicts[0].column == "status" and conflicts[0].stored == "applied"


  def test_two_open_findings_of_one_type_are_one_row():
      from app.ingest.promote import _row_identity

      a = finding("org_identifier", id_type="12a", id_value=None, status="applied", application_ref="A", **TIER)
      b = finding("org_identifier", id_type="12a", id_value=None, status="applied", application_ref="B", **TIER)
      c = finding("org_identifier", id_type="12a", id_value=" aaatg1234k ", status="registered", **TIER)
      d = finding("org_identifier", id_type="12a", id_value="AAATG1234K", status="registered", **TIER)
      assert _row_identity("org_identifier", a, None, None, None, None) == \
          _row_identity("org_identifier", b, None, None, None, None)
      assert _row_identity("org_identifier", c, None, None, None, None) == \
          _row_identity("org_identifier", d, None, None, None, None)
  ```
  In `backend/tests/test_ingest.py`:
  - Remove `"org_identifier"` from the `apart` set in `test_every_promotable_concept_is_written_by_one_kind_or_the_other`, and leave the rest as #99 left it.
  - Replace `test_twelve_a_and_eighty_g_reach_org_identifiers` with:
  ```python
      async def test_write_org_writes_no_identifier(self):
          """Each identifier is now its own finding with its own source (write_org_identifier)."""
          from app.ingest.matcher import Match
          from app.ingest.writer import write_org

          conn = self._Conn([None, {"id": 42}])
          await write_org(conn, self.rec(identifiers={"12a": "AAATG5219M"}), Match("none"))
          assert not any("org_identifiers" in q for q in conn.sql)
  ```
  Run → failures.
- [ ] **Step 2: Catalog.** Change `org_identifiers`:
  - Set `description="Statutory registrations of an org (PAN, 12A, 80G, FCRA, Darpan...), one row each, with a status. A row may have no number yet (an application)."` and `primary_key=('id',)`.
  - Add `ForeignKey("evidence_document_id", "documents.id")` to its `foreign_keys`.
  - Change `Column("id_value", "text")` to `Column("id_value", "text", note="NULL while only applied for: see status and application_ref")`.
  - After `*_TIER`, add:
  ```python
              Column("id", "bigint"),
              Column("status", "text", note="'applied' is NOT a registration; 'check_blocked' means nobody could read the registry, NEVER that it is valid; 'not_found' means a working source did not list it", values=('applied', 'provisional', 'registered', 'expired', 'suspended', 'cancelled', 'surrendered', 'not_available', 'not_found', 'check_blocked')),
              Column("valid_from", "date"),
              Column("valid_until", "date", note="an FCRA or 12AB/80G approval's end date, when stated"),
              Column("checked_at", "timestamp with time zone", note="when a person or a registry read last confirmed the status"),
              Column("checked_by", "uuid", note="the staff member who made a manual check"),
              Column("check_method", "text", values=('document', 'registry', 'manual_check', 'aggregator')),
              Column("evidence_document_id", "bigint", note="the documents row holding the certificate, order or check evidence"),
              Column("application_ref", "text", note="e.g. a Form 10AB acknowledgement number"),
  ```
- [ ] **Step 3: Expectations.**
  - Change `CONCEPTS["org_identifier"]` to:
  ```python
      "org_identifier": ConceptSpec(
          "org_identifiers",
          "Registrations and their status",
          kinds=_ORG,
          # valid_from is INTERNAL elsewhere (a place link's bookkeeping); here it is a stated date on a
          # certificate. checked_at, checked_by and evidence_document_id are staff fields for manual checks.
          columns=("id_type", "id_value", "status", "valid_from", "valid_until", "check_method",
                   "application_ref", "notes"),
      ),
  ```
    This removes its `not_written`: notes are written now.
  - Set `REQUIRED["org_identifier"] = frozenset({"id_type", "status"})`.
  - In `expected_fields`, make a column the concept explicitly lists bypass `INTERNAL`. After #99's `if spec.columns is not None and name not in spec.columns: continue`, the skip line becomes:
  ```python
          listed = spec.columns is not None and name in spec.columns
          if name == "id" or name in PROVENANCE or name in TIER or column.heavy:
              continue
          if name in INTERNAL and not listed:
              continue
  ```
- [ ] **Step 4: Record and finding.** In `records.py`:
  ```python
  IDENTIFIER_STATUSES: tuple[str, ...] = (
      "applied", "provisional", "registered", "expired", "suspended", "cancelled", "surrendered",
      "not_available", "not_found", "check_blocked",
  )
  IdentifierStatus = Literal["applied", "provisional", "registered", "expired", "suspended", "cancelled",
                             "surrendered", "not_available", "not_found", "check_blocked"]
  # A status that is about a number cannot be recorded without one.
  NEEDS_A_NUMBER = frozenset({"provisional", "registered", "expired", "suspended", "cancelled", "surrendered"})


  def check_registration(id_value: str | None, application_ref: str | None, status: str) -> None:
      if status in NEEDS_A_NUMBER and not id_value:
          raise ValueError(f"status {status!r} needs the registration's number; an application is 'applied'")
      if status == "applied" and not (id_value or application_ref):
          raise ValueError("an application needs its number or its acknowledgement (application_ref)")


  class OrgIdentifierRecord(Provenance, Tiered):
      """One registration of an NGO and what is known of it (C2, C3)."""

      kind: Literal["org_identifier"] = "org_identifier"
      entity_name: str = Field(min_length=2)
      id_type: Literal["pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no"]
      id_value: str | None = None
      status: IdentifierStatus
      valid_from: date | None = None
      valid_until: date | None = None
      check_method: Literal["document", "registry", "manual_check", "aggregator"] | None = None
      application_ref: str | None = None
      notes: str | None = None
      source_type: SourceType
      evidence_tier: EvidenceTier

      @field_validator("id_value")
      @classmethod
      def _stripped(cls, v: str | None) -> str | None:
          return v.strip() or None if v else None

      @model_validator(mode="after")
      def _a_status_has_what_it_needs(self) -> OrgIdentifierRecord:
          check_registration(self.id_value, self.application_ref, self.status)
          return self
  ```
  Add `OrgIdentifierRecord` to `Record`.

  In `research_records.py`, import `IdentifierStatus` and `check_registration`, and replace `OrgIdentifierFinding`:
  ```python
  class OrgIdentifierFinding(FindingBase, Sourced):
      """One registration and its status. A Form 10AB acknowledgement is 'applied', never 'registered'; a
      registry nobody could read is 'check_blocked', never assumed valid."""

      concept: Literal["org_identifier"] = "org_identifier"
      id_type: Literal["pan", "12a", "80g", "fcra", "csr1", "darpan", "cin", "reg_no"]
      id_value: str | None = Field(
          default=None, description="exactly as printed. None only while it is applied for. Never guess one"
      )
      status: IdentifierStatus = Field(description="what the source shows, not what you expect")
      valid_from: date | None = None
      valid_until: date | None = Field(default=None, description="an approval's end date, when stated")
      check_method: Literal["document", "registry", "aggregator"] | None = Field(
          default=None, description="how the status was read: from the CSO's document, a registry, an aggregator"
      )
      application_ref: str | None = Field(default=None, description="e.g. a Form 10AB acknowledgement number")
      notes: str | None = None

      @model_validator(mode="after")
      def _a_status_has_what_it_needs(self) -> OrgIdentifierFinding:
          check_registration(self.id_value, self.application_ref, self.status)
          return self
  ```
- [ ] **Step 5: The writer.** Delete `_write_org_identifiers` and its two calls in `write_org`. After `org_alias_holders`, add:
  ```python
  ORG_IDENTIFIER_VALUES = ("id_value", "status", "valid_from", "valid_until", "application_ref",
                           "check_method", "notes")


  async def write_org_identifier(
      conn: Any, rec: OrgIdentifierRecord, org_id: int, document_id: int | None
  ) -> tuple[str, dict, list[Conflict]]:
      """One registration with its status. Returns (added | updated | matched | held, changes, conflicts).

      Never trips 0033's two unique indexes, either of which would abort the whole promotion: a number is
      looked up (case-insensitively) before it is written, and an organisation's one open row per type is
      the row a number later fills. A number another organisation holds is a conflict, not a write.
      """
      cols = ", ".join(ORG_IDENTIFIER_VALUES)
      head = f"SELECT id, org_id, {cols}, source_type, source_url FROM org_identifiers WHERE "
      target = None
      if rec.id_value:
          holder = await (
              await conn.execute(head + "id_type = %s AND lower(id_value) = lower(%s)",
                                 (rec.id_type, rec.id_value))
          ).fetchone()
          if holder is not None and holder["org_id"] != org_id:
              return "held", {}, [Conflict(
                  "org_identifiers", f"{rec.id_type} {rec.id_value}", "org_id", f"[org:{holder['org_id']}]",
                  holder["source_type"], holder["source_url"], f"[org:{org_id}]", rec.source_type,
                  rec.source_url,
              )]
          target = holder
      if target is None:
          target = await (
              await conn.execute(head + "org_id = %s AND id_type = %s AND id_value IS NULL",
                                 (org_id, rec.id_type))
          ).fetchone()
      if target is None and not rec.id_value:
          # A status with no number is about the registration of that type we already hold, if exactly one.
          rows = await (
              await conn.execute(head + "org_id = %s AND id_type = %s AND is_current ORDER BY id LIMIT 2",
                                 (org_id, rec.id_type))
          ).fetchall()
          target = rows[0] if len(rows) == 1 else None

      proposed = {c: getattr(rec, c) for c in ORG_IDENTIFIER_VALUES}
      provenance = {c: getattr(rec, c) for c in RANKED_PROVENANCE}
      tier = Tier(rec.source_type, rec.evidence_tier)
      if target is None:
          cols_in = ["org_id", "id_type", *ORG_IDENTIFIER_VALUES, *RANKED_PROVENANCE,
                     "source_type", "evidence", "document_id"]
          vals = [org_id, rec.id_type, *proposed.values(), *provenance.values(), tier.source_type,
                  tier.evidence, document_id]
          await conn.execute(
              f"INSERT INTO org_identifiers ({', '.join(cols_in)}) VALUES ({', '.join(['%s'] * len(cols_in))})",
              tuple(vals),
          )
          return "added", {"status": {"old": None, "new": rec.status}}, []

      if rec.status == "check_blocked":
          proposed["status"] = None       # a check that could not be made says nothing about a known status
      if target["id_value"] is not None:
          proposed["id_value"] = None     # found by its number (case-insensitively): the spelling is not news
      write, kept = _ranked(dict(target), proposed, target["source_type"], tier.source_type)
      conflicts = [
          Conflict("org_identifiers", f"[org:{org_id}] {rec.id_type}", c, old, target["source_type"],
                   target["source_url"], new, tier.source_type, rec.source_url)
          for c, old, new in kept
      ]
      if not write:
          return "matched", {}, conflicts
      sets = {c: proposed[c] for c in write}
      if _may_overwrite(target["source_type"], tier.source_type):
          sets.update({c: v for c, v in provenance.items() if v is not None})
          sets.update(source_type=tier.source_type, evidence=tier.evidence)
      await conn.execute(
          f"UPDATE org_identifiers SET {', '.join(f'{c} = %s' for c in sets)}, "
          "document_id = coalesce(document_id, %s) WHERE id = %s",
          (*sets.values(), document_id, target["id"]),
      )
      return "updated", write, conflicts
  ```
  Import `OrgIdentifierRecord` in `writer.py`.
- [ ] **Step 6: Promote.**
  - **`ORG_WRITE_ORDER`.** Set it as in Interfaces, with the comment `# Identifiers first: each is its own fact with its own source, and nothing else names one.`.
  - **`CONCEPT_RECORDS["org_identifier"]`.** Set it to `OrgIdentifierRecord` and import it.
  - **`RENAMED`.** Delete the two `("org_identifier", …)` entries.
  - **`org_from`.** Make the matching map value-only: `identifiers={f["id_type"]: f["id_value"] for f in identifiers if f.get("id_value")},`.
  - **`_row_identity`.** Add, before `if concept == "org_location":`:
  ```python
      if concept == "org_identifier":
          return (concept, f.id_type, (f.id_value or "").strip().lower() or None)
  ```
  - **`_write_facts`.** Add a branch before `elif concept == "org_financials":`, and collect conflicts. Declare `conflicts: list[Conflict] = []` beside `seen`, and after the loop add `report["conflicts"].extend(c.describe() for c in conflicts)`:
  ```python
                  elif concept == "org_identifier":
                      rec = OrgIdentifierRecord(
                          entity_name=name, id_type=f.id_type, id_value=f.id_value, status=f.status,
                          valid_from=f.valid_from, valid_until=f.valid_until, check_method=f.check_method,
                          application_ref=f.application_ref, notes=f.notes, source_type=f.source_type,
                          evidence_tier=f.evidence_tier, as_of=None, **prov,
                      )
                      status, _, found = await write_org_identifier(conn, rec, owner.id, document_id)
                      conflicts.extend(found)
                      _count(report, "org_identifiers", status)
  ```
  - **`_hold_unstorable`.** Delete it and its call in `_promote_org`. The website and the identifier notes have columns now.
  - Import `Conflict` and `write_org_identifier`.
- [ ] **Step 7: Brief and dossier.**
  - **`brief.py`.** Add a helper and replace the `org_identifier` branch:
  ```python
  def _tier(f: dict[str, Any]) -> str | None:
      if not f.get("source_type"):
          return None
      return f"{f.get('evidence_tier')} ({f['source_type']})"
  ```
  ```python
      if concept == "org_identifier":
          number = f.get("id_value") or (f"application {f['application_ref']}" if f.get("application_ref") else None)
          return _join(f["id_type"].upper(), number, f.get("status"),
                       f"valid until {f['valid_until']}" if f.get("valid_until") else None, _tier(f))
  ```
  - **`catalog_tools.py`.** Change the dossier section title to `"org_identifiers (status: 'applied' is not a registration; 'check_blocked' is not 'valid')"` and its SQL to:
  ```sql
          SELECT id_type, id_value, status, valid_until, application_ref, is_current, source_type, evidence
          FROM org_identifiers WHERE org_id = %s ORDER BY id_type, is_current DESC, id
  ```
- [ ] **Step 8: Run.**
  - `bt tests/test_cso_evidence.py tests/test_ingest.py -q` → pass. That includes `test_the_model_carries_exactly_what_the_table_expects[org_identifier]` and `test_every_finding_field_reaches_a_record[org_identifier]`. `test_nothing_is_excused_that_is_actually_written` passes because the `notes` excuse is gone.
  - Full unit tier → 0 failed. `ruff check .` → clean.
  - `bti tests/test_sql_integration.py::TestCatalogMatchesReality -q` → `2 passed`.
- [ ] **Step 9: Commit.** `git add -A backend && git commit -m "feat(ingest): a registration is its own fact with a status; an application needs no number" -m "write_org_identifier ranks by tier, fills an open row when the number arrives, and reports a number another organisation holds instead of tripping the unique index." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 8: Financials, places, programmes, metrics and contacts rank too; `foreign_unspent`

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (`org_financials`: `foreign_unspent` after `archive_url`, before `*_TIER`)
- Modify: `backend/app/ingest/research_records.py` (`OrgFinancialsFinding`), `backend/app/ingest/records.py` (`OrgFinancialsRecord`)
- Modify: `backend/app/ingest/writer.py`. Change `ORG_FINANCIALS_*`, `ORG_LOCATION_*`, `write_org_financials`, `write_org_location`, `write_program`, `write_metric` and `write_contact`.
- Modify: `backend/app/ingest/promote.py`. Add `_tier_of`, and change `_write_programs` and the `metric`, `contact`, `org_financials` and `org_location` branches.
- Modify: `backend/app/ingest/brief.py` (the `org_financials` headline), `backend/app/ingest/tools/catalog_tools.py` (the org financials section)
- Modify: `backend/tests/test_cso_evidence.py`
- Create: `backend/tests/test_cso_promote_integration.py`

**Interfaces:**
- **Produces:**
  - `ORG_FINANCIALS_VALUES = ("total_income", "program_spend", "non_program_spend", "foreign_contribution", "foreign_unspent", "is_audited", "notes")`;
  - `ORG_LOCATION_VALUES = ("role", "note")`;
  - `write_org_financials(conn, rec, org_id, document_id) -> tuple[str, dict, list[Conflict]]`;
  - `write_org_location(conn, rec, org_id, *, location_id, document_id) -> tuple[str, dict, list[Conflict]]`;
  - `write_program`, `write_metric` and `write_contact` each gain a keyword `conflicts: list[Conflict] | None = None`. Their return shapes are unchanged. The ranked path runs only when `owner.column == "org_id"` and `rec.source_type` is set;
  - `promote._tier_of(f) -> Tier | None`.
- **Removes:** `ORG_FINANCIALS_UPDATABLE` and `ORG_LOCATION_UPDATABLE`, replaced by the `*_VALUES` tuples and `RANKED_PROVENANCE`.

- [ ] **Step 0: Find every caller of what this task changes.** Run `grep -rn "ORG_FINANCIALS_UPDATABLE\|ORG_LOCATION_UPDATABLE\|write_org_financials\|write_org_location\|write_program(\|write_metric(\|write_contact(" backend/app backend/tests`.
  - On master the only callers are `promote.py` and `writer.py`.
  - Any other caller, including one #99 added, is updated in this task to the new 3-tuple returns. A test that imports a deleted `*_UPDATABLE` tuple switches to the matching `*_VALUES` tuple.
- [ ] **Step 1: Failing tests** (append to `test_cso_evidence.py`):
  ```python
  from app.ingest.writer import Owner, write_contact, write_org_financials  # noqa: E402


  class TestTheFactWritersRank:
      def test_foreign_unspent_is_a_research_field(self):
          from app.ingest.expectations import expected_fields

          assert "foreign_unspent" in {f.name for f in expected_fields("org_financials")}

      async def test_an_aggregator_income_never_replaces_the_audited_one(self, recording_conn):
          from app.ingest.records import OrgFinancialsRecord

          audited = {"total_income": 5_000_000, "program_spend": None, "non_program_spend": None,
                     "foreign_contribution": None, "foreign_unspent": None, "is_audited": True, "notes": None,
                     "source_type": "org_document", "source_url": "https://ngo.example/audit.pdf"}
          conn = recording_conn([audited])
          rec = OrgFinancialsRecord(entity_name="Gramya Vikash Trust", fiscal_year="FY2023-24",
                                    total_income=6_200_000.0, source_type="aggregator", evidence_tier="claimed",
                                    **prov(source_url="https://aggregator.example/gvt"))
          status, _, conflicts = await write_org_financials(conn, rec, 9, None)
          assert status == "matched" and conflicts[0].column == "total_income"

      async def test_a_funder_contact_is_never_ranked(self, recording_conn):
          from app.ingest.records import ContactRecord

          conn = recording_conn([None])
          rec = ContactRecord(entity_name="Acme Foundation", name="CSR Head", role="Head", **prov())
          await write_contact(conn, rec, Owner.funder(1), document_id=None)
          assert "source_type" not in conn.sql[0] and "source_type" not in conn.sql[1]

      async def test_an_org_contact_is_ranked(self, recording_conn):
          from app.ingest.records import ContactRecord

          conn = recording_conn([None])
          rec = ContactRecord(entity_name="Gramya Vikash Trust", name="A. Das", role="Trustee",
                              contact_kind="office_bearer", source_type="org_document", evidence_tier="claimed",
                              **prov())
          sink = []
          await write_contact(conn, rec, Owner.org(9), document_id=None, conflicts=sink)
          assert "source_type" in conn.sql[0] and "source_type, evidence" in conn.sql[1]

      def test_an_org_finding_on_a_shared_table_without_a_tier_is_held(self):
          from app.ingest.promote import _tier_of

          bare = finding("metric", name="Households", value=10)
          assert _tier_of(bare) is None
          assert _tier_of(finding("metric", name="Households", value=10, **TIER)) == ("org_document", "evidenced")
  ```
  Create `backend/tests/test_cso_promote_integration.py`:
  ```python
  """Two promotions of one CSO against the scratch DB: the audited figure survives the aggregator's."""

  from __future__ import annotations

  import os
  from datetime import UTC, datetime
  from uuid import uuid4

  import psycopg
  import pytest
  from psycopg.rows import dict_row

  from app.ingest.promote import promote

  DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
  pytestmark = pytest.mark.integration
  NOW = datetime(2026, 10, 7, tzinfo=UTC)


  def _row(name, findings):
      return {"id": -1, "slug": f"cso-{uuid4().hex[:8]}", "entity_name": name, "canonical_name": None,
              "entity_kind": "org", "researched_at": NOW, "schema_version": 2, "website": None,
              "findings": findings}


  def _f(concept, source_type, evidence_tier, url, **kw):
      return {"concept": concept, "source_type": source_type, "evidence_tier": evidence_tier, "source_url": url,
              "evidence": "The statement for the year ended 31 March 2024 states this figure.",
              "confidence": "high", **kw}


  async def test_an_aggregator_income_never_replaces_the_audited_one():
      try:
          conn = await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row, connect_timeout=3)
      except psycopg.OperationalError:
          pytest.skip("compose Postgres not reachable")
      name = f"Gramya Vikash Trust {uuid4().hex[:6]}"
      audit = "https://ngo.example/audit-2023-24.pdf"
      listing = "https://aggregator.example/gvt"
      async with conn, conn.transaction(force_rollback=True):
          first = await promote(conn, _row(name, [
              _f("org_identity", "org_document", "evidenced", audit, name=name),
              _f("org_financials", "org_document", "evidenced", audit, fiscal_year="FY2023-24",
                 total_income={"value": 50, "unit": "lakh", "text": "Rs 50 lakh"}, is_audited=True),
          ]))
          org_id = first["entity"]["id"]
          second = await promote(conn, _row(name, [
              _f("org_identity", "aggregator", "claimed", listing, name=name, staff_count=45),
              _f("org_financials", "aggregator", "claimed", listing, fiscal_year="FY2023-24",
                 total_income={"value": 62, "unit": "lakh", "text": "Rs 62 lakh"},
                 foreign_unspent={"value": 1, "unit": "lakh", "text": "Rs 1 lakh"}),
          ]))
          row = await (await conn.execute(
              "SELECT total_income, foreign_unspent, source_type, evidence, source_url FROM org_financials "
              "WHERE org_id = %s AND fiscal_year = 'FY2023-24'", (org_id,))).fetchone()
          assert float(row["total_income"]) == 5_000_000
          assert float(row["foreign_unspent"]) == 100_000          # a blank: filled by the weaker source
          assert (row["source_type"], row["evidence"], row["source_url"]) == ("org_document", "evidenced", audit)
          assert any("total_income" in c and listing in c and audit in c for c in second["conflicts"])
  ```
  Run `bt tests/test_cso_evidence.py -q` → failures.
- [ ] **Step 2: `foreign_unspent`.**
  - **Catalog.** Add `Column("foreign_unspent", "numeric", note="INR: foreign contribution left unutilised at year end, from the FCRA return (FC-4)"),` to `org_financials`, before `*_TIER`. Also add to its `notes` column `note="audit anomalies quoted verbatim"`.
  - **Finding.** In `OrgFinancialsFinding`, after `foreign_contribution`:
    ```python
        foreign_unspent: Money | None = Field(
            default=None, description="foreign contribution unutilised at year end, from the FCRA return"
        )
    ```
    Change the `notes` description to `"quote any inconsistency the audit itself shows, verbatim"`.
  - **Record.** In `OrgFinancialsRecord`, add `foreign_unspent: float | None = None` after `foreign_contribution`.
- [ ] **Step 3: The org fact writers.** Replace `ORG_FINANCIALS_UPDATABLE`, `ORG_LOCATION_UPDATABLE`, `write_org_financials` and `write_org_location` with:
  ```python
  ORG_FINANCIALS_VALUES = ("total_income", "program_spend", "non_program_spend", "foreign_contribution",
                           "foreign_unspent", "is_audited", "notes")
  ORG_LOCATION_VALUES = ("role", "note")


  async def write_org_financials(
      conn: Any, rec: OrgFinancialsRecord, org_id: int, document_id: int | None
  ) -> tuple[str, dict, list[Conflict]]:
      """One fiscal year on UNIQUE (org_id, fiscal_year), ranked by tier. An aggregator's income never
      replaces the audited figure; it is reported beside it."""
      return await _upsert_ranked(
          conn, "org_financials", {"org_id": org_id, "fiscal_year": rec.fiscal_year}, ORG_FINANCIALS_VALUES,
          {c: getattr(rec, c) for c in ORG_FINANCIALS_VALUES},
          {c: getattr(rec, c) for c in RANKED_PROVENANCE}, Tier(rec.source_type, rec.evidence_tier),
          document_id, row=f"[org:{org_id}] {rec.fiscal_year}",
      )


  async def write_org_location(
      conn: Any, rec: OrgLocationRecord, org_id: int, *, location_id: int, document_id: int | None
  ) -> tuple[str, dict, list[Conflict]]:
      return await _upsert_ranked(
          conn, "org_locations", {"org_id": org_id, "location_id": location_id}, ORG_LOCATION_VALUES,
          {"role": rec.role, "note": rec.note}, {c: getattr(rec, c) for c in RANKED_PROVENANCE},
          Tier(rec.source_type, rec.evidence_tier), document_id, row=f"[org:{org_id}] location {location_id}",
      )
  ```
  In `write_program`, `write_metric` and `write_contact`, add `conflicts: list[Conflict] | None = None` to the keyword arguments. Just before each function's `_upsert` call, insert the ranked branch. For `write_contact`:
  ```python
      if owner.column == "org_id" and rec.source_type is not None:
          provenance_cols = (*RANKED_PROVENANCE, "content_hash", "extractor_version")
          values = tuple(c for c in CONTACT_UPDATABLE if c not in provenance_cols)
          status, changes, found = await _upsert_ranked(
              conn, "contacts", key, values, proposed, {c: proposed[c] for c in provenance_cols},
              Tier(rec.source_type, rec.evidence_tier), document_id, row=f"[org:{owner.id}] {rec.name}",
          )
          if conflicts is not None:
              conflicts.extend(found)
          return status, changes
  ```
  - **`write_metric`.** Use the same block with `"metrics"`, `METRIC_UPDATABLE`, `provenance_cols = RANKED_PROVENANCE`, and `row=f"[org:{owner.id}] {rec.name} {rec.period or ''}".strip()`.
  - **`write_program`.** Use the same block with `"programs"`, `PROGRAM_UPDATABLE` and `provenance_cols = (*RANKED_PROVENANCE, "content_hash", "extractor_version")`. Assign `status, changes, found = …`, extend `conflicts`, and then fall through to the existing `SELECT id FROM programs …` lookup and its return. Do not return early.
  - **Proposed dicts.** Each function's `proposed` dict already holds every provenance column it lists. Check that `metrics` has no `content_hash` column in the catalog: it does not, so `RANKED_PROVENANCE` alone is right.
- [ ] **Step 4: Promote.**
  - Add after `_provenance`:
  ```python
  def _tier_of(f: Any) -> Tier | None:
      """The finding's evidence tier, or None when it has none (a funder's, or one saved before tiers)."""
      source, evidence = getattr(f, "source_type", None), getattr(f, "evidence_tier", None)
      return Tier(source, evidence) if source and evidence else None
  ```
  - In `_write_facts`, at the top of the per-finding body (after `seen.add(identity)`), add:
  ```python
              if owner.column == "org_id" and concept in ("metric", "contact") and _tier_of(f) is None:
                  report["held"].append(
                      f"{concept} {_describe(concept, f)}: an organisation's finding needs source_type and "
                      f"evidence_tier. It stays on the research row; re-research it to promote it."
                  )
                  continue
  ```
  - In `_write_programs`, do the same before building the record. Use `if owner.column == "org_id" and _tier_of(f) is None:`, report `programme {f.name!r}: …` with the same wording, then `continue`. Then pass `conflicts=conflicts` and collect them:
    - declare `conflicts: list[Conflict] = []` in `_write_programs`, and after its loop add `report["conflicts"].extend(c.describe() for c in conflicts)`;
    - in `_write_facts`, pass `conflicts=conflicts` to `write_metric` and `write_contact`;
    - unpack the org writers as `status, _, found = await write_org_financials(...)` and `status, _, found = await write_org_location(...)`, then `conflicts.extend(found)`;
    - add `foreign_unspent=f.foreign_unspent.inr if f.foreign_unspent else None,` to the `OrgFinancialsRecord(...)` call.
- [ ] **Step 5: Brief and dossier.**
  - **`brief.py`.** In the `org_financials` branch, add `"foreign_unspent"` to the tuple of money keys and append `_tier(f)` to the `_join(...)` arguments. In the `org_identity` branch, append `f.get("website"), f"staff {f['staff_count']}" if f.get("staff_count") is not None else None, _tier(f)`.
  - **`catalog_tools.py`.** Change the org financials section SQL to `SELECT fiscal_year, total_income, program_spend, non_program_spend, foreign_contribution, foreign_unspent, is_audited, source_type, evidence FROM org_financials WHERE org_id = %s ORDER BY fiscal_year`.
- [ ] **Step 6: Run.**
  - `bt tests/test_cso_evidence.py tests/test_ingest.py -q` → pass.
  - Full unit tier → 0 failed. #99's funder tests are untouched, because the funder path never reaches `_upsert_ranked`.
  - `bti tests/test_cso_promote_integration.py -q` → `1 passed`.
  - `ruff check .` → clean.
- [ ] **Step 7: Commit.** `git add -A backend && git commit -m "feat(ingest): CSO financials, places, programmes, metrics and contacts rank by evidence tier; foreign_unspent" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 9: Seed writes `source_type = 'seed'` and names the partial index

**Files:**
- Modify: `seed/seed.py`. Change `_upsert_org_identifiers` (line 141), `_upsert_org_location` (line 171), `_upsert_contact` (line 182), and the two `INSERT INTO orgs` statements (lines 209 and 268).
- Modify: `seed/graph_seed.py` (the identifier `string_agg`, line 74)
- Create: append to `backend/tests/test_cso_evidence.py`

- [ ] **Step 1: Failing test** (append):
  ```python
  from pathlib import Path  # noqa: E402

  SEED = Path(__file__).resolve().parents[2] / "seed" / "seed.py"


  def test_the_seed_names_the_partial_index():
      """0033 dropped the (id_type, id_value) primary key; ON CONFLICT must name the partial index's predicate."""
      text = SEED.read_text(encoding="utf-8")
      assert "ON CONFLICT (id_type, id_value) WHERE id_value IS NOT NULL DO NOTHING" in text
      assert "ON CONFLICT (id_type, id_value) DO NOTHING" not in text


  def test_the_seed_labels_what_it_writes():
      text = SEED.read_text(encoding="utf-8")
      assert text.count("'seed', 'claimed'") >= 4          # orgs twice, identifiers, locations
      assert "SEED_TIER" in text                           # contacts: org rows only
  ```
  `bt tests/test_cso_evidence.py -q -k seed` → 2 failed.
- [ ] **Step 2: Seed.** In `seed/seed.py`:
  - **`_upsert_org_identifiers`.**
    ```sql
                INSERT INTO org_identifiers (org_id, id_type, id_value, verified, source_url, status,
                                             source_type, evidence)
                VALUES (%s, %s, %s, true, %s, 'registered', 'seed', 'claimed')
                ON CONFLICT (id_type, id_value) WHERE id_value IS NOT NULL DO NOTHING
    ```
  - **`_upsert_org_location`.** `INSERT INTO org_locations (org_id, location_id, role, source_type, evidence) VALUES (%s, %s, %s, 'seed', 'claimed')`. Keep its `ON CONFLICT … DO UPDATE SET role = EXCLUDED.role`.
  - **Both `INSERT INTO orgs`.** Add `source_type, evidence` to the column list, `'seed', 'claimed'` to the VALUES (literals, before the `RETURNING`), and `source_type = EXCLUDED.source_type, evidence = EXCLUDED.evidence` to each `DO UPDATE SET`.
  - **`_upsert_contact`.**
    - Add a module constant `SEED_TIER = ("seed", "claimed")  # org rows only: funders' rows carry no tier`.
    - Add `source_type, evidence` to its INSERT column list and two `%s` to VALUES.
    - Pass `*(SEED_TIER if org_id is not None else (None, None))` after `source_url` in the params tuple.
- [ ] **Step 3: `graph_seed.py`.** Replace the `string_agg` line with:
  ```sql
                SELECT string_agg(upper(oi.id_type) || ' ' || oi.id_value
                                  || CASE WHEN oi.status <> 'registered' THEN ' (' || oi.status || ')' ELSE '' END,
                                  ', ') AS ids
                FROM org_identifiers oi WHERE oi.org_id = o.id AND oi.id_value IS NOT NULL
  ```
- [ ] **Step 4: Run.**
  - `bt tests/test_cso_evidence.py -q -k seed` → 2 passed.
  - `seed_cso` → exits 0 on the already-seeded scratch DB, which is idempotent, and prints its usual counts with no `ON CONFLICT` error.
  - `psql_cso -tc "select source_type, count(*) from orgs group by 1 order by 1"` → shows a `seed` row whose count equals the seeded orgs. `psql_cso -tc "select count(*) from org_identifiers where verified and source_type is distinct from 'seed'"` → `0`.
- [ ] **Step 5: Commit.** `git add seed/seed.py seed/graph_seed.py backend/tests/test_cso_evidence.py && git commit -m "feat(seed): the seed labels its rows source_type 'seed' and upserts on the partial index" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 10: Org API — the new identity fields and identifier statuses

**Files:**
- Modify: `backend/app/repositories/orgs.py` (`LIST_SQL` darpan join; `get_org` darpan join and identifiers query)
- Modify: `backend/app/schemas/orgs.py` (`IdentifierOut`, `OrgDetail`)
- Modify: `backend/tests/test_orgs.py`

**Interfaces:**
- **`IdentifierOut`** gains:
  - `id: int | None = None`;
  - `id_value: str | None`;
  - `status: str = "registered"`;
  - `valid_from: date | None`, `valid_until: date | None`;
  - `application_ref: str | None`, `check_method: str | None`;
  - `is_current: bool = True`;
  - `source_type: str | None`, `evidence: str | None`.

  It keeps `verified` for the legacy shape. #99 left `IdentifierOut` used by orgs only.
- **`OrgDetail`** gains `website`, `description`, `aliases: list[str] = []`, `staff_count: int | None`, `staff_count_note`, `source_type` and `evidence`.

- [ ] **Step 1: Failing test** (append to `backend/tests/test_orgs.py`):
  ```python
  async def test_detail_carries_identity_and_identifier_status(client_for, monkeypatch):
      async def fake_get(pool, slug_or_id):
          return {
              **ROW, "org_kind": "cso", "legal_form": "Public Charitable Trust", "registration_date": None,
              "contact": {}, "profile": {}, "website": "https://theant.org", "description": "Works in Chirang.",
              "aliases": ["The ANT"], "staff_count": 20, "staff_count_note": "20+ (team page)",
              "source_type": "org_document", "evidence": "claimed", "tags": [], "locations": [], "contacts": [],
              "identifiers": [
                  {"id": 1, "id_type": "12a", "id_value": None, "status": "applied", "application_ref": "ACK-1",
                   "valid_from": None, "valid_until": None, "check_method": "document", "verified": False,
                   "is_current": True, "source_type": "org_document", "evidence": "evidenced",
                   "source_url": "https://theant.org/10ab.pdf"},
              ],
          }

      monkeypatch.setattr("app.api.routes.orgs.repo.get_org", fake_get)
      async with client_for(orgs_api.router) as client:
          body = (await client.get("/api/orgs/the-ant")).json()
      assert (body["website"], body["aliases"], body["staff_count"]) == ("https://theant.org", ["The ANT"], 20)
      ident = body["identifiers"][0]
      assert (ident["id_value"], ident["status"], ident["application_ref"]) == (None, "applied", "ACK-1")


  def test_one_darpan_row_per_org_in_the_list():
      """An org may hold an open and a numbered row of one type; a plain join would list it twice and
      corrupt COUNT(*) OVER ()."""
      from app.repositories.orgs import LIST_SQL

      assert "LEFT JOIN LATERAL" in LIST_SQL and "id_value IS NOT NULL" in LIST_SQL and "LIMIT 1" in LIST_SQL
  ```
  `bt tests/test_orgs.py -q` → failures.
- [ ] **Step 2: Repository.** In both `LIST_SQL` and `get_org`, replace `LEFT JOIN org_identifiers di ON di.org_id = o.id AND di.id_type = 'darpan'` with:
  ```sql
  LEFT JOIN LATERAL (
    SELECT id_value FROM org_identifiers
    WHERE org_id = o.id AND id_type = 'darpan' AND id_value IS NOT NULL
    ORDER BY is_current DESC, id LIMIT 1
  ) di ON true
  ```
  Change the identifiers query to:
  ```python
                  "SELECT id, id_type, id_value, status, valid_from, valid_until, application_ref, "
                  "check_method, verified, is_current, source_type, evidence, source_url "
                  "FROM org_identifiers WHERE org_id = %s "
                  "ORDER BY id_type, is_current DESC, (id_value IS NULL), id",
  ```
- [ ] **Step 3: Schemas.** In `schemas/orgs.py`, import `date` (already imported), then:
  ```python
  class IdentifierOut(ReadModel):
      id: int | None = None
      id_type: str
      id_value: str | None = None       # NULL while only applied for
      status: str = "registered"
      valid_from: date | None = None
      valid_until: date | None = None
      application_ref: str | None = None
      check_method: str | None = None
      verified: bool = False            # legacy; status is the field to read
      is_current: bool = True
      source_type: str | None = None
      evidence: str | None = None
      source_url: str | None = None
  ```
  In `OrgDetail`, add:
  ```python
      website: str | None = None
      description: str | None = None
      aliases: list[str] = []
      staff_count: int | None = None
      staff_count_note: str | None = None
      source_type: str | None = None
      evidence: str | None = None
  ```
- [ ] **Step 4: Run.** `bt tests/test_orgs.py -q` → pass. `test_list_is_legacy_array_shape` is unchanged, because the list items gain nothing. Full unit tier → 0 failed. `ruff check .` → clean.
- [ ] **Step 5: Commit.** `git add -A backend && git commit -m "feat(api): org detail returns website, aliases, staff and each registration's status" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 11: The Diligence tab shows status, not "Verified"

**Files:**
- Create: `frontend/features/registry/identifierStatus.ts`
- Modify: `frontend/lib/api/types.ts` (`Identifier`, `OrgDetail`)
- Modify: `frontend/features/registry/ProfileTabs.tsx` (lines 50-102)
- Modify: `frontend/app/registry/[slug]/page.tsx` (lines 28 and 52-60)
- Create: append to `backend/tests/test_cso_evidence.py` (a parity test reading the TS file)

**Interfaces:**
- **Produces:**
  - `STATUS_LABELS: Record<string, string>`;
  - `pickIdentifier(ids: Identifier[], idType: string): Identifier | undefined`, which prefers a current numbered row, then any row;
  - `statusLabel(id: Identifier | undefined): string`, which appends " (claimed)" when `evidence === "claimed"`;
  - `statusTone(id: Identifier | undefined): "good" | "pending" | "bad" | "none"`;
  - `isOnFile(id: Identifier | undefined): boolean`, true only for `registered` or `provisional`.

- [ ] **Step 1: Failing tests** (append to `test_cso_evidence.py`):
  ```python
  FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


  def test_status_labels_cover_every_status():
      import re

      from app.ingest.records import IDENTIFIER_STATUSES

      text = (FRONTEND / "features" / "registry" / "identifierStatus.ts").read_text(encoding="utf-8")
      labelled = set(re.findall(r"^\s+(\w+): \"", text, flags=re.M))
      assert labelled == set(IDENTIFIER_STATUSES)


  def test_the_diligence_tab_no_longer_calls_everything_verified():
      tabs = (FRONTEND / "features" / "registry" / "ProfileTabs.tsx").read_text(encoding="utf-8")
      page = (FRONTEND / "app" / "registry" / "[slug]" / "page.tsx").read_text(encoding="utf-8")
      assert '"Verified"' not in tabs and "statusLabel(" in tabs and "org.website" in tabs
      assert '"on file"' not in page and "isOnFile(" in page
  ```
  `bt tests/test_cso_evidence.py -q -k "status_labels or diligence"` → 2 failed.
- [ ] **Step 2: Types.** In `frontend/lib/api/types.ts`:
  ```ts
  export type Identifier = {
    id?: number; id_type: string; id_value: string | null; status: string;
    valid_from: string | null; valid_until: string | null; application_ref: string | null;
    check_method: string | null; verified: boolean; is_current: boolean;
    source_type: string | null; evidence: string | null; source_url: string | null;
  };
  ```
  and extend `OrgDetail` with `website: string | null; description: string | null; aliases: string[]; staff_count: number | null; staff_count_note: string | null; source_type: string | null; evidence: string | null;`.

  `id_value` becomes `string | null` and `status` becomes required, so this **narrows** the type, and every reader has to cope.
  - Run `grep -rn "id_value\|: Identifier\|Identifier\[\]" frontend/app frontend/features frontend/lib frontend/components`.
  - On master the only reader of `id_value` is `ProfileTabs.tsx:96`, which Step 4 rewrites.
  - If #99 left `FunderDetail.identifiers: Identifier[]`, give the funder side its own `FunderIdentifier = { id_type: string; id_value: string; verified: boolean; source_url: string | null }` and point `FunderDetail` at it. Do not widen `Identifier` back.
- [ ] **Step 3: The status module.** Create `frontend/features/registry/identifierStatus.ts`:
  ```ts
  import type { Identifier } from "@/lib/api";

  /* One label per org_identifiers.status (0033). A test holds these keys to the SQL CHECK list. */
  export const STATUS_LABELS: Record<string, string> = {
    applied: "Applied",
    provisional: "Provisional",
    registered: "Registered",
    expired: "Expired",
    suspended: "Suspended",
    cancelled: "Cancelled",
    surrendered: "Surrendered",
    not_available: "Not available",
    not_found: "Not found",
    check_blocked: "Check blocked",
  };

  export function pickIdentifier(ids: Identifier[], idType: string): Identifier | undefined {
    const ofType = ids.filter((i) => i.id_type === idType);
    return ofType.find((i) => i.is_current && i.id_value) ?? ofType[0];
  }

  /* "Check blocked" never means valid, and a claimed status says so on its face. */
  export function statusLabel(id: Identifier | undefined): string {
    if (!id) return "Not entered";
    const base = STATUS_LABELS[id.status] ?? id.status;
    return id.evidence === "claimed" ? `${base} (claimed)` : base;
  }

  export function statusTone(id: Identifier | undefined): "good" | "pending" | "bad" | "none" {
    if (!id) return "none";
    if (id.status === "registered" || id.status === "provisional") return "good";
    if (id.status === "applied" || id.status === "check_blocked") return "pending";
    return "bad";
  }

  export function isOnFile(id: Identifier | undefined): boolean {
    return !!id && (id.status === "registered" || id.status === "provisional");
  }
  ```
- [ ] **Step 4: `ProfileTabs.tsx`.**
  - Import `{ isOnFile, pickIdentifier, statusLabel, statusTone }` from `./identifierStatus`.
  - Add `const TONE_COLOR = { good: "var(--color-accent-2-600)", pending: "var(--color-accent-600)", bad: "var(--color-danger-600, #b42318)", none: "var(--color-neutral-400)" } as const;`.
  - In `completenessParts`, replace `org.identifiers.length > 0` with `org.identifiers.some((i) => isOnFile(i))`.
  - Replace the Credentials card's map body with:
  ```tsx
              {EXPECTED_IDS.map((idType) => {
                const found = pickIdentifier(org.identifiers, idType);
                const value = found?.id_value ?? (found?.application_ref ? `application ${found.application_ref}` : null);
                return (
                  <div key={idType} className="card" style={{ padding: 14, gap: 4 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-xs)", fontWeight: 600 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: TONE_COLOR[statusTone(found)] }} />
                      {statusLabel(found)}
                      <span className="muted-2" style={{ marginLeft: "auto" }}>{ID_LABELS[idType]}</span>
                    </div>
                    <div style={{ fontSize: "var(--fs-sm)", fontWeight: 600, fontStyle: value ? "normal" : "italic", color: value ? "var(--color-text)" : "var(--color-neutral-500)" }}>
                      {value ?? "— not in base"}
                    </div>
                    {found?.valid_until && (
                      <div className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>valid until {fmtDate(found.valid_until)}</div>
                    )}
                  </div>
                );
              })}
  ```
  - Insert a new card before "Credentials":
  ```tsx
            <SectionCard kicker="Identity" title={org.website ? org.website.replace(/^https?:\/\/(www\.)?/, "") : "No website on record"}>
              {org.website && <a href={org.website} target="_blank" rel="noreferrer" className="card-body">{org.website}</a>}
              {org.description && <div className="card-body">{org.description}</div>}
              {org.aliases.length > 0 && <div className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>Also known as: {org.aliases.join(" · ")}</div>}
              {org.staff_count != null && (
                <div className="muted-2" style={{ fontSize: "var(--fs-xs)" }}>Staff: {org.staff_count}{org.staff_count_note ? ` — ${org.staff_count_note}` : ""}</div>
              )}
            </SectionCard>
  ```
  - Change the coverage caption from "Share of profile sections with verified data in the base" to "Share of profile sections with data in the base".
- [ ] **Step 5: `page.tsx`.**
  - Import `{ isOnFile, pickIdentifier, statusLabel }` from `@/features/registry/identifierStatus`.
  - Set `const isFull = org.identifiers.filter((i) => isOnFile(i)).length >= 4;`.
  - Replace the chips' `map` body with:
    ```tsx
              {["fcra", "80g", "12a", "csr1"].map((idType) => {
                const found = pickIdentifier(org.identifiers, idType);
                return (
                  <Tag key={idType} tone="ondark">
                    {`${idType.toUpperCase()} — ${statusLabel(found).toLowerCase()}`}
                  </Tag>
                );
              })}
    ```
    The chip then reads "FCRA — check blocked", "12A — applied (claimed)" or "80G — not entered". `isOnFile` is used only for `isFull`.
- [ ] **Step 6: Run.**
  - `bt tests/test_cso_evidence.py -q -k "status_labels or diligence"` → 2 passed.
  - `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit && npm run lint` → exit 0.
  - `npx next build` → compiles and type-checks. CLAUDE.md says some type errors surface only here.
    - The build may then fail to prerender a page that fetches from `AGENT_URL`, because no backend is reachable from the worktree. That failure is environmental: report it and move on.
    - Any `Type error:` or `Failed to compile` line is real, and blocks the task.
- [ ] **Step 7: Commit.** `git add -A frontend backend/tests/test_cso_evidence.py && git commit -m "feat(registry): the Diligence tab shows each registration's status, website, aliases and staff" -m "No identifier is labelled Verified any more: Registered, Applied, Check blocked and Not found say what is known, and a claimed status says so." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 12: Prompts, instructions, skills and docs say what changed; counts

**Files:**
- Modify: `backend/app/ingest/prompts/entity_researcher.md` (the `## What to extract — an org` section, around lines 101-110)
- Modify: `backend/app/ingest/instructions.md` (the "An NGO promotes too" paragraph, around lines 160-166)
- Modify: `backend/app/ingest/skills/catalog-mapping/SKILL.md` (the precedence paragraph, around lines 20-24)
- Modify: `backend/app/ingest/skills/catalog-write-report/SKILL.md`
- Modify: `backend/app/ingest/expectations.py` (docstring table count)
- Modify: `docs/DATA_PLATFORM.md` (lines 24, 41, 53, 103, 233), `docs/INGEST.md` (lines 236, 343-344), `docs/SQL_AGENT.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Researcher prompt.**
  - In `entity_researcher.md`, replace items 1 and 2 of the org section with:
  ```markdown
  Every org finding — and an org's programmes, metrics and contacts — carries **`source_type`** and **`evidence_tier`**. `source_type` is the kind of source: `registry` (a government registry page you read directly), `org_document` (the CSO's own document or site), `funder` (a funder's page or a CSR filing naming the CSO), `staff_dataset`, `prior_research` (the team's earlier dossier, before its cited link is re-read), `aggregator`. `evidence_tier` is `evidenced` only when the document itself states the fact — a certificate, an audited statement, a dated return; a sentence on a web page is `claimed`, and `aggregator` and `prior_research` are always `claimed`. The writer ranks on these: a weaker source never overwrites a stronger one, and a disagreement is reported, not resolved.

  1. **org_identity** — name, `org_kind` (`cso`, `intermediary`, `government`), legal form as printed (free text), registration date, **website**, a short **description** in its own words, **aliases** (every other spelling a source used — never another organisation's name), and **staff_count** with **staff_count_note** saying what was counted and where. Two pages giving different counts are two findings, each with its source.
  2. **org_identifiers** — **12A, 80G, FCRA**, PAN, Darpan, CIN, registration number, each with a **status**: `registered`, `applied` (a Form 10AB acknowledgement: put its number in `application_ref`; `id_value` stays empty), `expired`, `cancelled`, `suspended`, `not_found` (a working source did not list it), `check_blocked` (the registry could not be read — **never** treat that as valid). Add `valid_until` when an approval states one. **Never guess an identifier.**
  ```
  - Add to item 3: "and **foreign contribution left unspent** at year end (`foreign_unspent`), from the FCRA return. Quote any inconsistency in the audit verbatim in `notes`."
  - Change the rule line "overwrite stronger evidence with weaker" in **Never:** to "record a weaker source's value as if it settled a stronger one's".
- [ ] **Step 2: Instructions.** In `instructions.md`, replace "One rule differs and is worth repeating … every difference is reported instead." with:
  ```markdown
  Every organisation fact carries an evidence tier, and promotion ranks on it: registry = manual check > the
  CSO's own document > a funder's > a staff dataset > prior research > an aggregator > the seed. A blank is
  always filled; a stronger source replaces a weaker one; anything else that differs is kept as stored and
  reported under **conflicts**, both values and both sources. A row entered by a person has no tier and is
  never overwritten. Report conflicts to the user word for word, beside what was held back.
  ```
- [ ] **Step 3: Skills.**
  - **`catalog-mapping/SKILL.md`.** Replace the precedence sentence "The precedence is: evidenced beats claimed; … A newer claim does not beat an older certificate." with: "The precedence is the writer's, by source type: registry = manual check > the organisation's own document > a funder's > a staff dataset > prior research > an aggregator > the seed. Equal sources that disagree are a conflict, never a choice; within one source type, more recent beats older only when a person decides it. A newer claim does not beat an older certificate."
  - **`catalog-write-report/SKILL.md`.** After the held-back rules, add a bullet: "- **Conflicts are reported like held-back rows**: verbatim, from `conflicts`, each naming both values and both sources. Never fold one into a total or say which is right."
- [ ] **Step 4: Recount and fix the wording.**
  ```bash
  source /Users/vinod/GitHub/cso-env.sh && bpy "
  import glob, re
  from app.agent.tools.sql import catalog as c
  mig = set()
  for f in glob.glob('/w/db/migrations/*.sql'):
      mig |= set(re.findall(r'CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)', open(f).read()))
  mig -= {'credential_events'}
  print(len(c.CATALOG), len(set(c.CATALOG) & mig), len(c.PROVENANCE_COLUMNS))"
  ```
  Expected: two fewer catalog tables than #99 left (its Task 17 recorded 36, so **34**), one fewer from migrations (**8**), and two fewer with provenance (**19**). Use the numbers printed, not these, if the base differs. Write them in:
  - the `expectations.py` docstring ("the schema as data — N tables");
  - `CLAUDE.md` ("N of the SQL catalog's M tables arrive in `db/migrations/`" and "**allowlist, as data** — M tables"), and append to the migrations paragraph: "`0033_cso_consolidation` adds the evidence tier to the seven CSO tables, re-keys `org_identifiers` with a status, and drops `credential_events` and `program_locations`.";
  - `docs/SQL_AGENT.md` (the table count line, removing the two tables from its list);
  - `README.md` (the two table counts).
- [ ] **Step 5: Platform and ingest docs.**
  - **`docs/DATA_PLATFORM.md`:**
    - line 24: credentials row → "a number in `org_identifiers`, with its **status** on the same row (`applied`, `registered`, `check_blocked`…) since 0033; `credential_events` was folded in and dropped";
    - line 41: add `id` (surrogate key), `status`, `valid_from`, `valid_until`, `check_method`, `application_ref`, `checked_at`, `checked_by`, `evidence_document_id` (0033);
    - line 53: drop `program_locations`;
    - line 103: replace the Credentials row with "`org_identifiers.status` (0033): one row per registration, which may have no number yet";
    - line 233: append "— folded into `org_identifiers` and dropped in 0033";
    - add a short "Evidence tiers (0033)" subsection quoting the precedence order, the NULL = unranked rule, and the row-level-tier limitation.
  - **`docs/INGEST.md`:**
    - line 236 → "`org_identifiers`, one row per registration with its status; an application has no number";
    - lines 343-344 → "Website and identifier notes have columns since 0033. Every org fact carries an evidence tier and is ranked by `_may_overwrite`; disagreements are reported under `conflicts`.";
    - delete the remaining `credential_events` sentence.
- [ ] **Step 6: Run.** `bt -m "'not integration'" -q` → 0 failed. That includes `test_no_module_names_a_table_0033_dropped` and the test that every Import tool is named in `instructions.md`. Then run `git grep -n "credential_events\|program_locations" -- backend docs CLAUDE.md README.md`. The only hits allowed are in `docs/features/` (dated history) and the `DATA_PLATFORM.md` lines that now say "dropped in 0033".
- [ ] **Step 7: Commit.** `git add -A backend docs CLAUDE.md README.md && git commit -m "docs: evidence tiers, registration status and the 0033 drops in prompts, skills and platform docs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 13: Final verification

**Files:** none change unless a check fails.

- [ ] **Step 1: Unit tier and lint.** `source /Users/vinod/GitHub/cso-env.sh && bt -m "'not integration'" -q` → 0 failed (the baseline count plus the new tests). `cd backend && ruff check .` → clean.
- [ ] **Step 2: Integration tier on `sangam_cso`.** `bti tests/test_cso_consolidation_migration.py tests/test_cso_promote_integration.py tests/test_sql_integration.py tests/test_rls.py tests/test_migration_integrity.py -m integration -q` → 0 failed. The migration's `before` tests skip, and `test_no_drift` and `test_every_live_table_is_either_catalogued_or_knowingly_excluded` pass.
- [ ] **Step 3: Boot gate.**
  ```bash
  bpy "
  import asyncio, psycopg
  from psycopg.rows import dict_row
  from app.agent.tools.sql.catalog import verify_against_db
  async def main():
      async with await psycopg.AsyncConnection.connect('host=postgres user=sangam password=sangam dbname=sangam_cso', row_factory=dict_row) as c:
          print(await verify_against_db(c))
  asyncio.run(main())"
  ```
  Expected: `[]`.
- [ ] **Step 4: Frontend.** In the worktree, `cd frontend && npx tsc --noEmit && npm run lint` → exit 0. Then `npx next build` → no `Type error:` or `Failed to compile`. A prerender fetch failure with no backend reachable is environmental (Task 11, Step 6).
- [ ] **Step 5: Smoke, after merge rather than on this branch.** `make smoke` exercises the running stack, which serves master. After this PR merges, the owner runs `make migrate` on the dev DB and then `SMOKE_SKIP_LLM=1 make smoke`. "org profile renders" must pass. Say so in the PR description.
- [ ] **Step 6: Supabase pre-flight.** This is for the person who runs `make migrate ENV=staging`. Put this in the PR description:
  ```sql
  SELECT 'credential_events' t, count(*) FROM credential_events UNION ALL
  SELECT 'credential_events (org, verified)', count(*) FROM credential_events WHERE org_id IS NOT NULL AND verified UNION ALL
  SELECT 'program_locations', count(*) FROM program_locations UNION ALL
  SELECT 'contacts entered by hand (stay unranked)', count(*) FROM contacts WHERE source_name = 'manual';
  SELECT org_id, credential, count(*) FROM credential_events WHERE org_id IS NOT NULL AND verified
  GROUP BY 1, 2 HAVING count(*) > 1;       -- history that collapses to its latest event
  ```
  - **Stops and backup.** Any `program_locations` row stops the migration by design. Take a backup, then run `make migrate ENV=staging`.
  - **Note in the PR:**
    - no table is new, so #92's grants and RLS need no change, and `org_identifiers_read` still governs the new columns;
    - rows the seed wrote become `source_type = 'seed'`, the weakest tier, so research from any other source now replaces a seeded value instead of only filling blanks. That is the spec's precedence, and it reverses the old "hand-vetted rows are filled, never overwritten" rule for seeded rows only.
- [ ] **Step 7: Clean up.** `docker exec sangam-postgres-1 dropdb -U sangam sangam_cso`; `rm /Users/vinod/GitHub/cso-env.sh`.

---

## Self-review: spec coverage

| Spec item | Task |
|---|---|
| C7 / §1: `source_type` and `evidence` on the 7 tables, with the CHECK enum (including `prior_research`, C14) | 1 (loop and CHECKs), 2 (catalog), 3 (findings and records) |
| §1 precedence order, strongest first, `prior_research` between `staff_dataset` and `aggregator` | 4 (`SOURCE_PRECEDENCE`, `test_the_order` incl. `staff_dataset`/`prior_research` both ways and `aggregator`), 12 (prompts and docs) |
| §1 weaker never overwrites, stronger replaces | 4, 5 (`write_org`), 7 (identifiers), 8 (facts and the integration test) |
| §1 `aggregator` (and `prior_research`) always `claimed` | 1 (DB CHECK), 3 (finding and record validators), 2 (catalog defect) |
| §1 conflicts: kept stored value, listed under `conflicts` with both values and sources; equals never resolved | 4 (`Conflict`, `test_equals_that_disagree_are_a_conflict`), 5 (report and tool), 7, 8 (integration asserts both URLs) |
| §2 `orgs` + `website`, `description`, `aliases`, `staff_count`, `staff_count_note` (C1) | 1, 5, 10, 11 |
| §2 `org_identifiers` surrogate key, nullable `id_value`, status and the check columns, two partial unique indexes (C3) | 1, 7 |
| §2 status meanings (`applied`, `check_blocked`, `not_found`) | 7 (catalog notes, finding validator, blocked-check rule), 11 (labels), 12 (prompt) |
| §2 `credential_events` copy (latest verified, onto status and `valid_until`), funder rows discarded, then drop (C2) | 1 |
| §2 `org_financials.foreign_unspent`; audit anomalies in `notes` (C6) | 1, 8 |
| §2 drop `program_locations` (C5, this PR's half) | 1, 2 |
| §2 `documents` new `doc_type` values | 2 (catalog note), 3 (`ORG_DOC_TYPES`, finding description) |
| §2 migration order, classification under #92 | 1 (steps 0–7; RLS test), 13 (pre-flight) |
| §3 `expectations.py`, `records.py`, `research_records.py`: identity, identifier, financials fields; every org finding carries a tier | 2 (`TIER`), 3, 5, 7, 8 |
| §3 `writer.py`: one `_may_overwrite`, used by every org writer; conflicts returned; `write_org` follows precedence | 4, 5, 7, 8 |
| §3 `promote.py`: `conflicts` beside `held` | 5, 7, 8 |
| §3 `matcher.py`: alias step between exact and trigram; North East / Northeast, "The", brackets and punctuation (C11) | 6 |
| §3 `catalog.py`: new columns, the two drops (this PR's half), aggregator defect note | 2, 5, 7, 8 |
| §3 repositories, schemas, routes: org detail returns `website`, `description`, `aliases`, `staff_count`, identifier `status` and `valid_until` | 10 |
| §3 frontend: Diligence shows status (Registered · Applied · Check blocked · Not found), not "Verified"; shows the website | 11 |
| §3 seed `source_type = 'seed'` | 1 (backfill), 9 |
| §3 tests: model-vs-table parametrisations, matcher alias tests, precedence and conflict tests, migration integration test | 2, 3, 6, 4, 1, 8 |
| §3 docs: `DATA_PLATFORM.md`, `INGEST.md` (`SKILLS.md` is (f)) | 12 |
| §2 and §3 grants → `funder_activity`, `grant_locations`, `/api/grants` view, `grants.json` | **not here: PR (e)** |
| §3 `record_registry_check`, `ngos.json` aggregators, `manual_aggregator`, skill rewrite | **not here: PR (f)** |
| C14 / §4a: the `prior_research` source type and its precedence slot | 1, 2, 3, 4 |
| C14 / §4a: the `org_grant_intelligence` registry entry, the `raw.githubusercontent.com` fetch allowlist, dossier-first reading, re-fetching cited links | **not here: PR (f)**. The spec's §3 table assigns no other (d) work for C14, as checked by `grep -n "prior_research\|org-grant-intelligence"` over the spec |

**Ambiguities resolved:**
1. **`evidence` naming.** On a finding, `evidence` is the quoted sentence. The tier is therefore `evidence_tier` on findings and records, and the writer stores it in the `evidence` column. `expectations.TIER` keeps both tier columns out of the derived research targets.
2. **NULL `source_type`.** NULL means unranked: a row a person entered (for example a `POST /api/contacts` contact, `source_name = 'manual'`) or a row written before tiers. `_may_overwrite(None, x)` is `False`, so Import fills such a row's blanks and never overwrites it. That is the old fill-only rule, kept for exactly the rows nobody classified. 0033 backfills `'seed'` only where the provenance proves the seed wrote the row.
3. **The tier is the row's.** It records the strongest source that has written to the row. A weaker source may still fill a blank, as gap-filling requires, but the row keeps the stronger label. The cost is pinned by `test_a_mid_tier_source_cannot_correct_what_a_weaker_one_filled` and stated in the catalog defect. The alternative was to let a fill lower the tier, which would let mid-tier sources overwrite audited values. Provenance (`source_url` …) moves only when the incoming source takes the row.
4. **Research cannot claim `manual_check` or `seed`.** Findings accept six source types. `manual_check` arrives through (f)'s staff tool, and `seed` only from `seed.py`.
5. **`prior_research` (C14)** sits between `staff_dataset` and `aggregator`, and is always `claimed` (DB CHECK `<table>_unverifiable_claimed` and `check_tier`). This PR adds only the source type. The registry entry and the dossier reading are (f).
6. **`check_blocked` never replaces a known status**, in the migration's copy and in the writer. A check that could not be made carries no information about the stored status. It is still recorded when nothing is stored, which is how the acceptance run's FCRA row gets "check_blocked". `superseded` is not a status: it sets `is_current = false`.
7. **`applied` → `registered` at equal tier is a conflict.** An open 12A row from the CSO's acknowledgement is filled with its number when the order arrives. If the order is also an `org_document`, the status change goes to a person (spec: "nothing silently picks a winner between equals"). A registry or manual check upgrades it automatically.
8. **Identifiers are their own fact rows.** Each `org_identifier` finding is written by `write_org_identifier` with its own source, in `ORG_WRITE_ORDER`, rather than under the identity finding's source inside `write_org`. `OrgRecord.identifiers` remains only as the matcher's type-to-number map. A number held by another organisation is a conflict, not a silent `DO NOTHING`.
9. **Name normalisation runs in Python** (`name_key`) over the trigram candidate set, so it has one implementation and no SQL twin. **Brackets lose their characters, not their content**: "Seva Mandir (Assam)" never merges with "(Bihar)". A normalised name or alias that two organisations share resolves neither. A normalised hit is reported as method `alias`, and the old boilerplate rule still follows it.
10. **Alias hygiene.** The research's own spelling becomes an alias when it differs from the stored name. Any spelling another organisation already answers to is held for a person, not written.
11. **`valid_from` is `INTERNAL`** for place links. `ConceptSpec.columns` may now name an `INTERNAL` column, and only `org_identifier` does: a test pins that, so #99's concepts are unaffected. `checked_at`, `checked_by` and `evidence_document_id` stay out of research targets, since they are staff fields for (f).
12. **Saved org research without tiers** fails re-validation and is reported in `held` through #99's `_validated(…, report)`. It is re-researched, not promoted. `SCHEMA_VERSION` is not bumped, which matches #99.
13. **New doc types** live in a catalog note and `ORG_DOC_TYPES`. They are not a CHECK and not one of #99's reserved types, so a document finding may use them freely and they share `ensure_document`'s default class.
14. **Seeded rows become the weakest tier.** The spec ranks `seed` last, so a CSO's own document now replaces a seeded value where the old rule only filled blanks. The PR description says so (Task 13), and `TestTheOrgWriter`'s fill-only test is deleted on purpose (Task 5).
15. **Trustee counts (8 / 6 / 5) are not a column-level conflict.** §1 lists them among the disagreements recorded. Board members are `contacts` rows keyed on (org, name, role), so three sources naming different trustees produce differently sourced `office_bearer` rows, each with its own `source_type`, rather than a `Conflict`. The disagreement is visible as the union with sources. A stated *count* that differs is a `Conflict`, because it lands on `orgs.staff_count` (Task 5's `test_an_aggregator_never_replaces_the_cso_s_own_document`). The other two §1 examples are true conflicts: aggregator income vs the audited figure (Task 8), and 12A/80G listed vs applied (Task 7, `test_an_aggregator_listing_does_not_upgrade_an_application`).
16. **An identifier found by its number never rewrites the number's spelling.** That keeps re-promotion `matched` (`test_the_same_registration_twice_is_matched`).
17. **The frontend has no test runner.** The Diligence change is held by grep assertions and a label-parity test in pytest, plus `tsc`, `eslint` and `next build`.
