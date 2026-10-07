# Authorization: roles and row-level security

Status: proposal for review. It builds on §4 and §5 of
[`2026-09-27-data-platform-architecture-design.md`](2026-09-27-data-platform-architecture-design.md)
and on the v3 schema in [`db/init/02_schema.sql`](db/init/02_schema.sql).

Funders are out of scope: no funder memberships and no funder-specific access rules.

## Who sees what

| Caller | Access |
|---|---|
| Anonymous, or signed in without any access granted | Public data only |
| Org admin (`org_members.role = 'admin'`) | Reads and writes that org's private data |
| Steward (`org_members.role = 'steward'`, one row per org) | Reads the private data of each org it is added to; cannot write |
| Staff (`users.is_staff`) | Everything, and the only callers who can grant or remove access in phase 1 |

`org_members.role` keeps its current values (`admin`, `member`, `steward`). Phase 1 writes only
`admin` and `steward`, so phase 2 needs no schema change to bring `member` into use.

## Phase 1: sign-in, RLS, one org role, staff admin tools

1. **Real sign-in all the way through**
   - The backend checks the Supabase JWT against Supabase's published signing keys (JWKS) and
     creates or updates the `users` row from its `sub` and email.
   - A `DEV_AUTH=1` setting keeps the dev token working locally. The dev user gets a fixed
     `auth_user_id`.
   - The frontend sends the Supabase access token instead of `Bearer dev`.
   - `proxy.ts` lets public pages load for callers who are not signed in, and when the Supabase
     keys are not set.
2. **RLS, with every query running as the caller** (spec §5.1)
   - Port the v3 functions and policies into migration `0021`. Its number follows #61's `0020`.
   - Every request runs through one `db.user_conn(user)` helper, which issues
     `SET LOCAL ROLE authenticated` (or `anon`) and sets `request.jwt.claim.sub`. A test fails if
     any module uses the pool without it.
   - `/agent` calls `app.can_open_thread` before loading or writing checkpoints, and returns 404
     when it returns false.
   - Ingest, seed and migrate jobs keep connecting as the table owner. Only requests from users
     run as the caller.
   - A test matrix covers every table as five callers: anonymous, signed in without access, org
     admin, steward and staff.
3. **Staff admin tools**
   - `SECURITY DEFINER` functions `app.grant_access` and `app.revoke_access` check `is_staff`
     and write each change to `membership_events`.
   - Screens:
     - **Users:** search people; make someone an org admin; add steward access to other orgs;
       set the staff flag.
     - **Audit log:** read the access changes.

## Phase 2

- **Domain matching.** An `email_domains` table maps a domain to one org, and only staff can
  add or verify a mapping. At sign-in, a verified email on a mapped domain gets access to that
  org. Free email providers (gmail.com, yahoo.co.in, …) can never be mapped. Sign-in only adds
  access: a `revoked` status stops a removed user from being re-added on the next sign-in.
- **Separate member and admin.** Members read and upload. Admins also manage their org's people.
- **Org admins manage their own members.** They can invite, remove, and switch people between
  member and admin.
- **Requests to join an NGO.** Anyone signed in can ask to join an org. Its admins approve or
  decline, and staff step in when an org has no admin yet. This is the route in for NGOs whose
  staff use personal gmail addresses.
- **The same access functions carry over.** They check for "staff, or admin of this org" instead
  of staff only.

## What the database has today

Checked against migrations 0001–0019 and a local database on 2026-10-01.

| Already in place | From |
|---|---|
| `users.auth_user_id`, `users.is_staff` (the dev user is staff) | 0004 |
| `org_members (user_id, org_id, role, added_by, added_at)`, roles `admin` / `member` / `steward` | 0004 |
| `orgs.registry_status`, `funders.registry_status`, including `hidden` | 0004 |
| `threads.org_id`, `visibility` (`private` / `team` / `team_and_stewards`), `use_case`, `updated_at` | 0005 |
| `documents.org_id`, `is_public`, `storage_path` (`<org_id>/<file>`), `uploaded_by` | 0005 |
| Public/private flags the policies read: `contacts.is_public` and `kind`, `org_identifiers.is_public`, `credential_events.verified`, `news_mentions.review_status` | 0006–0010 |

| Missing | Notes |
|---|---|
| `anon` and `authenticated` roles | Supabase creates them; the local container does not |
| `auth.uid()` stub for local runs, and the `app` schema | Nothing named `auth` exists locally |
| `app.*` functions | `user_id`, `is_staff`, `my_org_ids`, `my_writable_org_ids`, `can_open_thread` |
| RLS | Enabled on 0 of 49 tables, with 0 policies |
| Table grants to `anon` / `authenticated`; `GRANT anon, authenticated TO <owner>` | Needed to run queries as the caller |
| RLS on `checkpoint*`, `schema_migrations`, `graph_ingest_log` | Spec §5.3 |
| `membership_events` | Phase 1 |
| `email_domains`, join requests | Phase 2 |
| JWT check in the backend | `backend/app/core/security.py` always returns the dev user |
| Database role named by `sql_reader_role` | The setting exists (`backend/app/core/config.py`); the role is never created |

## What migration 0021 reuses from v3

From `features-plans/data-model/db/init/02_schema.sql`:

| v3 part | Lines | Reuse | Change |
|---|---|---|---|
| §0 roles and `auth.uid()` stub | 20–37 | As written | None |
| §12 `app.*` functions | 1078–1120 | As written | None. `my_writable_org_ids` (roles `admin`, `member`) and `can_open_thread` already work when `admin` is the only org role |
| §13 enable RLS on every table | 1130–1137 | As written | Run it after all migrations, so it also reaches the tables from 0011–0019 |
| §13 public-read and private-read policies | 1139–1200 | Mostly as written | Restrict `contacts_read_auth` to org members and staff, so a signed-in caller without access sees only public contacts |
| §13 vault storage policies | 1202–1215 | Adapt | Rename bucket `vault` to `org-vault` to match #61 |

### Not covered by v3

- **Grants.** v3 grants usage on schema `app` only. Grant `SELECT` on public tables to `anon` and
  `authenticated`, plus `INSERT`/`UPDATE` where a policy allows the write, and
  `GRANT anon, authenticated TO <owner>` so the backend can `SET ROLE`.
- **Six tables have no policy:** `ingest_runs`, `ingest_run_items`, `ingest_source_proposals`,
  `resolution_queue`, `entity_research` and `extraction_log`. With RLS on, nobody but the table
  owner could read them, so the Import screens would break. Give them staff-only policies.
- **Writes.** v3 has a write policy only for document uploads. Running as the caller also needs:
  - `threads` insert and update by the thread's owner;
  - `proposals` writes by org admins.

  Access changes go through `app.grant_access` and `app.revoke_access`, never through direct
  writes to `org_members`.
