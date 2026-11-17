-- Deletes the subagent checkpoint namespaces of idle, unpaused threads; `make prune-checkpoints`. Dry run unless :apply.
-- Whole namespaces only: messages and files are delta channels, so cutting a top-level chain would empty a chat.
\set QUIET on
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE prune ON COMMIT DROP AS
WITH latest AS (
  SELECT DISTINCT ON (thread_id) thread_id, checkpoint_id, (checkpoint->>'ts')::timestamptz AS ts
    FROM checkpoints
   WHERE checkpoint_ns = '' AND (:'thread' = '' OR thread_id = :'thread')
   ORDER BY thread_id, checkpoint_id DESC
)
SELECT l.thread_id FROM latest l
 WHERE l.ts < now() - make_interval(hours => :idle_hours)
   -- A thread paused on a card resumes from these checkpoints, at any age.
   AND NOT EXISTS (SELECT 1 FROM checkpoint_writes w
                    WHERE w.thread_id = l.thread_id AND w.checkpoint_ns = ''
                      AND w.checkpoint_id = l.checkpoint_id AND w.channel = '__interrupt__');

\echo '== subagent namespaces to delete, largest threads first'
WITH b AS (
  SELECT thread_id, checkpoint_ns, octet_length(blob) AS n FROM checkpoint_blobs
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
  UNION ALL
  SELECT thread_id, checkpoint_ns, octet_length(blob) FROM checkpoint_writes
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
)
SELECT thread_id, count(DISTINCT checkpoint_ns) AS namespaces, pg_size_pretty(sum(n)) AS bytes
  FROM b GROUP BY thread_id ORDER BY sum(n) DESC LIMIT 20;

\echo '== total'
SELECT count(DISTINCT thread_id) AS threads, pg_size_pretty(coalesce(sum(n), 0)) AS bytes FROM (
  SELECT thread_id, octet_length(blob) AS n FROM checkpoint_blobs
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
  UNION ALL
  SELECT thread_id, octet_length(blob) FROM checkpoint_writes
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
) t;

\if :apply
\set QUIET off
DELETE FROM checkpoint_blobs  WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune);
DELETE FROM checkpoint_writes WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune);
DELETE FROM checkpoints       WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune);
COMMIT;
\echo '== deleted. The disk shrinks only after pg_repack (or VACUUM FULL) on the three tables.'
\else
ROLLBACK;
\echo '== dry run: nothing deleted. APPLY=1 deletes.'
\endif
