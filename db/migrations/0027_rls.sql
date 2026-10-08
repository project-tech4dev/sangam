-- Which rows anon and authenticated see: one RLS rule per kind of table. Step 7 of
-- features-plans/access/auth-plan.md; the kinds are "Which rule each table gets" in
-- features-plans/data-model/2026-10-02-roles.md.
--
-- 0025 decided which tables each role may use; this decides which rows. Routes run as the caller since
-- step 6, so this changes what they return. The owner bypasses RLS, so the agent tools, Import and the
-- seeds see everything until step 8.
--
-- Every app.* call is wrapped in (SELECT ...) so Postgres evaluates it once per query, not once per row.

-- 1. RLS on for every table, the closed ones included: with no policy, a role that is ever granted one by
-- mistake still reads nothing.
DO $$
DECLARE
  t text;
BEGIN
  FOR t IN
    SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- 2. Rules that differ only in their table, by kind. A name missing from this database is skipped, as in 0025.
DO $$
DECLARE
  -- Public: every row, signed out or not.
  public_rows text[] := ARRAY[
    'programs', 'program_locations', 'program_tags', 'grants', 'grant_locations',
    'rfps', 'rfp_locations', 'rfp_tags',
    'rubrics', 'rubric_criteria', 'fit_scores', 'fit_score_items', 'score_adjustments',
    'credential_events', 'news_mentions', 'metrics', 'reference_figures', 'extraction_log',
    'tags', 'locations', 'location_designations', 'proposal_templates', 'template_items'];
  -- Follows its org: a row of a hidden org is as hidden as the org. The EXISTS reads orgs as the caller, so
  -- the orgs rule below decides.
  org_children text[] := ARRAY['org_locations', 'org_tags', 'org_financials'];
  funder_children text[] := ARRAY[
    'funder_csr_spend', 'funder_csr_years', 'funder_footprints', 'funder_identifiers',
    'funder_locations', 'funder_partners', 'funder_tags', 'funder_eligibility'];
  -- Staff only: Sangam Import.
  staff_only text[] := ARRAY[
    'ingest_runs', 'ingest_run_items', 'ingest_source_proposals', 'entity_research', 'resolution_queue'];
  t text;
BEGIN
  FOREACH t IN ARRAY public_rows LOOP
    CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT TO anon, authenticated USING (true)', t || '_read', t);
  END LOOP;
  FOREACH t IN ARRAY org_children LOOP
    CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT TO anon, authenticated '
      'USING (EXISTS (SELECT 1 FROM public.orgs o WHERE o.id = org_id))', t || '_read', t);
  END LOOP;
  FOREACH t IN ARRAY funder_children LOOP
    CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT TO anon, authenticated '
      'USING (EXISTS (SELECT 1 FROM public.funders f WHERE f.id = funder_id))', t || '_read', t);
  END LOOP;
  FOREACH t IN ARRAY staff_only LOOP
    CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT TO authenticated USING ((SELECT app.is_staff()))',
      t || '_read', t);
  END LOOP;
END $$;

-- 3. Public unless hidden. An org's own people still see it, so /api/me keeps listing their membership.
CREATE POLICY orgs_read ON orgs FOR SELECT TO anon, authenticated
  USING (registry_status <> 'hidden' OR id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY funders_read ON funders FOR SELECT TO anon, authenticated
  USING (registry_status <> 'hidden' OR (SELECT app.is_staff()));

-- 4. Public by flag: public rows to everyone, the rest to that org's people and staff. A private funder
-- contact has no org, so only staff see it.
CREATE POLICY contacts_read ON contacts FOR SELECT TO anon, authenticated
  USING (is_public OR org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY documents_read ON documents FOR SELECT TO anon, authenticated
  USING (is_public OR org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY org_identifiers_read ON org_identifiers FOR SELECT TO anon, authenticated
  USING (is_public OR org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

-- A chunk is as private as its document: a private vault upload must not come back through search.
CREATE POLICY chunks_read ON chunks FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = document_id));

-- 5. Org-private: that org's people and staff. 0025 granted these to authenticated only.
CREATE POLICY proposals_read ON proposals FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY rfp_matches_read ON rfp_matches FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));

-- 6. Own rows. A chat shared with the team opens for its members and admins, one shared with stewards for
-- every role in the org: the same answer as app.can_open_thread, which callers may not execute.
CREATE POLICY users_read ON users FOR SELECT TO authenticated
  USING (id = (SELECT app.user_id()) OR (SELECT app.is_staff()));

CREATE POLICY org_members_read ON org_members FOR SELECT TO authenticated
  USING (user_id = (SELECT app.user_id()) OR (SELECT app.is_staff()));

CREATE POLICY threads_read ON threads FOR SELECT TO authenticated
  USING (
    user_id = (SELECT app.user_id())
    OR (SELECT app.is_staff())
    OR (visibility = 'team' AND org_id IN (SELECT app.my_writable_org_ids()))
    OR (visibility = 'team_and_stewards' AND org_id IN (SELECT app.my_org_ids()))
  );

-- 7. Writes, one per grant 0025 made: to an org the caller may write to (member or admin, never a steward).
-- Staff too wherever a route already lets them; proposals have no route yet, and whether staff write them is
-- open (Part 2 of the plan).
CREATE POLICY contacts_insert ON contacts FOR INSERT TO authenticated
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()));
CREATE POLICY contacts_update ON contacts FOR UPDATE TO authenticated
  USING (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()))
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY documents_insert ON documents FOR INSERT TO authenticated
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY score_adjustments_insert ON score_adjustments FOR INSERT TO authenticated
  WITH CHECK (EXISTS (
    SELECT 1 FROM fit_scores s
    WHERE s.id = fit_score_id
      AND (s.org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()))
  ));

CREATE POLICY rfp_matches_update ON rfp_matches FOR UPDATE TO authenticated
  USING (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()))
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()) OR (SELECT app.is_staff()));

CREATE POLICY proposals_insert ON proposals FOR INSERT TO authenticated
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()));
CREATE POLICY proposals_update ON proposals FOR UPDATE TO authenticated
  USING (org_id IN (SELECT app.my_writable_org_ids()))
  WITH CHECK (org_id IN (SELECT app.my_writable_org_ids()));

CREATE POLICY threads_insert ON threads FOR INSERT TO authenticated
  WITH CHECK (user_id = (SELECT app.user_id()));

-- 8. A table either role may read with no rule returns no rows and no error: a page that silently goes
-- empty. Fail here instead.
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
