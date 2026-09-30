-- Two Supabase Storage buckets: the provenance archive for documents we fetch,
-- and the Doc Vault for documents an organisation uploads about itself.
--
-- Buckets separate ACCESS RULES; folders organise within them. That is why
-- there is not one bucket per funder: bucket names are immutable, each needs
-- its own policies, and creating one would become part of the ingest write
-- path. The two here differ in who may read them, which is what a bucket is for.
--
--   source-archive   funders/<funder_id>/<sha256[:12]>-<name>
--                    orgs/<org_id>/<sha256[:12]>-<name>
--   org-vault        <org_id>/<sha256[:12]>-<name>
--
-- Keyed by id, not slug: _free_slug appends a suffix on collision so a slug
-- depends on insertion order, and org_members joins on org_id. The RLS policy
-- will read (storage.foldername(name))[1]::bigint, so this path convention IS
-- the access design — see docs/features/2026-09-30-supabase-storage.md.
-- documents.storage_path (migration 0005) already assumed '<org_id>/<file>'.
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
