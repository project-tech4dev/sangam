-- Hosts the importer read that nobody has classified yet, and room in the
-- review queue for RFP names.
--
-- A proposal is a note, never a permission: the access rule lives in
-- app/ingest/data/sources/*.json and changes in a pull request. Promoting a
-- proposal means someone adds it to that file with a basis and a robots check.

CREATE TABLE ingest_source_proposals (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  host text NOT NULL UNIQUE,
  first_seen_url text,
  seen_for text,                                   -- what the agent was reading it for
  robots_result text,                              -- 'allowed' | 'no_rules' | 'unreadable'
  times_seen int NOT NULL DEFAULT 1,
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'classified', 'rejected')),
  notes text,
  proposed_by_run bigint REFERENCES ingest_runs(id) ON DELETE SET NULL,
  reviewed_by uuid REFERENCES users(id),
  reviewed_at timestamptz,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingest_source_proposals_status_idx ON ingest_source_proposals (status, last_seen_at DESC);

-- An RFP source can raise an ambiguous name too, and the queue had no room for it.
ALTER TABLE resolution_queue DROP CONSTRAINT resolution_queue_entity_kind_check;
ALTER TABLE resolution_queue ADD CONSTRAINT resolution_queue_entity_kind_check
  CHECK (entity_kind IN ('org', 'funder', 'location', 'partner', 'rfp'));
