-- SANGAM core schema, v2 (normalized source of truth).
-- Conventions (per ffrh-funder-intelligence/07-scrape-store-chat-stack.md):
--   * provenance columns on every scraped/extracted-fact table:
--       source_url, source_name, fetched_at, content_hash, extractor_version
--   * temporal columns (valid_from/valid_to) where facts change over time
--   * variable-shape source payloads in JSONB; typed columns for what we query
--   * deterministic entity-resolution keys as typed identifier rows
-- Table order below is FK-safe: locations/tags before the actors that
-- reference them; grants before news_mentions; documents before extraction_log.
-- NOT defined here: graph_ingest_log (created by the graph ingestion tooling)
-- and checkpoint* tables (owned by the LangGraph checkpointer).

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  display_name text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Chat thread ownership for the /agent endpoint (also referenced by the
-- production-hardening work; keep this DDL the single definition).
CREATE TABLE threads (
  thread_id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX threads_user_id_idx ON threads (user_id);

CREATE TABLE locations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('country', 'region', 'state', 'district', 'block')),
  name text NOT NULL,
  parent_id bigint REFERENCES locations(id),
  UNIQUE (kind, name, parent_id)
);
-- UNIQUE treats NULL parent_id rows as distinct; enforce root uniqueness separately.
CREATE UNIQUE INDEX locations_root_uniq ON locations (kind, name) WHERE parent_id IS NULL;

CREATE TABLE tags (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  label text NOT NULL,
  kind text NOT NULL DEFAULT 'sector' CHECK (kind IN ('sector', 'population', 'theme')),
  parent_id bigint REFERENCES tags(id),
  taxonomy_ref text                               -- e.g. Candid PCS code, when adopted
);

CREATE TABLE orgs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  org_kind text NOT NULL DEFAULT 'cso' CHECK (org_kind IN ('cso', 'intermediary', 'government')),
  cohort text,
  legal_form text,                                -- Society | Trust | Section 8 | ...
  registration_date date,
  registered_location_id bigint REFERENCES locations(id),  -- canonical registration place
  contact jsonb NOT NULL DEFAULT '{}'::jsonb,
  sections jsonb NOT NULL DEFAULT '{}'::jsonb,    -- full variable-shape darpan payload
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,     -- long-tail extracted facts
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);
CREATE INDEX orgs_name_trgm ON orgs USING gin (name gin_trgm_ops);

-- Deterministic entity-resolution keys (PAN, FCRA, Darpan, ...): one row per ID.
CREATE TABLE org_identifiers (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  id_type text NOT NULL CHECK (id_type IN ('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
  id_value text NOT NULL,
  verified boolean NOT NULL DEFAULT false,
  source_url text,
  PRIMARY KEY (id_type, id_value)
);
CREATE INDEX org_identifiers_org_idx ON org_identifiers (org_id);

CREATE TABLE funders (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  funder_type text,                               -- corporate_csr | private_foundation | family_trust_network | ...
  section_135_bound boolean,                      -- NULL = unknown
  website text,
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);
CREATE INDEX funders_name_trgm ON funders USING gin (name gin_trgm_ops);

CREATE TABLE funder_identifiers (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  id_type text NOT NULL CHECK (id_type IN ('pan', 'cin', 'csr1', 'darpan', 'reg_no', 'domain', 'name')),
  id_value text NOT NULL,
  verified boolean NOT NULL DEFAULT false,
  source_url text,
  PRIMARY KEY (id_type, id_value)
);
CREATE INDEX funder_identifiers_funder_idx ON funder_identifiers (funder_id);

-- People associated with either an org or a funder (exactly one).
CREATE TABLE contacts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  name text NOT NULL,
  role text,
  kind text NOT NULL DEFAULT 'other' CHECK (kind IN ('office_bearer', 'programme', 'grants', 'other')),
  email text,
  phone text,
  verified boolean NOT NULL DEFAULT false,
  notes text,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);
CREATE INDEX contacts_org_idx ON contacts (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX contacts_funder_idx ON contacts (funder_id) WHERE funder_id IS NOT NULL;
-- Upsert key for office-bearer ingestion from darpan payloads.
CREATE UNIQUE INDEX contacts_org_person_uniq ON contacts (org_id, name, role) WHERE org_id IS NOT NULL;
CREATE UNIQUE INDEX contacts_funder_person_uniq ON contacts (funder_id, name, role) WHERE funder_id IS NOT NULL;

-- Programs run by an org OR flagship programs of a funder (exactly one owner).
CREATE TABLE programs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  name text NOT NULL,
  description text,
  status text,
  start_date date,
  end_date date,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);
CREATE UNIQUE INDEX programs_funder_name_uniq ON programs (funder_id, name) WHERE funder_id IS NOT NULL;
CREATE UNIQUE INDEX programs_org_name_uniq ON programs (org_id, name) WHERE org_id IS NOT NULL;

-- Actual funding relationships (the authoritative record the graph derives from).
CREATE TABLE grants (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id),
  org_id bigint NOT NULL REFERENCES orgs(id),
  program_id bigint REFERENCES programs(id),
  title text NOT NULL,
  amount numeric,                                 -- NULL = not publicly known
  currency text NOT NULL DEFAULT 'INR',
  start_date date,
  end_date date,
  status text NOT NULL CHECK (status IN ('active', 'concluded', 'unconfirmed', 'dormant')),
  outcomes jsonb NOT NULL DEFAULT '{}'::jsonb,    -- e.g. {"families_reached": 24765}
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text,
  UNIQUE (funder_id, org_id, title)
);
CREATE INDEX grants_funder_org_idx ON grants (funder_id, org_id);

CREATE TABLE rfps (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint REFERENCES funders(id),
  title text NOT NULL,
  url text,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'removed')),
  deadline date,
  amount_min numeric,
  amount_max numeric,
  eligibility jsonb NOT NULL DEFAULT '{}'::jsonb,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  content_hash text,
  extractor_version text
);

-- RFP Watch: which opportunities look like fits for which orgs.
CREATE TABLE rfp_matches (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  match_score numeric,
  match_notes text,
  status text NOT NULL DEFAULT 'flagged' CHECK (status IN ('flagged', 'reviewed', 'dismissed')),
  matched_by text,                                -- 'manual' | 'model:<name>' | user uuid
  matched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (rfp_id, org_id)
);
CREATE INDEX rfp_matches_status_idx ON rfp_matches (status);

CREATE TABLE news_mentions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url text UNIQUE NOT NULL,
  title text,
  seendate timestamptz,
  domain text,
  language text,
  sourcecountry text,
  topic text,                                     -- gdelt query name
  funder_id bigint REFERENCES funders(id),
  org_id bigint REFERENCES orgs(id),
  grant_id bigint REFERENCES grants(id),
  source_name text NOT NULL DEFAULT 'gdelt',
  fetched_at timestamptz
);
CREATE INDEX news_mentions_seendate_idx ON news_mentions (seendate DESC);

-- Rubric family: v1 (flat criteria) and v2 (criteria + sub-criteria) in one shape.
CREATE TABLE rubrics (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  version text UNIQUE NOT NULL,
  name text NOT NULL,
  total_points int NOT NULL,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rubric_criteria (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  rubric_id bigint NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
  parent_id bigint REFERENCES rubric_criteria(id),
  code text NOT NULL,
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
  scored_by text NOT NULL DEFAULT 'manual',
  scored_at timestamptz NOT NULL DEFAULT now(),
  notes text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  UNIQUE (org_id, funder_id, rubric_id, scored_at)
);
CREATE INDEX fit_scores_org_funder_idx ON fit_scores (org_id, funder_id);

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

-- Documents/chunks DDL must stay byte-compatible with v1: the migration restores
-- the 96 existing documents rows into this exact shape.
CREATE TABLE documents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id),
  funder_id bigint REFERENCES funders(id),
  title text,
  doc_type text,
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
  embedding vector(1536),
  UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (content_tsv);

-- Receipts for LLM-extracted rows: which document produced which record.
CREATE TABLE extraction_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  target_table text NOT NULL,
  target_pk text NOT NULL,
  extractor_version text NOT NULL,
  model text,
  confidence numeric,
  extracted_at timestamptz NOT NULL DEFAULT now()
);

-- M2M links. Tag links carry primary|secondary (the rubric distinguishes primary
-- vs secondary theme match); location links carry the relationship kind.
CREATE TABLE org_tags (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  PRIMARY KEY (org_id, tag_id)
);
CREATE TABLE funder_tags (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  PRIMARY KEY (funder_id, tag_id)
);
CREATE TABLE program_tags (
  program_id bigint NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  PRIMARY KEY (program_id, tag_id)
);
CREATE TABLE rfp_tags (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  PRIMARY KEY (rfp_id, tag_id)
);
CREATE TABLE org_locations (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'operates' CHECK (role IN ('registered', 'operates', 'funds')),
  PRIMARY KEY (org_id, location_id)
);
CREATE TABLE funder_locations (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'funds' CHECK (role IN ('registered', 'operates', 'funds')),
  PRIMARY KEY (funder_id, location_id)
);
CREATE TABLE program_locations (
  program_id bigint NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'operates' CHECK (role IN ('registered', 'operates', 'funds')),
  PRIMARY KEY (program_id, location_id)
);
CREATE TABLE rfp_locations (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'funds' CHECK (role IN ('registered', 'operates', 'funds')),
  PRIMARY KEY (rfp_id, location_id)
);
