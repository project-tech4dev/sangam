-- Places: codes and aliases so districts match across sources, designations
-- (aspirational district, North East), and where a grant was actually spent.
-- Unblocks: db/seed/reference_data.sql and the seed.py district-parent fix.

ALTER TABLE locations
  ADD COLUMN lgd_code text,
  ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';

ALTER TABLE locations DROP CONSTRAINT locations_kind_check;
ALTER TABLE locations ADD CONSTRAINT locations_kind_check
  CHECK (kind IN ('country', 'region', 'state', 'district', 'block', 'village'));

CREATE UNIQUE INDEX locations_lgd_uniq ON locations (kind, lgd_code) WHERE lgd_code IS NOT NULL;
CREATE INDEX locations_aliases_idx ON locations USING gin (aliases);
CREATE INDEX locations_parent_idx ON locations (parent_id);

-- A funder's stated geography is a priority, not evidence of funding; where it
-- actually funded comes from grant_locations. The 14 seeded rows came from the
-- hand-vetting profiles' "geographies" lists, which describe stated focus.
ALTER TABLE funder_locations DROP CONSTRAINT funder_locations_role_check;
ALTER TABLE funder_locations ADD CONSTRAINT funder_locations_role_check
  CHECK (role IN ('registered', 'operates', 'funds', 'priority'));
ALTER TABLE funder_locations ALTER COLUMN role SET DEFAULT 'priority';
UPDATE funder_locations SET role = 'priority', note = 'stated focus; re-labelled from funds, review'
  WHERE role = 'funds';

CREATE TABLE location_designations (
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  designation text NOT NULL,
  programme text,
  list_rank int,
  name_as_listed text,                             -- e.g. 'Mewat' (now Nuh)
  valid_from date,
  valid_to date,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (location_id, designation)
);
CREATE INDEX location_designations_designation_idx ON location_designations (designation);

CREATE TABLE grant_locations (
  grant_id bigint NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (grant_id, location_id)
);
CREATE INDEX grant_locations_location_idx ON grant_locations (location_id);
