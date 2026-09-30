-- Import runs: what was read, what was written, and what a person still has to
-- decide. resolution_queue is the sink the architecture spec asks for - a name
-- that identifiers and exact matching could not resolve waits here rather than
-- being merged into a registry row.

CREATE TABLE ingest_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'finished', 'failed')),
  requested_sources text[] NOT NULL DEFAULT '{}',   -- empty means every dispatchable source
  started_by uuid REFERENCES users(id),
  notes text
);
CREATE INDEX ingest_runs_started_idx ON ingest_runs (started_at DESC);

-- One row per record the run considered, including the ones it refused to write.
CREATE TABLE ingest_run_items (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES ingest_runs(id) ON DELETE CASCADE,
  source text NOT NULL,                             -- sources.py key, e.g. 'india_csr'
  record_kind text NOT NULL,                        -- 'funder' | 'funder_csr_year' | 'news_mention'
  status text NOT NULL CHECK (status IN (
    'added', 'updated', 'matched', 'queued', 'failed', 'refused')),
  reason text,                                      -- required for queued, failed and refused
  subject text,                                     -- the name as the source printed it
  target_table text,
  target_id text,                                   -- the row written or matched
  changes jsonb NOT NULL DEFAULT '{}'::jsonb,       -- {"column": {"old": ..., "new": ...}}
  match_method text CHECK (match_method IN ('identifier', 'exact', 'alias', 'trigram', 'none')),
  match_score numeric,                              -- similarity() when match_method = 'trigram'
  source_url text,
  document_id bigint REFERENCES documents(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingest_run_items_run_idx ON ingest_run_items (run_id, status);
CREATE INDEX ingest_run_items_source_idx ON ingest_run_items (source, created_at DESC);

-- Names that could not be resolved automatically. A reviewer accepts one of the
-- candidates or rejects them all; accepting writes the alias back so the next
-- run resolves it at step 2.
CREATE TABLE resolution_queue (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  raw_name text NOT NULL,
  entity_kind text NOT NULL CHECK (entity_kind IN ('org', 'funder', 'location', 'partner')),
  context jsonb NOT NULL DEFAULT '{}'::jsonb,       -- what the source said around the name
  candidates jsonb NOT NULL DEFAULT '[]'::jsonb,    -- [{"id": 4, "name": "...", "score": 0.62}]
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'accepted', 'rejected')),
  resolved_org_id bigint REFERENCES orgs(id),
  resolved_funder_id bigint REFERENCES funders(id),
  resolved_location_id bigint REFERENCES locations(id),
  reviewed_by uuid REFERENCES users(id),
  reviewed_at timestamptz,
  notes text,
  source text,                                      -- the ingest source that raised it
  run_item_id bigint REFERENCES ingest_run_items(id) ON DELETE SET NULL,
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (entity_kind, raw_name, source)
);
CREATE INDEX resolution_queue_pending_idx ON resolution_queue (entity_kind, created_at DESC)
  WHERE status = 'pending';
