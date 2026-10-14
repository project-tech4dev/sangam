-- Empty every table, keep the schema and the migration ledger.
-- For starting a data run from nothing: `make db-clean`, then `make seed` or an import.

DO $$
DECLARE names text;
BEGIN
  -- schema_migrations is the record that the schema itself is already applied;
  -- dropping it would make `make migrate` try to replay every migration.
  SELECT string_agg(format('%I', tablename), ', ')
    INTO names
  FROM pg_tables
  WHERE schemaname = 'public' AND tablename <> 'schema_migrations';
  EXECUTE format('TRUNCATE TABLE %s RESTART IDENTITY CASCADE', names);
END $$;

-- The local dev user has to come back: every request resolves to it.
INSERT INTO users (id, email, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'dev@sangam.local', 'Dev User')
ON CONFLICT (id) DO NOTHING;

-- Staff, and with 0026's auth_user_id, which RLS's access functions match the `sub` claim on.
-- Guarded because db/init/03_dev_user.sql predates the columns migration 0004 adds.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'is_staff') THEN
    UPDATE users SET is_staff = true, auth_user_id = id
    WHERE id = '00000000-0000-0000-0000-000000000001';
  END IF;
END $$;
