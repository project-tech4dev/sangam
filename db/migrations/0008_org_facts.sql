-- An org's money per year, and its impact figures as results chains rather than
-- headline numbers. Unblocks: db/seed/orgs/kabil_impact.sql.

CREATE TABLE org_financials (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY[0-9]{4}-[0-9]{2}$'),
  total_income numeric,                            -- INR
  program_spend numeric,
  non_program_spend numeric,
  foreign_contribution numeric,
  is_audited boolean,
  notes text,
  source_url text, source_name text, fetched_at timestamptz,
  as_of text, document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE (org_id, fiscal_year)
);

-- Rows sharing a chain_key form one results chain: trained, adopted, income up,
-- sustained after two years, compared with similar households, SROI.
CREATE TABLE metrics (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  grant_id bigint REFERENCES grants(id) ON DELETE CASCADE,
  location_id bigint REFERENCES locations(id),
  name text NOT NULL,
  value numeric,
  target numeric,
  CHECK (value IS NOT NULL OR target IS NOT NULL),
  unit text,
  period text,                                     -- 'FY2023-24', 'cumulative to 2026'
  stage text CHECK (stage IN ('input', 'output', 'adoption', 'outcome',
                              'sustained_outcome', 'impact', 'sroi')),
  chain_key text,
  sequence int,                                    -- position in the chain
  baseline numeric,                                -- value before the intervention
  comparison_value numeric,                        -- value for comparable households
  method text CHECK (method IN ('self_reported', 'monitoring_data', 'survey', 'comparison_study',
                                'third_party_evaluation', 'estimate')),
  is_self_reported boolean NOT NULL DEFAULT true,
  notes text,
  source_url text, source_name text, fetched_at timestamptz,
  as_of text, document_id bigint REFERENCES documents(id), archive_url text
);
CREATE INDEX metrics_org_idx ON metrics (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX metrics_funder_idx ON metrics (funder_id) WHERE funder_id IS NOT NULL;
CREATE INDEX metrics_chain_idx ON metrics (chain_key, sequence) WHERE chain_key IS NOT NULL;
