# Access plan: sign-in, roles and RLS

Status: draft. The roles, the access functions and the end-to-end flow are in
[`../data-model/2026-10-02-roles.md`](../data-model/2026-10-02-roles.md). This file is the order we
build it in.

The plan does the minimum first: everything is built on one branch, one step at a time. Each step
changes one thing, has a quick check, and leaves the branch working.
Fuller tests and the extras come later, in their own PRs (Part 2).

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

**What changes:** one migration adds the `app.*` functions and removes Supabase's default access to
every table, then grants access table by table. The app still connects as the owner, so **nothing
changes for users yet**.

**How to test**
- `make migrate`.
- As a member and as staff, `app.my_org_ids()` returns the orgs you expect.

### Step 6: Requests run as the caller

**What changes**
- One middleware handles the token for every request: it reads `Authorization`, checks the token,
  finds or creates the `users` row, and keeps who is calling for the rest of the request. It does this
  as the owner, because it writes `users` rows no caller may write.
- `get_pool()` returns the pool as that caller: `anon` when signed out, `authenticated` with their
  claims when signed in. Routers keep `pool: PoolDep`, so no route file changes and a new route runs
  as the caller without having to ask.
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

**What changes:** RLS is turned on, with one rule per kind of table (see "Which rule each table gets"
in the roles doc).

**How to test:** open the same org page as a member of Org A, a member of Org B, and staff. Each sees
only what they should.

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
