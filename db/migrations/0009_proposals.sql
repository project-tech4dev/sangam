-- A funder's form broken into checkable items, the proposals an org is
-- preparing, and the external benchmarks a budget is argued against.
-- Unblocks: db/seed/funders/sbi_foundation_gramseva.sql.

CREATE TABLE proposal_templates (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  rfp_id bigint REFERENCES rfps(id) ON DELETE CASCADE,
  name text NOT NULL,
  kind text NOT NULL
    CHECK (kind IN ('application', 'rfp', 'due_diligence', 'budget', 'reporting', 'site_visit')),
  version text,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text
);
-- coalesce, because a template may hang off a funder, an RFP, or both.
CREATE UNIQUE INDEX proposal_templates_uniq
  ON proposal_templates (coalesce(funder_id, 0), coalesce(rfp_id, 0), name);

-- check_rule is a rule the database can test (credential, document, min_income,
-- in_rfp_geography, has_stage, ...); NULL means a person or the agent judges it.
CREATE TABLE template_items (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  template_id bigint NOT NULL REFERENCES proposal_templates(id) ON DELETE CASCADE,
  ord int NOT NULL,
  item_kind text NOT NULL
    CHECK (item_kind IN ('section', 'question', 'criterion', 'eligibility', 'document')),
  code text,                                       -- the template's own numbering, e.g. 'A7'
  heading text NOT NULL,
  guidance text,
  word_limit int,
  char_limit int,
  points numeric,                                  -- marks, when the funder publishes them
  required boolean NOT NULL DEFAULT true,
  check_rule jsonb,
  UNIQUE (template_id, ord)
);

CREATE TABLE proposals (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id),
  rfp_id bigint REFERENCES rfps(id),
  template_id bigint REFERENCES proposal_templates(id),
  title text NOT NULL,
  status text NOT NULL DEFAULT 'drafting'
    CHECK (status IN ('drafting', 'ready', 'submitted', 'shortlisted', 'awarded', 'declined', 'withdrawn')),
  requested_amount numeric,                        -- INR
  duration_months int,
  thread_id text REFERENCES threads(thread_id),    -- the shared proposal conversation
  draft_document_id bigint REFERENCES documents(id),
  budget_document_id bigint REFERENCES documents(id),
  fit_score_id bigint REFERENCES fit_scores(id),
  submitted_at date,
  decided_at date,
  decision_notes text,
  grant_id bigint REFERENCES grants(id),           -- set when awarded
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX proposals_org_idx ON proposals (org_id, status);

CREATE TABLE reference_figures (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('cost_per_beneficiary', 'overhead_norm', 'salary_benchmark',
        'unit_cost', 'outcome_rate', 'sroi_ratio', 'district_indicator', 'state_indicator', 'other')),
  name text NOT NULL,
  value numeric,
  value_text text,                                 -- when the figure is not a single number
  unit text,                                       -- 'INR per household', '% of CSR spend'
  tag_id bigint REFERENCES tags(id),               -- sector, cell, scheme or SDG it applies to
  location_id bigint REFERENCES locations(id),
  funder_id bigint REFERENCES funders(id),         -- a funder-specific norm
  period text,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  CHECK (value IS NOT NULL OR value_text IS NOT NULL)
);
CREATE INDEX reference_figures_kind_idx ON reference_figures (kind, tag_id, location_id);
