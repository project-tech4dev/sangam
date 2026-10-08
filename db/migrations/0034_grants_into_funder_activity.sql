-- grants -> funder_activity partner lines (spec: features-plans/data-model/2026-10-07-cso-model-consolidation.md
-- §2, C4 and C5). A grant to a CSO is a funder_activity line, kind 'partner', partner_org_id set.
--
--   funder_activity  + start_date, end_date, relationship_status
--   proposals        grant_id -> awarded_activity_id
--   metrics          grant_id -> activity_id (ON DELETE CASCADE, as before)
--   news_mentions    grant_id -> activity_id
--   grants, grant_locations   dropped
--
-- One grant is one line, never split across years: its fiscal_year is the year of its start date, else its
-- end date, else the day the source was read, else the day the row was recorded, and notes says which when
-- it is not the start date. A multi-year grant keeps its whole amount on that line with both dates set.
--
-- DESTRUCTIVE: safe because every grant is copied and every reference re-pointed through an id map, and both
-- are asserted, before anything is dropped. What has no mechanical home stops the migration instead:
-- grant_locations rows, non-INR amounts, and a grant whose line already exists. Not carried: currency (every
-- copied amount is INR), content_hash, extractor_version, valid_from; outcomes move into notes as text.
-- Access: 0031's policy now decides, so a grant of a hidden funder becomes staff-only.
-- Before running against Supabase: count grants, grant_locations, non-INR grants and hidden funders' grants,
-- and take a backup.

-- 0. Refuse what this file cannot carry across.
DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM grant_locations;
  IF n > 0 THEN
    RAISE EXCEPTION 'grant_locations holds % rows and has no home after 0034; record them as footprint '
                    'lines by hand, then empty it', n;
  END IF;
  SELECT count(*) INTO n FROM grants WHERE amount IS NOT NULL AND currency <> 'INR';
  IF n > 0 THEN
    RAISE EXCEPTION 'grants holds % non-INR amounts and funder_activity.amount is INR; convert them by '
                    'hand before 0034', n;
  END IF;
END $$;

-- 1. What a grant carried that a partner line lacked.
ALTER TABLE funder_activity
  ADD COLUMN start_date date,
  ADD COLUMN end_date date,
  ADD COLUMN relationship_status text CHECK (relationship_status IN
    ('active', 'concluded', 'unconfirmed', 'dormant')),
  ADD COLUMN legacy_grant_id bigint;                   -- the id map; dropped in step 5

-- 2. Each grant as the line it becomes.
CREATE TEMP TABLE grant_lines ON COMMIT DROP AS
SELECT g.id AS grant_id, g.funder_id, g.org_id, g.program_id, g.title, g.amount, g.start_date, g.end_date,
  g.status, o.name AS org_name,
  'FY' || to_char(fy.y, 'FM0000') || '-' || to_char((fy.y + 1) % 100, 'FM00') AS fiscal_year,
  concat_ws(E'\n',
    g.notes,
    CASE WHEN g.outcomes <> '{}'::jsonb THEN 'Outcomes: ' ||
      (SELECT string_agg(key || ' ' || value, '; ' ORDER BY key) FROM jsonb_each_text(g.outcomes)) || '.' END,
    CASE basis.label
      WHEN 'end_date' THEN 'fiscal_year is the year of the end date; the start date was not stated.'
      WHEN 'fetched_at' THEN 'fiscal_year is the year the source was read; the start date was not stated.'
      WHEN 'valid_from' THEN 'fiscal_year is the year the row was recorded; the start date was not stated.'
    END,
    CASE WHEN g.valid_to IS NOT NULL THEN 'Superseded on ' || to_char(g.valid_to, 'YYYY-MM-DD') || '.' END,
    'Moved from grants #' || g.id || ' by 0034.') AS notes,
  g.source_url, g.source_name, g.fetched_at, g.as_of, g.document_id, g.archive_url
FROM grants g
JOIN orgs o ON o.id = g.org_id
CROSS JOIN LATERAL (SELECT
    CASE WHEN g.start_date IS NOT NULL THEN 'start_date' WHEN g.end_date IS NOT NULL THEN 'end_date'
         WHEN g.fetched_at IS NOT NULL THEN 'fetched_at' ELSE 'valid_from' END AS label,
    COALESCE(g.start_date, g.end_date, g.fetched_at::date, g.valid_from::date) AS d) basis
CROSS JOIN LATERAL (SELECT CASE WHEN extract(month FROM basis.d) >= 4 THEN extract(year FROM basis.d)::int
                                ELSE extract(year FROM basis.d)::int - 1 END AS y) fy;

-- 3. A line the key cannot hold twice stops the migration with names, rather than as a bare UniqueViolation.
DO $$
DECLARE clash text;
BEGIN
  SELECT string_agg(format('funder %s, %s, %L to %L', funder_id, fiscal_year, title, org_name), '; ')
    INTO clash
  FROM (SELECT funder_id, fiscal_year, program_id, title, org_name FROM grant_lines
        GROUP BY 1, 2, 3, 4, 5 HAVING count(*) > 1) d;
  IF clash IS NOT NULL THEN
    RAISE EXCEPTION 'two grants become one funder_activity line: %. Merge or retitle them before 0034', clash;
  END IF;
  SELECT string_agg(format('grants #%s and funder_activity #%s', l.grant_id, a.id), '; ') INTO clash
  FROM grant_lines l JOIN funder_activity a
    ON a.funder_id = l.funder_id AND a.kind = 'partner' AND a.fiscal_year = l.fiscal_year
   AND a.program_id IS NOT DISTINCT FROM l.program_id AND a.csr_sector_id IS NULL
   AND a.state_location_id IS NULL AND a.location_id IS NULL AND a.designation IS NULL
   AND a.project_name = l.title AND a.partner_name = l.org_name;
  IF clash IS NOT NULL THEN
    RAISE EXCEPTION 'a grant is already a partner line: %. Reconcile them by hand before 0034', clash;
  END IF;
END $$;

INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, project_name, partner_name,
  partner_canonical, partner_org_id, amount, start_date, end_date, relationship_status, notes, is_public,
  source_url, source_name, fetched_at, as_of, document_id, archive_url, legacy_grant_id)
SELECT funder_id, 'partner', fiscal_year, program_id, title, org_name, org_name, org_id, amount, start_date,
  end_date, status, notes, true, source_url, source_name, fetched_at, as_of, document_id, archive_url, grant_id
FROM grant_lines;

-- 4. Re-point through the map, and prove nothing was left behind before anything is dropped.
ALTER TABLE proposals ADD COLUMN awarded_activity_id bigint REFERENCES funder_activity(id);   -- set when awarded
ALTER TABLE metrics ADD COLUMN activity_id bigint REFERENCES funder_activity(id) ON DELETE CASCADE;
ALTER TABLE news_mentions ADD COLUMN activity_id bigint REFERENCES funder_activity(id);
UPDATE proposals p SET awarded_activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = p.grant_id;
UPDATE metrics m SET activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = m.grant_id;
UPDATE news_mentions n SET activity_id = a.id FROM funder_activity a WHERE a.legacy_grant_id = n.grant_id;

DO $$
DECLARE copied bigint; total bigint; lost bigint;
BEGIN
  SELECT count(*) INTO copied FROM funder_activity WHERE legacy_grant_id IS NOT NULL;
  SELECT count(*) INTO total FROM grants;
  IF copied <> total THEN
    RAISE EXCEPTION '0034 copied % of % grants; nothing dropped', copied, total;
  END IF;
  SELECT (SELECT count(*) FROM proposals WHERE grant_id IS NOT NULL AND awarded_activity_id IS NULL)
       + (SELECT count(*) FROM metrics WHERE grant_id IS NOT NULL AND activity_id IS NULL)
       + (SELECT count(*) FROM news_mentions WHERE grant_id IS NOT NULL AND activity_id IS NULL)
    INTO lost;
  IF lost > 0 THEN
    RAISE EXCEPTION '0034 left % references unmapped; nothing dropped', lost;
  END IF;
END $$;

CREATE INDEX metrics_activity_idx ON metrics (activity_id) WHERE activity_id IS NOT NULL;

-- 5. Drop. Columns first, so no FK still points at grants; tables, never DELETE (metrics.grant_id cascades).
ALTER TABLE proposals DROP COLUMN grant_id;
ALTER TABLE metrics DROP COLUMN grant_id;
ALTER TABLE news_mentions DROP COLUMN grant_id;
DROP TABLE grant_locations;
DROP TABLE grants;
ALTER TABLE funder_activity DROP COLUMN legacy_grant_id;
