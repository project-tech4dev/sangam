-- Local-dev auth stub user; app code resolves every request to this user until
-- Supabase JWT auth replaces backend/app/auth.py::get_current_user.
INSERT INTO users (id, email, display_name)
VALUES ('00000000-0000-0000-0000-000000000001', 'dev@sangam.local', 'Dev User')
ON CONFLICT (id) DO NOTHING;
