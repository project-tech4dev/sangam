-- RFP Watch: where each funder lists its open calls, and an NGO's own "saved" on a matched call.
-- Purely additive: two nullable columns, and one more allowed status.
ALTER TABLE funders
  ADD COLUMN calls_url text,                 -- the one page listing open calls; staff may correct it by hand
  ADD COLUMN calls_url_found_at timestamptz;

ALTER TABLE rfp_matches DROP CONSTRAINT rfp_matches_status_check;
ALTER TABLE rfp_matches ADD CONSTRAINT rfp_matches_status_check
  CHECK (status IN ('flagged', 'saved', 'reviewed', 'dismissed'));
