-- Two Supabase Storage buckets: the provenance archive for documents we fetch,
-- and the Doc Vault for documents an organisation uploads about itself.
--
-- Buckets separate ACCESS RULES; folders organise within them. That is why
-- there is not one bucket per funder: bucket names are immutable, each needs
-- its own policies, and creating one would become part of the ingest write
-- path. The two here differ in who may read them, which is what a bucket is for.
--
--   source-archive   <sha256(source_url)[:12]>/<sha256(bytes)>-<name>
--   org-vault        <org_id>/<sha256(bytes)>-<name>
--
-- The two are keyed differently because they are written at different moments.
-- An upload knows its org_id, and <org_id>/ is what the RLS policy will read
-- as (storage.foldername(name))[1]::bigint — an id rather than a slug because
-- _free_slug appends a suffix on collision and org_members joins on org_id.
-- migration 0005 already assumed '<org_id>/<file>' for exactly this.
--
-- The archive cannot use an entity id: fetch_document runs during research,
-- and a funder_id does not exist until resolve_funder runs at promotion. So it
-- keys on the URL, which is known at both moments, and on the content, so a
-- funder republishing at the same URL adds a version instead of replacing the
-- bytes a finding was read from. The entity link lives in documents.funder_id.
-- See docs/features/2026-09-30-supabase-storage.md.
--
-- The guard is load-bearing. Supabase provides the `storage` schema; the local
-- Postgres container does not, exactly as 0004 notes for `auth`. Without it
-- this file breaks `make migrate` for every local developer. Applied locally it
-- is a no-op that still records in schema_migrations, so the ledgers match.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    RAISE NOTICE 'no storage schema (not Supabase) - skipping bucket creation';
    RETURN;
  END IF;

  -- 50 MB is the Free-plan ceiling on the global limit; a per-bucket value may
  -- be lower than the global one but never higher. NOTE: fetch_document caps
  -- its download at 60 MB, so a 50-60 MB PDF downloads and then fails to
  -- archive. Raise both together, or not at all.
  --
  -- allowed_mime_types stays NULL on purpose. Servers hand back
  -- application/octet-stream for perfectly good PDFs, and a bucket-level
  -- refusal surfaces as an opaque upload failure. The check belongs in the
  -- upload path, where it can say what it rejected.
  INSERT INTO storage.buckets (id, name, public, file_size_limit)
  VALUES
    ('source-archive', 'source-archive', false, 52428800),
    ('org-vault',      'org-vault',      false, 52428800)
  ON CONFLICT (id) DO NOTHING;
END
$$;
