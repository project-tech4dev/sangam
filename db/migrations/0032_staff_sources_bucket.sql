-- A third private bucket, staff-sources: workbooks a staff member uploads by hand (statutory CSR
-- filing exports, and the CSO funder workbook shared under partner permission). Spec D8: staff only.
--
--   staff-sources   <registry key>/<sha256(file name)[:12]>.xlsx    the workbook, as uploaded
--
-- Each object has one documents row: doc_type 'source_dataset', is_public false, no org, no
-- funder, no content_md. documents_read (0027) and readable_document() already give such a row to
-- staff alone. The contents never enter the database, so the owner-run SQL tool cannot read them.
--
-- Guarded like 0020: the local container has no storage schema, so locally this is a no-op that
-- still records in schema_migrations. Number follows plan B's 0031; reassigned at merge if needed.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    RAISE NOTICE 'no storage schema (not Supabase) - skipping the staff-sources bucket';
    RETURN;
  END IF;

  -- 100 MB: one filing export is ~59 MB and is stored whole. storage.STAFF_SOURCES_MAX_BYTES matches.
  INSERT INTO storage.buckets (id, name, public, file_size_limit)
  VALUES ('staff-sources', 'staff-sources', false, 104857600)
  ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = EXCLUDED.file_size_limit;

  -- The app reads with the service key; this policy is only for a staff client reading directly.
  IF to_regprocedure('app.is_staff()') IS NULL THEN
    RAISE NOTICE 'app.is_staff() missing - staff-sources gets no read policy; only the service role reads it';
    RETURN;
  END IF;
  BEGIN
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'staff_sources_staff_read'
    ) THEN
      CREATE POLICY staff_sources_staff_read ON storage.objects FOR SELECT TO authenticated
        USING (bucket_id = 'staff-sources' AND (SELECT app.is_staff()));
    END IF;
  EXCEPTION WHEN insufficient_privilege THEN
    -- Fail closed: without the policy only the service role reads the bucket.
    RAISE NOTICE 'not permitted to add a policy on storage.objects - staff-sources stays service-role only';
  END;
END
$$;
