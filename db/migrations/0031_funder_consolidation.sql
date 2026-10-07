-- Nine funder tables to five. Spec: features-plans/data-model/2026-10-07-funder-model-consolidation.md §2
-- (D1-D5, D7, D11, D12).
--
--   funders            + cin, aliases (from funder_identifiers; D1 discards pan/csr1/darpan/reg_no)
--   funder_activity    replaces funder_csr_spend, funder_footprints, funder_partners, one row per line
--   documents          holds eligibility (doc_type 'funder_eligibility') and templates ('proposal_template')
--   funder_csr_years   + local_area_spent
--
-- DESTRUCTIVE: drops seven tables. Safe because every row with a home is copied first (identifiers,
-- activity lines, eligibility rows), and the one table with no mechanical home - template_items, and
-- proposal_templates with it - stops the migration if it holds anything. Not carried: an eligibility
-- row's document_id (the new documents row is itself the page), the identifiers D1 discards, and a CIN
-- on a foundation-named funder (step 0 lists each in a NOTICE). Negative spend and CIN collisions stop it
-- too. documents.doc_type is free text, so the three new doc_type values need no DDL; the writer keeps
-- them reserved.
--
-- Numbered after #98's 0030. Renumber at merge if another branch takes 0031.
-- Before running against Supabase: SELECT count(*) on each dropped table, and take a backup.

-- A CIN names a company, and a foundation's legacy CIN is usually its parent's: the SQL twin of
-- matcher._is_foundation. pg_temp, so it goes with the session.
CREATE FUNCTION pg_temp.is_foundation(name text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $f$
  SELECT regexp_split_to_array(lower(name), '[^a-z0-9]+') && ARRAY['foundation', 'foundations', 'trust',
    'trusts', 'charitable', 'charities', 'society', 'sansthan', 'samiti']
$f$;

-- The one CIN each funder would keep, normalised as the writer does; a table, so step 6 can drop the source.
CREATE TEMP TABLE legacy_cin ON COMMIT DROP AS
SELECT DISTINCT ON (fi.funder_id) fi.funder_id, upper(regexp_replace(fi.id_value, '\s', '', 'g')) AS cin,
  pg_temp.is_foundation(f.name) AS on_foundation
FROM funder_identifiers fi JOIN funders f ON f.id = fi.funder_id
WHERE fi.id_type = 'cin'
ORDER BY fi.funder_id, fi.is_current DESC, fi.verified DESC, fi.id_value;

-- 0. Refuse to drop what this file cannot carry across.
DO $$
DECLARE n bigint; r record;
BEGIN
  SELECT count(*) INTO n FROM template_items;
  IF n > 0 THEN
    RAISE EXCEPTION 'template_items holds % rows and proposal_templates has no documents mapping for them; '
                    'move them by hand before 0031', n;
  END IF;
  SELECT count(*) INTO n FROM proposal_templates;
  IF n > 0 THEN
    RAISE EXCEPTION 'proposal_templates holds % rows; a template is now a documents row '
                    '(doc_type ''proposal_template''). Move them by hand before 0031', n;
  END IF;
  SELECT count(*) INTO n FROM funder_csr_spend WHERE amount < 0;
  IF n > 0 THEN
    RAISE EXCEPTION 'funder_csr_spend holds % rows with a negative amount and funder_activity.amount must be '
                    '>= 0; correct or delete them by hand before 0031', n;
  END IF;
  SELECT count(*) INTO n FROM (
    SELECT cin FROM legacy_cin WHERE NOT on_foundation GROUP BY cin HAVING count(*) > 1) d;
  IF n > 0 THEN
    RAISE EXCEPTION '% CIN value(s) are each held by more than one funder once case and whitespace are ignored, and '
                    'funders.cin is UNIQUE; merge or correct those funders by hand before 0031', n;
  END IF;
  FOR r IN SELECT lc.funder_id, lc.cin FROM legacy_cin lc WHERE lc.on_foundation LOOP
    RAISE NOTICE 'CIN % not copied onto foundation-named funder %: a CIN names a company', r.cin, r.funder_id;
  END LOOP;
  SELECT count(DISTINCT funder_id) INTO n FROM funder_eligibility WHERE source_url IS NULL;
  IF n > 0 THEN
    RAISE NOTICE '% funders have eligibility rows with no source_url; their document is keyed '
                 '''legacy:funder_eligibility/<funder_id>''', n;
  END IF;
END $$;

-- 1. funders: a corporate funder keeps its CIN (D1); other spellings become aliases (D2).
ALTER TABLE funders
  ADD COLUMN cin text UNIQUE,                          -- corporate funders only; trusts have none
  ADD COLUMN aliases text[] NOT NULL DEFAULT '{}';     -- other names it files or is reported under

-- 2. funder_identifiers -> columns.
UPDATE funders f SET aliases = a.names
FROM (
  SELECT funder_id, array_agg(spelling ORDER BY spelling) AS names
  FROM (
    SELECT DISTINCT ON (fi.funder_id, lower(btrim(fi.id_value))) fi.funder_id, btrim(fi.id_value) AS spelling
    FROM funder_identifiers fi JOIN funders own ON own.id = fi.funder_id
    WHERE fi.id_type = 'name' AND lower(btrim(fi.id_value)) <> lower(btrim(own.name))
    -- keep the mixed-case spelling over an all-caps or all-lower one
    ORDER BY fi.funder_id, lower(btrim(fi.id_value)), btrim(fi.id_value) = upper(btrim(fi.id_value)),
      btrim(fi.id_value) = lower(btrim(fi.id_value)), btrim(fi.id_value)
  ) d
  GROUP BY funder_id
) a
WHERE a.funder_id = f.id;

-- A foundation-named funder keeps no CIN (step 0 listed them); the parent gets its own on promote.
UPDATE funders f SET cin = c.cin FROM legacy_cin c WHERE c.funder_id = f.id AND NOT c.on_foundation;

UPDATE funders f SET website = CASE WHEN d.domain ~* '^https?://' THEN d.domain ELSE 'https://' || d.domain END
FROM (
  SELECT DISTINCT ON (funder_id) funder_id, btrim(id_value) AS domain
  FROM funder_identifiers WHERE id_type = 'domain'
  ORDER BY funder_id, is_current DESC, id_value
) d
WHERE d.funder_id = f.id AND (f.website IS NULL OR btrim(f.website) = '');

-- 3. funder_activity: one row per line of a CSR filing, annual report or partner list (D4).
CREATE TABLE funder_activity (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  funder_id bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('spend', 'footprint', 'partner', 'programme')),
  fiscal_year text NOT NULL CHECK (fiscal_year ~ '^FY\d{4}-\d{2}$'),
  program_id bigint REFERENCES programs(id) ON DELETE RESTRICT,  -- in the key, and required on 'programme'
  domain_tag_id bigint REFERENCES tags(id),            -- kind 'domain': one of the five
  theme_tag_id bigint REFERENCES tags(id),             -- kind 'theme' or 'sub_theme'; NULL when the
                                                       -- evidence supports no theme
  classified_by text CHECK (classified_by IN
    ('filed_sector', 'project_name', 'partner', 'report')),
  classification_note text,                            -- the evidence, e.g. "project 'Financial
                                                       -- Literacy & Inclusion'; filed under Education"
  classification_confirmed boolean NOT NULL DEFAULT false,
  csr_sector_id bigint REFERENCES tags(id),            -- Schedule VII, as filed
  state_location_id bigint REFERENCES locations(id),
  location_id bigint REFERENCES locations(id),         -- most specific place below state
  name_as_printed text,                                -- place as the source printed it
  project_name text,
  designation text,
  implementation_mode text CHECK (implementation_mode IN
    ('direct', 'implementing_agency', 'own_trust_or_section8', 'not_stated')),
  partner_name text,
  partner_canonical text,
  partner_org_id bigint REFERENCES orgs(id),
  partner_funder_id bigint REFERENCES funders(id),
  partner_csr1 text,                                   -- the PARTNER's CSR-1, when filed
  partner_kind text CHECK (partner_kind IN ('ngo', 'foundation', 'university', 'research',
    'government', 'armed_forces', 'hospital', 'network', 'company', 'other')),
  outlay numeric CHECK (outlay >= 0),
  amount numeric CHECK (amount >= 0),
  project_count integer,
  is_ongoing boolean,
  notes text,
  is_public boolean NOT NULL DEFAULT true,             -- false for a line a person marked internal
                                                       -- (D14); RLS gives it to staff only
  source_key text,                                     -- source registry key, e.g. 'mca_csr'
  source_url text, source_name text, fetched_at timestamptz, as_of text,
  document_id bigint REFERENCES documents(id), archive_url text,
  CHECK (kind <> 'spend' OR amount IS NOT NULL),
  CHECK (kind <> 'footprint' OR location_id IS NOT NULL OR state_location_id IS NOT NULL),
  CHECK (kind <> 'partner' OR partner_name IS NOT NULL),
  CHECK (kind <> 'programme' OR (program_id IS NOT NULL AND amount IS NOT NULL)),
  CHECK (domain_tag_id IS NULL OR classified_by IS NOT NULL),
  UNIQUE NULLS NOT DISTINCT (funder_id, kind, fiscal_year, program_id, csr_sector_id,
    state_location_id, location_id, designation, project_name, partner_name)
);
CREATE INDEX funder_activity_funder_kind_idx ON funder_activity (funder_id, kind, fiscal_year);
CREATE INDEX funder_activity_domain_idx ON funder_activity (domain_tag_id);
CREATE INDEX funder_activity_theme_idx ON funder_activity (theme_tag_id);
CREATE INDEX funder_activity_location_idx ON funder_activity (location_id, fiscal_year);
CREATE INDEX funder_activity_partner_org_idx ON funder_activity (partner_org_id);

-- Copies. Empty locally; on Supabase, count first (see the header).
INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, csr_sector_id, state_location_id,
  location_id, project_name, designation, implementation_mode, partner_name, partner_org_id, partner_csr1,
  amount, project_count, is_ongoing, notes, source_url, source_name, fetched_at, as_of, document_id,
  archive_url)
SELECT funder_id, 'spend', fiscal_year, program_id, csr_sector_id, state_location_id, district_location_id,
  project_name, designation,
  CASE via_agency WHEN true THEN 'implementing_agency' WHEN false THEN 'direct' END,
  implementing_agency, agency_org_id, agency_csr1, amount, project_count, is_ongoing, notes,
  source_url, source_name, fetched_at, as_of, document_id, archive_url
FROM funder_csr_spend;

-- A footprint's one location becomes the pair: a state goes to state_location_id; anything below a
-- state keeps its own id in location_id and its state parent in state_location_id.
INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, state_location_id, location_id,
  name_as_printed, notes, source_url, source_name, fetched_at, as_of, document_id, archive_url)
SELECT fp.funder_id, 'footprint', fp.fiscal_year, fp.program_id,
  CASE WHEN l.kind = 'state' THEN l.id WHEN p.kind = 'state' THEN p.id END,
  CASE WHEN l.kind = 'state' THEN NULL ELSE l.id END,
  fp.name_as_printed, fp.notes, fp.source_url, fp.source_name, fp.fetched_at, fp.as_of,
  fp.document_id, fp.archive_url
FROM funder_footprints fp
JOIN locations l ON l.id = fp.location_id
LEFT JOIN locations p ON p.id = l.parent_id;

INSERT INTO funder_activity (funder_id, kind, fiscal_year, program_id, partner_name, partner_canonical,
  partner_org_id, partner_funder_id, partner_csr1, partner_kind, notes, source_url, source_name,
  fetched_at, as_of, document_id, archive_url)
SELECT funder_id, 'partner', fiscal_year, program_id, partner_name, partner_canonical, org_id,
  partner_funder_id, partner_csr1, partner_kind, notes, source_url, source_name, fetched_at, as_of,
  document_id, archive_url
FROM funder_partners;

-- Eligibility (D3): one documents row per funder and page, the criteria kept verbatim under the three
-- headings EligibilityGuidelineRecord.content_md() writes.
INSERT INTO documents (funder_id, title, doc_type, content_md, source_url, source_name, fetched_at, as_of,
                       archive_url, is_public, status)
SELECT e.funder_id, 'Eligibility for applicants', 'funder_eligibility',
  concat_ws(E'\n\n',
    '## Statutory restatement' || E'\n\n'
      || string_agg(e.criterion, E'\n\n' ORDER BY e.id) FILTER (WHERE e.kind = 'statutory_restatement'),
    '## Its own bar' || E'\n\n'
      || string_agg(e.criterion, E'\n\n' ORDER BY e.id) FILTER (WHERE e.kind = 'own_bar'),
    '## Disqualifiers' || E'\n\n'
      || string_agg(e.criterion, E'\n\n' ORDER BY e.id) FILTER (WHERE e.kind = 'disqualifier'),
    '## Notes' || E'\n\n'
      || string_agg(btrim(e.notes), E'\n\n' ORDER BY e.id) FILTER (WHERE btrim(coalesce(e.notes, '')) <> '')),
  -- no URL: a stable synthetic key, so the text survives and the row can be found to re-source
  coalesce(e.source_url, 'legacy:funder_eligibility/' || e.funder_id),
  min(e.source_name), max(e.fetched_at), max(e.as_of), min(e.archive_url),
  f.registry_status <> 'hidden', 'read'
FROM funder_eligibility e JOIN funders f ON f.id = e.funder_id
GROUP BY e.funder_id, coalesce(e.source_url, 'legacy:funder_eligibility/' || e.funder_id), f.registry_status;

-- 4. The MCA return reports local-area spend; the table lacked it.
ALTER TABLE funder_csr_years ADD COLUMN local_area_spent numeric;

-- 5. A template is a documents row (D5). Step 0 proved no proposal names one.
ALTER TABLE proposals DROP CONSTRAINT proposals_template_id_fkey;
ALTER TABLE proposals ADD CONSTRAINT proposals_template_id_fkey
  FOREIGN KEY (template_id) REFERENCES documents(id);

-- 6. Drop, children first.
DROP TABLE template_items;
DROP TABLE proposal_templates;
DROP TABLE funder_eligibility;
DROP TABLE funder_partners;
DROP TABLE funder_footprints;
DROP TABLE funder_csr_spend;
DROP TABLE funder_identifiers;

-- 7. Access, as 0025 and 0027 would have classified it: a funder child, public read, hidden with a hidden
-- funder. Their guard blocks never run again, and 0025's default privileges leave a new table closed.
-- On top of that, a line marked internal (is_public = false, D14) is staff-only, like documents_read.
GRANT SELECT ON funder_activity TO anon, authenticated;
ALTER TABLE funder_activity ENABLE ROW LEVEL SECURITY;
CREATE POLICY funder_activity_read ON funder_activity FOR SELECT TO anon, authenticated
  USING ((is_public OR (SELECT app.is_staff()))
         AND EXISTS (SELECT 1 FROM public.funders f WHERE f.id = funder_id));
