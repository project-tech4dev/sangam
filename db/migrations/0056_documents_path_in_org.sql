-- A signed-in caller's documents row may only name a file in its own org's vault folder (#329).
-- storage_path is `<bucket>/<key>` and a vault key is `<org_id>/...`, so the row's org must be the key's first
-- segment. Library, staff-dataset and seed rows are written on the owner pool, which RLS does not reach.
-- Insert only: authenticated has no UPDATE on documents, so there is no update policy to tighten.
ALTER POLICY documents_insert ON documents
  WITH CHECK (
    (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()))
    AND (storage_path IS NULL OR starts_with(storage_path, 'org-vault/' || org_id::text || '/'))
  );
