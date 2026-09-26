-- A SELECT-only role for the agent's text-to-SQL tool (db_query).
--
-- Why a role at all, when the validator already rejects writes: the app
-- connects as the database OWNER, which locally is a superuser. Inside a
-- READ ONLY transaction a superuser can still run pg_read_file('/etc/passwd')
-- and SELECT from the checkpoint tables, which hold every user's chat history
-- in this same database. Those are closed by the validator's function
-- allowlist today -- a denylist that must stay complete forever. This GRANT
-- closes them structurally, so a gap in the allowlist stops being a breach.
--
-- NOLOGIN on purpose: the tool reaches the role with SET LOCAL ROLE inside the
-- transaction it already opens, which reverts at COMMIT. No password, no
-- second connection string, no second pool, nothing to add to .env.
--
-- Honest limit: RESET ROLE returns to the superuser session, so this bounds
-- single statements only. Multi-statement input is blocked three other ways
-- (the parser's one-statement check, AST regeneration, and prepare=True, which
-- makes the server itself refuse multiple commands).
--
-- The table and column lists below are generated from
-- backend/app/agent/tools/sql/catalog.py. tests/test_sql_integration.py
-- asserts the GRANTs and the catalog still agree, at column granularity.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sangam_reader') THEN
    CREATE ROLE sangam_reader NOLOGIN;
  END IF;
END $$;

-- current_database(): 'sangam' locally, 'postgres' on Supabase.
DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO sangam_reader', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO sangam_reader;

-- Deliberately NOT "ALL TABLES IN SCHEMA public" and NOT ALTER DEFAULT
-- PRIVILEGES: a table added tomorrow must be unreadable until someone decides
-- it is safe.
GRANT SELECT ON
  documents,
  extraction_log,
  fit_score_items,
  fit_scores,
  funder_identifiers,
  funder_locations,
  funder_tags,
  funders,
  grants,
  locations,
  news_mentions,
  org_identifiers,
  org_locations,
  org_tags,
  orgs,
  program_locations,
  program_tags,
  programs,
  rfp_locations,
  rfp_matches,
  rfp_tags,
  rfps,
  rubric_criteria,
  rubrics,
  tags
TO sangam_reader;

-- Column-level where the catalog withholds columns, so a hole in column
-- validation still cannot reach them. A table-level grant on contacts would
-- hand over email and phone regardless of what the validator believed.
--   chunks: withholding content_tsv, embedding
GRANT SELECT (chunk_index, content, document_id, id)
  ON chunks TO sangam_reader;
--   contacts: withholding email, phone
GRANT SELECT (content_hash, extractor_version, fetched_at, funder_id, id, kind, name, notes, org_id, role, source_name, source_url, verified)
  ON contacts TO sangam_reader;
--   score_adjustments: withholding adjusted_by
GRANT SELECT (adjusted_at, criterion_id, fit_score_id, id, new_score, old_score, reason)
  ON score_adjustments TO sangam_reader;

-- Not granted, and why: checkpoints/checkpoint_* (every user's conversation
-- history), users and threads (account records), schema_migrations and
-- graph_ingest_log (infrastructure).

-- Lets the app's own role assume it. CURRENT_USER rather than a hardcoded
-- name so this works unchanged on Supabase, where the role is 'postgres'.
GRANT sangam_reader TO CURRENT_USER;
