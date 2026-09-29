-- Which years a run went looking for. A run that searched three years and found
-- one is a different result from a run that only ever asked about one.

ALTER TABLE ingest_runs ADD COLUMN fiscal_years text[] NOT NULL DEFAULT '{}';
