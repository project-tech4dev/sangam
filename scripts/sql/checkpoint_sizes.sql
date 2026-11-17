-- Checkpoint bytes by table, thread, namespace and channel; `make checkpoint-sizes`. Read-only.
-- :thread is '' for every thread, or one thread_id. Uncompressed bytes drop on DELETE; on-disk size only after a repack.
\set QUIET on
BEGIN READ ONLY;

\echo '== tables: uncompressed bytes, and size on disk'
SELECT 'checkpoint_blobs' AS "table", pg_size_pretty(sum(octet_length(blob))) AS uncompressed,
       pg_size_pretty(pg_total_relation_size('checkpoint_blobs')) AS on_disk
  FROM checkpoint_blobs WHERE :'thread' = '' OR thread_id = :'thread'
UNION ALL
SELECT 'checkpoint_writes', pg_size_pretty(sum(octet_length(blob))), pg_size_pretty(pg_total_relation_size('checkpoint_writes'))
  FROM checkpoint_writes WHERE :'thread' = '' OR thread_id = :'thread'
UNION ALL
SELECT 'checkpoints', pg_size_pretty(sum(pg_column_size(checkpoint) + pg_column_size(metadata))),
       pg_size_pretty(pg_total_relation_size('checkpoints'))
  FROM checkpoints WHERE :'thread' = '' OR thread_id = :'thread';

\echo '== threads, largest first (blobs + writes)'
WITH b AS (
  SELECT thread_id, checkpoint_ns, octet_length(blob) AS n FROM checkpoint_blobs
  UNION ALL
  SELECT thread_id, checkpoint_ns, octet_length(blob) FROM checkpoint_writes
)
SELECT thread_id,
       pg_size_pretty(sum(n) FILTER (WHERE checkpoint_ns = '')) AS top_level,
       pg_size_pretty(sum(n) FILTER (WHERE checkpoint_ns <> '')) AS subagents,
       count(DISTINCT checkpoint_ns) FILTER (WHERE checkpoint_ns <> '') AS subagent_runs,
       pg_size_pretty(sum(n)) AS total
  FROM b WHERE :'thread' = '' OR thread_id = :'thread'
 GROUP BY thread_id ORDER BY sum(n) DESC LIMIT 20;

\echo '== channels (blobs + writes: messages and files are delta channels, saved as writes), top level vs subagents'
WITH c AS (
  SELECT thread_id, checkpoint_ns, channel, octet_length(blob) AS n FROM checkpoint_blobs
  UNION ALL
  SELECT thread_id, checkpoint_ns, channel, octet_length(blob) FROM checkpoint_writes
)
SELECT CASE WHEN checkpoint_ns = '' THEN 'top level' ELSE 'subagent' END AS level, channel,
       count(*) AS versions, pg_size_pretty(sum(n)) AS bytes, pg_size_pretty(max(n)::bigint) AS largest
  FROM c WHERE :'thread' = '' OR thread_id = :'thread'
 GROUP BY 1, 2 ORDER BY sum(n) DESC LIMIT 15;

ROLLBACK;
