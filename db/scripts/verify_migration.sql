-- Post-migration integrity checks (run after `make db-upgrade` restore step).
-- The linkage projection printed at the end must be byte-identical to the
-- documents_linkage.txt snapshot taken by `make db-backup`.

\set ON_ERROR_STOP on

DO $$
DECLARE
  n_docs int;
  n_ingest int;
  n_orgs int;
  n_funders int;
BEGIN
  SELECT count(*) INTO n_docs FROM documents;
  SELECT count(*) INTO n_ingest FROM graph_ingest_log;
  SELECT count(*) INTO n_orgs FROM orgs;
  SELECT count(*) INTO n_funders FROM funders;
  IF n_docs <> 96 THEN RAISE EXCEPTION 'documents: expected 96, got %', n_docs; END IF;
  IF n_ingest <> 29 THEN RAISE EXCEPTION 'graph_ingest_log: expected 29, got %', n_ingest; END IF;
  IF n_orgs <> 10 THEN RAISE EXCEPTION 'orgs: expected 10, got %', n_orgs; END IF;
  IF n_funders <> 4 THEN RAISE EXCEPTION 'funders: expected 4, got %', n_funders; END IF;
  RAISE NOTICE 'row counts OK: % documents, % graph_ingest_log, % orgs, % funders',
    n_docs, n_ingest, n_orgs, n_funders;
END $$;

-- The next documents id must be beyond the restored range (setval ran).
DO $$
DECLARE next_id bigint;
BEGIN
  next_id := nextval(pg_get_serial_sequence('documents', 'id'));
  IF next_id <= 96 THEN
    RAISE EXCEPTION 'documents id sequence not advanced (next=%): run setval', next_id;
  END IF;
  PERFORM setval(pg_get_serial_sequence('documents', 'id'), next_id - 1);
  RAISE NOTICE 'documents id sequence OK (next=%)', next_id;
END $$;

-- Linkage projection: diff against db/backups/<ts>/documents_linkage.txt
\echo --- documents linkage projection (diff against backup snapshot) ---
SELECT d.id || '|' || COALESCE(o.slug, '') || '|' || COALESCE(f.slug, '')
FROM documents d
LEFT JOIN orgs o ON o.id = d.org_id
LEFT JOIN funders f ON f.id = d.funder_id
ORDER BY d.id;
