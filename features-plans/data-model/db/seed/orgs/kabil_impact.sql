-- db/seed/orgs/kabil_impact.sql
-- GENERATED from seed/data/orgs/kabil-impact.json. Edit the JSON.
-- KABIL programmes with scheme links, results chains (only stages the research file
-- states; missing stages are left empty on purpose) and credential findings. Idempotent.
-- Run after db/seed/reference_data.sql.

BEGIN;
CREATE OR REPLACE FUNCTION pg_temp.state_id(p_state text) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  SELECT id INTO v FROM locations WHERE kind = 'state'
    AND (lower(name) = lower(p_state) OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE lower(a) = lower(p_state)))
  ORDER BY id LIMIT 1;
  IF v IS NULL THEN
    INSERT INTO locations (kind, name, parent_id)
    VALUES ('state', p_state, (SELECT id FROM locations WHERE kind = 'country' AND name = 'India' AND parent_id IS NULL))
    RETURNING id INTO v;
  END IF;
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION pg_temp.child_id(p_parent bigint, p_kind text, p_names text[]) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
  SELECT l.id INTO v FROM locations l
  WHERE l.kind = p_kind AND l.parent_id = p_parent
    AND (lower(l.name) = ANY (SELECT lower(x) FROM unnest(p_names) x)
         OR EXISTS (SELECT 1 FROM unnest(l.aliases) a WHERE lower(a) = ANY (SELECT lower(x) FROM unnest(p_names) x)))
  ORDER BY l.id LIMIT 1;
  IF v IS NULL THEN
    INSERT INTO locations (kind, name, parent_id, aliases)
    VALUES (p_kind, p_names[1], p_parent, p_names[2:array_length(p_names, 1)])
    RETURNING id INTO v;
  END IF;
  RETURN v;
END $$;

DO $$ BEGIN PERFORM pg_temp.child_id(pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']), 'block', ARRAY['Mazbat']); END $$;
INSERT INTO programs (org_id, kind, name, status, description, source_url, source_name, fetched_at, as_of)
VALUES ((SELECT id FROM orgs WHERE slug = 'kabil'), 'programme', 'Sustainable livelihoods project, undivided Udalguri (Axis Bank Foundation)', 'concluded', '4-year livelihoods project in Udalguri and Harisinga with SHG and non-SHG families: agriculture, livestock, and MGNREGS individual beneficiary schemes such as farm ponds.', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25')
ON CONFLICT (org_id, name) WHERE org_id IS NOT NULL DO UPDATE SET status = EXCLUDED.status, description = EXCLUDED.description;
INSERT INTO program_tags (program_id, tag_id, role, is_inferred, tagged_by) SELECT (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Sustainable livelihoods project, undivided Udalguri (Axis Bank Foundation)'), id, 'primary', false, 'manual' FROM tags WHERE slug = 'scheme-mgnrega' ON CONFLICT DO NOTHING;
INSERT INTO program_locations (program_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Sustainable livelihoods project, undivided Udalguri (Axis Bank Foundation)'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']), 'operates', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25') ON CONFLICT DO NOTHING;
INSERT INTO programs (org_id, kind, name, status, description, source_url, source_name, fetched_at, as_of)
VALUES ((SELECT id FROM orgs WHERE slug = 'kabil'), 'programme', 'Livelihood improvement, Mazbat block (Azim Premji Foundation)', 'concluded', 'Small and marginal farmers in Mazbat block: agriculture and livestock interventions, training and adoption support. Ran from January 2021, concluded FY2023-24.', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25')
ON CONFLICT (org_id, name) WHERE org_id IS NOT NULL DO UPDATE SET status = EXCLUDED.status, description = EXCLUDED.description;
INSERT INTO program_locations (program_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Livelihood improvement, Mazbat block (Azim Premji Foundation)'), pg_temp.child_id(pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']), 'block', ARRAY['Mazbat']), 'operates', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25') ON CONFLICT DO NOTHING;
INSERT INTO programs (org_id, kind, name, status, description, source_url, source_name, fetched_at, as_of)
VALUES ((SELECT id FROM orgs WHERE slug = 'kabil'), 'programme', 'Promoting livelihoods for rural poor households, Mazbat block', 'active', 'Aims to raise the income of 2,000 households in selected village councils by an average of 50% of current income.', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25')
ON CONFLICT (org_id, name) WHERE org_id IS NOT NULL DO UPDATE SET status = EXCLUDED.status, description = EXCLUDED.description;
INSERT INTO program_locations (program_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Promoting livelihoods for rural poor households, Mazbat block'), pg_temp.child_id(pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']), 'block', ARRAY['Mazbat']), 'operates', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25') ON CONFLICT DO NOTHING;
INSERT INTO programs (org_id, kind, name, status, description, source_url, source_name, fetched_at, as_of)
VALUES ((SELECT id FROM orgs WHERE slug = 'kabil'), 'programme', 'DWIMU: Diversification with Integrated Management for the Upliftment of People''s Lives', 'active', '10,000 ST, SC and other vulnerable households, 20 VCDCs, 105 villages; convergence with Agriculture, Forest, Animal Husbandry and Fishery departments. Launched July 2024; tripartite MoU with ASRLM and BRLF.', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25')
ON CONFLICT (org_id, name) WHERE org_id IS NOT NULL DO UPDATE SET status = EXCLUDED.status, description = EXCLUDED.description;
INSERT INTO program_tags (program_id, tag_id, role, is_inferred, tagged_by) SELECT (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'DWIMU: Diversification with Integrated Management for the Upliftment of People''s Lives'), id, 'primary', false, 'manual' FROM tags WHERE slug = 'scheme-asrlm' ON CONFLICT DO NOTHING;
INSERT INTO program_tags (program_id, tag_id, role, is_inferred, tagged_by) SELECT (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'DWIMU: Diversification with Integrated Management for the Upliftment of People''s Lives'), id, 'primary', false, 'manual' FROM tags WHERE slug = 'scheme-pm-kisan' ON CONFLICT DO NOTHING;
INSERT INTO program_locations (program_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'DWIMU: Diversification with Integrated Management for the Upliftment of People''s Lives'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']), 'operates', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'annual reports to FY2024-25') ON CONFLICT DO NOTHING;

-- Results chains
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Sustainable livelihoods project, undivided Udalguri (Axis Bank Foundation)'), (SELECT id FROM grants WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND title = 'Sustainable livelihoods project, Udalguri (with ASRLM)'), 'Net families reached', 24765, 15000,
       'families', 'project total', 'output', 'kabil-abf-udalguri', 1, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'project total'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-abf-udalguri' AND sequence = 1);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Livelihood improvement, Mazbat block (Azim Premji Foundation)'), NULL, 'Farmers trained (agriculture and livestock)', 2000, NULL,
       'farmers', 'as of March 2023', 'output', 'kabil-apf-mazbat', 1, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'as of March 2023'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-apf-mazbat' AND sequence = 1);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Livelihood improvement, Mazbat block (Azim Premji Foundation)'), NULL, 'Net households reached', 2417, 2000,
       'households', 'FY2023-24', 'output', 'kabil-apf-mazbat', 2, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'FY2023-24'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-apf-mazbat' AND sequence = 2);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Livelihood improvement, Mazbat block (Azim Premji Foundation)'), NULL, 'Farmers cultivating under rain shelters', 1163, NULL,
       'farmers', 'FY2023-24', 'adoption', 'kabil-apf-mazbat', 3, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'FY2023-24'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-apf-mazbat' AND sequence = 3);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Livelihood improvement, Mazbat block (Azim Premji Foundation)'), NULL, 'Farmers using trellis cultivation', 931, NULL,
       'farmers', 'FY2023-24', 'adoption', 'kabil-apf-mazbat', 4, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'FY2023-24'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-apf-mazbat' AND sequence = 4);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Promoting livelihoods for rural poor households, Mazbat block'), NULL, 'SHGs with livelihood plans', 15, NULL,
       'SHGs', 'FY2024-25', 'output', 'kabil-mazbat-2024', 1, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'FY2024-25'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-mazbat-2024' AND sequence = 1);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'Promoting livelihoods for rural poor households, Mazbat block'), NULL, 'Average household income increase', NULL, 50,
       '% of current income', 'project target', 'outcome', 'kabil-mazbat-2024', 2, NULL, true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'project target'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-mazbat-2024' AND sequence = 2);
INSERT INTO metrics (org_id, program_id, grant_id, name, value, target, unit, period, stage, chain_key, sequence, method, is_self_reported,
                     source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), (SELECT id FROM programs WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND name = 'DWIMU: Diversification with Integrated Management for the Upliftment of People''s Lives'), NULL, 'Households with vegetable or horticulture plans submitted to the Agriculture Department', 4000, 10000,
       'households', 'FY2024-25', 'output', 'kabil-dwimu', 1, 'self_reported', true, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/ngos/KABIL/KABIL_Programs_and_Reports.md', 'org-grant-intelligence', TIMESTAMPTZ '2026-09-27', 'FY2024-25'
WHERE NOT EXISTS (SELECT 1 FROM metrics WHERE chain_key = 'kabil-dwimu' AND sequence = 1);

-- Credential findings
INSERT INTO credential_events (org_id, credential, event, event_date, verified, notes, source_url, source_name, fetched_at)
SELECT (SELECT id FROM orgs WHERE slug = 'kabil'), 'csr1', 'not_available', DATE '2026-09-10', true, 'Single source, not checked against the MCA register', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/hand-vetting/KABIL_Fact_Check_Verified.md', 'give.do', TIMESTAMPTZ '2026-09-10'
WHERE NOT EXISTS (SELECT 1 FROM credential_events WHERE org_id = (SELECT id FROM orgs WHERE slug = 'kabil') AND credential = 'csr1' AND event = 'not_available' AND event_date = DATE '2026-09-10');

COMMIT;
