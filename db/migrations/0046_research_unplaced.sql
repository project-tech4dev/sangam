-- Facts a source states that no concept has a field for (schema v3): kept so the brief shows them,
-- and counted to decide which column to add next.
ALTER TABLE entity_research
    ADD COLUMN unplaced jsonb NOT NULL DEFAULT '[]'::jsonb;
