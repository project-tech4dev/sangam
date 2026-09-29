-- What a researcher set out to find, kept next to what it found.
--
-- Goals are derived from the schema (app/ingest/expectations.py) and written
-- down before the searching starts, so a partial result reads as "eight of
-- fourteen fields" rather than as an unexplained stop. They are saved with the
-- findings, in one write — a researcher that dies before save_research leaves
-- its goals in the transcript only.
ALTER TABLE entity_research
  ADD COLUMN goals jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- 1 = flat label/value findings. 2 = typed per-concept findings, which are
  -- the only shape the catalog writers can map. Version 1 rows stay readable
  -- and render with a note; they are not migrated, they are re-researched.
  ADD COLUMN schema_version int NOT NULL DEFAULT 1;
