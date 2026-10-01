-- db/seed/funders/sbi_foundation_gramseva.sql
-- GENERATED from seed/data/templates/sbi-foundation-gramseva-2024.json. Edit the JSON.
-- SBI Foundation Gram Seva RFP (2024): the call, its geography, and its template with
-- eligibility gates, proposal sections, evaluation criteria and the 30-item document
-- checklist. Items with a check_rule can be tested with check_template(). Idempotent.

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

INSERT INTO documents (funder_id, title, doc_type, is_public, status, source_url, source_name, fetched_at, as_of)
SELECT (SELECT id FROM funders WHERE slug = 'sbi-foundation'), 'SBI Gram Seva: integrated rural development programme (RFP 2024)', 'rfp', true, 'read', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21'
WHERE NOT EXISTS (SELECT 1 FROM documents WHERE source_url = 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf');

INSERT INTO rfps (funder_id, title, url, status, deadline, amount_min, amount_max, details, source_url, source_name, fetched_at, as_of, document_id)
SELECT (SELECT id FROM funders WHERE slug = 'sbi-foundation'), 'SBI Gram Seva: integrated rural development programme (RFP 2024)', 'https://www.sbifoundation.in/request-for-proposal', 'closed', DATE '2024-12-12',
       30000000, 40000000, '{"term_months": 24, "published": "2024-11-21", "one_district_per_agency": true, "themes": ["Digitalisation", "Education", "Health", "WaSH", "Livelihoods", "Women Empowerment", "Infrastructure", "Environment"], "grant_release": "Quarterly or half-yearly against certified reports", "separate_sbi_account": true}'::jsonb, 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21', (SELECT id FROM documents WHERE source_url = 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf' ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM rfps WHERE title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)');

-- Geography: states on the list, and Assam's districts
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Bihar'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Jharkhand'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Uttar Pradesh'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Madhya Pradesh'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Odisha'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Chhattisgarh'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Ladakh'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Dadra and Nagar Haveli and Daman and Diu'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Jammu and Kashmir'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Andaman and Nicobar Islands'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.state_id('Puducherry'), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Karbi Anglong']::text[]), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['North Cachar Hills','Dima Hasao']::text[]), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['Udalguri']::text[]), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;
INSERT INTO rfp_locations (rfp_id, location_id, role, source_url, source_name, fetched_at, as_of) VALUES ((SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), pg_temp.child_id(pg_temp.state_id('Assam'), 'district', ARRAY['West Karbi Anglong']::text[]), 'funds', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21') ON CONFLICT DO NOTHING;

INSERT INTO proposal_templates (funder_id, rfp_id, name, kind, version, source_url, source_name, fetched_at, as_of, document_id)
SELECT (SELECT id FROM funders WHERE slug = 'sbi-foundation'), (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)'), 'SBI Gram Seva RFP 2024', 'rfp', '2024', 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf', 'sbi-foundation-rfp', TIMESTAMPTZ '2026-09-27', '2024-11-21', (SELECT id FROM documents WHERE source_url = 'https://github.com/project-tech4dev/org-grant-intelligence/blob/main/deep-agent-app/downloads/SBI_Foundation_GramSeva_RFP.pdf' ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024');

INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 1, 'eligibility', 'P1', 'At least 10 years of existence on the RFP publication date', NULL, true, '{"type": "min_years_registered", "years": 10}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 2, 'eligibility', 'P2', 'Has worked on at least 5 of the 10 listed rural development themes', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 3, 'eligibility', 'P3', 'No sub-letting, sub-contracting or outsourcing of activities', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 4, 'eligibility', 'P4', 'Self-declaration of non-discrimination on letterhead', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 5, 'eligibility', 'P5', 'Not blacklisted by any government agency or PSU', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 6, 'eligibility', 'C1', 'Rejected if cumulative annual revenue for the last 3 years is below Rs 5 crore', NULL, true, '{"type": "min_income", "fiscal_years": 3, "amount": 50000000}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 7, 'eligibility', 'C2', 'Rejected if the agency has political or religious associations', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 8, 'eligibility', 'C3', 'Rejected if the due diligence documents in Annexure II are missing', 'See the document items', true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 9, 'eligibility', 'C4', 'Rejected if the board has fewer than 3 members', NULL, true, '{"type": "min_office_bearers", "count": 3}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 10, 'eligibility', 'C5', 'Rejected if there are fewer than 5 permanent employees', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 11, 'eligibility', 'C6', 'Rejected if individual donors are among the top 3 donors', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 12, 'eligibility', 'G1', 'Project district is on the RFP list (one district per agency)', NULL, true, '{"type": "in_rfp_geography"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 13, 'section', 'S1', 'Implementation plan, step by step', 'Direct, concise and complete; omit anything not relevant to the RFP', true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 14, 'section', 'S2', 'Log frame with means of verification', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 15, 'section', 'S3', 'Work plan with clear timelines', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 16, 'section', 'S4', 'Detailed financials with cost break-ups, in INR inclusive of all taxes', 'Annexure IV financial format (Excel)', true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 17, 'criterion', 'A1', 'Alignment with Gram Seva programme objectives', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 18, 'criterion', 'A2', 'Clear and concise detailing of the proposed solution, implementation plan and outcomes', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 19, 'criterion', 'A3', 'Innovation in the project', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 20, 'criterion', 'A4', 'Risk-mitigation measures', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 21, 'criterion', 'A5', 'Comprehensiveness of the log frame and project timelines', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 22, 'criterion', 'A6', 'Project monitoring and evaluation process', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 23, 'criterion', 'A7', 'Proportion of admin and overhead costs in the total project budget', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 24, 'criterion', 'A8', 'Exit strategy and sustainability of the solution', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 25, 'criterion', 'B1', 'Minimum 10 years of existence', NULL, true, '{"type": "min_years_registered", "years": 10}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 26, 'criterion', 'B2', 'Strong presence (at least 3 years) in the proposed State/UT', NULL, true, '{"type": "in_rfp_geography"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 27, 'criterion', 'B3', 'Demonstrated capability to improve measurable outcomes', NULL, true, '{"type": "has_stage", "stage": "outcome"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 28, 'criterion', 'B4', 'In-house implementation team with more than 5 permanent employees', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 29, 'criterion', 'B5', 'Experience of integrated or holistic village development projects', NULL, true, NULL)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 30, 'document', 'D1', 'Proposal form', NULL, true, '{"type": "document", "doc_types": ["proposal_form"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 31, 'document', 'D2', 'Two donor feedbacks', NULL, true, '{"type": "document", "doc_types": ["donor_feedback"], "min_count": 2}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 32, 'document', 'D3', 'Memorandum of Association / Trust Deed / Rules and Regulations', NULL, true, '{"type": "document", "doc_types": ["trust_deed", "moa"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 33, 'document', 'D4', 'Registration certificate', NULL, true, '{"type": "credential", "credential": "reg_no"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 34, 'document', 'D5', '12A registration', NULL, true, '{"type": "credential", "credential": "12a"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 35, 'document', 'D6', '80G registration', NULL, true, '{"type": "credential", "credential": "80g"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 36, 'document', 'D7', 'FCRA certificate', NULL, true, '{"type": "credential", "credential": "fcra"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 37, 'document', 'D8', 'PAN', NULL, true, '{"type": "credential", "credential": "pan"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 38, 'document', 'D9', 'Address proof', NULL, true, '{"type": "document", "doc_types": ["address_proof"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 39, 'document', 'D10', 'IT returns, last 3 years', NULL, true, '{"type": "document", "doc_types": ["itr"], "min_count": 3}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 40, 'document', 'D11', 'Audited reports, last 3 years', NULL, true, '{"type": "document", "doc_types": ["audited_accounts"], "min_count": 3}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 41, 'document', 'D12', 'Self-declaration (format provided)', NULL, true, '{"type": "document", "doc_types": ["self_declaration"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 42, 'document', 'D13', 'Annual reports, last 3 years', NULL, true, '{"type": "document", "doc_types": ["annual_report"], "min_count": 3}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 43, 'document', 'D14', 'Organisation profile', NULL, true, '{"type": "document", "doc_types": ["org_profile"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 44, 'document', 'D15', 'Brief bio data of board members', NULL, true, '{"type": "document", "doc_types": ["board_bios"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 45, 'document', 'D16', 'Brief bio data of top management', NULL, true, '{"type": "document", "doc_types": ["management_bios"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 46, 'document', 'D17', 'Minutes of the last two board meetings', NULL, true, '{"type": "document", "doc_types": ["board_minutes"], "min_count": 2}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 47, 'document', 'D18', 'HR policy, including remuneration policies', NULL, true, '{"type": "document", "doc_types": ["hr_policy"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 48, 'document', 'D19', 'Finance policy, including procurement and assets', NULL, true, '{"type": "document", "doc_types": ["finance_policy"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 49, 'document', 'D20', 'Organogram', NULL, true, '{"type": "document", "doc_types": ["organogram"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 50, 'document', 'D21', 'Detailed budget sheet in Excel', NULL, true, '{"type": "document", "doc_types": ["budget"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 51, 'document', 'D22', 'Third-party evaluation, audit or impact assessment reports', NULL, true, '{"type": "document", "doc_types": ["evaluation_report"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 52, 'document', 'D23', 'MIS for planning, tracking and reviewing', NULL, true, '{"type": "document", "doc_types": ["mis"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 53, 'document', 'D24', 'Profile of key leaders and founders', NULL, true, '{"type": "document", "doc_types": ["leader_profiles"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 54, 'document', 'D25', 'Press reports', NULL, true, '{"type": "document", "doc_types": ["press"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 55, 'document', 'D26', 'Awards and recognitions', NULL, true, '{"type": "document", "doc_types": ["awards"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 56, 'document', 'D27', 'Feedback mechanism', NULL, true, '{"type": "document", "doc_types": ["feedback_mechanism"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 57, 'document', 'D28', 'Monitoring mechanism or software in place', NULL, true, '{"type": "document", "doc_types": ["monitoring_system"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 58, 'document', 'D29', 'GST certificate', NULL, true, '{"type": "document", "doc_types": ["gst_certificate"]}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;
INSERT INTO template_items (template_id, ord, item_kind, code, heading, guidance, required, check_rule)
VALUES ((SELECT id FROM proposal_templates WHERE name = 'SBI Gram Seva RFP 2024' AND rfp_id = (SELECT id FROM rfps WHERE funder_id = (SELECT id FROM funders WHERE slug = 'sbi-foundation') AND title = 'SBI Gram Seva: integrated rural development programme (RFP 2024)')), 59, 'document', 'D30', 'Form CSR-1', NULL, true, '{"type": "credential", "credential": "csr1"}'::jsonb)
ON CONFLICT (template_id, ord) DO UPDATE SET item_kind = EXCLUDED.item_kind, code = EXCLUDED.code, heading = EXCLUDED.heading,
  guidance = EXCLUDED.guidance, check_rule = EXCLUDED.check_rule;

COMMIT;
