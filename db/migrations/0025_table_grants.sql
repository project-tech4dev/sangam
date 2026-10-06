-- Which tables anon and authenticated may use at all. Step 5, piece 3 of features-plans/access/auth-plan.md.
--
-- A grant decides the table; which rows come back is RLS, step 7. So a table any page reads signed out is
-- granted to anon even when most of its rows will be private: the rule, not the grant, narrows it.
--
-- The app still connects as the owner, which ignores grants, so nothing changes for users yet.

-- 1. Start closed. Supabase grants both roles everything in public by default, which is what feeds its REST
-- API at /rest/v1/<table> with the publishable key every browser holds. Revoke it, and for tables and sequences
-- created later too, so a new table stays closed until a migration grants it. Functions are left alone:
-- pgvector's live in public and PUBLIC keeps EXECUTE on them whatever is revoked from these two roles.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
GRANT USAGE ON SCHEMA public TO anon, authenticated;

-- 2. Grant back, by kind. A name missing from this database (one that exists only on Supabase) is skipped.
DO $$
DECLARE
  -- Public, public unless hidden, public by flag: everyone may read, signed out or not.
  readable text[] := ARRAY[
    'orgs', 'org_locations', 'org_tags', 'org_identifiers', 'org_financials', 'credential_events',
    'funders', 'funder_csr_spend', 'funder_csr_years', 'funder_footprints', 'funder_identifiers',
    'funder_locations', 'funder_partners', 'funder_tags', 'funder_eligibility',
    'programs', 'program_locations', 'program_tags', 'grants', 'grant_locations',
    'rfps', 'rfp_locations', 'rfp_tags',
    'rubrics', 'rubric_criteria', 'fit_scores', 'fit_score_items', 'score_adjustments',
    'contacts', 'documents', 'chunks', 'news_mentions', 'metrics', 'reference_figures', 'extraction_log',
    'tags', 'locations', 'location_designations', 'proposal_templates', 'template_items'];
  -- Signed in only: org-private data, your own rows, and the Import tables (staff, by rule in step 7).
  signed_in text[] := ARRAY[
    'proposals', 'rfp_matches', 'users', 'org_members', 'threads',
    'ingest_runs', 'ingest_run_items', 'ingest_source_proposals', 'entity_research', 'resolution_queue'];
  -- Nobody through the app: every user's chat history, and infrastructure.
  closed text[] := ARRAY[
    'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations',
    'schema_migrations', 'graph_ingest_log'];
  t text;
  unclassified text;
BEGIN
  FOREACH t IN ARRAY readable LOOP
    IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT ON public.%I TO anon, authenticated', t);
    END IF;
  END LOOP;
  FOREACH t IN ARRAY signed_in LOOP
    IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    END IF;
  END LOOP;

  -- Every table here is placed on purpose; one that is not is a decision nobody made.
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO unclassified
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
    AND c.relname <> ALL (readable || signed_in || closed);
  IF unclassified IS NOT NULL THEN
    RAISE EXCEPTION 'tables with no access decision: %', unclassified;
  END IF;
END $$;

-- 3. The writes the API makes for a signed-in caller. Never anon. Import and research write as the owner.
GRANT INSERT, UPDATE ON contacts TO authenticated;          -- POST/PATCH /api/contacts
GRANT INSERT ON documents TO authenticated;                 -- POST /api/documents (vault upload)
GRANT INSERT ON score_adjustments TO authenticated;         -- POST /api/scores/{id}/adjustments
GRANT UPDATE ON rfp_matches TO authenticated;               -- PATCH /api/rfps/{id}/matches/{org_id}
GRANT INSERT, UPDATE ON proposals TO authenticated;         -- an org's own drafts
GRANT INSERT ON threads TO authenticated;                   -- claiming a new chat
GRANT USAGE ON SEQUENCE contacts_id_seq, documents_id_seq, score_adjustments_id_seq, proposals_id_seq
  TO authenticated;
