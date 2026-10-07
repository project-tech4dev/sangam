# Funder schema consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the nine funder tables to five: `funders` gains `cin` and `aliases` (and its five 0019 posture columns become reachable), `funder_csr_spend` / `funder_footprints` / `funder_partners` merge into one `funder_activity` table with a `kind` and inferred-classification columns, eligibility and proposal templates become `documents` rows. Every reader and writer (Import concepts, records, writer, promote, matcher, dossier, brief, SQL catalog, funder API, seed, prompts, skills, docs) moves with the schema.

**Architecture:** One forward-only migration (`db/migrations/0031_funder_consolidation.sql`) copies what has a home (identifiers → columns, activity rows → `funder_activity`, eligibility rows → one `documents` row per page), refuses to drop what does not (`proposal_templates` / `template_items` with rows), drops seven tables in FK order, and classifies the new table for #92's grants and RLS. In code, a concept may now own **part of a table**: `ConceptSpec` gains `row_filter` (e.g. `("kind", "spend")`) and `columns` (the allowlist of columns that concept may fill), which `expected_fields()`, `_held_per_concept()` and the writers all read. The four activity concepts (`csr_spend`, `footprint`, `partner`, new `programme_spend`) write `funder_activity` through one key (`FUNDER_ACTIVITY_KEY`, which includes `kind`); the new `eligibility_guideline` concept writes a `documents` row of `doc_type = 'funder_eligibility'`. `ensure_document` keys on `(source_url, doc-type class)`. The funder matcher reads `funders.cin` and `funders.aliases`; the org matcher is untouched.

**Tech Stack:** PostgreSQL 17 + pgvector (compose), raw psycopg 3 (no ORM), FastAPI, Pydantic v2, pytest (`asyncio_mode = "auto"`), Next.js/TypeScript for one type.

**Spec:** features-plans/data-model/2026-10-07-funder-model-consolidation.md (§2, §3; D1–D5, D7, D11, D12)

## Global Constraints

- **Base branch.** Start from `origin/master` **after** PR #98 (`0030_tag_links`, `tags.kind` gains `sub_theme`) and PR (a) of this spec (domains `environment` and `others` in `seed/data/taxonomy/themes.json`) have merged. Precondition check, run first:
  ```bash
  git -C /Users/vinod/GitHub/sangam fetch origin
  git -C /Users/vinod/GitHub/sangam show origin/master:db/migrations/0030_tag_links.sql >/dev/null && echo "#98 in"
  git -C /Users/vinod/GitHub/sangam show origin/master:seed/data/taxonomy/themes.json | grep -c '"domain": "others"'   # expect 1
  ```
  If either fails, stop: the classification resolver (Task 9) needs `tags` rows of kind `domain` with codes `livelihoods|health|education|environment|others`.
- **Never edit `/Users/vinod/GitHub/sangam`.** It serves a running dev site on master. Work in a worktree:
  ```bash
  git -C /Users/vinod/GitHub/sangam worktree add /Users/vinod/GitHub/sangam-funder-schema -b feat/funder-schema-consolidation origin/master
  cd /Users/vinod/GitHub/sangam-funder-schema
  ```
- **Never migrate the shared dev database `sangam`.** It is at `0021` and serves master. All integration work runs against a scratch clone, `sangam_fc`, on the same Postgres container (`sangam-postgres-1`).
- **Test commands.** The host has no pytest and `backend/` has no venv; the backend image has the runtime dependencies. Save this file **outside the worktree** (never commit it) and start every command with `source /Users/vinod/GitHub/fc-env.sh &&`:
  ```bash
  # /Users/vinod/GitHub/fc-env.sh
  WT=/Users/vinod/GitHub/sangam-funder-schema
  _run() { docker run --rm --network sangam_default -v "$WT":/w -w /w/backend "$@"; }
  # unit tier (no DB)
  bt()  { _run --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  # integration tier, against the scratch DB only
  bti() { _run -e TEST_DATABASE_URL=postgresql://sangam:sangam@postgres:5432/sangam_fc --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  # migration runner, against the scratch DB only
  mig() { _run -e DATABASE_URL="host=postgres user=sangam password=sangam dbname=sangam_fc" -e MIGRATIONS_DIR=/w/db/migrations --entrypoint python sangam-backend:latest -m app.db.migrate "$@"; }
  # python one-liners with the app importable
  bpy() { _run --entrypoint python sangam-backend:latest -c "$1"; }
  psql_fc() { docker exec -i sangam-postgres-1 psql -U sangam -d sangam_fc "$@"; }
  ```
  Baseline on master (measured): `bt -m "'not integration'" -q` → `602 passed, 10 skipped, 74 deselected`. "Green" below means **0 failed**; the passed count grows with each task's new tests.
- `ruff check .` runs on the host (`cd backend && ruff check .`, line-length 110).
- Frontend: `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit` **in the worktree**. `docker compose exec frontend …` and `make smoke` check the master checkout and the running master stack, not this branch.
- Conventions (CLAUDE.md, `db/migrations/README.md`): schema changes only in `db/migrations/`; a destructive migration carries a note on why the data situation makes it safe; never edit an applied migration (0025/0027 keep naming the dropped tables — their `to_regclass` guards make that harmless). Unit tests never touch a DB (`client_for`, monkeypatch `repositories/`, or the `recording_conn` fake added in Task 3). Integration tests carry `pytestmark = pytest.mark.integration`. Agent tools never raise and cite every row. A catalog addition is a security decision; `verify_against_db()` raises on drift.
- **Known pre-existing failure:** `tests/test_storage.py::TestEnsureDocumentRecordsTheArchive` passes `funder_id=` to `ensure_document`, which takes `owner=`. Task 13 fixes it; do not chase it earlier.
- **Expected red until Task 17:** after Task 1 applies 0031 to `sangam_fc`, `tests/test_sql_integration.py::TestCatalogMatchesReality::test_no_drift` fails there (the catalog still lists the dropped tables). Do not run it before Task 18.
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Migration number: `0031`. Open branches have held `0022`–`0030`; if one lands first with `0031`, rename this file to the next free number at merge time and update `MIGRATION` in its test.

## Review Focus

Five failure modes the unit suite can pass straight through. Each has a named test in the task that owns it.

1. **Org matching regresses while the funder matcher is rewritten.** `resolve_org` must keep reading `org_identifiers`, and `_write_org_identifiers` / `MERGEABLE` stay shared. → Task 4 `test_resolve_org_still_reads_org_identifiers`; Task 5 keeps `TestTheOrgWriter` green unchanged.
2. **Aliases and CINs are lost, or a CIN merges the wrong funder.** The migration must exclude the funder's own name and dedupe; `write_funder` must union aliases, never replace; saved `identifier` findings must fold in; a foundation's research carrying its **parent's** CIN (D7) must not merge into the parent, and must not abort the promote with a `UniqueViolation`. → Task 1 `test_identifiers_become_columns`; Task 3 `test_aliases_are_appended_never_replaced`; Task 4 `test_a_foundation_carrying_its_parents_cin_is_not_merged`, `test_a_cin_held_by_another_funder_is_held_back`; Task 5 `test_saved_identifier_findings_fold_into_the_record`.
3. **Eligibility documents collide with source documents.** A policy page must be able to be both the archived source and the eligibility document (two rows), while a PDF called `annual_report` by one run and `csr_annexure` by another stays one row; a `document` finding must not create a text-less `funder_eligibility` row. → Task 13 `test_a_page_can_be_source_and_eligibility_document`, `test_two_wordings_of_a_source_type_are_one_row`, `test_a_reserved_doc_type_is_refused_on_a_document_finding`; Task 14 `test_one_eligibility_document_per_page`.
4. **`NULLS NOT DISTINCT` keys collide across kinds, or a DB constraint aborts a whole promotion.** `_write_facts` catches only `ValidationError`; a `CheckViolation`/`UniqueViolation` loses every fact for that funder. `_row_identity` must mirror `FUNDER_ACTIVITY_KEY` (which includes `kind` and `partner_name`), and each kind's CHECK must be mirrored before the write (spend ⇒ amount, footprint ⇒ a place, partner ⇒ name, programme ⇒ resolved programme + amount, domain ⇒ classified_by, grant band order). → Task 1 `test_one_line_per_key_across_nulls_but_not_across_kinds`; Task 10 `test_row_identity_mirrors_the_activity_key`, `test_two_partners_on_one_project_are_two_lines`; Task 11 `test_a_footprint_with_no_place_is_held_not_written`; Task 12 `test_a_programme_figure_with_no_programme_is_held`; Task 4 `test_an_inverted_band_against_the_stored_one_is_held`.
5. **Supabase holds rows the local DB does not.** The migration must copy eligibility and activity rows, refuse (not silently drop) templates with content, and grant/RLS-classify `funder_activity` — 0025/0027 will not run again. → Task 1 `test_eligibility_rows_become_one_document_per_page`, `test_a_template_with_content_stops_the_migration`, `test_a_hidden_funders_activity_reaches_only_staff`; Task 18 pre-flight counts on Supabase before `make migrate ENV=staging`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `db/migrations/0031_funder_consolidation.sql` | create | All of §2: funders columns, copies, `funder_activity`, `local_area_spent`, `proposals.template_id` → documents, drops, grants + RLS |
| `backend/tests/test_funder_consolidation_migration.py` | create | Integration: the copy (rolled back, pre-0031 DB), the post-state, RLS |
| `backend/tests/conftest.py` | modify | `RecordingConn`, `RecordingPool` fakes + fixtures |
| `backend/tests/test_funder_identity.py` | create | Unit: CIN/aliases/posture, `write_funder`, matcher, legacy fold |
| `backend/tests/test_funder_activity.py` | create | Unit + one integration class: concept mechanism, classification resolver, activity writers, promote branches, dossier SQL |
| `backend/tests/test_eligibility_document.py` | create | Unit + integration: `ensure_document` keying, eligibility concept/record/writer |
| `backend/app/agent/tools/sql/catalog.py` | modify | add `funder_activity`, funders columns, `local_area_spent`, doc_type note; remove 7 tables; counts comment |
| `backend/app/ingest/expectations.py` | modify | `ConceptSpec.row_filter/columns`, `RESERVED_DOC_TYPES`, concepts, `NAMED_AS`, `REQUIRED`, `EXTRA`, docstring count |
| `backend/app/ingest/records.py` | modify | `CIN_FORMAT`, `normalise_cin`; `FunderRecord` columns; activity records with `activity_kind`; `FunderProgrammeSpendRecord`; `EligibilityGuidelineRecord`; drop `FunderEligibilityRecord`, `identifiers` |
| `backend/app/ingest/research_records.py` | modify | identity fields; classified spend; `ProgrammeSpendFinding`; `EligibilityGuidelineFinding`; drop `IdentifierFinding`, `FunderEligibilityFinding`; reserved doc types |
| `backend/app/ingest/writer.py` | modify | `write_funder` (cin, aliases, posture), `cin_holder`, `FUNDER_ACTIVITY_KEY`, `_write_activity`, four activity writers, `write_eligibility_document`, `ensure_document` keying; drop `_write_identifiers`, `write_funder_eligibility` |
| `backend/app/ingest/promote.py` | modify | `funder_from`, `_reconcile_with_stored`, `_validated` reporting, `WRITE_ORDER`, `CONCEPT_RECORDS`, `RENAMED`, `_row_identity`, branches |
| `backend/app/ingest/matcher.py` | modify | `resolve_funder(conn, name, cin=None)` on `funders.cin` / `funders.aliases` |
| `backend/app/ingest/taxonomy.py` | modify | `resolve_classification` |
| `backend/app/ingest/tools/catalog_tools.py` | modify | dossier head and sections; `_held_per_concept` filter; `research_goals` target label |
| `backend/app/ingest/brief.py` | modify | headlines for new fields/concepts; legacy titles |
| `backend/app/ingest/runner.py`, `geography.py` | modify | baseline counts; docstring |
| `backend/app/repositories/funders.py`, `backend/app/schemas/funders.py`, `frontend/lib/api/types.ts` | modify | detail drops `identifiers`, adds `cin`, `aliases` |
| `backend/tests/test_funders.py` | modify | detail shape test |
| `seed/seed.py` | modify | drop the `funder_identifiers` domain block |
| `backend/app/ingest/prompts/entity_researcher.md`, `backend/app/ingest/instructions.md`, skills `catalog-mapping`, `catalog-write-report`, `funder-scan-for-fundraisers`, `funder-intake-research` | modify | table names, eligibility-as-document, classification columns, concept counts |
| `backend/tests/test_ingest.py`, `backend/tests/test_sql_catalog.py`, `backend/tests/test_storage.py` | modify | parametrisations, renamed constructors, `apart`, required sets, catalog guards, stale `funder_id=` |
| `docs/DATA_PLATFORM.md`, `docs/INGEST.md`, `docs/SQL_AGENT.md`, `CLAUDE.md`, `README.md`, `seed/taxonomy_seed.py`, `seed/data/taxonomy/schedule_vii.json` | modify | table lists and counts |

`seed/graph_seed.py` and `backend/app/ingest/extractor.py` were checked and need **no change**: graph_seed reads only `org_identifiers`; extractor writes only `funder_csr_years` through `FunderCsrYearRecord`, whose new field is optional.

---

### Task 1: Migration 0031 and its integration tests

**Files:**
- Create: `db/migrations/0031_funder_consolidation.sql`
- Create: `backend/tests/test_funder_consolidation_migration.py`

**Interfaces:**
- Consumes: tables `funder_identifiers` (02_schema.sql:95-103 + 0001:45), `funder_csr_spend` / `funder_footprints` / `funder_partners` (0007), `proposal_templates` / `template_items` / `proposals.template_id` (0009, constraint `proposals_template_id_fkey`), `funder_eligibility` (0021); roles `anon`, `authenticated` and `app.is_staff()` (0023–0027).
- Produces: `funders.cin text UNIQUE`, `funders.aliases text[] NOT NULL DEFAULT '{}'`, table `funder_activity` (spec DDL verbatim), `funder_csr_years.local_area_spent numeric`, `proposals.template_id → documents(id)`, policy `funder_activity_read`; documents rows `doc_type = 'funder_eligibility'` with `content_md` sections headed exactly `## Statutory restatement`, `## Its own bar`, `## Disqualifiers` (Task 14's `EligibilityGuidelineRecord.content_md()` uses the same headings).

- [ ] **Step 1: Create the scratch database at the base migration head.**
  ```bash
  docker exec sangam-postgres-1 sh -c 'createdb -U sangam sangam_fc && pg_dump -U sangam sangam | psql -q -U sangam -d sangam_fc'
  source /Users/vinod/GitHub/fc-env.sh && mig --status && mig
  ```
  Expected: `--status` lists `0022_…` through `0030_tag_links` as pending; `mig` applies them (0023 creates the cluster roles `anon` and `authenticated` if missing — harmless to `sangam`). Then `psql_fc -tc "select max(version) from schema_migrations"` → `0030_tag_links`.

- [ ] **Step 2: Write the failing copy tests.** Create `backend/tests/test_funder_consolidation_migration.py`:
  ```python
  """0031: nine funder tables to five.

  The copy is tested by running the migration inside a rolled-back transaction on a database
  that has not had it yet; the result is tested on one that has. Run against the scratch clone
  (TEST_DATABASE_URL=…/sangam_fc), never the shared dev database.
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
  MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0031_funder_consolidation.sql"
  DROPPED = ("funder_identifiers", "funder_eligibility", "funder_csr_spend", "funder_footprints",
             "funder_partners", "template_items", "proposal_templates")

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
      return conn.execute("SELECT to_regclass('public.funder_activity') AS t").fetchone()["t"] is not None


  @pytest.fixture
  def before(conn):
      if _applied(conn):
          pytest.skip("0031 is already applied here; the copy is tested on a database before it")
      with conn.transaction(force_rollback=True):
          yield conn


  @pytest.fixture
  def after(conn):
      if not _applied(conn):
          pytest.skip("0031 is not applied here yet")
      with conn.transaction(force_rollback=True):
          yield conn


  def _one(conn, sql, params=()):
      return conn.execute(sql, params).fetchone()


  def _funder(conn, name, website=None, status="placeholder"):
      return _one(
          conn,
          "INSERT INTO funders (slug, name, website, registry_status) VALUES (%s, %s, %s, %s) RETURNING id",
          (f"fc-{uuid4().hex[:8]}", name, website, status),
      )["id"]


  def _migrate(conn):
      conn.execute(MIGRATION.read_text(encoding="utf-8"))


  def test_identifiers_become_columns(before):
      conn = before
      a = _funder(conn, "Acme Industries Limited")
      b = _funder(conn, "Acme Foundation", website="https://acmefoundation.org")
      for funder_id, id_type, id_value in [
          (a, "name", "Acme Industries Ltd"),
          (a, "name", "ACME INDUSTRIES LIMITED"),     # its own name, not an alias
          (a, "cin", "l12345mh2001plc123456"),        # normalised to upper case
          (a, "domain", "acme.example"),              # becomes website: none is set
          (a, "pan", "AAACA1234A"),                   # D1: discarded
          (b, "domain", "other.example"),             # website already set: left alone
      ]:
          conn.execute("INSERT INTO funder_identifiers (funder_id, id_type, id_value) VALUES (%s, %s, %s)",
                       (funder_id, id_type, id_value))
      _migrate(conn)
      acme = _one(conn, "SELECT cin, aliases, website FROM funders WHERE id = %s", (a,))
      assert acme["cin"] == "L12345MH2001PLC123456"
      assert acme["aliases"] == ["Acme Industries Ltd"]
      assert acme["website"] == "https://acme.example"
      assert _one(conn, "SELECT website FROM funders WHERE id = %s", (b,))["website"] == "https://acmefoundation.org"


  def test_activity_lines_keep_their_kind_and_place(before):
      conn = before
      f = _funder(conn, "Acme Industries Limited")
      district = _one(conn, "SELECT l.id, l.parent_id FROM locations l JOIN locations p ON p.id = l.parent_id "
                            "WHERE l.kind = 'district' AND p.kind = 'state' LIMIT 1")
      conn.execute(
          "INSERT INTO funder_csr_spend (funder_id, fiscal_year, state_location_id, district_location_id, "
          "project_name, implementing_agency, agency_csr1, via_agency, amount) "
          "VALUES (%s, 'FY2023-24', %s, %s, 'Project Unnati', 'Harsha Trust', 'CSR00001234', true, 1000000)",
          (f, district["parent_id"], district["id"]),
      )
      conn.execute("INSERT INTO funder_footprints (funder_id, fiscal_year, location_id, name_as_printed) "
                   "VALUES (%s, 'FY2023-24', %s, 'Barpeta')", (f, district["id"]))
      conn.execute("INSERT INTO funder_partners (funder_id, fiscal_year, partner_name, partner_kind) "
                   "VALUES (%s, 'FY2023-24', 'Harsha Trust', 'ngo')", (f,))
      _migrate(conn)
      rows = {r["kind"]: r for r in conn.execute(
          "SELECT * FROM funder_activity WHERE funder_id = %s", (f,)).fetchall()}
      assert set(rows) == {"spend", "footprint", "partner"}
      spend = rows["spend"]
      assert (spend["partner_name"], spend["partner_csr1"], spend["implementation_mode"]) == (
          "Harsha Trust", "CSR00001234", "implementing_agency")
      assert (spend["state_location_id"], spend["location_id"]) == (district["parent_id"], district["id"])
      foot = rows["footprint"]
      assert (foot["state_location_id"], foot["location_id"]) == (district["parent_id"], district["id"])
      assert rows["partner"]["partner_kind"] == "ngo"


  def test_eligibility_rows_become_one_document_per_page(before):
      conn = before
      f = _funder(conn, "Acme Foundation")
      for kind, text in [
          ("disqualifier", "Organisations with a political affiliation are not eligible."),
          ("statutory_restatement", "Registered under Section 12A and 80G of the Income Tax Act."),
          ("own_bar", "At least five years of work in the district concerned."),
      ]:
          conn.execute(
              "INSERT INTO funder_eligibility (funder_id, kind, criterion, source_url, source_name) "
              "VALUES (%s, %s, %s, 'https://acme.example/csr-policy', 'acme')", (f, kind, text))
      _migrate(conn)
      docs = conn.execute("SELECT doc_type, content_md, source_url FROM documents WHERE funder_id = %s",
                          (f,)).fetchall()
      assert len(docs) == 1 and docs[0]["doc_type"] == "funder_eligibility"
      md = docs[0]["content_md"]
      assert md.index("## Statutory restatement") < md.index("## Its own bar") < md.index("## Disqualifiers")
      assert "five years of work" in md


  def test_a_template_with_content_stops_the_migration(before):
      conn = before
      f = _funder(conn, "Acme Foundation")
      conn.execute("INSERT INTO proposal_templates (funder_id, name, kind) VALUES (%s, 'Form', 'application')",
                   (f,))
      with pytest.raises(errors.RaiseException, match="proposal_templates"):
          with conn.transaction():
              _migrate(conn)
  ```
- [ ] **Step 3: Run them — they fail.** `source /Users/vinod/GitHub/fc-env.sh && bti tests/test_funder_consolidation_migration.py -q` → 4 errors/failures: `FileNotFoundError … 0031_funder_consolidation.sql`.

- [ ] **Step 4: Write the migration.** Create `db/migrations/0031_funder_consolidation.sql`:
  ```sql
  -- Nine funder tables to five. Spec: features-plans/data-model/2026-10-07-funder-model-consolidation.md §2
  -- (D1-D5, D7, D11, D12).
  --
  --   funders            + cin, aliases (from funder_identifiers; D1 discards pan/csr1/darpan/reg_no)
  --   funder_activity    replaces funder_csr_spend, funder_footprints, funder_partners, one row per line
  --   documents          holds eligibility (doc_type 'funder_eligibility') and templates ('proposal_template')
  --   funder_csr_years   + local_area_spent
  --
  -- DESTRUCTIVE: drops seven tables. Safe because every row with a home is copied first (identifiers,
  -- activity lines, eligibility rows), and the one table with no mechanical home - template_items, and
  -- proposal_templates with it - stops the migration if it holds anything. documents.doc_type is free
  -- text, so the three new doc_type values need no DDL; the writer keeps them reserved.
  --
  -- Numbered after #98's 0030. Renumber at merge if another branch takes 0031.
  -- Before running against Supabase: SELECT count(*) on each dropped table, and take a backup.

  -- 0. Refuse to drop what this file cannot carry across.
  DO $$
  DECLARE n bigint;
  BEGIN
    SELECT count(*) INTO n FROM template_items;
    IF n > 0 THEN
      RAISE EXCEPTION 'template_items holds % rows and proposal_templates has no documents mapping for them; '
                      'move them by hand before 0031', n;
    END IF;
    SELECT count(*) INTO n FROM proposal_templates;
    IF n > 0 THEN
      RAISE EXCEPTION 'proposal_templates holds % rows; a template is now a documents row '
                      '(doc_type ''proposal_template''). Move them by hand before 0031', n;
    END IF;
  END $$;

  -- 1. funders: a corporate funder keeps its CIN (D1); other spellings become aliases (D2).
  ALTER TABLE funders
    ADD COLUMN cin text UNIQUE,                          -- corporate funders only; trusts have none
    ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';     -- other names it files or is reported under

  -- 2. funder_identifiers -> columns.
  UPDATE funders f SET aliases = a.names
  FROM (
    SELECT fi.funder_id, array_agg(DISTINCT btrim(fi.id_value) ORDER BY btrim(fi.id_value)) AS names
    FROM funder_identifiers fi JOIN funders own ON own.id = fi.funder_id
    WHERE fi.id_type = 'name' AND lower(btrim(fi.id_value)) <> lower(own.name)
    GROUP BY fi.funder_id
  ) a
  WHERE a.funder_id = f.id;

  UPDATE funders f SET cin = c.cin
  FROM (
    SELECT DISTINCT ON (funder_id) funder_id, upper(regexp_replace(id_value, '\s', '', 'g')) AS cin
    FROM funder_identifiers WHERE id_type = 'cin'
    ORDER BY funder_id, is_current DESC, verified DESC, id_value
  ) c
  WHERE c.funder_id = f.id;

  UPDATE funders f SET website = 'https://' || d.domain
  FROM (
    SELECT DISTINCT ON (funder_id) funder_id, btrim(id_value) AS domain
    FROM funder_identifiers WHERE id_type = 'domain'
    ORDER BY funder_id, is_current DESC, id_value
  ) d
  WHERE d.funder_id = f.id AND (f.website IS NULL OR btrim(f.website) = '');

  -- 3. funder_activity: one row per line of a CSR filing, annual report or partner list (D4).
  CREATE TABLE funder_activity (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('spend', 'footprint', 'partner', 'programme')),
    fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY\d{4}-\d{2}$'),
    program_id bigint REFERENCES programs(id) ON DELETE SET NULL,
    domain_tag_id bigint REFERENCES tags(id),            -- kind 'domain': one of the five
    theme_tag_id bigint REFERENCES tags(id),             -- kind 'theme' or 'sub_theme'; NULL when the
                                                         -- evidence supports no theme
    classified_by text CHECK (classified_by IN
      ('filed_sector', 'project_name', 'partner', 'report')),
    classification_note text,                            -- the evidence, e.g. "project 'Financial
                                                         -- Literacy & Inclusion'; filed under Education"
    classification_confirmed boolean NOT NULL DEFAULT false,
    csr_sector_id bigint REFERENCES tags(id),            -- Schedule VII, as filed
    state_location_id bigint REFERENCES locations(id),
    location_id bigint REFERENCES locations(id),         -- most specific place below state
    name_as_printed text,                                -- place as the source printed it
    project_name text,
    designation text,
    implementation_mode text CHECK (implementation_mode IN
      ('direct', 'implementing_agency', 'own_trust_or_section8', 'not_stated')),
    partner_name text,
    partner_canonical text,
    partner_org_id bigint REFERENCES orgs(id),
    partner_funder_id bigint REFERENCES funders(id),
    partner_csr1 text,                                   -- the PARTNER's CSR-1, when filed
    partner_kind text CHECK (partner_kind IN ('ngo', 'foundation', 'university', 'research',
      'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
    outlay numeric CHECK (outlay >= 0),
    amount numeric CHECK (amount >= 0),
    project_count integer,
    is_ongoing boolean,
    notes text,
    source_key text,                                     -- source registry key, e.g. 'mca_csr'
    source_url text, source_name text, fetched_at timestamptz, as_of text,
    document_id bigint REFERENCES documents(id), archive_url text,
    CHECK (kind <> 'spend' OR amount IS NOT NULL),
    CHECK (kind <> 'footprint' OR location_id IS NOT NULL OR state_location_id IS NOT NULL),
    CHECK (kind <> 'partner' OR partner_name IS NOT NULL),
    CHECK (kind <> 'programme' OR (program_id IS NOT NULL AND amount IS NOT NULL)),
    CHECK (domain_tag_id IS NULL OR classified_by IS NOT NULL),
    UNIQUE NULLS NOT DISTINCT (funder_id, kind, fiscal_year, program_id, csr_sector_id,
      state_location_id, location_id, designation, project_name, partner_name)
  );
  CREATE INDEX funder_activity_funder_kind_idx ON funder_activity (funder_id, kind, fiscal_year);
  CREATE INDEX funder_activity_domain_idx ON funder_activity (domain_tag_id);
  CREATE INDEX funder_activity_theme_idx ON funder_activity (theme_tag_id);
  CREATE INDEX funder_activity_location_idx ON funder_activity (location_id, fiscal_year);
  CREATE INDEX funder_activity_partner_org_idx ON funder_activity (partner_org_id);

  -- Copies. Empty locally; on Supabase, count first (see the header).
  INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, csr_sector_id, state_location_id,
    location_id, project_name, designation, implementation_mode, partner_name, partner_org_id, partner_csr1,
    amount, project_count, is_ongoing, notes, source_url, source_name, fetched_at, as_of, document_id,
    archive_url)
  SELECT funder_id, 'spend', fiscal_year, program_id, csr_sector_id, state_location_id, district_location_id,
    project_name, designation,
    CASE via_agency WHEN true THEN 'implementing_agency' WHEN false THEN 'direct' END,
    implementing_agency, agency_org_id, agency_csr1, amount, project_count, is_ongoing, notes,
    source_url, source_name, fetched_at, as_of, document_id, archive_url
  FROM funder_csr_spend;

  -- A footprint's one location becomes the pair: a state goes to state_location_id; anything below a
  -- state keeps its own id in location_id and its state parent in state_location_id.
  INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, state_location_id, location_id,
    name_as_printed, notes, source_url, source_name, fetched_at, as_of, document_id, archive_url)
  SELECT fp.funder_id, 'footprint', fp.fiscal_year, fp.program_id,
    CASE WHEN l.kind = 'state' THEN l.id WHEN p.kind = 'state' THEN p.id END,
    CASE WHEN l.kind = 'state' THEN NULL ELSE l.id END,
    fp.name_as_printed, fp.notes, fp.source_url, fp.source_name, fp.fetched_at, fp.as_of,
    fp.document_id, fp.archive_url
  FROM funder_footprints fp
  JOIN locations l ON l.id = fp.location_id
  LEFT JOIN locations p ON p.id = l.parent_id;

  INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, partner_name, partner_canonical,
    partner_org_id, partner_funder_id, partner_csr1, partner_kind, notes, source_url, source_name,
    fetched_at, as_of, document_id, archive_url)
  SELECT funder_id, 'partner', fiscal_year, program_id, partner_name, partner_canonical, org_id,
    partner_funder_id, partner_csr1, partner_kind, notes, source_url, source_name, fetched_at, as_of,
    document_id, archive_url
  FROM funder_partners;

  -- Eligibility (D3): one documents row per funder and page, the criteria kept verbatim under the three
  -- headings EligibilityGuidelineRecord.content_md() writes.
  INSERT INTO documents (funder_id, title, doc_type, content_md, source_url, source_name, fetched_at, as_of,
                         archive_url, is_public, status)
  SELECT funder_id, 'Eligibility for applicants', 'funder_eligibility',
    concat_ws(E'\n\n',
      '## Statutory restatement' || E'\n\n'
        || string_agg(criterion, E'\n\n' ORDER BY id) FILTER (WHERE kind = 'statutory_restatement'),
      '## Its own bar' || E'\n\n'
        || string_agg(criterion, E'\n\n' ORDER BY id) FILTER (WHERE kind = 'own_bar'),
      '## Disqualifiers' || E'\n\n'
        || string_agg(criterion, E'\n\n' ORDER BY id) FILTER (WHERE kind = 'disqualifier')),
    source_url, min(source_name), max(fetched_at), max(as_of), min(archive_url), true, 'read'
  FROM funder_eligibility
  GROUP BY funder_id, source_url;

  -- 4. The MCA return reports local-area spend; the table lacked it.
  ALTER TABLE funder_csr_years ADD COLUMN local_area_spent numeric;

  -- 5. A template is a documents row (D5). Step 0 proved no proposal names one.
  ALTER TABLE proposals DROP CONSTRAINT proposals_template_id_fkey;
  ALTER TABLE proposals ADD CONSTRAINT proposals_template_id_fkey
    FOREIGN KEY (template_id) REFERENCES documents(id);

  -- 6. Drop, children first.
  DROP TABLE template_items;
  DROP TABLE proposal_templates;
  DROP TABLE funder_eligibility;
  DROP TABLE funder_partners;
  DROP TABLE funder_footprints;
  DROP TABLE funder_csr_spend;
  DROP TABLE funder_identifiers;

  -- 7. Access, as 0025 and 0027 would have classified it: a funder child, public read, hidden with a hidden
  -- funder. Their guard blocks never run again, and 0025's default privileges leave a new table closed.
  GRANT SELECT ON funder_activity TO anon, authenticated;
  ALTER TABLE funder_activity ENABLE ROW LEVEL SECURITY;
  CREATE POLICY funder_activity_read ON funder_activity FOR SELECT TO anon, authenticated
    USING (EXISTS (SELECT 1 FROM public.funders f WHERE f.id = funder_id));
  ```
- [ ] **Step 5: Run the copy tests — they pass.** `bti tests/test_funder_consolidation_migration.py -q` → `4 passed`.
- [ ] **Step 6: Apply 0031 to the scratch DB and add the post-state tests.** `mig` → reports `0031_funder_consolidation` applied. Append to the test file:
  ```python
  def test_the_old_tables_are_gone(after):
      for table in DROPPED:
          assert _one(after, "SELECT to_regclass(%s) AS t", (f"public.{table}",))["t"] is None, table


  def test_a_template_is_a_document(after):
      target = _one(after, "SELECT confrelid::regclass::text AS t FROM pg_constraint "
                           "WHERE conname = 'proposals_template_id_fkey'")["t"]
      assert target == "documents"


  def test_one_line_per_key_across_nulls_but_not_across_kinds(after):
      conn = after
      f = _funder(conn, "Acme Industries Limited")
      line = "INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, amount) VALUES (%s, %s, 'FY2023-24', 'Harsha Trust', %s)"
      conn.execute(line, (f, "spend", 100))
      conn.execute(line, (f, "partner", None))          # same key bar kind: a different line
      with pytest.raises(errors.UniqueViolation):
          with conn.transaction():
              conn.execute(line, (f, "partner", None))  # NULLS NOT DISTINCT: the same line twice


  @pytest.mark.parametrize("sql", [
      "INSERT INTO funder_activity (funder_id, kind, fiscal_year) VALUES (%s, 'spend', 'FY2023-24')",
      "INSERT INTO funder_activity (funder_id, kind, fiscal_year) VALUES (%s, 'footprint', 'FY2023-24')",
      "INSERT INTO funder_activity (funder_id, kind, fiscal_year) VALUES (%s, 'partner', 'FY2023-24')",
      "INSERT INTO funder_activity (funder_id, kind, fiscal_year, amount) VALUES (%s, 'programme', 'FY2023-24', 1)",
  ])
  def test_each_kind_refuses_a_line_missing_what_defines_it(after, sql):
      f = _funder(after, "Acme Industries Limited")
      with pytest.raises(errors.CheckViolation):
          with after.transaction():
              after.execute(sql, (f,))


  def test_a_hidden_funders_activity_reaches_only_staff(after):
      conn = after
      hidden = _funder(conn, "Hidden Funder", status="hidden")
      public = _funder(conn, "Public Funder")
      for f in (hidden, public):
          conn.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name) "
                       "VALUES (%s, 'partner', 'FY2023-24', 'Harsha Trust')", (f,))
      staff = uuid4()
      conn.execute("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true)",
                   (f"fc-{staff}@rls.test", staff))

      def sees(role, claims, funder_id):
          with conn.transaction(force_rollback=True):
              conn.execute("SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                           (role, claims))
              return len(conn.execute("SELECT 1 FROM funder_activity WHERE funder_id = %s",
                                      (funder_id,)).fetchall())

      staff_claims = json.dumps({"sub": str(staff)})
      assert sees("anon", "", hidden) == 0
      assert sees("anon", "", public) == 1
      assert sees("authenticated", staff_claims, hidden) == 1
  ```
- [ ] **Step 7: Run.** `bti tests/test_funder_consolidation_migration.py -q` → `4 skipped` (the `before` tests, now that 0031 is applied) and `9 passed`. `bt -m "'not integration'" -q` → 0 failed (no code changed).
- [ ] **Step 8: Commit.**
  ```bash
  git add db/migrations/0031_funder_consolidation.sql backend/tests/test_funder_consolidation_migration.py
  git commit -m "feat(db): 0031 — nine funder tables to five" -m "funders gains cin and aliases; funder_csr_spend, funder_footprints and funder_partners merge into funder_activity with a kind and classification columns; eligibility and templates become documents rows; funder_activity is granted and RLS-classified as a funder child." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

### Task 2: Catalog — add `funder_activity`

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (insert a `Table` after `funder_csr_years`, ~line 229)
- Modify: `backend/tests/test_sql_catalog.py` (append a class)

**Interfaces:**
- Produces: `CATALOG["funder_activity"]` with the columns in DDL order, `kind.values == ("spend", "footprint", "partner", "programme")`, citations `funder_id`/`partner_funder_id` → funder, `partner_org_id` → org; `DEFECTS["funder_activity"]`. Later tasks' `ConceptSpec.columns` name these columns.

- [ ] **Step 1: Failing test.** Append to `backend/tests/test_sql_catalog.py`:
  ```python
  class TestFunderActivity:
      def test_it_is_catalogued_with_its_four_kinds(self):
          assert cat.COLUMNS["funder_activity"]["kind"].values == ("spend", "footprint", "partner", "programme")

      def test_every_line_cites_its_funder_and_its_partner(self):
          assert cat.CITE_COLUMNS[("funder_activity", "funder_id")] == "funder"
          assert cat.CITE_COLUMNS[("funder_activity", "partner_funder_id")] == "funder"
          assert cat.CITE_COLUMNS[("funder_activity", "partner_org_id")] == "org"

      def test_programme_rows_are_never_summed_with_spend(self):
          text = " ".join(cat.DEFECTS["funder_activity"]).lower()
          assert "programme" in text and "never" in text and "spend" in text

      def test_an_inferred_classification_says_so(self):
          text = " ".join(cat.DEFECTS["funder_activity"]).lower()
          assert "classification_confirmed" in text

      def test_its_sources_are_surfaced(self):
          assert "funder_activity" in cat.PROVENANCE_COLUMNS
  ```
  Run `bt tests/test_sql_catalog.py -q` → `KeyError: 'funder_activity'`.
- [ ] **Step 2: Add the table.** In `_TABLES`, after the `funder_csr_years` entry:
  ```python
      Table(
          name="funder_activity",
          description="One line of a funder's CSR filing, annual report or partner list per fiscal year: a spend line, a place the work ran, a named partner, or the funder's own programme figure. `kind` says which.",
          primary_key=('id',),
          foreign_keys=(ForeignKey("funder_id", "funders.id"), ForeignKey("program_id", "programs.id"), ForeignKey("domain_tag_id", "tags.id"), ForeignKey("theme_tag_id", "tags.id"), ForeignKey("csr_sector_id", "tags.id"), ForeignKey("state_location_id", "locations.id"), ForeignKey("location_id", "locations.id"), ForeignKey("partner_org_id", "orgs.id"), ForeignKey("partner_funder_id", "funders.id"), ForeignKey("document_id", "documents.id")),
          columns=(
              Column("id", "bigint"),
              Column("funder_id", "bigint", cites="funder", note="for a statutory filing, the corporate parent that filed it; a foundation is its child through funders.parent_id"),
              Column("kind", "text", note="'spend' a filing line with an amount; 'footprint' a place the work ran; 'partner' a named partner; 'programme' the funder's OWN total for one programme component. Always filter on kind", values=('spend', 'footprint', 'partner', 'programme')),
              Column("fiscal_year", "text", note="period label, always 'FYyyyy-yy'"),
              Column("program_id", "bigint", note="the funder's programs row; required on kind 'programme'"),
              Column("domain_tag_id", "bigint", note="tags row of kind 'domain' (livelihoods, health, education, environment, others). Set on every spend and programme line; INFERRED unless classification_confirmed"),
              Column("theme_tag_id", "bigint", note="tags row of kind 'theme' or 'sub_theme', at the most specific level the evidence supports; NULL means the line gave nothing to go on, not 'no theme'"),
              Column("classified_by", "text", note="what the domain and theme rest on", values=('filed_sector', 'project_name', 'partner', 'report')),
              Column("classification_note", "text", note="the evidence for the classification in a few words"),
              Column("classification_confirmed", "boolean", note="true only after a person vetted the domain and theme; report totals as 'confirmed' or 'including inferred'"),
              Column("csr_sector_id", "bigint", note="the Schedule VII sector AS FILED (tags kind 'csr_sector'); filings misfile often, so prefer domain_tag_id for 'what was this spent on'"),
              Column("state_location_id", "bigint"),
              Column("location_id", "bigint", note="the most specific place below the state, usually a district"),
              Column("name_as_printed", "text", note="the place name as the source spelled it"),
              Column("project_name", "text", note="NULL on an aggregate spend line; set on a single project"),
              Column("designation", "text", note="the total covers only places with this designation, e.g. 'aspirational_district'"),
              Column("implementation_mode", "text", values=('direct', 'implementing_agency', 'own_trust_or_section8', 'not_stated')),
              Column("partner_name", "text", note="the implementing agency or named partner, as printed"),
              Column("partner_canonical", "text", note="one spelling per partner; count renewals on this, not partner_name"),
              Column("partner_org_id", "bigint", cites="org"),
              Column("partner_funder_id", "bigint", cites="funder"),
              Column("partner_csr1", "text", note="the PARTNER's CSR-1 registration, when filed"),
              Column("partner_kind", "text", values=('ngo', 'foundation', 'university', 'research', 'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
              Column("outlay", "numeric", note="INR approved or budgeted for the line, when filed beside the spend"),
              Column("amount", "numeric", note="INR"),
              Column("project_count", "integer", note="set on an aggregate: how many projects the amount covers"),
              Column("is_ongoing", "boolean"),
              Column("notes", "text"),
              Column("source_key", "text", note="the source registry key, e.g. 'mca_csr'"),
              Column("source_url", "text"),
              Column("source_name", "text"),
              Column("fetched_at", "timestamp with time zone"),
              Column("as_of", "text", note="the period the source describes, e.g. 'FY2023-24' - NOT when it was fetched"),
              Column("document_id", "bigint", note="the documents row this fact was read from, when there is one"),
              Column("archive_url", "text"),
          ),
          defects=(
              "Sparse: lines arrive one funder at a time from promoted research, so a missing year or kind means 'not recorded', never 'spent nothing' or 'no partners'.",
              "Rows of kind 'programme' are the funder's own programme totals: never sum them with 'spend' lines and never spread them across them; report the two side by side.",
              "domain_tag_id and theme_tag_id are inferences unless classification_confirmed is true, so a total by domain or theme must say whether it is confirmed or includes inferred lines.",
              "A 'partner' line is a named relationship, NOT evidence that money changed hands; that is a grant.",
          ),
      ),
  ```
- [ ] **Step 3: Run.** `bt tests/test_sql_catalog.py -q` → all pass (the import-time `_self_check()` accepts the new FKs). `bt -m "'not integration'" -q` → 0 failed.
- [ ] **Step 4: Commit.** `git add backend/app/agent/tools/sql/catalog.py backend/tests/test_sql_catalog.py && git commit -m "feat(sql): catalogue funder_activity" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 3: Identity — CIN, aliases and the posture columns reach research and the writer

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (funders `Table`, ~lines 391-409)
- Modify: `backend/app/ingest/records.py` (top constants; `FunderRecord` lines 64-90)
- Modify: `backend/app/ingest/research_records.py` (`IdentityFinding` lines 114-126; imports)
- Modify: `backend/app/ingest/writer.py` (`FUNDER_UPDATABLE` line 41; `write_funder` lines 142-187; new `new_aliases`)
- Modify: `backend/app/ingest/promote.py` (`funder_from` lines 164-185)
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_funder_identity.py`

**Interfaces:**
- Produces: `records.CIN_FORMAT: re.Pattern`, `records.normalise_cin(v: str) -> str`; `FunderRecord.cin: str | None`, `.aliases: list[str]`, `.intake_mode`, `.funds_external`, `.typical_duration_months`, `.grant_size_min: float | None`, `.grant_size_max: float | None` (INR); `IdentityFinding` same names (`grant_size_*` as `Money`); `writer.new_aliases(held: list[str], found: list[str], name: str) -> list[str]`; `FUNDER_UPDATABLE` gains `cin` + 5 posture columns. Fixtures `recording_conn` (class `RecordingConn(rows)`) and `recording_pool` (class `RecordingPool(conn)`).

- [ ] **Step 1: Add the fakes to `backend/tests/conftest.py`** (append):
  ```python
  class RecordingConn:
      """Replays one queued row per fetchone()/fetchall() and records every statement and its params."""

      def __init__(self, rows=()):
          self.rows, self.sql, self.params = list(rows), [], []

      async def execute(self, sql, params=None):
          self.sql.append(" ".join(sql.split()))
          self.params.append(params)
          return self

      async def fetchone(self):
          return self.rows.pop(0) if self.rows else None

      async def fetchall(self):
          return self.rows.pop(0) if self.rows else []

      def transaction(self):
          conn = self

          class _Tx:
              async def __aenter__(self):
                  return conn

              async def __aexit__(self, *exc):
                  return False

          return _Tx()


  class RecordingPool:
      def __init__(self, conn):
          self.conn = conn

      def connection(self):
          return self.conn.transaction()


  @pytest.fixture
  def recording_conn():
      return RecordingConn


  @pytest.fixture
  def recording_pool():
      return RecordingPool
  ```
- [ ] **Step 2: Failing tests.** Create `backend/tests/test_funder_identity.py`:
  ```python
  """A funder's identity after 0031: a CIN, other spellings, and its stated posture are columns."""

  from __future__ import annotations

  from datetime import UTC, datetime

  import pytest
  from pydantic import ValidationError

  from app.ingest.expectations import expected_fields
  from app.ingest.matcher import Match
  from app.ingest.records import FunderRecord
  from app.ingest.research_records import IdentityFinding
  from app.ingest.writer import FUNDER_UPDATABLE, new_aliases, write_funder

  NOW = datetime(2026, 10, 7, tzinfo=UTC)
  CIN = "L65110GJ1993PLC020769"


  def prov(**kw):
      return {"source_url": "https://a.b/c", "source_name": "test", "fetched_at": NOW, **kw}


  def finding(**kw):
      return IdentityFinding(
          name="Axis Bank Limited",
          evidence="Axis Bank Limited, CIN L65110GJ1993PLC020769, files its CSR return.",
          source_url="https://a.b/c", confidence="high", **kw,
      )


  class TestTheFindingCarriesTheColumns:
      def test_identity_offers_cin_aliases_and_the_posture(self):
          names = {f.name for f in expected_fields("identity")}
          assert {"cin", "aliases", "intake_mode", "funds_external", "typical_duration_months",
                  "grant_size_min", "grant_size_max"} <= names

      def test_a_cin_is_normalised(self):
          assert finding(cin=" l65110gj1993plc020769 ").cin == CIN

      @pytest.mark.parametrize("bad", ["AAACA1234A", "L65110GJ1993PLC02076", "csr00001234"])
      def test_something_that_is_not_a_cin_is_refused(self, bad):
          with pytest.raises(ValidationError, match="not a CIN"):
              finding(cin=bad)

      def test_an_inverted_band_is_refused(self):
          with pytest.raises(ValidationError, match="inverted"):
              finding(grant_size_min={"value": 2, "unit": "crore", "text": "Rs 2 crore"},
                      grant_size_max={"value": 25, "unit": "lakh", "text": "Rs 25 lakh"})


  class TestAliases:
      def test_only_new_spellings_are_kept(self):
          assert new_aliases(["ABF"], ["abf", "Axis Bank Fdn", "AXIS BANK FOUNDATION", "Axis Bank Fdn"],
                             "Axis Bank Foundation") == ["Axis Bank Fdn"]

      def test_the_record_drops_blanks_and_repeats(self):
          rec = FunderRecord(name="Axis Bank Limited", aliases=[" Axis Bank ", "", "axis bank"], **prov())
          assert rec.aliases == ["Axis Bank"]


  class TestWriteFunder:
      async def test_a_new_funder_is_written_with_its_cin_and_posture(self, recording_conn):
          conn = recording_conn([None, {"id": 7}])
          rec = FunderRecord(name="Axis Bank Limited", cin=CIN, aliases=["Axis Bank Ltd"],
                             intake_mode="rfp_only", grant_size_min=2_500_000.0, **prov())
          status, funder_id, _ = await write_funder(conn, rec, Match("none"))
          assert (status, funder_id) == ("added", 7)
          insert = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO funders"))
          assert "cin" in conn.sql[insert] and "intake_mode" in conn.sql[insert]
          params = conn.params[insert]
          assert CIN in params and ["Axis Bank Ltd"] in params and "rfp_only" in params

      async def test_aliases_are_appended_never_replaced(self, recording_conn):
          held = {"name": "Axis Bank Foundation", "aliases": ["ABF"], **dict.fromkeys(FUNDER_UPDATABLE)}
          conn = recording_conn([held])
          rec = FunderRecord(name="Axis Bank Foundation", aliases=["abf", "Axis Bank Fdn"], **prov())
          status, _, changes = await write_funder(conn, rec, Match("exact", 1))
          assert status == "updated"
          update = next(i for i, q in enumerate(conn.sql) if q.startswith("UPDATE funders"))
          assert "aliases = aliases || %s::text[]" in conn.sql[update]
          assert ["Axis Bank Fdn"] in conn.params[update]
          assert changes["aliases"]["new"] == ["ABF", "Axis Bank Fdn"]
  ```
  Also add, in the same file, the `funder_from` mapping test:
  ```python
  def test_funder_from_carries_the_new_identity_fields():
      from app.ingest.promote import funder_from

      row = {"slug": "axis-bank", "entity_name": "Axis Bank", "canonical_name": None, "website": None,
             "researched_at": NOW}
      f = finding(cin=CIN, aliases=["Axis Bank Ltd"], intake_mode="closed",
                  grant_size_max={"value": 1, "unit": "crore", "text": "Rs 1 crore"}).model_dump(mode="json")
      rec = funder_from(row, [f])
      assert (rec.cin, rec.aliases, rec.intake_mode, rec.grant_size_max) == (CIN, ["Axis Bank Ltd"], "closed", 10_000_000)
  ```
  Run `bt tests/test_funder_identity.py -q` → import error (`new_aliases`), then field failures.
- [ ] **Step 3: Catalog funders columns.** In the `funders` `Table` columns, after `parent_id`, add:
  ```python
              Column("intake_mode", "text", note="how an NGO can approach the funder at all, as it says so", values=('open', 'rolling', 'invitation_only', 'rfp_only', 'closed', 'unknown')),
              Column("funds_external", "boolean", note="what the funder SAYS about funding other organisations; funder_activity.implementation_mode is what it did. Report both, never reconcile them"),
              Column("typical_duration_months", "integer", note="a stated typical grant duration"),
              Column("grant_size_min", "numeric", note="a stated grant band, INR: the funder's posture across all its giving, not one call's (that is rfps.amount_min)"),
              Column("grant_size_max", "numeric", note="the top of the stated grant band, INR"),
              Column("cin", "text", note="Corporate Identity Number of a company funder, 21 characters; a trust or society has none. One CIN, one row"),
              Column("aliases", "text[]", note="other names the funder files or is reported under; match names against these too"),
  ```
- [ ] **Step 4: Records.** In `backend/app/ingest/records.py`, after `FISCAL_YEAR`:
  ```python
  # A company's Corporate Identity Number: listing status, industry code, state, year, type, serial.
  CIN_FORMAT = re.compile(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}")


  def normalise_cin(v: str) -> str:
      """One spelling per CIN: upper case, no spaces. The MCA prints it both ways."""
      return re.sub(r"\s+", "", v).upper()
  ```
  In `FunderRecord`, after `identifiers` (removed in Task 5), add:
  ```python
      cin: str | None = None
      """Corporate funders only. Normalised here and refused on the finding, so a malformed CIN costs
      one field at save time rather than the whole funder at promotion."""
      aliases: list[str] = Field(default_factory=list)
      intake_mode: Literal["open", "rolling", "invitation_only", "rfp_only", "closed", "unknown"] | None = None
      funds_external: bool | None = None
      typical_duration_months: int | None = Field(default=None, gt=0)
      grant_size_min: float | None = Field(default=None, ge=0, description="INR")
      grant_size_max: float | None = Field(default=None, ge=0, description="INR")

      @field_validator("cin")
      @classmethod
      def _one_spelling(cls, v: str | None) -> str | None:
          return normalise_cin(v) if v else None

      @field_validator("aliases")
      @classmethod
      def _distinct(cls, v: list[str]) -> list[str]:
          out: list[str] = []
          seen: set[str] = set()
          for alias in (a.strip() for a in v):
              if alias and alias.lower() not in seen:
                  seen.add(alias.lower())
                  out.append(alias)
          return out
  ```
- [ ] **Step 5: Finding.** In `research_records.py` add `from app.ingest.records import CIN_FORMAT, normalise_cin` and extend `IdentityFinding`:
  ```python
      cin: str | None = Field(
          default=None,
          description="the Corporate Identity Number of a COMPANY funder, 21 characters as the MCA prints "
                      "it. A trust or society has none. Never guess one, and never put a parent company's "
                      "CIN on its foundation",
      )
      aliases: list[str] = Field(
          default_factory=list,
          description="other names it files or is reported under, e.g. the name on its MCA filings",
      )
      intake_mode: (
          Literal["open", "rolling", "invitation_only", "rfp_only", "closed", "unknown"] | None
      ) = Field(default=None, description="how an NGO can approach it at all, as it says so")
      funds_external: bool | None = Field(
          default=None, description="what it SAYS about funding other organisations; null means it does not say"
      )
      typical_duration_months: int | None = Field(default=None, gt=0, description="a stated typical grant duration")
      grant_size_min: Money | None = Field(default=None, description="the bottom of a stated grant band")
      grant_size_max: Money | None = Field(default=None, description="the top of a stated grant band")

      @field_validator("cin")
      @classmethod
      def _cin(cls, v: str | None) -> str | None:
          if v is None:
              return v
          cin = normalise_cin(v)
          if not CIN_FORMAT.fullmatch(cin):
              raise ValueError(
                  f"{v!r} is not a CIN: 21 characters, e.g. 'L65110GJ1993PLC020769'. Never guess one"
              )
          return cin

      @model_validator(mode="after")
      def _band_is_the_right_way_round(self) -> IdentityFinding:
          lo, hi = self.grant_size_min, self.grant_size_max
          if lo is not None and hi is not None and hi.inr < lo.inr:
              raise ValueError(f"grant band is inverted: {lo.text} above {hi.text}")
          return self
  ```
- [ ] **Step 6: Writer.** Replace `FUNDER_UPDATABLE` and `write_funder` in `writer.py`:
  ```python
  FUNDER_UPDATABLE = (
      "funder_type", "website", "section_135_bound", "parent_id", "cin",
      "intake_mode", "funds_external", "typical_duration_months", "grant_size_min", "grant_size_max",
      "source_url", "source_name", "fetched_at", "as_of", "content_hash", "extractor_version",
  )


  def new_aliases(held: list[str], found: list[str], name: str) -> list[str]:
      """Spellings not already held and not the funder's own name, case-insensitively, in found order."""
      seen = {a.lower() for a in held} | {name.lower()}
      out: list[str] = []
      for alias in found:
          if alias.lower() not in seen:
              seen.add(alias.lower())
              out.append(alias)
      return out


  async def write_funder(
      conn: Any, rec: FunderRecord, match: Match, *, parent_id: int | None = None
  ) -> tuple[str, int, dict]:
      """Returns (status, funder_id, changes). Status is added | updated | matched.

      parent_id is resolved by the caller, which can report a parent it could not find; this writer
      only stores what it is given. Aliases are appended, never replaced: a spelling one source used
      is still a way to find this funder.
      """
      proposed = {
          "funder_type": rec.funder_type, "website": rec.website,
          "section_135_bound": rec.section_135_bound, "parent_id": parent_id, "cin": rec.cin,
          "intake_mode": rec.intake_mode, "funds_external": rec.funds_external,
          "typical_duration_months": rec.typical_duration_months,
          "grant_size_min": rec.grant_size_min, "grant_size_max": rec.grant_size_max,
          "source_url": rec.source_url, "source_name": rec.source_name,
          "fetched_at": rec.fetched_at, "as_of": rec.as_of,
          "content_hash": rec.content_hash, "extractor_version": rec.extractor_version,
      }
      if match.resolved:
          existing = await (
              await conn.execute(
                  f"SELECT name, aliases, {', '.join(FUNDER_UPDATABLE)} FROM funders WHERE id = %s",
                  (match.entity_id,),
              )
          ).fetchone()
          changes = _diff({c: existing[c] for c in FUNDER_UPDATABLE}, proposed)
          held = list(existing["aliases"] or [])
          added = new_aliases(held, rec.aliases, existing["name"])
          if not changes and not added:
              return "matched", match.entity_id, {}
          sets = [f"{c} = %s" for c in changes]
          values = [proposed[c] for c in changes]
          if added:
              sets.append("aliases = aliases || %s::text[]")
              values.append(added)
              changes["aliases"] = {"old": held, "new": [*held, *added]}
          await conn.execute(
              f"UPDATE funders SET {', '.join(sets)} WHERE id = %s", (*values, match.entity_id)
          )
          await _write_identifiers(conn, match.entity_id, rec)
          return "updated", match.entity_id, changes

      slug = await _free_slug(conn, slugify(rec.name))
      row = await (
          await conn.execute(
              "INSERT INTO funders (slug, name, funder_type, website, section_135_bound, parent_id, cin, "
              "aliases, intake_mode, funds_external, typical_duration_months, grant_size_min, "
              "grant_size_max, registry_status, source_url, source_name, fetched_at, as_of, "
              "content_hash, extractor_version) "
              "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'placeholder', "
              "%s, %s, %s, %s, %s, %s) RETURNING id",
              (slug, rec.name, rec.funder_type, rec.website, rec.section_135_bound, parent_id, rec.cin,
               new_aliases([], rec.aliases, rec.name), rec.intake_mode, rec.funds_external,
               rec.typical_duration_months, rec.grant_size_min, rec.grant_size_max,
               rec.source_url, rec.source_name, rec.fetched_at, rec.as_of,
               rec.content_hash, rec.extractor_version),
          )
      ).fetchone()
      await _write_identifiers(conn, row["id"], rec)
      return "added", row["id"], {"name": {"old": None, "new": rec.name}}
  ```
- [ ] **Step 7: `funder_from`.** In `promote.py`, inside the `FunderRecord(...)` call add (keep `identifiers=` for now):
  ```python
              cin=(identity or {}).get("cin"),
              aliases=(identity or {}).get("aliases") or [],
              intake_mode=(identity or {}).get("intake_mode"),
              funds_external=(identity or {}).get("funds_external"),
              typical_duration_months=(identity or {}).get("typical_duration_months"),
              grant_size_min=to_inr((identity or {}).get("grant_size_min")),
              grant_size_max=to_inr((identity or {}).get("grant_size_max")),
  ```
- [ ] **Step 8: Run.** `bt tests/test_funder_identity.py -q` → all pass. `bt -m "'not integration'" -q` → 0 failed (`test_the_model_carries_exactly_what_the_table_expects[identity]` and `test_every_finding_field_reaches_a_record[identity]` pass because catalog, finding and record moved together). `cd backend && ruff check .` → clean.
- [ ] **Step 9: Commit.** `git add -A backend && git commit -m "feat(ingest): a funder's CIN, aliases and stated posture reach research and the writer" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 4: The funder matcher reads `funders.cin` and `funders.aliases`

**Files:**
- Modify: `backend/app/ingest/matcher.py` (`resolve_funder` lines 68-130; `resolve_org` docstring lines 134-141)
- Modify: `backend/app/ingest/writer.py` (new `cin_holder`)
- Modify: `backend/app/ingest/promote.py` (`_promote_funder` lines 674-699; new `_reconcile_with_stored`)
- Modify: `backend/tests/test_funder_identity.py`

**Interfaces:**
- Produces: `resolve_funder(conn, name: str, cin: str | None = None) -> Match` (method names unchanged: `"identifier"` now means a CIN hit, so `MERGEABLE` and its test stay as they are); `writer.cin_holder(conn, cin: str) -> dict | None` (`{"id", "name"}`); `promote._reconcile_with_stored(conn, record: FunderRecord, match: Match, report: dict) -> FunderRecord`.
- Consumes: `FunderRecord.cin` (Task 3). `runner._write_csr_year` and `promote._parent` call `resolve_funder(conn, name)` and are unaffected.

- [ ] **Step 1: Failing tests** (append to `test_funder_identity.py`):
  ```python
  class TestTheFunderMatcher:
      async def test_a_cin_resolves_the_same_company(self, recording_conn):
          from app.ingest.matcher import resolve_funder

          conn = recording_conn([{"id": 3, "name": "Axis Bank Limited", "aliases": []}])
          assert await resolve_funder(conn, "Axis Bank Ltd", cin=CIN) == Match("identifier", 3)
          assert "FROM funders WHERE cin = %s" in conn.sql[0]

      async def test_a_foundation_carrying_its_parents_cin_is_not_merged(self, recording_conn):
          """D7: filings attach to the parent, so a foundation's research often carries its CIN."""
          from app.ingest.matcher import resolve_funder

          conn = recording_conn([{"id": 3, "name": "Axis Bank Limited", "aliases": []}, {"id": 9}])
          assert await resolve_funder(conn, "Axis Bank Foundation", cin=CIN) == Match("exact", 9)

      async def test_an_alias_resolves(self, recording_conn):
          from app.ingest.matcher import resolve_funder

          conn = recording_conn([None, [{"id": 4}]])
          assert await resolve_funder(conn, "ABF") == Match("alias", 4)
          assert any("unnest(aliases)" in q for q in conn.sql)

      async def test_an_alias_two_funders_share_resolves_neither(self, recording_conn):
          from app.ingest.matcher import resolve_funder

          conn = recording_conn([None, [{"id": 4}, {"id": 5}], [], []])
          assert (await resolve_funder(conn, "ABF")).method == "none"

      async def test_no_query_reads_funder_identifiers(self, recording_conn):
          from app.ingest.matcher import resolve_funder

          conn = recording_conn([None, None, [], [], []])
          await resolve_funder(conn, "Nobody Limited", cin=CIN)
          assert not any("funder_identifiers" in q for q in conn.sql)

      async def test_resolve_org_still_reads_org_identifiers(self, recording_conn):
          from app.ingest.matcher import resolve_org

          conn = recording_conn([{"org_id": 5}])
          assert await resolve_org(conn, "Goonj", {"12a": "AAATG5219M"}) == Match("identifier", 5)
          assert "FROM org_identifiers" in conn.sql[0]


  class TestWhatTheFundersRowWouldRefuse:
      async def test_a_cin_held_by_another_funder_is_held_back(self, recording_conn):
          from app.ingest.promote import _reconcile_with_stored

          conn = recording_conn([{"id": 3, "name": "Axis Bank Limited"}])
          report = {"held": []}
          rec = FunderRecord(name="Axis Bank Foundation", cin=CIN, **prov())
          out = await _reconcile_with_stored(conn, rec, Match("exact", 9), report)
          assert out.cin is None
          assert "[funder:3]" in report["held"][0]

      async def test_a_cin_on_its_own_row_is_kept(self, recording_conn):
          from app.ingest.promote import _reconcile_with_stored

          conn = recording_conn([{"id": 3, "name": "Axis Bank Limited"}])
          rec = FunderRecord(name="Axis Bank Limited", cin=CIN, **prov())
          assert (await _reconcile_with_stored(conn, rec, Match("identifier", 3), {"held": []})).cin == CIN

      async def test_an_inverted_band_against_the_stored_one_is_held(self, recording_conn):
          from app.ingest.promote import _reconcile_with_stored

          conn = recording_conn([{"grant_size_min": None, "grant_size_max": 1_000_000}])
          report = {"held": []}
          rec = FunderRecord(name="Axis Bank Foundation", grant_size_min=5_000_000.0, **prov())
          out = await _reconcile_with_stored(conn, rec, Match("exact", 9), report)
          assert out.grant_size_min is None and "inverts" in report["held"][0]
  ```
  Run `bt tests/test_funder_identity.py -q` → failures (`cin` keyword, `_reconcile_with_stored` missing).
- [ ] **Step 2: Matcher.** Replace the head of `resolve_funder` through the alias step (lines 68-95):
  ```python
  # Words that make a name a foundation or trust rather than the company itself. A CIN match is only
  # the same organisation when both names are on the same side of this line.
  _FOUNDATION_WORDS = frozenset({
      "foundation", "foundations", "trust", "trusts", "charitable", "charities", "society",
      "sansthan", "samiti",
  })


  def _is_foundation(name: str) -> bool:
      return bool(set(re.findall(r"[a-z0-9]+", name.lower())) & _FOUNDATION_WORDS)


  def _same_organisation(name: str, held: str, aliases: list[str]) -> bool:
      return any(
          n.lower() == name.lower()
          or (same_but_for_boilerplate(name, n) and _is_foundation(name) == _is_foundation(n))
          for n in (held, *aliases)
      )


  async def resolve_funder(conn: Any, name: str, cin: str | None = None) -> Match:
      """Four steps in order: CIN, exact name, alias, trigram.

      A CIN hit must also look like the same organisation. Filings attach to the corporate parent
      (D7), so a foundation's research often carries its parent's CIN, and merging on the number
      alone would fold Axis Bank Foundation into Axis Bank Limited. Such a hit falls through to the
      name steps, and promotion holds the CIN back for a person.
      """
      if cin:
          row = await (
              await conn.execute(
                  "SELECT id, name, aliases FROM funders WHERE cin = %s", (cin.strip().upper(),)
              )
          ).fetchone()
          if row and _same_organisation(name, row["name"], row["aliases"] or []):
              return Match("identifier", row["id"])

      row = await (
          await conn.execute("SELECT id FROM funders WHERE lower(name) = lower(%s)", (name,))
      ).fetchone()
      if row:
          return Match("exact", row["id"])

      # One funder per spelling. Two rows sharing an alias is exactly the case a person settles.
      rows = await (
          await conn.execute(
              "SELECT id FROM funders WHERE EXISTS "
              "(SELECT 1 FROM unnest(aliases) AS a WHERE lower(a) = lower(%s)) ORDER BY id LIMIT 2",
              (name,),
          )
      ).fetchall()
      if len(rows) == 1:
          return Match("alias", rows[0]["id"])
  ```
  (the boilerplate and trigram steps below are unchanged). In `resolve_org`'s docstring replace the sentence about `funder_identifiers` with: "`resolve_funder` has an alias step reading `funders.aliases`; `orgs` has no such column, so there is no alias step to port."
- [ ] **Step 3: `cin_holder`** in `writer.py` (after `_free_slug`):
  ```python
  async def cin_holder(conn: Any, cin: str) -> dict | None:
      """The funder already holding this CIN, if any. funders.cin is UNIQUE."""
      return await (
          await conn.execute("SELECT id, name FROM funders WHERE cin = %s", (cin,))
      ).fetchone()
  ```
- [ ] **Step 4: Promote.** Import `cin_holder`, add before `_promote_funder`:
  ```python
  async def _reconcile_with_stored(
      conn: Any, record: FunderRecord, match: Match, report: dict[str, Any]
  ) -> FunderRecord:
      """Drop what the funders row's own constraints would refuse, and say so.

      A constraint violation is not a ValidationError: it aborts this funder's whole promotion, every
      fact with it. funders.cin is UNIQUE and funders_grant_band orders the band.
      """
      update: dict[str, Any] = {}
      if record.cin:
          holder = await cin_holder(conn, record.cin)
          if holder is not None and holder["id"] != match.entity_id:
              report["held"].append(
                  f"CIN {record.cin} is already recorded on {holder['name']!r} [funder:{holder['id']}], "
                  f"so it is not written on {record.name!r}. One CIN is one company: a foundation's "
                  f"research often carries its parent's CIN, and the parent is its own row linked by "
                  f"parent_id."
              )
              update["cin"] = None
      one_sided = (record.grant_size_min is None) != (record.grant_size_max is None)
      if match.entity_id is not None and one_sided:
          stored = await (
              await conn.execute(
                  "SELECT grant_size_min, grant_size_max FROM funders WHERE id = %s", (match.entity_id,)
              )
          ).fetchone()
          lo = record.grant_size_min if record.grant_size_min is not None else stored["grant_size_min"]
          hi = record.grant_size_max if record.grant_size_max is not None else stored["grant_size_max"]
          if lo is not None and hi is not None and float(hi) < float(lo):
              report["held"].append(
                  f"grant band for {record.name!r}: the research inverts the stored band "
                  f"({stored['grant_size_min']} to {stored['grant_size_max']}). Not written — a person "
                  f"decides which is current."
              )
              update.update(grant_size_min=None, grant_size_max=None)
      return record.model_copy(update=update) if update else record
  ```
  and in `_promote_funder` replace `match = await resolve_funder(conn, record.name, record.identifiers)` with `match = await resolve_funder(conn, record.name, record.cin)`; after the trigram early return add `record = await _reconcile_with_stored(conn, record, match, report)`. Add `from app.ingest.matcher import Match, resolve_funder, resolve_org`.
- [ ] **Step 5: Run.** `bt tests/test_funder_identity.py tests/test_ingest.py -q` → pass (`TestAParentIsLinkedOnlyWhenTheMatcherWouldMerge` unchanged). Full unit tier → 0 failed. `ruff check .` clean.
- [ ] **Step 6: Commit.** `git add -A backend && git commit -m "feat(ingest): match funders on funders.cin and funders.aliases" -m "A CIN hit must be the same organisation, so a foundation carrying its parent's CIN is not merged into the parent (D7); promotion holds back a CIN or band the funders row would refuse." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 5: `funder_identifiers` leaves the code

**Files:**
- Modify: `backend/app/ingest/expectations.py` (`CONCEPTS["identifier"]` line 69; `REQUIRED["identifier"]` line 207; comment lines 29-34)
- Modify: `backend/app/ingest/research_records.py` (delete `IdentifierFinding` 129-132; union 441-447; `FINDING_MODELS` 449-458; `OrgIdentifierFinding` docstring 411)
- Modify: `backend/app/ingest/records.py` (delete `FunderRecord.identifiers` + `_known_types` 75-90; `OrgRecord.identifiers` docstring 351)
- Modify: `backend/app/ingest/writer.py` (delete `_write_identifiers` 200-207 and both calls; `_write_org_identifiers` docstring 673-674)
- Modify: `backend/app/ingest/promote.py` (`CONCEPT_RECORDS`, `RENAMED`, `funder_from`, `promote()` skipped count)
- Modify: `backend/app/ingest/tools/catalog_tools.py` (dossier head line 53; delete section 109-115; `_reject_unknown` docstring 287)
- Modify: `backend/app/ingest/brief.py` (legacy titles)
- Modify: `backend/tests/test_ingest.py` (line 160 test; line 849 `apart`)
- Modify: `backend/tests/test_funder_identity.py`

**Interfaces:**
- Produces: `promote.FOLDED = frozenset({"identifier"})`; `brief.LEGACY_TITLES: dict[str, str]`. `"identifier"` is no longer a concept, finding model, record field or `RENAMED` key.

- [ ] **Step 1: Failing tests.** In `backend/tests/test_ingest.py` replace `test_an_unknown_identifier_type_is_rejected` (line 159-161) with:
  ```python
      def test_a_funder_record_has_no_identifier_map(self):
          # funder_identifiers is gone (0031): a CIN and other spellings are columns on funders.
          with pytest.raises(ValidationError, match="identifiers"):
              FunderRecord(name="Acme", identifiers={"cin": "L12345MH2001PLC123456"}, **prov())
  ```
  and change `apart` (line 849) to `{"identity", "csr_year", "program", "document", "org_identity", "org_identifier"}`. Append to `test_funder_identity.py`:
  ```python
  class TestSavedResearchFromBefore0031:
      ROW = {"slug": "axis-bank", "entity_name": "Axis Bank", "canonical_name": "Axis Bank Limited",
             "website": None, "researched_at": NOW}

      def ident(self, id_type, id_value):
          return {"concept": "identifier", "id_type": id_type, "id_value": id_value,
                  "evidence": "The annual report lists the company's registration details.",
                  "source_url": "https://a.b/c", "confidence": "high"}

      def test_saved_identifier_findings_fold_into_the_record(self):
          from app.ingest.promote import funder_from

          rec = funder_from(self.ROW, [self.ident("cin", "l65110gj1993plc020769"),
                                       self.ident("name", "UTI Bank Limited"),
                                       self.ident("domain", "axisbank.com"),
                                       self.ident("pan", "AAACU2414K")])
          assert rec.cin == CIN and rec.aliases == ["UTI Bank Limited"]
          assert rec.website == "https://axisbank.com"

      def test_a_malformed_saved_cin_is_dropped_not_fatal(self):
          from app.ingest.promote import funder_from

          assert funder_from(self.ROW, [self.ident("cin", "not-a-cin")]).cin is None

      def test_identifier_is_no_longer_a_concept(self):
          from app.ingest.expectations import CONCEPTS
          from app.ingest.research_records import FINDING_MODELS

          assert "identifier" not in CONCEPTS and "identifier" not in FINDING_MODELS

      def test_a_saved_identifier_still_renders_in_the_brief(self):
          from app.ingest.brief import entity_markdown

          row = {**self.ROW, "researched_on": "2026-10-01", "status": "partial", "stopped_reason": "x",
                 "summary": "A bank.", "goals": [], "not_found": [], "sources_read": [], "schema_version": 2,
                 "findings": [self.ident("cin", CIN)]}
          md = entity_markdown(row)
          assert "saved before 0031" in md and CIN in md

      async def test_the_dossier_head_shows_cin_and_aliases(self, recording_conn, recording_pool, monkeypatch):
          from app.ingest.tools import catalog_tools

          conn = recording_conn([[{"id": 1, "name": "Axis Bank Limited", "slug": "axis-bank", "cin": CIN,
                                   "aliases": ["UTI Bank Limited"]}]])
          monkeypatch.setattr(catalog_tools, "get_pool", lambda: recording_pool(conn))
          out = await catalog_tools.funder_dossier.ainvoke({"name": "Axis Bank", "entity_kind": "funder"})
          assert f"cin={CIN}" in out
          assert "cin, aliases" in conn.sql[0]
          assert not any("funder_identifiers" in q for q in conn.sql)
  ```
  Run → failures.
- [ ] **Step 2: Remove the concept.** `expectations.py`: delete the `"identifier"` entries in `CONCEPTS` and `REQUIRED`; replace the comment at lines 29-34 with: "Which kind of entity offers a concept. programs, metrics, contacts and documents each carry both an org_id and a funder_id, so they are the same concept either way and only the foreign key changes. Everything else hangs off one or the other: an NGO's 12A, 80G and FCRA live in org_identifiers, and a funder keeps only a CIN, on its own row." `research_records.py`: delete `IdentifierFinding`, its union member and `FINDING_MODELS` entry; `OrgIdentifierFinding` docstring → `"""12A, 80G and FCRA live here and nowhere else — a funder keeps only a CIN."""`.
- [ ] **Step 3: Records and writer.** Delete `FunderRecord.identifiers` and `_known_types`; `OrgRecord.identifiers` docstring → `"""12A, 80G and FCRA; a funder has no room for them."""`. Delete `_write_identifiers` and its two calls in `write_funder`. `_write_org_identifiers` docstring → `"""12A, 80G and FCRA among them — the registrations only an NGO carries. `verified` is left at its default: research is not verification."""`.
- [ ] **Step 4: Promote.** Remove `"identifier"` from `CONCEPT_RECORDS` and the two `("identifier", …)` `RENAMED` entries. Import `CIN_FORMAT, normalise_cin` from records. Replace `funder_from`:
  ```python
  # Concepts from before 0031 that promotion still reads, so they are not reported as "no writer".
  FOLDED = frozenset({"identifier"})


  def _legacy_identifiers(findings: list[dict[str, Any]]) -> dict[str, list[str]]:
      """`identifier` findings saved before 0031, by type. Only cin, name and domain have a home now (D1)."""
      out: dict[str, list[str]] = {}
      for f in findings:
          if f.get("concept") == "identifier" and f.get("id_value"):
              out.setdefault(f.get("id_type") or "", []).append(str(f["id_value"]).strip())
      return out


  def funder_from(row: dict[str, Any], findings: list[dict[str, Any]]) -> FunderRecord | None:
      """One funder record, from the identity finding and any identifiers saved before 0031."""
      identity = next((f for f in findings if f["concept"] == "identity"), None)
      legacy = [f for f in findings if f["concept"] == "identifier"]
      anchor = identity or (legacy[0] if legacy else None)
      if anchor is None:
          return None
      ident = identity or {}
      old = _legacy_identifiers(legacy)
      cins = [c for c in map(normalise_cin, old.get("cin", [])) if CIN_FORMAT.fullmatch(c)]
      domains = old.get("domain", [])
      try:
          return FunderRecord(
              name=ident.get("name") or row["canonical_name"] or row["entity_name"],
              funder_type=ident.get("funder_type"),
              website=ident.get("website") or row.get("website")
              or (f"https://{domains[0]}" if domains else None),
              section_135_bound=ident.get("section_135_bound"),
              parent_name=ident.get("parent_name"),
              cin=ident.get("cin") or (cins[0] if cins else None),
              aliases=[*(ident.get("aliases") or []), *old.get("name", [])],
              intake_mode=ident.get("intake_mode"),
              funds_external=ident.get("funds_external"),
              typical_duration_months=ident.get("typical_duration_months"),
              grant_size_min=to_inr(ident.get("grant_size_min")),
              grant_size_max=to_inr(ident.get("grant_size_max")),
              as_of=None,
              **_provenance(anchor, row["researched_at"]),
          )
      except ValueError as exc:
          logger.info("funder record refused for %s: %s", row["slug"], exc)
          return None
  ```
  In `promote()`, change the skipped loop's condition to `if concept not in PROMOTABLE and concept not in FOLDED:`. In `_promote_funder` change the reason text to `"no identity finding to build a funder from"`.
- [ ] **Step 5: Dossier.** In `catalog_tools.py` set the funder `head` to `"id, name, slug, registry_status, funder_type, website, parent_id, section_135_bound, cin, aliases, intake_mode, funds_external, typical_duration_months, grant_size_min, grant_size_max"`, delete the `funder_identifiers` section, and in `_reject_unknown`'s docstring replace "which is how an NGO ended up aimed at funder_identifiers" with "which is how an NGO ended up aimed at the funder tables".
- [ ] **Step 6: Brief.** In `brief.py` after `_ELIGIBILITY_KINDS`:
  ```python
  # Concepts saved before 0031. Rendered so old research keeps its facts on the page; never promoted
  # as themselves (promote.funder_from folds `identifier` into the funder record).
  LEGACY_TITLES: dict[str, str] = {
      "identifier": "Registrations and identifiers (saved before 0031)",
  }
  ```
  and in `entity_markdown` iterate `{**CONCEPT_TITLES, **LEGACY_TITLES}.items()`; in the not-found line use `{**CONCEPT_TITLES, **LEGACY_TITLES}.get(c, c)`. The `identifier` branch of `headline` stays.
- [ ] **Step 7: Run.** `bt tests/test_funder_identity.py tests/test_ingest.py -q` → pass, including `TestTheOrgWriter` unchanged. Full unit tier → 0 failed. `ruff check .` clean.
- [ ] **Step 8: Commit.** `git add -A backend && git commit -m "refactor(ingest): funder_identifiers leaves the code" -m "Saved identifier findings fold into the funder record (cin, aliases, website) instead of being dropped; the brief still renders them." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 6: Funder detail API and frontend type

**Files:**
- Modify: `backend/app/repositories/funders.py` (delete lines 81-87)
- Modify: `backend/app/schemas/funders.py` (import line 5; `FunderDetail` lines 33-38)
- Modify: `frontend/lib/api/types.ts` (lines 50-53)
- Modify: `backend/tests/test_funders.py`

**Interfaces:**
- Produces: `FunderDetail.cin: str | None`, `FunderDetail.aliases: list[str]`; no `identifiers`. `IdentifierOut` stays in `schemas/orgs.py` for `OrgDetail`.

- [ ] **Step 1: Failing test** (append to `test_funders.py`):
  ```python
  async def test_detail_carries_cin_and_aliases_not_an_identifier_list(client_for, monkeypatch):
      async def fake(pool, slug_or_id):
          return {**ROW, "section_135_bound": True, "cin": "L65110GJ1993PLC020769",
                  "aliases": ["UTI Bank Limited"], "tags": [], "locations": [], "contacts": []}

      monkeypatch.setattr("app.api.routes.funders.repo.get_funder", fake)
      async with client_for(funders_api.router) as client:
          body = (await client.get("/api/funders/axis-bank-foundation")).json()
      assert body["cin"] == "L65110GJ1993PLC020769"
      assert body["aliases"] == ["UTI Bank Limited"]
      assert "identifiers" not in body
  ```
  `bt tests/test_funders.py -q` → fails on `body["cin"]`.
- [ ] **Step 2: Implement.** `schemas/funders.py`: `from app.schemas.orgs import LocationRef, TagRef`; `FunderDetail`:
  ```python
  class FunderDetail(FunderListItem):
      section_135_bound: bool | None = None
      cin: str | None = None            # corporate funders only (0031)
      aliases: list[str] = []
      tags: list[TagRef] = []
      locations: list[LocationRef] = []
      contacts: list[ContactOut] = []
  ```
  `repositories/funders.py`: delete the `row["identifiers"] = …` query (`SELECT f.*` already returns `cin` and `aliases`). `frontend/lib/api/types.ts`:
  ```ts
  export type FunderDetail = FunderListItem & {
    section_135_bound: boolean | null; cin: string | null; aliases: string[];
    tags: TagRef[]; locations: LocationRef[]; contacts: Contact[];
  };
  ```
- [ ] **Step 3: Run.** `bt tests/test_funders.py -q` → pass. `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit` → exit 0 (no component reads `funder.identifiers`; `org.identifiers` is untouched).
- [ ] **Step 4: Commit.** `git add backend/app/repositories/funders.py backend/app/schemas/funders.py backend/tests/test_funders.py frontend/lib/api/types.ts && git commit -m "feat(api): funder detail carries cin and aliases, not funder_identifiers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 7: Seed stops writing `funder_identifiers`

**Files:**
- Modify: `seed/seed.py` (delete lines 354-363)

**Interfaces:** none. `seed.py:316-328` already writes `funders.website`, which is where the domain rows came from.

- [ ] **Step 1:** Delete the `if funder.get("website"): … INSERT INTO funder_identifiers …` block.
- [ ] **Step 2: Verify on the scratch DB.**
  ```bash
  docker run --rm --network sangam_default -v "$WT":/w -w /w -e DATABASE_URL="host=postgres user=sangam password=sangam dbname=sangam_fc" --entrypoint python sangam-backend:latest -m seed.seed
  source /Users/vinod/GitHub/fc-env.sh && psql_fc -tc "select count(*) from funders where website is not null"
  ```
  Expected: the seed completes without `relation "funder_identifiers" does not exist`; the count is ≥ 4. (If `seed.seed` reads its DSN from another variable, use the one named at the top of `seed/seed.py`.)
- [ ] **Step 3: Commit.** `git add seed/seed.py && git commit -m "chore(seed): the website is the domain; stop writing funder_identifiers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 8: `funder_csr_years.local_area_spent`

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (funder_csr_years columns, after `excess_spent`)
- Modify: `backend/app/ingest/research_records.py` (`CsrYearFinding` 135-150), `records.py` (`FunderCsrYearRecord` 93-135), `writer.py` (`CSR_YEAR_UPDATABLE` 47-52, `write_csr_year` 212-221), `promote.py` (`csr_years_from`), `brief.py` (csr_year money keys), `tools/catalog_tools.py` (csr_years section)
- Modify: `backend/tests/test_funder_identity.py` → no; add to `backend/tests/test_ingest.py` class `TestNothingResearchedIsSilentlyDropped`

**Interfaces:** Produces `local_area_spent` on catalog column, finding (`Money | None`), record (`float | None`, INR), `CSR_YEAR_UPDATABLE`.

- [ ] **Step 1: Failing test** (append in `TestNothingResearchedIsSilentlyDropped`):
  ```python
      def test_local_area_spend_reaches_the_year(self):
          from app.ingest.promote import csr_years_from

          row = {"slug": "acme", "entity_name": "Acme Ltd", "canonical_name": None, "researched_at": NOW}
          finding = {"concept": "csr_year", "fiscal_year": "FY2023-24",
                     "local_area_spent": {"value": 2.5, "unit": "crore", "text": "Rs 2.5 crore"},
                     "evidence": "Rs 2.5 crore was spent in the local areas of operation in FY2023-24.",
                     "source_url": "https://a.b/c", "confidence": "high"}
          assert csr_years_from(row, [finding])[0].local_area_spent == 25_000_000
          assert "local_area_spent" in CSR_YEAR_UPDATABLE
  ```
- [ ] **Step 2: Implement.** Catalog: `Column("local_area_spent", "numeric", note="spent in the local area of the company's operations, INR, as the MCA return reports it")`. Finding: `local_area_spent: Money | None = Field(default=None, description="spent in the local area of its operations, as the MCA return reports it")`. Record: `local_area_spent: float | None = None` and add it to the `_non_negative` validator's field list. Writer: add `"local_area_spent"` to `CSR_YEAR_UPDATABLE` after `excess_spent`, and `"local_area_spent": rec.local_area_spent` to `proposed`. `csr_years_from`: `local_area_spent=to_inr(f.get("local_area_spent")),`. Brief: add `"local_area_spent"` to the csr_year money tuple. Dossier csr_years SELECT: add `local_area_spent`.
- [ ] **Step 3: Run.** Full unit tier → 0 failed (`[csr_year]` parametrisations pass because catalog, finding and record moved together).
- [ ] **Step 4: Commit.** `git add -A backend && git commit -m "feat(ingest): funder_csr_years.local_area_spent" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 9: A concept may own part of a table; classifications resolve or are held; refusals are reported

**Files:**
- Modify: `backend/app/ingest/expectations.py` (`ConceptSpec` 50-60; `expected_fields` 342-366)
- Modify: `backend/app/ingest/tools/catalog_tools.py` (`research_goals` 360-370; `_held_per_concept` 382-413)
- Modify: `backend/app/ingest/taxonomy.py` (append)
- Modify: `backend/app/ingest/promote.py` (`_validated` 145-157 and its three callers)
- Create: `backend/tests/test_funder_activity.py`

**Interfaces:**
- Produces: `ConceptSpec.row_filter: tuple[str, str] | None = None`, `ConceptSpec.columns: tuple[str, ...] | None = None`; `expected_fields()` and `_held_per_concept()` read `CONCEPTS[concept]`; `taxonomy.DOMAINS`, `taxonomy.NO_THEMES`, `taxonomy.resolve_classification(conn, domain: str | None, theme: str | None) -> tuple[int | None, int | None, list[str]]`; `promote._validated(findings, concept, report: dict | None = None)`.

- [ ] **Step 1: Failing tests.** Create `backend/tests/test_funder_activity.py`:
  ```python
  """funder_activity: four concepts on one table, inferred classifications, and the writers."""

  from __future__ import annotations

  from datetime import UTC, datetime

  import pytest

  from app.agent.tools.sql.catalog import CATALOG
  from app.ingest import expectations
  from app.ingest.expectations import CONCEPTS, ConceptSpec, expected_fields

  NOW = datetime(2026, 10, 7, tzinfo=UTC)


  class _CountConn:
      """Answers every count query with nothing held, recording SQL and params."""

      def __init__(self):
          self.sql, self.params = [], []

      async def execute(self, sql, params=None):
          self.sql.append(" ".join(sql.split()))
          self.params.append(params)
          return self

      async def fetchone(self):
          return {"n": 0, "years": []}


  class TestAConceptCanOwnPartOfATable:
      def probe(self, monkeypatch):
          spec = ConceptSpec("funder_csr_years", "Probe", row_filter=("fiscal_year", "FY2023-24"),
                             columns=("fiscal_year", "total_spent"))
          monkeypatch.setitem(expectations.CONCEPTS, "probe", spec)

      def test_only_its_columns_are_targets(self, monkeypatch):
          self.probe(monkeypatch)
          assert [f.name for f in expected_fields("probe")] == ["fiscal_year", "total_spent"]

      async def test_its_rows_are_counted_through_the_filter(self, monkeypatch):
          from app.ingest.tools.catalog_tools import _held_per_concept

          self.probe(monkeypatch)
          conn = _CountConn()
          await _held_per_concept(conn, 7, "funder")
          i = next(i for i, q in enumerate(conn.sql) if "AND fiscal_year = %s" in q)
          assert "FROM funder_csr_years WHERE funder_id = %s AND fiscal_year = %s" in conn.sql[i]
          assert conn.params[i] == (7, "FY2023-24")

      def test_every_listed_column_exists(self):
          for name, spec in CONCEPTS.items():
              if spec.columns is None:
                  continue
              have = {c.name for c in CATALOG[spec.table].columns}
              assert set(spec.columns) <= have, f"{name}: {set(spec.columns) - have}"

      def test_concepts_sharing_a_table_own_distinct_rows(self):
          by_table: dict[str, list[ConceptSpec]] = {}
          for spec in CONCEPTS.values():
              by_table.setdefault(spec.table, []).append(spec)
          for table, specs in by_table.items():
              if len(specs) < 2:
                  continue
              assert sum(s.row_filter is None for s in specs) <= 1, table
              filters = [s.row_filter for s in specs if s.row_filter]
              assert len(filters) == len(set(filters)), table

      def test_a_concept_never_names_a_field_twice(self):
          for name in CONCEPTS:
              names = [f.name for f in expected_fields(name)]
              assert len(names) == len(set(names)), name


  class TestClassificationResolves:
      async def test_a_domain_alone(self, recording_conn):
          from app.ingest.taxonomy import resolve_classification

          assert await resolve_classification(recording_conn([{"id": 11}]), "others", None) == (11, None, [])

      async def test_a_missing_domain_holds_the_line(self, recording_conn):
          from app.ingest.taxonomy import resolve_classification

          domain_id, theme_id, why = await resolve_classification(recording_conn([None]), "environment", None)
          assert (domain_id, theme_id) == (None, None) and "taxonomy-seed" in why[0]

      async def test_a_theme_under_its_domain(self, recording_conn):
          from app.ingest.taxonomy import resolve_classification

          conn = recording_conn([{"id": 11}, [{"id": 40, "domain": "livelihoods"}]])
          assert await resolve_classification(conn, "livelihoods", "skilling") == (11, 40, [])

      async def test_a_theme_under_another_domain_is_dropped_not_guessed(self, recording_conn):
          from app.ingest.taxonomy import resolve_classification

          conn = recording_conn([{"id": 11}, [{"id": 40, "domain": "livelihoods"}]])
          domain_id, theme_id, why = await resolve_classification(conn, "education", "skilling")
          assert (domain_id, theme_id) == (11, None) and "belongs to 'livelihoods'" in why[0]

      async def test_an_ambiguous_theme_is_dropped(self, recording_conn):
          from app.ingest.taxonomy import resolve_classification

          conn = recording_conn([{"id": 11}, [{"id": 40, "domain": "health"}, {"id": 41, "domain": "health"}]])
          assert (await resolve_classification(conn, "health", "screening"))[1] is None


  def test_a_refused_finding_is_reported_not_just_logged():
      from app.ingest.promote import _validated

      report = {"held": []}
      out = _validated([{"concept": "partner", "fiscal_year": "FY24", "partner_name": "Harsha Trust",
                         "evidence": "Harsha Trust was named as a partner in the annual report.",
                         "source_url": "https://a.b/c", "confidence": "high"}], "partner", report)
      assert out == []
      assert report["held"][0].startswith("partner finding refused (fiscal_year)")
  ```
  `bt tests/test_funder_activity.py -q` → failures.
- [ ] **Step 2: `ConceptSpec` and `expected_fields`.** Add to the dataclass:
  ```python
      # A concept that shares its table with others: the rows it owns, e.g. ("kind", "spend"), and the
      # columns it may fill. None means the whole table, as before. Read by expected_fields(), by
      # research_goals' counts and by the writers, so the three cannot disagree about which rows are whose.
      row_filter: tuple[str, str] | None = None
      columns: tuple[str, ...] | None = None
  ```
  In `expected_fields`, replace the first two lines with
  ```python
      spec = CONCEPTS[concept]
      table = CATALOG[spec.table]
  ```
  and add as the first statement in the loop body after `name = column.name`:
  ```python
          if spec.columns is not None and name not in spec.columns:
              continue
  ```
- [ ] **Step 3: `_held_per_concept` and `research_goals`.** Import `CONCEPTS` in `catalog_tools.py`. In `_held_per_concept`:
  ```python
      for concept in concepts_for(entity_kind):
          spec = CONCEPTS[concept]
          table = spec.table
          if table == entity_table:
              out[concept] = (1, [])
              continue
          has_year = any(c.name == "fiscal_year" for c in CATALOG[table].columns)
          years = ", array_agg(DISTINCT fiscal_year)" if has_year else ", '{}'::text[]"
          # Table, column and filter column come from module constants, never a caller.
          where, params = f"{fk} = %s", [entity_id]
          if spec.row_filter:
              where += f" AND {spec.row_filter[0]} = %s"
              params.append(spec.row_filter[1])
          found = await (
              await conn.execute(f"SELECT count(*) AS n{years} AS years FROM {table} WHERE {where}",
                                 tuple(params))
          ).fetchone()
          out[concept] = (found["n"], [y for y in (found["years"] or []) if y])
  ```
  In `research_goals`'s loop:
  ```python
          spec = CONCEPTS[concept]
          target = spec.table + (f" ({spec.row_filter[0]}='{spec.row_filter[1]}')" if spec.row_filter else "")
          …
          out.append(f"\n{concept} -> {target}: {state}")
  ```
- [ ] **Step 4: Classification resolver** (append to `taxonomy.py`):
  ```python
  # The five domains (D6). Environment and Others have no themes.
  DOMAINS = ("livelihoods", "health", "education", "environment", "others")
  NO_THEMES = frozenset({"environment", "others"})


  async def resolve_classification(
      conn: Any, domain: str | None, theme: str | None
  ) -> tuple[int | None, int | None, list[str]]:
      """(domain_tag_id, theme_tag_id, reasons) for an inferred classification (D11).

      Holds back rather than guesses: a domain that is not seeded holds the whole line, and a theme
      that is unknown, ambiguous or under another domain is dropped with a reason while the line is
      written with its domain.
      """
      if not domain:
          return None, None, []
      row = await (
          await conn.execute(
              "SELECT id FROM tags WHERE kind = 'domain' AND code = %s AND status <> 'deprecated'",
              (domain,),
          )
      ).fetchone()
      if row is None:
          return None, None, [
              f"domain {domain!r} is not in tags, so the line is not written. Run `make taxonomy-seed`: "
              f"the five domains come from seed/data/taxonomy/themes.json"
          ]
      if not theme:
          return row["id"], None, []
      rows = await (
          await conn.execute(
              "SELECT id, domain FROM tags WHERE kind IN ('theme', 'sub_theme') AND code = %s "
              "AND status <> 'deprecated' ORDER BY id LIMIT 2",
              (theme,),
          )
      ).fetchall()
      if len(rows) != 1:
          what = "is ambiguous" if rows else "is not in the taxonomy"
          return row["id"], None, [f"theme {theme!r} {what}; the line is written with its domain and no theme"]
      if rows[0]["domain"] != domain:
          return row["id"], None, [
              f"theme {theme!r} belongs to {rows[0]['domain']!r}, not {domain!r}; the line is written "
              f"with its domain and no theme"
          ]
      return row["id"], rows[0]["id"], []
  ```
- [ ] **Step 5: `_validated` reports.**
  ```python
  def _validated(
      findings: list[dict[str, Any]], concept: str, report: dict[str, Any] | None = None
  ) -> list[Any]:
      """Findings come back out of jsonb as plain dicts. Re-validating each one through its own model
      is what lets the writers map instead of parse, and catches a row stored before a field became
      required — which is now reported, because a finding refused here is otherwise a fact that
      silently never reaches the catalog."""
      out = []
      for f in findings:
          if f.get("concept") != concept:
              continue
          try:
              out.append(FINDING_MODELS[concept].model_validate(f))
          except ValidationError as exc:
              err = exc.errors()[0]
              where = ".".join(str(p) for p in err.get("loc", ())) or "finding"
              msg = f"{concept} finding refused ({where}): {err.get('msg')}"
              logger.info(msg)
              if report is not None:
                  report["held"].append(
                      f"{msg}. It stays on the research row; re-research it in the current shape to promote it."
                  )
      return out
  ```
  Pass `report` at the three call sites (`_write_documents`, `_write_programs`, `_write_facts`).
- [ ] **Step 6: Run.** `bt tests/test_funder_activity.py tests/test_ingest.py -q` → pass (the existing `TestResearchGoalsAsksTheRightTables` still sees `WHERE {fk} = %s`). Full unit tier → 0 failed.
- [ ] **Step 7: Commit.** `git add -A backend && git commit -m "feat(ingest): concepts can own part of a table; inferred classifications resolve or are held" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 10: Spend lines move to `funder_activity`

**Files:**
- Modify: `backend/app/ingest/expectations.py` (`CONCEPTS["csr_spend"]` 71-78; `NAMED_AS` 153-158; `REQUIRED["csr_spend"]` 209; `EXTRA["csr_spend"]` 327-338)
- Modify: `backend/app/ingest/research_records.py` (`CsrSpendFinding` 153-186; new `DomainCode`, `ClassifiedBy`, `_check_classification`)
- Modify: `backend/app/ingest/records.py` (`FunderCsrSpendRecord` 158-178)
- Modify: `backend/app/ingest/writer.py` (replace `CSR_SPEND_KEY`/`CSR_SPEND_UPDATABLE` 301-305 and `write_csr_spend` 367-384; add `FUNDER_ACTIVITY_KEY`, `FUNDER_ACTIVITY_UPDATABLE`, `_write_activity`)
- Modify: `backend/app/ingest/promote.py` (`_row_identity` 356-385; csr_spend branch 426-439; imports)
- Modify: `backend/app/ingest/brief.py` (csr_spend headline 79-83), `tools/catalog_tools.py` (spend section 145-151)
- Modify: `backend/tests/test_ingest.py` (lines 533-543 required set; 757 and 787-791 `NAMED`/fiscal-year extras; 1164-1177 `test_two_findings_on_one_row_are_distinguished`)
- Modify: `backend/tests/test_funder_activity.py`

**Interfaces:**
- Produces: `writer.FUNDER_ACTIVITY_KEY = ("funder_id", "kind", "fiscal_year", "program_id", "csr_sector_id", "state_location_id", "location_id", "designation", "project_name", "partner_name")`; `writer._write_activity(conn, key: dict, proposed: dict, document_id: int | None) -> tuple[str, dict]`; `write_csr_spend(conn, rec, funder_id, *, program_id, state_id, district_id, csr_sector_id, domain_id, theme_id, document_id)`; `FunderCsrSpendRecord.activity_kind: ClassVar[str] = "spend"`; `promote._activity_identity(kind, year, program_id, sector_id, state_id, location_id, designation, project_name, partner_name) -> tuple`; `research_records.DomainCode`, `ClassifiedBy`, `_check_classification(f)`.

- [ ] **Step 1: Failing tests** (append to `test_funder_activity.py`):
  ```python
  SPEND = {
      "concept": "csr_spend", "fiscal_year": "FY2024-25",
      "amount": {"value": 1.0, "unit": "crore", "text": "Rs 1 crore"},
      "project_name": "Financial Literacy & Inclusion", "partner_name": "Harsha Trust",
      "domain": "livelihoods", "classified_by": "project_name",
      "evidence": "Rs 1 crore was spent on Financial Literacy & Inclusion through Harsha Trust.",
      "source_url": "https://a.b/c", "confidence": "high",
  }
  ROW = {"slug": "acme", "entity_name": "Acme Ltd", "canonical_name": None, "researched_at": NOW}


  class TestSpendLines:
      def test_spend_owns_its_rows_and_only_its_columns(self):
          spec = CONCEPTS["csr_spend"]
          assert (spec.table, spec.row_filter) == ("funder_activity", ("kind", "spend"))
          names = {f.name for f in expected_fields("csr_spend")}
          assert {"domain", "theme", "classified_by", "partner_name", "outlay", "district", "sector"} <= names
          assert not names & {"kind", "classification_confirmed", "partner_kind", "name_as_printed"}

      def test_a_theme_needs_its_evidence(self):
          from pydantic import ValidationError

          from app.ingest.research_records import CsrSpendFinding

          with pytest.raises(ValidationError, match="classification_note"):
              CsrSpendFinding(**{**SPEND, "theme": "skilling"})

      def test_others_has_no_themes(self):
          from pydantic import ValidationError

          from app.ingest.research_records import CsrSpendFinding

          with pytest.raises(ValidationError, match="no themes"):
              CsrSpendFinding(**{**SPEND, "domain": "others", "theme": "skilling",
                                 "classification_note": "relief line"})

      def test_row_identity_mirrors_the_activity_key(self):
          from app.ingest.promote import _row_identity
          from app.ingest.research_records import CsrSpendFinding
          from app.ingest.writer import FUNDER_ACTIVITY_KEY

          ident = _row_identity("csr_spend", CsrSpendFinding(**SPEND), None, 3, 4, 7)
          assert len(ident) == len(FUNDER_ACTIVITY_KEY) - 1 and ident[0] == "spend"

      def test_two_partners_on_one_project_are_two_lines(self):
          from app.ingest.promote import _row_identity
          from app.ingest.research_records import CsrSpendFinding

          a = _row_identity("csr_spend", CsrSpendFinding(**SPEND), None, 3, 4, 7)
          b = _row_identity("csr_spend", CsrSpendFinding(**{**SPEND, "partner_name": "PRADAN"}), None, 3, 4, 7)
          assert a != b

      async def test_the_writer_writes_a_spend_line(self, recording_conn):
          from app.ingest.records import FunderCsrSpendRecord
          from app.ingest.writer import write_csr_spend

          conn = recording_conn([None, None])
          rec = FunderCsrSpendRecord(funder_name="Acme Ltd", fiscal_year="FY2024-25", amount=1e7,
                                     domain="livelihoods", classified_by="project_name",
                                     source_url="https://a.b/c", source_name="t", fetched_at=NOW)
          status, _ = await write_csr_spend(conn, rec, 1, program_id=None, state_id=None, district_id=None,
                                            csr_sector_id=None, domain_id=11, theme_id=None, document_id=None)
          assert status == "added"
          insert = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO funder_activity"))
          assert "spend" in conn.params[insert] and 11 in conn.params[insert]

      async def test_a_confirmed_classification_is_never_re_inferred(self, recording_conn):
          from app.ingest.records import FunderCsrSpendRecord
          from app.ingest.writer import FUNDER_ACTIVITY_UPDATABLE, write_csr_spend

          held = {**dict.fromkeys(FUNDER_ACTIVITY_UPDATABLE), "domain_tag_id": 12, "amount": 1e7}
          conn = recording_conn([{"classification_confirmed": True}, held])
          rec = FunderCsrSpendRecord(funder_name="Acme Ltd", fiscal_year="FY2024-25", amount=2e7,
                                     domain="livelihoods", classified_by="project_name",
                                     source_url="https://a.b/c", source_name="t", fetched_at=NOW)
          await write_csr_spend(conn, rec, 1, program_id=None, state_id=None, district_id=None,
                                csr_sector_id=None, domain_id=11, theme_id=None, document_id=None)
          update = next(q for q in conn.sql if q.startswith("UPDATE funder_activity"))
          assert "amount = %s" in update and "domain_tag_id" not in update

      async def test_promotion_writes_the_line_with_its_domain(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def classified(conn, domain, theme):
              return 11, None, []

          monkeypatch.setattr(promote, "resolve_classification", classified)
          conn = recording_conn([None, None])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [SPEND], Owner.funder(1), {}, {}, report, order=("csr_spend",))
          assert report["written"]["funder_activity (spend)"]["added"] == 1

      async def test_an_unseeded_domain_holds_the_line(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def unseeded(conn, domain, theme):
              return None, None, ["domain 'livelihoods' is not in tags"]

          monkeypatch.setattr(promote, "resolve_classification", unseeded)
          conn = recording_conn([])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [SPEND], Owner.funder(1), {}, {}, report, order=("csr_spend",))
          assert not any(q.startswith("INSERT INTO funder_activity") for q in conn.sql)
          assert "not in tags" in report["held"][0]

      async def test_the_dossier_reads_spend_from_funder_activity(self, recording_conn, recording_pool, monkeypatch):
          from app.ingest.tools import catalog_tools

          conn = recording_conn([[{"id": 1, "name": "Acme Ltd", "slug": "acme"}]])
          monkeypatch.setattr(catalog_tools, "get_pool", lambda: recording_pool(conn))
          await catalog_tools.funder_dossier.ainvoke({"name": "Acme", "entity_kind": "funder"})
          assert any("FROM funder_activity" in q and "kind = 'spend'" in q for q in conn.sql)
          assert not any("funder_csr_spend" in q for q in conn.sql)
  ```
  Also update `backend/tests/test_ingest.py`:
  - `test_required_fields_are_marked`: `assert required == {"fiscal_year", "amount", "domain", "classified_by"}`.
  - `NAMED` entry: `(FunderCsrSpendRecord, "funder_name", {"fiscal_year": "FY2024-25", "amount": 1.0, "domain": "others", "classified_by": "filed_sector"}),` and in `test_fiscal_year_format_is_enforced_on_every_yearly_record` the spend extra becomes `{"amount": 1.0, "domain": "others", "classified_by": "filed_sector"}`; in `test_an_amount_is_inr_and_cannot_be_negative` add `domain="others", classified_by="filed_sector"` to the call.
  - `test_two_findings_on_one_row_are_distinguished`: add `domain="health", classified_by="filed_sector",` to the `CsrSpendFinding(...)`.
- [ ] **Step 2: Finding.** In `research_records.py` add near the top:
  ```python
  DomainCode = Literal["livelihoods", "health", "education", "environment", "others"]
  ClassifiedBy = Literal["filed_sector", "project_name", "partner", "report"]
  _NO_THEMES = frozenset({"environment", "others"})


  def _check_classification(f: Any) -> None:
      """D11: a domain and theme are inferences, and a theme says what it rests on."""
      if f.domain in _NO_THEMES and f.theme:
          raise ValueError(f"{f.domain!r} has no themes in the taxonomy; leave theme empty")
      if f.theme and not (f.classification_note or "").strip():
          raise ValueError(
              "a theme needs a classification_note quoting what it rests on, e.g. "
              "\"project 'Financial Literacy & Inclusion'; filed under Education\""
          )
  ```
  Replace `CsrSpendFinding`:
  ```python
  class CsrSpendFinding(YearlyFinding):
      """One spend line: a project, or an aggregate. Never divide an aggregate across projects."""

      concept: Literal["csr_spend"] = "csr_spend"
      amount: Money
      outlay: Money | None = Field(
          default=None, description="the amount approved or budgeted for the line, when filed beside the spend"
      )
      project_name: str | None = Field(
          default=None, description="null on an aggregate row; set for a single project"
      )
      project_count: int | None = Field(
          default=None, description="set on an aggregate: how many projects the amount covers"
      )
      state: str | None = None
      district: str | None = None
      sector: str | None = Field(
          default=None, description="the Schedule VII sector the line was FILED under, as printed"
      )
      program_name: str | None = None
      designation: str | None = Field(
          default=None, description="e.g. 'aspirational_district', when the total is limited to those"
      )
      implementation_mode: (
          Literal["direct", "implementing_agency", "own_trust_or_section8", "not_stated"] | None
      ) = None
      partner_name: str | None = Field(default=None, description="the implementing agency or partner, as printed")
      partner_csr1: str | None = Field(default=None, description="the PARTNER's CSR-1, when filed")
      is_ongoing: bool | None = None
      notes: str | None = None
      domain: DomainCode = Field(
          description="ALWAYS set, by project name and partner, not by the filed sector. 'others' for relief, "
                      "sports, administration, unlabelled or multi-sector lines; 'environment' for "
                      "conservation and animal welfare that is not a livelihood programme"
      )
      theme: str | None = Field(
          default=None,
          description="a theme or sub-theme code from the taxonomy, at the most specific level the evidence "
                      "supports; null when the line gives nothing to go on. Never pick one to fill the field",
      )
      classified_by: ClassifiedBy = Field(description="what the domain and theme rest on")
      classification_note: str | None = Field(default=None, description="the evidence in a few words")

      @model_validator(mode="after")
      def _aggregate_or_project(self) -> CsrSpendFinding:
          if self.project_name and self.project_count:
              raise ValueError(
                  "a row is either one project or an aggregate of several, not both. Drop "
                  "project_count, or drop project_name and keep the total"
              )
          _check_classification(self)
          return self
  ```
- [ ] **Step 3: Expectations.** `NAMED_AS`: remove `"district_location_id"`, add `"domain_tag_id": "domain", "theme_tag_id": "theme"`. `CONCEPTS["csr_spend"]`:
  ```python
      "csr_spend": ConceptSpec(
          "funder_activity",
          "Project and sector spend",
          row_filter=("kind", "spend"),
          columns=("fiscal_year", "program_id", "domain_tag_id", "theme_tag_id", "classified_by",
                   "classification_note", "state_location_id", "project_name", "designation",
                   "implementation_mode", "partner_name", "partner_csr1", "outlay", "amount",
                   "project_count", "is_ongoing", "notes"),
          not_written={
              "sector": "resolved to funder_activity.csr_sector_id when it names a Schedule VII clause, "
                        "and kept in notes in the funder's own words either way",
          },
      ),
  ```
  `REQUIRED["csr_spend"] = frozenset({"fiscal_year", "amount", "domain", "classified_by"})`. `EXTRA["csr_spend"] = (_DISTRICT, Expected(name="sector", type="text", note="the Schedule VII sector the line was FILED under, as printed; stored in csr_sector_id when it names a clause", values=(), required=False))`.
- [ ] **Step 4: Record.**
  ```python
  class FunderCsrSpendRecord(Provenance):
      """One spend line: a project, or an aggregate of several. Never both, and never divided."""

      kind: Literal["funder_csr_spend"] = "funder_csr_spend"
      activity_kind: ClassVar[str] = "spend"
      funder_name: str = Field(min_length=2)
      fiscal_year: str
      amount: float = Field(ge=0, description="INR")
      outlay: float | None = Field(default=None, ge=0, description="INR")
      project_name: str | None = None
      project_count: int | None = None
      state: str | None = None
      district: str | None = None
      program_name: str | None = None
      designation: str | None = None
      implementation_mode: (
          Literal["direct", "implementing_agency", "own_trust_or_section8", "not_stated"] | None
      ) = None
      partner_name: str | None = None
      partner_csr1: str | None = None
      is_ongoing: bool | None = None
      notes: str | None = None
      domain: str
      theme: str | None = None
      classified_by: Literal["filed_sector", "project_name", "partner", "report"]
      classification_note: str | None = None

      _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
      _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))
  ```
  (`from typing import ClassVar, Literal`.)
- [ ] **Step 5: Writer.** Replace `CSR_SPEND_KEY`/`CSR_SPEND_UPDATABLE` with:
  ```python
  # funder_activity's UNIQUE NULLS NOT DISTINCT key, in its order. `kind` is part of it, so a spend
  # line and a partner line that agree on everything else are two lines (0031).
  FUNDER_ACTIVITY_KEY = ("funder_id", "kind", "fiscal_year", "program_id", "csr_sector_id",
                         "state_location_id", "location_id", "designation", "project_name", "partner_name")
  FUNDER_ACTIVITY_UPDATABLE = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note",
                               "name_as_printed", "implementation_mode", "partner_canonical",
                               "partner_csr1", "partner_kind", "outlay", "amount", "project_count",
                               "is_ongoing", "notes", "source_url", "source_name", "fetched_at", "as_of")
  _CLASSIFICATION = ("domain_tag_id", "theme_tag_id", "classified_by", "classification_note")
  ```
  and replace `write_csr_spend` with:
  ```python
  async def _write_activity(
      conn: Any, key: dict[str, Any], proposed: dict[str, Any], document_id: int | None
  ) -> tuple[str, dict]:
      """One funder_activity line. A classification a person confirmed is never re-inferred (D11)."""
      where = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in key)
      row = await (
          await conn.execute(
              f"SELECT classification_confirmed FROM funder_activity WHERE {where}", tuple(key.values())
          )
      ).fetchone()
      if row and row["classification_confirmed"]:
          proposed = {c: v for c, v in proposed.items() if c not in _CLASSIFICATION}
      return await _upsert(conn, "funder_activity", key, FUNDER_ACTIVITY_UPDATABLE, proposed, document_id)


  def _activity_key(funder_id: int, kind: str, fiscal_year: str, **ids: Any) -> dict[str, Any]:
      key = dict.fromkeys(FUNDER_ACTIVITY_KEY)
      key.update(funder_id=funder_id, kind=kind, fiscal_year=fiscal_year, **ids)
      return key


  async def write_csr_spend(
      conn: Any, rec: Any, funder_id: int, *, program_id: int | None, state_id: int | None,
      district_id: int | None, csr_sector_id: int | None, domain_id: int | None,
      theme_id: int | None, document_id: int | None,
  ) -> tuple[str, dict]:
      key = _activity_key(
          funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
          csr_sector_id=csr_sector_id, state_location_id=state_id, location_id=district_id,
          designation=rec.designation, project_name=rec.project_name, partner_name=rec.partner_name,
      )
      proposed = {
          "domain_tag_id": domain_id, "theme_tag_id": theme_id,
          "classified_by": rec.classified_by, "classification_note": rec.classification_note,
          "implementation_mode": rec.implementation_mode, "partner_csr1": rec.partner_csr1,
          "outlay": rec.outlay, "amount": rec.amount, "project_count": rec.project_count,
          "is_ongoing": rec.is_ongoing, "notes": rec.notes, "source_url": rec.source_url,
          "source_name": rec.source_name, "fetched_at": rec.fetched_at, "as_of": rec.as_of,
      }
      return await _write_activity(conn, key, proposed, document_id)
  ```
  `dict.fromkeys(FUNDER_ACTIVITY_KEY)` keeps the key's column order, which `_upsert` uses for both the SELECT and the INSERT.
- [ ] **Step 6: Promote.** Import `resolve_classification` from `app.ingest.taxonomy`. Add above `_row_identity`:
  ```python
  def _activity_identity(
      kind: str, year: str | None, program_id: int | None, sector_id: int | None,
      state_id: int | None, location_id: int | None, designation: str | None,
      project_name: str | None, partner_name: str | None,
  ) -> tuple:
      """writer.FUNDER_ACTIVITY_KEY without funder_id, in its order."""
      return (kind, year, program_id, sector_id, state_id, location_id, designation, project_name,
              partner_name)
  ```
  In `_row_identity` replace the csr_spend branch with `return _activity_identity("spend", year, program_id, sector_id, state_id, district_id, f.designation, f.project_name, f.partner_name)`. Replace the csr_spend branch of `_write_facts`:
  ```python
                  if concept == "csr_spend":
                      domain_id, theme_id, why = await resolve_classification(conn, f.domain, f.theme)
                      report["held"].extend(f"csr_spend {_describe(concept, f)}: {r}" for r in why)
                      if domain_id is None:
                          continue
                      rec = FunderCsrSpendRecord(
                          fiscal_year=f.fiscal_year, amount=f.amount.inr,
                          outlay=f.outlay.inr if f.outlay else None,
                          project_name=f.project_name, project_count=f.project_count,
                          designation=f.designation, partner_name=f.partner_name,
                          partner_csr1=f.partner_csr1, implementation_mode=f.implementation_mode,
                          is_ongoing=f.is_ongoing, domain=f.domain, theme=f.theme,
                          classified_by=f.classified_by, classification_note=f.classification_note,
                          as_of=f.fiscal_year, notes=_with_sector(f), **base,
                      )
                      status, _ = await write_csr_spend(
                          conn, rec, funder_id, program_id=program_id, state_id=state_id,
                          district_id=district_id, csr_sector_id=sector_id,
                          domain_id=domain_id, theme_id=theme_id, document_id=document_id,
                      )
                      _count(report, "funder_activity (spend)", status)
  ```
- [ ] **Step 7: Brief and dossier.** Brief csr_spend headline:
  ```python
      if concept == "csr_spend":
          what = f.get("project_name") or f.get("sector") or "aggregate"
          count = f"{f['project_count']} projects" if f.get("project_count") else None
          label = "/".join(b for b in (f.get("domain"), f.get("theme")) if b) or None
          return _join(what, _money(f.get("amount")), _place(f), count, f.get("partner_name"),
                       f"{label} (inferred)" if label else None)
  ```
  Dossier: replace the `funder_csr_spend` section with:
  ```python
      (
          "funder_activity kind='spend' (filed lines, INR; domain and theme are INFERRED unless confirmed)",
          """
          SELECT a.fiscal_year, a.project_name, a.amount, a.outlay, a.partner_name, a.implementation_mode,
                 a.designation, d.code AS domain, t.code AS theme, a.classified_by, a.classification_confirmed
          FROM funder_activity a
          LEFT JOIN tags d ON d.id = a.domain_tag_id LEFT JOIN tags t ON t.id = a.theme_tag_id
          WHERE a.funder_id = %s AND a.kind = 'spend' ORDER BY a.fiscal_year, a.id
          """,
      ),
  ```
- [ ] **Step 8: Integration check of the key** (append to `test_funder_activity.py`; runs on `sangam_fc`):
  ```python
  @pytest.mark.integration
  class TestTheKeyAgainstPostgres:
      async def test_a_re_promote_matches_and_another_kind_adds(self, db):
          from app.ingest.records import FunderCsrSpendRecord, FunderPartnerRecord
          from app.ingest.writer import write_csr_spend, write_partner

          f = (await (await db.execute(
              "INSERT INTO funders (slug, name) VALUES ('fc-key-test', 'Key Test Ltd') RETURNING id"
          )).fetchone())["id"]
          prov = {"source_url": "https://a.b/c", "source_name": "t", "fetched_at": NOW}
          spend = FunderCsrSpendRecord(funder_name="Key Test Ltd", fiscal_year="FY2024-25", amount=1e7,
                                       partner_name="Harsha Trust", domain="others",
                                       classified_by="filed_sector", **prov)
          args = dict(program_id=None, state_id=None, district_id=None, csr_sector_id=None,
                      domain_id=None, theme_id=None, document_id=None)
          assert (await write_csr_spend(db, spend, f, **args))[0] == "added"
          assert (await write_csr_spend(db, spend, f, **args))[0] == "matched"
          partner = FunderPartnerRecord(funder_name="Key Test Ltd", fiscal_year="FY2024-25",
                                        partner_name="Harsha Trust", **prov)
          assert (await write_partner(db, partner, f, program_id=None, document_id=None))[0] == "added"
  ```
  (`write_partner` reaches `funder_activity` in Task 11; run this class after Task 11.)
- [ ] **Step 9: Run.** `bt tests/test_funder_activity.py tests/test_ingest.py -q` → pass except `TestTheKeyAgainstPostgres` (deselected by `-m "not integration"` in the full run). Full unit tier → 0 failed. `ruff check .` clean.
- [ ] **Step 10: Commit.** `git add -A backend && git commit -m "feat(ingest): spend lines are funder_activity rows with an inferred domain and theme" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 11: Footprints and partners move to `funder_activity`

**Files:**
- Modify: `backend/app/ingest/expectations.py` (`CONCEPTS["footprint"]` 79, `["partner"]` 81; `EXTRA["footprint"]` 248; `_GRANT_NEEDS_A_RECIPIENT` 39-47; `EXTRA["grant"]` note 265-266)
- Modify: `backend/app/ingest/records.py` (`FunderFootprintRecord` 181-195, `FunderPartnerRecord` 211-225: add `activity_kind`)
- Modify: `backend/app/ingest/writer.py` (`FOOTPRINT_*`, `PARTNER_*` 306-313; `write_footprint` 387-398; `write_partner` 414-425)
- Modify: `backend/app/ingest/promote.py` (`_row_identity` footprint/partner; branches 441-484; `_place` docstring 254-256)
- Modify: `backend/app/ingest/brief.py` (no change to headlines), `tools/catalog_tools.py` (sections 152-159, 167-173)
- Modify: `backend/app/ingest/runner.py` (48-51), `backend/app/ingest/geography.py` (docstring 3-5)
- Modify: `backend/tests/test_ingest.py` (`test_stated_geography_and_footprint_are_different_concepts` 518-522)
- Modify: `backend/tests/test_funder_activity.py`

**Interfaces:**
- Produces: `write_footprint(conn, rec, funder_id, *, program_id, state_id, district_id, document_id)`; `write_partner(conn, rec, funder_id, *, program_id, document_id)` (signature unchanged); `FunderFootprintRecord.activity_kind = "footprint"`, `FunderPartnerRecord.activity_kind = "partner"`; `catalog_baseline()` key `funder_activity` replaces three keys.

- [ ] **Step 1: Failing tests.** In `test_ingest.py` replace the body of `test_stated_geography_and_footprint_are_different_concepts`:
  ```python
          assert CONCEPT_TABLES["stated_geography"] == "funder_locations"
          from app.ingest.expectations import CONCEPTS
          assert (CONCEPT_TABLES["footprint"], CONCEPTS["footprint"].row_filter) == (
              "funder_activity", ("kind", "footprint"))
  ```
  Append to `test_funder_activity.py`:
  ```python
  FOOTPRINT = {"concept": "footprint", "fiscal_year": "FY2024-25", "state": "Atlantis",
               "evidence": "The programme ran in Atlantis during the year under review.",
               "source_url": "https://a.b/c", "confidence": "high"}


  class TestFootprintsAndPartners:
      def test_each_owns_its_rows(self):
          assert CONCEPTS["footprint"].row_filter == ("kind", "footprint")
          assert CONCEPTS["partner"].row_filter == ("kind", "partner")
          assert {f.name for f in expected_fields("footprint")} == {
              "fiscal_year", "program_name", "state", "name_as_printed", "notes", "district"}

      async def test_a_footprint_with_no_place_is_held_not_written(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def unresolved(conn, state, district=None):
              return None, f"{state!r} is not an Indian state"

          monkeypatch.setattr(promote, "resolve_location", unresolved)
          conn = recording_conn([])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [FOOTPRINT], Owner.funder(1), {}, {}, report,
                                     order=("footprint",))
          assert not any(q.startswith("INSERT INTO funder_activity") for q in conn.sql)
          assert any("a footprint line needs one" in h for h in report["held"])

      async def test_a_footprint_keeps_state_and_district_apart(self, recording_conn):
          from app.ingest.records import FunderFootprintRecord
          from app.ingest.writer import write_footprint

          conn = recording_conn([None, None])
          rec = FunderFootprintRecord(funder_name="Acme Ltd", fiscal_year="FY2024-25", state="Assam",
                                      district="Barpeta", source_url="https://a.b/c", source_name="t",
                                      fetched_at=NOW)
          await write_footprint(conn, rec, 1, program_id=None, state_id=3, district_id=8, document_id=None)
          insert = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO funder_activity"))
          assert "footprint" in conn.params[insert]
          cols = conn.sql[insert].split("(")[1].split(")")[0].replace(" ", "").split(",")
          values = conn.params[insert]
          assert values[cols.index("state_location_id")] == 3 and values[cols.index("location_id")] == 8

      async def test_the_baseline_counts_funder_activity(self, recording_conn, recording_pool, monkeypatch):
          from app.ingest import runner

          conn = recording_conn([{"funder_activity": 0}])
          monkeypatch.setattr(runner, "get_pool", lambda: recording_pool(conn))
          await runner.catalog_baseline()
          assert "FROM funder_activity" in conn.sql[0] and "funder_footprints" not in conn.sql[0]
  ```
  (`resolve_location` is imported by name into `promote`, so the monkeypatch reaches `_place`.)
- [ ] **Step 2: Expectations.**
  ```python
      "footprint": ConceptSpec(
          "funder_activity", "Where the work ran", row_filter=("kind", "footprint"),
          columns=("fiscal_year", "program_id", "state_location_id", "name_as_printed", "notes"),
      ),
      …
      "partner": ConceptSpec(
          "funder_activity", "Implementing partners", row_filter=("kind", "partner"),
          columns=("fiscal_year", "program_id", "partner_name", "partner_canonical", "partner_csr1",
                   "partner_kind", "notes"),
      ),
  ```
  `EXTRA["footprint"] = (_DISTRICT,)` (state now comes from `state_location_id` through `NAMED_AS`, required by `REQUIRED["footprint"]`). In the `_GRANT_NEEDS_A_RECIPIENT` comment and string replace `funder_partners` with `funder_activity (kind 'partner')`; in `EXTRA["grant"]`'s note likewise.
- [ ] **Step 3: Records.** Add `activity_kind: ClassVar[str] = "footprint"` to `FunderFootprintRecord` and `activity_kind: ClassVar[str] = "partner"` to `FunderPartnerRecord`; footprint docstring → `"""Where a theme actually ran. A line needs a place, so a place that will not resolve is a line that cannot be written — say so, do not guess."""`.
- [ ] **Step 4: Writer.** Delete `FOOTPRINT_KEY`, `FOOTPRINT_UPDATABLE`, `PARTNER_KEY`, `PARTNER_UPDATABLE`. Replace the two writers:
  ```python
  async def write_footprint(
      conn: Any, rec: Any, funder_id: int, *, program_id: int | None,
      state_id: int | None, district_id: int | None, document_id: int | None,
  ) -> tuple[str, dict]:
      key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                          state_location_id=state_id, location_id=district_id)
      proposed = {
          "name_as_printed": rec.name_as_printed, "notes": rec.notes,
          "source_url": rec.source_url, "source_name": rec.source_name,
          "fetched_at": rec.fetched_at, "as_of": rec.as_of,
      }
      return await _write_activity(conn, key, proposed, document_id)


  async def write_partner(
      conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None
  ) -> tuple[str, dict]:
      key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                          partner_name=rec.partner_name)
      proposed = {
          "partner_canonical": rec.partner_canonical or rec.partner_name,
          "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1, "notes": rec.notes,
          "source_url": rec.source_url, "source_name": rec.source_name,
          "fetched_at": rec.fetched_at, "as_of": rec.as_of,
      }
      return await _write_activity(conn, key, proposed, document_id)
  ```
- [ ] **Step 5: Promote.** `_row_identity`: footprint → `_activity_identity("footprint", year, program_id, None, state_id, district_id, None, None, None)`; partner → `_activity_identity("partner", year, program_id, None, None, None, None, None, f.partner_name)`. Footprint branch:
  ```python
                  elif concept == "footprint":
                      if state_id is None and district_id is None:
                          report["held"].append(
                              f"footprint {f.state!r}: no place to attach it to, and a footprint line "
                              f"needs one"
                          )
                          continue
                      rec = FunderFootprintRecord(
                          fiscal_year=f.fiscal_year, state=f.state, district=f.district,
                          name_as_printed=f.name_as_printed or f.district or f.state,
                          notes=f.notes, as_of=f.fiscal_year, **base,
                      )
                      status, _ = await write_footprint(
                          conn, rec, funder_id, program_id=program_id, state_id=state_id,
                          district_id=district_id, document_id=document_id,
                      )
                      _count(report, "funder_activity (footprint)", status)
  ```
  Partner branch: `_count(report, "funder_activity (partner)", status)`. `_place` docstring: replace "funder_footprints.location_id is NOT NULL" with "a footprint line needs a place".
- [ ] **Step 6: Dossier, runner, geography.** Dossier sections:
  ```python
      (
          "funder_activity kind='footprint' (where the work actually ran)",
          """
          SELECT a.fiscal_year, a.name_as_printed, s.name AS state, l.name AS location
          FROM funder_activity a
          LEFT JOIN locations s ON s.id = a.state_location_id LEFT JOIN locations l ON l.id = a.location_id
          WHERE a.funder_id = %s AND a.kind = 'footprint' ORDER BY a.fiscal_year, a.id
          """,
      ),
      …
      (
          "funder_activity kind='partner' (named, not proof money changed hands)",
          """
          SELECT fiscal_year, partner_name, partner_canonical, partner_kind
          FROM funder_activity WHERE funder_id = %s AND kind = 'partner' ORDER BY fiscal_year, id
          """,
      ),
  ```
  `runner.catalog_baseline`: replace the three count lines with `"(SELECT count(*) FROM funder_activity) AS funder_activity, "`. `geography.py` docstring line 4-5: "…and a footprint line needs a place, so a footprint with an unresolvable place cannot be written at all."
- [ ] **Step 7: Run.** `bt -m "'not integration'" -q` → 0 failed. Then `bti tests/test_funder_activity.py -m integration -q` → `TestTheKeyAgainstPostgres` passes on `sangam_fc`. `ruff check .` clean.
- [ ] **Step 8: Commit.** `git add -A backend && git commit -m "feat(ingest): footprints and partners are funder_activity rows" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 12: `programme_spend` — the funder's own programme split (D12)

**Files:**
- Modify: `backend/app/ingest/expectations.py` (new concept after `partner`; `REQUIRED`)
- Modify: `backend/app/ingest/research_records.py` (new `ProgrammeSpendFinding`; union; `FINDING_MODELS`)
- Modify: `backend/app/ingest/records.py` (new `FunderProgrammeSpendRecord`; `Record` union)
- Modify: `backend/app/ingest/writer.py` (new `write_programme_spend`)
- Modify: `backend/app/ingest/promote.py` (`WRITE_ORDER`, `CONCEPT_RECORDS`, `_row_identity`, branch, `_funder_program`)
- Modify: `backend/app/ingest/brief.py`, `tools/catalog_tools.py`
- Modify: `backend/tests/test_funder_activity.py`

**Interfaces:**
- Produces: concept `"programme_spend"` → `ConceptSpec("funder_activity", "The funder's own programme split", row_filter=("kind", "programme"), …)`; `ProgrammeSpendFinding`; `FunderProgrammeSpendRecord` (`kind="funder_programme_spend"`, `activity_kind="programme"`); `write_programme_spend(conn, rec, funder_id, *, program_id: int, domain_id, theme_id, document_id)`; `promote._funder_program(conn, funder_id, name) -> int | None`.

- [ ] **Step 1: Failing tests** (append to `test_funder_activity.py`):
  ```python
  PROGRAMME = {"concept": "programme_spend", "fiscal_year": "FY2024-25", "program_name": "Rural Livelihoods",
               "amount": {"value": 40, "unit": "crore", "text": "Rs 40 crore"}, "domain": "livelihoods",
               "classified_by": "report",
               "evidence": "The Foundation spent Rs 40 crore on its rural livelihoods programme in FY2024-25.",
               "source_url": "https://a.b/c", "confidence": "high"}


  class TestTheFundersOwnSplit:
      def test_it_owns_programme_rows(self):
          assert CONCEPTS["programme_spend"].row_filter == ("kind", "programme")
          required = {f.name for f in expected_fields("programme_spend") if f.required}
          assert required == {"fiscal_year", "program_name", "amount", "domain", "classified_by"}

      async def test_a_programme_figure_with_no_programme_is_held(self, recording_conn):
          from app.ingest import promote
          from app.ingest.writer import Owner

          conn = recording_conn([None])     # no programs row of that name for this funder
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [PROGRAMME], Owner.funder(1), {}, {}, report,
                                     order=("programme_spend",))
          assert not any(q.startswith("INSERT INTO funder_activity") for q in conn.sql)
          assert "Rural Livelihoods" in report["held"][0]

      async def test_a_programme_figure_is_written_against_its_programme(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def classified(conn, domain, theme):
              return 11, None, []

          monkeypatch.setattr(promote, "resolve_classification", classified)
          conn = recording_conn([None, None])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [PROGRAMME], Owner.funder(1), {"Rural Livelihoods": 5}, {},
                                     report, order=("programme_spend",))
          insert = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO funder_activity"))
          assert "programme" in conn.params[insert] and 5 in conn.params[insert]

      def test_spend_comes_before_the_split_and_programmes_before_both(self):
          from app.ingest.promote import WRITE_ORDER

          assert WRITE_ORDER.index("csr_spend") < WRITE_ORDER.index("programme_spend")
          assert "program" not in WRITE_ORDER
  ```
- [ ] **Step 2: Implement.** Expectations (after `"partner"`):
  ```python
      # D12: the funder's OWN figure per programme component. Never summed with spend lines and never
      # spread onto them; the two are reported side by side.
      "programme_spend": ConceptSpec(
          "funder_activity", "The funder's own programme split", row_filter=("kind", "programme"),
          columns=("fiscal_year", "program_id", "domain_tag_id", "theme_tag_id", "classified_by",
                   "classification_note", "amount", "notes"),
      ),
  ```
  `REQUIRED["programme_spend"] = frozenset({"fiscal_year", "program_name", "amount", "domain", "classified_by"})`. Finding:
  ```python
  class ProgrammeSpendFinding(YearlyFinding):
      """The funder's own figure for one programme component in a year (D12). It is the funder's total,
      never a sum of filing lines and never spread across them."""

      concept: Literal["programme_spend"] = "programme_spend"
      program_name: str = Field(min_length=2, description="the programme as the funder names it; also a program finding")
      amount: Money
      domain: DomainCode
      theme: str | None = None
      classified_by: ClassifiedBy = Field(description="usually 'report': the funder's own programme naming")
      classification_note: str | None = None
      notes: str | None = None

      @model_validator(mode="after")
      def _classified(self) -> ProgrammeSpendFinding:
          _check_classification(self)
          return self
  ```
  Add it to the `Finding` union and `FINDING_MODELS["programme_spend"]`. Record:
  ```python
  class FunderProgrammeSpendRecord(Provenance):
      """The funder's own programme total for a year (D12)."""

      kind: Literal["funder_programme_spend"] = "funder_programme_spend"
      activity_kind: ClassVar[str] = "programme"
      funder_name: str = Field(min_length=2)
      fiscal_year: str
      program_name: str = Field(min_length=2)
      amount: float = Field(ge=0, description="INR")
      domain: str
      theme: str | None = None
      classified_by: Literal["filed_sector", "project_name", "partner", "report"]
      classification_note: str | None = None
      notes: str | None = None

      _fy = field_validator("fiscal_year")(lambda v: _fiscal_year(v))
      _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))
  ```
  (add to `Record`). Writer:
  ```python
  async def write_programme_spend(
      conn: Any, rec: Any, funder_id: int, *, program_id: int, domain_id: int | None,
      theme_id: int | None, document_id: int | None,
  ) -> tuple[str, dict]:
      key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id)
      proposed = {
          "domain_tag_id": domain_id, "theme_tag_id": theme_id, "classified_by": rec.classified_by,
          "classification_note": rec.classification_note, "amount": rec.amount, "notes": rec.notes,
          "source_url": rec.source_url, "source_name": rec.source_name,
          "fetched_at": rec.fetched_at, "as_of": rec.as_of,
      }
      return await _write_activity(conn, key, proposed, document_id)
  ```
  Promote: `WRITE_ORDER = ("csr_spend", "footprint", "stated_geography", "partner", "programme_spend", "metric", "contact", "rfp", "funder_eligibility")`; `CONCEPT_RECORDS["programme_spend"] = FunderProgrammeSpendRecord`; in `_row_identity`: `if concept == "programme_spend": return ("programme", year, f.program_name)` (a programme's name is its key within one funder — `PROGRAM_KEY` — so this mirrors the line key even before the id resolves). Helper and branch:
  ```python
  async def _funder_program(conn: Any, funder_id: int, name: str) -> int | None:
      row = await (
          await conn.execute("SELECT id FROM programs WHERE funder_id = %s AND name = %s", (funder_id, name))
      ).fetchone()
      return row["id"] if row else None
  ```
  ```python
                  elif concept == "programme_spend":
                      program_id = program_id or await _funder_program(conn, funder_id, f.program_name)
                      if program_id is None:
                          report["held"].append(
                              f"programme_spend {f.program_name!r} {f.fiscal_year}: no programme of that "
                              f"name for this funder, and the funder's own figure has to hang off one. "
                              f"Add it as a program finding and promote again."
                          )
                          continue
                      domain_id, theme_id, why = await resolve_classification(conn, f.domain, f.theme)
                      report["held"].extend(f"programme_spend {f.program_name!r}: {r}" for r in why)
                      if domain_id is None:
                          continue
                      rec = FunderProgrammeSpendRecord(
                          fiscal_year=f.fiscal_year, program_name=f.program_name, amount=f.amount.inr,
                          domain=f.domain, theme=f.theme, classified_by=f.classified_by,
                          classification_note=f.classification_note, notes=f.notes,
                          as_of=f.fiscal_year, **base,
                      )
                      status, _ = await write_programme_spend(
                          conn, rec, funder_id, program_id=program_id, domain_id=domain_id,
                          theme_id=theme_id, document_id=document_id,
                      )
                      _count(report, "funder_activity (programme)", status)
  ```
  Brief: `if concept == "programme_spend": return _join(f.get("program_name"), _money(f.get("amount")), "the funder's own figure", "/".join(b for b in (f.get("domain"), f.get("theme")) if b))`. Dossier section after spend:
  ```python
      (
          "funder_activity kind='programme' (the funder's OWN programme totals; never add them to spend)",
          """
          SELECT a.fiscal_year, p.name AS programme, a.amount, d.code AS domain, t.code AS theme,
                 a.classification_confirmed
          FROM funder_activity a JOIN programs p ON p.id = a.program_id
          LEFT JOIN tags d ON d.id = a.domain_tag_id LEFT JOIN tags t ON t.id = a.theme_tag_id
          WHERE a.funder_id = %s AND a.kind = 'programme' ORDER BY a.fiscal_year, p.name
          """,
      ),
  ```
- [ ] **Step 3: Run.** Full unit tier → 0 failed (`TestPromotionCoversEveryConceptWithAWriter` passes: `programme_spend` is promotable and in `WRITE_ORDER`). `ruff check .` clean.
- [ ] **Step 4: Commit.** `git add -A backend && git commit -m "feat(ingest): programme_spend — a funder's own programme split, beside its filing lines (D12)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 13: `ensure_document` keys on the source URL and the kind of document

**Files:**
- Modify: `backend/app/ingest/expectations.py` (new `RESERVED_DOC_TYPES`)
- Modify: `backend/app/ingest/writer.py` (`ensure_document` 98-139)
- Modify: `backend/app/ingest/research_records.py` (`DocumentFinding` 356-362)
- Modify: `backend/app/agent/tools/sql/catalog.py` (`documents.doc_type` note, line 125)
- Modify: `backend/tests/test_storage.py` (lines 258-296: `funder_id=None` → `owner=None`, five calls)
- Create: `backend/tests/test_eligibility_document.py`

**Interfaces:**
- Produces: `expectations.RESERVED_DOC_TYPES = frozenset({"funder_eligibility", "proposal_template", "source_dataset"})`. `ensure_document` signature unchanged; its lookup is `source_url = %s AND (CASE WHEN doc_type = ANY(reserved) THEN doc_type ELSE '' END) = <class>`.

- [ ] **Step 1: Failing tests.** Create `backend/tests/test_eligibility_document.py`:
  ```python
  """Eligibility is a documents row (D3), so documents are keyed on the URL and the kind of document."""

  from __future__ import annotations

  from datetime import UTC, datetime

  import pytest
  from pydantic import ValidationError

  NOW = datetime(2026, 10, 7, tzinfo=UTC)


  def shim(url="https://acme.example/csr-policy", title="CSR Policy"):
      return type("Doc", (), {"source_url": url, "title": title, "source_name": "t",
                              "fetched_at": NOW, "as_of": None})()


  class TestDocumentKeying:
      async def test_an_eligibility_document_is_looked_up_as_its_own_kind(self, recording_conn):
          from app.ingest.writer import ensure_document

          conn = recording_conn([None, {"id": 5}])
          await ensure_document(conn, shim(), owner=None, doc_type="funder_eligibility")
          assert conn.params[0][2] == "funder_eligibility"

      async def test_every_other_type_shares_one_class(self, recording_conn):
          from app.ingest.writer import ensure_document

          conn = recording_conn([{"id": 5, "storage_path": None, "content_hash": None}])
          assert await ensure_document(conn, shim(), owner=None, doc_type="csr_annexure") == (5, "matched")
          assert conn.params[0][2] == ""

      def test_a_reserved_doc_type_is_refused_on_a_document_finding(self):
          from app.ingest.research_records import DocumentFinding

          with pytest.raises(ValidationError, match="reserved"):
              DocumentFinding(title="CSR Policy", doc_type="funder_eligibility",
                              evidence="The CSR policy sets out who may apply for support.",
                              source_url="https://a.b/c", confidence="high")


  @pytest.mark.integration
  class TestDocumentKeyingAgainstPostgres:
      async def test_a_page_can_be_source_and_eligibility_document(self, db):
          from app.ingest.writer import ensure_document

          url = "https://test.invalid/fc-policy"
          source, _ = await ensure_document(db, shim(url), owner=None, doc_type="csr_policy")
          eligibility, status = await ensure_document(db, shim(url), owner=None, doc_type="funder_eligibility")
          assert status == "added" and eligibility != source

      async def test_two_wordings_of_a_source_type_are_one_row(self, db):
          from app.ingest.writer import ensure_document

          url = "https://test.invalid/fc-report.pdf"
          first, _ = await ensure_document(db, shim(url), owner=None, doc_type="annual_report")
          second, status = await ensure_document(db, shim(url), owner=None, doc_type="csr_annexure")
          assert (second, status) == (first, "matched")
  ```
- [ ] **Step 2: Implement.** `expectations.py` (after `PROVENANCE`):
  ```python
  # doc_type values written only by their own path: the eligibility concept, the template path and the
  # staff-source upload. A `document` finding may not use them, and ensure_document keys them apart.
  RESERVED_DOC_TYPES = frozenset({"funder_eligibility", "proposal_template", "source_dataset"})
  ```
  `writer.py`: `from app.ingest.expectations import RESERVED_DOC_TYPES`; replace the lookup at the top of `ensure_document` and its docstring's first line:
  ```python
      """One documents row per source URL and kind of document, so many facts can cite one report.

      The kind is the doc_type itself for the three reserved types and one shared class for every
      other type: a policy page can be both the archived source and the funder's eligibility document
      (two rows), while one PDF that two research runs called 'annual_report' and 'csr_annexure' is
      still one row. Returns (id, added | updated | matched). The archive columns backfill onto a row
      that predates archiving, and only where the row is empty.
      """
      kind = doc_type if doc_type in RESERVED_DOC_TYPES else ""
      row = await (
          await conn.execute(
              "SELECT id, storage_path, content_hash FROM documents WHERE source_url = %s "
              "AND (CASE WHEN doc_type = ANY(%s) THEN doc_type ELSE '' END) = %s ORDER BY id LIMIT 1",
              (rec.source_url, sorted(RESERVED_DOC_TYPES), kind),
          )
      ).fetchone()
  ```
  `DocumentFinding`: import `RESERVED_DOC_TYPES` and add
  ```python
      @field_validator("doc_type")
      @classmethod
      def _not_reserved(cls, v: str) -> str:
          if v in RESERVED_DOC_TYPES:
              raise ValueError(
                  f"doc_type {v!r} is reserved: eligibility is an eligibility_guideline finding, and "
                  f"templates and staff datasets have their own paths"
              )
          return v
  ```
  Catalog: `Column("doc_type", "text", note="free text, except three values written by their own path: 'funder_eligibility' (a funder's standing eligibility, verbatim in content_md), 'proposal_template' (a funder's application form), 'source_dataset' (a staff-only file with no content_md)")`. `test_storage.py`: replace every `funder_id=None` in the `ensure_document(...)` calls with `owner=None`.
- [ ] **Step 3: Run.** `bt -m "'not integration'" -q` → 0 failed. `bti tests/test_eligibility_document.py tests/test_storage.py -m integration -q` → the two keying tests and `TestEnsureDocumentRecordsTheArchive` pass on `sangam_fc`.
- [ ] **Step 4: Commit.** `git add -A backend && git commit -m "feat(ingest): documents are keyed on source URL and the kind of document" -m "Also fixes test_storage's ensure_document calls, which still passed funder_id= after the Owner change." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 14: Eligibility is a document (D3)

**Files:**
- Modify: `backend/app/ingest/expectations.py` (replace `CONCEPTS["funder_eligibility"]` 82-87 and `REQUIRED` 213; `EXTRA`)
- Modify: `backend/app/ingest/research_records.py` (replace `FunderEligibilityFinding` 334-353; union; `FINDING_MODELS`)
- Modify: `backend/app/ingest/records.py` (replace `FunderEligibilityRecord` 287-298; `Record` union)
- Modify: `backend/app/ingest/writer.py` (replace `FUNDER_ELIGIBILITY_*` and `write_funder_eligibility` 537-560)
- Modify: `backend/app/ingest/promote.py` (imports; `WRITE_ORDER`; `CONCEPT_RECORDS`; `RENAMED` line 120; `_row_identity` 377-378; branch 497-505)
- Modify: `backend/app/ingest/brief.py` (headline; `LEGACY_TITLES`), `tools/catalog_tools.py` (section 116-125)
- Modify: `backend/tests/test_eligibility_document.py`

**Interfaces:**
- Produces: concept `"eligibility_guideline"` → `ConceptSpec("documents", "Eligibility guidelines", row_filter=("doc_type", "funder_eligibility"), columns=("title",))`; `EligibilityGuidelineFinding`; `records.ELIGIBILITY_SECTIONS`, `records.NOT_STATED`, `EligibilityGuidelineRecord.content_md() -> str` (`doc_type` ClassVar `"funder_eligibility"`); `writer.write_eligibility_document(conn, rec, funder_id: int) -> tuple[int, str]`.
- Consumes: `ensure_document` keying (Task 13); migration headings (Task 1).

- [ ] **Step 1: Failing tests** (append to `test_eligibility_document.py`):
  ```python
  from pathlib import Path

  GUIDELINE = {"concept": "eligibility_guideline", "title": "CSR Policy — partner selection",
               "statutory_restatement": "Registered under Section 12A and 80G of the Income Tax Act.",
               "own_bar": "At least five years of work in the district concerned.",
               "evidence": "The policy states the criteria an implementing agency must meet.",
               "source_url": "https://acme.example/csr-policy", "confidence": "high"}


  class TestTheEligibilityConcept:
      def test_it_owns_eligibility_documents(self):
          from app.ingest.expectations import CONCEPTS, expected_fields

          assert CONCEPTS["eligibility_guideline"].row_filter == ("doc_type", "funder_eligibility")
          assert "funder_eligibility" not in CONCEPTS
          assert {f.name for f in expected_fields("eligibility_guideline")} == {
              "title", "as_of", "statutory_restatement", "own_bar", "disqualifiers", "not_stated"}

      def test_text_or_an_honest_absence(self):
          from app.ingest.research_records import EligibilityGuidelineFinding

          with pytest.raises(ValidationError, match="not_stated"):
              EligibilityGuidelineFinding(**{**GUIDELINE, "statutory_restatement": None, "own_bar": None})
          assert EligibilityGuidelineFinding(**{**GUIDELINE, "statutory_restatement": None, "own_bar": None,
                                                "not_stated": True}).not_stated

      def test_the_text_is_kept_under_the_migrations_headings(self):
          from app.ingest.records import ELIGIBILITY_SECTIONS, EligibilityGuidelineRecord

          rec = EligibilityGuidelineRecord(funder_name="Acme Foundation", title="Policy",
                                           own_bar="At least five years of work in the district.",
                                           source_url="https://a.b/c", source_name="t", fetched_at=NOW)
          assert rec.content_md() == "## Its own bar\n\nAt least five years of work in the district."
          sql = (Path(__file__).resolve().parents[2] / "db" / "migrations"
                 / "0031_funder_consolidation.sql").read_text(encoding="utf-8")
          assert all(f"## {heading}" in sql for _, heading in ELIGIBILITY_SECTIONS)

      async def test_one_eligibility_document_per_page(self, recording_conn):
          from app.ingest import promote
          from app.ingest.writer import Owner

          conn = recording_conn([None, {"id": 21}, {"id": 21}])
          row = {"slug": "acme", "entity_name": "Acme Foundation", "canonical_name": None, "researched_at": NOW}
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, row, [GUIDELINE, {**GUIDELINE, "title": "Same page again"}],
                                     Owner.funder(1), {}, {}, report, order=("eligibility_guideline",))
          assert sum(q.startswith("INSERT INTO documents") for q in conn.sql) == 1
          assert any("same row" in h for h in report["held"])
          assert report["written"]["documents (funder_eligibility)"]["added"] == 1

      async def test_the_dossier_reads_the_latest_eligibility_document(self, recording_conn, recording_pool, monkeypatch):
          from app.ingest.tools import catalog_tools

          conn = recording_conn([[{"id": 1, "name": "Acme Foundation", "slug": "acme"}]])
          monkeypatch.setattr(catalog_tools, "get_pool", lambda: recording_pool(conn))
          await catalog_tools.funder_dossier.ainvoke({"name": "Acme", "entity_kind": "funder"})
          assert any("doc_type = 'funder_eligibility'" in q and "LIMIT 1" in q for q in conn.sql)
  ```
- [ ] **Step 2: Expectations.** Replace the `funder_eligibility` concept with:
  ```python
      # The funder's standing eligibility (D3): one documents row per page, the text verbatim, keeping
      # the split funder-intake-research field 4 makes. NOT rfps.eligibility, which is one call's.
      "eligibility_guideline": ConceptSpec(
          "documents", "Eligibility guidelines",
          row_filter=("doc_type", "funder_eligibility"), columns=("title",),
      ),
  ```
  `REQUIRED["eligibility_guideline"] = frozenset({"title"})`. `EXTRA["eligibility_guideline"]`:
  ```python
      "eligibility_guideline": (
          Expected(name="as_of", type="text", note="the period or version the guideline describes",
                   values=(), required=False),
          Expected(name="statutory_restatement", type="text",
                   note="Rule 4 of the CSR Rules copied into the policy, VERBATIM. Not the funder's own bar",
                   values=(), required=False),
          Expected(name="own_bar", type="text",
                   note="anything beyond the statutory minimum, in the funder's own words, verbatim",
                   values=(), required=False),
          Expected(name="disqualifiers", type="text",
                   note="stated grounds for outright rejection, verbatim", values=(), required=False),
          Expected(name="not_stated", type="boolean",
                   note="the page was read and states no eligibility; source_url is still that page",
                   values=(), required=False),
      ),
  ```
- [ ] **Step 3: Finding.** Replace `FunderEligibilityFinding`:
  ```python
  class EligibilityGuidelineFinding(FindingBase):
      """A funder's standing eligibility for applicants, verbatim, from one page (D3).

      Not rfps.eligibility: that is one call's. The same sentence can be true in both places and that
      is two findings, not a duplicate.
      """

      concept: Literal["eligibility_guideline"] = "eligibility_guideline"
      title: str = Field(min_length=4, description="what the page is, e.g. 'CSR Policy — partner selection'")
      as_of: str | None = Field(default=None, description="the period or version the guideline describes")
      statutory_restatement: str | None = Field(
          default=None, description="Rule 4 copied into the policy, VERBATIM. Not the funder's own bar"
      )
      own_bar: str | None = Field(default=None, description="beyond the statutory minimum, verbatim")
      disqualifiers: str | None = Field(default=None, description="stated grounds for rejection, verbatim")
      not_stated: bool = Field(
          default=False, description="true when the page was read and states no eligibility"
      )

      @model_validator(mode="after")
      def _text_or_an_honest_absence(self) -> EligibilityGuidelineFinding:
          texts = [t for t in (self.statutory_restatement, self.own_bar, self.disqualifiers) if t and t.strip()]
          if self.not_stated and texts:
              raise ValueError("not_stated with eligibility text is a contradiction — drop one")
          if not self.not_stated and not texts:
              raise ValueError(
                  "no eligibility text: quote the page verbatim, or set not_stated=true if it states none"
              )
          if any(len(t.strip()) < 10 for t in texts):
              raise ValueError("eligibility text is the sentence that states the bar, not a label")
          return self
  ```
  Swap it into the `Finding` union and `FINDING_MODELS` (`"eligibility_guideline": EligibilityGuidelineFinding`, remove `"funder_eligibility"`).
- [ ] **Step 4: Record and writer.** In `records.py` replace `FunderEligibilityRecord`:
  ```python
  # The headings an eligibility document's text sits under. 0031 writes the same three when it moves
  # funder_eligibility rows into documents; a test holds the two together.
  ELIGIBILITY_SECTIONS = (
      ("statutory_restatement", "Statutory restatement"),
      ("own_bar", "Its own bar"),
      ("disqualifiers", "Disqualifiers"),
  )
  NOT_STATED = "Not stated. The page was read and sets out no eligibility for applicants."


  class EligibilityGuidelineRecord(Provenance):
      """One funder_eligibility documents row: the guideline text, verbatim."""

      kind: Literal["eligibility_guideline"] = "eligibility_guideline"
      doc_type: ClassVar[str] = "funder_eligibility"
      funder_name: str = Field(min_length=2)
      title: str = Field(min_length=4)
      statutory_restatement: str | None = None
      own_bar: str | None = None
      disqualifiers: str | None = None
      not_stated: bool = False

      _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))

      def content_md(self) -> str:
          if self.not_stated:
              return NOT_STATED
          return "\n\n".join(
              f"## {heading}\n\n{text.strip()}"
              for field, heading in ELIGIBILITY_SECTIONS
              if (text := getattr(self, field))
          )
  ```
  (update `Record`). In `writer.py` replace the eligibility block:
  ```python
  async def write_eligibility_document(
      conn: Any, rec: Any, funder_id: int
  ) -> tuple[int, str]:
      """The funder's standing eligibility as one documents row, text verbatim (D3).

      Keyed by ensure_document on (source_url, 'funder_eligibility'). The text follows the newest
      research, as write_funder's columns do: every funder row is machine-made.
      """
      document_id, status = await ensure_document(
          conn, rec, owner=Owner.funder(funder_id), doc_type=rec.doc_type
      )
      content = rec.content_md()
      changed = await (
          await conn.execute(
              "UPDATE documents SET content_md = %s, title = %s, as_of = coalesce(%s, as_of), "
              "fetched_at = %s WHERE id = %s AND content_md IS DISTINCT FROM %s RETURNING id",
              (content, rec.title, rec.as_of, rec.fetched_at, document_id, content),
          )
      ).fetchone()
      if status == "matched" and changed is not None:
          status = "updated"
      return document_id, status
  ```
- [ ] **Step 5: Promote.** Imports: `EligibilityGuidelineRecord` instead of `FunderEligibilityRecord`, `write_eligibility_document` instead of `write_funder_eligibility`. `WRITE_ORDER`: replace `"funder_eligibility"` with `"eligibility_guideline"`. `CONCEPT_RECORDS["eligibility_guideline"] = EligibilityGuidelineRecord` (remove the old entry); delete `("funder_eligibility", "kind")` from `RENAMED`. `_row_identity`: `if concept == "eligibility_guideline": return (concept, f.source_url)`. Branch:
  ```python
                  elif concept == "eligibility_guideline":
                      rec = EligibilityGuidelineRecord(
                          title=f.title, statutory_restatement=f.statutory_restatement,
                          own_bar=f.own_bar, disqualifiers=f.disqualifiers, not_stated=f.not_stated,
                          as_of=f.as_of, **base,
                      )
                      _, status = await write_eligibility_document(conn, rec, funder_id)
                      _count(report, "documents (funder_eligibility)", status)
  ```
  (It is not added to `_write_documents`' `by_url`, so no fact cites the eligibility document as its source.) `_describe` already tries `title`.
- [ ] **Step 6: Brief and dossier.** Brief: replace the `funder_eligibility` headline branch with
  ```python
      if concept == "eligibility_guideline":
          if f.get("not_stated"):
              return _join(f.get("title"), "states no eligibility")
          return _join(f.get("title"), *(
              f"{label}: {f[key][:160]}" for key, label in (
                  ("statutory_restatement", "restates the statutory minimum"),
                  ("own_bar", "its own bar"), ("disqualifiers", "DISQUALIFIERS"))
              if f.get(key)))
      if concept == "funder_eligibility":
          return _join(_ELIGIBILITY_KINDS.get(f.get("kind"), f.get("kind")),
                       f.get("criterion"), f.get("notes"))
  ```
  and add `"funder_eligibility": "Eligibility it sets for applicants (saved before 0031)"` to `LEGACY_TITLES`. Dossier: replace the eligibility section:
  ```python
      (
          "eligibility (the funder_eligibility document: what it REQUIRES of applicants; not a judgement on any)",
          """
          SELECT id AS document_id, title, as_of, source_url, left(content_md, 1500) AS text
          FROM documents WHERE funder_id = %s AND doc_type = 'funder_eligibility'
          ORDER BY fetched_at DESC NULLS LAST, id DESC LIMIT 1
          """,
      ),
  ```
- [ ] **Step 7: Run.** `bt -m "'not integration'" -q` → 0 failed (all `CONCEPT_TABLES` parametrisations include `eligibility_guideline`). `ruff check .` clean.
- [ ] **Step 8: Commit.** `git add -A backend && git commit -m "feat(ingest): eligibility is a documents row, kept verbatim (D3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 15: Prompts, instructions and skills name the new tables

**Files:**
- Modify: `backend/app/ingest/prompts/entity_researcher.md` (line 14; lines 80-90)
- Modify: `backend/app/ingest/instructions.md` (lines 70-73, 77-95, 122, 150-153)
- Modify: `backend/app/ingest/skills/catalog-mapping/SKILL.md` (lines 61-73), `catalog-write-report/SKILL.md` (line 26), `funder-scan-for-fundraisers/SKILL.md` (lines 60-66), `funder-intake-research/SKILL.md` (lines 56-58, 67-70, 106-109 — wording only; the rewrite is PR (c))

**Interfaces:** text only. `test_ingest.py`'s tool-naming tests must still pass (no tool is renamed).

- [ ] **Step 1: Researcher prompt.** Line 14: replace "and an identifier enum of pan|cin|csr1|darpan|reg_no|domain|name, which has **no 12A, no 80G and no FCRA**" with "and a single CIN field, with **no 12A, no 80G and no FCRA**". Replace items 1-7 of "What to extract — a `funder`" with:
  ```markdown
  1. **funders** (concept `identity`) — name, website, funder type (`corporate_csr`, `corporate_foundation`, `private_foundation`, `family_trust`, `family_trust_network`, `other`), Section 135 applicability, parent/foundation relationship, the **CIN** of a company funder (a trust has none), other names it files under (`aliases`), and its stated posture: `intake_mode`, `funds_external`, `typical_duration_months`, the grant band. **Never merge a company with its foundation**, and never put the parent's CIN on the foundation: statutory filings belong to the corporate parent, the foundation is its child through the parent link.
  2. **funder_csr_years** (`csr_year`) — per FY: `section_135_applicable`, `average_net_profit`, `prescribed_csr`, `spent_on_projects`, `local_area_spent`, `admin_overheads`, `impact_assessment_cost`, `total_spent`, `unspent_transferred`, `excess_spent`, `impact_assessment_done`. Obligation, budget, allocation, actual spend, overhead and unspent are **not interchangeable**.
  3. **funder_activity, kind `spend`** (`csr_spend`) — the highest-value target. Per project *or* per aggregate: FY, project name, filed sector, state, district, designation, partner name and the partner's CSR-1, implementation mode, outlay, amount, project count. An aggregate has `project_name = null` and a `project_count`. **Never divide an aggregate across projects.** Every line carries a **domain** — `livelihoods`, `health`, `education`, `environment` or `others` — chosen from the project name and the named partner, not the filed sector; relief, sports, administration, unlabelled and multi-sector lines are `others`. Add a **theme** (a theme or sub-theme code) only where the evidence supports one, with `classification_note` quoting it. `classified_by` says what it rests on. These are inferences: say so.
  4. **funder_activity, kind `footprint`** (`footprint`) — where a theme actually ran, by FY, at the most precise level the source states. "Barpeta and Kamrup districts of Assam" is two districts, not one state. **Never invent a district from a city or a programme name.**
  5. **funder_locations** (`stated_geography`) — where the funder *says* it prioritises, role `priority`. Not proof of spending.
  6. **funder_activity, kind `partner`** (`partner`) — per FY and programme: partner name as printed, a canonical spelling, kind (`ngo`, `foundation`, `university`, `research`, `government`, `armed_forces`, `hospital`, `network`, `company`, `other`), the partner's CSR-1 if stated. Search both directions. Keep the year — repeated appearances mean renewal.
  7. **funder_activity, kind `programme`** (`programme_spend`) — the funder's **own** figure for a programme component in a year, from its own report. It is never added to the spend lines and never spread across them.
  ```
  Renumber the remaining items 8-15 and change "thirteen concepts across fourteen entries" to "fourteen concepts across fifteen entries". Add after the rfps item: "15. **eligibility** (`eligibility_guideline`) — the funder's standing eligibility, **verbatim**, one finding per page: the statutory restatement, its own bar, and disqualifiers, each in its own field. It becomes a document of type `funder_eligibility`. A page that states none is `not_stated` with its URL."
- [ ] **Step 2: `instructions.md`.** Lines 70-73: replace "An NGO sent at the funder list used to be offered `funder_type`, `section_135_bound` and an identifier enum with no room for any of them." with "An NGO sent at the funder list would be offered `funder_type`, `section_135_bound` and a CIN, with no room for any of them." Replace "The thirteen `funder` concepts" with "The fourteen `funder` concepts" and the table rows: delete the `identifier` row; `identity` → "name, website, funder type, Section 135, parent/foundation link, CIN, aliases, stated intake and grant band"; `csr_spend` → "the highest-value target — spend lines by FY and place, each with an inferred domain (and theme where evidenced)"; add rows `| \`programme_spend\` | the funder's own programme split per FY — never summed with spend lines |` and `| \`eligibility_guideline\` | its standing eligibility, verbatim, one document per page |`. Line 122: `\`funder\`, \`csr_years\`, \`activity\` (spend, footprints, partners, programme split), \`eligibility\`, \`programs\`, \`grants\`, \`metrics\`, \`contacts\`, \`documents\``. Lines 150-153: "`promote_research` moves thirteen of the fourteen concepts — identity, CSR years, spend lines, footprints, stated geography, partners, the funder's programme split, eligibility, programmes, metrics, contacts, documents and RFPs."
- [ ] **Step 3: Skills.** `catalog-mapping/SKILL.md` funder table — replace the rows from "project and sector spend" to "hard disqualifiers" with:
  ```markdown
  | project and sector spend | `funder_activity`, `kind='spend'`, with `domain_tag_id` / `theme_tag_id` inferred and `classified_by`, `classification_note` saying from what |
  | implementing partners | `funder_activity`, `kind='partner'` |
  | the funder's own programme split | `funder_activity`, `kind='programme'` — never summed with spend lines |
  | the funder's standing eligibility — statutory restatement, its own bar, disqualifiers | one `documents` row, `doc_type='funder_eligibility'`, the text verbatim under three headings, per page |
  | CIN and other names it files under | `funders.cin`, `funders.aliases` |
  ```
  and replace the three "no home" rows for intake route, grantmaker/implementer, duration with: "| intake route | `funders.intake_mode` |", "| says it funds external NGOs | `funders.funds_external` (stated) — `funder_activity.implementation_mode` is what it did |", "| typical duration, grant band | `funders.typical_duration_months`, `grant_size_min`, `grant_size_max` |" (keep "co-funding share" as **no home**). `catalog-write-report/SKILL.md` line 26: "`funder_csr_years` 3 rows, `funder_activity (spend)` 11 rows, `funder_locations` 4 rows." `funder-scan-for-fundraisers/SKILL.md` lines 60-66: "Two columns moved out of the middle category and the cells have to move with them. **Hard disqualifiers** and the **eligibility bar** are now stored, verbatim, in the funder's `funder_eligibility` document, under separate headings — so an empty cell there means *not recorded* or *not disclosed*, never *found, not storable*. Read them from the dossier rather than from the research prose, and keep the headings visible: a bar that only restates the statutory minimum is not a bar the funder chose." `funder-intake-research/SKILL.md`: field 4's "Both land in `funder_eligibility`, one row per condition, as `kind='statutory_restatement'` and `kind='own_bar'`." → "Both are quoted verbatim into one `eligibility_guideline` finding per page, in its `statutory_restatement` and `own_bar` fields; it becomes the funder's `funder_eligibility` document."; field 6's "They land in `funder_eligibility` as `kind='disqualifier'` — the same table, because…" → "They go in the same finding's `disqualifiers` field — the same document, because all three are conditions on the applicant; a separate heading, because a rejection ground is not a credential."; field 11's "field 4's land in `funder_eligibility`" → "field 4's land in the `funder_eligibility` document".
- [ ] **Step 4: Run.** `bt tests/test_ingest.py tests/test_harness.py -q` → pass. `grep -rn "funder_csr_spend\|funder_footprints\|funder_partners\|funder_identifiers" backend/app/ingest/prompts backend/app/ingest/skills backend/app/ingest/instructions.md` → no output.
- [ ] **Step 5: Commit.** `git add backend/app/ingest && git commit -m "docs(ingest): prompts and skills name funder_activity and the eligibility document" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 16: Platform and ingest docs

**Files:**
- Modify: `docs/DATA_PLATFORM.md` (lines 22, 26, 49, 107-113, 132-133, 163-166, 186-187, 290-305, 321-344; append a migration-table note after line 239)
- Modify: `docs/INGEST.md` (lines 207-224, 251-254)
- Modify: `seed/taxonomy_seed.py` (docstring line 5), `seed/data/taxonomy/schedule_vii.json` (`note`)

**Interfaces:** text only.

- [ ] **Step 1: `DATA_PLATFORM.md`.**
  - Line 22 "Funder money" after-cell: "`funder_csr_years` and `funder_activity` — one row per filing or report line, `kind` spend / footprint / partner / programme (0031 merged the three tables this began as) — for Axis alone: 4 CSR years, 58 spend lines, 705 footprints, 114 partner lines, each with its source".
  - Line 26: "`proposals`; a funder's form is a `documents` row of `doc_type='proposal_template'` (0031)".
  - Line 49: delete the `funder_identifiers` row; add `| \`funders\` | \`cin\`, \`aliases\` (0031) | a corporate funder's CIN and the other names it files under; funder_identifiers is gone |`.
  - Lines 107-109 → one row: `| | \`funder_activity\` | one line of a filing, report or partner list per year: \`spend\` (with outlay, partner and implementation mode), \`footprint\` (state and place), \`partner\`, or \`programme\` (the funder's own split, never summed with spend). Every spend and programme line carries an inferred domain and, where evidenced, a theme, with \`classified_by\`, a note and \`classification_confirmed\` |`.
  - Lines 112-113: replace with `| **Proposals** | \`documents\` (\`doc_type='proposal_template'\`) | a funder's application form, kept as a document; \`proposals.template_id\` points at it |`.
  - Lines 132-133: "…written back to `locations.aliases`, `funders.aliases` or `funder_activity.partner_canonical`, and resolving the queue is what finally fills `funder_activity.partner_org_id`, empty today."
  - Lines 163-166 diagram: `funder_activity  footprint · Baksa · FY2025-26`, `funder_activity  … 705 footprint lines across 3 reports`, `funder_activity  partner · 'Ayang Trust' · FY2025-26`, `funder_activity  spend · ₹8 crore · others (sports) · FY2024-25`.
  - Lines 186-187: `funder_activity.funder_id → funders.id` and `funder_activity.document_id → documents.funder_id → funders.id`.
  - After line 239 add: "**`0031_funder_consolidation` is the first migration that drops tables.** Nine funder tables became five: `funder_identifiers` → `funders.cin` / `aliases`; `funder_csr_spend`, `funder_footprints`, `funder_partners` → `funder_activity`; `funder_eligibility` and `proposal_templates` / `template_items` → `documents`. Every row with a home is copied; templates with content stop the migration. Spec: `features-plans/data-model/2026-10-07-funder-model-consolidation.md`."
  - Field table: 10 → "`funder_locations` (stated) and `funder_activity` `kind='footprint'` (actual)"; 15 → "`funders.funds_external` (stated) vs `funder_activity.implementation_mode` (done)"; 16 → "the funder's `funder_eligibility` document, verbatim, under statutory restatement / its own bar / disqualifiers; per call, `rfps.eligibility`"; 17 → "a `documents` row, `doc_type='proposal_template'` — **no writer yet**"; 22 → "`funder_activity` `kind='partner'`"; 23 → "**`funder_activity` `kind='partner'`** — `grants` has no writer"; 24 → "`funder_activity.amount` + `partner_name` on spend lines"; 25 → "`funder_activity.state_location_id` / `location_id` → `locations`"; 26 → "`funder_activity.csr_sector_id` (as filed) → `tags(kind='csr_sector')`; what it was spent on is `domain_tag_id` / `theme_tag_id`, inferred".
  - "Application process (17)": "A form is a `documents` row of `doc_type='proposal_template'` and has no writer. The URL of the form reaches `rfps.url`; the form's structure does not." "Eligibility (16)": replace "`funder_eligibility` holds the standing policy, one row per condition with its own source, `kind` carrying the split…" with "The standing policy is a `funder_eligibility` document per page, the text verbatim under the split `funder-intake-research` field 4 works to produce:". Grants (23): "`funder_activity` with `kind='partner'`, whose `partner_org_id` is nullable". Funds external (15): "counting `funder_activity.implementation_mode = 'implementing_agency'` on spend lines is what it *did*".
- [ ] **Step 2: `INGEST.md`.** Funder table: heading "A **funder** (14):"; delete `identifier`; `csr_spend` → "`funder_activity`, `kind='spend'`"; `footprint` → "`funder_activity`, `kind='footprint'`"; `partner` → "`funder_activity`, `kind='partner'`"; add rows `| programme_spend | \`funder_activity\`, \`kind='programme'\` |` and `| eligibility_guideline | \`documents\`, \`doc_type='funder_eligibility'\` |`. Add after the table: "Several concepts share one table. `ConceptSpec.row_filter` names the rows each owns and `ConceptSpec.columns` the columns it may fill; `expected_fields()`, `research_goals` and the writers read both." Line 253: "`funder_activity.partner_org_id` is nullable on a `partner` line, which is where such a relationship belongs…".
- [ ] **Step 3: Seed text.** `seed/taxonomy_seed.py` line 5 and the `note` in `schedule_vii.json`: `funder_csr_spend.csr_sector_id` → `funder_activity.csr_sector_id`.
- [ ] **Step 4: Verify.** `grep -n "funder_csr_spend\|funder_footprints\|funder_partners\|funder_identifiers\|template_items" docs/DATA_PLATFORM.md docs/INGEST.md seed/taxonomy_seed.py seed/data/taxonomy/schedule_vii.json` → only the historical `0007`/`0009` migration-table rows (lines ~234-236) and the new 0031 paragraph. `cmp seed/data/taxonomy/themes.json frontend/features/taxonomy/data/themes.json` unaffected (schedule_vii.json is not mirrored).
- [ ] **Step 5: Commit.** `git add docs seed && git commit -m "docs: funder_activity and the eligibility document in the platform and ingest docs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 17: Catalog removes the seven tables; counts everywhere

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (delete `funder_csr_spend`, `funder_eligibility`, `funder_footprints`, `funder_identifiers`, `funder_partners`, `proposal_templates`, `template_items` entries; comment at line 1012)
- Modify: `backend/app/ingest/expectations.py` (docstring line 3)
- Modify: `backend/tests/test_sql_catalog.py`
- Modify: `CLAUDE.md`, `docs/SQL_AGENT.md` (line 158-160), `README.md` (lines 111, 318)

**Interfaces:** `CATALOG` drops 7 tables. Counts on the base with #98: 42 → **36** tables; tables arriving in migrations 14 → **9**; tables with provenance columns 26 → **21**.

- [ ] **Step 1: Failing tests** (append to `test_sql_catalog.py`):
  ```python
  import re
  from pathlib import Path

  DROPPED_IN_0031 = ("funder_identifiers", "funder_eligibility", "funder_csr_spend", "funder_footprints",
                     "funder_partners", "proposal_templates", "template_items")


  class TestNineFunderTablesAreFive:
      @pytest.mark.parametrize("table", DROPPED_IN_0031)
      def test_a_dropped_table_is_neither_catalogued_nor_excused(self, table):
          assert table not in cat.TABLE_NAMES and table not in cat.KNOWN_EXCLUDED

      def test_funders_carry_cin_aliases_and_the_posture(self):
          assert {"cin", "aliases", "intake_mode", "funds_external", "typical_duration_months",
                  "grant_size_min", "grant_size_max"} <= set(cat.COLUMNS["funders"])


  def test_no_module_names_a_dropped_table():
      """funder_eligibility survives as a doc_type value, so only its use as a table is refused."""
      root = Path(cat.__file__).resolve().parents[3]          # backend/app
      gone = re.compile(
          r"\b(funder_identifiers|funder_csr_spend|funder_footprints|funder_partners|proposal_templates"
          r"|template_items)\b|(?:FROM|INTO|JOIN|UPDATE)\s+funder_eligibility\b"
      )
      hits = [
          f"{p.relative_to(root)}:{i}"
          for p in root.rglob("*") if p.suffix in {".py", ".md"}
          for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
          if gone.search(line)
      ]
      assert not hits, hits
  ```
  `bt tests/test_sql_catalog.py -q` → failures listing `catalog.py` lines.
- [ ] **Step 2: Remove the seven `Table` entries.** `_self_check()` passes: nothing catalogued references `proposal_templates` once `template_items` goes, and `proposals` stays in `KNOWN_EXCLUDED`. Fix the provenance comment: "Twenty-one of the catalogued tables carry this set; …". If the guard test lists any other file, reword that line (it is a docstring or comment naming the old table).
- [ ] **Step 3: Recount and fix the wording.**
  ```bash
  source /Users/vinod/GitHub/fc-env.sh && bpy "
  import glob, re
  from app.agent.tools.sql import catalog as c
  mig = set()
  for f in glob.glob('/w/db/migrations/*.sql'):
      mig |= set(re.findall(r'CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)', open(f).read()))
  print(len(c.CATALOG), len(set(c.CATALOG) & mig), len(c.PROVENANCE_COLUMNS))"
  ```
  Expected: `36 9 21`. Write those numbers: `expectations.py` docstring "the schema as data — 36 tables"; `CLAUDE.md` "9 of the SQL catalog's 36 tables arrive in `db/migrations/`" and "**allowlist, as data** — 36 tables"; and append to the Conventions migrations paragraph (after "…`docs/DATA_PLATFORM.md`."): "`0031_funder_consolidation` is the first that drops tables: nine funder tables became five."; `docs/SQL_AGENT.md`: "**In (36 tables after the v3 migrations, `tag_links` and `0031`'s funder consolidation; 28 when this was written):** … news_mentions, tags, tag_links, locations, extraction_log, `org_identifiers`, `funder_activity`, and all eight `*_tags` / `*_locations` join tables."; `README.md` line 111 "9 of the 36 tables", line 318 "An allowlist catalog of 36 tables".
- [ ] **Step 4: Run.** `bt -m "'not integration'" -q` → 0 failed. `cd backend && ruff check .` clean.
- [ ] **Step 5: Commit.** `git add -A backend CLAUDE.md docs/SQL_AGENT.md README.md && git commit -m "feat(sql): the catalog drops the seven tables 0031 removed" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 18: Final verification

**Files:** none changed unless a check fails.

- [ ] **Step 1: Unit tier and lint.** `source /Users/vinod/GitHub/fc-env.sh && bt -m "'not integration'" -q` → 0 failed (≥ 602 + the new tests passed). `cd backend && ruff check .` → clean.
- [ ] **Step 2: Integration tier on `sangam_fc`.** `bti tests/test_funder_consolidation_migration.py tests/test_sql_integration.py tests/test_rls.py tests/test_funder_activity.py tests/test_eligibility_document.py tests/test_storage.py -m integration -q` → 0 failed (`test_no_drift` and `test_every_live_table_is_either_catalogued_or_knowingly_excluded` now pass; the migration `before` tests skip).
- [ ] **Step 3: Boot gate.**
  ```bash
  bpy "
  import asyncio, psycopg
  from psycopg.rows import dict_row
  from app.agent.tools.sql.catalog import verify_against_db
  async def main():
      async with await psycopg.AsyncConnection.connect('host=postgres user=sangam password=sangam dbname=sangam_fc', row_factory=dict_row) as c:
          print(await verify_against_db(c))
  asyncio.run(main())"
  ```
  Expected: `[]`.
- [ ] **Step 4: Frontend.** `cd frontend && npx tsc --noEmit` (worktree) → exit 0; `npm run lint` → clean.
- [ ] **Step 5: Smoke — after merge, not on this branch.** `make smoke` exercises the running stack, which serves master. After this PR merges, the owner runs `make migrate` on the dev DB and then `make smoke` (`SMOKE_SKIP_LLM=1` for the cheap run); `funders: latest_scores` and `funder profile renders` must pass. Say so in the PR description.
- [ ] **Step 6: Supabase pre-flight (for the person who runs `make migrate ENV=staging`).** Put this in the PR description:
  ```sql
  SELECT 'funder_identifiers' t, count(*) FROM funder_identifiers UNION ALL
  SELECT 'funder_eligibility', count(*) FROM funder_eligibility UNION ALL
  SELECT 'funder_csr_spend', count(*) FROM funder_csr_spend UNION ALL
  SELECT 'funder_footprints', count(*) FROM funder_footprints UNION ALL
  SELECT 'funder_partners', count(*) FROM funder_partners UNION ALL
  SELECT 'proposal_templates', count(*) FROM proposal_templates UNION ALL
  SELECT 'template_items', count(*) FROM template_items UNION ALL
  SELECT 'proposals with a template', count(*) FROM proposals WHERE template_id IS NOT NULL;
  SELECT upper(regexp_replace(id_value, '\s', '', 'g')) cin, count(DISTINCT funder_id)
  FROM funder_identifiers WHERE id_type = 'cin' GROUP BY 1 HAVING count(DISTINCT funder_id) > 1;
  ```
  Templates or template items above zero stop the migration by design; a CIN shared by two funders would violate `funders.cin UNIQUE` — resolve it first. Then a backup, then `make migrate ENV=staging`. Note in the PR that "staff only" and RLS for the new table follow #92's rules (granted public read, hidden with a hidden funder), and that #89's author reviews the eligibility change.
- [ ] **Step 7: Clean up.** `docker exec sangam-postgres-1 dropdb -U sangam sangam_fc`; `rm /Users/vinod/GitHub/fc-env.sh`.

---

## Self-review: spec coverage

| Spec item | Task |
|---|---|
| D1 — funders keep a CIN, not CSR-1/PAN/12A/80G | 1 (pan/csr1/darpan/reg_no discarded), 3 (`cin` only), 5 (`identifiers` map removed) |
| D2 — `funder_identifiers` goes; `funders.cin`, `aliases` | 1 (step 1-2, step 6), 3, 4, 5, 6, 7, 17 |
| D3 — eligibility is a `documents` row, verbatim | 1 (copy), 13, 14, 15, 16 |
| D4 — three tables merge into `funder_activity` with `kind` | 1, 2, 9, 10, 11, 12 |
| D5 — templates are `documents` rows; `proposals.template_id` → documents | 1 (guard, FK repoint, drop), 16, 17 |
| D7 — filings attach to the corporate parent; foundation is the child | 4 (`_same_organisation`, held CIN), 2 (column note), 15 (prompt) |
| D11 — domain/theme inferred, evidenced, confirmable | 1 (columns), 2 (notes, defect), 9 (`resolve_classification`), 10 (finding validator, writer never sets `classification_confirmed`, confirmed rows not re-inferred), 15 |
| D12 — programme split at funder level, never spread | 12, 2 (defect), 15 |
| §2 `funders` + `cin`, `aliases`; posture columns wired into catalog and identity writer | 1, 3 |
| §2 `funder_activity` DDL, kinds, classification columns, indexes | 1 (verbatim), 2 |
| §2 old→new column mapping (agency → `partner_*`, `via_agency` → `implementation_mode`, district/location → `location_id`) | 1 (copy SQL), 10, 11 |
| §2 `funder_csr_years.local_area_spent` | 1, 8 |
| §2 documents doc_types + `ensure_document` dedupe on `(source_url, doc_type)` | 13 (see resolution 1), 14 |
| §2 migration steps 1-7, Supabase checks | 1, 18 |
| §3 `expectations.py` — activity concepts with fixed kind, per-concept columns, new `programme_spend`, drop `identifier`/`funder_eligibility`, identity gains columns, "40 tables" | 3, 5, 9, 10, 11, 12, 14, 17 |
| §3 `records.py`, `research_records.py` — drop identifiers/`IdentifierFinding`/`FunderEligibilityRecord`, add kind, add eligibility finding | 5, 10, 11, 12, 14 |
| §3 `writer.py` — one `FUNDER_ACTIVITY_KEY` with kind, drop `_write_identifiers`/`write_funder_eligibility`, `write_funder` cin/aliases/posture, `ensure_document` | 3, 5, 10, 11, 12, 13, 14 |
| §3 `promote.py` — `WRITE_ORDER`, `CONCEPT_RECORDS`, `RENAMED`, `_row_identity`, eligibility → documents | 5, 10, 11, 12, 14 |
| §3 `matcher.py` — CIN and aliases on funders; org matching untouched | 4 |
| §3 `brief.py`, `catalog_tools.py` — dossier by kind, eligibility from latest document, `_held_per_concept` by kind | 5, 8, 9, 10, 11, 12, 14 |
| §3 `runner.py`, `geography.py`, `extractor.py` | 11 (runner, geography); extractor verified unchanged (File Structure note) |
| §3 `catalog.py` — add `funder_activity`, remove 6 + `proposal_templates`, funders columns, counts | 2, 3, 8, 13, 17 |
| §3 API/schema/frontend type | 6 |
| §3 `seed.py`, `graph_seed.py` | 7; graph_seed verified unchanged |
| §3 skills and prompts (table names, eligibility-as-document, classification columns) | 15 |
| §3 tests (`test_ingest.py` parametrisations, `WRITE_ORDER`, `_row_identity`, `MERGEABLE`, `apart`, identifier rejection; `test_sql_catalog.py`; `test_migration_integrity.py`; `test_sql_integration.py`) | 4, 5, 9-14, 17, 18. `test_migration_integrity.py` needs no edit (it asserts documents, orgs and funders, which 0031 keeps); the migration's own integrity is the new `test_funder_consolidation_migration.py`. |
| §3 docs `DATA_PLATFORM.md`, `INGEST.md`; CLAUDE.md, SQL_AGENT.md counts | 16, 17 |
| §2 step 7 / #92 — classify `funder_activity` | 1 (grant, RLS, policy, test) |

**Ambiguities resolved:**
1. **Dedupe key.** The spec says `(source_url, doc_type)`. Taken literally, one PDF that two research runs call `annual_report` and `csr_annexure` becomes two rows. The plan keys on `(source_url, doc-type class)`: the class is the doc_type itself for the three reserved types and one shared class for all other types. The spec's stated purpose still holds — a policy page can be both the source document and the eligibility document.
2. **"Add `kind` to the activity records."** Each record's `kind` field is already the Pydantic discriminator (`"funder_csr_spend"`, and so on). The activity kind is therefore a `ClassVar`, `activity_kind`, which the writers read. It is not a second field.
3. **How the eligibility finding works.** `funder_eligibility` stays as a doc_type value but is no longer a concept name. The new concept is `eligibility_guideline` (model `EligibilityGuidelineFinding`): one finding per page, with three verbatim fields and a `not_stated` flag. It writes `content_md` under three headings, and the migration writes the same three, with a test holding them together. The spec does not say whether to copy existing `funder_eligibility` rows. The plan copies them, one document per funder per page, rather than refusing, because they have a lossless home.
4. **Footprint location split.** The spec maps `funder_footprints.location_id` → `location_id`. The plan sends a state-level location to `state_location_id`, and a place below a state to `location_id` with its state parent in `state_location_id`. This matches the meaning of the new columns ("most specific place below state").
5. **`via_agency` NULL.** It maps to NULL, not `'not_stated'`. "Unknown" and "the source said nothing" are kept apart.
6. **Domain is required** on `csr_spend` and `programme_spend` findings (D6 says every line carries one). Spend findings saved in the old shape fail re-validation. `_validated` now reports each refusal in `held` instead of only logging it. The plan adds no renamer for old field names, and `SCHEMA_VERSION` is not bumped.
7. **Saved `identifier` findings** are folded into the funder record (cin, name → aliases, domain → website), mirroring migration step 2. Saved `funder_eligibility` findings stay as research: the brief renders them under a "saved before 0031" heading, and they are not promoted.
8. **CIN matching (D7).** A CIN hit merges only when the names agree apart from boilerplate and both or neither are a foundation or trust. Anything else falls through to the name steps. Promotion holds back a CIN that another row already has, rather than violating `UNIQUE`.
9. **Detail API** adds `aliases` as well as `cin`. Dropping `identifiers` would otherwise lose the name aliases the API returned before.
10. **Counts** assume #98 is merged: 36 catalog tables, 9 of them from migrations, 21 with provenance. Task 17 has the executor print them, so a different base shows up as a mismatch.
