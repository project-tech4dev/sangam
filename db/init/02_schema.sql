-- SANGAM core schema.
-- Conventions (per ffrh-funder-intelligence/07-scrape-store-chat-stack.md):
--   * provenance columns on every scraped-fact table:
--       source_url, source_name, fetched_at, content_hash, extractor_version
--   * temporal columns (valid_from/valid_to) where facts change over time
--   * variable-shape source payloads land in JSONB, typed columns for what we query
-- Deferred (nothing here blocks them): *_versions SCD2 tables, grants, csr_spend,
--   HNSW index on chunks.embedding.

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  display_name text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orgs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  darpan_id text UNIQUE,
  cohort text,
  state text,
  district text,
  registration jsonb NOT NULL DEFAULT '{}'::jsonb,
  contact jsonb NOT NULL DEFAULT '{}'::jsonb,
  sectors text[] NOT NULL DEFAULT '{}',
  sections jsonb NOT NULL DEFAULT '{}'::jsonb,   -- full variable-shape darpan payload
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);

CREATE TABLE org_office_bearers (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name text NOT NULL,
  designation text,
  UNIQUE (org_id, name, designation)
);

CREATE TABLE funders (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  funder_type text,                               -- corporate_csr | private_foundation | family_trust_network | ...
  website text,
  focus_sectors text[] NOT NULL DEFAULT '{}',
  geographies text[] NOT NULL DEFAULT '{}',
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,     -- long-tail extracted facts
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);

CREATE TABLE funder_aliases (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  alias_type text NOT NULL,                       -- 'cin' | 'pan' | 'fcra' | 'domain' | 'name' | ...
  alias_value text NOT NULL,
  PRIMARY KEY (alias_type, alias_value)
);

CREATE TABLE funder_contacts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  name text,
  role text,
  email text,
  phone text,
  verified boolean NOT NULL DEFAULT false,
  notes text,
  source_url text,
  fetched_at timestamptz
);

CREATE TABLE rfps (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint REFERENCES funders(id),
  title text NOT NULL,
  url text,
  status text NOT NULL DEFAULT 'open',            -- open | closed | removed
  deadline date,
  sectors text[] NOT NULL DEFAULT '{}',
  geographies text[] NOT NULL DEFAULT '{}',
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);

CREATE TABLE news_mentions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url text UNIQUE NOT NULL,
  title text,
  seendate timestamptz,
  domain text,
  language text,
  sourcecountry text,
  topic text,                                     -- gdelt query name: funders_grants | fcra_actions | ...
  funder_id bigint REFERENCES funders(id),
  org_id bigint REFERENCES orgs(id),
  source_name text NOT NULL DEFAULT 'gdelt',
  fetched_at timestamptz
);

-- Rubric family: supports v1 (flat criteria) and v2 (criteria + sub-criteria) in one shape.
CREATE TABLE rubrics (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  version text UNIQUE NOT NULL,                   -- 'v1', 'v2'
  name text NOT NULL,
  total_points int NOT NULL,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rubric_criteria (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rubric_id bigint NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
  parent_id bigint REFERENCES rubric_criteria(id),  -- NULL for top-level; set for v2 sub-criteria
  code text NOT NULL,                               -- '1', '1a', '4c', ...
  label text NOT NULL,
  points int NOT NULL,
  guiding_question text,
  UNIQUE (rubric_id, code)
);

CREATE TABLE fit_scores (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint NOT NULL REFERENCES orgs(id),
  funder_id bigint NOT NULL REFERENCES funders(id),
  rubric_id bigint NOT NULL REFERENCES rubrics(id),
  total_score int NOT NULL,
  max_score int NOT NULL,
  scored_by text NOT NULL DEFAULT 'manual',       -- 'manual' | 'model:<name>'
  scored_at timestamptz NOT NULL DEFAULT now(),
  notes text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE (org_id, funder_id, rubric_id, scored_at)
);

CREATE TABLE fit_score_items (
  fit_score_id bigint NOT NULL REFERENCES fit_scores(id) ON DELETE CASCADE,
  criterion_id bigint NOT NULL REFERENCES rubric_criteria(id),
  score int NOT NULL,
  justification text,
  PRIMARY KEY (fit_score_id, criterion_id)
);

CREATE TABLE score_adjustments (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fit_score_id bigint NOT NULL REFERENCES fit_scores(id) ON DELETE CASCADE,
  criterion_id bigint NOT NULL REFERENCES rubric_criteria(id),
  old_score int,
  new_score int,
  reason text NOT NULL,
  adjusted_by uuid REFERENCES users(id),
  adjusted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id),
  funder_id bigint REFERENCES funders(id),
  title text,
  doc_type text,                                  -- profile | annual_report | proposal_template | ...
  content_md text,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);

CREATE TABLE chunks (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  content text NOT NULL,
  content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
  embedding vector(1536),                         -- nullable; no embedding pipeline yet
  UNIQUE (document_id, chunk_index)
);

CREATE INDEX chunks_tsv_idx ON chunks USING gin (content_tsv);
CREATE INDEX orgs_name_trgm ON orgs USING gin (name gin_trgm_ops);
CREATE INDEX funders_name_trgm ON funders USING gin (name gin_trgm_ops);
CREATE INDEX news_mentions_seendate_idx ON news_mentions (seendate DESC);
CREATE INDEX fit_scores_org_funder_idx ON fit_scores (org_id, funder_id);
