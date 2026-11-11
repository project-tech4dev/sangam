-- The Registry counts each entity's research runs through these two columns (#341); the slug side already
-- has UNIQUE (slug, researched_on). Partial, since most runs resolve to one kind or the other.
CREATE INDEX IF NOT EXISTS entity_research_resolved_org ON entity_research (resolved_org_id)
  WHERE resolved_org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_research_resolved_funder ON entity_research (resolved_funder_id)
  WHERE resolved_funder_id IS NOT NULL;
