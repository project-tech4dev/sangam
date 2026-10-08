-- What a research run looked for and did not get, and the years it was asked to cover, so the
-- coverage report can say "blocked" or "not stated" rather than read every absence as "not attempted".
ALTER TABLE entity_research
    ADD COLUMN gaps  jsonb  NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN years text[] NOT NULL DEFAULT '{}';
