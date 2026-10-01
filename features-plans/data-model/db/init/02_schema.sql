-- SANGAM core schema, v3 (single baseline; replaces v2 plus migrations 0001-0007).
-- There is no production database, so v3 is applied to an empty database and seeded.
--
-- Conventions
--   * Provenance: one row = one fact = one source. Fact rows carry source_url (a link,
--     the page is not cached), source_name, fetched_at (date sourced), as_of (date or
--     period the source describes), document_id (content file it was read from) and
--     archive_url (optional web archive snapshot). A second source is a second row.
--   * Access: registry data is public. Private data is non-public documents, private
--     identifier values, unvetted news, RFP matches and unshared threads. Users belong
--     to orgs through org_members (admin | member | steward).
--   * Rubric logic lives in the agent code; the rubric tables hold recorded versions
--     and scored results.
--   * Taxonomy: every vocabulary lives in tags (see tags.kind).
--   * Temporal columns (valid_from/valid_to) where facts change over time.
-- Table order is FK-safe. NOT defined here: graph_ingest_log (graph tooling) and
-- checkpoint* tables (LangGraph checkpointer). Reference lists (CSR Schedule VII,
-- aspirational districts, North East states) load from db/seed/reference_data.sql.

-- =====================================================================================
-- 0. Roles and auth stub for the local container. On Supabase these already exist
--    and nothing is created.
-- =====================================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS auth;
DO $$
BEGIN
  IF to_regprocedure('auth.uid()') IS NULL THEN
    EXECUTE $f$CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
      $b$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $b$ $f$;
  END IF;
END $$;

-- =====================================================================================
-- 1. People and places
-- =====================================================================================

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  display_name text,
  auth_user_id uuid UNIQUE,                        -- Supabase auth.users(id); no FK so local runs work
  is_staff boolean NOT NULL DEFAULT false,         -- FFRH / platform staff: see everything
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE locations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('country', 'region', 'state', 'district', 'block', 'village')),
  name text NOT NULL,
  parent_id bigint REFERENCES locations(id),
  lgd_code text,                                   -- Local Government Directory code
  aliases text[] NOT NULL DEFAULT '{}',            -- other spellings and former names
  UNIQUE (kind, name, parent_id)
);
-- UNIQUE treats NULL parent_id rows as distinct; enforce root uniqueness separately.
CREATE UNIQUE INDEX locations_root_uniq ON locations (kind, name) WHERE parent_id IS NULL;
CREATE UNIQUE INDEX locations_lgd_uniq ON locations (kind, lgd_code) WHERE lgd_code IS NOT NULL;
CREATE INDEX locations_aliases_idx ON locations USING gin (aliases);
CREATE INDEX locations_parent_idx ON locations (parent_id);

-- Every vocabulary in one table.
--   cross-domain: sdg | sector (SANGAM formal sector) | population | darpan_sector | theme
--                 | csr_sector (Schedule VII groups and development sectors)
--                 | scheme (government schemes and missions, e.g. MGNREGA, DAY-NRLM, a state mission)
--   per domain:   domain (root row, e.g. 'Livelihoods') | cell (node of that domain's tree)
-- Cells are never deleted: removed cells become 'deprecated' and replaced_by points at
-- the successor. A 'draft' domain is loaded for review and hidden in the product.
CREATE TABLE tags (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  label text NOT NULL,
  kind text NOT NULL DEFAULT 'sector'
    CHECK (kind IN ('sdg', 'sector', 'population', 'darpan_sector', 'theme', 'domain', 'cell', 'csr_sector',
                    'scheme')),
  domain text,                                     -- 'livelihoods', 'health', ... for domain and cell rows
  code text,                                       -- 'SDG 8', '01.A.informal', 'VII(ii)'
  level text,                                      -- 'goal', 'macro_sector', 'sub_sector', 'track', 'group', ...
  parent_id bigint REFERENCES tags(id),
  description text,
  meta jsonb NOT NULL DEFAULT '{}'::jsonb,         -- crosswalk (sdgs, sectors, adds), maps_to, designation
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'deprecated')),
  replaced_by bigint REFERENCES tags(id),
  sort_order int,
  taxonomy_ref text,                               -- e.g. Candid PCS code, when adopted
  CONSTRAINT tags_domain_required CHECK (kind NOT IN ('domain', 'cell') OR domain IS NOT NULL)
);
CREATE INDEX tags_kind_domain_idx ON tags (kind, domain) WHERE status = 'active';
CREATE INDEX tags_parent_idx ON tags (parent_id);

-- =====================================================================================
-- 2. Organisations, funders and membership
-- =====================================================================================

CREATE TABLE orgs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  org_kind text NOT NULL DEFAULT 'cso' CHECK (org_kind IN ('cso', 'intermediary', 'government')),
  registry_status text NOT NULL DEFAULT 'in_vetting'
    CHECK (registry_status IN ('placeholder', 'in_vetting', 'full_profile', 'hidden')),
  cohort text,
  legal_form text,                                 -- Society | Trust | Section 8 | ...
  registration_date date,
  registered_location_id bigint REFERENCES locations(id),
  contact jsonb NOT NULL DEFAULT '{}'::jsonb,
  sections jsonb NOT NULL DEFAULT '{}'::jsonb,     -- full variable-shape darpan payload
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,      -- long-tail extracted facts
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  archive_url text
);
CREATE INDEX orgs_name_trgm ON orgs USING gin (name gin_trgm_ops);

-- Many users per org; one user in many orgs. An ecosystem player such as Node is an org
-- (org_kind 'intermediary'); its staff get 'steward' rows on each org they support.
CREATE TABLE org_members (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'steward')),
  added_by uuid REFERENCES users(id),
  added_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, org_id)
);
CREATE INDEX org_members_org_idx ON org_members (org_id);

CREATE TABLE funders (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  funder_type text,                                -- corporate_csr | private_foundation | ...
  parent_id bigint REFERENCES funders(id),         -- company -> its foundation
  registry_status text NOT NULL DEFAULT 'in_vetting'
    CHECK (registry_status IN ('placeholder', 'in_vetting', 'full_profile', 'hidden')),
  section_135_bound boolean,                       -- NULL = unknown; per-year status in funder_csr_years
  website text,
  profile jsonb NOT NULL DEFAULT '{}'::jsonb,      -- incl. grant-shape flags
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  archive_url text
);
CREATE INDEX funders_name_trgm ON funders USING gin (name gin_trgm_ops);
CREATE INDEX funders_parent_idx ON funders (parent_id);

-- =====================================================================================
-- 3. Content files
-- =====================================================================================

-- Research files, uploaded vault files and AI-generated artefacts. A requested but
-- missing document is a row with status 'requested' and no content.
CREATE TABLE documents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id),
  funder_id bigint REFERENCES funders(id),
  title text,
  doc_type text,
  content_md text,
  is_public boolean NOT NULL DEFAULT true,         -- vault uploads are inserted with false
  status text NOT NULL DEFAULT 'read'
    CHECK (status IN ('requested', 'received', 'read', 'scored', 'verified')),
  storage_path text,                               -- Supabase Storage key, '<org_id>/<file>' in bucket 'vault'
  uploaded_by uuid REFERENCES users(id),
  is_ai_generated boolean NOT NULL DEFAULT false,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  archive_url text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_org_idx ON documents (org_id);

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

-- =====================================================================================
-- 4. Conversations
-- =====================================================================================

-- private: creator only | team: + org admins and members | team_and_stewards: + stewards.
-- Messages live in the LangGraph checkpoint tables; the backend checks
-- app.can_open_thread() before loading or posting.
CREATE TABLE threads (
  thread_id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  title text,
  use_case text NOT NULL DEFAULT 'ask' CHECK (use_case IN ('ask', 'proposal', 'signals', 'rfp_watch')),
  org_id bigint REFERENCES orgs(id),
  context jsonb NOT NULL DEFAULT '{}'::jsonb,      -- seed: {"news_mention_id": 12} | {"rfp_id": 3}
  visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team', 'team_and_stewards')),
  updated_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT threads_shared_needs_org CHECK (visibility = 'private' OR org_id IS NOT NULL)
);
CREATE INDEX threads_user_id_idx ON threads (user_id);
CREATE INDEX threads_rail_idx ON threads (user_id, use_case, updated_at DESC);
CREATE INDEX threads_org_rail_idx ON threads (org_id, use_case, updated_at DESC) WHERE visibility <> 'private';

-- =====================================================================================
-- 5. Identifiers and credentials
-- =====================================================================================

-- The numbers. A missing credential has no row; its status and history are in
-- credential_events.
CREATE TABLE org_identifiers (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  id_type text NOT NULL CHECK (id_type IN ('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
  id_value text NOT NULL,
  verified boolean NOT NULL DEFAULT false,
  is_public boolean NOT NULL DEFAULT true,         -- false = 'on file, number not published'
  is_current boolean NOT NULL DEFAULT true,        -- false for a superseded number (old 12A/80G)
  notes text,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  document_id bigint REFERENCES documents(id),
  archive_url text,
  PRIMARY KEY (id_type, id_value)
);
CREATE INDEX org_identifiers_org_idx ON org_identifiers (org_id);
CREATE INDEX org_identifiers_private_idx ON org_identifiers (org_id) WHERE NOT is_public;

CREATE TABLE funder_identifiers (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  id_type text NOT NULL CHECK (id_type IN ('pan', 'cin', 'csr1', 'darpan', 'reg_no', 'domain', 'name')),
  id_value text NOT NULL,
  verified boolean NOT NULL DEFAULT false,
  is_current boolean NOT NULL DEFAULT true,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  archive_url text,
  PRIMARY KEY (id_type, id_value)
);
CREATE INDEX funder_identifiers_funder_idx ON funder_identifiers (funder_id);

-- What happened to a registration: registered, renewed, checked, expired, ... Holds no
-- number, so status and history can be public while the number stays private.
CREATE TABLE credential_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  credential text NOT NULL
    CHECK (credential IN ('pan', '12a', '80g', 'fcra', 'csr1', 'darpan', 'cin', 'reg_no')),
  event text NOT NULL CHECK (event IN (
    'registered', 'renewed', 'checked_active', 'restored',     -- status becomes active
    'expired', 'suspended', 'cancelled', 'surrendered',
    'superseded',                                              -- replaced by a new number
    'not_available', 'not_found',                              -- a source says it does not exist
    'check_blocked'                                            -- could not check; history only
  )),
  event_date date NOT NULL,
  valid_until date,
  verified boolean NOT NULL DEFAULT false,         -- only verified events set current status
  notes text,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  document_id bigint REFERENCES documents(id),
  archive_url text,
  recorded_by uuid REFERENCES users(id),
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX credential_events_org_idx ON credential_events (org_id, credential, event_date DESC)
  WHERE org_id IS NOT NULL;
CREATE INDEX credential_events_funder_idx ON credential_events (funder_id, credential, event_date DESC)
  WHERE funder_id IS NOT NULL;

-- =====================================================================================
-- 6. People, programmes, grants, calls
-- =====================================================================================

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
  is_public boolean NOT NULL DEFAULT false,        -- office bearers are always public (see policy)
  notes text,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  document_id bigint REFERENCES documents(id),
  archive_url text
);
CREATE INDEX contacts_org_idx ON contacts (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX contacts_funder_idx ON contacts (funder_id) WHERE funder_id IS NOT NULL;
-- Upsert key for office-bearer ingestion from darpan payloads.
CREATE UNIQUE INDEX contacts_org_person_uniq ON contacts (org_id, name, role) WHERE org_id IS NOT NULL;
CREATE UNIQUE INDEX contacts_funder_person_uniq ON contacts (funder_id, name, role) WHERE funder_id IS NOT NULL;

-- Programmes run by an org, or a funder's own themes, programmes and phases
-- (exactly one owner). kind: theme ('Lives & Livelihoods') > programme ('Axis DilSe')
-- > phase ('Mission 4 Million'), linked by parent_id.
CREATE TABLE programs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  CHECK ((org_id IS NULL) <> (funder_id IS NULL)),
  parent_id bigint REFERENCES programs(id),
  kind text NOT NULL DEFAULT 'programme' CHECK (kind IN ('theme', 'programme', 'phase', 'project')),
  name text NOT NULL,
  description text,
  status text,
  is_enabler boolean NOT NULL DEFAULT false,       -- enablers get no domain cell
  start_date date,
  end_date date,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  document_id bigint REFERENCES documents(id),
  archive_url text
);
CREATE UNIQUE INDEX programs_funder_name_uniq ON programs (funder_id, name) WHERE funder_id IS NOT NULL;
CREATE UNIQUE INDEX programs_org_name_uniq ON programs (org_id, name) WHERE org_id IS NOT NULL;

-- Actual funding relationships.
CREATE TABLE grants (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id),
  org_id bigint NOT NULL REFERENCES orgs(id),
  program_id bigint REFERENCES programs(id),
  title text NOT NULL,
  amount numeric,                                  -- NULL = not publicly known
  currency text NOT NULL DEFAULT 'INR',
  start_date date,
  end_date date,
  status text NOT NULL CHECK (status IN ('active', 'concluded', 'unconfirmed', 'dormant')),
  outcomes jsonb NOT NULL DEFAULT '{}'::jsonb,     -- e.g. {"families_reached": 24765}
  notes text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  document_id bigint REFERENCES documents(id),
  archive_url text,
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
  details jsonb NOT NULL DEFAULT '{}'::jsonb,      -- rolling, term, core costs, ...
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to timestamptz,
  source_url text,
  source_name text,
  fetched_at timestamptz,
  as_of text,
  content_hash text,
  extractor_version text,
  document_id bigint REFERENCES documents(id),
  archive_url text
);

-- RFP Watch: which opportunities look like fits for which orgs.
CREATE TABLE rfp_matches (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  match_score numeric,
  match_notes text,
  status text NOT NULL DEFAULT 'flagged' CHECK (status IN ('flagged', 'reviewed', 'dismissed')),
  matched_by text,                                 -- 'manual' | 'model:<name>' | user uuid
  matched_at timestamptz NOT NULL DEFAULT now(),
  week_of date,                                    -- weekly batch that flagged it
  PRIMARY KEY (rfp_id, org_id)
);
CREATE INDEX rfp_matches_status_idx ON rfp_matches (status);
CREATE INDEX rfp_matches_org_idx ON rfp_matches (org_id);

-- News (GDELT) and manually checked social items. Only 'vetted' items are public.
CREATE TABLE news_mentions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url text UNIQUE NOT NULL,
  title text,
  seendate timestamptz,
  domain text,
  language text,
  sourcecountry text,
  topic text,                                      -- gdelt query name
  kind text NOT NULL DEFAULT 'news' CHECK (kind IN ('news', 'press', 'social')),
  platform text,                                   -- 'linkedin' | 'x' | 'youtube' | ...
  summary text,
  sentiment text CHECK (sentiment IN ('positive', 'neutral', 'negative')),
  review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'vetted', 'rejected')),
  reviewed_by uuid REFERENCES users(id),
  reviewed_at timestamptz,
  funder_id bigint REFERENCES funders(id),
  org_id bigint REFERENCES orgs(id),
  grant_id bigint REFERENCES grants(id),
  source_name text NOT NULL DEFAULT 'gdelt',
  fetched_at timestamptz,
  archive_url text
);
CREATE INDEX news_mentions_seendate_idx ON news_mentions (seendate DESC);
CREATE INDEX news_mentions_org_idx ON news_mentions (org_id);

-- =====================================================================================
-- 7. Rubrics and scores (unchanged from v2; scoring logic lives in agent code)
-- =====================================================================================

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

-- =====================================================================================
-- 8. Org and funder facts
-- =====================================================================================

CREATE TABLE org_financials (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL,                       -- 'FY2023-24'
  total_income numeric,
  program_spend numeric,
  non_program_spend numeric,
  foreign_contribution numeric,
  is_audited boolean,
  notes text,
  source_url text, source_name text, fetched_at timestamptz,
  as_of text, document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE (org_id, fiscal_year)
);

-- Impact metrics and reach (villages, families, districts) for an org or a funder
-- (exactly one), optionally tied to a programme, grant or place.
-- Results chain: rows sharing a chain_key form one chain, ordered by sequence and typed
-- by stage, e.g. trained (output) -> adopted (adoption) -> income up (outcome) ->
-- sustained after 2 years (sustained_outcome) -> vs comparison households -> SROI.
-- A planned figure (e.g. a proposal target) has a target and no value yet.
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
  stage text CHECK (stage IN ('input', 'output', 'adoption', 'outcome', 'sustained_outcome', 'impact', 'sroi')),
  chain_key text,                                  -- groups one results chain, e.g. 'kabil-mazbat-livelihoods'
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
CREATE INDEX metrics_chain_idx ON metrics (chain_key, sequence) WHERE chain_key IS NOT NULL;
CREATE INDEX metrics_funder_idx ON metrics (funder_id) WHERE funder_id IS NOT NULL;

-- =====================================================================================
-- 9. Funder facts: CSR money, footprints, partners
-- =====================================================================================

CREATE TABLE funder_csr_years (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL,
  section_135_applicable boolean,
  -- Fields follow the statutory Annual Report on CSR Activities (item 5 and 6), INR
  average_net_profit numeric,                      -- 5(a), per Section 135(5)
  prescribed_csr numeric,                          -- 5(b), 2% obligation
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

-- CSR spend. Either an aggregate (project_name NULL): by sector and/or place from
-- csr.gov.in, a theme total stated in a report, or BRSR spend in aspirational districts
-- per state (designation = 'aspirational_district'). Or one project (project_name set)
-- from csr.gov.in company data (filed on Form CSR-2) or a board-approved annual action
-- plan, with its implementing agency and CSR-1 number.
CREATE TABLE funder_csr_spend (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL,
  program_id bigint REFERENCES programs(id),       -- the funder's theme, when known
  csr_sector_id bigint REFERENCES tags(id),        -- a csr_sector tag (group or sector)
  state_location_id bigint REFERENCES locations(id),
  district_location_id bigint REFERENCES locations(id),
  designation text,                                -- spend limited to places with this designation,
                                                   -- e.g. 'aspirational_district' (BRSR Principle 8)
  project_name text,                               -- NULL for aggregate rows
  implementing_agency text,                        -- as printed
  agency_csr1 text,                                -- agency's CSR-1 registration number
  agency_org_id bigint REFERENCES orgs(id),        -- set when the agency is in the registry
  via_agency boolean,                              -- false = implemented directly
  is_ongoing boolean,                              -- ongoing (multi-year) project
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

-- Where a funder's theme ran in a fiscal year (district, or state if that is all the
-- source gives).
CREATE TABLE funder_footprints (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL,
  location_id bigint NOT NULL REFERENCES locations(id),
  name_as_printed text,                            -- e.g. 'Kamrup Metropolitan'
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, program_id, fiscal_year, location_id)
);
CREATE INDEX funder_footprints_location_idx ON funder_footprints (location_id, fiscal_year);

-- Organisations a funder names as partners, per theme and year.
CREATE TABLE funder_partners (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  program_id bigint REFERENCES programs(id) ON DELETE CASCADE,
  fiscal_year text NOT NULL,
  partner_name text NOT NULL,                      -- as printed in the source
  partner_canonical text,                          -- one spelling per partner, for counting renewals
  org_id bigint REFERENCES orgs(id),               -- set when the partner is in the registry
  partner_funder_id bigint REFERENCES funders(id), -- set when the partner is itself a funder
  partner_csr1 text,                               -- partner's CSR-1 number, when the source gives it
  partner_kind text CHECK (partner_kind IN ('ngo', 'foundation', 'university', 'research', 'government',
                                            'armed_forces', 'hospital', 'network', 'company', 'other')),
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  UNIQUE NULLS NOT DISTINCT (funder_id, program_id, fiscal_year, partner_name)
);
CREATE INDEX funder_partners_org_idx ON funder_partners (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX funder_partners_canonical_idx ON funder_partners (funder_id, partner_canonical);

-- =====================================================================================
-- 9b. Proposals, funder templates and reference figures
-- =====================================================================================

-- External numbers used for budgets and secondary research: cost benchmarks, overhead
-- norms, salary benchmarks, outcome rates from studies, SROI ratios, district or state
-- indicators. Each is scoped by a tag, a place and/or a funder where relevant.
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

-- A funder's application form, RFP, due-diligence checklist, budget format or report format.
CREATE TABLE proposal_templates (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint REFERENCES funders(id) ON DELETE CASCADE,
  rfp_id bigint REFERENCES rfps(id) ON DELETE CASCADE,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('application', 'rfp', 'due_diligence', 'budget', 'reporting', 'site_visit')),
  version text,
  notes text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text
);
CREATE UNIQUE INDEX proposal_templates_uniq ON proposal_templates (coalesce(funder_id, 0), coalesce(rfp_id, 0), name);

-- One section, question, criterion, eligibility gate or required document of a template.
-- check_rule lets check_template() test it against the data; items without one are
-- checked by a person or the agent.
CREATE TABLE template_items (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  template_id bigint NOT NULL REFERENCES proposal_templates(id) ON DELETE CASCADE,
  ord int NOT NULL,
  item_kind text NOT NULL CHECK (item_kind IN ('section', 'question', 'criterion', 'eligibility', 'document')),
  code text,                                       -- the template's own numbering, e.g. 'A7', 'C1'
  heading text NOT NULL,
  guidance text,
  word_limit int,
  char_limit int,
  points numeric,                                  -- marks, when the funder publishes them
  required boolean NOT NULL DEFAULT true,
  check_rule jsonb,                                -- see check_template()
  UNIQUE (template_id, ord)
);

-- A proposal an org is preparing or has sent. Private to the org's members and staff.
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
  fit_score_id bigint REFERENCES fit_scores(id),   -- the score the agent or a reviewer gave
  submitted_at date,
  decided_at date,
  decision_notes text,
  grant_id bigint REFERENCES grants(id),           -- set when awarded
  created_by uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX proposals_org_idx ON proposals (org_id, status);

-- =====================================================================================
-- 10. Links between entities and tags or places
-- =====================================================================================

-- Tag links carry primary|secondary, whether the tag was inferred, and who tagged it.
CREATE TABLE org_tags (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  is_inferred boolean NOT NULL DEFAULT false,
  tagged_by text,                                  -- 'darpan' | 'manual' | 'model:<name>' | 'rule:derive_tags'
  note text,
  PRIMARY KEY (org_id, tag_id)
);
CREATE TABLE funder_tags (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  is_inferred boolean NOT NULL DEFAULT false,
  tagged_by text,
  note text,
  PRIMARY KEY (funder_id, tag_id)
);
CREATE TABLE program_tags (
  program_id bigint NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  is_inferred boolean NOT NULL DEFAULT false,
  tagged_by text,
  note text,                                       -- e.g. 'Informal: small & marginal farmers'
  PRIMARY KEY (program_id, tag_id)
);
CREATE TABLE rfp_tags (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'primary' CHECK (role IN ('primary', 'secondary')),
  is_inferred boolean NOT NULL DEFAULT false,
  tagged_by text,
  note text,
  PRIMARY KEY (rfp_id, tag_id)
);

-- Location links carry the relationship kind, dates, a note and their own source.
-- funder_locations holds the funder's STATED geography (role 'priority'); where it
-- actually funded comes from grant_locations and funder_footprints.
CREATE TABLE org_locations (
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'operates' CHECK (role IN ('registered', 'operates', 'funds')),
  valid_from date, valid_to date, note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (org_id, location_id)
);
CREATE TABLE funder_locations (
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'priority' CHECK (role IN ('registered', 'operates', 'funds', 'priority')),
  valid_from date, valid_to date, note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (funder_id, location_id)
);
CREATE TABLE program_locations (
  program_id bigint NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'operates' CHECK (role IN ('registered', 'operates', 'funds')),
  valid_from date, valid_to date, note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (program_id, location_id)
);
CREATE TABLE rfp_locations (
  rfp_id bigint NOT NULL REFERENCES rfps(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'funds' CHECK (role IN ('registered', 'operates', 'funds')),
  valid_from date, valid_to date, note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (rfp_id, location_id)
);
CREATE TABLE grant_locations (
  grant_id bigint NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  note text,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  PRIMARY KEY (grant_id, location_id)
);
CREATE INDEX org_locations_location_idx ON org_locations (location_id);
CREATE INDEX funder_locations_location_idx ON funder_locations (location_id);
CREATE INDEX program_locations_location_idx ON program_locations (location_id);
CREATE INDEX rfp_locations_location_idx ON rfp_locations (location_id);
CREATE INDEX grant_locations_location_idx ON grant_locations (location_id);

-- Designations on places used as matching priorities: 'aspirational_district',
-- 'north_east'; later 'aspirational_block', ...
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

-- =====================================================================================
-- 11. Views
-- =====================================================================================

CREATE VIEW location_paths WITH (security_invoker = true) AS
WITH RECURSIVE p AS (
  SELECT id, kind, name, lgd_code, parent_id,
         name::text AS path, 1 AS depth,
         CASE WHEN kind = 'state' THEN id END AS state_id,
         CASE WHEN kind = 'district' THEN id END AS district_id
  FROM locations WHERE parent_id IS NULL
  UNION ALL
  SELECT l.id, l.kind, l.name, l.lgd_code, l.parent_id,
         p.path || ' / ' || l.name, p.depth + 1,
         CASE WHEN l.kind = 'state' THEN l.id ELSE p.state_id END,
         CASE WHEN l.kind = 'district' THEN l.id ELSE p.district_id END
  FROM locations l JOIN p ON l.parent_id = p.id
)
SELECT * FROM p;

CREATE VIEW tag_paths WITH (security_invoker = true) AS
WITH RECURSIVE p AS (
  SELECT id, slug, label, kind, domain, code, level, status, parent_id,
         label::text AS path, 1 AS depth
  FROM tags WHERE parent_id IS NULL
  UNION ALL
  SELECT t.id, t.slug, t.label, t.kind, t.domain, t.code, t.level, t.status, t.parent_id,
         p.path || ' / ' || t.label, p.depth + 1
  FROM tags t JOIN p ON t.parent_id = p.id
)
SELECT * FROM p;

-- Current status per credential from the latest verified event. check_blocked never
-- changes status; past_validity flags an active registration past valid_until;
-- pending_change flags a newer unverified event.
CREATE VIEW credential_status WITH (security_invoker = true) AS
WITH keys AS (
  SELECT DISTINCT org_id, funder_id, credential FROM credential_events
),
latest AS (
  SELECT DISTINCT ON (org_id, funder_id, credential) *
  FROM credential_events
  WHERE verified AND event <> 'check_blocked'
  ORDER BY org_id, funder_id, credential, event_date DESC, recorded_at DESC
)
SELECT
  k.org_id,
  k.funder_id,
  k.credential,
  CASE
    WHEN l.event IS NULL THEN 'unknown'
    WHEN l.event IN ('registered', 'renewed', 'checked_active', 'restored') THEN 'active'
    ELSE l.event
  END AS status,
  l.event AS last_event,
  l.event_date AS status_date,
  l.valid_until,
  coalesce(l.event IN ('registered', 'renewed', 'checked_active', 'restored')
           AND l.valid_until < current_date, false) AS past_validity,
  EXISTS (
    SELECT 1 FROM credential_events p
    WHERE p.org_id IS NOT DISTINCT FROM k.org_id
      AND p.funder_id IS NOT DISTINCT FROM k.funder_id
      AND p.credential = k.credential
      AND NOT p.verified
      AND (l.event_date IS NULL OR p.event_date >= l.event_date)
  ) AS pending_change,
  l.source_url,
  l.source_name,
  l.fetched_at,
  l.archive_url,
  l.id AS event_id
FROM keys k
LEFT JOIN latest l
  ON l.org_id IS NOT DISTINCT FROM k.org_id
 AND l.funder_id IS NOT DISTINCT FROM k.funder_id
 AND l.credential = k.credential;

-- Per funder and district: themes, years, latest year, aspirational flag.
CREATE VIEW funder_district_presence WITH (security_invoker = true) AS
SELECT
  ff.funder_id,
  ff.location_id,
  lp.path,
  lp.state_id,
  array_agg(DISTINCT p.name) FILTER (WHERE p.name IS NOT NULL) AS themes,
  array_agg(DISTINCT ff.fiscal_year) AS fiscal_years,
  max(ff.fiscal_year) AS latest_fiscal_year,
  EXISTS (SELECT 1 FROM location_designations d
          WHERE d.location_id = ff.location_id AND d.designation = 'aspirational_district') AS is_aspirational
FROM funder_footprints ff
JOIN location_paths lp ON lp.id = ff.location_id
LEFT JOIN programs p ON p.id = ff.program_id
GROUP BY ff.funder_id, ff.location_id, lp.path, lp.state_id;


-- One row per results chain: which stages have data, which are missing, and whether a
-- comparison or baseline exists. Drives the 'what is missing' check on impact claims.
CREATE VIEW impact_chains WITH (security_invoker = true) AS
SELECT
  m.org_id,
  m.funder_id,
  m.chain_key,
  min(m.program_id) AS program_id,
  array_agg(DISTINCT m.stage) FILTER (WHERE m.value IS NOT NULL) AS stages_with_data,
  array_agg(DISTINCT m.stage) FILTER (WHERE m.value IS NULL) AS stages_with_target_only,
  ARRAY(SELECT st FROM unnest(ARRAY['output', 'adoption', 'outcome', 'sustained_outcome', 'impact', 'sroi']) st
        WHERE NOT EXISTS (SELECT 1 FROM metrics x WHERE x.chain_key = m.chain_key AND x.stage = st
                          AND x.value IS NOT NULL)) AS stages_missing,
  bool_or(m.baseline IS NOT NULL) AS has_baseline,
  bool_or(m.comparison_value IS NOT NULL) AS has_comparison,
  count(*) AS rows
FROM metrics m
WHERE m.chain_key IS NOT NULL
GROUP BY m.org_id, m.funder_id, m.chain_key;

-- Checks an org against a template's items that carry a check_rule.
-- Rule types: credential | document | min_years_registered | min_income |
-- min_office_bearers | in_rfp_geography | has_stage. Anything else returns 'manual'.
-- status: pass | fail | missing (the data to decide is not in SANGAM) | manual
CREATE FUNCTION check_template(p_org_id bigint, p_template_id bigint)
RETURNS TABLE (ord int, item_kind text, code text, heading text, status text, detail text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  it record;
  r jsonb;
  v_n numeric;
  v_txt text;
  v_rfp bigint;
BEGIN
  SELECT t.rfp_id INTO v_rfp FROM proposal_templates t WHERE t.id = p_template_id;
  FOR it IN SELECT * FROM template_items i WHERE i.template_id = p_template_id ORDER BY i.ord LOOP
    ord := it.ord; item_kind := it.item_kind; code := it.code; heading := it.heading;
    r := it.check_rule;
    IF r IS NULL THEN
      status := 'manual'; detail := NULL;

    ELSIF r->>'type' = 'credential' THEN
      SELECT cs.status INTO v_txt FROM credential_status cs
      WHERE cs.org_id = p_org_id AND cs.credential = r->>'credential';
      IF v_txt = 'active' THEN status := 'pass'; detail := 'Active per credential history';
      ELSIF v_txt IN ('expired', 'suspended', 'cancelled', 'surrendered', 'not_available', 'not_found') THEN
        status := 'fail'; detail := 'Credential status: ' || v_txt;
      ELSIF EXISTS (SELECT 1 FROM org_identifiers oi WHERE oi.org_id = p_org_id
                    AND oi.id_type = r->>'credential' AND oi.is_current) THEN
        status := 'pass'; detail := 'Number on file; no status history yet';
      ELSE status := 'missing'; detail := 'No ' || (r->>'credential') || ' number or status recorded';
      END IF;

    ELSIF r->>'type' = 'document' THEN
      SELECT count(*) INTO v_n FROM documents d
      WHERE d.org_id = p_org_id AND d.doc_type = ANY (ARRAY(SELECT jsonb_array_elements_text(r->'doc_types')))
        AND d.status <> 'requested';
      IF v_n >= coalesce((r->>'min_count')::int, 1) THEN status := 'pass'; detail := v_n || ' document(s) in the vault';
      ELSE status := 'missing'; detail := v_n || ' of ' || coalesce((r->>'min_count')::int, 1) || ' required in the vault';
      END IF;

    ELSIF r->>'type' = 'min_years_registered' THEN
      SELECT extract(year FROM age(current_date, o.registration_date)) INTO v_n FROM orgs o WHERE o.id = p_org_id;
      IF v_n IS NULL THEN status := 'missing'; detail := 'Registration date not recorded';
      ELSIF v_n >= (r->>'years')::numeric THEN status := 'pass'; detail := v_n || ' years since registration';
      ELSE status := 'fail'; detail := v_n || ' years since registration';
      END IF;

    ELSIF r->>'type' = 'min_income' THEN
      SELECT count(*), sum(f.total_income) INTO v_txt, v_n FROM (
        SELECT total_income FROM org_financials f2 WHERE f2.org_id = p_org_id AND f2.total_income IS NOT NULL
        ORDER BY f2.fiscal_year DESC LIMIT (r->>'fiscal_years')::int) f;
      IF v_txt::int < (r->>'fiscal_years')::int THEN
        status := 'missing'; detail := v_txt || ' of ' || (r->>'fiscal_years') || ' years of income recorded';
      ELSIF v_n >= (r->>'amount')::numeric THEN status := 'pass'; detail := 'Income over the period: ' || v_n;
      ELSE status := 'fail'; detail := 'Income over the period: ' || v_n;
      END IF;

    ELSIF r->>'type' = 'min_office_bearers' THEN
      SELECT count(*) INTO v_n FROM contacts c WHERE c.org_id = p_org_id AND c.kind = 'office_bearer';
      IF v_n = 0 THEN status := 'missing'; detail := 'No board members recorded';
      ELSIF v_n >= (r->>'count')::int THEN status := 'pass'; detail := v_n || ' board members recorded';
      ELSE status := 'fail'; detail := v_n || ' board members recorded';
      END IF;

    ELSIF r->>'type' = 'in_rfp_geography' THEN
      SELECT string_agg(DISTINCT l.name, ', ') INTO v_txt
      FROM (SELECT o.registered_location_id AS location_id FROM orgs o WHERE o.id = p_org_id
            UNION SELECT ol.location_id FROM org_locations ol WHERE ol.org_id = p_org_id) w
      JOIN locations l ON l.id = w.location_id
      JOIN rfp_locations rl ON rl.rfp_id = v_rfp
       AND (rl.location_id = w.location_id
            OR rl.location_id = (SELECT lp.state_id FROM location_paths lp WHERE lp.id = w.location_id));
      IF v_rfp IS NULL THEN status := 'manual'; detail := 'Template has no RFP';
      ELSIF v_txt IS NOT NULL THEN status := 'pass'; detail := 'Works in ' || v_txt;
      ELSE status := 'fail'; detail := 'None of the org''s places is in the RFP geography';
      END IF;

    ELSIF r->>'type' = 'has_stage' THEN
      SELECT count(*) INTO v_n FROM metrics m
      WHERE m.org_id = p_org_id AND m.stage = r->>'stage' AND m.value IS NOT NULL;
      IF v_n > 0 THEN status := 'pass'; detail := v_n || ' ' || (r->>'stage') || ' figure(s) with data';
      ELSE status := 'missing'; detail := 'No ' || (r->>'stage') || ' figures with data';
      END IF;

    ELSE
      status := 'manual'; detail := 'Unknown rule type';
    END IF;
    RETURN NEXT;
  END LOOP;
END $$;

-- =====================================================================================
-- 12. Access helpers (schema 'app' is not exposed by the Supabase API)
-- =====================================================================================

CREATE SCHEMA IF NOT EXISTS app;
GRANT USAGE ON SCHEMA app TO anon, authenticated;

CREATE FUNCTION app.user_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT id FROM users WHERE auth_user_id = auth.uid() $$;

CREATE FUNCTION app.is_staff() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT coalesce((SELECT is_staff FROM users WHERE auth_user_id = auth.uid()), false) $$;

-- Orgs the caller can read privately (any role, stewards included).
CREATE FUNCTION app.my_org_ids() RETURNS bigint[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT coalesce(array_agg(m.org_id), '{}') FROM org_members m
   JOIN users u ON u.id = m.user_id WHERE u.auth_user_id = auth.uid() $$;

-- Orgs the caller can upload to (stewards read, they do not write).
CREATE FUNCTION app.my_writable_org_ids() RETURNS bigint[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT coalesce(array_agg(m.org_id), '{}') FROM org_members m
   JOIN users u ON u.id = m.user_id
   WHERE u.auth_user_id = auth.uid() AND m.role IN ('admin', 'member') $$;

-- One thread-access rule, used by the backend before touching LangGraph checkpoints.
CREATE FUNCTION app.can_open_thread(p_thread_id text, p_user_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (
    SELECT 1
    FROM threads t
    LEFT JOIN org_members m ON m.org_id = t.org_id AND m.user_id = p_user_id
    WHERE t.thread_id = p_thread_id
      AND (   t.user_id = p_user_id
           OR (t.visibility = 'team' AND m.role IN ('admin', 'member'))
           OR (t.visibility = 'team_and_stewards' AND m.role IS NOT NULL)
           OR EXISTS (SELECT 1 FROM users u WHERE u.id = p_user_id AND u.is_staff))
  )
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM public;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO anon, authenticated;

-- =====================================================================================
-- 13. Row level security (applies to the Supabase API; the backend connects as the
--     table owner and applies the same rules in its own queries)
-- =====================================================================================

-- RLS on for every table. A table with no policy is invisible to the API
-- (extraction_log; graph_ingest_log, schema_migrations and checkpoint tables need
-- RLS switched on when they are created).
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;

-- Open registry: readable by anyone.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'locations', 'tags', 'org_tags', 'funder_tags', 'program_tags', 'rfp_tags',
    'org_locations', 'funder_locations', 'program_locations', 'rfp_locations', 'grant_locations',
    'location_designations', 'programs', 'grants', 'rfps', 'org_financials', 'metrics',
    'funder_identifiers', 'funder_csr_years', 'funder_csr_spend', 'funder_footprints', 'funder_partners',
    'rubrics', 'rubric_criteria', 'fit_scores', 'fit_score_items', 'score_adjustments',
    'reference_figures', 'proposal_templates', 'template_items'
  ] LOOP
    EXECUTE format('CREATE POLICY %I ON %I FOR SELECT TO anon, authenticated USING (true)', t || '_read', t);
  END LOOP;
END $$;

-- Contacts: office bearers (published on NGO Darpan) and rows marked public are open;
-- everything else, e.g. funder staff emails, needs sign-in.
CREATE POLICY contacts_read_anon ON contacts FOR SELECT TO anon
  USING (is_public OR kind = 'office_bearer');
CREATE POLICY contacts_read_auth ON contacts FOR SELECT TO authenticated USING (true);

CREATE POLICY orgs_read ON orgs FOR SELECT TO anon, authenticated
  USING (registry_status <> 'hidden' OR (SELECT app.is_staff()));
CREATE POLICY funders_read ON funders FOR SELECT TO anon, authenticated
  USING (registry_status <> 'hidden' OR (SELECT app.is_staff()));

CREATE POLICY org_identifiers_read ON org_identifiers FOR SELECT TO anon, authenticated
  USING (is_public OR org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

CREATE POLICY credential_events_read ON credential_events FOR SELECT TO anon, authenticated
  USING (verified OR org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

CREATE POLICY news_read ON news_mentions FOR SELECT TO anon, authenticated
  USING (review_status = 'vetted' OR org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

-- Private org data.
CREATE POLICY documents_read ON documents FOR SELECT TO anon, authenticated
  USING (is_public OR org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));
CREATE POLICY documents_upload ON documents FOR INSERT TO authenticated
  WITH CHECK (org_id = ANY ((SELECT app.my_writable_org_ids())::bigint[]) AND NOT is_public);

-- chunks follow their document (the documents policy applies inside the subquery).
CREATE POLICY chunks_read ON chunks FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM documents d WHERE d.id = chunks.document_id));

CREATE POLICY proposals_read ON proposals FOR SELECT TO authenticated
  USING (org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

CREATE POLICY rfp_matches_read ON rfp_matches FOR SELECT TO authenticated
  USING (org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

CREATE POLICY org_members_read ON org_members FOR SELECT TO authenticated
  USING (user_id = (SELECT app.user_id()) OR org_id = ANY ((SELECT app.my_org_ids())::bigint[]) OR (SELECT app.is_staff()));

-- Own rows, and threads shared with the team.
CREATE POLICY users_self ON users FOR SELECT TO authenticated
  USING (auth_user_id = (SELECT auth.uid()) OR (SELECT app.is_staff()));
CREATE POLICY threads_read ON threads FOR SELECT TO authenticated USING (
     user_id = (SELECT app.user_id())
  OR (visibility = 'team' AND org_id = ANY ((SELECT app.my_writable_org_ids())::bigint[]))
  OR (visibility = 'team_and_stewards' AND org_id = ANY ((SELECT app.my_org_ids())::bigint[]))
);

-- Vault files in Supabase Storage: bucket 'vault', path '<org_id>/<filename>'.
-- Skipped on the local container, which has no storage schema.
DO $$
BEGIN
  IF to_regclass('storage.objects') IS NOT NULL THEN
    INSERT INTO storage.buckets (id, name, public) VALUES ('vault', 'vault', false)
      ON CONFLICT (id) DO NOTHING;
    EXECUTE $p$CREATE POLICY vault_read ON storage.objects FOR SELECT TO authenticated USING (
      bucket_id = 'vault' AND ((storage.foldername(name))[1]::bigint = ANY ((SELECT app.my_org_ids())::bigint[])
                               OR (SELECT app.is_staff())))$p$;
    EXECUTE $p$CREATE POLICY vault_upload ON storage.objects FOR INSERT TO authenticated WITH CHECK (
      bucket_id = 'vault' AND (storage.foldername(name))[1]::bigint = ANY ((SELECT app.my_writable_org_ids())::bigint[]))$p$;
  END IF;
END $$;
