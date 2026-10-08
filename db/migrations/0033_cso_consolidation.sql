-- CSO consolidation, part one (spec: features-plans/data-model/2026-10-07-cso-model-consolidation.md §1-§2).
--
--   7 CSO tables       + source_type, evidence: the evidence tier every Import write carries (C7)
--   orgs               + website, description, aliases, staff_count, staff_count_note (C1)
--   org_financials     + foreign_unspent (C6)
--   org_identifiers    a surrogate key, a status, and a number that may not exist yet (C2, C3)
--   credential_events  folded into org_identifiers.status, then dropped (C2)
--   program_locations  dropped (C5); grant_locations goes with grants in 0034
--
-- DESTRUCTIVE: safe because the latest verified org event per credential is copied onto org_identifiers
-- first, funder events are history funders no longer keep (0031), and program_locations must be empty.
-- Before running against Supabase: SELECT count(*) on both dropped tables, and take a backup.

-- 0. Refuse to drop what this file cannot carry across.
DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM program_locations;
  IF n > 0 THEN
    RAISE EXCEPTION 'program_locations holds % rows and nothing replaces it; move them by hand before 0033', n;
  END IF;
END $$;

-- 1. Facts the sources state that had no column (C1, C6).
ALTER TABLE orgs
  ADD COLUMN website text,
  ADD COLUMN description text,
  ADD COLUMN aliases text[] NOT NULL DEFAULT '{}',
  ADD COLUMN staff_count integer CHECK (staff_count >= 0),
  ADD COLUMN staff_count_note text;               -- e.g. "20+ full-time professionals (team page)"
ALTER TABLE org_financials
  ADD COLUMN foreign_unspent numeric;             -- FC unutilised at year end (FCRA return), INR

-- 2. The evidence tier (C7). NULL means unranked: entered by a person, or written before tiers.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['orgs', 'org_identifiers', 'org_financials', 'org_locations', 'contacts',
                           'programs', 'metrics'] LOOP
    EXECUTE format(
      'ALTER TABLE public.%I '
      'ADD COLUMN source_type text CHECK (source_type IN (''registry'', ''org_document'', ''funder'', '
      '''staff_dataset'', ''manual_check'', ''prior_research'', ''aggregator'', ''seed'')), '
      'ADD COLUMN evidence text CHECK (evidence IN (''evidenced'', ''claimed'')), '
      'ADD CONSTRAINT %I CHECK ((source_type IS NULL) = (evidence IS NULL)), '
      'ADD CONSTRAINT %I CHECK (source_type IS NULL OR source_type NOT IN (''aggregator'', ''prior_research'') '
      'OR evidence = ''claimed'')',
      t, t || '_tier_pair', t || '_unverifiable_claimed');
  END LOOP;
END $$;

-- 3. org_identifiers: one row per registration, with or without a number yet (C3).
ALTER TABLE org_identifiers DROP CONSTRAINT org_identifiers_pkey;
ALTER TABLE org_identifiers
  ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ALTER COLUMN id_value DROP NOT NULL,
  ADD COLUMN status text NOT NULL DEFAULT 'registered' CHECK (status IN
    ('applied', 'provisional', 'registered', 'expired', 'suspended', 'cancelled',
     'surrendered', 'not_available', 'not_found', 'check_blocked')),
  ADD COLUMN valid_from date,
  ADD COLUMN valid_until date,
  ADD COLUMN checked_at timestamptz,
  ADD COLUMN checked_by uuid REFERENCES users(id),
  ADD COLUMN check_method text CHECK (check_method IN
    ('document', 'registry', 'manual_check', 'aggregator')),
  ADD COLUMN evidence_document_id bigint REFERENCES documents(id),
  ADD COLUMN application_ref text;                -- e.g. a Form 10AB acknowledgement number
CREATE UNIQUE INDEX org_identifiers_value_uq ON org_identifiers (id_type, id_value)
  WHERE id_value IS NOT NULL;
CREATE UNIQUE INDEX org_identifiers_open_uq ON org_identifiers (org_id, id_type)
  WHERE id_value IS NULL;

-- 4. credential_events -> the identifier row's status (C2). Only verified events ever set a status (0006);
-- a check that could not be made never replaces a known status, so check_blocked sorts last.
CREATE TEMP TABLE _latest_event AS
SELECT DISTINCT ON (org_id, credential)
  org_id, credential, valid_until, notes, source_url, source_name, fetched_at, as_of, document_id,
  archive_url, recorded_by, recorded_at,
  CASE event
    WHEN 'renewed' THEN 'registered' WHEN 'checked_active' THEN 'registered'
    WHEN 'restored' THEN 'registered'
    WHEN 'superseded' THEN NULL                   -- not a status: the number on file was replaced
    ELSE event
  END AS status
FROM credential_events
WHERE org_id IS NOT NULL AND verified
ORDER BY org_id, credential, (event = 'check_blocked'), event_date DESC, recorded_at DESC, id DESC;

UPDATE org_identifiers oi SET is_current = false
FROM _latest_event e
WHERE e.status IS NULL AND oi.org_id = e.org_id AND oi.id_type = e.credential;

UPDATE org_identifiers oi SET
  status = e.status,
  valid_until = coalesce(e.valid_until, oi.valid_until),
  checked_at = e.recorded_at,
  checked_by = e.recorded_by,
  evidence_document_id = coalesce(oi.evidence_document_id, e.document_id),
  notes = coalesce(oi.notes, e.notes)
FROM _latest_event e
WHERE e.status IS NOT NULL AND oi.org_id = e.org_id AND oi.id_type = e.credential;

-- A status with no identifier row (a CSR-1 that is 'not_available', say) becomes an open row.
INSERT INTO org_identifiers (org_id, id_type, id_value, status, valid_until, checked_at, checked_by,
  evidence_document_id, notes, source_url, source_name, fetched_at, as_of, document_id, archive_url)
SELECT e.org_id, e.credential, NULL, e.status, e.valid_until, e.recorded_at, e.recorded_by,
  e.document_id, e.notes, e.source_url, e.source_name, e.fetched_at, e.as_of, e.document_id, e.archive_url
FROM _latest_event e
WHERE e.status IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM org_identifiers oi WHERE oi.org_id = e.org_id AND oi.id_type = e.credential);

DO $$
DECLARE n bigint;
BEGIN
  SELECT (SELECT count(*) FROM credential_events) - (SELECT count(*) FROM _latest_event) INTO n;
  IF n > 0 THEN
    RAISE NOTICE '% credential_events rows are history (unverified, older, or a funder''s) and are not carried over', n;
  END IF;
END $$;

DROP TABLE _latest_event;

-- 5. What the seed wrote is the weakest tier, recognised by what seed.py stamps on it. Everything else
-- stays unranked; seed.py writes the tier itself from now on.
UPDATE orgs SET source_type = 'seed', evidence = 'claimed' WHERE extractor_version LIKE 'seed-%';
UPDATE org_identifiers SET source_type = 'seed', evidence = 'claimed' WHERE verified;
UPDATE org_locations SET source_type = 'seed', evidence = 'claimed'
  WHERE source_url IS NULL AND source_name IS NULL;
UPDATE contacts SET source_type = 'seed', evidence = 'claimed'
  WHERE org_id IS NOT NULL AND extractor_version IS NULL AND source_name IS DISTINCT FROM 'manual';

-- 6. Drop.
DROP TABLE credential_events;
DROP TABLE program_locations;

-- 7. Access: no new table, and 0025's SELECT grants cover the new columns, except two. checked_by names a
-- staff member and evidence_document_id may point at a private upload, so both are closed to anon and
-- authenticated by granting every other column instead of the table. org_identifiers_read (0027) reads only
-- is_public and org_id, and the new identity sequence stays ungranted (0025's default privileges).
DO $$
DECLARE cols text;
BEGIN
  SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) INTO cols
  FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'org_identifiers'
    AND column_name NOT IN ('checked_by', 'evidence_document_id');
  REVOKE SELECT ON org_identifiers FROM anon, authenticated;
  EXECUTE format('GRANT SELECT (%s) ON org_identifiers TO anon, authenticated', cols);
END $$;
