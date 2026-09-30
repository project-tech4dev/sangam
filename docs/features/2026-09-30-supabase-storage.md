# Supabase Storage: an archive for what we fetch, a vault for what orgs upload

**Status: planned, nothing built.** Written 2026-09-30, branch `feat/supabase-storage`.
This is a record of what was decided and why, not a description of what exists. When the code
lands, the living description goes in `docs/STORAGE.md`; this file stays as the reasoning.

## Why

Sangam holds no bytes. `fetch_document` (`backend/app/ingest/research.py:119-151`) streams a
funder's CSR report to `/tmp/sangam-downloads` (`backend/app/core/config.py:56`), the model reads
a few pages, and the container throws it away on restart. Worse, `_safe_name`
(`backend/app/agent/tools/files.py:27-32`) flattens the URL down to its filename, so two sources
both called `report.pdf` silently overwrite each other mid-run.

The product promise is that every field traces to a source. Today it traces to a URL that may
404 tomorrow.

And there is no way for an NGO to give us anything. `cso_vault_uploads` is already a declared
source in `backend/app/ingest/data/sources/ngos.json:190-200` — *"Documents an organisation
uploads about itself. Use is governed by that CSO's consent under the DPDP Act, and the files
stay private by default"* — with nothing behind it.

**Most of the modelling is already done.** `db/migrations/0005_documents_threads.sql:4-14` added
to `documents`: `storage_path text` (commented *"Supabase Storage key, `'<org_id>/<file>'`"*),
`is_public` (*"vault uploads are inserted false"*), `uploaded_by`, `status`, `archive_url`.
Nothing in `backend/app/` reads or writes any of them. `db/migrations/0004_identity.sql` added
`users.auth_user_id`, `users.is_staff` and `org_members` — *"Every private-read policy will
resolve through these."* This work is the wiring those columns were added for.

## Decisions

### Two buckets, both private, with a folder per entity

The instinct is a bucket per funder and per NGO. It is the wrong grain. Supabase's own guidance:
buckets exist to separate **access rules**; folders organise within them. Bucket names are
immutable, and each bucket needs its own policies — so one-per-entity would make bucket creation
part of the ingest write path and turn RLS into N policy sets that must be kept identical.

| Bucket | Holds | Key |
|---|---|---|
| `source-archive` | what research downloaded — public documents, kept for provenance | `<sha256(source_url)[:12]>/<sha256(bytes)>-<name>` |
| `org-vault` | what an NGO uploads about itself — DPDP-governed | `<org_id>/<sha256(bytes)>-<name>` |

Two buckets rather than one because a scraped public annual report and an NGO's audited accounts
have genuinely different access rules, and a bucket is the cheapest place to put that boundary.

**Revised at M2, from `funders/<funder_id>/…`.** Reading the code killed the original: an entity
prefix cannot be written, because `fetch_document` runs during research and a `funder_id` does
not exist until `resolve_funder` runs at promotion — while the bytes exist only at fetch. The
archive therefore keys on the URL (known at both moments, so promotion finds the object with no
lookup table) and on the content (so a funder republishing at the same URL adds a version instead
of overwriting the bytes a finding was read from — the precise provenance failure this exists to
prevent). The content hash in the key is what lets promotion populate `documents.content_hash`
with nothing re-downloaded. The entity link lives in `documents.funder_id`.

`org-vault` is unchanged: an upload knows its org, and `<org_id>` is the RLS predicate.

### Keyed by id, not slug

`_free_slug` (`backend/app/ingest/writer.py:122`) appends a suffix on collision, so a funder's
slug depends on insertion order and is not stable. `org_members` joins on `org_id`, and the
eventual policy reads `(storage.foldername(name))[1]::bigint`. Migration 0005 already assumed
this: `'<org_id>/<file>'`.

Moving objects to change a prefix later is the expensive mistake. A policy is cheap. **The path
convention is the RLS design**, so it is fixed now even though enforcement comes last.

### No `supabase` SDK

`httpx>=0.27` is already a dependency and Storage has a plain REST API
(`POST /storage/v1/object/{bucket}/{path}`, service-role bearer). The SDK would pull
`gotrue`/`realtime`/`postgrest` into a service that already talks to Postgres via psycopg, on a
256 MB-of-500 MB Vercel bundle budget.

### Signed URLs, not proxied bytes

Vercel Functions cap request bodies at roughly 4.5 MB (**confirm before building M3**) and annual
reports are routinely 5–20 MB. The backend authorises and mints a short-lived signed upload URL;
the browser transfers directly to Storage. This also means no multipart handling in FastAPI.

A signed URL bypasses RLS at redemption by design, which is why the application-level
`org_members` check in M3 is not made redundant by M4.

### Vault text is extracted immediately, and the exposure is written down

Decided deliberately, with the cost stated. `documents.content_md` and `storage_path` are in the
SQL catalog (`backend/app/agent/tools/sql/catalog.py:134`) and `db_query` has no per-caller
filter. So from M3, every user's agent can read every org's private accounts. With one seeded dev
user there is effectively one tenant today, and making uploads usable immediately is worth more
than a boundary nothing yet crosses.

M3 therefore adds a `defects` line to the `documents` catalog entry — defects are injected into
every result touching the table — and M4 is what deletes it.

## Milestones

| | Milestone | Size | The gate |
|---|---|---|---|
| **M0** | Reach the right Supabase project | — | `list_projects` returns the live ref |
| **M1** | The two buckets and the path convention | S | Both buckets exist; `make migrate` is a clean no-op locally |
| **M2** | Archive what research already downloads | M | A research run leaves `documents.storage_path` non-null and the object fetchable |
| — | *M1 done, M2 code done — live verification of M2 needs the two env vars* | | |
| **M3** | The Doc Vault — orgs upload | L | A 12 MB PDF goes up from the browser and comes back down |
| **M4** | RLS, when auth lands | M | A non-member gets 403 *without* the backend checking |

### M0 — Reach the right Supabase project

`list_projects` through the connected Supabase MCP returns exactly one project:
`ibezaibwiuauquvsxbhw` (ap-northeast-1). `.memory/STATE.md:23` records the deployed database as
`aqhhlorihtkcipntwycg` (ap-south-1), and `:64` states the MCP account *"cannot inspect the real
database."* Anything created through that connection lands in the wrong project.

Re-authenticate via `/mcp` against the account that owns the ap-south-1 project.

**Exit:** `list_projects` shows `aqhhlorihtkcipntwycg`, and `select id, name from
storage.buckets` runs against it.

**Done 2026-09-30.** Re-authenticating surfaced `aqhhlorihtkcipntwycg` "Sangam Dev", ap-south-1,
36 public tables, 96 documents — the live one.

### M1 — The two buckets and the path convention

- **`db/migrations/0020_storage_buckets.sql`** — `INSERT INTO storage.buckets (id, name, public,
  file_size_limit, allowed_mime_types) … ON CONFLICT DO NOTHING` for both, wrapped in a
  `DO $$ … IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') … $$` guard. **The
  guard is not optional:** the local Postgres container has no `storage` schema, exactly as 0004
  notes for `auth`, so an unguarded file breaks `make migrate` for everyone. One ledger, no-op
  locally.
  Numbering continues from `0019`. `docs/DATA_PLATFORM.md`'s ten-migration plan is numbered
  against a different baseline and collides — ignore those numbers.
- **`backend/app/core/config.py`** — `supabase_url` and `supabase_service_key` (both `""`), plus
  a `storage_enabled` property, following the `graph_enabled` / `langfuse_enabled` idiom at
  `:91,:95`.
- **`.env.example` and `docker-compose.yml`.** Both. A variable absent from the compose
  `environment:` block never reaches the container no matter what `.env` says — that is precisely
  how LangSmith tracing was silently dead for weeks.
- **`docs/DATA_PLATFORM.md`** gains the bucket table beside its `storage_path` row (`:42`).

**Exit:** both buckets listed on the live project with `public = false`; `make migrate` applies
`0020` locally and touches nothing; `make up` still boots with the keys unset.

### M2 — Archive what research already downloads

- **`backend/app/integrations/storage.py`** (new) — the only module that talks to Storage.
  `upload(bucket, key, data, content_type)`, `signed_url(bucket, key, ttl)`, `exists(...)`, over
  `httpx` with the service-role bearer. Follows `app/integrations/graphiti.py`: lazy, and when
  `storage_enabled` is false every call is a no-op that logs once. It goes in `integrations/`
  per CLAUDE.md's "no new module goes flat at the top of `backend/app/`".
- **`backend/app/ingest/research.py:119-151`** — after `fetch_document` streams to disk, hash the
  bytes, upload to `source-archive` under the entity's prefix, return the key. **Keying on the
  hash also fixes the `_safe_name` overwrite bug**: two different `report.pdf`s stop colliding.
- **`backend/app/ingest/writer.py:71-87`** — `ensure_document` gains `storage_path`,
  `content_hash` and `archive_url`. It currently dedupes with SELECT-then-INSERT and there is
  **no unique index on `documents.source_url`**, so it races; adding one would let it use
  `ON CONFLICT`. Do it here or defer it explicitly.
- Failure is never fatal: a failed upload logs and leaves `storage_path` null. Optional
  subsystems degrade, they do not crash.

**Exit:** research one funder against the live project — `documents.storage_path` non-null, the
object downloads through a signed URL, the same PDF fetched twice writes one object. With
`SUPABASE_SERVICE_KEY` unset the same run completes and writes its rows.

**Built 2026-09-30; live verification still owed.** `app/integrations/storage.py`,
`fetch_document` archiving, `ensure_document` recording and backfilling, 29 tests over
`httpx.MockTransport` plus four against a real Postgres. The live half needs `SUPABASE_URL` and
`SUPABASE_SERVICE_KEY` in `.env`; until they are set `storage_enabled` is false and the archive
is a logged no-op.

Two things that came out of building it, beyond the key change above:

- **`ensure_document` returned early on an existing row and never updated it**, so a re-promote
  could never have filled `storage_path` on any of the 96 rows that predate this. It now returns
  `(id, added | updated | matched)` like the other writers, and backfills the archive columns
  with a `coalesce`-style guard so a second promote cannot rewrite provenance.
- **`storage_path` is looked up, not assumed.** A page read with `read_page` was never
  downloaded; claiming a key for it would be a lie in a provenance column. Promotion asks
  Storage whether the URL was archived, and Storage being unreachable returns `None` rather than
  aborting the promote.

### M3 — The Doc Vault: orgs upload

Three routes, following `backend/app/api/routes/documents.py` (which already uses the newer
`PageParams`/`Page[T]` convention — copy that, not `orgs.py`), each with its
`repositories/documents.py` and `schemas/documents.py` counterpart:

- `POST /api/orgs/{slug_or_id}/documents/upload-url` — check the caller against `org_members`,
  return a signed upload URL and the key.
- `POST /api/orgs/{slug_or_id}/documents` — confirm the object landed, insert the row
  (`is_public = false`, `status = 'received'`, `uploaded_by`, `storage_path`, `content_hash`),
  then extract text with the existing `extract_pdf_text`
  (`backend/app/agent/tools/files.py:46-61`) into `content_md`.
- `GET /api/documents/{id}/file` — authorise, return a short-lived signed download URL.

Frontend: `frontend/lib/api/client.ts` is GET-only (25 lines, one `apiGet`), so it needs an
`apiPost`. The upload control goes in `frontend/features/ask/views/VaultView.tsx`, which already
exists and already sends `Bearer dev` (`:24`).

Security: add the `defects` line to the `documents` entry in
`backend/app/agent/tools/sql/catalog.py` recording that private vault rows are readable by every
caller until run-as-caller RLS lands. Adding to the catalog is a security decision; so is
knowingly leaving something in it.

**Exit:** a 12 MB PDF uploads from the browser and downloads again; the row has
`is_public = false` and a populated `content_md`; `pytest -m "not integration"` green against the
pool sentinel (unit tests never touch a database — monkeypatch the repository, not the pool).

### M4 — RLS, when auth lands

Rides with the access-layer phase `docs/DATA_PLATFORM.md:157-181` already designs: `SET LOCAL
ROLE authenticated` plus the JWT subject, so policies apply to REST and to the agent alike.
Storage policies on `storage.objects` resolve `auth.uid() → users.auth_user_id → org_members`,
with `is_staff` seeing everything:

```sql
create policy "org members read their vault" on storage.objects for select to authenticated
using (
  bucket_id = 'org-vault'
  and (storage.foldername(name))[1]::bigint in (
    select m.org_id from org_members m join users u on u.id = m.user_id
    where u.auth_user_id = auth.uid()
  )
);
```

Two things that will bite. The deployed role is `postgres`, and **a table owner bypasses RLS on
its own tables unless `FORCE ROW LEVEL SECURITY`** — `storage.objects` is owned by
`supabase_storage_admin`, so Storage-API traffic is fine, but the `public` table policies are
not. And the service key bypasses everything by design, which is why M3's membership check stays.

**Exit:** with a real user JWT, a member downloads and a non-member gets 403 with the backend
check removed; the `documents` catalog defect from M3 is deleted.

## Known gaps — what this does NOT make true

Read this before treating the feature as finished.

- **Nothing is access-controlled until M4.** Both buckets are private, but every read and write
  goes through the service key, which bypasses RLS entirely. The only authorisation is the
  `org_members` check in M3's routes — application code, not the database.
- **There is no auth to control access with.** `get_current_user`
  (`backend/app/core/security.py:12-13`) declares the `Authorization` header and ignores it,
  returning one hardcoded UUID; five frontend call sites send a literal `Bearer dev`. M4 cannot
  start until Supabase Auth does.
- **From M3, any user's agent can read any org's private uploads.** Deliberate, scoped to the
  single-tenant staging reality, recorded as a catalog defect, closed by M4. See the decision
  above.
- **Row-level security does not exist anywhere in this database today** — no policies, no grants,
  no roles. `docs/DATA_PLATFORM.md:18`: *"Access control | none in the database; the backend
  connects as owner and sees everything."*
- **The 96 existing `documents` rows keep no bytes.** They have source URLs and nothing archived.
  Backfilling is a one-off script after M2 proves the path, not part of it.
- **No retention, deletion or virus scanning**, and no resumable (TUS) uploads. An upload that
  fails halfway leaves an orphaned object with no `documents` row.
- **Staging is 19 migrations behind, which blocks M2 and M3.** Measured 2026-09-30 on
  `aqhhlorihtkcipntwycg`: `schema_migrations` is empty, and `documents.storage_path`,
  `org_members`, `entity_research`, `funder_csr_years`, `proposals` and `resolution_queue` do
  not exist. It is the v2 baseline plus data. M2 writes `documents.storage_path` and M3 reads
  `org_members`; neither can run there until `make migrate ENV=staging` applies `0001`–`0020`.
  That is a substantial schema change to a live database with 96 documents in it — back it up
  first, and treat it as its own piece of work, not a step inside this one.
- **A bucket named `axis` already exists** on the project (private, 50 MB, created 2026-09-30
  06:20 UTC), outside this design and unreferenced by any code. Left alone pending a decision.

## Verification

- `make migrate` locally (0020 no-ops) and against the live project (buckets appear).
- `make up` with `SUPABASE_*` unset — boots, research runs, `storage_path` stays null.
- End to end on the live project: research a funder → signed-URL download of the archived PDF →
  upload a 12 MB PDF through the Vault → fetch it back → confirm the `documents` row in
  `make psql`.
- `pytest backend/tests/` — a `storage_enabled = false` no-op test, the hash-keying test (two
  `report.pdf`s, two objects), the membership check refusing another org.
- `cd frontend && npm run build` — type errors surface there, never in `next dev`.
- Confirm the Vercel request-body limit before building M3's upload path.

## Out of scope

Supabase Auth itself — M4's precondition and separate work. Image transforms, resumable uploads,
virus scanning, retention and deletion policy. Backfilling the existing `documents` rows.
