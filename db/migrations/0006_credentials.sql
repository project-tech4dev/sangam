-- A registration's number stays in *_identifiers and can be withheld; what
-- happened to it goes here, holding no number, so history can be public while
-- the number is not. Current status comes from the latest verified event.

ALTER TABLE org_identifiers
  ADD COLUMN is_public boolean NOT NULL DEFAULT true,  -- false = "on file, number not published"
  ADD COLUMN notes text;
CREATE INDEX org_identifiers_private_idx ON org_identifiers (org_id) WHERE NOT is_public;

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
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  recorded_by uuid REFERENCES users(id),
  recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX credential_events_org_idx ON credential_events (org_id, credential, event_date DESC)
  WHERE org_id IS NOT NULL;
CREATE INDEX credential_events_funder_idx ON credential_events (funder_id, credential, event_date DESC)
  WHERE funder_id IS NOT NULL;
