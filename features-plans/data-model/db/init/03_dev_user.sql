-- Local-dev auth stub user; app code resolves every request to this user until
-- Supabase JWT auth replaces backend/app/core/security.py::get_current_user.
-- Staff, so it can see hidden registry rows and private data locally.
INSERT INTO users (id, email, display_name, is_staff)
VALUES ('00000000-0000-0000-0000-000000000001', 'dev@sangam.local', 'Dev User', true)
ON CONFLICT (id) DO NOTHING;
