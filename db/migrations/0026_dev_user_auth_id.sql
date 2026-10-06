-- The seeded dev user has no Supabase account, so nothing links it to a token and the access functions
-- would see it as nobody once requests run as the caller (step 6 of features-plans/access/auth-plan.md).
-- Give it an auth_user_id equal to its own id, which the backend sends as the `sub` claim for the dev user.
-- No real Supabase account has this id, so it can never be signed into.
UPDATE users SET auth_user_id = id
WHERE id = '00000000-0000-0000-0000-000000000001' AND auth_user_id IS NULL;
