-- A refresh that removes a fact names it here (brief.fact_key, as a JSON array), so merging older rows
-- into the brief does not bring it back.
ALTER TABLE entity_research ADD COLUMN supersedes jsonb NOT NULL DEFAULT '[]'::jsonb;
