-- Provenance on every fact table: as_of (the period the source describes),
-- document_id (the content file it was read from) and archive_url (a snapshot).
-- Derived from features-plans/data-model/db/init/02_schema.sql on
-- origin/docs/data-platform-architecture-spec. Purely additive.

ALTER TABLE orgs
  ADD COLUMN as_of text,
  ADD COLUMN archive_url text;

ALTER TABLE funders
  ADD COLUMN as_of text,
  ADD COLUMN archive_url text;

ALTER TABLE grants
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

ALTER TABLE rfps
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

ALTER TABLE programs
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

-- is_public: office bearers stay public, other contacts (funder staff) do not.
ALTER TABLE contacts
  ADD COLUMN is_public boolean NOT NULL DEFAULT false,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

-- is_current: false for a superseded number, e.g. an old 12A after re-registration.
ALTER TABLE org_identifiers
  ADD COLUMN is_current boolean NOT NULL DEFAULT true,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

ALTER TABLE funder_identifiers
  ADD COLUMN is_current boolean NOT NULL DEFAULT true,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN archive_url text;

-- Tag links: separate what a source states from what a person or model inferred.
ALTER TABLE org_tags
  ADD COLUMN is_inferred boolean NOT NULL DEFAULT false,
  ADD COLUMN tagged_by text,
  ADD COLUMN note text;
ALTER TABLE funder_tags
  ADD COLUMN is_inferred boolean NOT NULL DEFAULT false,
  ADD COLUMN tagged_by text,
  ADD COLUMN note text;
ALTER TABLE program_tags
  ADD COLUMN is_inferred boolean NOT NULL DEFAULT false,
  ADD COLUMN tagged_by text,
  ADD COLUMN note text;
ALTER TABLE rfp_tags
  ADD COLUMN is_inferred boolean NOT NULL DEFAULT false,
  ADD COLUMN tagged_by text,
  ADD COLUMN note text;

-- Place links: a link is itself a dated, sourced fact.
ALTER TABLE org_locations
  ADD COLUMN valid_from date,
  ADD COLUMN valid_to date,
  ADD COLUMN note text,
  ADD COLUMN source_url text,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;
ALTER TABLE funder_locations
  ADD COLUMN valid_from date,
  ADD COLUMN valid_to date,
  ADD COLUMN note text,
  ADD COLUMN source_url text,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;
ALTER TABLE program_locations
  ADD COLUMN valid_from date,
  ADD COLUMN valid_to date,
  ADD COLUMN note text,
  ADD COLUMN source_url text,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;
ALTER TABLE rfp_locations
  ADD COLUMN valid_from date,
  ADD COLUMN valid_to date,
  ADD COLUMN note text,
  ADD COLUMN source_url text,
  ADD COLUMN source_name text,
  ADD COLUMN fetched_at timestamptz,
  ADD COLUMN as_of text,
  ADD COLUMN document_id bigint REFERENCES documents(id),
  ADD COLUMN archive_url text;

-- "Who works here" is asked by place as often as by entity.
CREATE INDEX org_locations_location_idx ON org_locations (location_id);
CREATE INDEX funder_locations_location_idx ON funder_locations (location_id);
CREATE INDEX program_locations_location_idx ON program_locations (location_id);
CREATE INDEX rfp_locations_location_idx ON rfp_locations (location_id);
