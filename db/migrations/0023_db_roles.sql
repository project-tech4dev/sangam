-- The two roles a request will run as: anon (signed out) and authenticated (signed in). Step 5, piece 1
-- of features-plans/access/auth-plan.md.
--
-- Supabase creates both; the local container has neither, so they are created here only when missing, with
-- Supabase's attributes: NOLOGIN, because nobody connects as them, the backend switches to them with
-- SET ROLE; NOINHERIT, so they hold only what is granted to them by name.
--
-- Nothing is granted to them yet and the app still connects as the owner, so nothing changes for users.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;

  -- SET ROLE needs the connecting role to be a member. A superuser (the local container) already counts
  -- as one, and so does Supabase's postgres, so this only fires on a database set up some other way.
  IF NOT pg_has_role(current_user, 'anon', 'MEMBER') THEN
    EXECUTE format('GRANT anon TO %I', current_user);
  END IF;
  IF NOT pg_has_role(current_user, 'authenticated', 'MEMBER') THEN
    EXECUTE format('GRANT authenticated TO %I', current_user);
  END IF;
END $$;
