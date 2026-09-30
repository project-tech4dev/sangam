-- What a researcher found about one organisation, kept as structure rather than
-- as a chat message. This is the artifact the client and entity docs render
-- from, and the reason research stops evaporating when a conversation ends.
--
-- It is NOT the catalog. A finding here is something a source said, with the
-- sentence that says it; promoting one into orgs/funders/funder_csr_years is a
-- separate, deliberate step.

CREATE TABLE entity_research (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_name text NOT NULL,                       -- as the user asked for it
  canonical_name text,                             -- as the strongest source writes it
  entity_kind text NOT NULL DEFAULT 'unknown'
    CHECK (entity_kind IN ('funder', 'org', 'unknown')),
  slug text NOT NULL,
  website text,
  status text NOT NULL
    CHECK (status IN ('complete', 'partial', 'not_found', 'wrong_entity')),
  stopped_reason text,                             -- why it ended where it did
  summary text NOT NULL,
  findings jsonb NOT NULL DEFAULT '[]'::jsonb,     -- one entry per fact, each with its evidence
  not_found text[] NOT NULL DEFAULT '{}',          -- concepts looked for and not there
  sources_read text[] NOT NULL DEFAULT '{}',
  fact_count int NOT NULL DEFAULT 0,
  resolved_org_id bigint REFERENCES orgs(id) ON DELETE SET NULL,
  resolved_funder_id bigint REFERENCES funders(id) ON DELETE SET NULL,
  researched_at timestamptz NOT NULL DEFAULT now(),
  -- A plain date, not researched_at::date: casting timestamptz depends on the
  -- session timezone, so it cannot be indexed.
  researched_on date NOT NULL DEFAULT current_date,
  run_id bigint REFERENCES ingest_runs(id) ON DELETE SET NULL,
  -- One row per entity per day: re-researching within a day replaces it,
  -- across days it accumulates, so a doc can show what changed.
  UNIQUE (slug, researched_on)
);
CREATE INDEX entity_research_recent ON entity_research (researched_at DESC);
