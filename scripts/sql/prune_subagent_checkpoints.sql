-- Deletes the subagent checkpoint namespaces of idle, settled threads; `make prune-checkpoints`. Dry run unless :apply.
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
SELECT l.thread_id, l.checkpoint_id FROM latest l
 WHERE l.ts < now() - make_interval(hours => :idle_hours)
   -- Any write on the latest checkpoint means a pause (an __interrupt__) or a run that died mid-step: both resume from it.
   AND NOT EXISTS (SELECT 1 FROM checkpoint_writes w
                    WHERE w.thread_id = l.thread_id AND w.checkpoint_ns = '' AND w.checkpoint_id = l.checkpoint_id);

CREATE TEMP TABLE sizes ON COMMIT DROP AS
SELECT thread_id, count(DISTINCT checkpoint_ns) AS namespaces, sum(n) AS n FROM (
  SELECT thread_id, checkpoint_ns, octet_length(blob) AS n FROM checkpoint_blobs
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
  UNION ALL
  SELECT thread_id, checkpoint_ns, octet_length(blob) FROM checkpoint_writes
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
  UNION ALL
  SELECT thread_id, checkpoint_ns, pg_column_size(checkpoint) + pg_column_size(metadata) FROM checkpoints
   WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM prune)
) t GROUP BY thread_id;

\echo '== subagent namespaces to delete, largest threads first'
SELECT thread_id, namespaces, pg_size_pretty(n) AS bytes FROM sizes ORDER BY n DESC LIMIT 20;

\echo '== total'
SELECT count(*) AS threads, pg_size_pretty(coalesce(sum(n), 0)) AS bytes FROM sizes;

\if :apply
-- A thread that moved on since it was picked (someone reopened it) is skipped: its subagent may be running.
CREATE TEMP TABLE settled ON COMMIT DROP AS
SELECT p.thread_id FROM prune p
 WHERE NOT EXISTS (SELECT 1 FROM checkpoints c
                    WHERE c.thread_id = p.thread_id AND c.checkpoint_ns = '' AND c.checkpoint_id > p.checkpoint_id);
\set QUIET off
DELETE FROM checkpoint_blobs  WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM settled);
DELETE FROM checkpoint_writes WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM settled);
DELETE FROM checkpoints       WHERE checkpoint_ns <> '' AND thread_id IN (SELECT thread_id FROM settled);
COMMIT;
\echo '== deleted. The disk shrinks only after pg_repack (or VACUUM FULL) on the three tables.'
\else
ROLLBACK;
\echo '== dry run: nothing deleted. APPLY=1 deletes.'
\endif
