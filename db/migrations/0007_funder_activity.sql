-- What a funder actually did, per fiscal year: the statutory CSR return, spend
-- by sector and place, where each theme ran, and who it named as a partner.
-- Unblocks: db/seed/funders/axis_bank.sql and axis_bank_disclosures.sql.
--
-- fiscal_year is text (a period label, not a date). v3 leaves it unvalidated;
-- the format CHECK here is a deliberate addition so 'FY24' and 'FY2023-2024'
-- cannot enter the same column.

ALTER TABLE funders ADD COLUMN parent_id bigint REFERENCES funders(id);
CREATE INDEX funders_parent_idx ON funders (parent_id);

-- A funder's own themes, programmes and phases are programs rows it owns.
ALTER TABLE programs
  ADD COLUMN parent_id bigint REFERENCES programs(id),
  ADD COLUMN kind text NOT NULL DEFAULT 'programme'
    CHECK (kind IN ('theme', 'programme', 'phase', 'project')),
  ADD COLUMN is_enabler boolean NOT NULL DEFAULT false;

CREATE TABLE funder_csr_years (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY[0-9]{4}-[0-9]{2}$'),
  section_135_applicable boolean,
  -- Items 5 and 6 of the statutory Annual Report on CSR Activities, INR.
  average_net_profit numeric,                      -- 5(a), per Section 135(5)
  prescribed_csr numeric,                          -- 5(b), the 2% obligation
  spent_on_projects numeric,                       -- 6(a), ongoing and other projects
  admin_overheads numeric,                         -- 6(b)
  impact_assessment_cost numeric,                  -- 6(c)
  total_spent numeric,                             -- 6(d)
  unspent_transferred numeric,                     -- 6(e), moved to the Unspent CSR Account
  excess_spent numeric,                            -- 6(f), available for set-off
  impact_assessment_done boolean,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (funder_id, fiscal_year)
);

-- A row is either an aggregate (project_name NULL) or one project.
CREATE TABLE funder_csr_spend (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY[0-9]{4}-[0-9]{2}$'),
  program_id bigint REFERENCES programs(id),       -- the funder's theme, when known
  csr_sector_id bigint REFERENCES tags(id),        -- a csr_sector tag (group or sector)
  state_location_id bigint REFERENCES locations(id),
  district_location_id bigint REFERENCES locations(id),
  designation text,                                -- spend limited to places with this designation,
                                                   -- e.g. 'aspirational_district' (BRSR Principle 8)
  project_name text,
  implementing_agency text,                        -- as printed
  agency_csr1 text,                                -- the agency's CSR-1 number
  agency_org_id bigint REFERENCES orgs(id),        -- set when the agency is in the registry
  via_agency boolean,                              -- false = implemented directly
  is_ongoing boolean,
  amount numeric NOT NULL,                         -- INR
  project_count int,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, fiscal_year, program_id, csr_sector_id, state_location_id,
                             district_location_id, designation, project_name)
);
CREATE INDEX funder_csr_spend_agency_idx ON funder_csr_spend (agency_org_id) WHERE agency_org_id IS NOT NULL;
CREATE INDEX funder_csr_spend_state_idx ON funder_csr_spend (state_location_id, fiscal_year);
CREATE INDEX funder_csr_spend_district_idx ON funder_csr_spend (district_location_id, fiscal_year);

-- Where a theme actually ran: the strongest geographic matching signal.
CREATE TABLE funder_footprints (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY[0-9]{4}-[0-9]{2}$'),
  location_id bigint NOT NULL REFERENCES locations(id),
  name_as_printed text,                            -- e.g. 'Kamrup Metropolitan'
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, program_id, fiscal_year, location_id)
);
CREATE INDEX funder_footprints_location_idx ON funder_footprints (location_id, fiscal_year);

-- partner_canonical is one spelling per partner, so renewals can be counted
-- when the partner is not in the registry ('Peepul' and 'Peepul Trust').
CREATE TABLE funder_partners (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY[0-9]{4}-[0-9]{2}$'),
  partner_name text NOT NULL,                      -- as printed in the source
  partner_canonical text,
  org_id bigint REFERENCES orgs(id),               -- set when the partner is in the registry
  partner_funder_id bigint REFERENCES funders(id), -- set when the partner is itself a funder
  partner_csr1 text,
  partner_kind text CHECK (partner_kind IN ('ngo', 'foundation', 'university', 'research', 'government',
                                            'armed_forces', 'hospital', 'network', 'company', 'other')),
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, program_id, fiscal_year, partner_name)
);
CREATE INDEX funder_partners_org_idx ON funder_partners (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX funder_partners_canonical_idx ON funder_partners (funder_id, partner_canonical);
