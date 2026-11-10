-- What each document backs: its owner, programme and fiscal year, and the pages facts were read from.
-- Written by Import's promotion from every fact it wrote or confirmed. Purely additive.
CREATE TABLE document_links (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  fiscal_year text,
  pages text[] NOT NULL DEFAULT '{}',            -- as each fact cites it: 'p.33', 'Annexure 4'
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  UNIQUE NULLS NOT DISTINCT (document_id, org_id, funder_id, program_id, fiscal_year)
);
CREATE INDEX document_links_org_idx ON document_links (org_id);
CREATE INDEX document_links_funder_idx ON document_links (funder_id);
CREATE INDEX document_links_program_idx ON document_links (program_id);

-- A link is as private as its document, as chunks are (0027).
ALTER TABLE document_links ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON document_links TO anon, authenticated;
CREATE POLICY document_links_read ON document_links FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = document_id));

-- Logged like every table a save writes (0041), so undoing a save removes its links.
CREATE TRIGGER log_catalog_write AFTER INSERT OR UPDATE ON document_links
  FOR EACH ROW EXECUTE FUNCTION app.log_catalog_write();
