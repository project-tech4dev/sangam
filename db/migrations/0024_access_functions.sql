-- The access functions every RLS rule will call: who is calling, are they staff, which orgs they may read
-- and write, and which chats they may open. Step 5, piece 2 of features-plans/access/auth-plan.md; the roles
-- they serve are in features-plans/data-model/2026-10-02-roles.md.
--
-- Nothing calls them yet and the app still connects as the owner, so nothing changes for users.

-- 1. auth.uid() is Supabase's: the `sub` claim of the request's token. The local container has none, so it
-- gets a stand-in that reads the same settings; on Supabase the real one exists and is left alone.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'auth' AND p.proname = 'uid'
  ) THEN
    CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $f$
      SELECT coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), ''),
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
      )::uuid
    $f$;
  END IF;
END $$;

-- 2. About the caller only. SECURITY DEFINER so a rule can read users and org_members without the caller
-- being able to; a fixed search_path so that cannot be turned against them.

-- The caller's users.id; NULL when signed out or not yet linked.
CREATE FUNCTION app.user_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT id FROM users WHERE auth_user_id = auth.uid()
$$;

CREATE FUNCTION app.is_staff() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT coalesce((SELECT is_staff FROM users WHERE auth_user_id = auth.uid()), false)
$$;

-- Orgs whose private data the caller may read: member, admin and steward (Group Admin).
CREATE FUNCTION app.my_org_ids() RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.org_id FROM org_members m JOIN users u ON u.id = m.user_id
  WHERE u.auth_user_id = auth.uid()
$$;

-- Orgs the caller may write to: member and admin. A steward reads but never writes.
CREATE FUNCTION app.my_writable_org_ids() RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.org_id FROM org_members m JOIN users u ON u.id = m.user_id
  WHERE u.auth_user_id = auth.uid() AND m.role IN ('member', 'admin')
$$;

-- 3. May this user open this chat: the owner; the org's members and admins when it is shared with the team;
-- its stewards too when shared with them; staff always. A thread that does not exist is false.
--
-- It takes the user rather than reading the token because the backend calls it, and the backend connects
-- as the owner, where no token is set. For the same reason it is not granted to anon or authenticated:
-- answering about any user is a backend question, not one a caller may ask.
CREATE FUNCTION app.can_open_thread(p_thread_id text, p_user_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (
    SELECT 1 FROM threads t
    WHERE t.thread_id = p_thread_id
      AND (
        t.user_id = p_user_id
        OR EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND is_staff)
        OR EXISTS (
          SELECT 1 FROM org_members m
          WHERE m.user_id = p_user_id AND m.org_id = t.org_id
            AND (
              (t.visibility = 'team' AND m.role IN ('member', 'admin'))
              OR t.visibility = 'team_and_stewards'
            )
        )
      )
  )
$$;

-- 4. Who may call them. Functions are executable by everyone by default; make it explicit.
REVOKE ALL ON FUNCTION app.user_id(), app.is_staff(), app.my_org_ids(), app.my_writable_org_ids(),
  app.can_open_thread(text, uuid) FROM public;
GRANT USAGE ON SCHEMA app TO anon, authenticated;
GRANT EXECUTE ON FUNCTION app.user_id(), app.is_staff(), app.my_org_ids(), app.my_writable_org_ids()
  TO anon, authenticated;
