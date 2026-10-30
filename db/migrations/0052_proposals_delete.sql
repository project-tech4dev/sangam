-- Delete a proposal and its saved Word versions (DELETE /api/proposals/{id}, #307). The route runs as the
-- caller, so the database allows the same people who edit a proposal: the org's admins and stewards, and staff.
GRANT DELETE ON proposals TO authenticated;

CREATE POLICY proposals_delete ON proposals FOR DELETE TO authenticated
  USING (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff()));

-- A saved version is a private proposal_draft row; documents_delete (0051) stays staff-only for vault uploads.
CREATE POLICY documents_delete_draft ON documents FOR DELETE TO authenticated
  USING (doc_type = 'proposal_draft' AND NOT is_public AND org_id IS NOT NULL
         AND (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff())));
