-- metrics was the one funder-side fact table with no unique constraint, so
-- re-reading the same annual report grew a second copy of every figure rather
-- than updating the first. The key matches what app/ingest/writer.py already
-- treats as a metric's identity.
--
-- NULLS NOT DISTINCT because period and program_id are usually null: without
-- it Postgres treats every such row as unique and the constraint does nothing.
CREATE UNIQUE INDEX metrics_funder_identity
  ON metrics (funder_id, name, period, program_id) NULLS NOT DISTINCT
  WHERE funder_id IS NOT NULL;

CREATE UNIQUE INDEX metrics_org_identity
  ON metrics (org_id, name, period, program_id) NULLS NOT DISTINCT
  WHERE org_id IS NOT NULL;
