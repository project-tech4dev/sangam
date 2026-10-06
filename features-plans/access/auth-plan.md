# Access plan: sign-in, roles and RLS

Status: draft. The roles, the access functions and the end-to-end flow are in
[`../data-model/2026-10-02-roles.md`](../data-model/2026-10-02-roles.md). This file is the order we
build it in.

The plan does the minimum first: everything is built on one branch, one step at a time. Each step
changes one thing, has a quick check, and leaves the branch working.
Fuller tests and the extras come later, in their own PRs (Part 2).

## How we use the `users` table

Supabase handles the sign-in; our `users` table holds who that person is inside Sangam.

```
Sign in with Google ──► Supabase creates a row in auth.users
                              │  trigger (step 2)
                              ▼
                        we create a row in users, linked by users.auth_user_id = auth.users.id
```

- **One row per person**: `id` (our id, used everywhere in Sangam), `auth_user_id` (their Supabase
  account), `email`, `display_name`, `is_staff`.
- **Created at sign-up** by a trigger on `auth.users` (step 2). If the trigger missed someone, the
  backend creates the row on their first request (step 1). If staff already made a row with that
  email, it is linked instead of a second one being created.
- **Every request** reads the token, finds the row by `auth_user_id`, and so knows who is calling and
  whether they are staff.
- **What it decides**: `is_staff` gives staff access, `org_members` links the row to organisations and
  so to their private rows, and `threads.user_id` makes each chat its owner's.

In short: Supabase says "this person signed in"; `users` says who they are in Sangam and what they
may see.

## Part 1: the minimum, step by step

### Step 1: The backend reads the Supabase token

**What changes**
- The backend checks the token against Supabase's public keys and reads the Supabase id and email
  from it.
- It looks the user up in our `users` table by `auth_user_id`. If no row exists yet, it creates one
  (the fallback for anyone the step 2 trigger missed).
- No token means anonymous. With `SUPABASE_URL` empty, everything works as it does today.

**How to test**
- Set `SUPABASE_URL`, sign in, call any route: your row is in `users`.
- One unit test for a valid token and one for an expired token.

### Step 2: Create the `users` row when someone signs up

**What changes**
- A trigger on Supabase's `auth.users` creates our `users` row the moment a person signs up, instead
  of waiting for their first request.
- If staff already created a row with that email, the trigger links it instead of making a second.
- A second trigger keeps the email in step when it changes in Supabase.
- Local Postgres has no `auth.users`, so the migration adds a small stand-in table for local runs
  and tests.

**How to test**
- Sign up a new user in Supabase: the `users` row exists before they call the backend.
- Pre-create a row by email, then sign up with that email: one row, now linked.
- Invite a user from the Supabase dashboard (Authentication → Invite user): their row appears at once.

**Keep it simple:** a trigger that fails blocks the sign-up, so it does only the create or link.

### Step 3: The frontend sends the real token

**What changes:** every call, chat included, sends the Supabase access token instead of `Bearer dev`.

**How to test**
- Browser Network tab: `Authorization` holds the token, not `dev`.
- `npm run build`.

### Step 4: Block what needs sign-in or staff

**What changes**
- Saving or editing needs sign-in.
- Sangam Import needs staff.
- The chat needs sign-in and your own thread; someone else's thread is 404.

**How to test**
- Signed out, saving gets 401.
- Non-staff opening Import gets 403.
- `make smoke`.

### Step 5: Database roles and the access functions

**What changes:** three migrations. `0023` adds the `anon` and `authenticated` roles, `0024` the
`app.*` functions, and `0025` removes Supabase's default access to every table, then grants access
table by table; a table left out of its lists fails the migration. The app still connects as the
owner, so **nothing changes for users yet**.

**How to test**
- `make migrate`.
- As a member and as staff, `app.my_org_ids()` returns the orgs you expect.

### Step 6: Requests run as the caller

**What changes**
- One middleware handles the token for every request: it reads `Authorization`, checks the token,
  finds or creates the `users` row, and keeps who is calling for the rest of the request. It does this
  as the owner, because it writes `users` rows no caller may write.
- `PoolDep` becomes the pool as that caller: `anon` when signed out, `authenticated` with their
  claims when signed in. Routers keep `pool: PoolDep`, so no route file changes and a new route runs
  as the caller without having to ask. Identity code takes `OwnerPoolDep`.
- `get_pool()` stays the owner. The agent tools and the Import runner call it outside any request, and
  Import writes the catalog as the owner; running them as the caller is step 8.
- `0026` gives the seeded dev user an `auth_user_id`, so the access functions still recognise it.
- `get_current_user`, `require_user` and `require_staff` read the caller the middleware kept instead of
  checking the token again.
- A table the role cannot use returns 403 instead of 500.

**Keep it simple**
- A plain ASGI middleware, not `BaseHTTPMiddleware`, which buffers responses and breaks the chat's
  streaming.
- It answers a bad token with its own 401: FastAPI's exception handlers never see errors raised there.
- It sits inside `CORSMiddleware`, so preflight requests are answered before it runs, and it skips
  `/health` and `/docs`.

**How to test**
- `make smoke`.
- Click through the registry signed out and signed in.
- Unit test: no token runs as `anon`, a valid one as `authenticated`, a bad one gets 401.

### Step 7: RLS rules

**What changes:** `0027` turns RLS on for every table, with one rule per kind of table (see "Which rule
each table gets" in the roles doc), and fails if a table either role can read has no rule. A row of an
`org_*` or `funder_*` table follows its org or funder, so a hidden org hides its rows too, and a chunk
follows its document. Writes go to orgs in `app.my_writable_org_ids()`, and staff may write wherever a
route already lets them.

**How to test**
- `pytest tests/test_rls.py` runs each role against each kind of table, in a transaction that is rolled
  back.
- Open the same org page as a member of Org A, a member of Org B, and staff. Each sees only what they
  should.

#### Public tables: everyone, signed out too

These 23 tables are granted to `anon` and `authenticated`, and their rule is `USING (true)`: everyone,
signed out or signed in, sees every row. Nobody writes to them through the app, except a member adding a
score adjustment to their own org's score.

| Group | Tables |
|---|---|
| Programs | `programs`, `program_locations`, `program_tags` |
| Grants | `grants`, `grant_locations` |
| RFPs | `rfps`, `rfp_locations`, `rfp_tags` |
| Scoring | `rubrics`, `rubric_criteria`, `fit_scores`, `fit_score_items`, `score_adjustments` |
| Signals | `credential_events`, `news_mentions`, `metrics`, `reference_figures`, `extraction_log` |
| Reference | `tags`, `locations`, `location_designations`, `proposal_templates`, `template_items` |

#### Every other table: who reads

"Their org" means the org the row belongs to. A member, admin or steward of it is one of "its people".

| Kind | Tables | Signed out | Signed in, no org | Its people | Staff |
|---|---|---|---|---|---|
| Public unless hidden | `orgs` | ✔ not hidden | ✔ not hidden | ✔ also their hidden org | ✔ all |
| | `funders` | ✔ not hidden | ✔ not hidden | ✔ not hidden | ✔ all |
| Follows its org | `org_locations`, `org_tags`, `org_financials` | as `orgs` | as `orgs` | as `orgs` | ✔ all |
| Follows its funder | `funder_csr_spend`, `funder_csr_years`, `funder_footprints`, `funder_identifiers`, `funder_locations`, `funder_partners`, `funder_tags`, `funder_eligibility` | as `funders` | as `funders` | as `funders` | ✔ all |
| Public by flag | `contacts`, `documents`, `org_identifiers` | ✔ public rows | ✔ public rows | ✔ public + their org's private | ✔ all |
| Follows its document | `chunks` | as `documents` | as `documents` | as `documents` | ✔ all |
| Org-private | `proposals`, `rfp_matches` | ✘ 403 | 0 rows | ✔ their org's | ✔ all |
| Own rows | `users`, `org_members` | ✘ 403 | ✔ own row | ✔ own rows | ✔ all |
| | `threads` | ✘ 403 | ✔ own chats | ✔ own + shared with them¹ | ✔ all |
| Staff only (Import) | `ingest_runs`, `ingest_run_items`, `ingest_source_proposals`, `entity_research`, `resolution_queue` | ✘ 403 | 0 rows | 0 rows | ✔ all |
| Closed | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`, `schema_migrations`, `graph_ingest_log` | ✘ 403 | ✘ 403 | ✘ 403 | ✘ 403² |

¹ A chat shared with `team` opens for the org's members and admins; one shared with `team_and_stewards`
for its stewards too.
² Through the app. The backend reads them as the owner, which RLS does not apply to.

#### Who writes

Signed out writes nothing: `anon` has no write grant. There is no DELETE anywhere. "Member or admin"
means of the row's org; a steward never writes.

| Table | Insert | Update | Who | Route |
|---|---|---|---|---|
| `contacts` | ✔ | ✔ | Member or admin, staff | `POST`/`PATCH /api/contacts` |
| `documents` | ✔ | ✘ | Member or admin, staff | `POST /api/documents` (vault upload) |
| `score_adjustments` | ✔ | ✘ | Member or admin of the score's org, staff | `POST /api/scores/{id}/adjustments` |
| `rfp_matches` | ✘ | ✔ | Member or admin, staff | `PATCH /api/rfps/{id}/matches/{org_id}` |
| `proposals` | ✔ | ✔ | Member or admin only, **not staff** (open question) | none yet |
| `threads` | ✔ | ✘ | Anyone signed in, only as themselves | claiming a new chat |
| Every other table | ✘ | ✘ | Nobody through the app; Import and the seeds write as the owner | — |

#### Contacts, documents and org identifiers

These are public by flag: a row with `is_public = true` goes to everyone, one with `is_public = false`
only to that org's people and staff. A private funder contact has no org, so only staff see it.

What a person sees, for public rows and for the private rows of Org 1:

| Who | Public rows | Org 1's private rows | Org 2's private rows | Can add or edit Org 1's contacts |
|---|---|---|---|---|
| Signed out | ✔ | ✘ | ✘ | ✘ |
| Signed in, no org | ✔ | ✘ | ✘ | ✘ |
| Member of Org 1 | ✔ | ✔ | ✘ | ✔ |
| Admin of Org 1 | ✔ | ✔ | ✘ | ✔ |
| Steward of Org 1 | ✔ | ✔ | ✘ | ✘ (reads only) |
| Member of Org 2 | ✔ | ✘ | ✔ | ✘ |
| Staff | ✔ | ✔ | ✔ | ✔ |

So a member of Org 1 who signs in sees every public contact plus Org 1's private ones, and none of any other
org's. The same holds for documents (a member or admin may also upload to their own org's vault) and org
identifiers (read only).

#### How public and private tables are set up

Each table gets one grant and one RLS rule:

```
Request ──► Grant: may anon / authenticated use this table?
              no  ──► 403
              yes ──► RLS rule: which rows may this person see?
                        ──► only those rows come back
```

A signed-in user who isn't in any organisation sees exactly what an anonymous user sees. The rules
need nothing extra for this: `app.my_org_ids()` returns nothing for that user, so only the public rows
get through.

**A fully public table, e.g. `programs`**

```sql
-- 1. Grant: both roles may read, neither may write
GRANT SELECT ON programs TO anon, authenticated;

-- 2. RLS: turn it on, and let every row through
ALTER TABLE programs ENABLE ROW LEVEL SECURITY;

CREATE POLICY programs_public_read ON programs
  FOR SELECT TO anon, authenticated
  USING (true);
```

Signed out and signed in both pass the grant, and `true` returns every row. They see the same thing,
because the rule never looks at organisations.

**A table with some private rows, e.g. `contacts`**

```sql
GRANT SELECT ON contacts TO anon, authenticated;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY contacts_read ON contacts
  FOR SELECT TO anon, authenticated
  USING (
    is_public
    OR org_id IN (SELECT app.my_org_ids())
    OR app.is_staff()
  );
```

| Who | `is_public` | `org_id IN my_org_ids()` | `is_staff()` | Sees |
|---|---|---|---|---|
| Signed out | ✔ | empty | false | Public rows only |
| Signed in, no organisation | ✔ | **empty** | false | **Public rows only, same as signed out** |
| Member of Org A | ✔ | Org A | false | Public rows and Org A's rows |
| Staff | ✔ | — | true | Every row |

When staff add the user to `org_members`, `my_org_ids()` starts returning that organisation and the
user sees more. The rule itself never changes.

**A private table, e.g. `proposals`**

```sql
GRANT SELECT, INSERT, UPDATE ON proposals TO authenticated;   -- no anon grant at all
ALTER TABLE proposals ENABLE ROW LEVEL SECURITY;

CREATE POLICY proposals_read ON proposals
  FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_org_ids()) OR app.is_staff());
```

Signed out gets 403 at the grant. Signed in with no organisation passes the grant, but the rule finds
no organisations for them, so they get 0 rows.

**In short**

| What you want | Grant to | Rule |
|---|---|---|
| Everyone sees all rows | `anon, authenticated` | `USING (true)` |
| Everyone sees public rows, organisation people see more | `anon, authenticated` | `is_public OR org_id IN (SELECT app.my_org_ids()) OR app.is_staff()` |
| Only organisation people | `authenticated` | `org_id IN (SELECT app.my_org_ids()) OR app.is_staff()` |

### Step 8: Ask Sangam runs as the caller

**What changes:** the chat's SQL tool runs as the user, not as the owner. This closes the largest gap.

**How to test:** as a member of Org A, ask the chat for Org B's private data. It finds nothing.

### Step 9: Roll out

**What changes, in this order**
1. Run the migrations on staging.
2. Deploy the backend with `SUPABASE_URL` set and `DEV_AUTH` unset.
3. Deploy the frontend.
4. Mark the staff accounts as staff.

**How to test:** `make smoke` against staging, then sign in once as each role.

## Part 2: later, in separate PRs

| What | Why it can wait |
|---|---|
| `/api/me`, and hiding Import in the nav | Step 4 already blocks Import; this only tidies the UI |
| Full test suites: every route and every table, for every role | The manual checks above cover the main path |
| Staff can write proposals and documents | Needs a team decision first |
| Grant and revoke functions, with an audit log | Staff can add members by hand until then |
| Screens: My organizations, org members, staff users | Same reason |
| Re-linking a recreated account with the same email | Rare; staff can fix it by hand |
| Email-domain matching, join requests, admins managing their own members | Phase 2 features |

## Every step

- `pytest -m "not integration"` and `ruff check .` pass.
- `pytest -m integration` too, when the database changes.
- `npm run build`, when the frontend changes.
