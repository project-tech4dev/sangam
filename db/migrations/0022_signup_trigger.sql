-- Create the users row when someone signs up in Supabase, instead of on their first request. Step 2 of
-- features-plans/access/auth-plan.md. The backend's resolve_auth_user stays as the fallback for anyone
-- this misses.

-- 1. auth.users is Supabase's. The local container has none, so it gets a stand-in with the columns the
-- triggers read; on Supabase the table exists and this is skipped. Guarded rather than IF NOT EXISTS:
-- Supabase denies CREATE on its auth schema, and Postgres checks that before it checks existence.
DO $$
BEGIN
  IF to_regclass('auth.users') IS NULL THEN
    CREATE SCHEMA IF NOT EXISTS auth;
    CREATE TABLE auth.users (
      id uuid PRIMARY KEY,
      email text,
      raw_user_meta_data jsonb NOT NULL DEFAULT '{}'
    );
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS app;

-- 2. On sign-up: link the row staff pre-created by email, or create one. A failure here would refuse the
-- sign-up itself, so every error is downgraded to a warning and the backend's fallback takes over.
CREATE FUNCTION app.on_auth_user_created() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_name text := coalesce(NEW.raw_user_meta_data ->> 'full_name', NEW.raw_user_meta_data ->> 'name');
BEGIN
  IF NEW.email IS NULL OR EXISTS (SELECT 1 FROM users WHERE auth_user_id = NEW.id) THEN
    RETURN NEW;
  END IF;

  UPDATE users SET auth_user_id = NEW.id, display_name = coalesce(display_name, v_name)
  WHERE email = NEW.email AND auth_user_id IS NULL;

  IF NOT FOUND THEN
    -- An email already linked to another Supabase account is left alone; the backend answers it with 409.
    INSERT INTO users (email, auth_user_id, display_name) VALUES (NEW.email, NEW.id, v_name)
    ON CONFLICT DO NOTHING;
  END IF;
  RETURN NEW;
EXCEPTION WHEN others THEN
  RAISE WARNING 'users row for auth user % not created: %', NEW.id, SQLERRM;
  RETURN NEW;
END $$;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION app.on_auth_user_created();

-- 3. On an email change in Supabase, keep users.email in step.
CREATE FUNCTION app.on_auth_user_email_changed() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  UPDATE users SET email = NEW.email WHERE auth_user_id = NEW.id;
  RETURN NEW;
EXCEPTION WHEN others THEN
  RAISE WARNING 'email of auth user % not synced: %', NEW.id, SQLERRM;
  RETURN NEW;
END $$;

CREATE TRIGGER on_auth_user_email_changed
  AFTER UPDATE OF email ON auth.users
  FOR EACH ROW WHEN (OLD.email IS DISTINCT FROM NEW.email AND NEW.email IS NOT NULL)
  EXECUTE FUNCTION app.on_auth_user_email_changed();

REVOKE ALL ON FUNCTION app.on_auth_user_created(), app.on_auth_user_email_changed() FROM public;
