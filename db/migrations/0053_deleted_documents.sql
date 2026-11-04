-- Every deleted documents row, so a mistake can be undone without a hand-made backup schema (#307). A
-- trigger logs it, so no delete path can skip it; the vault and proposal deletes move the file to org-vault/trash/.
CREATE TABLE deleted_documents (
    id           bigserial PRIMARY KEY,
    document_id  bigint NOT NULL,
    org_id       bigint,
    old_row      jsonb NOT NULL,
    deleted_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    deleted_at   timestamptz NOT NULL DEFAULT now(),
    restored_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    restored_at  timestamptz
);
CREATE INDEX deleted_documents_recent ON deleted_documents (deleted_at DESC);

-- SECURITY DEFINER: the deletes run as the caller, who has no grant on this table.
CREATE FUNCTION app.log_document_delete() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    INSERT INTO deleted_documents (document_id, org_id, old_row, deleted_by)
    VALUES (OLD.id, OLD.org_id, to_jsonb(OLD), app.user_id());
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION app.log_document_delete() FROM PUBLIC;

CREATE TRIGGER log_document_delete AFTER DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION app.log_document_delete();

-- Staff-only, read through the owner pool like promotions; no grant to authenticated.
ALTER TABLE deleted_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY deleted_documents_staff ON deleted_documents FOR SELECT USING ((SELECT app.is_staff()));
