-- Staff delete a Doc Vault upload (DELETE /api/documents/{id}, #306). The route runs as the caller, so the
-- database holds the same line require_staff does: only a private, org-owned vault upload, and only staff.
GRANT DELETE ON documents TO authenticated;

CREATE POLICY documents_delete ON documents FOR DELETE TO authenticated
  USING ((SELECT app.is_staff()) AND doc_type = 'vault_upload' AND NOT is_public AND org_id IS NOT NULL);
