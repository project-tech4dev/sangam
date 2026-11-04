-- org-vault takes PowerPoint (.pptx) too, so earlier slide decks can be imported. The whole list again, as in 0054:
-- storage.VAULT_TYPES is the same list, and test_storage holds the two together.
--
-- Guarded like 0054: the local container has no storage schema.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'storage') THEN
    RAISE NOTICE 'no storage schema (not Supabase) - skipping the org-vault type list';
    RETURN;
  END IF;

  UPDATE storage.buckets
  SET allowed_mime_types = ARRAY[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/csv',
    'text/markdown',
    'text/plain',
    'image/png',
    'image/jpeg',
    'image/webp'
  ]
  WHERE id IN ('org-vault', 'org-vault-local');
END
$$;
