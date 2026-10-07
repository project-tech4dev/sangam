-- An org's admins see and manage that org's members: who they are, their email and their role; add an
-- existing user by email, change a role, remove someone. Staff may do the same for any org. Members and
-- stewards still see only themselves and change nothing.
--
-- 1. Reads are RLS rules. Policies of one command OR together, so these only add rows to what users_read
-- and org_members_read (0027) already return.

-- Orgs the caller is an admin of. SECURITY DEFINER, like the other app.* functions, so the rules below can
-- read org_members without depending on the caller's own view of it.
CREATE FUNCTION app.my_admin_org_ids() RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.org_id FROM org_members m JOIN users u ON u.id = m.user_id
  WHERE u.auth_user_id = auth.uid() AND m.role = 'admin'
$$;

-- Users who belong to an org the caller is an admin of.
CREATE FUNCTION app.my_admin_org_member_ids() RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.user_id FROM org_members m WHERE m.org_id IN (SELECT app.my_admin_org_ids())
$$;

REVOKE ALL ON FUNCTION app.my_admin_org_ids(), app.my_admin_org_member_ids() FROM public;
GRANT EXECUTE ON FUNCTION app.my_admin_org_ids(), app.my_admin_org_member_ids() TO authenticated;

CREATE POLICY org_members_read_by_admin ON org_members FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_admin_org_ids()));

CREATE POLICY users_read_by_admin ON users FOR SELECT TO authenticated
  USING (id IN (SELECT app.my_admin_org_member_ids()));

-- 2. Writes go through functions rather than table grants: each one checks the caller itself, and an org
-- can never be left without an admin. SECURITY DEFINER, so they can read users by email, which the caller
-- cannot. Errors are raised with a message the API passes on as is.

-- May the caller manage this org's members?
CREATE FUNCTION app.can_manage_org(p_org_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT app.is_staff() OR p_org_id IN (SELECT app.my_admin_org_ids())
$$;

-- Raises when p_user_id is the org's last admin, so taking that away would leave it with none.
CREATE FUNCTION app.assert_other_admin(p_org_id bigint, p_user_id uuid) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM org_members WHERE org_id = p_org_id AND user_id = p_user_id AND role = 'admin')
     AND NOT EXISTS (
    SELECT 1 FROM org_members WHERE org_id = p_org_id AND role = 'admin' AND user_id <> p_user_id
  ) THEN
    RAISE EXCEPTION 'An organisation needs at least one admin.';
  END IF;
END $$;

CREATE FUNCTION app.add_org_member(p_org_id bigint, p_email text, p_role text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_user uuid;
BEGIN
  IF NOT app.can_manage_org(p_org_id) THEN
    RAISE EXCEPTION 'Only an admin of this organisation can add members.' USING ERRCODE = '42501';
  END IF;
  SELECT id INTO v_user FROM users WHERE lower(email) = lower(trim(p_email));
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'No Sangam account uses %. They need to sign in once first.', trim(p_email);
  END IF;
  IF EXISTS (SELECT 1 FROM org_members WHERE org_id = p_org_id AND user_id = v_user) THEN
    RAISE EXCEPTION '% is already a member of this organisation.', trim(p_email);
  END IF;
  INSERT INTO org_members (user_id, org_id, role, added_by) VALUES (v_user, p_org_id, p_role, app.user_id());
  RETURN v_user;
END $$;

CREATE FUNCTION app.set_org_member_role(p_org_id bigint, p_user_id uuid, p_role text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT app.can_manage_org(p_org_id) THEN
    RAISE EXCEPTION 'Only an admin of this organisation can change roles.' USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM org_members WHERE org_id = p_org_id AND user_id = p_user_id) THEN
    RAISE EXCEPTION 'That person is not a member of this organisation.' USING ERRCODE = 'P0002';
  END IF;
  IF p_role <> 'admin' THEN
    PERFORM app.assert_other_admin(p_org_id, p_user_id);
  END IF;
  UPDATE org_members SET role = p_role WHERE org_id = p_org_id AND user_id = p_user_id;
END $$;

CREATE FUNCTION app.remove_org_member(p_org_id bigint, p_user_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT app.can_manage_org(p_org_id) THEN
    RAISE EXCEPTION 'Only an admin of this organisation can remove members.' USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM org_members WHERE org_id = p_org_id AND user_id = p_user_id) THEN
    RAISE EXCEPTION 'That person is not a member of this organisation.' USING ERRCODE = 'P0002';
  END IF;
  PERFORM app.assert_other_admin(p_org_id, p_user_id);
  DELETE FROM org_members WHERE org_id = p_org_id AND user_id = p_user_id;
END $$;

REVOKE ALL ON FUNCTION app.can_manage_org(bigint), app.assert_other_admin(bigint, uuid),
  app.add_org_member(bigint, text, text), app.set_org_member_role(bigint, uuid, text),
  app.remove_org_member(bigint, uuid) FROM public;
GRANT EXECUTE ON FUNCTION app.add_org_member(bigint, text, text), app.set_org_member_role(bigint, uuid, text),
  app.remove_org_member(bigint, uuid) TO authenticated;
