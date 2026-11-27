-- The funder pool: a queue of candidate funders to research in rank order, and the switches the worker
-- reads every minute. A queue, not a second funders table: once a row is researched, funders is the truth.

CREATE TABLE funder_pool (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pool_funder_id text NOT NULL UNIQUE,
  funder_id bigint REFERENCES funders(id) ON DELETE SET NULL,
  category text NOT NULL,
  name text NOT NULL,
  cin text,
  rank_in_category integer,
  score_total numeric,
  csr_spend_3y_avg_cr numeric,
  in_sangam_at_load text,
  signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  ingest_status text NOT NULL DEFAULT 'pending'
    CHECK (ingest_status IN ('pending', 'running', 'done', 'failed', 'skipped', 'needs_review')),
  priority_override integer,
  attempts smallint NOT NULL DEFAULT 0,
  locked_at timestamptz,
  locked_by text,
  last_attempt_at timestamptz,
  last_completed_at timestamptz,
  last_error text,
  last_run_id bigint REFERENCES ingest_runs(id) ON DELETE SET NULL,
  export_version text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX funder_pool_queue_idx ON funder_pool (category, ingest_status, priority_override, rank_in_category);
CREATE INDEX funder_pool_cin_idx ON funder_pool (cin);
CREATE INDEX funder_pool_funder_idx ON funder_pool (funder_id);

CREATE TABLE funder_ingest_settings (
  category text PRIMARY KEY,
  enabled boolean NOT NULL DEFAULT false,
  max_parallel smallint NOT NULL DEFAULT 2 CHECK (max_parallel BETWEEN 0 AND 20),
  min_csr_spend_cr numeric,
  daily_cap integer CHECK (daily_cap >= 0),
  max_attempts smallint NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
  lock_timeout_min integer NOT NULL DEFAULT 60 CHECK (lock_timeout_min >= 1),
  updated_by text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Every category starts off; only indian_csr has a research path today.
INSERT INTO funder_ingest_settings (category, updated_by) VALUES
  ('indian_csr', 'migration'), ('western_funders', 'migration'), ('hni_family', 'migration'),
  ('government_india', 'migration'), ('bilateral_multilateral', 'migration');

-- Every funder, pooled or not, with its pull status. funders has no updated_at, so fetched_at stands in.
CREATE VIEW funder_pool_status AS
SELECT coalesce(f.id, p.funder_id) AS funder_id, coalesce(f.name, p.name) AS name, p.category,
       p.rank_in_category, coalesce(p.ingest_status, 'in_sangam') AS ingest_status,
       p.last_completed_at, p.last_error, f.fetched_at AS funder_fetched_at
  FROM funder_pool p
  FULL JOIN funders f ON f.id = p.funder_id;

-- Staff read; the worker and loader write as the owner. The view runs as its caller so RLS still applies.
ALTER VIEW funder_pool_status SET (security_invoker = true);
GRANT SELECT ON funder_pool, funder_ingest_settings, funder_pool_status TO authenticated;
ALTER TABLE funder_pool ENABLE ROW LEVEL SECURITY;
ALTER TABLE funder_ingest_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY funder_pool_read ON funder_pool FOR SELECT TO authenticated USING ((SELECT app.is_staff()));
CREATE POLICY funder_ingest_settings_read ON funder_ingest_settings FOR SELECT TO authenticated
    USING ((SELECT app.is_staff()));
