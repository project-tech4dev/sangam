-- 'Axis Bank' and 'Axis Bank Limited' are one funder. Resolving that is a
-- distinct match method from a trigram guess, and the run report should say so.

ALTER TABLE ingest_run_items DROP CONSTRAINT ingest_run_items_match_method_check;
ALTER TABLE ingest_run_items ADD CONSTRAINT ingest_run_items_match_method_check
  CHECK (match_method IN ('identifier', 'exact', 'alias', 'boilerplate', 'trigram', 'none'));
