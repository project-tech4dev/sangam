# Staff-only CSR sources and the intake skill — Implementation Plan (v2, no layout profiles)

> **For agentic workers:** execute with superpowers:subagent-driven-development (spec D15): a fresh
> implementer per task, a fresh reviewer per task, a whole-branch review at the end. **No new tests
> (team rule).** Every "verify" step is a throwaway scratch script in the scratchpad, never
> committed; the only test edits allowed are existing tests a change breaks. Steps use `- [ ]`.

**Goal:** three confidential workbooks go into a private `staff-sources` bucket, one private
`documents` row each. The Import researcher reads them itself through one tool, `read_source_rows`,
which returns header rows and matching rows with cell references. Promotion turns cited facts into
public rows (D14). The two research skills say where to look, in which order, and how each staff
sheet is laid out.

**What changed from v1:** the layout-profile parser (v1 Tasks 2–5: `LayoutProfile`, normalisers,
three layout readers, profile JSONs, sidecars, `--split-sheets`) is dropped by the user's decision.
This supersedes spec D13 and the spec's "Large datasets" resolution. Units, blocks and sections are
explained to the model in the skill instead of normalised in code. Review findings I1–I8 and
M1–M7 (`.superpowers/sdd/plan-c-review.md`) are fixed where they still apply.

**Architecture:**
- `db/migrations/0032_staff_sources_bucket.sql` — private bucket, 100 MB per object, staff-only SELECT policy.
- `app/integrations/storage.py` — `STAFF_SOURCES`, `split()` learns it, `upload()` takes `max_bytes`.
- `scripts/upload_staff_source.py` + `make staff-source` (ENV=staging only) — stores a workbook under
  a name-derived key and upserts its `documents` row (`doc_type 'source_dataset'`).
- `app/ingest/staff_sources.py` — identity helpers, download cache, the openpyxl scan, rendering,
  `hold_unmarked`. Pure helpers plus two repository calls; no tool lives here.
- `app/ingest/tools/pipeline_tools.py` — the `read_source_rows` tool, on `entity-researcher` only.
- `app/ingest/promote.py` — staff URLs map to the dataset row; unmarked staff findings are held.

**Spec:** features-plans/data-model/2026-10-07-funder-model-consolidation.md (§4, §5; D8, D9, D11,
D12, D14; D13 superseded as above).

## Global constraints

- **Stacked on plan B** (`feat/funder-schema-consolidation`, built): `funders.aliases`,
  `funder_activity` (kinds `spend|footprint|partner|programme`, `classified_by`,
  `classification_note`, `classification_confirmed`), `PartnerFinding.amount`, eligibility as a
  `documents` row, `'source_dataset'` already in `RESERVED_DOC_TYPES` (expectations.py) and named
  in the catalog's `doc_type` note.
- **Confidentiality.** The real workbooks are never committed, copied, logged, written to
  `content_md` or chunked. No real company, CSO or funder name, no file name and no figure from
  them appears in code, scratch scripts, skills, docs or commit messages. Scratch workbooks are
  generated in code with invented names ("Kestrel Polymers", "Heron Trust").
- **No cell value in any log line or error string.** Errors carry an exception's type name only.
- **Tool conventions** (CLAUDE.md): the tool never raises (returns `read_source_rows failed: …`),
  every row it returns carries `[source:<document_id>#<sheet>!<cell>]`, it is registered, named in
  the prompt that owns it (`prompts/entity_researcher.md`), and labelled in `toolLabels.ts`.
- **`DISPATCHABLE` and every `access_rule` stay unchanged.** The one registry edit is
  `ffrh_funder_datasets.basis` (D14).
- **Files staff-only, facts public (D14).** Workbooks and their `documents` rows are staff-only; a
  promoted fact is a public row like any other.
- **Schema changes only in `db/migrations/`.** 0032 follows plan B's 0031; renumber at merge if needed.
- **Comments and docstrings 1–2 lines** (tool docstrings excepted). Ruff line length 110, py312.
- **Never touch the dev database `sangam` or staging.** Scratch DB checks use `sangam_fc` only.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Environment (this machine; from plan B's context.md)

```bash
WT=/Users/siddhantsingh/Documents/sangam/.claude/worktrees/staff-sources
PY=/Users/siddhantsingh/Documents/sangam/backend/.venv/bin/python     # host venv, shared
RUFF=/Users/siddhantsingh/Documents/sangam/backend/.venv/bin/ruff
# unit tests
cd $WT/backend && PYTHONPATH=.:.. $PY -m pytest -p no:cacheprovider -q -m "not integration"
# scratch DB migrate (sangam_fc ONLY)
cd $WT/backend && DATABASE_URL=postgresql://sangam:sangam@localhost:5433/sangam_fc \
  MIGRATIONS_DIR=$WT/db/migrations PYTHONPATH=. $PY -m app.db.migrate
# frontend type check
cd $WT/frontend && ln -s /Users/siddhantsingh/Documents/sangam/frontend/node_modules node_modules \
  && npx tsc --noEmit && npm run lint; rm node_modules
```

Repo-wide ruff has pre-existing findings; check only touched files. Scratch scripts live in the
session scratchpad (`$SCRATCH`) and run with `cd $WT/backend && PYTHONPATH=. $PY $SCRATCH/<name>.py`.

## File map

| File | Change | Task |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | `openpyxl>=3.1` | 1 |
| `db/migrations/0032_staff_sources_bucket.sql` | create | 2 |
| `backend/app/integrations/storage.py` | `STAFF_SOURCES`, `BUCKETS`, `split()`, `upload(max_bytes=)` | 2 |
| `backend/app/api/routes/documents.py` | never sign a staff object on a public/org row | 2 |
| `backend/app/repositories/documents.py` | `upsert_source_dataset`, `list_source_datasets` | 3 |
| `backend/app/ingest/staff_sources.py` | create: identity, cache, scan, render, `hold_unmarked` | 3, 4, 5 |
| `scripts/upload_staff_source.py`, `Makefile` | create / `staff-source` target | 3 |
| `backend/app/repositories/funders.py` | `name_variants` | 4 |
| `backend/app/ingest/tools/pipeline_tools.py` | `read_source_rows` | 4 |
| `backend/app/ingest/agent.py` | add to `RESEARCH_TOOLS` | 4 |
| `backend/app/ingest/prompts/entity_researcher.md`, `instructions.md` | name the tool | 4 |
| `backend/tests/test_harness.py` | researcher tool set gains `read_source_rows` (existing test) | 4 |
| `frontend/features/ingest/lib/toolLabels.ts`, `docs/INGEST.md` | label, docs | 4 |
| `backend/app/ingest/promote.py` | staff URL mapping, marker hold | 5 |
| `backend/app/ingest/data/sources/funders.json` | `ffrh_funder_datasets.basis` | 5 |
| `backend/app/agent/tools/sql/catalog.py` | documents note/defect names `source_dataset` (M3) | 5 |
| `backend/app/ingest/skills/funder-intake-research/SKILL.md` | sections added, description | 6 |
| `backend/app/ingest/skills/ngo-credential-research/SKILL.md`, `docs/SKILLS.md` | CSO workbook; note | 6 |
| `.gitignore` | `*.xlsx` etc. | 7 |

---

### Task 1: openpyxl as a runtime dependency

**Files:** `backend/pyproject.toml`, `backend/uv.lock`

- [ ] **Step 1: Add the dependency.** In `backend/pyproject.toml`, after `"pypdf>=5",` add:

```toml
    "openpyxl>=3.1",
```

- [ ] **Step 2: Lock, and install into the host venv.**

```bash
cd $WT/backend && uv lock
uv pip install --python $PY "openpyxl>=3.1"
```

Expected: `uv.lock` gains `name = "openpyxl"` and `name = "et-xmlfile"`; no other package moves
(check `git diff --stat backend/uv.lock` is small).

- [ ] **Step 3: Verify (throwaway).**

```bash
grep -c 'name = "openpyxl"' $WT/backend/uv.lock          # 1
$PY -c "import openpyxl; print(openpyxl.__version__)"     # 3.1.x
```

- [ ] **Step 4: Commit.**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build(backend): add openpyxl for the staff workbook reader

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The `staff-sources` bucket, `storage.split`, and the download guard

**Files:** create `db/migrations/0032_staff_sources_bucket.sql`; modify
`backend/app/integrations/storage.py`, `backend/app/api/routes/documents.py`.

The largest workbook is ~59 MB, over 0020's 50 MB ceiling, and nothing splits it any more. So this
bucket allows 100 MB and `upload()` takes a `max_bytes`. The Supabase project's **global** upload
limit must also be ≥ 100 MB (a dashboard setting; gated step G2).

- [ ] **Step 1: Write the migration.** Create `db/migrations/0032_staff_sources_bucket.sql`:

```sql
-- A third private bucket, staff-sources: workbooks a staff member uploads by hand (statutory CSR
-- filing exports, and the CSO funder workbook shared under partner permission). Spec D8: staff only.
--
--   staff-sources   <registry key>/<sha256(file name)[:12]>.xlsx    the workbook, as uploaded
--
-- Each object has one documents row: doc_type 'source_dataset', is_public false, no org, no
-- funder, no content_md. documents_read (0027) and readable_document() already give such a row to
-- staff alone. The contents never enter the database, so the owner-run SQL tool cannot read them.
--
-- Guarded like 0020: the local container has no storage schema, so locally this is a no-op that
-- still records in schema_migrations. Number follows plan B's 0031; reassigned at merge if needed.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    RAISE NOTICE 'no storage schema (not Supabase) - skipping the staff-sources bucket';
    RETURN;
  END IF;

  -- 100 MB: one filing export is ~59 MB and is stored whole. storage.STAFF_SOURCES_MAX_BYTES matches.
  INSERT INTO storage.buckets (id, name, public, file_size_limit)
  VALUES ('staff-sources', 'staff-sources', false, 104857600)
  ON CONFLICT (id) DO NOTHING;

  -- The app reads with the service key; this policy is only for a staff client reading directly.
  IF to_regprocedure('app.is_staff()') IS NULL THEN
    RAISE NOTICE 'app.is_staff() missing - staff-sources gets no read policy; only the service role reads it';
    RETURN;
  END IF;
  BEGIN
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'staff_sources_staff_read'
    ) THEN
      CREATE POLICY staff_sources_staff_read ON storage.objects FOR SELECT TO authenticated
        USING (bucket_id = 'staff-sources' AND (SELECT app.is_staff()));
    END IF;
  EXCEPTION WHEN insufficient_privilege THEN
    -- Fail closed: without the policy only the service role reads the bucket.
    RAISE NOTICE 'not permitted to add a policy on storage.objects - staff-sources stays service-role only';
  END;
END
$$;
```

- [ ] **Step 2: Teach `storage.py` the bucket.** After `ORG_VAULT = "org-vault"` add:

```python
# Staff-only workbooks uploaded by scripts/upload_staff_source.py; 0032 creates it at 100 MB.
STAFF_SOURCES = "staff-sources"
STAFF_SOURCES_MAX_BYTES = 100 * 1024 * 1024
BUCKETS: tuple[str, ...] = (SOURCE_ARCHIVE, ORG_VAULT, STAFF_SOURCES)
```

Replace the body of `split` (keep its docstring, changing "neither of ours" to "not one of ours"):

```python
    bucket, _, key = storage_path.partition("/")
    return (bucket, key) if key and bucket in BUCKETS else None
```

In `upload`, add a keyword `max_bytes: int = MAX_ARCHIVE_BYTES` after `replace`, and use it in the
size check and its log line:

```python
async def upload(
    bucket: str, key: str, data: bytes, content_type: str, *, replace: bool = False,
    max_bytes: int = MAX_ARCHIVE_BYTES,
) -> str | None:
```

```python
    if len(data) > max_bytes:
        logger.warning(
            "not archiving %s: %.1f MB exceeds the %d MB bucket limit",
            key, len(data) / 1024 / 1024, max_bytes // 1024 // 1024,
        )
        return None
```

- [ ] **Step 3: Guard the download route.** In `document_file` (`backend/app/api/routes/documents.py`),
after the `if parts is None:` raise, insert:

```python
    # Only the upload script writes staff-sources paths, always on a private, org-less row.
    if parts[0] == storage.STAFF_SOURCES and (row["is_public"] or row["org_id"] is not None):
        raise HTTPException(404, f"document {document_id} has no readable file")
```

- [ ] **Step 4: Verify (throwaway).**
  1. Migration parses and no-ops locally: run the scratch-DB migrate command (Environment) against
     `sangam_fc`. Expected: `0032_staff_sources_bucket.sql` applied, NOTICE `no storage schema`.
  2. `cd $WT/backend && PYTHONPATH=. $PY -c "from app.integrations import storage as s; print(s.split('staff-sources/mca_csr/0123456789ab.xlsx'), s.split('elsewhere/x'))"`
     → `('staff-sources', 'mca_csr/0123456789ab.xlsx') None`.
  3. Route: create `backend/tests/test_zz_scratch_staff.py` (uses the existing `client_for`/`storage_on`
     fixtures; **delete it before committing**):

```python
from app.api.routes import documents as documents_api

ROUTE = "app.api.routes.documents"


async def _async(v):
    return v


async def test_scratch_staff_route(client_for, monkeypatch, storage_on):
    path = "staff-sources/mca_csr/0123456789ab.xlsx"
    for flags, code in (({"is_public": True, "org_id": None}, 404), ({"is_public": False, "org_id": 3}, 404),
                        ({"is_public": False, "org_id": None}, 200)):
        async def fake_row(pool, *, document_id, user_id, flags=flags):
            return {"id": 7, "title": "x", "storage_path": path, **flags}

        monkeypatch.setattr(f"{ROUTE}.repo.readable_document", fake_row)
        monkeypatch.setattr(f"{ROUTE}.storage.signed_url", lambda b, k: _async(f"https://p/{b}/{k}"))
        async with client_for(documents_api.router) as client:
            assert (await client.get("/api/documents/7/file")).status_code == code
```

     Run it, then `rm backend/tests/test_zz_scratch_staff.py`.
  4. Existing suites still pass: `pytest tests/test_storage.py tests/test_vault.py -m "not integration"`.
  5. `$RUFF check app/integrations/storage.py app/api/routes/documents.py`.

- [ ] **Step 5: Commit** (confirm `git status` shows no scratch test).

```bash
git add db/migrations/0032_staff_sources_bucket.sql backend/app/integrations/storage.py backend/app/api/routes/documents.py
git commit -m "feat(storage): private staff-sources bucket, readable by staff alone

Guarded like 0020; 100 MB per object; the read policy is SELECT for app.is_staff()
and fails closed. The download route never signs a staff object on a public or
org row.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The upload script and `make staff-source`

**Files:** create `backend/app/ingest/staff_sources.py` (identity part), `scripts/upload_staff_source.py`;
modify `backend/app/repositories/documents.py`, `Makefile`.

**Identity (I1).** A dataset is identified by its **file name**, not its bytes: key
`<registry key>/<sha256(name)[:12]>.xlsx`, `source_url` `https://staff-sources.sangam.invalid/<same 12>`.
Re-uploading a corrected file under the same name overwrites the object (`replace=True`) and
updates the same row, so findings citing the old URL keep mapping. No file name reaches the
database (Ask's SQL tool can read `title` and `storage_path`). Renaming a file makes a new dataset;
retire the old row by hand.

**Environment (I6).** Storage is global, so a local-ENV upload would put the row locally and the
object in the cloud. The Makefile target refuses anything but `ENV=staging`.

- [ ] **Step 1: Repository functions.** Append to `backend/app/repositories/documents.py`:

```python
async def upsert_source_dataset(
    pool: AsyncConnectionPool, *, title: str, source_key: str, storage_path: str, source_url: str,
    content_hash: str,
) -> tuple[int, str]:
    """A staff dataset's row: private, nobody's, no content. Keyed on storage_path, so re-upload updates it."""
    params = {"title": title, "url": source_url, "key": source_key, "hash": content_hash, "path": storage_path}
    async with pool.connection() as conn, conn.transaction():
        row = await (await conn.execute(
            """UPDATE documents SET content_hash = %(hash)s, fetched_at = now(), title = %(title)s,
                      source_url = %(url)s, source_name = %(key)s
               WHERE doc_type = 'source_dataset' AND storage_path = %(path)s RETURNING id""",
            params,
        )).fetchone()
        if row:
            return row["id"], "replaced"
        row = await (await conn.execute(
            """INSERT INTO documents (org_id, funder_id, title, doc_type, source_url, source_name,
                                      fetched_at, content_hash, extractor_version, storage_path,
                                      is_public, status)
               VALUES (NULL, NULL, %(title)s, 'source_dataset', %(url)s, %(key)s, now(), %(hash)s,
                       'upload_staff_source/1', %(path)s, false, 'received')
               RETURNING id""",
            params,
        )).fetchone()
    return row["id"], "added"


async def list_source_datasets(pool: AsyncConnectionPool) -> list[dict]:
    """Every staff dataset row. Staff-only by construction: private and org-less."""
    sql = """
    SELECT id, title, source_name, source_url, storage_path, content_hash FROM documents
    WHERE doc_type = 'source_dataset' AND NOT is_public AND org_id IS NULL AND funder_id IS NULL
    ORDER BY source_name, id
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql)).fetchall()
```

- [ ] **Step 2: Identity helpers.** Create `backend/app/ingest/staff_sources.py`:

```python
"""Staff-only source workbooks: where they live, how they are read, how a fact from one is cited.

Confidential: nothing here logs or returns an error carrying a cell value."""

from __future__ import annotations

import hashlib
from pathlib import PurePath

DOC_TYPE = "source_dataset"
SOURCE_URL_PREFIX = "https://staff-sources.sangam.invalid/"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dataset_id(filename: str) -> str:
    """A file's identity is its base name, so a corrected re-upload replaces it."""
    return hashlib.sha256(PurePath(filename).name.encode()).hexdigest()[:12]


def object_key(source_key: str, filename: str) -> str:
    return f"{source_key}/{dataset_id(filename)}.xlsx"


def source_url(filename: str) -> str:
    """http(s) as findings require; resolves nowhere (RFC 2606) and names no file."""
    return SOURCE_URL_PREFIX + dataset_id(filename)


def is_staff_source_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(SOURCE_URL_PREFIX)


def title(source_key: str, filename: str) -> str:
    return f"Staff dataset · {source_key} · {dataset_id(filename)}"
```

- [ ] **Step 3: The script.** Create `scripts/upload_staff_source.py`:

```python
"""Upload one staff-only workbook to the private staff-sources bucket (spec §4).

    make staff-source ENV=staging FILE="<path>.xlsx" KEY=<registry key>

Service key, staff-run. Re-uploading the same file name replaces the object and updates its row.
Prints counts only, never a cell, a sheet name or the file name.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.checkpointer import make_pool
from app.ingest import staff_sources
from app.ingest.sources import SOURCES
from app.integrations import storage
from app.repositories import documents as documents_repo


def _sheet_count(data: bytes) -> int:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return len(wb.worksheets)
    finally:
        wb.close()


async def main(path: Path, source_key: str) -> int:
    settings = get_settings()
    if not settings.storage_enabled:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set: staff datasets live only in Storage.")
        return 2
    if source_key not in SOURCES:
        print(f"{source_key!r} is not a registered source key.")
        return 2
    data = path.read_bytes()
    if len(data) > storage.STAFF_SOURCES_MAX_BYTES:
        print(f"{len(data) / 1024 / 1024:.1f} MB is over the 100 MB staff-sources limit.")
        return 2
    try:
        sheets = _sheet_count(data)
    except Exception as exc:  # noqa: BLE001 - any openpyxl failure means "not a workbook we can read"
        print(f"not a readable .xlsx workbook ({type(exc).__name__}); nothing stored.")
        return 2
    key = staff_sources.object_key(source_key, path.name)
    stored = await storage.upload(storage.STAFF_SOURCES, key, data, staff_sources.XLSX, replace=True,
                                  max_bytes=storage.STAFF_SOURCES_MAX_BYTES)
    if stored is None:
        print("storing the workbook failed - does 0032's bucket exist, and is the project's global "
              "upload limit at least 100 MB?")
        return 1
    pool = make_pool(settings.database_url, max_size=2)
    await pool.open()
    try:
        document_id, status = await documents_repo.upsert_source_dataset(
            pool, title=staff_sources.title(source_key, path.name), source_key=source_key,
            storage_path=storage.qualify(storage.STAFF_SOURCES, key),
            source_url=staff_sources.source_url(path.name), content_hash=storage.content_hash(data),
        )
    finally:
        await pool.close()
    print(f"{status}: document {document_id} · {storage.qualify(storage.STAFF_SOURCES, key)} · {sheets} sheets")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--source-key", required=True, help="registry key, e.g. mca_csr")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.file, args.source_key)))
```

- [ ] **Step 4: Makefile target.** Add `staff-source` to the `.PHONY` line; after the `client-docs`
target add:

```make
# Upload one staff-only workbook (spec §4). Host venv: the file is on this machine. Staging only:
# Storage is global, so a local row would name a cloud object.
staff-source:  ## Upload a staff workbook: make staff-source ENV=staging FILE="<xlsx>" KEY=<registry key>
	@test "$(ENV)" = staging || { echo 'staff-source runs with ENV=staging only (Storage is global).'; exit 2; }
	@test -n "$(FILE)" && test -n "$(KEY)" || { echo 'usage: make staff-source ENV=staging FILE="<xlsx>" KEY=<key>'; exit 2; }
	@set -a; [ -f .env ] && . ./.env; set +a; \
	DATABASE_URL="$(DB_URL)" PYTHONPATH=backend backend/.venv/bin/python scripts/upload_staff_source.py \
	  "$(FILE)" --source-key "$(KEY)"
```

- [ ] **Step 5: Verify (throwaway, no network, no DB).** `$SCRATCH/upload_check.py` imports the
script by path and stubs its collaborators:

```python
import asyncio, importlib.util, io, sys, tempfile
from pathlib import Path
from openpyxl import Workbook

spec = importlib.util.spec_from_file_location("up", "/Users/siddhantsingh/Documents/sangam/.claude/worktrees/staff-sources/scripts/upload_staff_source.py")
up = importlib.util.module_from_spec(spec); spec.loader.exec_module(up)

wb = Workbook(); wb.active.title = "S"; wb.active.append(["Company Name", "Amount"]); wb.active.append(["Kestrel Polymers Limited", 0.5])
buf = io.BytesIO(); wb.save(buf)
f = Path(tempfile.mkdtemp()) / "invented.xlsx"; f.write_bytes(buf.getvalue())

keys, rows = [], {}
async def upload(bucket, key, data, ct, *, replace, max_bytes): keys.append((bucket, key, replace)); return key
async def upsert(pool, **kw):
    status = "replaced" if kw["storage_path"] in rows else "added"; rows[kw["storage_path"]] = kw; return 1, status
class Pool:
    async def open(self): pass
    async def close(self): pass
up.storage.upload = upload
up.documents_repo.upsert_source_dataset = upsert
up.make_pool = lambda *a, **k: Pool()
up.get_settings = lambda: type("S", (), {"storage_enabled": True, "database_url": "x"})()

assert asyncio.run(up.main(f, "mca_csr")) == 0
assert asyncio.run(up.main(f, "mca_csr")) == 0                 # same name twice
assert len(rows) == 1 and keys[0] == keys[1] and keys[0][2] is True
assert "invented" not in str(rows) and "invented" not in str(keys)   # no file name stored
assert asyncio.run(up.main(f, "not_a_key")) == 2
print("ok", keys[0][1])
```

Expected: prints `added: …`, then `replaced: …`, then `ok mca_csr/<12 hex>.xlsx`. Then:

```bash
make staff-source FILE=/tmp/x.xlsx KEY=mca_csr; echo $?     # refuses: ENV=staging only, exit 2
$RUFF check backend/app/repositories/documents.py backend/app/ingest/staff_sources.py scripts/upload_staff_source.py
```


- [ ] **Step 6: Commit.**

```bash
git add backend/app/repositories/documents.py backend/app/ingest/staff_sources.py scripts/upload_staff_source.py Makefile
git commit -m "feat(scripts): upload a staff workbook to staff-sources, one private row per file

Identity is the file name, so a corrected re-upload replaces the object and its
row. Staging only: Storage is global. Nothing from the file reaches the row.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `read_source_rows` on the researcher

**Files:** modify `backend/app/ingest/staff_sources.py`, `backend/app/repositories/funders.py`,
`backend/app/ingest/tools/pipeline_tools.py`, `backend/app/ingest/agent.py`,
`backend/app/ingest/prompts/entity_researcher.md`, `backend/app/ingest/instructions.md`,
`backend/tests/test_harness.py` (existing assertion), `frontend/features/ingest/lib/toolLabels.ts`,
`docs/INGEST.md`.

**Interface:** `read_source_rows(name: str, sheet: str = "") -> str`. `sheet` is an optional
substring filter on sheet names (e.g. `"2023-24"`); it narrows output and skips parsing other sheets.

**What it returns, per dataset with a match:** the dataset's `source_url`/`source_name`; per sheet,
its first `HEADER_ROWS` (3) non-empty rows; each matching row; and for each match the context a
sectioned sheet needs — the latest numbered heading (`1. …`), the latest one-cell heading, and the
row under that heading (the sub-table's header). A matching numbered heading brings its section
(up to 40 rows, to the next numbered heading). Each row is one line:
`[source:<doc>#<sheet>!<first cell>] B17='…' · C17='…'`.

**Matching:** the name plus the funder's catalog name and `aliases` (from `name_variants`),
case- and punctuation-folded, trailing `Ltd/Limited/Pvt/Private` and a leading `The` dropped; a cell
matches when the term occurs as whole words. Terms under three characters are dropped.

**Contacts:** any column whose header (in the header rows, or a sub-table header row) contains
`phone`, `mobile`, `email`, `e-mail`, `contact person` or `address` is dropped for that sheet, and
any cell holding an email address is replaced by `[email removed]`.

**Cost (accepted):** each call downloads each workbook once per process (cached by
`storage_path` + `content_hash`, 200 MB cap, one download at a time per object) but re-scans the
sheets every call: ~6.6 s per 100k rows, so about a minute on the largest export unless the
researcher passes `sheet`. Accepted for a first cut; a per-process row cache is the next step if
acceptance runs prove it too slow.

- [ ] **Step 1: `name_variants`.** Append to `backend/app/repositories/funders.py`:

```python
def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def name_variants(pool: AsyncConnectionPool, *, match: str, limit: int = 5) -> list[dict]:
    """Funders whose name or an alias contains `match`, with every name they go by."""
    sql = """
    SELECT name, aliases FROM funders
    WHERE name ILIKE %(p)s OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE a ILIKE %(p)s)
    ORDER BY similarity(name, %(m)s) DESC, id
    LIMIT %(limit)s
    """
    async with pool.connection() as conn:
        return await (await conn.execute(sql, {"p": _like(match), "m": match, "limit": limit})).fetchall()
```

(`similarity()` is `pg_trgm`, already required by `funders_name_trgm` in `02_schema.sql`.)

- [ ] **Step 2: The read path.** In `backend/app/ingest/staff_sources.py`, extend the imports to:

```python
import asyncio
import hashlib
import io
import logging
import re
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import PurePath
from typing import Any

from app.integrations import storage
from app.repositories import documents as documents_repo
from app.repositories import funders as funders_repo

logger = logging.getLogger(__name__)
```

and append:

```python
HEADER_ROWS = 3            # top rows of a sheet shown with any match
SECTION_ROWS = 40          # rows a matching numbered heading brings with it
MAX_CHARS = 60_000         # ~15k tokens of tool output
CONTACT_HEADERS = ("phone", "mobile", "email", "e mail", "contact person", "address")
_SUFFIXES = {"ltd", "limited", "pvt", "private"}
_NON_WORD = re.compile(r"[^\w]+")
_NUMBERED = re.compile(r"^\s*\d+\s*[.)]\s*\S")
_EMAIL = re.compile(r"\S+@\S+\.\w+")
_CACHE_MAX_BYTES = 200 * 1024 * 1024
_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}


def _words(value: Any) -> str:
    return " ".join(_NON_WORD.sub(" ", str(value).casefold()).split())


def search_terms(names: Iterable[str | None]) -> list[str]:
    terms: list[str] = []
    for name in names:
        words = _words(name or "").split()
        while words and words[-1] in _SUFFIXES:
            words.pop()
        if words and words[0] == "the":
            words.pop(0)
        term = " ".join(words)
        if len(term) >= 3 and term not in terms:
            terms.append(term)
    return terms


def _hit(value: Any, terms: list[str]) -> bool:
    if not isinstance(value, str):
        return False
    padded = f" {_words(value)} "
    return any(f" {t} " in padded for t in terms)


def _contact_columns(values: tuple) -> set[int]:
    return {c for c, v in enumerate(values, start=1)
            if isinstance(v, str) and any(f" {h} " in f" {_words(v)} " for h in CONTACT_HEADERS)}


def scan(data: bytes, terms: list[str], only_sheet: str = "") -> list[tuple[str, list[tuple[int, tuple]], set[int]]]:
    """Per sheet with a match: its title, the rows to show (header, context, matches), and contact columns."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    try:
        for ws in wb.worksheets:
            if only_sheet and only_sheet.casefold() not in ws.title.casefold():
                continue
            ws.reset_dimensions()  # some exports carry a wrong <dimension>; read_only trusts it otherwise
            rows: dict[int, tuple] = {}
            drop: set[int] = set()
            numbered = heading = under = None
            section_left, matched, seen = 0, False, 0
            for r, values in enumerate(ws.iter_rows(values_only=True), start=1):
                filled = [v for v in values if v not in (None, "")]
                if not filled:
                    continue
                seen += 1
                hit = any(_hit(v, terms) for v in filled)
                if seen <= HEADER_ROWS:  # shown always; a match here still counts (data can start on row 2)
                    rows[r] = values
                    drop |= _contact_columns(values)
                    matched = matched or hit
                    continue
                if heading and under is None and r == heading[0] + 1:
                    under = (r, values)
                    drop |= _contact_columns(values)
                if len(filled) == 1:
                    heading, under = (r, values), None
                    if _NUMBERED.match(str(filled[0])):
                        numbered, section_left = (r, values), (SECTION_ROWS if hit else 0)
                if hit or section_left:
                    for ctx in (numbered, heading, under):
                        if ctx:
                            rows.setdefault(*ctx)
                    rows[r] = values
                    matched = matched or hit
                    section_left = max(section_left - 1, 0)
            if matched:
                out.append((ws.title, sorted(rows.items()), drop))
    finally:
        wb.close()
    return out


def _cell(value: Any) -> str:
    text = " ".join(str(value).split())
    return "[email removed]" if _EMAIL.search(text) else text[:300]


def render(doc: dict[str, Any], sheets: list[tuple[str, list[tuple[int, tuple]], set[int]]]) -> str:
    from openpyxl.utils import get_column_letter

    lines = [f"## document {doc['id']} · {doc['source_name']}",
             f"A finding from it: source_url {doc['source_url']} · source_name {doc['source_name']}"]
    for title, rows, drop in sheets:
        lines.append(f"### sheet {title!r}")
        for r, values in rows:
            cells = [(f"{get_column_letter(c)}{r}", v) for c, v in enumerate(values, start=1)
                     if v not in (None, "") and c not in drop]
            if cells:
                body = " · ".join(f"{ref}={_cell(v)!r}" for ref, v in cells)
                lines.append(f"[source:{doc['id']}#{title}!{cells[0][0]}] {body}")
    return "\n".join(lines)


async def _workbook(doc: dict[str, Any]) -> bytes | None:
    """The workbook's bytes, downloaded once per process and per upload (content_hash)."""
    parts = storage.split(doc["storage_path"] or "")
    if parts is None or parts[0] != storage.STAFF_SOURCES:
        return None
    key = (doc["storage_path"], doc["content_hash"] or "")
    async with _locks.setdefault(doc["storage_path"], asyncio.Lock()):
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        data = await storage.download(*parts, max_bytes=storage.STAFF_SOURCES_MAX_BYTES)
        if data is None:
            return None
        _cache[key] = data
        while len(_cache) > 1 and sum(len(b) for b in _cache.values()) > _CACHE_MAX_BYTES:
            _cache.popitem(last=False)
        return data


async def read_rows(pool: Any, name: str, *, sheet: str = "") -> str:
    name = (name or "").strip()
    funders = await funders_repo.name_variants(pool, match=name) if len(name) >= 3 else []
    terms = search_terms([name, *(n for f in funders for n in (f["name"], *(f["aliases"] or [])))])
    if not terms:
        return "read_source_rows needs a name of at least three letters."
    datasets = await documents_repo.list_source_datasets(pool)
    if not datasets:
        return "No staff dataset is uploaded (make staff-source). Nothing was read."
    parts: list[str] = []
    problems: list[str] = []
    for doc in datasets:
        data = await _workbook(doc)
        if data is None:
            problems.append(f"document {doc['id']} ({doc['source_name']}) could not be downloaded.")
            continue
        try:
            sheets = await asyncio.to_thread(scan, data, terms, sheet)
        except Exception as exc:  # noqa: BLE001 - type only: a message could quote a cell
            problems.append(f"document {doc['id']} ({doc['source_name']}) could not be read ({type(exc).__name__}).")
            continue
        if sheets:
            parts.append(render(doc, sheets))
    logger.info("read_source_rows: %d of %d datasets matched", len(parts), len(datasets))
    head = [f"read_source_rows: {len(parts)} of {len(datasets)} staff datasets name one of: {'; '.join(terms)}."]
    if not parts:
        head.append("No row matched. The filer is often the parent company, not the foundation: try its "
                    "registered name.")
        return "\n".join(head + problems)
    head.append("Cite a fact by the marker of the cell that holds it: [source:<document>#<sheet>!<cell>]. "
                "Amounts are as printed; the sheet's unit is in your skill's sheet notes.")
    text = "\n\n".join(["\n".join(head), *parts, *problems])
    if len(text) > MAX_CHARS:
        cut = text.rfind("\n", 0, MAX_CHARS)
        text = (text[:cut] + f"\n… output cut at {MAX_CHARS} characters. Call again with `sheet` "
                "(e.g. one fiscal year) to read the rest.")
    return text
```

- [ ] **Step 3: The tool.** In `backend/app/ingest/tools/pipeline_tools.py`, add
`from app.ingest import staff_sources` to the imports, change the module docstring's first line to
`"""The adapter path: the source registry, the runs that pull from it, and the staff workbooks.`,
and append:

```python
@tool
async def read_source_rows(name: str, sheet: str = "") -> str:
    """Read the staff-only workbooks — statutory CSR filing exports and the CSO funder workbook — for one name.

    Searches every sheet of every uploaded workbook for rows naming `name`, or any name
    the catalog holds for that funder (its aliases). Returns each sheet's header rows, the
    matching rows, and the section heading and sub-table header above each match, every
    row as cell=value pairs with a [source:<document>#<sheet>!<cell>] marker.

    Cite a fact by the marker of the CELL that holds it (change the cell in the marker),
    with the dataset's source_url and source_name printed above its rows. The source_url
    is cited, never fetched. Amounts are as printed: save the figure with the sheet's
    unit (crore, lakh or a unit written in the cell), as your skill's sheet notes say.

    Contact columns are removed by design. The filer is often the parent company, not
    the foundation: search both names.

    Args:
        name: a company, funder or CSO name, at least three letters.
        sheet: optional part of a sheet name (e.g. "2023-24") to read one sheet only.
    """
    try:
        return await staff_sources.read_rows(get_pool(), name, sheet=sheet)
    except Exception as exc:  # noqa: BLE001 - a tool returns its failure; type only, never a value
        return f"read_source_rows failed: {type(exc).__name__}"
```

- [ ] **Step 4: Register it.** In `backend/app/ingest/agent.py`, add `read_source_rows` to the
`pipeline_tools` import and to `RESEARCH_TOOLS` after `funder_dossier`:

```python
RESEARCH_TOOLS = [
    research_goals,
    funder_dossier,
    # Staff-only workbooks; the gate is the require_staff Import route this agent sits behind.
    read_source_rows,
    search_public_sources,
    read_page,
    fetch_document,
    read_document_pages,
]
```

In `backend/tests/test_harness.py`, `test_the_researcher_gets_its_seven_and_nothing_of_the_filesystem`
(an existing test this breaks): rename to `..._its_eight_...` and add `"read_source_rows"` to the set.

- [ ] **Step 5: Name it in the researcher's prompt** (`prompts/entity_researcher.md`).

(a) After the `**STEP 2: …**` paragraph, insert (M1, M4, I2):

```markdown
**For a corporate funder, after STEP 1's search: `read_source_rows(name)`.** The staff workbooks hold statutory CSR filing exports and a CSO funder workbook. Search the filer's registered name — often the parent company, not the foundation — and the foundation's. Each row comes as `cell=value` pairs with a `[source:<document>#<sheet>!<cell>]` marker; a finding from it uses the dataset's `source_url` and `source_name` printed above its rows and quotes the row's line, **with the marker of the cell that holds the fact**. Without a marker, promotion holds the finding. The `source_url` (`https://staff-sources.sangam.invalid/…`) is cited, never fetched. Save each amount as printed with the sheet's unit. A filing repeats the company's year figures on every project line: take them once per company-year, never add them up. A grant amount on a CSO funder sheet is a `partner` finding for the funder (the CSO as `partner_name`): an exact fiscal year gives that year and the `amount`; a range of years gives the **last** fiscal year of the range and **no amount**, the range quoted in the evidence; a row with no closing year is named in your summary, not saved. Calls to it do not count against your document budget.
```

(b) In `## Your tools`, before the `save_research` bullet:

```markdown
- `read_source_rows(name, sheet)` — the staff workbooks: statutory CSR filing exports and the CSO
  funder workbook, every sheet, rows as `cell=value` with a `[source:…]` marker. Cite the cell;
  never fetch the dataset's `source_url`.
```

- [ ] **Step 6: Tell the supervisor** (`instructions.md`).

(a) Append to `## Source priority`, after `…is the error to watch for.`:

```markdown

For a corporate funder the statutory filing is often already here: the staff workbooks, which a
researcher reads with `read_source_rows`. Put the filer's registered name in the task when you
know it — the filer is often the parent company, not the foundation.
```

(b) In "Tools you do NOT have", replace the researcher row with:

```markdown
| `research_goals` · `read_source_rows` · `search_public_sources` · `read_page` · `fetch_document` · `read_document_pages` · `save_research` | `entity-researcher` |
```

- [ ] **Step 7: Label it.** In `frontend/features/ingest/lib/toolLabels.ts`, after the
`read_document_pages` entry:

```ts
  read_source_rows: {
    label: "Reading staff workbooks",
    detail: (a) => [a?.name, a?.sheet].filter(Boolean).join(" · "),
  },
```

- [ ] **Step 8: Document it** (`docs/INGEST.md`). Replace the `pipeline_tools.py` table row with:

```markdown
| `pipeline_tools.py` | `list_import_sources` · `plan_import` · `run_import_now` · `import_run_summary` · `pending_resolutions` · `read_source_rows` |
```

After the `**`entity-researcher`**` paragraph add:

```markdown
**Staff workbooks.** `read_source_rows` is the researcher's eighth tool (the supervisor's five
pipeline tools do not include it). It reads the workbooks a person uploaded with `make staff-source`
from the private `staff-sources` bucket with openpyxl and returns header rows and matching rows as
`cell=value`, each cited `[source:<document>#<sheet>!<cell>]`. There is no layout parser: how each
sheet is laid out, and its unit, is in the `funder-intake-research` skill. Contact columns are
dropped. Promoted facts are public (D14); the files and their `documents` rows stay staff-only, and
`promote` holds a staff finding without its marker. Tool output reaches the model provider and,
with tracing on, Langfuse, like every tool output.
```

- [ ] **Step 9: Verify (throwaway).** `$SCRATCH/read_check.py` — generates an invented workbook with
the three shapes, runs `scan`/`render` directly, then the tool with stubs:

```python
import asyncio, io, time
from openpyxl import Workbook
from app.ingest import staff_sources as ss
from app.ingest.tools import pipeline_tools as pt

wb = Workbook()
t = wb.active; t.title = "2023-24"
t.append(["Year", "Company Name", "State", "CSR Spent", "Project", "State", "Amount"])
t.append(["2023-24", "Osprey Mills Limited", "Goa", 2, "Clinics", "Goa", 1])         # rows 2-3 are shown as
t.append(["2023-24", "Osprey Mills Limited", "Goa", 2, "Wells", "Goa", 1])           # "header rows" (first 3)
t.append(["2023-24", "KESTREL POLYMERS LIMITED", "Goa", 1.5, "School kits", "Assam", 0.4])
t.append(["2023-24", "Kestrelworks Private Limited", "Goa", 9, "x", "Goa", 1])      # must NOT match
b = wb.create_sheet("Blocks")
b.append(["Heron Trust", None, None, "Egret Society", None])
b.append(["Funder", "Year", "Grant (₹)", "Funder", "Fund Amount (Rs)"])
b.append(["Kestrel Foundation", "2023-24", "4 Lakhs", "Other Fund", "1Cr"])
s = wb.create_sheet("Sections")
s.append(["Funders and partners"]); s.append(["All amounts in lakh"]); s.append([None]); s.append(["Intro"])
s.append(["1. Heron Trust"]); s.append(["FUNDERS"])
s.append(["#", "Funder Name", "Type", "Year(s)", "Amount (₹ Lakhs)", "Contact Person"])
s.append([1, "The Kestrel Foundation", "CSR", "2021-2024", 7.5, "someone@example.org"])
buf = io.BytesIO(); wb.save(buf); data = buf.getvalue()

terms = ss.search_terms(["Kestrel Polymers Ltd.", "Kestrel Foundation"])
out = ss.render({"id": 41, "source_name": "x", "source_url": "u"}, ss.scan(data, terms))
print(out)
assert "B4='KESTREL POLYMERS LIMITED'" in out and "Kestrelworks" not in out
assert "[source:41#Blocks!A3]" in out and "A1='Heron Trust'" in out           # block title row shown
assert "A5='1. Heron Trust'" in out and "A6='FUNDERS'" in out                  # section heading + sub-table
assert "B7='Funder Name'" in out and "someone@" not in out and "Contact" not in out
cso = ss.render({"id": 41, "source_name": "x", "source_url": "u"}, ss.scan(data, ss.search_terms(["Heron Trust"])))
assert "B8='The Kestrel Foundation'" in cso                                     # a heading brings its section
assert ss.search_terms(["AB", "The Ltd"]) == []

async def no_pool_call(*a, **k): return [{"name": "Kestrel Foundation", "aliases": ["Kestrel Polymers Ltd"]}]
async def datasets(pool): return [{"id": 41, "source_name": "mca_csr", "source_url": "u", "content_hash": "h",
                                   "storage_path": "staff-sources/mca_csr/0123456789ab.xlsx", "title": "t"}]
async def download(*a, **k): raise RuntimeError("KESTREL secret value")
ss.funders_repo.name_variants = no_pool_call
ss.documents_repo.list_source_datasets = datasets
pt.get_pool = lambda: None
ss.storage.download = download
res = asyncio.run(pt.read_source_rows.ainvoke({"name": "Kestrel"}))
assert res.startswith("read_source_rows failed: RuntimeError") and "secret" not in res, res

# Cost: a 100k-row single sheet, scanned once.
big = Workbook(); w = big.active
w.append([f"H{i}" for i in range(20)])
for i in range(100_000):
    w.append([f"Company {i % 5000}", "2023-24", "State", "District", i * 0.01] + ["filler text"] * 15)
b2 = io.BytesIO(); big.save(b2)
t0 = time.time(); ss.scan(b2.getvalue(), ["company 42"]); print(f"100k rows: {time.time() - t0:.1f}s, {len(b2.getvalue()) / 1e6:.1f} MB")
print("ok")
```

Expected: the asserts pass (fix `scan` if one exposes a bug; never loosen the confidentiality
asserts). Record the timing line in the task report. Reference, measured while writing this plan
with openpyxl 3.1.5: **~6.6 s per 100k rows (5.8 MB)**, so the ~59 MB export costs about a minute
per unfiltered call (accepted, see "Cost"). Materially worse than that: stop and report.

Then: existing suites `tests/test_harness.py tests/test_ingest.py` pass (including
`test_a_subagent_prompt_names_every_tool_its_spec_declares[ENTITY_RESEARCHER]` and
`test_instructions_name_every_registered_tool`); ruff on touched files; frontend `tsc` + lint
(Environment).

- [ ] **Step 10: Commit.**

```bash
git add backend/app/ingest/staff_sources.py backend/app/repositories/funders.py backend/app/ingest/tools/pipeline_tools.py backend/app/ingest/agent.py backend/app/ingest/prompts/entity_researcher.md backend/app/ingest/instructions.md backend/tests/test_harness.py frontend/features/ingest/lib/toolLabels.ts docs/INGEST.md
git commit -m "feat(ingest): read_source_rows - the researcher reads the staff workbooks itself

openpyxl, every sheet, header rows plus matching rows as cell=value, each cited
to its cell. Matches the funder's catalog name and aliases; drops contact
columns; never raises and never echoes a cell in an error.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Promotion — staff URLs map to the dataset row; unmarked findings are held

**Files:** modify `backend/app/ingest/staff_sources.py`, `backend/app/ingest/promote.py`,
`backend/app/ingest/data/sources/funders.json`, `backend/app/agent/tools/sql/catalog.py`.

Why the early `continue` is required: `ensure_document` keys reserved kinds on owner, so a
`document` finding at a staff URL has kind `''`, never matches the `'source_dataset'` row, and
would INSERT a new `is_public = true` row (writer.py `ensure_document`).

- [ ] **Step 1: The marker check.** Append to `backend/app/ingest/staff_sources.py`:

```python
_MARKER = re.compile(r"\[source:\d+#[^\]]+![A-Z]{1,3}\d+\]")


def hold_unmarked(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Promotable findings, and a held reason for each staff-dataset finding with no cell marker."""
    kept: list[dict[str, Any]] = []
    held: list[str] = []
    for f in findings:
        if is_staff_source_url(f.get("source_url")) and not _MARKER.search(str(f.get("evidence", ""))):
            held.append(f"{f.get('concept')}: cites a staff dataset without its [source:…] marker — quote "
                        f"the row's line with the marker of the cell that holds the fact")
        else:
            kept.append(f)
    return kept, held
```

- [ ] **Step 2: Wire it into `promote.py`.** Add `from app.ingest import staff_sources` to the
imports. In `promote()`, right after the `schema_version` block's `return report`, insert:

```python
    findings, unmarked = staff_sources.hold_unmarked(findings)
    report["held"].extend(unmarked)
```

In `_write_documents`, make the first statement inside `for f in _validated(findings, "document", report):`:

```python
        if staff_sources.is_staff_source_url(f.source_url):
            continue  # the dataset's private row exists; ensure_document would add a public one
```

Replace its final `return by_url` with:

```python
    by_url.update(await _staff_datasets(conn, findings))
    return by_url


async def _staff_datasets(conn: Any, findings: list[dict[str, Any]]) -> dict[str, int]:
    """source_url -> the private row of each staff dataset cited, so its lines carry document_id."""
    urls = sorted({f["source_url"] for f in findings if staff_sources.is_staff_source_url(f.get("source_url"))})
    if not urls:
        return {}
    rows = await (await conn.execute(
        "SELECT id, source_url FROM documents WHERE doc_type = 'source_dataset' AND source_url = ANY(%s) "
        "ORDER BY id",
        (urls,),
    )).fetchall()
    found: dict[str, int] = {}
    for row in rows:
        found.setdefault(row["source_url"], row["id"])
    return found
```

Every writer already resolves `docs.get(f.source_url)`, so a spend, csr-year, partner or programme
line from a staff dataset now carries the dataset's `document_id`, with the `.invalid` URL and the
registry key as provenance, and is written public by the writers' default (D14).

- [ ] **Step 3: FFRH basis (D14).** In `funders.json`, `ffrh_funder_datasets`, replace `basis` with:

```json
      "basis": "Shared by FFRH for this project through Drive. Use follows the FFRH agreement; FFRH has cleared its figures, funder-CSO links and grant amounts included, for display. The files stay in the staff-only bucket; facts promoted from them are public.",
```

Leave `access_rule`, `categories`, `yields`, `robots_checked_at` unchanged.

- [ ] **Step 4: Catalog (M3).** In `backend/app/agent/tools/sql/catalog.py`, documents table:
  - the `is_public` column note becomes `"false = a private vault upload, a hidden funder's eligibility document, or a staff dataset (doc_type 'source_dataset') - all staff or owner only"`;
  - add a defect after the `is_public = false` one:

```python
            "doc_type 'source_dataset' rows are staff-only workbooks with no content_md; their contents are read only by Sangam Import. Facts promoted from them cite a non-resolving https://staff-sources.sangam.invalid/ URL by design - never present that URL as a link.",
```

- [ ] **Step 5: Verify (throwaway, no DB).** `$SCRATCH/promote_check.py`:

```python
import asyncio
from app.ingest import promote, staff_sources as ss
from app.ingest.sources import SOURCES

url = "https://staff-sources.sangam.invalid/0123456789ab"
kept, held = ss.hold_unmarked([
    {"concept": "partner", "evidence": "[source:42#Sheet Two!F7] B7='Kestrel Foundation' · F7=7.5", "source_url": url},
    {"concept": "partner", "evidence": "the CSO sheet lists this funder", "source_url": url},
    {"concept": "grant", "evidence": "annual report", "source_url": "https://example.org/r"},
])
assert [f["concept"] for f in kept] == ["partner", "grant"] and len(held) == 1

class Conn:
    def __init__(self, rows): self.rows = rows
    async def execute(self, sql, params=()):
        rows = self.rows
        class C:
            async def fetchall(s): return rows
            async def fetchone(s): return rows[0]
        return C()

assert asyncio.run(promote._staff_datasets(Conn([{"id": 41, "source_url": url}]),
                                           [{"source_url": url}])) == {url: 41}
calls = []
async def ensure(*a, **k): calls.append(k); return 1, "added"
promote.ensure_document = ensure
doc = type("D", (), {"source_url": url, "title": "t", "source_name": None, "as_of": None, "doc_type": "annual_report"})()
promote._validated = lambda findings, concept, report: [doc] if concept == "document" else []
by_url = asyncio.run(promote._write_documents(
    Conn([{"slug": "kestrel-foundation", "id": 41, "source_url": url}]), {"researched_at": None},
    [{"concept": "document", "source_url": url}], promote.Owner.funder(1), {"written": {}, "held": []}))
assert calls == [] and by_url == {url: 41}
assert "cleared" in SOURCES["ffrh_funder_datasets"].basis
print("ok")
```

Then existing suites `tests/test_ingest.py tests/test_sql_catalog.py tests/test_storage.py` pass; ruff
on touched files.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/ingest/staff_sources.py backend/app/ingest/promote.py backend/app/ingest/data/sources/funders.json backend/app/agent/tools/sql/catalog.py
git commit -m "feat(ingest): promote facts read from a staff workbook

A finding at a staff URL links to the dataset's private row and never creates a
public one; a staff finding without its cell marker is held. The FFRH basis
records that its figures are cleared for display; the catalog names
source_dataset rows.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The skills

**Files:** modify `backend/app/ingest/skills/funder-intake-research/SKILL.md`,
`backend/app/ingest/skills/ngo-credential-research/SKILL.md`, `docs/SKILLS.md`.

Edits, not a rewrite: fields 1–11 of the funder skill stay as they are, so plan B's
`eligibility_guideline` finding, its `statutory_restatement` / `own_bar` / `disqualifiers` fields and
"one finding per page" are untouched (I3). No real names, file names or figures anywhere (D9).

- [ ] **Step 1: Funder skill — description.** Replace the `description:` line with (one line):

```yaml
description: Use when someone names one or more companies, corporate foundations, trusts or grantmakers and wants to know where their CSR money goes and what it would take to reach it. Sets the source order — statutory CSR filings under the corporate filer first (staff workbooks, via read_source_rows), then the funder's own publications, then recipient-side records — and pulls ten fields per funder in intake order: route and whether it is live, the receiving legal entity, grantmaker or implementer, eligibility split into statutory restatement and the funder's own bar, the document checklist verbatim, hard disqualifiers, district-level geography, grant size and co-funding, live call or historical disclosure, provenance with access state; plus the open call when field 9 found one, and the rule for classifying spend lines. Raw field-value-source only; no verdicts, no scoring. Not for an organisation that receives money — use ngo-credential-research. Not for one fact already in the catalog — funder_dossier answers that.
```

Count it (1018 as written): `$PY -c "import re,sys;t=open(sys.argv[1]).read();print(len(re.search(r'^description: (.*)$',t,re.M).group(1)))" <file>` → must be ≤ 1024.

- [ ] **Step 2: Funder skill — "Where to look".** Insert before `## The rules that hold for all ten`:

```markdown
## Where to look, in this order

The order is strength of evidence for money, not convenience. The researcher's STEP 1
confirmation search always comes first; this is the order after it.

1. **Statutory CSR filings for the corporate entity.** The filer carries the Section 135
   obligation — often the parent company, not the foundation that runs the programmes.
   - Read them with `read_source_rows`, under the filer's registered name, then the foundation's.
   - Record the filer as the parent and the foundation as its child (`funders.parent_id`). Never merge them.
   - Per fiscal year, the company-level figures (average net profit, prescribed CSR, spent,
     local-area spent) go to `funder_csr_years`, once per company-year.
   - Each project line goes to `funder_activity` with `kind = 'spend'`: project, filed sector,
     state, district, outlay, amount spent, implementation mode, and the partner when named.
2. **The funder's own publications** — foundation and parent annual reports and the CSR annexure,
   CSR policy and annual action plan, impact-assessment report, BRSR. The funder's own programme
   split ("₹X on programme A this year") is a `kind = 'programme'` row per component per year —
   never spread across filing lines, never added to them.
3. **Recipient-side records** — the staff CSO workbook and recipients' own annual reports — for
   grant amounts per partner, which funders rarely publish. Each is a `partner` finding for the
   funder: the recipient as `partner_name`, the amount as printed with its unit.
   - **An exact fiscal year** (`2023-24`) gives that fiscal year and the amount.
   - **A range** (`2021–2024`, `2023-26`, `2022-2025 (Closed)`) gives the **last** fiscal year of
     the range — the one ending in its closing year — and **no amount**; the range is quoted in
     the evidence. A multi-year figure on one year's line would misstate it.
   - **No closing year** (`Post 2022`, `Ongoing`): no finding; name it in the summary.
   - Partner findings are saved in a **funder** research run; an NGO run does not write them.

### Reading the staff workbooks

`read_source_rows` returns rows as `cell=value` with a `[source:<document>#<sheet>!<cell>]`
marker. Cite the cell that holds the fact. The dataset's `source_url` (a `.invalid` address) is
cited, never fetched. The tool does not convert units; these notes say how each kind of sheet reads.

- **Filing exports (`mca_csr`).** One row per project line per fiscal year; amounts in **crore**.
  The filer's company-level figures repeat on every project line of a year — take them once. Where
  two columns share the header `State`, the left one is the filer's registered state, the right
  one the project's. One export has a sheet per fiscal year (pass the year as `sheet`); the other
  has one sheet with a fiscal-year column and a group-company column beside the filer.
- **The CSO workbook (`ffrh_funder_datasets`)** has three sheets:
  - a **profile sheet**, one row per CSO, headers on row 2 — the CSO's own account, so `claimed`;
  - a **funder-details sheet in side-by-side blocks**, one block per CSO: the CSO's name in row 1
    above its block, the block's headers in row 2. A funder row belongs to the CSO named in row 1
    at or left of its columns. Amounts are headed ₹ but a cell may carry its own unit
    (`<n> Lakhs`, `<n>Cr`, `<n>,<nn>,<nnn>`): the cell's unit wins. A cell that is not a number
    ("Not disclosed", "<n> and materials") has no amount;
  - a **funders-and-partners sheet in numbered sections**, one per CSO, each with a funders table
    and a partners table; amounts in **lakh**. The note in cell A2 states the unit and caveats —
    read it. The type column uses codes D (domestic), F (foreign), G (government), CSR (corporate
    CSR). The tool shows the section heading and the table's header row with each match.
- Contact columns are removed by the tool, by design.

```

- [ ] **Step 3: Funder skill — the rules.** In `## The rules that hold for all ten`:
  - first rule's opening sentence becomes `**Every value carries its exact source. Including "not stated".** A URL, or a staff workbook's cell marker.`;
  - the aggregator rule's last sentence becomes `Only the funder's own domain, a primary document it hosts, or a staff workbook — the statutory filing or the recipient's own record, held privately.`

- [ ] **Step 4: Funder skill — classification.** Insert before `## When a source will not open`:

```markdown
## Classifying a spend line: domain and theme

Every domain and theme on a line is an **inference**. Record it as one.

- **Classify by the project name and the named partner**, not the Schedule VII sector filed.
  Filings misfile often.
- **A domain, always** — one of five: livelihoods, health, education, **environment**
  (sustainability, conservation, animal welfare that is not a livelihood programme), **others**
  (relief, sports, administration, unlabelled lines, lines listing several sectors).
- **A theme only as far as the evidence goes**: a sub-theme when the project or partner points to
  one, a theme when only the broad area is clear, none otherwise. Environment and others have none.
- **Record what it rests on**: `classified_by` (`filed_sector` only where unambiguous,
  `project_name`, `partner`, or `report`) and a one-line `classification_note` quoting the
  evidence. Leave `classification_confirmed` false.
- **The filed sector is stored as filed** in `csr_sector_id`, whatever the classification says.
- A `programme` row is classified the same way, `classified_by = 'report'`.
```

  Update `## What this skill does not do`'s last sentence to: `It produces ten cited fields per funder, the classified lines, and any open call it found, and stops.`

- [ ] **Step 5: NGO skill (I8, M5).**
  (a) Replace the two-line rule (it wraps exactly like this):

```markdown
**Never cite an aggregator.** Only the organisation's own domain, or a
primary document it has published.
```

  with:

```markdown
**Never cite an aggregator.** Only the organisation's own domain, a primary
document it has published, or the staff CSO workbook below.
```

  (b) Insert before `## FCRA is not part of this chain`:

```markdown
## A staff source: the CSO workbook

Sangam holds an internal workbook on partner CSOs, shared under partner permission. Read it with
`read_source_rows` and the organisation's name, after the confirmation search.

- **Cite the cell.** Each row carries a `[source:<document>#<sheet>!<cell>]` marker; a finding uses
  the dataset's `source_url` and `source_name` printed by the tool. Never fetch that URL.
- **It is the organisation's own account.** Every profile value is `claimed`. A registration number
  written there is a lead to the certificate, not the certificate.
- **Its funder sheets name who funds it**, by year. Name them in your summary — an NGO run does not
  write partner findings. The amounts are saved as `partner` findings in a **funder** research run
  for each funder (`funder-intake-research` has the year and unit rules).
- Contact details are not in what the tool returns, by design.
```

- [ ] **Step 6: `docs/SKILLS.md`.** After the paragraph ending `…one mapping onto the catalog, one report, either kind.` add:

```markdown
Both "what to pull" skills name `read_source_rows`, the researcher's reader for the staff
workbooks, and the funder skill carries the per-sheet layout and unit notes the tool does not
apply. That is detail on a tool the researcher's prompt already names. Neither skill names a
funder, a CSO or a file.
```

- [ ] **Step 7: Verify (throwaway).** Description count ≤ 1024 (Step 1 command); `pytest tests/test_harness.py`
(frontmatter tests); and a grep that no invented or real proper name slipped in:

```bash
grep -nE "Kestrel|Heron|Egret|\.xlsx|[0-9]+\.[0-9]+ ?(Lakhs?|Cr)" backend/app/ingest/skills/*/SKILL.md docs/SKILLS.md   # no output
```

Read both skills top to bottom once: the section order is "Where to look" → rules → the ten →
classification → when a source will not open.

- [ ] **Step 8: Commit.**

```bash
git add backend/app/ingest/skills/funder-intake-research/SKILL.md backend/app/ingest/skills/ngo-credential-research/SKILL.md docs/SKILLS.md
git commit -m "docs(skills): source order, staff sheet notes, classification as inference

The funder skill reads filings under the corporate filer first, explains each
staff sheet's layout and unit, saves a range of years as its last year with no
amount, and classifies every spend line with its basis. The NGO skill reads the
CSO workbook and leaves partner amounts to a funder run. Generic throughout.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Verification, then STOP before staging

**Files:** modify `.gitignore`.

- [ ] **Step 1: Ignore spreadsheets.** Append to `.gitignore`:

```gitignore

# Staff workbooks are confidential and live only in the private staff-sources bucket.
*.xlsx
*.xls
*.xlsm
```

- [ ] **Step 2: Verify the branch.**

```bash
git ls-files '*.xlsx' '*.xls' '*.xlsm'                                # no output
git log -p master..HEAD | grep -nE "Kestrel|Heron|Egret"             # only the plan's scratch snippets, no code
cd $WT/backend && PYTHONPATH=.:.. $PY -m pytest -p no:cacheprovider -q -m "not integration"   # all pass
$RUFF check <every backend file this branch touched>                 # clean
# frontend tsc + lint (Environment)
ls backend/tests | grep -c scratch                                   # 0
```

- [ ] **Step 3: Commit.**

```bash
git add .gitignore
git commit -m "chore: keep spreadsheets out of the repo

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: STOP.** Everything below is the user's, in this order. Do not run any of it.

  - **G1. Back up staging** — `make db-backup ENV=staging` or the Supabase dashboard.
  - **G2. Confirm the project's global Storage upload limit is ≥ 100 MB** (Supabase dashboard →
    Storage settings). If it cannot be raised, save the largest export as two smaller workbooks
    offline and upload each as its own file.
  - **G3. Plan B's 0031 first (I4).** If staging is not yet at 0031, run plan B's own pre-flight
    and stop procedure (its data-dependent stops), then `make migrate ENV=staging` up to 0031 only
    after it passes. 0032 must not ride along with an unchecked 0031.
  - **G4. 0032** — `make migrate ENV=staging`; then check
    `SELECT policyname FROM pg_policies WHERE schemaname='storage' AND policyname='staff_sources_staff_read'`
    (a NOTICE instead means service-role only, which is acceptable) and
    `SELECT id, public, file_size_limit FROM storage.buckets WHERE id='staff-sources'`.
  - **G5. Upload the three files** (the user supplies the paths):

```bash
make staff-source ENV=staging KEY=mca_csr FILE="<path to the analytics export>"
make staff-source ENV=staging KEY=mca_csr FILE="<path to the filing subset>"
make staff-source ENV=staging KEY=ffrh_funder_datasets FILE="<path to the CSO workbook>"
```

    Expected: three `added: document N · staff-sources/<key>/<12 hex>.xlsx · <n> sheets` lines. Then:

```sql
SELECT id, source_name, content_md IS NULL AS empty, is_public, org_id, title FROM documents
WHERE doc_type = 'source_dataset' ORDER BY id;     -- 3 rows; empty t, is_public f, org_id NULL, no file name in title
```

  - **G6. Acceptance run (spec §5, costs model calls, writes staging)** — in the Import chat as
    staff, research and push one corporate funder present in both filing exports, choosing one with
    a modest number of project lines (large filers exceed the researcher's budget and one
    `save_research` payload — I7). Then, counts only, no names or figures, in the PR:
    1. **Lines written vs held (I7).** Per fiscal year, the project lines the tool returned for the
       filer equal `written` + `held` for `csr_spend` in promote's report; every held line has a
       reason (same-key lines are deduplicated by `_row_identity` by design). Do not compare sums.
    2. `SELECT count(*) FROM funder_activity WHERE funder_id = <parent> AND kind = 'spend' AND (domain_tag_id IS NULL OR classified_by IS NULL)` → 0.
    3. `… AND theme_tag_id IS NOT NULL AND coalesce(classification_note, '') = ''` → 0.
    4. `kind = 'programme'` rows, if any, show in `funder_dossier` beside the filing figures and
       are not part of check 1.
    5. Relief, sports, administration, unlabelled and multi-sector lines carry `others`.
    6. For a funder on the CSO sheets: `kind = 'partner'` rows with an amount exist only for rows
       with an exact fiscal year, each equal to the printed figure × its unit once; range rows have
       the last fiscal year and no amount.
    7. `held` lists any staff finding without its marker; `SELECT count(*) FROM funder_activity a
       JOIN documents d ON d.id = a.document_id WHERE d.doc_type = 'source_dataset' AND NOT a.is_public` → 0,
       while every `source_dataset` row stays `is_public = false`.

- [ ] **Step 5: PR description must say** — staff-only enforcement as built (RLS `documents_read`,
`readable_document`, the route guard, `require_staff` on Import, the bucket policy failing closed;
the tool runs as owner, so the Import route is its gate); where data goes (tool output reaches the
model provider, the checkpoint tables and, with tracing on, Langfuse; the app logs counts only); the
spec refinements (no layout profiles — D13 superseded; the cell citation with `!`; the `.invalid`
URL; file-name identity; the 100 MB bucket; range rows saved as last year with no amount; the tool
on the researcher); and that 0032 is renumbered at merge if needed.

---

## Self-review

| Requirement | Task |
|---|---|
| D8 private bucket, staff SELECT policy, `split()`, download guard | 2 |
| §4 one private `source_dataset` row per file, no content, script with service key | 3 |
| I1 re-upload replaces object and row; I6 staging only | 3 |
| §4 `read_source_rows`: every sheet, aliases, cited cells, never raises, no values in errors, contact denylist, size cap | 4 |
| Tool registered on the researcher, named in its prompt and `instructions.md`, labelled, documented | 4 |
| M1 cite never fetch; M4 after STEP 1; I2 ranges → last FY, no amount | 4, 6 |
| D14 facts public, files private; unmarked staff findings held; FFRH basis; M3 catalog | 5 |
| D9 generic skill; I3 plan B eligibility wording kept; source order; classification (D11, D12) | 6 |
| I8 partner facts in a funder run; M5 anchors as they really wrap | 6 |
| Real files never committed | 7 |
| I4 0031 before 0032 after backup; I7 acceptance by lines written vs held | 7 (STOP list) |

---

## Pending: prior research from org-grant-intelligence (D16) — not built in this PR

Added to the earlier plan by febf172 (Vinod Rajasekaran) while this plan was being rewritten and built. Carried here verbatim for a follow-up PR; its references to layout profiles and Task numbers are to that earlier plan.

### D16 global constraints

- **Prior research is read pinned, from one repository, and from nowhere else on that host (D16).**
  - The research fetch tools (`read_page`, `fetch_document`) may read `https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/<commit>/<path>`, where `<commit>` is 40 or 7 lowercase hex characters.
  - Anything else on `raw.githubusercontent.com` is refused. That covers other repositories, a branch or `HEAD`, `refs/…`, a `..` or empty segment, `%2e` / `%2f` / `%5c`, a query string, a port and userinfo.
  - `github.com`, `api.github.com` and the GitHub contents API are not added.
  - The pin Sangam's seed was copied from is `414cd6968765bcfff758632797dcbb8d00363ab2` (`414cd69`, `seed/data/README.md`). It lives in `prior_research.PINNED_COMMIT`, the registry `basis` and the researcher's prompt. The skill names no commit.
  - Sangam never writes to the repository.
- **A dossier fact is `claimed` and never outranks a primary source.** There is no `evidenced`/`claimed` column on funder findings (`FindingBase` has `confidence` and `basis`). This PR does not add one. A dossier finding is identified by its `source_url`, the pinned raw URL that carries the commit. Promotion stamps its `source_name` as `org_grant_intelligence`. A non-dossier finding with the same key replaces it at promotion, and a disagreement is reported in `held`. Both findings stay in `entity_research.findings`. This ranking holds **within one research run**. Across runs, the newest research wins, as it does for every source today. A later run that saves only a dossier value would overwrite a stored primary-sourced row. The prompt asks for a re-read on every run, and the PR says so.
- **Coordination with the CSO plan.** The companion CSO spec (C14) uses the same repository and rule, and accepts either registry shape. Whichever PR lands second drops its own copy of the `internal_research` enum value and the `org_grant_intelligence` entry, and keeps the other's. `manual_aggregator` (C8) belongs to the CSO plan. This plan's skill refers to it only conditionally: "where the registry lists it under `manual_aggregator`".

### Task 10A: The research repository as a source, readable only pinned (D16)

**Files:**
- Create: `backend/app/ingest/prior_research.py`
- Modify: `backend/app/ingest/sources.py`, `backend/app/ingest/data/sources/ngos.json`
- Modify: `backend/app/ingest/access.py`, `backend/app/ingest/tools/research_tools.py`
- Modify: `frontend/features/ingest/components/SourcePanel.tsx`
- Modify: `docs/INGEST.md`
- Test: `backend/tests/test_prior_research.py` (create)

**Interfaces:**

```python
# prior_research.py
SOURCE_KEY = "org_grant_intelligence"
HOST = "raw.githubusercontent.com"
REPO = "project-tech4dev/org-grant-intelligence"
PINNED_COMMIT = "414cd6968765bcfff758632797dcbb8d00363ab2"
def pinned(url: str | None) -> tuple[str, str] | None        # (commit, path in the repository)
def is_prior_research_url(url: str | None) -> bool
def refusal(url: str) -> str | None                          # None when readable
# sources.py
AccessRule.INTERNAL_RESEARCH = "internal_research"
```

**Registry: replace, not widen.** `hand_vetting_sheets` is replaced by `org_grant_intelligence`, for three reasons:
- **The entry now covers the whole repository.** That includes the funder and CSO dossiers, `hand-vetting/` and `deep-agent-app/downloads/`. A key that names one folder would mislead every reader of `list_import_sources`.
- **Nothing reads the old key.** `ngos.json:204` is its only occurrence. `seed/data/*.json` cites the repository with `source_name: "hand-vetting"`, which is a citation label, not a registry key, and stays.
- **The entry must gain a host.** With `host: ""`, `rule_for_host("raw.githubusercontent.com")` matches nothing, so every repository on that host falls through to robots.txt. That is the exact hole this task closes.

The companion CSO spec (C14) accepts either shape, and its plan uses this key and rule.

**Why `check_url` needs a branch.** Today any registered non-dispatchable source is refused, so the allowed path would be refused too. The new branch runs before that check and before robots.txt. On this host the path rule is the whole permission. `raw.githubusercontent.com/robots.txt` returns 404, which RFC 9309 reads as allow-all, so robots.txt could never refuse a foreign repository.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_prior_research.py`:

```python
"""Prior research (spec D16): the team's research repository, read only at a pinned commit."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx
import pytest

from app.ingest import access, prior_research
from app.ingest.sources import SOURCES, AccessRule, rule_for_host
from app.ingest.tools import research_tools

NOW = datetime(2026, 10, 7, tzinfo=UTC)
SHA = "0123456789abcdef0123456789abcdef01234567"  # invented; tests never use the real pin
BASE = "https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence"
DOSSIER = f"{BASE}/{SHA}/Funder/kestrel-foundation/Kestrel_Foundation_Profile.md"


@pytest.fixture(autouse=True)
def no_robots(monkeypatch):
    """Nothing on this host may depend on robots.txt: the path rule is the whole permission."""

    async def consulted(*a, **k):
        raise AssertionError("robots.txt was consulted for the research repository's host")

    monkeypatch.setattr(access, "_robots_allows", consulted)


def _serve(monkeypatch, body: str, content_type: str, seen: list[str]) -> None:
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    def client(*a, **k):
        return real(*a, transport=httpx.MockTransport(handler), **k)

    monkeypatch.setattr(research_tools.httpx, "AsyncClient", client)


class TestTheRegistry:
    def test_internal_research_is_one_source_on_one_host(self):
        found = [s for s in SOURCES.values() if s.access_rule is AccessRule.INTERNAL_RESEARCH]
        assert [s.key for s in found] == [prior_research.SOURCE_KEY]
        assert found[0].host == prior_research.HOST
        assert not found[0].dispatchable

    def test_the_hand_vetting_key_is_replaced(self):
        assert "hand_vetting_sheets" not in SOURCES
        assert {"funder", "ngo", "rfp"} <= {c.value for c in SOURCES["org_grant_intelligence"].categories}

    def test_the_host_resolves_to_the_repository_rule(self):
        rule, source = rule_for_host("raw.githubusercontent.com")
        assert rule is AccessRule.INTERNAL_RESEARCH and source.key == "org_grant_intelligence"

    def test_the_pin_is_a_full_commit_and_the_basis_names_it(self):
        assert re.fullmatch(r"[0-9a-f]{40}", prior_research.PINNED_COMMIT)
        assert prior_research.PINNED_COMMIT in SOURCES["org_grant_intelligence"].basis


class TestOnlyAPinnedPathIsReadable:
    def test_pinned_returns_the_commit_and_the_path(self):
        assert prior_research.pinned(DOSSIER) == (SHA, "Funder/kestrel-foundation/Kestrel_Foundation_Profile.md")

    def test_a_github_page_is_not_a_pinned_url(self):
        assert prior_research.pinned(f"https://github.com/project-tech4dev/org-grant-intelligence/blob/{SHA}/a.md") is None

    async def test_a_pinned_dossier_is_readable(self):
        assert await access.check_url(DOSSIER) is None

    async def test_a_short_pin_is_readable(self):
        url = f"{BASE}/0123abc/deep-agent-app/downloads/Trust_Template_Example.pdf"
        assert await access.check_url(url) is None

    @pytest.mark.parametrize("url", [
        f"https://raw.githubusercontent.com/someone-else/org-grant-intelligence/{SHA}/Funder/x/a.md",
        f"https://raw.githubusercontent.com/project-tech4dev/another-repo/{SHA}/Funder/x/a.md",
        f"{BASE}/main/Funder/x/a.md",
        f"{BASE}/HEAD/Funder/x/a.md",
        f"{BASE}/refs/heads/main/Funder/x/a.md",
        f"{BASE}/{SHA}/../../another-repo/main/a.md",
        f"{BASE}/{SHA}/%2e%2e/%2e%2e/another-repo/main/a.md",
        f"{BASE}/{SHA}/Funder%2Fx/a.md",
        f"{BASE}/{SHA}//a.md",
        f"{BASE}/{SHA}/Funder/x/a.md?token=1",
        f"{BASE}/{SHA.upper()}/a.md",
        f"{BASE}/{SHA}",
        f"http://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/{SHA}/a.md",
        f"https://raw.githubusercontent.com:8443/project-tech4dev/org-grant-intelligence/{SHA}/a.md",
    ])
    async def test_anything_else_on_the_host_is_refused(self, url):
        out = await access.check_url(url)
        assert out is not None
        assert "pinned" in out and prior_research.PINNED_COMMIT in out


class TestReadingTheRepository:
    async def test_a_dossier_is_read_as_its_text(self, monkeypatch):
        seen: list[str] = []
        body = "# Kestrel Foundation\n\n| Field | Value |\n|---|---|\n| CSR spent FY2023-24 | 1.2 crore |\n"
        _serve(monkeypatch, body, "text/plain; charset=utf-8", seen)
        out = await research_tools.read_page.ainvoke({"url": DOSSIER})
        assert out == body and seen == [DOSSIER]

    async def test_read_page_refuses_a_branch_path_before_any_request(self, monkeypatch):
        seen: list[str] = []
        _serve(monkeypatch, "x", "text/plain", seen)
        out = await research_tools.read_page.ainvoke({"url": f"{BASE}/main/Funder/x/a.md"})
        assert out.startswith("REFUSED:") and seen == []

    async def test_fetch_document_refuses_another_repository(self, monkeypatch):
        seen: list[str] = []
        _serve(monkeypatch, "%PDF-1.4", "application/pdf", seen)
        url = f"https://raw.githubusercontent.com/project-tech4dev/another-repo/{SHA}/a.pdf"
        out = await research_tools.fetch_document.ainvoke({"url": url})
        assert out.startswith("REFUSED:") and seen == []
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_prior_research.py -q`
Expected: `ImportError: cannot import name 'prior_research' from 'app.ingest'`.

- [ ] **Step 3: The access rule**

In `backend/app/ingest/sources.py`, in `AccessRule`, after `PARTNER_PERMISSION = "partner_permission_internal"`:

```python
    # The team's own research repository, read by the research tools at a pinned commit only
    # (prior_research.py, spec D16). Never dispatched: no adapter runs against it.
    INTERNAL_RESEARCH = "internal_research"
```

In `_STRICTNESS`, insert `AccessRule.INTERNAL_RESEARCH,` directly after `AccessRule.REFERENCE_ONLY,`. It must be in the tuple, because `rule_for_host` calls `_STRICTNESS.index()` and raises `ValueError` on a missing rule. It is the only product on its host, so its position decides nothing today. Ranking it below `PARTNER_PERMISSION` means a partner-permission product added to the same host would still win.

`DISPATCHABLE` is not touched.

- [ ] **Step 4: The registry entry**

In `backend/app/ingest/data/sources/ngos.json`, replace the whole `hand_vetting_sheets` object with:

```json
    {
      "key": "org_grant_intelligence",
      "name": "org-grant-intelligence research repository",
      "host": "raw.githubusercontent.com",
      "access_rule": "internal_research",
      "categories": [
        "ngo",
        "funder",
        "rfp"
      ],
      "yields": [
        "org",
        "funder",
        "rfp"
      ],
      "basis": "The team's own earlier research, public on GitHub as project-tech4dev/org-grant-intelligence: funder and CSO dossiers, the hand-vetting sheets, and proposal templates and RFPs under deep-agent-app/downloads. Read only as raw files pinned to a commit (Sangam's seed was copied at 414cd6968765bcfff758632797dcbb8d00363ab2), never a branch and never another repository on this host. Each fact carries the dossier's cited source and stays claimed until that source is re-read.",
      "robots_checked_at": null
    },
```

The object stays in `ngos.json`, where the old one was, so the CSO plan finds it in the same place.

- [ ] **Step 5: `prior_research.py`, access half**

Create `backend/app/ingest/prior_research.py`:

```python
"""Prior research: the team's earlier research repository, read at a pinned commit (spec D16).

Pure: no pool, no network, no settings. access.check_url hands every URL on the repository's host
to `refusal`, because raw.githubusercontent.com serves every public repository and a rule keyed on
the host alone would let the researcher read any of them. Only a file of this repository at a
commit is a source a citation can point at: a branch path is different text on a different day.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

SOURCE_KEY = "org_grant_intelligence"
HOST = "raw.githubusercontent.com"
REPO = "project-tech4dev/org-grant-intelligence"
# The commit Sangam's seed data was copied from (seed/data/README.md). Moving it is a reviewed change.
PINNED_COMMIT = "414cd6968765bcfff758632797dcbb8d00363ab2"

_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{7}")
# An encoded dot, slash or backslash is a path the server will normalise into something this
# check never saw. httpx removes literal dot segments before sending, so `..` is refused too.
_ESCAPES = re.compile(r"%(2e|2f|5c)", re.IGNORECASE)


def pinned(url: str | None) -> tuple[str, str] | None:
    """(commit, path in the repository) when `url` is one file of the repository at a commit."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != HOST:
        return None  # netloc, not hostname: a port or userinfo is refused here too
    if parsed.params or parsed.query or parsed.fragment:
        return None
    if "\\" in parsed.path or _ESCAPES.search(parsed.path):
        return None
    segments = parsed.path.split("/")
    # '', owner, repo, commit, *path
    if len(segments) < 5 or segments[0] != "" or "/".join(segments[1:3]) != REPO:
        return None
    commit, path = segments[3], segments[4:]
    if not _COMMIT.fullmatch(commit):
        return None
    if any(part in ("", ".", "..") for part in path):
        return None
    return commit, "/".join(path)


def is_prior_research_url(url: str | None) -> bool:
    return pinned(url) is not None


def refusal(url: str) -> str | None:
    """None when `url` may be read; otherwise the reason, with the form that would be allowed."""
    if pinned(url) is not None:
        return None
    return (
        f"{HOST} is registered as internal_research for one repository only, and only pinned: "
        f"https://{HOST}/{REPO}/<commit>/<path>, with a 40-character commit. {url} is another "
        f"repository, a branch, or a path that is not a plain file. Rewrite a github.com link to the "
        f"pinned form, e.g. https://{HOST}/{REPO}/{PINNED_COMMIT}/<path>. Never read a branch."
    )
```

- [ ] **Step 6: The `check_url` branch**

In `backend/app/ingest/access.py`:
- change `from app.ingest.sources import rule_for_host` to `from app.ingest.sources import AccessRule, rule_for_host`;
- add `from app.ingest import prior_research`;
- directly after `source = found[1] if found else None`, insert:

```python
    if source is not None and source.access_rule is AccessRule.INTERNAL_RESEARCH:
        # The team's own research repository (D16). Its registry entry owns the whole host, so
        # every other repository there is refused here, and so is a branch: only a file at a
        # commit is a citable, unchanging source. robots.txt is not the question - the host
        # serves none, which RFC 9309 reads as allow-all - so the path rule is the whole permission.
        return prior_research.refusal(url)
```

`test_internal_research_is_one_source_on_one_host` is what keeps this branch from silently covering a second `internal_research` source it was not written for.

- [ ] **Step 7: `read_page` returns a raw text file as text**

`raw.githubusercontent.com` serves a dossier as `text/plain; charset=utf-8`. `trafilatura.extract` looks for an HTML article and drops most of a markdown table. In `backend/app/ingest/tools/research_tools.py`, in `read_page`, replace:

```python
    text = trafilatura.extract(response.text, url=url) or ""
```

with:

```python
    content_type = response.headers.get("content-type", "").lower()
    if content_type.startswith(("text/plain", "text/markdown")):
        # Already text (the prior-research dossiers are markdown served raw). trafilatura looks
        # for an HTML article and would drop most of a table.
        text = response.text
    else:
        text = trafilatura.extract(response.text, url=url) or ""
```

The truncation at `MAX_CONTENT_CHARS` below it applies unchanged.

- [ ] **Step 8: Label the rule**

In `frontend/features/ingest/components/SourcePanel.tsx`, in `RULE_TEXT`, after `partner_permission_internal: "Partner data",`:

```ts
  internal_research: "Team research (pinned)",
```

- [ ] **Step 9: Document it**

In `docs/INGEST.md`, in "## Sources: access rules are config, not comments":

(a) In the category table, change the `rfp` row to `| rfp | 12 | 2 |`. The total stays 74: one entry is replaced, and it gains the `rfp` category. Recount with:

```bash
cd backend && python -c "import collections,json;c=collections.Counter();[c.update(s['categories']) for f in ('funders','ngos','rfps','media') for s in json.load(open(f'app/ingest/data/sources/{f}.json'))['sources']];print(sum(1 for f in ('funders','ngos','rfps','media') for _ in json.load(open(f'app/ingest/data/sources/{f}.json'))['sources']),dict(c))"
```

Expected: `74 {'funder': 32, …, 'ngo': 21, 'rfp': 12, 'media': 26}` (key order may differ).

(b) After the paragraph that begins ``` `read_page` and `fetch_document` check twice before fetching```, add:

```markdown
**One host is decided by path, not by robots.txt.** `raw.githubusercontent.com` belongs to
`org_grant_intelligence` (`internal_research`), the team's earlier research repository
(`app/ingest/prior_research.py`). `check_url` hands every URL on that host to
`prior_research.refusal`. It allows a file of that repository at a 40- or 7-hex commit and refuses
everything else: another repository, a branch or `HEAD`, a dot segment, an encoded slash or dot,
a query string, a port. A branch is refused because a citation has to point at text that does not
change. The rule is not dispatchable, so it counts among the 51 held: no adapter reads the
repository, and only the researcher's fetch tools do, one file at a time. Sangam never writes
to it.
```

- [ ] **Step 10: Run the tests**

Run: `cd backend && pytest tests/test_prior_research.py tests/test_ingest.py tests/test_storage.py -q -m "not integration" && ruff check .`
Expected: all pass, including `TestSourcesGateOnAccessRules` (the registry still self-checks, nothing new is dispatchable) and `test_the_strictest_rule_on_a_host_wins`.

Run: `cd frontend && npm run lint && npm run build`
Expected: clean.

- [ ] **Step 11: Commit**

```bash
git add backend/app/ingest/prior_research.py backend/app/ingest/sources.py backend/app/ingest/data/sources/ngos.json backend/app/ingest/access.py backend/app/ingest/tools/research_tools.py frontend/features/ingest/components/SourcePanel.tsx docs/INGEST.md backend/tests/test_prior_research.py
git commit -m "feat(ingest): the research repository as a source, read only pinned

org_grant_intelligence replaces hand_vetting_sheets and covers the whole
repository under a new rule, internal_research, which is never dispatched.
The entry owns raw.githubusercontent.com, so check_url refuses every other
repository there, every branch and every path that is not a plain file at a
commit. read_page returns a raw markdown file as its text.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10B: Promotion ranks a dossier below the primary source it cites (D16)

**Files:**
- Modify: `backend/app/ingest/prior_research.py` (add `rank_key`, `rank`)
- Modify: `backend/app/ingest/promote.py`
- Test: `backend/tests/test_prior_research.py`

**Interfaces:**

```python
def rank_key(f: dict) -> tuple
def rank(findings: list[dict]) -> tuple[list[dict], list[str]]   # (to promote, held lines)
```

**Why this is needed.** Within one payload `_write_facts` holds the second of two findings with the same `_row_identity` as "two findings resolve to the same row". So whichever finding comes first wins, and that is often the dossier, which the researcher reads first. `rank` runs before any writer. It is pure and works on the unresolved dict, because `_row_identity` needs ids that do not exist yet. It also covers `csr_year` and `identity`, which never reach `_write_facts`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_prior_research.py`:

```python
PRIMARY = "https://kestrel.example/csr-annexure-2023-24.pdf"


def _year(url, prescribed, unit="crore", fy="FY2023-24"):
    return {"concept": "csr_year", "fiscal_year": fy, "prescribed_csr": {"value": prescribed, "unit": unit},
            "evidence": "The CSR annexure states the prescribed CSR obligation for the year.",
            "source_url": url, "confidence": "high"}


class TestAPrimarySourceOutranksTheDossier:
    def test_a_dossier_fact_alone_is_promoted_and_labelled(self):
        kept, held = prior_research.rank([_year(DOSSIER, 1.2)])
        assert kept == [{**_year(DOSSIER, 1.2), "source_name": "org_grant_intelligence"}]
        assert held == []

    def test_a_primary_fact_outranks_the_dossier(self):
        primary = _year(PRIMARY, 1.2)
        kept, held = prior_research.rank([_year(DOSSIER, 1.2), primary])
        assert kept == [primary] and held == []

    def test_a_disagreement_is_reported_and_both_are_kept(self):
        primary = _year(PRIMARY, 1.35)
        findings = [_year(DOSSIER, 1.2), primary]
        kept, held = prior_research.rank(findings)
        assert kept == [primary]
        assert len(held) == 1
        assert "prescribed_csr" in held[0] and PRIMARY in held[0] and DOSSIER in held[0]
        assert len(findings) == 2  # the research record itself is never edited

    def test_a_value_only_the_dossier_states_is_reported_not_dropped(self):
        dossier = {**_year(DOSSIER, 1.2), "average_net_profit": {"value": 60, "unit": "crore"}}
        primary = _year(PRIMARY, 1.2)
        kept, held = prior_research.rank([dossier, primary])
        assert kept == [primary]
        assert len(held) == 1 and "also states average_net_profit" in held[0]

    def test_the_same_amount_in_another_unit_agrees(self):
        kept, held = prior_research.rank([_year(DOSSIER, 120, unit="lakh"), _year(PRIMARY, 1.2)])
        assert [f["source_url"] for f in kept] == [PRIMARY] and held == []

    def test_another_year_is_another_fact(self):
        kept, _ = prior_research.rank([_year(DOSSIER, 1.0, fy="FY2022-23"), _year(PRIMARY, 1.2)])
        assert len(kept) == 2

    def test_one_identity_per_entity(self):
        base = {"concept": "identity", "evidence": "The page names the foundation and its registered office.",
                "confidence": "high"}
        dossier = {**base, "name": "Kestrel Foundation Trust", "source_url": DOSSIER}
        primary = {**base, "name": "Kestrel Foundation", "source_url": "https://kestrel.example/about"}
        kept, held = prior_research.rank([dossier, primary])
        assert kept == [primary] and "name" in held[0]


async def test_promote_writes_the_primary_value(monkeypatch):
    from app.ingest import promote
    from app.ingest.research_records import SCHEMA_VERSION

    seen = {}

    async def capture(conn, row, findings, report):
        seen["findings"] = findings

    monkeypatch.setattr(promote, "_promote_funder", capture)
    primary = _year(PRIMARY, 1.35)
    row = {"slug": "kestrel-foundation", "entity_kind": "funder", "schema_version": SCHEMA_VERSION,
           "findings": [_year(DOSSIER, 1.2), primary]}
    report = await promote.promote(object(), row)
    assert seen["findings"] == [primary]
    assert any("prior-research dossier disagrees" in h for h in report["held"])
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_prior_research.py -q -k "Outranks or promote_writes"`
Expected: `AttributeError: module 'app.ingest.prior_research' has no attribute 'rank'`.

- [ ] **Step 3: `rank`**

In `backend/app/ingest/prior_research.py`, add `from typing import Any` and `from app.ingest.research_records import to_inr` to the imports, then append:

```python
# What says where a finding came from or how it was labelled, not what it states. Two findings
# that differ only here agree.
_PROVENANCE = frozenset({
    "concept", "evidence", "source_url", "source_name", "confidence", "basis", "notes",
    "classified_by", "classification_note", "classification_confirmed",
})
# What names the row a finding is about, before anything is resolved to an id.
_KEY = ("fiscal_year", "program_name", "project_name", "partner_name", "recipient_name", "name",
        "title", "role", "period", "state", "district", "id_type", "kind")
# One row per entity: two of these are the same fact whatever they say.
_ONE_PER_ENTITY = frozenset({"identity"})


def _norm(v: Any) -> Any:
    return " ".join(v.lower().split()) if isinstance(v, str) else v


def _value(v: Any) -> Any:
    if isinstance(v, dict) and "unit" in v:
        return to_inr(v)  # 120 lakh and 1.2 crore agree
    return _norm(v)


def rank_key(f: dict[str, Any]) -> tuple:
    if f.get("concept") in _ONE_PER_ENTITY:
        return (f.get("concept"),)
    return (f.get("concept"), *(_norm(f.get(k)) for k in _KEY))


def rank(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The findings to promote, and a held line for each dossier value a primary source contradicts.

    A finding read from the repository is the dossier's claim, kept as a lead until its own source
    is re-read. It is promoted under source_name = SOURCE_KEY when nothing else states the same
    fact. When a finding from any other source does, that one is written, and a dossier that said
    something different is reported, not silently lost. This filters what promote writes, never
    what research saved: both findings stay in entity_research.findings.
    """
    primary: dict[tuple, dict[str, Any]] = {}
    for f in findings:
        if not is_prior_research_url(f.get("source_url")):
            primary.setdefault(rank_key(f), f)

    kept: list[dict[str, Any]] = []
    held: list[str] = []
    for f in findings:
        if not is_prior_research_url(f.get("source_url")):
            kept.append(f)
            continue
        other = primary.get(rank_key(f))
        if other is None:
            kept.append({**f, "source_name": SOURCE_KEY})
            continue
        differs = sorted(
            k for k in f.keys() & other.keys()
            if k not in _PROVENANCE and (k not in _KEY or f.get("concept") in _ONE_PER_ENTITY)
            and f[k] is not None and other[k] is not None and _value(f[k]) != _value(other[k])
        )
        label = " ".join(str(x) for x in (f.get("concept"), f.get("fiscal_year")) if x)
        if differs:
            held.append(
                f"{label}: the prior-research dossier disagrees with {other['source_url']} on "
                f"{', '.join(differs)}. The primary source is written; the dossier value stays in the "
                f"research record ({f['source_url']})."
            )
        # Fields only the dossier states. Not merged onto the primary row, which would cite the
        # primary URL for a value it never stated; reported, so the claim is not lost in silence.
        only_dossier = sorted(
            k for k in f
            if k not in _PROVENANCE and k not in _KEY and f[k] is not None and other.get(k) is None
        )
        if only_dossier:
            held.append(
                f"{label}: the prior-research dossier also states {', '.join(only_dossier)}, which "
                f"{other['source_url']} does not. Not written, because the row cites that source; "
                f"re-read it from a primary source to store it ({f['source_url']})."
            )
    return kept, held
```

`research_records` imports nothing from `access` or `prior_research`, so there is no import cycle.

- [ ] **Step 4: Wire it into `promote()`**

In `backend/app/ingest/promote.py`, add `from app.ingest import prior_research` to the imports. Directly after the two lines Task 10 inserted (`findings, unmarked = staff_sources.hold_unmarked(findings)` / `report["held"].extend(unmarked)`), insert:

```python
    # A dossier fact loses to the same fact re-read from its own source (D16).
    findings, outranked = prior_research.rank(findings)
    report["held"].extend(outranked)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_prior_research.py tests/test_staff_sources.py tests/test_ingest.py -q -m "not integration" && ruff check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingest/prior_research.py backend/app/ingest/promote.py backend/tests/test_prior_research.py
git commit -m "feat(ingest): a fact re-read from its source outranks the dossier

promote ranks findings before any writer: a finding from the research
repository is promoted as claimed prior research only when nothing else states
the same fact, and a dossier that disagrees with the primary source is reported
in held. The research record keeps both.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10C: A funder's proposal template is a `proposal_template` document (D5, D16)

**Files:**
- Modify: `backend/app/ingest/expectations.py`, `backend/app/ingest/research_records.py`, `backend/app/ingest/records.py`
- Modify: `backend/app/ingest/promote.py`, `backend/app/ingest/brief.py`
- Test: `backend/tests/test_prior_research.py`

**Interfaces:**
- Produces: concept `"proposal_template"` → `ConceptSpec("documents", "Proposal templates", row_filter=("doc_type", "proposal_template"), columns=("title",))`, `ProposalTemplateFinding`, `ProposalTemplateRecord` (`doc_type` ClassVar `"proposal_template"`).
- Consumes: plan (b) Task 13 (`RESERVED_DOC_TYPES`, `ensure_document` keyed on the reserved type) and Task 14 (the `eligibility_guideline` concept this mirrors).

**Why.** Plan (b) reserves `proposal_template` and refuses it on a `document` finding. It also says templates have "no writer yet". The skill cannot tell the researcher to save one until something writes it.

The concept writes one funder-owned `documents` row per URL. It archives the file when `fetch_document` archived it, the same way `_write_documents` does. A generic template, one named by funder type rather than by a funder, has no funder to own it. It is therefore never a finding: the skill keeps it as a reference in the summary.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_prior_research.py`:

```python
TEMPLATE = {"concept": "proposal_template", "title": "Kestrel Foundation grant application form",
            "evidence": "The form is headed 'Kestrel Foundation: Application for CSR Support'.",
            "source_url": "https://kestrel.example/apply/application-form.pdf", "confidence": "high"}


class TestTheTemplateConcept:
    def test_it_owns_template_documents(self):
        from app.ingest.expectations import CONCEPTS, expected_fields

        assert CONCEPTS["proposal_template"].row_filter == ("doc_type", "proposal_template")
        assert {f.name for f in expected_fields("proposal_template")} == {"title", "as_of"}

    def test_a_document_finding_still_cannot_claim_the_type(self):
        from pydantic import ValidationError

        from app.ingest.research_records import DocumentFinding

        with pytest.raises(ValidationError, match="reserved"):
            DocumentFinding(title="Application form", doc_type="proposal_template",
                            evidence="The form is headed with the funder's name.",
                            source_url="https://a.b/c", confidence="high")

    async def test_a_template_is_one_funder_document(self, recording_conn, monkeypatch):
        from app.ingest import promote
        from app.ingest.writer import Owner

        async def not_archived(*a, **k):
            return None

        monkeypatch.setattr(promote.storage, "archived_key", not_archived)
        conn = recording_conn([None, {"id": 31}])
        row = {"slug": "kestrel-foundation", "entity_name": "Kestrel Foundation", "canonical_name": None,
               "researched_at": NOW}
        report = {"held": [], "written": {}}
        await promote._write_facts(conn, row, [TEMPLATE, {**TEMPLATE, "title": "The same form again"}],
                                   Owner.funder(1), {}, {}, report, order=("proposal_template",))
        inserts = [i for i, q in enumerate(conn.sql) if q.startswith("INSERT INTO documents")]
        assert len(inserts) == 1
        assert conn.sql[inserts[0]].startswith("INSERT INTO documents (funder_id,")
        assert conn.params[inserts[0]][0] == 1 and conn.params[inserts[0]][2] == "proposal_template"
        assert report["written"]["documents (proposal_template)"]["added"] == 1
        assert any("same row" in h for h in report["held"])
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend && pytest tests/test_prior_research.py -q -k Template`
Expected: `KeyError: 'proposal_template'`, and the promote test finding no INSERT.

- [ ] **Step 3: Expectations**

In `backend/app/ingest/expectations.py`, after the `eligibility_guideline` entry in `CONCEPTS`:

```python
    # A funder's own application form or proposal template (D5): one documents row per URL, owned
    # by the funder. A template named only by funder type has no owner and is not a finding.
    "proposal_template": ConceptSpec(
        "documents", "Proposal templates",
        row_filter=("doc_type", "proposal_template"), columns=("title",),
    ),
```

`REQUIRED["proposal_template"] = frozenset({"title"})`. In `EXTRA`:

```python
    "proposal_template": (
        Expected(name="as_of", type="text", note="the year or version printed on the form",
                 values=(), required=False),
    ),
```

- [ ] **Step 4: Finding and record**

In `backend/app/ingest/research_records.py`, after `EligibilityGuidelineFinding`:

```python
class ProposalTemplateFinding(FindingBase):
    """A named funder's own proposal template or application form (D5).

    source_url is where the funder publishes it, or the pinned research-repository file when that
    is the only copy left. The evidence quotes what on the form names the funder.
    """

    concept: Literal["proposal_template"] = "proposal_template"
    title: str = Field(min_length=4, description="the form's title as printed")
    as_of: str | None = Field(default=None, description="the year or version printed on the form")
```

Add it to the `Finding` union and to `FINDING_MODELS` (`"proposal_template": ProposalTemplateFinding`).

In `backend/app/ingest/records.py`, after `EligibilityGuidelineRecord`:

```python
class ProposalTemplateRecord(Provenance):
    """One proposal_template documents row, owned by the funder that publishes the form."""

    kind: Literal["proposal_template"] = "proposal_template"
    doc_type: ClassVar[str] = "proposal_template"
    funder_name: str = Field(min_length=2)
    title: str = Field(min_length=4)

    _org = field_validator("funder_name")(lambda v: reject_if_aggregate(v))
```

Add it to `Record`.

- [ ] **Step 5: Promote and brief**

In `backend/app/ingest/promote.py`:
- import `ProposalTemplateRecord`;
- append `"proposal_template"` to `WRITE_ORDER`;
- `CONCEPT_RECORDS["proposal_template"] = ProposalTemplateRecord`;
- in `_row_identity`: `if concept == "proposal_template": return (concept, f.source_url)`;
- next to the `eligibility_guideline` branch in `_write_facts`:

```python
                elif concept == "proposal_template":
                    rec = ProposalTemplateRecord(title=f.title, as_of=f.as_of, **base)
                    # Archived when fetch_document read it, as _write_documents does; a page read
                    # with read_page never was, and claiming a storage_path would misstate provenance.
                    key = await storage.archived_key(storage.SOURCE_ARCHIVE, f.source_url)
                    _, status = await ensure_document(
                        conn, rec, owner=owner, doc_type=rec.doc_type,
                        storage_path=storage.qualify(storage.SOURCE_ARCHIVE, key) if key else None,
                        content_hash=storage.hash_from_key(key) if key else None,
                    )
                    _count(report, "documents (proposal_template)", status)
```

It is not added to `_write_documents`' `by_url`, so no fact cites the template as its source.

In `backend/app/ingest/brief.py`, in `headline`, after the `document` branch:

```python
    if concept == "proposal_template":
        return _join(f.get("title"), "proposal template", f.get("as_of"))
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest -q -m "not integration" && ruff check .`
Expected: all pass. That includes every `CONCEPT_TABLES` / `FINDING_MODELS` parametrisation, which now includes `proposal_template`, and plan (b)'s `test_a_reserved_doc_type_is_refused_on_a_document_finding`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/ingest/expectations.py backend/app/ingest/research_records.py backend/app/ingest/records.py backend/app/ingest/promote.py backend/app/ingest/brief.py backend/tests/test_prior_research.py
git commit -m "feat(ingest): a funder's proposal template is a documents row

The proposal_template concept writes one funder-owned documents row per URL,
archived when the file was fetched. A document finding still cannot claim the
reserved type; a template named only by funder type is not a finding.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---


### D16 skill section (for funder-intake-research)

## Prior research, before anything else

The team researched funders before Sangam existed, in its own repository (registry key
`org_grant_intelligence`, rule `internal_research`). Read the funder's dossier there first. It is
a map of leads, not a source of record.

- **Find it, pinned.**
  - The dossier is `Funder/<funder>/*.md`: one folder per funder, its name in lowercase with
    hyphens. It holds a profile table, programmes, annual-report summaries and the links each fact
    came from.
  - Read every file in the folder with `read_page`, at the pinned commit the researcher's prompt
    gives, never at a branch. Rewrite a `github.com/…/blob/<branch>/…` link to the pinned raw
    address before reading it. Anything else on that host is refused.
  - The raw host lists no folders. Find file names with `search_public_sources`, using
    `site:github.com`, the repository name and the funder's name, then rewrite each hit.
  - A dossier path given in the task is read directly.
  - No folder for the funder is an answer ("no prior research"), not a reason to stop.
- **Save what it says as `claimed` prior research.**
  - Each fact is a finding whose `source_url` is the dossier file at its commit, and whose
    evidence quotes the dossier's line.
  - It is `claimed`: the dossier is our own earlier reading, not the funder's document.
  - Promotion records it under `org_grant_intelligence`.
- **Re-read what it cites.**
  - Every link in a dossier is a lead. Re-read the primary ones with `read_page` and
    `fetch_document`, under their own access rules: the funder's own site, its annual reports,
    the CSR annexure, the CSR policy.
  - A `REFUSED:` there is final, and the dossier's value stays `claimed`.
  - A fact you re-read is saved with its own source and evidence. At promotion it outranks the
    dossier value for the same fact.
- **An aggregator link is read only where the registry lists it under `manual_aggregator`.**
  Otherwise it is a lead to the funder's own page and nothing more, and the never-cite-an-aggregator
  rule below holds.
- **Where the dossier and the primary source disagree, keep both.**
  - Save the dossier finding and the primary finding, and do not edit either to agree.
  - Promotion writes the primary value and reports the disagreement.
  - Your summary names it: the field, both values and both sources. A dossier can be out of date.
- **Templates and RFPs.** The repository's `deep-agent-app/downloads/` folder holds proposal
  templates and RFPs as PDFs. Read them with `fetch_document` at the same commit.
  - **A template that a named funder publishes** becomes a `proposal_template` finding for that
    funder. A funder publishes it when its name is on the form, or on the page the form comes
    from. Save the form's title as printed, the year if one is printed, and the line naming the
    funder as evidence. Use the funder's own copy as `source_url` when it can still be read; the
    pinned file is the source only when it is the only copy.
  - **An RFP that a named funder issued** becomes an `rfp` finding (field 11). Mark it `closed`
    when its deadline has passed.
  - **A generic template**, one named by funder type with no funder on it, is a reference, not a
    finding. Mention it in the summary as a drafting reference, tied to no funder.


### D16 acceptance check

8. **Prior research (D16).** Pick a funder that has a dossier under `Funder/` in the repository at the pin, and research and push it in the same chat. Name it nowhere in the PR. Search may not index the repository's files. Put the dossier folder's profile file path in the Import task (`Funder/<folder>/<file>.md`), so the check tests the code and not the search index. Let `<slug>` be its slug, `<f>` its `funders.id`, and `R` the latest research row: `SELECT findings FROM entity_research WHERE slug = '<slug>' ORDER BY id DESC LIMIT 1`.
   - **Dossier facts land as claimed, with the commit cited.**
     - `SELECT count(*) FROM jsonb_array_elements(R.findings) f WHERE f->>'source_url' LIKE 'https://raw.githubusercontent.com/project-tech4dev/org-grant-intelligence/414cd6968765bcfff758632797dcbb8d00363ab2/Funder/%'` is at least 1.
     - Every catalog row written from the dossier carries the pinned file and the registry key. `SELECT count(*) FROM (SELECT source_url, source_name FROM funder_csr_years WHERE funder_id = <f> UNION ALL SELECT source_url, source_name FROM funder_activity WHERE funder_id = <f> UNION ALL SELECT source_url, source_name FROM programs WHERE funder_id = <f>) x WHERE source_url LIKE 'https://raw.githubusercontent.com/%' AND (source_name <> 'org_grant_intelligence' OR source_url NOT LIKE '%/414cd6968765bcfff758632797dcbb8d00363ab2/%')` returns 0.
   - **Nothing unpinned or foreign was cited.** `SELECT count(*) FROM jsonb_array_elements(R.findings) f WHERE f->>'source_url' LIKE 'https://raw.githubusercontent.com/%' AND f->>'source_url' !~ '^https://raw\.githubusercontent\.com/project-tech4dev/org-grant-intelligence/([0-9a-f]{40}|[0-9a-f]{7})/'` returns 0.
   - **A re-read primary fact outranks the dossier value.** Find a year for which `R` holds two `csr_year` findings, one at a dossier URL and one at a primary URL. If the researcher re-read none, ask Import to re-read the annual report or CSR annexure the dossier cites for one year, and push again.
     - `SELECT source_url FROM funder_csr_years WHERE funder_id = <f> AND fiscal_year = '<FY>'` returns the primary URL, not a `raw.githubusercontent.com` one.
     - If the two findings' values differ, `promote`'s report lists `the prior-research dossier disagrees with <primary URL> on <field>` under `held`, `R` still holds both findings, and the researcher's summary names the disagreement.
   - **Templates.** `SELECT count(*) FROM documents WHERE doc_type = 'proposal_template' AND funder_id IS NULL` returns 0. If the repository's `deep-agent-app/downloads/` holds a template that names this funder, `SELECT count(*) FROM documents WHERE funder_id = <f> AND doc_type = 'proposal_template'` is at least 1. No generic, type-named template appears as a row.

Record pass/fail per check in the PR. Use counts only — no names or figures.

- [ ] **Step 8: PR description must say**

- **Staff-only enforcement.** #92 is merged. The `documents` row is staff-only through `documents_read` RLS and `readable_document`. The download route also refuses to sign a staff object on a public or org row. Import is `require_staff`. `read_source_rows` runs as the owner, like every agent tool until 0027's "step 8", so the Import route is its gate. The bucket's `storage.objects` policy is staff SELECT only, and it fails closed where the migration role may not add it.
- **Where data goes.** Tool output, rows included, reaches the model provider, the LangGraph checkpoint tables (owner-only, not catalogued) and, when tracing is on, Langfuse, like any tool output. Nothing is logged by the app.
- **Spec refinements:**
  - a citation is a cell, not a row;
  - amount units include `inr`, with per-cell suffixes;
  - the sidecar;
  - `--split-sheets`;
  - the `.invalid` source URL;
  - a staff-dataset finding without its sheet/cell marker is held;
  - facts from every sheet, the CSO funder sheets included, are promoted as public rows (D14), and the `ffrh_funder_datasets` basis says FFRH has cleared them for display;
  - the tool sits on the researcher, not the supervisor.
- **Prior research (D16).**
  - `hand_vetting_sheets` is replaced by `org_grant_intelligence`, under the new non-dispatchable rule `internal_research`. It owns `raw.githubusercontent.com`, so the fetch tools read only that repository's files at a 40- or 7-hex commit. Other repositories, branches, `HEAD`, dot segments and encoded slashes are refused.
  - Redirects are followed and not re-checked per hop, as for every host today. A pinned blob does not redirect.
  - Coordination: the CSO plan adds the same rule and entry, and whichever PR lands second drops its own copy.
- **Spec refinements (D16):**
  - "claimed" is carried by the pinned `source_url` and `source_name = 'org_grant_intelligence'`, not by a new column;
  - "outranks" is `prior_research.rank`, which runs before any writer. It holds within one research run; across runs the newest research wins, as for every source today;
  - a funder's template needed a writer, the `proposal_template` concept, because plan (b) reserved the type without one;
  - `read_page` returns a `text/plain` body as it is;
  - the researcher finds dossier file names through `search_public_sources`, because the raw host lists no folders.
- **Migration.** The number (0032) follows (b) and is reassigned at merge if needed.

---

