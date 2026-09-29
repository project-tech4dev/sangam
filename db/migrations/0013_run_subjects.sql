-- Which names a run researched. A run can be source-first ("pull the latest
-- from India CSR") or subject-first ("research these three funders"), and the
-- report has to say which it was months later.

ALTER TABLE ingest_runs ADD COLUMN subjects text[] NOT NULL DEFAULT '{}';
