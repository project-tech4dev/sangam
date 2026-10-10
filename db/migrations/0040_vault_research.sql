-- What Import's vault-reader found in one organisation's Doc Vault, kept apart from entity_research:
-- that row is shared by everyone researching the entity, and these findings belong to one org.
CREATE TABLE vault_research (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug           text NOT NULL,
    org_id         bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    entity_name    text NOT NULL,
    entity_kind    text NOT NULL,
    findings       jsonb NOT NULL DEFAULT '[]'::jsonb,
    gaps           jsonb NOT NULL DEFAULT '[]'::jsonb,
    documents_read bigint[] NOT NULL DEFAULT '{}',
    fact_count     integer NOT NULL DEFAULT 0,
    researched_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    researched_on  date NOT NULL DEFAULT current_date,
    researched_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (slug, researched_on, org_id)
);
CREATE INDEX vault_research_slug ON vault_research (slug, researched_at DESC);

-- Staff and the org's own people; Import reads it on the owner pool and checks the caller itself.
ALTER TABLE vault_research ENABLE ROW LEVEL SECURITY;
CREATE POLICY vault_research_read ON vault_research FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));
