-- Columns for facts Import already researches and had nowhere to put. Purely additive bar one CHECK, which
-- only widens programs.kind.
--   funders            + legal_form, founded_year, registered_address, registered_location_id
--   orgs               + registered_address, parent_id (an NGO's parent body, linked only when it resolves)
--   org_locations      + program_id: the programme that brings the NGO to the place
--   funder_activity    + source_type, evidence: the tier a partner line carried in notes until now
--   programs.kind      + 'component': a part of a programme a funder reports spend on

ALTER TABLE funders
  ADD COLUMN legal_form text,                     -- free text as printed, e.g. 'Section 8 Company'
  ADD COLUMN founded_year integer CHECK (founded_year BETWEEN 1800 AND 2100),
  ADD COLUMN registered_address text,
  ADD COLUMN registered_location_id bigint REFERENCES locations(id);

ALTER TABLE orgs
  ADD COLUMN registered_address text,
  ADD COLUMN parent_id bigint REFERENCES orgs(id) CHECK (parent_id <> id);

ALTER TABLE org_locations
  ADD COLUMN program_id bigint REFERENCES programs(id) ON DELETE SET NULL;

ALTER TABLE funder_activity
  ADD COLUMN source_type text CHECK (source_type IN ('registry', 'org_document', 'funder', 'staff_dataset',
                                                     'manual_check', 'prior_research', 'aggregator', 'seed')),
  ADD COLUMN evidence text CHECK (evidence IN ('evidenced', 'claimed')),
  ADD CONSTRAINT funder_activity_tier_pair CHECK ((source_type IS NULL) = (evidence IS NULL)),
  ADD CONSTRAINT funder_activity_unverifiable_claimed CHECK (
    source_type IS NULL OR source_type NOT IN ('aggregator', 'prior_research') OR evidence = 'claimed');

ALTER TABLE programs DROP CONSTRAINT programs_kind_check;
ALTER TABLE programs ADD CONSTRAINT programs_kind_check
  CHECK (kind IN ('theme', 'programme', 'component', 'phase', 'project'));

CREATE INDEX funders_registered_location_idx ON funders (registered_location_id);
CREATE INDEX orgs_parent_idx ON orgs (parent_id);
CREATE INDEX org_locations_program_idx ON org_locations (program_id);
