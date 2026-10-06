-- An admin or member belongs to one org only; a steward supports as many as it is added to.
--
-- 1. The rule is an index rather than a check in the functions alone, so no path around them (Import, a staff
-- edit by hand) can break it either. Steward rows are left out of it.
CREATE UNIQUE INDEX org_members_one_org_per_person ON org_members (user_id)
  WHERE role IN ('admin', 'member');

-- 2. Raises when making p_user_id an admin or member of this org would give them a second such org. The index
-- refuses it anyway; this says so in words the person can act on.
CREATE FUNCTION app.assert_no_other_org(p_org_id bigint, p_user_id uuid, p_role text) RETURNS void
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF p_role IN ('admin', 'member') AND EXISTS (
    SELECT 1 FROM org_members
    WHERE user_id = p_user_id AND org_id <> p_org_id AND role IN ('admin', 'member')
  ) THEN
    RAISE EXCEPTION '% is already an admin or member of another organisation.',
      (SELECT email FROM users WHERE id = p_user_id);
  END IF;
END $$;

REVOKE ALL ON FUNCTION app.assert_no_other_org(bigint, uuid, text) FROM public;

-- 3. The two functions that can make someone an admin or member (0028) now ask it first. CREATE OR REPLACE
-- keeps their grants; only the PERFORM line is new in each, and add_org_member also finds only people who
-- have signed in: a users row with no auth_user_id is not an account yet.
CREATE OR REPLACE FUNCTION app.add_org_member(p_org_id bigint, p_email text, p_role text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_user uuid;
BEGIN
  IF NOT app.can_manage_org(p_org_id) THEN
    RAISE EXCEPTION 'Only an admin of this organisation can add members.' USING ERRCODE = '42501';
  END IF;
  SELECT id INTO v_user FROM users WHERE lower(email) = lower(trim(p_email)) AND auth_user_id IS NOT NULL;
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'No Sangam account uses %. They need to sign in once first.', trim(p_email);
  END IF;
  IF EXISTS (SELECT 1 FROM org_members WHERE org_id = p_org_id AND user_id = v_user) THEN
    RAISE EXCEPTION '% is already a member of this organisation.', trim(p_email);
  END IF;
  PERFORM app.assert_no_other_org(p_org_id, v_user, p_role);
  INSERT INTO org_members (user_id, org_id, role, added_by) VALUES (v_user, p_org_id, p_role, app.user_id());
  RETURN v_user;
END $$;

CREATE OR REPLACE FUNCTION app.set_org_member_role(p_org_id bigint, p_user_id uuid, p_role text) RETURNS void
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
  PERFORM app.assert_no_other_org(p_org_id, p_user_id, p_role);
  UPDATE org_members SET role = p_role WHERE org_id = p_org_id AND user_id = p_user_id;
END $$;
