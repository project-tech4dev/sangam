-- RFP Watch: an org may save a call. "Not for us" stays 'dismissed'.
ALTER TABLE rfp_matches DROP CONSTRAINT rfp_matches_status_check,
  ADD CONSTRAINT rfp_matches_status_check CHECK (status IN ('flagged', 'saved', 'reviewed', 'dismissed'));
