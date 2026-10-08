# Grants into funder_activity — Implementation Plan

> **For agentic workers:** REQUIRED: execute this plan with superpowers:subagent-driven-development — a fresh implementer subagent per task, a fresh reviewer subagent checking each task before the next starts, and a whole-branch review at the end. Do not use executing-plans or implement inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the `grants` table (C4). Every grant becomes a `funder_activity` line with `kind = 'partner'` and `partner_org_id` set, and `funder_activity` gains `start_date`, `end_date` and `relationship_status`. `proposals`, `metrics` and `news_mentions` are re-pointed from `grant_id` to the new line. `grant_locations` and `grants` are dropped (C5, the grants part). `/api/grants` keeps its exact JSON shape as a compatibility read over partner lines. Every reader and writer moves with the schema: the SQL catalog, citation markers, the Ask index, the seed, the graph seed and Sangam Import. In Import, the `grant` concept folds into `partner`, and an NGO's own research can now write the funder's partner line.

**Architecture:** One forward-only migration, `db/migrations/0034_grants_into_funder_activity.sql`, runs in this order:
1. It refuses what it cannot carry: `grant_locations` rows, non-INR amounts, and key collisions.
2. It adds the three columns.
3. It copies `grants` row by row through a temporary `legacy_grant_id` column. That column is the id map.
4. It re-points the three referencing tables through the map, and asserts that nothing was left unmapped.
5. It drops the old columns and both tables, then drops the map column.

`funder_activity` already has its grants and RLS policy from #99's 0031, so there is nothing new to classify. The task tests that the migrated rows obey the policy.

`/api/grants` is a **repository query**, not a SQL VIEW. A view runs as its owner, so it would bypass RLS. Routes run as the caller (#92), and the funder-activity policy and the orgs policy decide visibility.

Citations get a new marker, `[activity:N]`, carried on `funder_activity.id`. The catalog's `cites` is per column, so marking that column `grant` would label every spend, footprint and programme line a grant. `[grant:N]` stays in the frontend grammar only so old saved answers still render, unlinked.

In Import, `partner` gains `project_name`, `start_date`, `end_date` and `relationship_status`. A funder-side partner line links `partner_org_id` only when the org matcher would merge (exact, alias, identifier or boilerplate), never on a trigram resemblance. An org-side partner finding names its funder (`funder_name`). It writes the funder's line, with `partner_org_id` set to the NGO, and only when that funder already exists. Saved `grant` findings are folded into partner findings at promotion, following (b)'s `FOLDED` pattern.

**Tech Stack:** PostgreSQL 17 + pgvector (compose), raw psycopg 3 (no ORM), FastAPI, Pydantic v2, pytest (`asyncio_mode = "auto"`), Next.js/TypeScript (no frontend unit runner: `tsc`, `eslint`, `next build`).

**Spec:** features-plans/data-model/2026-10-07-cso-model-consolidation.md (§2 grants → funder_activity; C4, C5)

## Global Constraints

- **Base branch and preconditions.** Start from `origin/master` **after** #99's (a), (b) and (c) and this spec's PR (d) have merged. Run this first:
  ```bash
  git -C /Users/vinod/GitHub/sangam fetch origin
  git -C /Users/vinod/GitHub/sangam grep -l "CREATE TABLE funder_activity" origin/master -- db/migrations   # expect the 0031 file
  git -C /Users/vinod/GitHub/sangam ls-tree --name-only origin/master db/migrations/ | grep -E '^db/migrations/0033_'   # expect 0033_cso_consolidation.sql
  git -C /Users/vinod/GitHub/sangam grep -n "FOLDED = frozenset" origin/master -- backend/app/ingest/promote.py   # (b) Task 5
  git -C /Users/vinod/GitHub/sangam grep -n "def _activity_key" origin/master -- backend/app/ingest/writer.py     # (b) Task 10
  ```
  If any of these fails, stop. This plan edits code (b) introduced: `FUNDER_ACTIVITY_KEY`, `FUNDER_ACTIVITY_UPDATABLE`, `_write_activity`, `_activity_key`, `write_partner`, `_activity_identity`, `ConceptSpec.row_filter`/`columns`, `FOLDED`, `brief.LEGACY_TITLES`, and the `recording_conn`/`recording_pool` fixtures.
- **Never edit `/Users/vinod/GitHub/sangam`.** It serves a running dev site. Work in a worktree:
  ```bash
  git -C /Users/vinod/GitHub/sangam worktree add /Users/vinod/GitHub/sangam-grants-activity -b feat/grants-into-funder-activity origin/master
  cd /Users/vinod/GitHub/sangam-grants-activity
  ```
- **Never migrate the shared dev database `sangam`.** All integration work runs against a scratch clone, `sangam_ge`, on the same container (`sangam-postgres-1`).
- **Test commands.** The host has no pytest. Save this file **outside the worktree** (never commit it) and start every command with `source /Users/vinod/GitHub/ge-env.sh &&`:
  ```bash
  # /Users/vinod/GitHub/ge-env.sh
  WT=/Users/vinod/GitHub/sangam-grants-activity
  _run() { docker run --rm --network sangam_default -v "$WT":/w -w /w/backend "$@"; }
  bt()  { _run --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  bti() { _run -e TEST_DATABASE_URL=postgresql://sangam:sangam@postgres:5432/sangam_ge --entrypoint sh sangam-backend:latest -c "pip install -q pytest pytest-asyncio >/dev/null 2>&1; python -m pytest -p no:cacheprovider $*"; }
  mig() { _run -e DATABASE_URL="host=postgres user=sangam password=sangam dbname=sangam_ge" -e MIGRATIONS_DIR=/w/db/migrations --entrypoint python sangam-backend:latest -m app.db.migrate "$@"; }
  bpy() { _run --entrypoint python sangam-backend:latest -c "$1"; }
  psql_ge() { docker exec -i sangam-postgres-1 psql -U sangam -d sangam_ge "$@"; }
  ```
  If `docker` reports that the daemon is not running, start Docker Desktop. While this plan was being written the daemon was down, so the local data described below comes from `seed/data/grants.json`, not from a query. Task 1 Step 1 re-runs the query.
- **Record the unit baseline before Task 1:** `bt -m "'not integration'" -q`. "Green" below means **0 failed**.
- `ruff check .` runs on the host (`cd backend && ruff check .`, line-length 110). Frontend checks run in the worktree: `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit && npm run lint && npm run build`.
- **Conventions** (CLAUDE.md, `db/migrations/README.md`):
  - Schema changes go only in `db/migrations/`.
  - A destructive migration carries a note on why the data makes it safe.
  - Never edit an applied migration. 0025 and 0027 keep naming `grants` and `grant_locations`, and their `to_regclass` guards make that harmless.
  - Unit tests never touch a DB. Integration tests carry `pytestmark = pytest.mark.integration`.
  - Agent tools never raise and cite every row.
  - A catalog change is a security decision.
- **Never run `make evals`.** It bills real model calls. Task 5 edits `golden.jsonl` and does not run it.
- **Expected red:**
  - After Task 1 applies 0034 to `sangam_ge`, `tests/test_sql_integration.py::TestCatalogMatchesReality::test_no_drift` fails there until Task 5 removes `grants` and `grant_locations` from the catalog. Do not run it before Task 10.
  - `tests/test_migration_integrity.py::test_v2_content_present` fails against `sangam_ge` until Task 8.
- Every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Migration number: `0034`.** It follows (d)'s `0033_cso_consolidation.sql`. If another branch takes 0034 first, rename the file to the next free number at merge time and update `MIGRATION` in its test.

**Local data (from `seed/data/grants.json`):** four grants, all to `kabil`.
- All four have `amount` NULL: the seed never inserts one.
- Two have no `start_date` or `end_date` (Azim Premji Foundation, SBI Foundation). Their fiscal year therefore comes from `fetched_at` (`2026-09-10` → `FY2026-27`).
- One spans four fiscal years (Axis Bank Foundation, 2018-04-01 to 2022-03-31).
- `grant_locations` has 0 rows.
- `metrics.grant_id` and `news_mentions.grant_id` are NULL everywhere: the catalog's own defect says so for news.
- `proposals` is expected to be empty.

## Review Focus

Five failure modes the unit suite can pass straight through. Each has a named test in the task that owns it.

1. **A multi-year grant's amount is read as one year's money.**
   - The decision: one grant is one line. The **whole** amount sits on the start date's fiscal year with `start_date` and `end_date` set. It is never split: a split would invent a schedule no source gave.
   - The agent must be told. #99's partner defect says the amount is "that year's", and that wording is amended here.
   - Tests: Task 1 `test_a_multi_year_grant_is_one_line_with_its_whole_amount`; Task 2 `test_a_multi_year_amount_is_flagged_to_the_agent`; Task 3 `test_a_multi_year_grant_is_one_partner_line`.
2. **Citation markers break in Ask answers.**
   - The agent stops emitting `[grant:N]`.
   - The frontend must link `[activity:N]` and must still render an old `[grant:N]` without pointing it at whichever activity line now holds that number.
   - The prompt must name the new marker.
   - Tests: Task 2 `test_an_activity_line_is_citable`; Task 5 `test_tools_emit_the_markers_we_think_they_do`; Task 7 `test_the_frontend_links_every_marker_the_tools_emit`, and `tsc` over `citationTarget`'s exhaustive switch.
3. **The Registry "Known funders" and "Recorded grants" tabs drift in shape.**
   - `GrantOut` must keep every field.
   - A partner line Import wrote (NULL project, NULL status) must not 500 the route.
   - A partner line with no catalogued org must not appear.
   - A hidden org's and an internal line's grants must reach only staff.
   - Tests: Task 6 `test_the_grant_shape_is_frozen`, `test_an_import_shaped_partner_line_reads_as_a_grant`, `test_only_partner_lines_naming_a_catalogued_org_are_grants`, `test_a_hidden_org_or_internal_line_reaches_only_staff`.
4. **Re-pointing `proposals`, `metrics` or `news_mentions` loses a reference.**
   - Every non-null `grant_id` must reach the new column through the id map.
   - The migration asserts this before any drop.
   - The tables are dropped, never `DELETE`d, because `metrics.grant_id` is `ON DELETE CASCADE`.
   - Tests: Task 1 `test_references_follow_their_grant`, `test_every_grant_is_copied_before_anything_is_dropped`.
5. **Supabase holds grants (or grant places) the local DB does not.**
   - The migration must copy every row.
   - It must stop rather than silently drop `grant_locations` rows.
   - It must stop on non-INR amounts and on a grant that would collide with an existing partner line.
   - Tests: Task 1 `test_grant_locations_with_rows_stop_the_migration`, `test_a_non_inr_amount_stops_the_migration`, `test_a_grant_already_on_a_partner_line_stops_the_migration`, `test_two_grants_on_one_line_stop_the_migration`; Task 10 pre-flight counts on Supabase before `make migrate ENV=staging`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `db/migrations/0034_grants_into_funder_activity.sql` | create | The three columns, the guarded copy, re-pointing, the drops |
| `backend/tests/test_grants_into_activity_migration.py` | create | Integration: the copy (rolled back, pre-0034 DB), the post-state, RLS on migrated rows |
| `backend/app/agent/tools/sql/catalog.py` | modify | `funder_activity` gains 3 columns, `id` cites `activity`, notes; `metrics`/`news_mentions` `activity_id`; drop `grants`, `grant_locations`; cite-kind set |
| `backend/app/agent/tools/sql_tools.py` | modify | docstring example table |
| `backend/app/agent/instructions.md` | modify | rules 2 and 8: `[activity:N]`, `funder_activity.id` |
| `backend/tests/test_sql_catalog.py`, `test_sql_validator.py`, `test_sql_errors.py`, `test_prompt.py` | modify | the grants examples and the marker sets |
| `backend/tests/evals/harness.py`, `backend/tests/evals/cases/golden.jsonl` | modify | marker regex; `gold_sql` of `grants-per-funder` |
| `backend/app/ingest/expectations.py` | modify | drop `grant`; `partner` columns, kinds, `EXTRA["partner"]` |
| `backend/app/ingest/research_records.py` | modify | `PartnerFinding` gains grant fields + `funder_name`; drop `GrantFinding` |
| `backend/app/ingest/records.py` | modify | `fiscal_year_of`; `FunderPartnerRecord` gains grant fields |
| `backend/app/ingest/writer.py` | modify | `FUNDER_ACTIVITY_UPDATABLE`; `write_partner(..., partner_org_id)` keyed on `project_name` |
| `backend/app/ingest/promote.py` | modify | `_partner_org`, `_legacy_grants`, `FOLDED`, `_row_identity`, partner branch for both kinds, `ORG_WRITE_ORDER` |
| `backend/app/ingest/brief.py` | modify | partner headline; `LEGACY_TITLES["grant"]` |
| `backend/app/ingest/tools/catalog_tools.py` | modify | funder and org dossier sections; `_held_per_concept` fk for org; `promote_research` text |
| `backend/tests/test_grants_as_partner_lines.py` | create | Unit: the fold, the writer, both promote paths, dossier SQL, the seed's fiscal year |
| `backend/tests/test_funder_activity.py` | modify | #99's partner tests stub the org matcher |
| `backend/tests/test_ingest.py` | modify | `PROMOTABLE` exclusion sets, `by_concept("grant")`, org/funder overlap |
| `backend/app/repositories/grants.py`, `backend/app/repositories/news.py`, `backend/app/api/router.py` | modify | compatibility read; stats count; tag text |
| `backend/tests/test_grants.py` | create | Unit (route shape) + integration (RLS via the caller role) |
| `frontend/features/ask/lib/citations.ts`, `sources.ts`, `AskWorkspace.tsx`, `preview/AskPreview.tsx`, `preview/sample.ts`, `frontend/app/(agent)/ask/page.tsx` | modify | `activity` kind and `activities` index; `grant` kept as a retired, unlinked marker |
| `seed/seed.py`, `seed/graph_seed.py` | modify | `grants.json` → partner lines; graph episodes read partner lines |
| `backend/tests/test_migration_integrity.py`, `scripts/smoke.sh` | modify | counts on partner lines; `>= 4` |
| `backend/app/ingest/instructions.md`, `prompts/entity_researcher.md`, skills `entity-record`, `ngo-brief-for-funders`, `funder-intake-research` | modify | grants are partner lines; an NGO's funders are partner findings |
| `CLAUDE.md`, `README.md`, `docs/DATA_PLATFORM.md`, `docs/INGEST.md`, `docs/SQL_AGENT.md` | modify | markers, table counts, the grants story |

These were checked and need **no change**:
- `frontend/features/registry/ProfileTabs.tsx`, `frontend/app/registry/[slug]/page.tsx`, `frontend/app/registry/funders/[slug]/page.tsx`. They read `GrantRow` through `/api/grants`, whose shape is frozen.
- `frontend/lib/api/types.ts::GrantRow`.
- `schemas/grants.py`. Its shape is the contract.
- `backend/app/api/routes/grants.py`. It calls the repository by name.
- `EvidenceRail.tsx`. It reads `stats.grants`, whose key stays.
- `schemas/funders.py::GrantSummary` is unused. Leave it: removing it is unrelated cleanup.

---

### Task 1: Migration 0034 and its integration tests

**Files:**
- Create: `db/migrations/0034_grants_into_funder_activity.sql`
- Create: `backend/tests/test_grants_into_activity_migration.py`

**Interfaces:**
- Consumes:
  - `grants` (02_schema.sql:152-174, plus 0001's `as_of`/`document_id`/`archive_url`);
  - `grant_locations` (0003);
  - `metrics.grant_id` (0008, `ON DELETE CASCADE`);
  - `proposals.grant_id` (0009);
  - `news_mentions.grant_id` (02_schema.sql:220 — that `grant_id` is on `news_mentions`, the table defined at 02_schema.sql:207-223);
  - `funder_activity` and its `UNIQUE NULLS NOT DISTINCT (funder_id, kind, fiscal_year, program_id, csr_sector_id, state_location_id, location_id, designation, project_name, partner_name)` (#99 0031);
  - policy `funder_activity_read`: `(is_public OR app.is_staff()) AND funder visible`.
- Produces:
  - `funder_activity.start_date date`, `.end_date date`, `.relationship_status text CHECK (… 'active','concluded','unconfirmed','dormant')`;
  - `proposals.awarded_activity_id → funder_activity(id)`;
  - `metrics.activity_id → funder_activity(id) ON DELETE CASCADE`;
  - `news_mentions.activity_id → funder_activity(id)`;
  - tables `grants`, `grant_locations` and the three `grant_id` columns gone.
  - Each copied line's `notes` ends with `Moved from grants #<id> by 0034.`
- The fiscal-year rule is shared with Task 3's `records.fiscal_year_of` and Task 8's `seed.fiscal_year_of`, all pinned to the same literal labels:
  - the year comes from `start_date`, else `end_date`, else `fetched_at`, else `valid_from`;
  - the label is the Indian FY, April to March, e.g. 2018-04-01 → `FY2018-19`, 2019-03-31 → `FY2018-19`, 1999-06-01 → `FY1999-00`.

- [ ] **Step 1: Look at the data, then build the scratch database at the base head.**
  ```bash
  docker exec sangam-postgres-1 psql -U sangam -d sangam -c "select * from grants" \
    -c "select count(*) from grant_locations" \
    -c "select count(*) filter (where grant_id is not null) from metrics" \
    -c "select count(*) filter (where grant_id is not null) from news_mentions" \
    -c "select count(*) filter (where grant_id is not null) from proposals"
  docker exec sangam-postgres-1 sh -c 'createdb -U sangam sangam_ge && pg_dump -U sangam sangam | psql -q -U sangam -d sangam_ge'
  source /Users/vinod/GitHub/ge-env.sh && mig --status && mig
  psql_ge -tc "select max(version) from schema_migrations"
  ```
  - Expected: 4 grants. Compare them with `seed/data/grants.json`; if the database holds more, note them in the PR. 0 everywhere else.
  - `mig` applies everything pending through `0033_cso_consolidation`. The last line prints `0033_cso_consolidation`.

- [ ] **Step 2: Write the failing copy tests.** Create `backend/tests/test_grants_into_activity_migration.py`:
  ```python
  """0034: grants become funder_activity partner lines.

  The copy is tested by running the migration inside a rolled-back transaction on a database that has not
  had it; the result is tested on one that has. Run against the scratch clone
  (TEST_DATABASE_URL=…/sangam_ge), never the shared dev database.
  """

  from __future__ import annotations

  import json
  import os
  from datetime import date
  from pathlib import Path
  from uuid import uuid4

  import psycopg
  import pytest
  from psycopg import errors
  from psycopg.rows import dict_row

  DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://sangam:sangam@localhost:5433/sangam")
  ROOT = Path(__file__).resolve().parents[2]
  MIGRATION = ROOT / "db" / "migrations" / "0034_grants_into_funder_activity.sql"

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
      return conn.execute("SELECT to_regclass('public.grants') AS t").fetchone()["t"] is None


  @pytest.fixture
  def before(conn):
      if _applied(conn):
          pytest.skip("0034 is already applied here; the copy is tested on a database before it")
      with conn.transaction(force_rollback=True):
          yield conn


  @pytest.fixture
  def after(conn):
      if not _applied(conn):
          pytest.skip("0034 is not applied here yet")
      with conn.transaction(force_rollback=True):
          yield conn


  def _one(conn, sql, params=()):
      return conn.execute(sql, params).fetchone()


  def _funder(conn, name="Acme Foundation", status="placeholder"):
      return _one(conn, "INSERT INTO funders (slug, name, registry_status) VALUES (%s, %s, %s) RETURNING id",
                  (f"ge-{uuid4().hex[:8]}", name, status))["id"]


  def _org(conn, name="Harsha Trust", status="placeholder"):
      return _one(conn, "INSERT INTO orgs (slug, name, registry_status) VALUES (%s, %s, %s) RETURNING id",
                  (f"ge-{uuid4().hex[:8]}", name, status))["id"]


  def _grant(conn, funder, org, title, **cols):
      cols = {"status": "active", **cols}
      names = ", ".join(["funder_id", "org_id", "title", *cols])
      marks = ", ".join(["%s"] * (3 + len(cols)))
      return _one(conn, f"INSERT INTO grants ({names}) VALUES ({marks}) RETURNING id",
                  (funder, org, title, *cols.values()))["id"]


  def _migrate(conn):
      conn.execute(MIGRATION.read_text(encoding="utf-8"))


  def _line(conn, grant_id):
      return _one(conn, "SELECT * FROM funder_activity WHERE notes LIKE %s",
                  (f"%Moved from grants #{grant_id} by 0034.",))


  def test_a_grant_becomes_a_partner_line(before):
      conn = before
      f, o = _funder(conn), _org(conn, "Harsha Trust")
      g = _grant(conn, f, o, "Livelihoods in Barpeta", amount=750000, start_date=date(2023, 6, 1),
                 end_date=date(2024, 3, 31), status="concluded", outcomes=json.dumps({"families_reached": 120}),
                 notes="From the annual report.", source_url="https://a.b/c", source_name="report")
      _migrate(conn)
      line = _line(conn, g)
      assert (line["kind"], line["funder_id"], line["partner_org_id"]) == ("partner", f, o)
      assert (line["partner_name"], line["partner_canonical"], line["project_name"]) == (
          "Harsha Trust", "Harsha Trust", "Livelihoods in Barpeta")
      assert (line["fiscal_year"], line["amount"], line["relationship_status"]) == ("FY2023-24", 750000, "concluded")
      assert (line["start_date"], line["end_date"]) == (date(2023, 6, 1), date(2024, 3, 31))
      assert line["is_public"] is True and line["source_url"] == "https://a.b/c"
      assert "From the annual report." in line["notes"] and "families_reached 120" in line["notes"]


  def test_a_multi_year_grant_is_one_line_with_its_whole_amount(before):
      conn = before
      f, o = _funder(conn), _org(conn)
      g = _grant(conn, f, o, "Four-year project", amount=40000000,
                 start_date=date(2018, 4, 1), end_date=date(2022, 3, 31), status="concluded")
      _migrate(conn)
      lines = conn.execute("SELECT * FROM funder_activity WHERE funder_id = %s", (f,)).fetchall()
      assert len(lines) == 1, "never split across years: no source gave a schedule"
      assert (lines[0]["fiscal_year"], lines[0]["amount"]) == ("FY2018-19", 40000000)
      assert (lines[0]["start_date"], lines[0]["end_date"]) == (date(2018, 4, 1), date(2022, 3, 31))
      assert _line(conn, g)["id"] == lines[0]["id"]


  @pytest.mark.parametrize(("cols", "year", "said"), [
      ({"start_date": date(2019, 3, 31)}, "FY2018-19", None),
      ({"end_date": date(2014, 3, 31)}, "FY2013-14", "end date"),
      ({"fetched_at": "2026-09-10T00:00:00Z"}, "FY2026-27", "the source was read"),
      ({"start_date": date(1999, 6, 1)}, "FY1999-00", None),
  ])
  def test_the_fiscal_year_falls_back_and_says_so(before, cols, year, said):
      conn = before
      g = _grant(before, _funder(conn), _org(conn), "A grant", **cols)
      _migrate(conn)
      line = _line(conn, g)
      assert line["fiscal_year"] == year
      if said:
          assert said in line["notes"] and "start date was not stated" in line["notes"]
      else:
          assert "start date was not stated" not in line["notes"]


  def test_references_follow_their_grant(before):
      conn = before
      f, o = _funder(conn), _org(conn)
      g = _grant(conn, f, o, "Referenced grant")
      metric = _one(conn, "INSERT INTO metrics (org_id, grant_id, name, value) VALUES (%s, %s, 'families', 10) "
                          "RETURNING id", (o, g))["id"]
      news = _one(conn, "INSERT INTO news_mentions (url, grant_id) VALUES (%s, %s) RETURNING id",
                  (f"https://news.example/{uuid4().hex}", g))["id"]
      proposal = _one(conn, "INSERT INTO proposals (org_id, funder_id, title, status, grant_id) "
                            "VALUES (%s, %s, 'Ask', 'awarded', %s) RETURNING id", (o, f, g))["id"]
      _migrate(conn)
      line = _line(conn, g)["id"]
      assert _one(conn, "SELECT activity_id FROM metrics WHERE id = %s", (metric,))["activity_id"] == line
      assert _one(conn, "SELECT activity_id FROM news_mentions WHERE id = %s", (news,))["activity_id"] == line
      assert _one(conn, "SELECT awarded_activity_id FROM proposals WHERE id = %s",
                  (proposal,))["awarded_activity_id"] == line


  def test_every_grant_is_copied_before_anything_is_dropped(before):
      conn = before
      n = _one(conn, "SELECT count(*) AS n FROM grants")["n"]
      _migrate(conn)
      assert _one(conn, "SELECT count(*) AS n FROM funder_activity WHERE notes LIKE "
                        "'%%Moved from grants #%% by 0034.'")["n"] == n
      assert _one(conn, "SELECT count(*) AS n FROM information_schema.columns WHERE table_name = "
                        "'funder_activity' AND column_name = 'legacy_grant_id'")["n"] == 0


  def test_grant_locations_with_rows_stop_the_migration(before):
      conn = before
      g = _grant(conn, _funder(conn), _org(conn), "Placed grant")
      loc = _one(conn, "SELECT id FROM locations WHERE kind = 'district' LIMIT 1")["id"]
      conn.execute("INSERT INTO grant_locations (grant_id, location_id) VALUES (%s, %s)", (g, loc))
      with pytest.raises(errors.RaiseException, match="grant_locations"):
          with conn.transaction():
              _migrate(conn)


  def test_a_non_inr_amount_stops_the_migration(before):
      conn = before
      _grant(conn, _funder(conn), _org(conn), "Dollar grant", amount=1000, currency="USD")
      with pytest.raises(errors.RaiseException, match="non-INR"):
          with conn.transaction():
              _migrate(conn)


  def test_a_grant_already_on_a_partner_line_stops_the_migration(before):
      conn = before
      f, o = _funder(conn), _org(conn, "Harsha Trust")
      _grant(conn, f, o, "Livelihoods", start_date=date(2023, 6, 1))
      conn.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, project_name, partner_name) "
                   "VALUES (%s, 'partner', 'FY2023-24', 'Livelihoods', 'Harsha Trust')", (f,))
      with pytest.raises(errors.RaiseException, match="already a partner line"):
          with conn.transaction():
              _migrate(conn)


  def test_two_grants_on_one_line_stop_the_migration(before):
      conn = before
      f = _funder(conn)
      a, b = _org(conn, "Twin Trust"), _org(conn, "Twin Trust")     # two orgs, one printed name
      for org in (a, b):
          _grant(conn, f, org, "Same title", start_date=date(2023, 6, 1))
      with pytest.raises(errors.RaiseException, match="two grants become one"):
          with conn.transaction():
              _migrate(conn)
  ```
- [ ] **Step 3: Run them. They fail.** `source /Users/vinod/GitHub/ge-env.sh && bti tests/test_grants_into_activity_migration.py -q`. Every test errors with `FileNotFoundError … 0034_grants_into_funder_activity.sql`. Parity with Python is kept by shared literals: the parametrised labels here, Task 3's `test_fiscal_year_of` for `records.fiscal_year_of`, and Task 8's `test_the_seed_places_a_date_in_the_same_year_as_0034`.
- [ ] **Step 4: Write the migration.** Create `db/migrations/0034_grants_into_funder_activity.sql`:
  ```sql
  -- grants -> funder_activity partner lines. Spec: features-plans/data-model/2026-10-07-cso-model-consolidation.md
  -- §2 (C4, C5). A grant to a CSO is a funder_activity line, kind 'partner', partner_org_id set (#99).
  --
  --   funder_activity  + start_date, end_date, relationship_status
  --   proposals        grant_id -> awarded_activity_id
  --   metrics          grant_id -> activity_id (ON DELETE CASCADE, as before)
  --   news_mentions    grant_id -> activity_id
  --   grants, grant_locations   dropped
  --
  -- One grant is one line. Its fiscal_year is the year of its start date, else its end date, else the day the
  -- source was read, else the day the row was recorded; notes says which when it is not the start date. A
  -- multi-year grant keeps its WHOLE amount on that one line with both dates set: splitting it would invent a
  -- schedule no source gave.
  --
  -- DESTRUCTIVE: drops two tables and three columns. Safe because every grants row is copied and every
  -- reference re-pointed through an id map before anything is dropped, and both are asserted. What has no
  -- mechanical home stops the migration instead: grant_locations rows, non-INR amounts, and a grant whose
  -- line already exists. Lost on purpose: grants.currency (every copied amount is INR), content_hash,
  -- extractor_version and valid_from (funder_activity has none of them; valid_to, when set, goes in notes),
  -- and outcomes as jsonb (kept as text in notes, as the spec maps it).
  --
  -- Access: funder_activity was granted and given its RLS policy by 0031; the new columns are covered by the
  -- table grant. A grant of a hidden funder, which the grants table showed to anyone, now follows its funder.
  --
  -- Numbered after (d)'s 0033. Renumber at merge if another branch takes 0034.
  -- Before running against Supabase: the counts in the plan's Task 10, and a backup.

  -- 0. Refuse what this file cannot carry across.
  DO $$
  DECLARE n bigint;
  BEGIN
    SELECT count(*) INTO n FROM grant_locations;
    IF n > 0 THEN
      RAISE EXCEPTION 'grant_locations holds % rows and has no home after 0034; record them as footprint '
                      'lines by hand, then empty it', n;
    END IF;
    SELECT count(*) INTO n FROM grants WHERE amount IS NOT NULL AND currency <> 'INR';
    IF n > 0 THEN
      RAISE EXCEPTION 'grants holds % non-INR amounts; funder_activity.amount is INR. Convert them by hand '
                      'before 0034', n;
    END IF;
  END $$;

  -- 1. The columns a grant needs that a partner line lacked.
  ALTER TABLE funder_activity
    ADD COLUMN start_date date,
    ADD COLUMN end_date date,
    ADD COLUMN relationship_status text CHECK (relationship_status IN
      ('active', 'concluded', 'unconfirmed', 'dormant')),
    ADD COLUMN legacy_grant_id bigint;                   -- the id map; dropped in step 5

  -- 2. Each grant as the line it becomes.
  CREATE TEMP TABLE grant_lines ON COMMIT DROP AS
  SELECT g.id AS grant_id, g.funder_id, g.org_id, g.program_id, g.title, g.amount, g.start_date, g.end_date,
    g.status, o.name AS org_name,
    'FY' || to_char(fy.y, 'FM0000') || '-' || to_char((fy.y + 1) % 100, 'FM00') AS fiscal_year,
    concat_ws(E'\n',
      g.notes,
      CASE WHEN g.outcomes <> '{}'::jsonb THEN 'Outcomes: ' ||
        (SELECT string_agg(key || ' ' || value, '; ' ORDER BY key) FROM jsonb_each_text(g.outcomes)) END,
      CASE basis.label
        WHEN 'end_date' THEN 'fiscal_year is the year of the end date; the start date was not stated.'
        WHEN 'fetched_at' THEN 'fiscal_year is the year the source was read; the start date was not stated.'
        WHEN 'valid_from' THEN 'fiscal_year is the year the row was recorded; the start date was not stated.'
      END,
      CASE WHEN g.valid_to IS NOT NULL THEN 'Superseded on ' || to_char(g.valid_to, 'YYYY-MM-DD') || '.' END,
      'Moved from grants #' || g.id || ' by 0034.') AS notes,
    g.source_url, g.source_name, g.fetched_at, g.as_of, g.document_id, g.archive_url
  FROM grants g
  JOIN orgs o ON o.id = g.org_id
  CROSS JOIN LATERAL (SELECT
      CASE WHEN g.start_date IS NOT NULL THEN 'start_date' WHEN g.end_date IS NOT NULL THEN 'end_date'
           WHEN g.fetched_at IS NOT NULL THEN 'fetched_at' ELSE 'valid_from' END AS label,
      COALESCE(g.start_date, g.end_date, g.fetched_at::date, g.valid_from::date) AS d) basis
  CROSS JOIN LATERAL (SELECT CASE WHEN extract(month FROM basis.d) >= 4 THEN extract(year FROM basis.d)::int
                                  ELSE extract(year FROM basis.d)::int - 1 END AS y) fy;

  -- 3. A line the key cannot hold twice stops the migration with names, rather than as a bare UniqueViolation.
  DO $$
  DECLARE clash text;
  BEGIN
    SELECT string_agg(format('funder %s, %s, %L to %L', funder_id, fiscal_year, title, org_name), '; ')
      INTO clash
    FROM (SELECT funder_id, fiscal_year, program_id, title, org_name FROM grant_lines
          GROUP BY 1, 2, 3, 4, 5 HAVING count(*) > 1) d;
    IF clash IS NOT NULL THEN
      RAISE EXCEPTION 'two grants become one funder_activity line: %. Merge or retitle them before 0034', clash;
    END IF;
    SELECT string_agg(format('grants #%s and funder_activity #%s', l.grant_id, a.id), '; ') INTO clash
    FROM grant_lines l JOIN funder_activity a
      ON a.funder_id = l.funder_id AND a.kind = 'partner' AND a.fiscal_year = l.fiscal_year
     AND a.program_id IS NOT DISTINCT FROM l.program_id AND a.csr_sector_id IS NULL
     AND a.state_location_id IS NULL AND a.location_id IS NULL AND a.designation IS NULL
     AND a.project_name = l.title AND a.partner_name = l.org_name;
    IF clash IS NOT NULL THEN
      RAISE EXCEPTION 'a grant is already a partner line: %. Reconcile them by hand before 0034', clash;
    END IF;
  END $$;

  INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, project_name, partner_name,
    partner_canonical, partner_org_id, amount, start_date, end_date, relationship_status, notes, is_public,
    source_url, source_name, fetched_at, as_of, document_id, archive_url, legacy_grant_id)
  SELECT funder_id, 'partner', fiscal_year, program_id, title, org_name, org_name, org_id, amount, start_date,
    end_date, status, notes, true, source_url, source_name, fetched_at, as_of, document_id, archive_url, grant_id
  FROM grant_lines;

  -- 4. Re-point through the map, and prove nothing was left behind before anything is dropped.
  ALTER TABLE proposals ADD COLUMN awarded_activity_id bigint REFERENCES funder_activity(id);   -- set when awarded
  ALTER TABLE metrics ADD COLUMN activity_id bigint REFERENCES funder_activity(id) ON DELETE CASCADE;
  ALTER TABLE news_mentions ADD COLUMN activity_id bigint REFERENCES funder_activity(id);
  UPDATE proposals p SET awarded_activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = p.grant_id;
  UPDATE metrics m SET activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = m.grant_id;
  UPDATE news_mentions n SET activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = n.grant_id;

  DO $$
  DECLARE copied bigint; total bigint; lost bigint;
  BEGIN
    SELECT count(*) INTO copied FROM funder_activity WHERE legacy_grant_id IS NOT NULL;
    SELECT count(*) INTO total FROM grants;
    IF copied <> total THEN
      RAISE EXCEPTION '0034 copied % of % grants; nothing dropped', copied, total;
    END IF;
    SELECT (SELECT count(*) FROM proposals WHERE grant_id IS NOT NULL AND awarded_activity_id IS NULL)
         + (SELECT count(*) FROM metrics WHERE grant_id IS NOT NULL AND activity_id IS NULL)
         + (SELECT count(*) FROM news_mentions WHERE grant_id IS NOT NULL AND activity_id IS NULL)
      INTO lost;
    IF lost > 0 THEN
      RAISE EXCEPTION '0034 left % references unmapped; nothing dropped', lost;
    END IF;
  END $$;

  CREATE INDEX metrics_activity_idx ON metrics (activity_id) WHERE activity_id IS NOT NULL;

  -- 5. Drop. Columns first, so no FK still points at grants; tables, never DELETE (metrics.grant_id cascades).
  ALTER TABLE proposals DROP COLUMN grant_id;
  ALTER TABLE metrics DROP COLUMN grant_id;
  ALTER TABLE news_mentions DROP COLUMN grant_id;
  DROP TABLE grant_locations;
  DROP TABLE grants;
  ALTER TABLE funder_activity DROP COLUMN legacy_grant_id;
  ```
- [ ] **Step 5: Run the copy tests. They pass.** `bti tests/test_grants_into_activity_migration.py -q` → `13 passed`.
- [ ] **Step 6: Apply 0034 to the scratch DB and add the post-state tests.** Run `mig`; it reports `0034_grants_into_funder_activity` applied. Append:
  ```python
  def test_the_grant_tables_and_columns_are_gone(after):
      for table in ("grants", "grant_locations"):
          assert _one(after, "SELECT to_regclass(%s) AS t", (f"public.{table}",))["t"] is None
      gone = after.execute("SELECT table_name FROM information_schema.columns WHERE column_name = 'grant_id' "
                           "AND table_schema = 'public'").fetchall()
      assert gone == []


  @pytest.mark.parametrize(("table", "column"), [("proposals", "awarded_activity_id"),
                                                 ("metrics", "activity_id"), ("news_mentions", "activity_id")])
  def test_references_point_at_funder_activity(after, table, column):
      target = _one(after, """
          SELECT c.confrelid::regclass::text AS t FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
          WHERE c.contype = 'f' AND c.conrelid = %s::regclass AND a.attname = %s""", (table, column))["t"]
      assert target == "funder_activity"


  def test_relationship_status_is_the_grant_enum(after):
      f = _funder(after)
      with pytest.raises(errors.CheckViolation):
          with after.transaction():
              after.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, "
                            "relationship_status) VALUES (%s, 'partner', 'FY2023-24', 'X Trust', 'paused')", (f,))


  def test_the_seeded_grants_arrived(after):
      if _one(after, "SELECT count(*) AS n FROM orgs WHERE slug = 'kabil'")["n"] == 0:
          pytest.skip("not a seeded clone")
      rows = after.execute("""
          SELECT a.fiscal_year, a.relationship_status, a.start_date FROM funder_activity a
          JOIN orgs o ON o.id = a.partner_org_id
          WHERE o.slug = 'kabil' AND a.kind = 'partner' AND a.notes LIKE '%%Moved from grants #%%'
          ORDER BY a.start_date NULLS LAST""").fetchall()
      assert len(rows) == 4
      assert rows[0]["fiscal_year"] == "FY2013-14" and rows[1]["fiscal_year"] == "FY2018-19"


  def test_a_hidden_funders_grant_reaches_only_staff(after):
      """The grants table showed every row to anyone; a grant now follows its funder (0031's policy)."""
      conn = after
      hidden, o = _funder(conn, "Hidden Funder", status="hidden"), _org(conn)
      conn.execute("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
                   "relationship_status, start_date) VALUES (%s, 'partner', 'FY2023-24', 'Harsha Trust', %s, "
                   "'active', '2023-06-01')", (hidden, o))
      staff = uuid4()
      conn.execute("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true)",
                   (f"ge-{staff}@rls.test", staff))

      def sees(role, claims):
          with conn.transaction(force_rollback=True):
              conn.execute("SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                           (role, claims))
              return len(conn.execute("SELECT start_date, relationship_status FROM funder_activity "
                                      "WHERE funder_id = %s", (hidden,)).fetchall())

      assert sees("anon", "") == 0
      assert sees("authenticated", json.dumps({"sub": str(staff)})) == 1
  ```
- [ ] **Step 7: Run.** `bti tests/test_grants_into_activity_migration.py -q`. Expected: `13 skipped` (the `before` tests) and `7 passed` (`test_references_point_at_funder_activity` counts as 3). `bt -m "'not integration'" -q` shows 0 failed: no code changed.
- [ ] **Step 8: Commit.**
  ```bash
  git add db/migrations/0034_grants_into_funder_activity.sql backend/tests/test_grants_into_activity_migration.py
  git commit -m "feat(db): 0034 — grants become funder_activity partner lines" -m "funder_activity gains start_date, end_date and relationship_status; every grant is copied through an id map, proposals/metrics/news_mentions are re-pointed and checked, then grants and grant_locations are dropped. Rows with no home stop the migration." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  ```

---

### Task 2: Catalog — partner lines carry grants, and an activity line is citable

`grants` and `grant_locations` stay in the catalog until Task 5. The `grant` concept still targets them until Tasks 3 and 4.

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (`funder_activity` entry from #99 Task 2; `metrics` ~line 499; `news_mentions` ~line 536; `_self_check` ~line 1100; `Column.cites` docstring line 22)
- Modify: `backend/app/agent/instructions.md` (rules 2 and 8)
- Modify: `backend/tests/test_sql_catalog.py`, `backend/tests/test_prompt.py`

**Interfaces:**
- Produces:
  - `CATALOG["funder_activity"]` columns `start_date`, `end_date`, `relationship_status` (values `('active','concluded','unconfirmed','dormant')`);
  - `CITE_COLUMNS[("funder_activity","id")] == "activity"`;
  - `metrics.activity_id` and `news_mentions.activity_id`, both citing `activity`;
  - the cite-kind set `{"org","funder","activity","grant","score"}` (narrowed in Task 5).

- [ ] **Step 1: Failing tests.** Append to `backend/tests/test_sql_catalog.py`:
  ```python
  class TestGrantsArePartnerLines:
      def test_partner_lines_carry_dates_and_status(self):
          cols = cat.COLUMNS["funder_activity"]
          assert cols["relationship_status"].values == ("active", "concluded", "unconfirmed", "dormant")
          assert cols["start_date"].type == cols["end_date"].type == "date"

      def test_an_activity_line_is_citable(self):
          assert cat.CITE_COLUMNS[("funder_activity", "id")] == "activity"
          assert cat.CITE_COLUMNS[("metrics", "activity_id")] == "activity"
          assert cat.CITE_COLUMNS[("news_mentions", "activity_id")] == "activity"
          assert ("metrics", "grant_id") not in cat.CITE_COLUMNS

      def test_a_multi_year_amount_is_flagged_to_the_agent(self):
          text = " ".join(cat.DEFECTS["funder_activity"]).lower()
          assert "whole grant" in text and "never divide" in text

      def test_the_agent_is_told_where_grants_went(self):
          t = cat.CATALOG["funder_activity"]
          assert "grant" in t.description.lower()
          assert any("moved from grants #" in d.lower() for d in t.defects)
  ```
  In `backend/tests/test_prompt.py`, change the expected set in `test_tools_emit_the_markers_we_think_they_do` to `{"org", "funder", "activity", "grant", "score", "graph"}`. Run `bt tests/test_sql_catalog.py tests/test_prompt.py -q`. It fails with a `KeyError` or an assertion error.
- [ ] **Step 2: Catalog.** In the `funder_activity` `Table`:
  - `description`: append ` A grant to an organisation is a 'partner' line with partner_org_id set; there is no grants table.`
  - `Column("id", "bigint")` becomes `Column("id", "bigint", cites="activity")`.
  - `project_name` note becomes `"the project as the source names it: NULL on an aggregate spend line; on a partner line, the grant's title"`.
  - After `Column("is_ongoing", "boolean")` insert:
    ```python
                Column("start_date", "date", note="kind 'partner': when the grant or partnership began, as a source states it"),
                Column("end_date", "date", note="kind 'partner': when it ended or is due to end"),
                Column("relationship_status", "text", note="kind 'partner': whether it is running, as a source says; NULL means no source said", values=('active', 'concluded', 'unconfirmed', 'dormant')),
    ```
  - Replace #99's partner defect (the string beginning `"A 'partner' line is a named relationship."`) with:
    ```python
                "A 'partner' line is a named relationship. Only when its amount is set does it say money changed hands: the amount (INR) is what the source, usually the recipient's own record, says the partner received from this funder - in that fiscal_year, or, when start_date and end_date span more than one fiscal year, over the whole grant. A partner line with no amount is not evidence of a grant.",
                "A multi-year grant is ONE partner line: the whole grant amount sits on the fiscal_year it started, with start_date and end_date set. Never read it as that year's spend and never divide it across years yourself; say it is a multi-year total.",
                "There is no grants table: grants moved here in 0034 as 'partner' lines with partner_org_id set. Their notes end 'Moved from grants #N by 0034.', which is how an old [grant:N] citation is traced.",
    ```
  - In `metrics`: replace `ForeignKey("grant_id", "grants.id")` with `ForeignKey("activity_id", "funder_activity.id")`, and replace `Column("grant_id", "bigint", cites="grant")` with `Column("activity_id", "bigint", cites="activity", note="the funder_activity line (usually a partner line, i.e. a grant) this figure reports on")`. In its defect, replace `grants.outcomes holds a little more as jsonb;` with `outcomes of the grants moved in 0034 sit as text in funder_activity.notes;`.
  - In `news_mentions`: the same FK/column swap (`note="the funder_activity line a story is about"`). Its defect becomes `"org_id, funder_id and activity_id are NULL for all 118 rows. Any JOIN or filter on them returns zero rows. A zero result here means 'not linked in the data', NEVER 'no news exists'."`.
  - `_self_check`: the allowed set becomes `{"org", "funder", "activity", "grant", "score"}`. `Column.cites` docstring: `'org' | 'funder' | 'activity' | 'score'`.
  - In `test_sql_catalog.py::test_citation_kinds_stay_within_the_frontend_union`, the set becomes `{"org", "funder", "activity", "grant", "score"}`, and the docstring names `org|funder|activity|grant|score|graph`.
- [ ] **Step 3: Agent instructions.** In `backend/app/agent/instructions.md`, rule 2's list becomes `[org:12], [funder:3], [activity:2], [grant:2], [score:7], and [graph:ab12cd34]`. Rule 8's list becomes `orgs.id, funders.id, funder_activity.id or fit_scores.id`. `[grant:2]` leaves in Task 5.
- [ ] **Step 4: Run.** `bt tests/test_sql_catalog.py tests/test_prompt.py tests/test_sql_validator.py -q` all pass; the validator still has `grants` until Task 5. Then `bt -m "'not integration'" -q` shows 0 failed.
- [ ] **Step 5: Commit.** `git add -A backend && git commit -m "feat(sql): partner lines carry a grant's dates and status; [activity:N] cites a funder_activity line" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 3: Import, funder side — `grant` folds into `partner`

**Files:**
- Modify: `backend/app/ingest/expectations.py` (delete `_GRANT_NEEDS_A_RECIPIENT` and its comment; `CONCEPTS["grant"]`, `REQUIRED["grant"]`, `EXTRA["grant"]`; `CONCEPTS["partner"]`; `concepts_for` docstring; `REQUIRED` comment about `grants.status`)
- Modify: `backend/app/ingest/research_records.py` (`PartnerFinding`; delete `GrantFinding`, its union member and `FINDING_MODELS` entry; `skipped` field description ~line 581)
- Modify: `backend/app/ingest/records.py` (`fiscal_year_of`; `FunderPartnerRecord`)
- Modify: `backend/app/ingest/writer.py` (`FUNDER_ACTIVITY_UPDATABLE`; `write_partner`)
- Modify: `backend/app/ingest/promote.py` (`FOLDED`, `_legacy_grants`, `_partner_org`, `_row_identity` partner, partner branch, `_promote_funder`)
- Modify: `backend/app/ingest/brief.py` (partner headline; `LEGACY_TITLES`)
- Modify: `backend/app/ingest/tools/catalog_tools.py` (funder dossier: delete `grants` section, widen partner section; `promote_research` docstring and trailer)
- Create: `backend/tests/test_grants_as_partner_lines.py`
- Modify: `backend/tests/test_ingest.py` (lines ~456, ~823-833)
- Modify: `backend/tests/test_funder_activity.py` (#99's partner tests that call `_write_facts`)

**Interfaces:**
- Produces:
  - `records.fiscal_year_of(d: date) -> str`;
  - `PartnerFinding.project_name: str | None`, `.start_date`, `.end_date: date | None`, `.relationship_status: Literal[...] | None`;
  - the same four fields on `FunderPartnerRecord`;
  - `write_partner(conn, rec, funder_id, *, program_id, document_id, partner_org_id: int | None = None)`, keyed on `partner_name` **and** `project_name`;
  - `promote._partner_org(conn, name) -> int | None`;
  - `promote._legacy_grants(findings, report) -> list[dict]`;
  - `"grant" in promote.FOLDED`;
  - `brief.LEGACY_TITLES["grant"]`.
- `"grant"` is no longer a concept, finding model or record.

- [ ] **Step 1: Failing tests.** Create `backend/tests/test_grants_as_partner_lines.py`:
  ```python
  """A grant is a partner line (0034): the grant concept folds into partner, on both sides."""

  from __future__ import annotations

  from datetime import UTC, date, datetime

  import pytest
  from pydantic import ValidationError

  from app.ingest.matcher import Match

  NOW = datetime(2026, 10, 7, tzinfo=UTC)
  ROW = {"slug": "acme", "entity_name": "Acme Ltd", "canonical_name": "Acme Ltd", "researched_at": NOW}
  GRANT_PARTNER = {
      "concept": "partner", "fiscal_year": "FY2018-19", "partner_name": "KABIL",
      "project_name": "Sustainable livelihoods project, Udalguri",
      "amount": {"value": 4, "unit": "crore", "text": "Rs 4 crore"},
      "start_date": "2018-04-01", "end_date": "2022-03-31", "relationship_status": "concluded",
      "evidence": "Acme supported KABIL's four-year livelihoods project in Udalguri with Rs 4 crore.",
      "source_url": "https://a.b/c", "confidence": "high",
  }


  def _inserted(conn):
      i = next(i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO funder_activity"))
      cols = conn.sql[i].split("(")[1].split(")")[0].replace(" ", "").split(",")
      return dict(zip(cols, conn.params[i], strict=True))


  def _resolving(monkeypatch, method, entity_id=None):
      from app.ingest import promote

      async def fake(conn, name, identifiers=None):
          return Match(method=method, entity_id=entity_id)

      monkeypatch.setattr(promote, "resolve_org", fake)


  @pytest.mark.parametrize(("day", "year"), [
      (date(2018, 4, 1), "FY2018-19"), (date(2019, 3, 31), "FY2018-19"),
      (date(1999, 6, 1), "FY1999-00"), (date(2000, 1, 1), "FY1999-00"),
  ])
  def test_fiscal_year_of(day, year):
      from app.ingest.records import fiscal_year_of

      assert fiscal_year_of(day) == year


  class TestTheConcept:
      def test_grant_is_no_longer_a_concept(self):
          from app.ingest.expectations import CONCEPTS, PROMOTABLE
          from app.ingest.research_records import FINDING_MODELS

          assert "grant" not in CONCEPTS and "grant" not in FINDING_MODELS
          assert set(CONCEPTS) == set(PROMOTABLE)

      def test_a_partner_finding_carries_what_a_grant_carried(self):
          from app.ingest.expectations import expected_fields

          fields = {f.name: f for f in expected_fields("partner")}
          assert {"project_name", "start_date", "end_date", "relationship_status", "amount"} <= set(fields)
          assert not any(fields[n].required for n in ("project_name", "start_date", "relationship_status"))
          assert fields["relationship_status"].values == ("active", "concluded", "unconfirmed", "dormant")

      def test_an_end_before_its_start_is_refused(self):
          from app.ingest.research_records import PartnerFinding

          with pytest.raises(ValidationError, match="ends before it starts"):
              PartnerFinding(**{**GRANT_PARTNER, "start_date": "2022-03-31", "end_date": "2018-04-01"})


  class TestTheFunderSide:
      async def test_a_multi_year_grant_is_one_partner_line(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          _resolving(monkeypatch, "exact", 9)
          conn = recording_conn([None, None])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [GRANT_PARTNER], Owner.funder(1), {}, {}, report,
                                     order=("partner",))
          row = _inserted(conn)
          assert (row["kind"], row["fiscal_year"], row["amount"]) == ("partner", "FY2018-19", 40_000_000)
          assert (row["start_date"], row["end_date"]) == (date(2018, 4, 1), date(2022, 3, 31))
          assert (row["relationship_status"], row["partner_org_id"]) == ("concluded", 9)
          assert row["project_name"] == "Sustainable livelihoods project, Udalguri"
          assert report["written"]["funder_activity (partner)"]["added"] == 1

      async def test_a_resemblance_is_not_a_link(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          _resolving(monkeypatch, "trigram")
          conn = recording_conn([None, None])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [GRANT_PARTNER], Owner.funder(1), {}, {}, report,
                                     order=("partner",))
          assert "partner_org_id" not in _inserted(conn)

      async def test_two_grants_to_one_partner_in_a_year_are_two_lines(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          _resolving(monkeypatch, "none")
          conn = recording_conn([None, None, None, None])
          report = {"held": [], "written": {}}
          other = {**GRANT_PARTNER, "project_name": "Water conservation, Udalguri"}
          await promote._write_facts(conn, ROW, [GRANT_PARTNER, other], Owner.funder(1), {}, {}, report,
                                     order=("partner",))
          assert sum(q.startswith("INSERT INTO funder_activity") for q in conn.sql) == 2
          assert report["held"] == []

      def test_the_partner_key_includes_the_project(self):
          from app.ingest.promote import _row_identity
          from app.ingest.research_records import PartnerFinding

          a = PartnerFinding(**GRANT_PARTNER)
          b = PartnerFinding(**{**GRANT_PARTNER, "project_name": "Another project"})
          assert _row_identity("partner", a, None, None, None, None) != _row_identity("partner", b, None, None, None, None)

      def test_dates_and_status_are_updatable_and_is_public_is_not(self):
          from app.ingest.writer import FUNDER_ACTIVITY_UPDATABLE

          assert {"start_date", "end_date", "relationship_status", "partner_org_id"} <= set(FUNDER_ACTIVITY_UPDATABLE)
          assert "is_public" not in FUNDER_ACTIVITY_UPDATABLE


  class TestSavedGrantFindings:
      SAVED = {"concept": "grant", "recipient_name": "KABIL", "title": "Jaldhara water conservation",
               "status": "active", "start_date": "2025-06-01", "currency": "INR",
               "evidence": "SBI Foundation's Jaldhara programme funds KABIL's water conservation work.",
               "source_url": "https://a.b/c", "confidence": "medium"}

      def test_a_saved_grant_becomes_a_partner_finding(self):
          from app.ingest.promote import _legacy_grants
          from app.ingest.research_records import PartnerFinding

          report = {"held": []}
          [out] = _legacy_grants([self.SAVED], report)
          f = PartnerFinding(**out)
          assert (f.fiscal_year, f.partner_name, f.project_name, f.relationship_status) == (
              "FY2025-26", "KABIL", "Jaldhara water conservation", "active")

      def test_a_saved_grant_with_no_date_is_held_not_guessed(self):
          from app.ingest.promote import _legacy_grants

          report = {"held": []}
          undated = {k: v for k, v in self.SAVED.items() if k != "start_date"}
          assert _legacy_grants([undated], report) == []
          assert "no start or end date" in report["held"][0]

      def test_grant_is_folded_not_skipped(self):
          from app.ingest.promote import FOLDED

          assert "grant" in FOLDED

      def test_a_saved_grant_still_renders_in_the_brief(self):
          from app.ingest.brief import LEGACY_TITLES

          assert LEGACY_TITLES["grant"] == "Grants (saved before 0034)"


  async def test_the_funder_dossier_reads_grants_from_partner_lines(recording_conn, recording_pool, monkeypatch):
      from app.ingest.tools import catalog_tools

      conn = recording_conn([[{"id": 1, "name": "Acme Ltd", "slug": "acme"}]])
      monkeypatch.setattr(catalog_tools, "get_pool", lambda: recording_pool(conn))
      await catalog_tools.funder_dossier.ainvoke({"name": "Acme Ltd", "entity_kind": "funder"})
      assert not any("FROM grants" in q for q in conn.sql)
      assert any("relationship_status" in q and "kind = 'partner'" in q for q in conn.sql)
  ```
  In `test_ingest.py`:
  - line ~456: `assert r.by_concept("grant") == []` becomes `assert r.by_concept("partner") != []`;
  - `test_what_is_left_out_is_left_out_for_one_reason` becomes `assert set(CONCEPT_TABLES) - set(PROMOTABLE) == set()`, with its comment rewritten: "Every concept promotes. `grant` was the last exclusion; since 0034 a grant is a partner line, whose org link is nullable.";
  - `test_a_funder_concept_is_never_the_one_left_out` asserts `== set()`.

  In #99's `backend/tests/test_funder_activity.py`, the partner branch now asks the real org matcher, which would consume the canned `recording_conn` rows. Add this fixture and put it in the parameters of every test that runs `_write_facts` or `promote()` over partner findings: at least `test_a_partner_amount_lands_on_the_partner_line` and `test_a_partner_without_an_amount_is_still_written`. `grep -n '"partner"' tests/test_funder_activity.py` finds the rest.
  ```python
  @pytest.fixture
  def no_org_match(monkeypatch):
      """Since 0034 a partner line asks the org matcher whether it names a catalogued org; these tests are
      about the line, not the link."""
      from app.ingest import promote
      from app.ingest.matcher import Match

      async def none(conn, name, identifiers=None):
          return Match(method="none")

      monkeypatch.setattr(promote, "resolve_org", none)
  ```
  On master, `grep -n "_write_facts\|promote(" tests/test_ingest.py` finds no partner-carrying call. Re-check after #99, and give any that has appeared the same fixture.

  Run `bt tests/test_grants_as_partner_lines.py tests/test_ingest.py -q`; it fails.
- [ ] **Step 2: Records.** In `records.py`, near `_fiscal_year`:
  ```python
  def fiscal_year_of(d: date) -> str:
      """The Indian fiscal year (April to March) a date falls in: 2018-04-01 and 2019-03-31 are both 'FY2018-19'.

      0034 and seed.py place a grant in a year by the same rule; test_grants_into_activity_migration holds
      the three together."""
      y = d.year if d.month >= 4 else d.year - 1
      return f"FY{y}-{(y + 1) % 100:02d}"
  ```
  (Add `from datetime import date` if it is missing.) `FunderPartnerRecord` gains:
  ```python
      project_name: str | None = None
      start_date: date | None = None
      end_date: date | None = None
      relationship_status: Literal["active", "concluded", "unconfirmed", "dormant"] | None = None
  ```
  Its docstring becomes `"""A named partner in a year. With an amount, what the partner received from this funder (INR) — a grant; without one, NOT proof that money changed hands. A multi-year grant is one line: the whole amount, with both dates."""`.
- [ ] **Step 3: Finding.** In `research_records.py`, `PartnerFinding` gains, after `partner_csr1`:
  ```python
      project_name: str | None = Field(
          default=None, description="the grant or project as the source titles it; two projects are two lines"
      )
      start_date: date | None = Field(default=None, description="when the grant or partnership began")
      end_date: date | None = Field(
          default=None,
          description="when it ended or is due to. A multi-year grant is ONE finding with both dates and its "
                      "whole amount, in the fiscal_year it started — never split it across years",
      )
      relationship_status: Literal["active", "concluded", "unconfirmed", "dormant"] | None = Field(
          default=None, description="only when a source says whether it is running; null means not stated"
      )

      @model_validator(mode="after")
      def _dates_in_order(self) -> PartnerFinding:
          if self.start_date and self.end_date and self.end_date < self.start_date:
              raise ValueError(f"the partnership ends before it starts ({self.start_date} to {self.end_date})")
          return self
  ```
  (Import `model_validator` if it is not already imported.) Its docstring becomes `"""A named partner, and — with an amount — a grant. Keep the year: repeated appearances mean renewal, and collapsing them destroys that."""`. Delete `GrantFinding`, its member of the `Finding` union and `"grant": GrantFinding` in `FINDING_MODELS`. The `skipped` field description becomes `"concepts saved under a shape no writer reads"`.
- [ ] **Step 4: Expectations.** Delete the `_GRANT_NEEDS_A_RECIPIENT` comment and constant, `CONCEPTS["grant"]`, `REQUIRED["grant"]` and `EXTRA["grant"]`. Change `CONCEPTS["partner"]` to:
  ```python
      # A named partner in a year — and, since 0034, a grant: a grant to an organisation is a partner line
      # with its amount, dates and status, and partner_org_id when the organisation is catalogued.
      "partner": ConceptSpec(
          "funder_activity", "Partners and grants", row_filter=("kind", "partner"),
          columns=("fiscal_year", "program_id", "project_name", "partner_name", "partner_canonical",
                   "partner_csr1", "partner_kind", "outlay", "amount", "start_date", "end_date",
                   "relationship_status", "notes"),
      ),
  ```
  In the `REQUIRED` comment, replace "and neither is grants.status, which has no default but whose 'unconfirmed' value exists precisely so the writer can say "the source did not say"" with "and neither is a partner line's relationship_status, which is NULL when no source said". In `OURS`'s comment, "a grant's and a programme's status" becomes "a partner line's and a programme's status". In `concepts_for`'s docstring, delete the sentence "`grant` is the one that still stays research, for the reason above it."
- [ ] **Step 5: Writer.** Append `"start_date", "end_date", "relationship_status", "partner_org_id"` to `FUNDER_ACTIVITY_UPDATABLE`, then replace `write_partner`:
  ```python
  async def write_partner(
      conn: Any, rec: Any, funder_id: int, *, program_id: int | None, document_id: int | None,
      partner_org_id: int | None = None,
  ) -> tuple[str, dict]:
      """One partner line; a grant is one. Two projects with one partner in one year are two lines, so the
      key carries project_name. partner_org_id is set only from a match the matcher would merge, and a
      proposed NULL never erases a stored link (_diff)."""
      key = _activity_key(funder_id, rec.activity_kind, rec.fiscal_year, program_id=program_id,
                          project_name=rec.project_name, partner_name=rec.partner_name)
      proposed = {
          "partner_canonical": rec.partner_canonical or rec.partner_name,
          "partner_kind": rec.partner_kind, "partner_csr1": rec.partner_csr1, "partner_org_id": partner_org_id,
          "outlay": rec.outlay, "amount": rec.amount, "start_date": rec.start_date, "end_date": rec.end_date,
          "relationship_status": rec.relationship_status, "notes": rec.notes,
          "source_url": rec.source_url, "source_name": rec.source_name,
          "fetched_at": rec.fetched_at, "as_of": rec.as_of,
      }
      return await _write_activity(conn, key, proposed, document_id)
  ```
- [ ] **Step 6: Promote.**
  - Add `"grant"` to `FOLDED`, keeping (b)'s members.
  - Import `fiscal_year_of` from `app.ingest.records`, and `date` from `datetime`.
  - Add below `_legacy_identifiers`:
  ```python
  def _legacy_grants(findings: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
      """`grant` findings saved before 0034, as the partner findings they are now.

      A grant had no fiscal year of its own, so the line takes its start date's, else its end date's. One with
      neither cannot be placed in a year and is reported, not guessed."""
      out: list[dict[str, Any]] = []
      for f in findings:
          if f.get("concept") != "grant":
              continue
          when = f.get("start_date") or f.get("end_date")
          if not when:
              report["held"].append(
                  f"grant {f.get('title')!r} (saved before 0034): no start or end date, so no fiscal year for "
                  f"its partner line. Re-research it as a partner finding with its year."
              )
              continue
          out.append({
              "concept": "partner", "fiscal_year": fiscal_year_of(date.fromisoformat(str(when)[:10])),
              "partner_name": f.get("recipient_name"), "project_name": f.get("title"),
              "relationship_status": f.get("status"), "amount": f.get("amount"),
              "start_date": f.get("start_date"), "end_date": f.get("end_date"),
              "program_name": f.get("program_name"), "notes": f.get("notes"),
              **{k: f[k] for k in ("evidence", "source_url", "source_name", "confidence", "basis") if k in f},
          })
      return out


  async def _partner_org(conn: Any, name: str) -> int | None:
      """The catalogued organisation a partner line names, when the matcher would merge it. A trigram
      resemblance is not a link: the line keeps partner_name and a person links it."""
      match = await resolve_org(conn, name)
      return match.entity_id if match.method in MERGEABLE else None
  ```
  - `_row_identity`'s partner branch becomes `return _activity_identity("partner", year, program_id, None, None, None, None, f.project_name, f.partner_name)`.
  - The partner branch of `_write_facts` becomes:
  ```python
                  elif concept == "partner":
                      rec = FunderPartnerRecord(
                          fiscal_year=f.fiscal_year, partner_name=f.partner_name,
                          partner_canonical=f.partner_canonical, partner_kind=f.partner_kind,
                          partner_csr1=f.partner_csr1, project_name=f.project_name,
                          start_date=f.start_date, end_date=f.end_date,
                          relationship_status=f.relationship_status,
                          outlay=f.outlay.inr if f.outlay else None,
                          amount=f.amount.inr if f.amount else None,
                          notes=f.notes, as_of=f.fiscal_year, **base,
                      )
                      status, _ = await write_partner(
                          conn, rec, funder_id, program_id=program_id, document_id=document_id,
                          partner_org_id=await _partner_org(conn, f.partner_name),
                      )
                      _count(report, "funder_activity (partner)", status)
  ```
  - In `_promote_funder`, immediately before `programs = await _write_programs(...)`, add `findings = [*findings, *_legacy_grants(findings, report)]`.
- [ ] **Step 7: Brief and dossier.**
  - In `brief.py`, add `"grant": "Grants (saved before 0034)"` to `LEGACY_TITLES`. Keep the `grant` branch of `headline`.
  - The partner branch becomes `return _join(f.get("partner_name"), f.get("project_name"), _money(f.get("amount")), f.get("relationship_status"), f.get("partner_kind"), f.get("program_name"))`.
  - In `catalog_tools.py`, delete the funder dossier's `"grants"` section. Its partner section becomes:
  ```python
      (
          "funder_activity kind='partner' (named partners and grants; amount INR, a multi-year grant's whole amount on its start year)",
          """
          SELECT fiscal_year, partner_name, project_name, partner_kind, amount, start_date, end_date,
                 relationship_status, partner_org_id
          FROM funder_activity WHERE funder_id = %s AND kind = 'partner' ORDER BY fiscal_year, id
          """,
      ),
  ```
  - In `promote_research`'s docstring, replace "`grant` is the one concept that still stays research, and anything" with "A grant is a partner line, linked to the organisation when the matcher would merge it, and anything".
  - Replace the trailer string with `"\nA grant is a partner line on the funder: linked to the organisation only when the name matches one we hold, never on a resemblance. Anything held back is named above: it is a decision waiting for a person, not a silent loss."`.
- [ ] **Step 8: Run.** `bt tests/test_grants_as_partner_lines.py tests/test_ingest.py tests/test_funder_activity.py -q` passes. #99's partner tests pass with `no_org_match`. `test_a_re_promote_updates_a_partner_amount` passes because `write_partner`'s new keyword has a default. Full unit tier: 0 failed. `ruff check .` is clean.
- [ ] **Step 9: Commit.** `git add -A backend && git commit -m "feat(ingest): a grant is a partner finding; saved grant findings fold into partner lines" -m "partner gains project_name, dates and relationship_status; a line links partner_org_id only on a merging match." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 4: Import, org side — an NGO's funders become the funder's partner lines

**Files:**
- Modify: `backend/app/ingest/expectations.py` (`CONCEPTS["partner"].kinds`, `EXTRA["partner"]`)
- Modify: `backend/app/ingest/research_records.py` (`PartnerFinding.funder_name`)
- Modify: `backend/app/ingest/promote.py` (`ORG_WRITE_ORDER`, partner branch, `_row_identity`)
- Modify: `backend/app/ingest/tools/catalog_tools.py` (`_held_per_concept` fk; org dossier `"grants received"`)
- Modify: `backend/tests/test_grants_as_partner_lines.py`, `backend/tests/test_ingest.py` (`test_the_funder_loop_never_tries_an_org_concept`)

**Interfaces:**
- Produces:
  - `CONCEPTS["partner"].kinds == frozenset({"funder", "org"})`;
  - `PartnerFinding.funder_name: str | None` (org research only);
  - `"partner" in ORG_WRITE_ORDER`.
- On an org run, a partner line is written with:
  - `funder_id`: the resolved funder, only when the match is in `MERGEABLE`;
  - `partner_org_id`: the org;
  - `partner_name` and `partner_canonical`: the org's catalogued `orgs.name`, so it meets the line 0034/seed made for the same grant;
  - `program_id`: NULL, because the org's programmes are not the funder's.
- An unresolved funder is held. An NGO's paperwork never creates a funder.

- [ ] **Step 1: Failing tests.** Append to `test_grants_as_partner_lines.py`:
  ```python
  class TestTheOrgSide:
      FROM_ORG = {**GRANT_PARTNER, "funder_name": "Axis Bank Foundation", "partner_name": "Karbi Anglong Bhumi"}

      def test_an_ngo_is_offered_partner_findings_with_a_funder(self):
          from app.ingest.expectations import concepts_for, expected_fields

          assert "partner" in concepts_for("org")
          funder = next(f for f in expected_fields("partner") if f.name == "funder_name")
          assert not funder.required and "org research" in funder.note

      async def test_an_ngos_funder_line_lands_on_the_funder(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def funder(conn, name, *args, **kwargs):
              return Match(method="exact", entity_id=1)

          monkeypatch.setattr(promote, "resolve_funder", funder)
          conn = recording_conn([{"name": "KABIL"}, None, None])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [self.FROM_ORG], Owner.org(9), {"x": 3}, {}, report,
                                     order=("partner",))
          row = _inserted(conn)
          assert (row["funder_id"], row["partner_org_id"], row["partner_name"]) == (1, 9, "KABIL")
          assert "program_id" not in row
          assert "Karbi Anglong Bhumi" in row["notes"]      # the spelling the source printed

      async def test_an_unknown_funder_is_held_never_created(self, recording_conn, monkeypatch):
          from app.ingest import promote
          from app.ingest.writer import Owner

          async def funder(conn, name, *args, **kwargs):
              return Match(method="trigram", candidates=[{"name": "Axis Bank"}])

          monkeypatch.setattr(promote, "resolve_funder", funder)
          conn = recording_conn([])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [self.FROM_ORG], Owner.org(9), {}, {}, report, order=("partner",))
          assert not any(q.startswith("INSERT") for q in conn.sql)
          assert "not a funder Sangam holds" in report["held"][0]

      async def test_an_ngo_partner_finding_without_a_funder_is_held(self, recording_conn):
          from app.ingest import promote
          from app.ingest.writer import Owner

          conn = recording_conn([])
          report = {"held": [], "written": {}}
          await promote._write_facts(conn, ROW, [GRANT_PARTNER], Owner.org(9), {}, {}, report, order=("partner",))
          assert "needs funder_name" in report["held"][0]

      async def test_research_goals_count_an_orgs_lines_by_partner_org(self, recording_conn):
          from app.ingest.tools.catalog_tools import _held_per_concept

          conn = recording_conn([{"n": 0, "years": []}] * 20)
          await _held_per_concept(conn, 9, "org")
          partner = next(q for q in conn.sql if "FROM funder_activity" in q)
          assert "partner_org_id = %s" in partner and "kind = %s" in partner

      async def test_the_org_dossier_reads_grants_received_from_partner_lines(
          self, recording_conn, recording_pool, monkeypatch
      ):
          from app.ingest.tools import catalog_tools

          conn = recording_conn([[{"id": 9, "name": "KABIL", "slug": "kabil"}]])
          monkeypatch.setattr(catalog_tools, "get_pool", lambda: recording_pool(conn))
          await catalog_tools.funder_dossier.ainvoke({"name": "KABIL", "entity_kind": "org"})
          assert not any("FROM grants" in q for q in conn.sql)
          assert any("partner_org_id = %s" in q for q in conn.sql)
  ```
  In `test_ingest.py::test_the_funder_loop_never_tries_an_org_concept`, change the expected set to `{"metric", "contact", "partner"}` and the comment to "metric and contact sit on tables with both foreign keys, and partner writes the funder's line from either side; nothing else may overlap." Run the tests: they fail.
- [ ] **Step 2: Concept and finding.**
  - `CONCEPTS["partner"]` gains `kinds=_BOTH`. Prefix its comment with: "Offered to both kinds: a funder names its partners, and an NGO's own accounts, returns and grantee pages name its funders (`funder_name`), which lands on the same funder line from the other side."
  - Add `EXTRA["partner"]`:
  ```python
      "partner": (
          Expected(
              name="funder_name",
              type="text",
              note="org research only: the funder that gave to this organisation, as printed. Its line is "
                   "written on that funder when Sangam already holds it; otherwise it is held for a person",
              values=(),
              required=False,
          ),
      ),
  ```
  - `PartnerFinding` gains `funder_name: str | None = Field(default=None, description="org research only: who gave the money, as printed")`.
- [ ] **Step 3: Promote.**
  - `ORG_WRITE_ORDER = ("org_financials", "org_location", "metric", "contact", "partner")`.
  - In `_row_identity`'s partner branch, append the funder: `return (*_activity_identity("partner", year, program_id, None, None, None, None, f.project_name, f.partner_name), f.funder_name)`.
  - In `_write_facts`, add `org_names: dict[int, str] = {}` beside `themes`, and replace the partner branch with:
  ```python
                  elif concept == "partner":
                      if owner.column == "org_id":
                          # An NGO's record names who funded it. The line is the funder's, so the funder must
                          # already be one we hold: an NGO's paperwork never creates a funder.
                          if not f.funder_name:
                              report["held"].append(
                                  f"partner {_describe(concept, f)}: an NGO's funder line needs funder_name "
                                  f"— whose money it was"
                              )
                              continue
                          match = await resolve_funder(conn, f.funder_name)
                          if match.method not in MERGEABLE:
                              like = ", ".join(c["name"] for c in match.candidates)
                              report["held"].append(
                                  f"partner {f.funder_name!r}: not a funder Sangam holds"
                                  + (f" (resembles {like})" if like else "")
                                  + ". A person adds or links the funder first."
                              )
                              continue
                          if owner.id not in org_names:
                              found = await (
                                  await conn.execute("SELECT name FROM orgs WHERE id = %s", (owner.id,))
                              ).fetchone()
                              org_names[owner.id] = found["name"]
                          catalogued = org_names[owner.id]
                          printed = None if f.partner_name == catalogued else f"Named in the source as {f.partner_name!r}."
                          line_funder, partner_org_id, line_program = match.entity_id, owner.id, None
                          rec_names = {"funder_name": f.funder_name, "partner_name": catalogued,
                                       "partner_canonical": catalogued,
                                       "notes": "\n".join(p for p in (f.notes, printed) if p) or None}
                      else:
                          line_funder, line_program = funder_id, program_id
                          partner_org_id = await _partner_org(conn, f.partner_name)
                          rec_names = {"funder_name": name, "partner_name": f.partner_name,
                                       "partner_canonical": f.partner_canonical, "notes": f.notes}
                      rec = FunderPartnerRecord(
                          fiscal_year=f.fiscal_year, partner_kind=f.partner_kind, partner_csr1=f.partner_csr1,
                          project_name=f.project_name, start_date=f.start_date, end_date=f.end_date,
                          relationship_status=f.relationship_status,
                          outlay=f.outlay.inr if f.outlay else None,
                          amount=f.amount.inr if f.amount else None,
                          as_of=f.fiscal_year, **rec_names, **prov,
                      )
                      status, _ = await write_partner(
                          conn, rec, line_funder, program_id=line_program, document_id=document_id,
                          partner_org_id=partner_org_id,
                      )
                      _count(report, "funder_activity (partner)", status)
  ```
  `resolve_funder` is already imported in `promote.py`. `prov` is the provenance dict computed above `base` in the loop.
- [ ] **Step 4: Research goals and dossier.** In `_held_per_concept`, after `table = spec.table`, add:
  ```python
          # funder_activity hangs off the funder; an NGO's lines are the ones naming it as the partner.
          col = "partner_org_id" if (entity_kind == "org" and table == "funder_activity") else fk
  ```
  and use `col` in place of `fk` in the `where` it builds. Replace the org dossier's `"grants received"` section:
  ```python
      (
          "funder_activity kind='partner' naming this organisation (grants received; amount INR)",
          """
          SELECT a.fiscal_year, f.name AS funder, a.project_name, a.amount, a.relationship_status,
                 a.start_date, a.end_date
          FROM funder_activity a JOIN funders f ON f.id = a.funder_id
          WHERE a.partner_org_id = %s AND a.kind = 'partner' ORDER BY a.fiscal_year, a.id
          """,
      ),
  ```
- [ ] **Step 5: Run.** `bt tests/test_grants_as_partner_lines.py tests/test_ingest.py tests/test_funder_activity.py -q` passes. Check that `test_every_promotable_concept_is_written_by_one_kind_or_the_other` still holds. Full unit tier: 0 failed. `ruff check .` is clean.
- [ ] **Step 6: Commit.** `git add -A backend && git commit -m "feat(ingest): an NGO's funders become the funder's partner lines" -m "Org research names funder_name; the line is written on a funder we already hold, partner_org_id set, and held otherwise." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 5: Catalog drops `grants`; `[grant:N]` stops being emitted

**Files:**
- Modify: `backend/app/agent/tools/sql/catalog.py` (delete the `grant_locations` and `grants` `Table`s; `_self_check` set; `funder_locations.role` note)
- Modify: `backend/app/agent/tools/sql_tools.py` (docstring line 54)
- Modify: `backend/app/agent/instructions.md` (rule 2)
- Modify: `backend/tests/test_sql_catalog.py` (lines 66-69, 78-80, 105-120), `test_sql_validator.py` (5 sites), `test_sql_errors.py` (line 104), `test_prompt.py`
- Modify: `backend/tests/evals/harness.py` (line 19), `backend/tests/evals/cases/golden.jsonl` (`grants-per-funder`)

**Interfaces:**
- Produces:
  - cite kinds `{"org", "funder", "activity", "score"}`;
  - `"grants" not in CATALOG`, `"grant_locations" not in CATALOG`;

- [ ] **Step 1: Failing tests.** Append to `TestGrantsArePartnerLines` in `test_sql_catalog.py`:
  ```python
      def test_the_grant_tables_are_gone(self):
          assert "grants" not in cat.CATALOG and "grant_locations" not in cat.CATALOG
          assert "grant" not in set(cat.CITE_COLUMNS.values())

      def test_no_note_sends_the_agent_to_a_dropped_table(self):
          import re

          for t in cat.CATALOG.values():
              blob = " ".join([t.description, *t.defects, *(c.note for c in t.columns)])
              assert "grant_locations" not in blob, t.name
              assert not re.search(r"\bgrants\.\w", blob), t.name
  ```
  Edit the existing tests:
  - `test_primary_keys_carry_their_citation_kind`'s list becomes `[("orgs", "org"), ("funders", "funder"), ("funder_activity", "activity"), ("fit_scores", "score")]`.
  - `test_citation_kinds_stay_within_the_frontend_union` becomes `<= {"org", "funder", "activity", "score"}`, with docstring `"""frontend/features/ask/lib/citations.ts hardcodes org|funder|activity|grant|score|graph; grant is only kept there so saved answers still render."""`.
  - In `test_self_check_rejects_a_dangling_foreign_key`, replace `"grants"` with `"funder_activity"` (three places) and the FK with `cat.ForeignKey("partner_org_id", "nonexistent_table.id")`.

  In `test_prompt.py`, the expected set becomes `{"org", "funder", "activity", "score", "graph"}`.
  Validator and errors tests:
  - `validate("SELECT count(*) FROM grants")` (×2) becomes `validate("SELECT count(*) FROM funder_activity")`.
  - The duplicate-names SQL becomes `"SELECT o.id, f.id FROM orgs o JOIN funder_activity a ON a.partner_org_id = o.id JOIN funders f ON f.id = a.funder_id"`.
  - The corpus query becomes:
    ```python
            """SELECT a.id, o.name AS org_name, a.project_name, a.relationship_status, a.start_date
               FROM funder_activity a JOIN orgs o ON o.id = a.partner_org_id
               WHERE a.funder_id = 1 AND a.kind = 'partner' ORDER BY a.start_date DESC NULLS LAST""",
    ```
  - The useful query becomes `("SELECT f.name, count(a.id) AS n FROM funders f LEFT JOIN funder_activity a ON a.funder_id = f.id AND a.kind = 'partner' GROUP BY f.name ORDER BY n DESC")`.
  - `test_sql_errors.py` line 104: `tables=["orgs", "funder_activity", "funders", "fit_scores"]`.

  Run: the new catalog tests fail.
- [ ] **Step 2: Catalog.**
  - Delete the `grant_locations` and `grants` `Table` entries.
  - `_self_check`'s set becomes `{"org", "funder", "activity", "score"}`.
  - Ensure the `funder_locations.role` note reads `"'priority' is a STATED focus, not evidence of funding - see funder_activity (kind 'footprint' and 'partner') for where a funder actually gave"`. #99 may already have rewritten it, but it must not name `grant_locations`.
  - In `sql_tools.py`, the docstring example becomes `"funder_activity,funders"`.
- [ ] **Step 3: Prompt and evals.**
  - `instructions.md` rule 2's list becomes `[org:12], [funder:3], [activity:2], [score:7], and [graph:ab12cd34]`. Follow it with: ` An [activity:N] is one line of a funder's activity: a spend line, a place, a named partner — a grant to an organisation is a partner line — or the funder's own programme figure.`
  - `tests/evals/harness.py`: `CITATION = re.compile(r"\[(org|funder|activity|grant|score|graph):([a-zA-Z0-9]+)\]")`. Old transcripts may still carry `grant`.
  - In `golden.jsonl`, the `grants-per-funder` `gold_sql` becomes `"SELECT f.name, count(a.id) AS n FROM funders f LEFT JOIN funder_activity a ON a.funder_id = f.id AND a.kind = 'partner' AND a.partner_org_id IS NOT NULL GROUP BY f.name"`. **Do not run evals.**
- [ ] **Step 4: Run.** `bt tests/test_sql_catalog.py tests/test_sql_validator.py tests/test_sql_errors.py tests/test_prompt.py -q`. All pass. The frontend learns `[activity:N]` in Task 7, which adds the contract test that holds the two together. `bti tests/test_sql_integration.py -q` against `sangam_ge` now shows the drift test green. `ruff check .`.
- [ ] **Step 5: Commit.** `git add -A backend && git commit -m "feat(sql): the catalog drops grants and grant_locations; [activity:N] replaces [grant:N]" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 6: `/api/grants` is a compatibility read over partner lines

**Files:**
- Modify: `backend/app/repositories/grants.py`, `backend/app/repositories/news.py` (`stats`), `backend/app/api/router.py` (tag text line 27)
- Create: `backend/tests/test_grants.py`

**Interfaces:**
- Consumes: `GrantOut` (unchanged, `schemas/grants.py`); `CallerPool` semantics (role and claims set per transaction).
- Produces:
  - `repo.list_grants(pool, *, limit, offset, status=None, funder=None, org=None)` and `repo.get_grant(pool, grant_id)`, with unchanged signatures, over `funder_activity` rows where `kind = 'partner'` and `partner_org_id` names a visible org.
  - `id` is the activity id.
  - `title = COALESCE(project_name, partner_name)`, `status = COALESCE(relationship_status, 'unconfirmed')`, `currency = 'INR'`, `outcomes = {}`.
  - `stats()["grants"]` counts the same rows.

- [ ] **Step 1: Failing tests.** Create `backend/tests/test_grants.py`:
  ```python
  """/api/grants after 0034: the same JSON over funder_activity partner lines."""

  from __future__ import annotations

  import json
  from contextlib import asynccontextmanager
  from uuid import uuid4

  import pytest

  from app.api.routes import grants as grants_api
  from app.repositories import grants as repo
  from app.schemas.grants import GrantOut

  ROW = {
      "id": 41, "funder_id": 1, "funder_name": "Axis Bank Foundation", "org_id": 9, "org_name": "KABIL",
      "program_id": None, "program_name": None, "title": "Sustainable livelihoods project", "amount": None,
      "currency": "INR", "start_date": None, "end_date": None, "status": "unconfirmed", "outcomes": {},
      "notes": None, "source_name": "hand-vetting", "source_url": "https://a.b/c", "fetched_at": None, "total": 1,
  }


  def test_the_grant_shape_is_frozen():
      """ProfileTabs, the Ask index and smoke.sh read these names; 0034 must not move one."""
      assert list(GrantOut.model_fields) == [
          "id", "funder_id", "funder_name", "org_id", "org_name", "program_id", "program_name", "title",
          "amount", "currency", "start_date", "end_date", "status", "outcomes", "notes", "source_name",
          "source_url", "fetched_at"]


  async def test_the_route_serves_the_same_page(client_for, monkeypatch):
      async def fake(pool, **kwargs):
          return [ROW], 1

      monkeypatch.setattr("app.api.routes.grants.repo.list_grants", fake)
      async with client_for(grants_api.router) as client:
          body = (await client.get("/api/grants?org=kabil")).json()
      assert body["total"] == 1 and set(body["items"][0]) == set(GrantOut.model_fields)


  async def test_the_read_is_partner_lines_naming_an_org(recording_conn, recording_pool):
      conn = recording_conn([[ROW]])
      await repo.list_grants(recording_pool(conn), limit=10, offset=0)
      sql = conn.sql[0]
      assert "FROM funder_activity" in sql and "kind = 'partner'" in sql
      assert "JOIN orgs o ON o.id = a.partner_org_id" in sql and "grants g" not in sql


  # --- integration: the read as the caller, after 0034 ---------------------------------------------------


  class _AsCaller:
      """CallerPool's behaviour over the test's own connection, rolled back each time."""

      def __init__(self, conn, role, claims=""):
          self.conn, self.role, self.claims = conn, role, claims

      @asynccontextmanager
      async def connection(self):
          async with self.conn.transaction(force_rollback=True):
              await self.conn.execute(
                  "SELECT set_config('role', %s, true), set_config('request.jwt.claims', %s, true)",
                  (self.role, self.claims))
              yield self.conn


  async def _setup(db):
      if (await (await db.execute("SELECT to_regclass('public.grants') AS t")).fetchone())["t"] is not None:
          pytest.skip("0034 is not applied here yet")
      tag = uuid4().hex[:8]

      async def one(sql, params):
          return (await (await db.execute(sql, params)).fetchone())["id"]

      f = await one("INSERT INTO funders (slug, name) VALUES (%s, 'Acme Foundation') RETURNING id", (f"ge-f-{tag}",))
      o = await one("INSERT INTO orgs (slug, name) VALUES (%s, 'Harsha Trust') RETURNING id", (f"ge-o-{tag}",))
      h = await one("INSERT INTO orgs (slug, name, registry_status) VALUES (%s, 'Hidden Trust', 'hidden') "
                    "RETURNING id", (f"ge-h-{tag}",))
      line = ("INSERT INTO funder_activity (funder_id, kind, fiscal_year, partner_name, partner_org_id, "
              "project_name, relationship_status, amount, is_public) VALUES (%s, %s, 'FY2024-25', %s, %s, %s, %s, %s, %s)")
      for args in [
          ("partner", "Harsha Trust", o, None, None, None, True),        # Import-shaped: no project, no status
          ("partner", "Harsha Trust", o, "Migrated grant", "active", 750000, True),
          ("partner", "Unlinked Trust", None, None, None, None, True),   # no catalogued org: not a grant
          ("spend", "Harsha Trust", o, "A spend line", None, 100, True),  # not a partner line
          ("partner", "Hidden Trust", h, "Hidden org grant", "active", None, True),
          ("partner", "Harsha Trust", o, "Internal grant", "active", None, False),
      ]:
          await db.execute(line, (f, *args))
      staff = uuid4()
      await db.execute("INSERT INTO users (email, auth_user_id, is_staff) VALUES (%s, %s, true)",
                       (f"ge-{staff}@rls.test", staff))
      return f"ge-f-{tag}", json.dumps({"sub": str(staff)})


  @pytest.mark.integration
  async def test_an_import_shaped_partner_line_reads_as_a_grant(db):
      funder, _ = await _setup(db)
      rows, total = await repo.list_grants(_AsCaller(db, "anon"), limit=50, offset=0, funder=funder)
      items = [GrantOut.model_validate(r) for r in rows]
      bare = next(g for g in items if g.title == "Harsha Trust")
      assert (bare.status, bare.currency, bare.outcomes, bare.amount) == ("unconfirmed", "INR", {}, None)


  @pytest.mark.integration
  async def test_only_partner_lines_naming_a_catalogued_org_are_grants(db):
      funder, _ = await _setup(db)
      rows, total = await repo.list_grants(_AsCaller(db, "anon"), limit=50, offset=0, funder=funder)
      assert {r["title"] for r in rows} == {"Harsha Trust", "Migrated grant"} and total == 2


  @pytest.mark.integration
  async def test_a_hidden_org_or_internal_line_reaches_only_staff(db):
      funder, staff = await _setup(db)
      rows, _ = await repo.list_grants(_AsCaller(db, "authenticated", staff), limit=50, offset=0, funder=funder)
      assert {"Hidden org grant", "Internal grant"} <= {r["title"] for r in rows}


  @pytest.mark.integration
  async def test_a_non_partner_id_is_not_a_grant(db):
      await _setup(db)
      spend = (await (await db.execute(
          "SELECT id FROM funder_activity WHERE kind = 'spend' AND project_name = 'A spend line'")).fetchone())["id"]
      assert await repo.get_grant(_AsCaller(db, "anon"), spend) is None
  ```
  Run `bt tests/test_grants.py -q`. `test_the_read_is_partner_lines_naming_an_org` fails, and the shape and route tests pass, which is what freezes them.
- [ ] **Step 2: Repository.** Replace `backend/app/repositories/grants.py`:
  ```python
  """The grants API after 0034: a read over funder_activity partner lines, in the shape grants had.

  A grant to an organisation is a partner line with partner_org_id set (C4). This is a query, not a SQL VIEW:
  a view runs as its owner and would skip the row-level rules that hide a hidden funder's or org's lines and
  an internal (is_public = false) line, and routes run as the caller. Lines with no catalogued org are not
  grants here: GrantOut.org_id is required, and a name alone is not a recipient.
  """

  from __future__ import annotations

  from typing import Any

  BASE = """
  SELECT a.id, a.funder_id, f.name AS funder_name, a.partner_org_id AS org_id, o.name AS org_name,
         a.program_id, p.name AS program_name,
         COALESCE(a.project_name, a.partner_name) AS title,
         a.amount, 'INR' AS currency, a.start_date, a.end_date,
         COALESCE(a.relationship_status, 'unconfirmed') AS status,
         '{}'::jsonb AS outcomes, a.notes, a.source_name, a.source_url, a.fetched_at,
         COUNT(*) OVER () AS total
  FROM funder_activity a
  JOIN funders f ON f.id = a.funder_id
  JOIN orgs o ON o.id = a.partner_org_id
  LEFT JOIN programs p ON p.id = a.program_id
  WHERE a.kind = 'partner'
  """


  async def list_grants(pool: Any, *, limit: int, offset: int, status: str | None = None,
                        funder: str | None = None, org: str | None = None) -> tuple[list[dict], int]:
      sql = BASE + """
        AND (%(status)s::text IS NULL OR COALESCE(a.relationship_status, 'unconfirmed') = %(status)s)
        AND (%(funder)s::text IS NULL OR f.slug = %(funder)s OR f.id::text = %(funder)s)
        AND (%(org)s::text IS NULL OR o.slug = %(org)s OR o.id::text = %(org)s)
      ORDER BY a.start_date DESC NULLS LAST, a.fiscal_year DESC, a.id
      LIMIT %(limit)s OFFSET %(offset)s
      """
      params = {"limit": limit, "offset": offset, "status": status, "funder": funder, "org": org}
      async with pool.connection() as conn:
          rows = await (await conn.execute(sql, params)).fetchall()
      return rows, (rows[0]["total"] if rows else 0)


  async def get_grant(pool: Any, grant_id: int) -> dict | None:
      async with pool.connection() as conn:
          return await (await conn.execute(BASE + " AND a.id = %s", (grant_id,))).fetchone()
  ```
  In `news.py::stats`, the `grants` line becomes `(SELECT count(*) FROM funder_activity a JOIN orgs o ON o.id = a.partner_org_id WHERE a.kind = 'partner') AS grants,`. In `router.py`, the grants tag description becomes `"Funding relationships: funder_activity partner lines naming a catalogued organisation (the grants table retired in 0034)"`.
- [ ] **Step 3: Run.** `bt tests/test_grants.py -q`: 3 passed, 4 skipped (integration deselected or skipped). `bti tests/test_grants.py -q` against `sangam_ge`: 7 passed. Full unit tier: 0 failed. `ruff check .`.
- [ ] **Step 4: Commit.** `git add -A backend && git commit -m "feat(api): /api/grants reads funder_activity partner lines in the same shape" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 7: Frontend — `[activity:N]` links, and `[grant:N]` retires

**Files:**
- Modify: `frontend/features/ask/lib/citations.ts`, `frontend/features/ask/lib/sources.ts`, `frontend/features/ask/AskWorkspace.tsx`, `frontend/features/ask/preview/AskPreview.tsx`, `frontend/features/ask/preview/sample.ts`, `frontend/app/(agent)/ask/page.tsx`
- Modify: `backend/tests/test_prompt.py` (the frontend contract test)

**Interfaces:**
- Produces:
  - `CitationKind = "org" | "funder" | "activity" | "grant" | "score" | "graph"`;
  - `RegistryIndex.activities: Map<number, { orgSlug: string; title: string } & Provenance>`, replacing `grants`;
  - `IndexPayload.activities`, replacing `grants`.
- Consumes: `/api/grants?limit=100` (shape unchanged; `id` is now an activity id).

- [ ] **Step 0: Failing contract test.** Append to `backend/tests/test_prompt.py`:
  ```python
  def test_the_frontend_links_every_marker_the_tools_emit():
      """citations.ts hardcodes the marker grammar, and a kind it does not list renders as plain text."""
      ts = (Path(__file__).resolve().parents[2] / "frontend" / "features" / "ask" / "lib" / "citations.ts")
      grammar = re.search(r"const CITE_RE = /\\\[\(([a-z|]+)\):", ts.read_text(encoding="utf-8"))
      assert grammar, "citations.ts no longer declares CITE_RE where this test reads it"
      assert emitted_markers() <= set(grammar.group(1).split("|"))
  ```
  `source /Users/vinod/GitHub/ge-env.sh && bt tests/test_prompt.py -q` fails: `activity` is missing from `CITE_RE`.
- [ ] **Step 1: citations.ts.**
  - Change the type and index:
  ```ts
  export type CitationKind = "org" | "funder" | "activity" | "grant" | "score" | "graph";
  …
    activities: Map<number, { orgSlug: string; title: string } & Provenance>;
  };

  const CITE_RE = /\[(org|funder|activity|grant|score|graph):([a-zA-Z0-9]+)\]/g;
  ```
  - Replace the `case "grant"` block:
  ```ts
      case "activity": {
        // Only partner lines naming a catalogued organisation (grants) are in the index; any other line
        // still renders, unlinked, under its number.
        const line = index?.activities.get(numeric);
        return { href: line ? `/registry/${line.orgSlug}` : null, label: line?.title ?? `funder activity #${id}` };
      }
      case "grant":
        // Retired in 0034. An answer saved before then still renders the marker, unlinked, rather than
        // pointing at whichever activity line now carries the old number.
        return { href: null, label: `grant #${id} (retired record)` };
  ```
- [ ] **Step 2: sources.ts.** `: cite.kind === "grant" ? index?.grants.get(id)` becomes `: cite.kind === "activity" ? index?.activities.get(id)`. In the header comment, "the org, funder or grant" becomes "the org, funder or activity line".
- [ ] **Step 3: Payload.**
  - `AskWorkspace.tsx`: `grants: ({ id: number; orgSlug: string; title: string } & Sourced)[];` becomes `activities: (…same…)[];`, and `grants: new Map(payload.grants.map(...))` becomes `activities: new Map(payload.activities.map((g) => [g.id, g]))`.
  - `ask/page.tsx`: rename the destructured `grants` to `grantLines`, and the payload key `grants:` to `activities: grantLines.map((g) => ({ … }))`, with the body unchanged.
  - `AskPreview.tsx`: `grants: new Map()` becomes `activities: new Map()`.
  - `sample.ts`: `grants: []` becomes `activities: []`.
- [ ] **Step 4: Check.** `cd frontend && npm ci --no-audit --no-fund && npx tsc --noEmit && npm run lint && npm run build` passes. `tsc` also proves that `citationTarget`'s switch covers every `CitationKind`. Then `source /Users/vinod/GitHub/ge-env.sh && bt tests/test_prompt.py -q` passes, including `test_the_frontend_links_every_marker_the_tools_emit`.
- [ ] **Step 5: Commit.** `git add -A frontend backend/tests/test_prompt.py && git commit -m "feat(ask): [activity:N] links to the funded organisation; [grant:N] renders as a retired record" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 8: Seed, graph seed, integrity test, smoke

**Files:**
- Modify: `seed/seed.py` (`seed_grants`, `main` summary, module docstring line 2)
- Modify: `seed/graph_seed.py` (lines 94-121)
- Modify: `backend/tests/test_migration_integrity.py` (line 46)
- Modify: `scripts/smoke.sh` (line 64)

**Interfaces:**
- Produces: `seed.fiscal_year_of(d: date) -> str`, the same rule as `records.fiscal_year_of` and 0034. `grants.json` loads as partner lines.

- [ ] **Step 1: Failing test.** Append to `backend/tests/test_grants_as_partner_lines.py`. It is a unit test: it loads `seed/seed.py` by path, which imports only psycopg, and touches no database.
  ```python
  @pytest.mark.parametrize(("day", "year"), [
      (date(2018, 4, 1), "FY2018-19"), (date(2019, 3, 31), "FY2018-19"),
      (date(1999, 6, 1), "FY1999-00"), (date(2000, 1, 1), "FY1999-00"), (date(2026, 9, 10), "FY2026-27"),
  ])
  def test_the_seed_places_a_date_in_the_same_year_as_0034(day, year):
      """The same literals pin 0034 (Task 1) and records.fiscal_year_of (Task 3)."""
      import importlib.util
      from pathlib import Path

      path = Path(__file__).resolve().parents[2] / "seed" / "seed.py"
      spec = importlib.util.spec_from_file_location("seed_module", path)
      seed = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(seed)
      assert seed.fiscal_year_of(day) == year
  ```
  `bt tests/test_grants_as_partner_lines.py -k seed -q` fails with `AttributeError: … has no attribute 'fiscal_year_of'`.
- [ ] **Step 2: seed.py.** Add `from datetime import date` to the imports. Replace `seed_grants`:
  ```python
  def fiscal_year_of(d: date) -> str:
      """The Indian fiscal year (April to March) a date falls in. 0034 and app.ingest.records use this rule."""
      y = d.year if d.month >= 4 else d.year - 1
      return f"FY{y}-{(y + 1) % 100:02d}"


  def _grant_year(grant: dict) -> tuple[str, str | None]:
      """A grant's line year, and the note 0034 writes when it is not the start date's."""
      for key, why in (
          ("start_date", None),
          ("end_date", "fiscal_year is the year of the end date; the start date was not stated."),
          ("fetched_at", "fiscal_year is the year the source was read; the start date was not stated."),
      ):
          if grant.get(key):
              return fiscal_year_of(date.fromisoformat(grant[key][:10])), why
      sys.exit(f"seed error: grant {grant['title']!r} has no date to place it in a fiscal year")


  def seed_grants(cur, program_ids) -> int:
      """grants.json as funder_activity partner lines: the mapping 0034 applied to the grants table (C4)."""
      grants = json.loads((DATA / "grants.json").read_text())
      for grant in grants:
          funder_id = lookup_id(cur, "funders", "slug", grant["funder"])
          org_id = lookup_id(cur, "orgs", "slug", grant["org"])
          cur.execute("SELECT name FROM orgs WHERE id = %s", (org_id,))
          org_name = cur.fetchone()[0]
          program_id = program_ids.get((funder_id, grant["program"])) if grant.get("program") else None
          fiscal_year, why = _grant_year(grant)
          outcomes = "; ".join(f"{k} {v}" for k, v in sorted(grant.get("outcomes", {}).items()))
          notes = "\n".join(p for p in (grant.get("notes"), f"Outcomes: {outcomes}" if outcomes else None, why) if p)
          # notes is written on insert only: a line 0034 moved keeps its "Moved from grants #N" trace.
          cur.execute(
              """
              INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, project_name, partner_name,
                                           partner_canonical, partner_org_id, start_date, end_date,
                                           relationship_status, notes, source_url, source_name, fetched_at)
              VALUES (%s, 'partner', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
              ON CONFLICT (funder_id, kind, fiscal_year, program_id, csr_sector_id, state_location_id,
                           location_id, designation, project_name, partner_name) DO UPDATE SET
                partner_org_id = EXCLUDED.partner_org_id, start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date, relationship_status = EXCLUDED.relationship_status,
                source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at
              """,
              (
                  funder_id, fiscal_year, program_id, grant["title"], org_name, org_name, org_id,
                  grant.get("start_date"), grant.get("end_date"), grant["status"], notes,
                  grant.get("source_url"), grant.get("source_name"), grant.get("fetched_at"),
              ),
          )
      return len(grants)
  ```
  - In `main`'s summary, `{n_grants} grants` becomes `{n_grants} grant lines`.
  - In the module docstring, `grants` becomes `grants (as funder_activity partner lines)`.
- [ ] **Step 3: graph_seed.py.** Replace the grants query and loop:
  ```python
          grants = conn.execute(
              """
              SELECT a.project_name AS title, a.relationship_status AS status, a.start_date, a.end_date, a.notes,
                     f.name AS funder_name, o.name AS org_name, p.name AS program_name
              FROM funder_activity a
              JOIN funders f ON f.id = a.funder_id
              JOIN orgs o ON o.id = a.partner_org_id
              LEFT JOIN programs p ON p.id = a.program_id
              WHERE a.kind = 'partner' AND a.project_name IS NOT NULL
              ORDER BY a.id
              """
          ).fetchall()
          for g in grants:
              dates = (f" from {g['start_date']} to {g['end_date']}" if g["start_date"] else "")
              episodes.append(
                  {
                      "name": f"grant-{g['funder_name']}-{g['org_name']}-{g['title'][:30]}",
                      "body": (
                          f"{g['funder_name']} funded {g['org_name']}: {g['title']}"
                          + (f" under the {g['program_name']} program" if g["program_name"] else "")
                          + f"{dates}. Status: {g['status'] or 'not stated'}."
                          + (f" {g['notes']}" if g["notes"] else "")
                      ),
                      "description": "funding relationship (funder_activity partner line)",
                  }
              )
  ```
  The episode name format is unchanged, so an episode already ingested is recognised by name. Outcomes now arrive through `notes`.
- [ ] **Step 4: Integrity and smoke.**
  - In `test_v2_content_present`, `SELECT count(*) FROM grants` becomes `SELECT count(*) FROM funder_activity a JOIN orgs o ON o.id = a.partner_org_id WHERE a.kind = 'partner' AND o.slug = 'kabil' AND a.source_name = 'hand-vetting'`, which equals 4.
  - In `smoke.sh`, the line becomes `check_json    "grants: 4+ relationships"   "$BACKEND/api/grants" "d['total'] >= 4"`, with a comment above it: `# >= since 0034: a grant is a partner line, and Import adds partner lines that name a catalogued org.`
- [ ] **Step 5: Run.**
  - `bt tests/test_grants_as_partner_lines.py -k seed -q` passes.
  - Re-seed the scratch DB to prove idempotence. Run this twice; the working directory must be the worktree root, so that `seed` is importable:
    ```bash
    docker run --rm --network sangam_default -v /Users/vinod/GitHub/sangam-grants-activity:/w -w /w \
      -e DATABASE_URL="host=postgres user=sangam password=sangam dbname=sangam_ge" \
      --entrypoint python sangam-backend:latest -m seed.seed
    ```
    Then run `psql_ge -tc "select count(*) from funder_activity a join orgs o on o.id = a.partner_org_id where o.slug = 'kabil' and kind = 'partner'"`. It returns `4` both times, the 0034 lines updated in place.
  - `bti tests/test_migration_integrity.py -q` passes against `sangam_ge`.
  - `bash -n scripts/smoke.sh`.
- [ ] **Step 6: Commit.** `git add seed scripts backend/tests/test_migration_integrity.py && git commit -m "feat(seed): grants.json loads as funder_activity partner lines; the graph reads them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 9: Prompts, skills and docs say a grant is a partner line

**Files:**
- Modify: `backend/app/ingest/instructions.md`, `backend/app/ingest/prompts/entity_researcher.md`, `backend/app/ingest/skills/entity-record/SKILL.md`, `backend/app/ingest/skills/ngo-brief-for-funders/SKILL.md`, `backend/app/ingest/skills/funder-intake-research/SKILL.md`
- Modify: `CLAUDE.md`, `README.md`, `docs/DATA_PLATFORM.md`, `docs/INGEST.md`, `docs/SQL_AGENT.md`
- Modify: `backend/tests/test_grants_as_partner_lines.py`

- [ ] **Step 1: Failing test.** Append to `test_grants_as_partner_lines.py`:
  ```python
  def test_no_prompt_or_skill_names_the_grants_table():
      import re
      from pathlib import Path

      app = Path(__file__).resolve().parents[1] / "app"
      texts = [*app.glob("ingest/**/*.md"), app / "agent" / "instructions.md"]
      bad = re.compile(r"`grants`|\bgrants\.\w|grant_locations|`grant` is (a )?funder-side")
      hits = [f"{p.relative_to(app)}: {m.group(0)}" for p in texts for m in bad.finditer(p.read_text("utf-8"))]
      assert not hits, hits
  ```
  Run: it fails, naming `instructions.md`, `entity_researcher.md`, `entity-record`, `ngo-brief-for-funders` and others.
- [ ] **Step 2: Ingest prompts and skills.** Locate each line with `grep -n` on the anchor phrase. #99 Task 15 may have reworded neighbouring lines.
  - `ingest/instructions.md`:
    - In the concept table, delete the `grant` row. The `partner` row becomes `| \`partner\` | named partners and grants per FY — a grant is a partner line with amount, dates and status; a multi-year grant is one line with its whole amount |`.
    - In the research-results list, delete `grants`.
    - The "named grants" summary item stays.
    - Replace the paragraph beginning "**The one exception is `grant`.**" with: "**A grant is a partner line.** Record it as a `partner` finding with `project_name`, `amount`, `start_date`, `end_date` and `relationship_status`. It links to the organisation only when the name matches one we hold. An NGO's own research records its funders the same way, with `funder_name`, and the line is written on that funder when we hold it."
    - In the promotion sentence, drop "twelve of the thirteen" and say "every concept".
  - `prompts/entity_researcher.md`:
    - Replace item `**grants**` with `8. **grants** — a \`partner\` finding: \`partner_name\` the recipient, \`project_name\` the grant's title, \`amount\` with its unit, \`start_date\`, \`end_date\`, \`relationship_status\` (\`active\`, \`concluded\`, \`unconfirmed\`, \`dormant\`). **\`amount = null\` means not public. It never means zero.** A multi-year grant is ONE finding in the fiscal year it started, with both dates and its whole amount — never split it.`
    - Replace the paragraph beginning "**Never record a grant an NGO received as if the NGO gave it.**" with: "**Never record a grant an NGO received as if the NGO gave it.** Each funder an NGO's accounts, FCRA return, annual report or a funder's grantee page names is a `partner` finding: `funder_name` the funder as printed, `partner_name` this NGO as that source prints it, `fiscal_year`, and `amount`, `project_name`, dates and `relationship_status` when stated. It lands on the funder's line. A funder Sangam does not hold yet is held for a person, never created from an NGO's paperwork. Name its funders in your `summary` too."
  - `skills/entity-record/SKILL.md`, item 6: replace "This has no finding behind it: `grant` is funder-side and `grants.org_id` is NOT NULL, so it comes from the researcher's summary or from `funder_dossier` with `entity_kind='org'`." with "These are `partner` lines naming this organisation — `funder_dossier` with `entity_kind='org'` lists them under grants received."
  - `skills/ngo-brief-for-funders/SKILL.md`: replace the paragraph beginning "**Existing funders has no finding behind it.**" with "**Existing funders** are the funder partner lines naming the organisation, from `funder_dossier` with `entity_kind='org'` (grants received). Write \"not recorded\" rather than leaving the cell out."
  - `skills/funder-intake-research/SKILL.md`: in the field-23 row, change "`grants` has no writer" (or its #99 rewording) to "a grant is a `partner` finding with amount, dates and status".
- [ ] **Step 3: Repository docs.**
  - **CLAUDE.md:**
    - The marker list becomes `[org:N]`, `[funder:N]`, `[activity:N]`, `[score:N]`, `[graph:<uuid8>]`.
    - Get the table count from `bpy "from app.agent.tools.sql.catalog import CATALOG; print(len(CATALOG))"`, then update every "N tables" phrase that `grep -rn "[0-9]\+ tables" CLAUDE.md docs/SQL_AGENT.md backend/app/ingest/expectations.py` finds.
    - In the migrations paragraph, add: "`0034` retires `grants` into `funder_activity` partner lines."
  - **README.md:** line 37 `grants` stays as the API name. Line 75 `**grants**` becomes `**funder activity** (spend, partners — grants are partner lines)`. Line 315's marker list matches CLAUDE.md.
  - **docs/DATA_PLATFORM.md:**
    - Line 23: `grants.outcomes` → `funder_activity.notes (outcomes moved in 0034)`.
    - Line 50 row: delete `grants`.
    - Line 110 row: replace it with `| **Places** | ~~\`grant_locations\`~~ | dropped in 0034 (0 rows, no writer); where a funder gave is \`funder_activity\` |`.
    - Field-23 row: `funder_activity kind='partner'`, with amount, dates and status.
    - Replace the "**Grants (23).**" paragraph with: "**Grants (23).** Since 0034 a grant is a `funder_activity` line of kind `partner` with `partner_org_id` set; `start_date`, `end_date` and `relationship_status` came with it, and `/api/grants` reads those lines in the old shape. A multi-year grant is one line with its whole amount on its start year."
    - Add a `0034_grants_into_funder_activity.sql` row to the migrations table.
  - **docs/INGEST.md:**
    - Line 226: `| **grant** | **\`grants\` — no writer** |` becomes `| **partner** (incl. grants) | \`funder_activity\` kind \`partner\`, from either side |`.
    - Replace the paragraph at 250-252 with: "A grant is a partner finding. A funder's research links the line to an organisation only on a merging match; an NGO's research writes the line on a funder we hold, and holds it otherwise."
    - Delete the "**A grant writer.**" future-work bullet at 347.
  - **docs/SQL_AGENT.md:**
    - Line 142: `# "org" | "funder" | "activity" | "score"`.
    - In the table list (158), replace `grants` with `funder_activity`.
    - Line 342: `grants.status` → `funder_activity.relationship_status`.
    - Lines 362-363: `grants.funder_id` → `funder_activity.funder_id`.
- [ ] **Step 4: Run.** `bt tests/test_grants_as_partner_lines.py tests/test_prompt.py tests/test_ingest.py -q` passes. Full unit tier: 0 failed. #99's skill tests and `test_harness.py`'s prompt-names-tools tests stay green.
- [ ] **Step 5: Commit.** `git add -A backend CLAUDE.md README.md docs && git commit -m "docs: a grant is a funder_activity partner line" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 10: Final verification and the Supabase pre-flight

**Files:** none new.

- [ ] **Step 1: Whole suite.**
  ```bash
  source /Users/vinod/GitHub/ge-env.sh
  bt -m "'not integration'" -q                       # 0 failed; passed = baseline + this branch's tests
  bti -m integration -q                              # against sangam_ge at 0034: 0 failed
  cd /Users/vinod/GitHub/sangam-grants-activity/backend && ruff check .
  cd ../frontend && npx tsc --noEmit && npm run lint && npm run build
  ```
  The integration run must include `test_sql_integration.py::TestCatalogMatchesReality::test_no_drift`, which is the boot-time `verify_against_db`. It must also include `test_grants_into_activity_migration.py`, `test_grants.py`, `test_rls.py` and `test_migration_integrity.py`.
- [ ] **Step 2: Nothing names the old tables.** `git grep -n -E "\bgrants\b|grant_locations|grant_id|\[grant:" -- backend seed scripts frontend ':!**/0025_*' ':!**/0027_*' ':!db/init/*'`. Every remaining hit is one of:
  - the `/api/grants` route, repository, schema, router or types;
  - the `stats` key `grants`;
  - English prose ("grants@", "named grants");
  - the retired-marker branch in `citations.ts`;
  - the evals regex;
  - `features/registry` UI text.

  List anything else in the PR, or fix it.
- [ ] **Step 3: Boot check.** This needs no separate command. Step 1's `test_sql_integration.py::TestCatalogMatchesReality::test_no_drift` runs `verify_against_db()` against `sangam_ge` at 0034, the same check the lifespan raises on at boot, and its sibling tests cover `undeclared_tables()`. Both must be in Step 1's green run.
- [ ] **Step 4: Supabase pre-flight.** Do this before the merge runs `make migrate ENV=staging`, and paste the output into the PR:
  ```sql
  SELECT 'grants' AS t, count(*) FROM grants
  UNION ALL SELECT 'grant_locations', count(*) FROM grant_locations
  UNION ALL SELECT 'non-INR amounts', count(*) FROM grants WHERE amount IS NOT NULL AND currency <> 'INR'
  UNION ALL SELECT 'proposals.grant_id', count(*) FROM proposals WHERE grant_id IS NOT NULL
  UNION ALL SELECT 'metrics.grant_id', count(*) FROM metrics WHERE grant_id IS NOT NULL
  UNION ALL SELECT 'news_mentions.grant_id', count(*) FROM news_mentions WHERE grant_id IS NOT NULL
  UNION ALL SELECT 'partner lines (would collide)', count(*) FROM grants g JOIN orgs o ON o.id = g.org_id
    JOIN funder_activity a ON a.funder_id = g.funder_id AND a.kind = 'partner' AND a.project_name = g.title
    AND a.partner_name = o.name;

  -- Nothing may be built on what 0034 drops: a view here makes DROP TABLE / DROP COLUMN fail partway.
  SELECT DISTINCT view_schema, view_name FROM information_schema.view_column_usage
  WHERE table_name IN ('grants', 'grant_locations')
     OR (column_name = 'grant_id' AND table_name IN ('metrics', 'proposals', 'news_mentions'));
  ```
  Run it with `make psql ENV=staging`.
  - `grant_locations`, non-INR amounts and collisions above zero stop the migration by design, and any view listed would break the drops. Resolve them first.
  - Then take a backup (`make db-backup ENV=staging`, or Supabase's dashboard), then run `make migrate ENV=staging`.
  - State in the PR:
    - the citation decision (`[activity:N]`; old `[grant:N]` renders unlinked as a retired record, traceable through `notes`);
    - that a hidden funder's grants are now staff-only;
    - that `smoke.sh` checks `>= 4`.
- [ ] **Step 5: Whole-branch review**, per subagent-driven-development. Then hand off with `superpowers:finishing-a-development-branch`.

---

## Self-review

**Spec coverage.**

| Spec item | Task |
|---|---|
| §2 C4: each `grants` row → one partner line, per the mapping table (kind, funder, partner_org, partner_name = CSO name, program, project_name = title, amount, fiscal_year of start_date, notes, provenance, is_public) | 1 |
| `start_date`, `end_date`, `relationship_status` columns | 1, 2 |
| Re-point `proposals.grant_id` → `awarded_activity_id`, `metrics.grant_id` → `activity_id`, `news_mentions.grant_id` → `activity_id` (02_schema.sql:220's `grant_id` is `news_mentions`'s) | 1 |
| C5: drop `grant_locations` (refusing rows); drop `grants` | 1 |
| Migration step 6: classify under #92 | 1 (no new table; RLS on migrated rows tested) |
| `/api/grants` the same JSON shape; Known funders tab; smoke check | 6, 8 |
| Seed `grants.json` through the same mapping | 8 |
| §3 catalog: new columns, drop tables, `funder_activity`'s grant columns | 2, 5 |
| §3 promote: grant findings write partner rows | 3, 4 |
| Agent citations kept working | 2, 5, 7 |
| Pre-Supabase counts and backup | 10 |

`program_locations` and `credential_events` are dropped by (d), not here.

**Decisions this plan takes, and why:**
- **Citations.** The marker becomes `[activity:N]` on `funder_activity.id`, because `cites` is per column. Old `[grant:N]` stays in the grammar and renders unlinked as "retired". Ids were not preserved: `funder_activity` already holds rows that would collide.
- **Fiscal year without a start date.** It falls back to the end date, then `fetched_at`, then `valid_from`, and notes say which. #99 made `fiscal_year` NOT NULL, and two local grants have no dates.
- **Multi-year amounts.** One line, the whole amount, never split, and the agent is told.
- **Outcomes.** They become text in `notes`, per the spec mapping. The compatibility read returns `{}`. Nothing in the UI reads `outcomes`, and the graph seed reads `notes`.
- **The `grant` concept folds into `partner`.** #99's distinct-row-filter test forbids two concepts on `kind='partner'`.
- **Org links.** `partner_org_id` is resolved here on a merging match. The org-side path (an NGO naming its funders) is built here and not left to (f), because the spec's acceptance run needs partner lines with amounts from the CSO's own documents. (f) only writes the skill that asks for them.
- **ON DELETE.** Mirrored from the old columns: CASCADE on metrics, none on the other two.

**Known limits, left as they are:**
- The same grant read from the funder's side, with a different spelling of the CSO, and from the CSO's side is two lines. The org-side writer uses `orgs.name` precisely so that it meets 0034's and the seed's lines. A funder-side line keeps the printed spelling, as #99 decided.
- Saved threads with `[grant:N]` lose their link. The trace is `notes`' `Moved from grants #N`.
- The partner key now includes `project_name`. A line #99 wrote with `project_name` NULL is not updated in place when a later run names the project: that run writes a sibling line. Re-import is stopped at the agent level today (#99), so this is noted, not built.

**Placeholder scan.** Every code step carries the code. The two references to #99's text that may have been reworded (the field-23 skill row and the `funder_locations` note) give the target wording, not a diff.

**Type and name consistency:**
- `fiscal_year_of` is defined identically in `records.py` and `seed.py`. Tasks 1, 3 and 8 pin the SQL and both functions to the same literal labels.
- `write_partner(..., partner_org_id=None)` is used by Tasks 3 and 4.
- `FOLDED` and `LEGACY_TITLES` extend #99's.
- `RegistryIndex.activities` is used in `citations.ts`, `sources.ts`, `AskWorkspace.tsx`, `AskPreview.tsx`, `sample.ts` and `ask/page.tsx`.
- The cite set is `{org, funder, activity, score}` in `_self_check`, `test_sql_catalog`, `test_prompt` and CLAUDE.md.
