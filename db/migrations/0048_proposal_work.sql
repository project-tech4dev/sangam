-- Proposals on the server (docs/features/2026-10-14-proposal-copilot.md, M1). `work` is everything the
-- proposal screen and its agent edit; `summary` is what the list shows, recomputed from `work` on every save.
ALTER TABLE proposals
  ADD COLUMN work    jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN summary jsonb NOT NULL DEFAULT '{}'::jsonb;

-- The people who may save a Funder Match run start and write a proposal: admins, stewards and staff.
-- Members still read (proposals_read is unchanged) and no longer write.
ALTER POLICY proposals_insert ON proposals
  WITH CHECK (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff()));
ALTER POLICY proposals_update ON proposals
  USING (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff()))
  WITH CHECK (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff()));

-- A steward adds the files a proposal draws on, so a Doc Vault upload is open to every role in the org.
ALTER POLICY documents_insert ON documents
  WITH CHECK (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

-- 0027's guard, again: no readable table may be left without a read rule.
DO $$
DECLARE
  missing text;
BEGIN
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO missing
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    AND (has_table_privilege('anon', c.oid, 'SELECT') OR has_table_privilege('authenticated', c.oid, 'SELECT'))
    AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polcmd IN ('r', '*'));
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'readable tables with no RLS rule: %', missing;
  END IF;
END $$;
