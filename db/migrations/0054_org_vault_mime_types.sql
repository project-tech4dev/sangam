-- org-vault takes only the types the Doc Vault reads (#307 §4); storage.VAULT_TYPES is the same list, and the
-- upload routes check the extension and the bytes as well. The browser sends the type the backend names, not its
-- own guess, which is why the octet-stream worry in 0020 does not apply here. org-vault-local follows when it exists.
--
-- Guarded like 0020: the local container has no storage schema.

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
