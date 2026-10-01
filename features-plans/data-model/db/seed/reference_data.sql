-- db/seed/reference_data.sql
-- GENERATED from the JSON files in seed/data/reference/. Edit the JSON, not this file.
-- Idempotent. Run AFTER `python -m seed.seed`, so districts seed.py creates (e.g.
-- 'GOALPARA') are matched instead of duplicated. Then run `python -m seed.taxonomy_seed`.
--
--   1. CSR Schedule VII groups and development sectors as tags (kind 'csr_sector')
--   2. Geographic priority tags (kind 'theme') that funders can be tagged with
--   3. The 112 NITI Aayog aspirational districts, with state rows where missing
--   4. The 8 North East states, designated 'north_east'
--   5. Government schemes as tags (from government_schemes.json)
--   6. Reference figures (from reference_figures.json)
-- Existing district rows are matched by name or alias, case-insensitively, and never
-- renamed (seed.py matches on the stored name); the source spelling is added as an alias.

BEGIN;

-- 1. CSR Schedule VII ------------------------------------------------------------
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-health-hunger-poverty-water-sanitation', 'Health, Eradicating Hunger, Poverty and Malnutrition, Safe Drinking Water, Sanitation', 'csr_sector', 'VII(i)', 'group', 'Eradicating hunger, poverty and malnutrition, promoting health care including preventive health care and sanitation including contribution to the Swach Bharat Kosh set-up by the Central Government for the promotion of sanitation and making available safe drinking water.', '{"schedule_vii": ["i"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-health-care', 'Health Care', 'csr_sector', 'health-care', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-health-hunger-poverty-water-sanitation'), '{"schedule_vii": ["i"], "sdgs": ["sdg-3"], "maps_to": ["sector-health"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-poverty-hunger-malnutrition', 'Poverty, Eradicating Hunger, Malnutrition', 'csr_sector', 'poverty-hunger-malnutrition', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-health-hunger-poverty-water-sanitation'), '{"schedule_vii": ["i"], "sdgs": ["sdg-1", "sdg-2"], "maps_to": ["sector-nutrition", "sector-livelihoods"], "open_to_ngos": true}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-safe-drinking-water', 'Safe Drinking Water', 'csr_sector', 'safe-drinking-water', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-health-hunger-poverty-water-sanitation'), '{"schedule_vii": ["i"], "sdgs": ["sdg-6"], "maps_to": ["sector-water-sanitation"], "open_to_ngos": true}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-sanitation', 'Sanitation', 'csr_sector', 'sanitation', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-health-hunger-poverty-water-sanitation'), '{"schedule_vii": ["i"], "sdgs": ["sdg-6"], "maps_to": ["sector-water-sanitation"], "open_to_ngos": true}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-swachh-bharat-kosh', 'Swachh Bharat Kosh', 'csr_sector', 'VII(i)', 'group', 'Contribution towards Swachh Bharat Kosh', '{"schedule_vii": ["i"], "open_to_ngos": false, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-swachh-bharat-kosh', 'Swachh Bharat Kosh', 'csr_sector', 'swachh-bharat-kosh', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-swachh-bharat-kosh'), '{"schedule_vii": ["i"], "sdgs": ["sdg-6"], "maps_to": [], "open_to_ngos": false, "note": "Government fund contribution, not open to NGOs"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-education-differently-abled-livelihood', 'Education, Differently Abled, Livelihood', 'csr_sector', 'VII(ii)', 'group', 'Promoting education, including special education and employment enhancing vocation skills especially among children, women, elderly and the differently abled and livelihood enhancement projects', '{"schedule_vii": ["ii"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-education', 'Education', 'csr_sector', 'education', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-education-differently-abled-livelihood'), '{"schedule_vii": ["ii"], "sdgs": ["sdg-4"], "maps_to": ["sector-education"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-special-education', 'Special Education', 'csr_sector', 'special-education', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-education-differently-abled-livelihood'), '{"schedule_vii": ["ii"], "sdgs": ["sdg-4", "sdg-10"], "maps_to": ["sector-education", "sector-disability-inclusion", "pop-persons-with-disabilities"], "open_to_ngos": true}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-vocational-skills', 'Vocational Skills', 'csr_sector', 'vocational-skills', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-education-differently-abled-livelihood'), '{"schedule_vii": ["ii"], "sdgs": ["sdg-4", "sdg-8"], "maps_to": ["sector-skilling"], "open_to_ngos": true}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-livelihood-enhancement', 'Livelihood Enhancement Projects', 'csr_sector', 'livelihood-enhancement', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-education-differently-abled-livelihood'), '{"schedule_vii": ["ii"], "sdgs": ["sdg-1", "sdg-8"], "maps_to": ["sector-livelihoods"], "open_to_ngos": true}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-gender-women-elderly-inequalities', 'Gender Equality, Women Empowerment, Old Age Homes, Reducing Inequalities', 'csr_sector', 'VII(iii)', 'group', 'Promoting gender equality, empowering women, setting up homes and hostels for women and orphans; setting up old age homes, day care centers and such other facilities for senior citizens and measures for reducing inequalities faced by socially and economically backward groups.', '{"schedule_vii": ["iii"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-gender-equality', 'Gender Equality', 'csr_sector', 'gender-equality', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-5"], "maps_to": ["sector-gender"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-women-empowerment', 'Women Empowerment', 'csr_sector', 'women-empowerment', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-5"], "maps_to": ["sector-gender", "pop-women"], "open_to_ngos": true}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-homes-hostels-women', 'Setting Up Homes And Hostels For Women', 'csr_sector', 'homes-hostels-women', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-5"], "maps_to": ["sector-gender", "pop-women"], "open_to_ngos": true}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-orphanage', 'Setting Up Orphanage', 'csr_sector', 'orphanage', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-1", "sdg-10"], "maps_to": ["pop-children"], "open_to_ngos": true}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-senior-citizens', 'Senior Citizens Welfare', 'csr_sector', 'senior-citizens', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-3", "sdg-10"], "maps_to": ["pop-elderly"], "open_to_ngos": true}'::jsonb, 4, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-socio-economic-inequalities', 'Socio-Economic Inequalities', 'csr_sector', 'socio-economic-inequalities', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-gender-women-elderly-inequalities'), '{"schedule_vii": ["iii"], "sdgs": ["sdg-10"], "maps_to": ["sector-governance-entitlements"], "open_to_ngos": true}'::jsonb, 5, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-environment-animal-welfare-conservation', 'Environment, Animal Welfare, Conservation of Resources', 'csr_sector', 'VII(iv)', 'group', 'Ensuring environmental sustainability, ecological balance, protection of flora and fauna, animal welfare, agroforestry, conservation of natural resources and maintaining quality of soil, air and water.', '{"schedule_vii": ["iv"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 4, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-environmental-sustainability', 'Environmental Sustainability', 'csr_sector', 'environmental-sustainability', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-environment-animal-welfare-conservation'), '{"schedule_vii": ["iv"], "sdgs": ["sdg-13", "sdg-15"], "maps_to": ["sector-environment-nrm"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-animal-welfare', 'Animal Welfare', 'csr_sector', 'animal-welfare', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-environment-animal-welfare-conservation'), '{"schedule_vii": ["iv"], "sdgs": ["sdg-15"], "maps_to": ["sector-environment-nrm"], "open_to_ngos": true}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-agro-forestry', 'Agro Forestry', 'csr_sector', 'agro-forestry', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-environment-animal-welfare-conservation'), '{"schedule_vii": ["iv"], "sdgs": ["sdg-13", "sdg-15"], "maps_to": ["sector-environment-nrm", "sector-agriculture-livelihoods"], "open_to_ngos": true}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-conservation-natural-resources', 'Conservation Of Natural Resources', 'csr_sector', 'conservation-natural-resources', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-environment-animal-welfare-conservation'), '{"schedule_vii": ["iv"], "sdgs": ["sdg-6", "sdg-15"], "maps_to": ["sector-environment-nrm"], "open_to_ngos": true}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-clean-ganga-fund', 'Clean Ganga Fund', 'csr_sector', 'VII(iv)', 'group', 'Contribution to the Clean Ganga Fund set-up by the Central Government for rejuvenation of the river Ganga', '{"schedule_vii": ["iv"], "open_to_ngos": false, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 5, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-clean-ganga-fund', 'Clean Ganga Fund', 'csr_sector', 'clean-ganga-fund', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-clean-ganga-fund'), '{"schedule_vii": ["iv"], "sdgs": ["sdg-6"], "maps_to": [], "open_to_ngos": false, "note": "Government fund contribution, not open to NGOs"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-heritage-art-culture', 'Heritage Art and Culture', 'csr_sector', 'VII(v)', 'group', 'Protection of national heritage, art and culture including restoration of buildings and sites of historical importance and works of art; setting up public libraries; promotion and development of traditional art and handicrafts', '{"schedule_vii": ["v"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 6, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-heritage-art-culture', 'Heritage Art And Culture', 'csr_sector', 'heritage-art-culture', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-heritage-art-culture'), '{"schedule_vii": ["v"], "sdgs": ["sdg-11"], "maps_to": ["sector-culture-craft"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-other-incubators-armed-forces-admin', 'Other Sectors (Technology Incubator and Benefits to Armed Forces and Admin Overheads)', 'csr_sector', 'VII(vi,ix(a))', 'group', 'Contribution to incubators or research and development projects in the field of science, technology, engineering and medicine, funded by the Central Government or State Government or Public Sector Undertaking or any agency of the Central Government or State Government; and measures for the benefit of armed forces veterans, war widows and their dependents, Central Armed Police Forces (CAPF) and Central Para Military Forces (CPMF) veterans, and their dependents including widows.', '{"schedule_vii": ["vi", "ix(a)"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 7, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-technology-incubators', 'Technology Incubators', 'csr_sector', 'technology-incubators', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-other-incubators-armed-forces-admin'), '{"schedule_vii": ["vi", "ix(a)"], "sdgs": ["sdg-9"], "maps_to": [], "open_to_ngos": false, "note": "Government-funded incubators and R&D only"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-armed-forces-veterans', 'Armed Forces Veterans, War Widows And Dependents', 'csr_sector', 'armed-forces-veterans', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-other-incubators-armed-forces-admin'), '{"schedule_vii": ["vi", "ix(a)"], "sdgs": ["sdg-16"], "maps_to": [], "open_to_ngos": true}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-admin-overheads', 'Admin Overheads', 'csr_sector', 'admin-overheads', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-other-incubators-armed-forces-admin'), '{"schedule_vii": ["vi", "ix(a)"], "sdgs": [], "maps_to": [], "open_to_ngos": false, "note": "The company''s own CSR administration, capped by the CSR Rules; not a programme area"}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-encouraging-sports', 'Encouraging Sports', 'csr_sector', 'VII(vii)', 'group', 'Training to promote rural sports, nationally recognised sports, Paralympic sports and Olympic sports', '{"schedule_vii": ["vii"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 8, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-training-promote-sports', 'Training To Promote Sports', 'csr_sector', 'training-promote-sports', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-encouraging-sports'), '{"schedule_vii": ["vii"], "sdgs": ["sdg-3"], "maps_to": ["sector-sports"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-pm-national-relief-fund', 'Prime Minister''s National Relief Fund', 'csr_sector', 'VII(viii)', 'group', 'Contribution to the prime minister''s national relief fund or Prime Minister''s Citizen Assistance and Relief in Emergency Situations Fund (PM CARES Fund) or any other fund set up by the central govt. for socio economic development and relief and welfare of the schedule caste, tribes, other backward classes, minorities and women', '{"schedule_vii": ["viii"], "open_to_ngos": false, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 9, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-pm-national-relief-fund', 'Prime Minister''s National Relief Fund', 'csr_sector', 'pm-national-relief-fund', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-pm-national-relief-fund'), '{"schedule_vii": ["viii"], "sdgs": ["sdg-1", "sdg-10"], "maps_to": [], "open_to_ngos": false, "note": "Government fund contribution, not open to NGOs"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-any-other-fund', 'Any Other Fund', 'csr_sector', 'VII(ix(b))', 'group', 'Contributions to public funded Universities; IITs; National Laboratories and autonomous bodies under DAE, DBT, DST, Department of Pharmaceuticals, AYUSH, MeitY and other bodies (DRDO, ICAR, ICMR, CSIR) engaged in research in science, technology, engineering and medicine aimed at promoting the SDGs', '{"schedule_vii": ["ix(b)"], "open_to_ngos": false, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 10, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-any-other-fund', 'Any Other Fund', 'csr_sector', 'any-other-fund', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-any-other-fund'), '{"schedule_vii": ["ix(b)"], "sdgs": ["sdg-9"], "maps_to": [], "open_to_ngos": false, "note": "Public research institutions only"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-rural-development', 'Rural Development', 'csr_sector', 'VII(x)', 'group', 'Rural development projects', '{"schedule_vii": ["x"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 11, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-rural-development', 'Rural Development Projects', 'csr_sector', 'rural-development', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-rural-development'), '{"schedule_vii": ["x"], "sdgs": ["sdg-1", "sdg-11"], "maps_to": ["sector-livelihoods"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-slum-area-development', 'Slum Area Development', 'csr_sector', 'VII(xi)', 'group', 'Slum Area Development Projects', '{"schedule_vii": ["xi"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 12, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-slum-area-development', 'Slum Area Development', 'csr_sector', 'slum-area-development', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-slum-area-development'), '{"schedule_vii": ["xi"], "sdgs": ["sdg-11"], "maps_to": [], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, description, meta, sort_order, status)
VALUES ('csr-g-disaster-management', 'Disaster Management', 'csr_sector', 'VII(xii)', 'group', 'Including relief, rehabilitation and reconstruction activities', '{"schedule_vii": ["xii"], "open_to_ngos": true, "source_url": "https://www.csrxchange.gov.in/frontend_assets/documents/DEVELOPMENT_SECTORS_IN_CSR.pdf", "scheme_version": "2026.1"}'::jsonb, 13, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  description = EXCLUDED.description, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, parent_id, meta, sort_order, status)
VALUES ('csr-disaster-management', 'Disaster Management', 'csr_sector', 'disaster-management', 'sector', (SELECT id FROM tags WHERE slug = 'csr-g-disaster-management'), '{"schedule_vii": ["xii"], "sdgs": ["sdg-11", "sdg-13"], "maps_to": ["sector-disaster-management"], "open_to_ngos": true}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  parent_id = EXCLUDED.parent_id, meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;

-- 2. Geographic priority tags ------------------------------------------------------
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-aspirational-districts', 'Aspirational districts', 'theme', 'geo_priority', '{"designation": "aspirational_district"}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-north-east', 'North East India', 'theme', 'geo_priority', '{"designation": "north_east"}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-tribal-areas', 'Tribal-dominated areas', 'theme', 'geo_priority', '{"designation": null, "note": "No place list loaded yet"}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-rainfed-regions', 'Rainfed regions', 'theme', 'geo_priority', '{"designation": null, "note": "No place list loaded yet"}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-conflict-affected', 'Conflict-affected areas', 'theme', 'geo_priority', '{"designation": null, "note": "No place list loaded yet"}'::jsonb, 4, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;
INSERT INTO tags (slug, label, kind, level, meta, sort_order, status)
VALUES ('geo-himalayan', 'Himalayan regions', 'theme', 'geo_priority', '{"designation": null, "note": "No place list loaded yet"}'::jsonb, 5, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, level = EXCLUDED.level, meta = EXCLUDED.meta;

-- 3 and 4. Places and designations ---------------------------------------------------------
DO $$
DECLARE
  r record;
  v_india bigint;
  v_state bigint;
  v_dist bigint;
BEGIN
  SELECT id INTO v_india FROM locations WHERE kind = 'country' AND name = 'India' AND parent_id IS NULL;
  IF v_india IS NULL THEN
    INSERT INTO locations (kind, name) VALUES ('country', 'India') RETURNING id INTO v_india;
  END IF;

  FOR r IN SELECT * FROM (VALUES
    (1, 'Andhra Pradesh', 'Vizianagaram', 'Vizianagaram', '{}'::text[]),
    (2, 'Andhra Pradesh', 'Visakhapatnam', 'Visakhapatnam', '{}'::text[]),
    (3, 'Andhra Pradesh', 'Y.S.R. Kadapa', 'YSR Kadapa', ARRAY['Y.S.R. Kadapa','Kadapa','Cuddapah']::text[]),
    (4, 'Arunachal Pradesh', 'Namsai', 'Namsai', '{}'::text[]),
    (5, 'Assam', 'Goalpara', 'Goalpara', '{}'::text[]),
    (6, 'Assam', 'Barpeta', 'Barpeta', '{}'::text[]),
    (7, 'Assam', 'Hailakandi', 'Hailakandi', '{}'::text[]),
    (8, 'Assam', 'Baksa', 'Baksa', '{}'::text[]),
    (9, 'Assam', 'Darrang', 'Darrang', '{}'::text[]),
    (10, 'Assam', 'Udalguri', 'Udalguri', '{}'::text[]),
    (11, 'Assam', 'Dhubri', 'Dhubri', '{}'::text[]),
    (12, 'Bihar', 'Sitamarhi', 'Sitamarhi', '{}'::text[]),
    (13, 'Bihar', 'Araria', 'Araria', '{}'::text[]),
    (14, 'Bihar', 'Purnia', 'Purnia', '{}'::text[]),
    (15, 'Bihar', 'Katihar', 'Katihar', '{}'::text[]),
    (16, 'Bihar', 'Muzaffarpur', 'Muzaffarpur', '{}'::text[]),
    (17, 'Bihar', 'Begusarai', 'Begusarai', '{}'::text[]),
    (18, 'Bihar', 'Khagaria', 'Khagaria', '{}'::text[]),
    (19, 'Bihar', 'Banka', 'Banka', '{}'::text[]),
    (20, 'Bihar', 'Sheikhpura', 'Sheikhpura', '{}'::text[]),
    (21, 'Bihar', 'Aurangabad', 'Aurangabad', ARRAY['Aurangabad (Bihar)']::text[]),
    (22, 'Bihar', 'Gaya', 'Gaya', '{}'::text[]),
    (23, 'Bihar', 'Nawada', 'Nawada', '{}'::text[]),
    (24, 'Bihar', 'Jamui', 'Jamui', '{}'::text[]),
    (25, 'Chhattisgarh', 'Korba', 'Korba', '{}'::text[]),
    (26, 'Chhattisgarh', 'Rajnandgaon', 'Rajnandgaon', '{}'::text[]),
    (27, 'Chhattisgarh', 'Mahasamund', 'Mahasamund', '{}'::text[]),
    (28, 'Chhattisgarh', 'Kanker', 'Uttar Bastar Kanker', ARRAY['Kanker']::text[]),
    (29, 'Chhattisgarh', 'Narayanpur', 'Narayanpur', '{}'::text[]),
    (30, 'Chhattisgarh', 'Dantewada', 'Dakshin Bastar Dantewada', ARRAY['Dantewada']::text[]),
    (31, 'Chhattisgarh', 'Bijapur', 'Bijapur', '{}'::text[]),
    (32, 'Chhattisgarh', 'Bastar', 'Bastar', '{}'::text[]),
    (33, 'Chhattisgarh', 'Kondagaon', 'Kondagaon', '{}'::text[]),
    (34, 'Chhattisgarh', 'Sukma', 'Sukma', '{}'::text[]),
    (35, 'Gujarat', 'Dahod', 'Dahod', '{}'::text[]),
    (36, 'Gujarat', 'Narmada', 'Narmada', '{}'::text[]),
    (37, 'Haryana', 'Mewat', 'Nuh', ARRAY['Mewat']::text[]),
    (38, 'Himachal Pradesh', 'Chamba', 'Chamba', '{}'::text[]),
    (39, 'Jammu and Kashmir', 'Kupwara', 'Kupwara', '{}'::text[]),
    (40, 'Jammu and Kashmir', 'Baramulla', 'Baramulla', '{}'::text[]),
    (41, 'Jharkhand', 'Garhwa', 'Garhwa', '{}'::text[]),
    (42, 'Jharkhand', 'Chatra', 'Chatra', '{}'::text[]),
    (43, 'Jharkhand', 'Giridih', 'Giridih', '{}'::text[]),
    (44, 'Jharkhand', 'Godda', 'Godda', '{}'::text[]),
    (45, 'Jharkhand', 'Sahibganj', 'Sahebganj', ARRAY['Sahibganj']::text[]),
    (46, 'Jharkhand', 'Pakur', 'Pakur', '{}'::text[]),
    (47, 'Jharkhand', 'Bokaro', 'Bokaro', '{}'::text[]),
    (48, 'Jharkhand', 'Lohardaga', 'Lohardaga', '{}'::text[]),
    (49, 'Jharkhand', 'Purbi Singhbhum', 'East Singhbhum', ARRAY['Purbi Singhbhum']::text[]),
    (50, 'Jharkhand', 'Palamu', 'Palamu', '{}'::text[]),
    (51, 'Jharkhand', 'Latehar', 'Latehar', '{}'::text[]),
    (52, 'Jharkhand', 'Hazaribagh', 'Hazaribagh', '{}'::text[]),
    (53, 'Jharkhand', 'Ramgarh', 'Ramgarh', '{}'::text[]),
    (54, 'Jharkhand', 'Dumka', 'Dumka', '{}'::text[]),
    (55, 'Jharkhand', 'Ranchi', 'Ranchi', '{}'::text[]),
    (56, 'Jharkhand', 'Khunti', 'Khunti', '{}'::text[]),
    (57, 'Jharkhand', 'Gumla', 'Gumla', '{}'::text[]),
    (58, 'Jharkhand', 'Simdega', 'Simdega', '{}'::text[]),
    (59, 'Jharkhand', 'Pashchimi Singhbhum', 'West Singhbhum', ARRAY['Pashchimi Singhbhum']::text[]),
    (60, 'Karnataka', 'Raichur', 'Raichur', '{}'::text[]),
    (61, 'Karnataka', 'Yadgir', 'Yadgir', '{}'::text[]),
    (62, 'Kerala', 'Wayanad', 'Wayanad', '{}'::text[]),
    (63, 'Madhya Pradesh', 'Chhatarpur', 'Chhatarpur', '{}'::text[]),
    (64, 'Madhya Pradesh', 'Damoh', 'Damoh', '{}'::text[]),
    (65, 'Madhya Pradesh', 'Barwani', 'Barwani', '{}'::text[]),
    (66, 'Madhya Pradesh', 'Rajgarh', 'Rajgarh', '{}'::text[]),
    (67, 'Madhya Pradesh', 'Vidisha', 'Vidisha', '{}'::text[]),
    (68, 'Madhya Pradesh', 'Guna', 'Guna', '{}'::text[]),
    (69, 'Madhya Pradesh', 'Singrauli', 'Singrauli', '{}'::text[]),
    (70, 'Madhya Pradesh', 'Khandwa', 'Khandwa (East Nimar)', ARRAY['Khandwa','East Nimar']::text[]),
    (71, 'Maharashtra', 'Nandurbar', 'Nandurbar', '{}'::text[]),
    (72, 'Maharashtra', 'Washim', 'Washim', '{}'::text[]),
    (73, 'Maharashtra', 'Gadchiroli', 'Gadchiroli', '{}'::text[]),
    (74, 'Maharashtra', 'Osmanabad', 'Dharashiv', ARRAY['Osmanabad']::text[]),
    (75, 'Manipur', 'Chandel', 'Chandel', '{}'::text[]),
    (76, 'Meghalaya', 'Ribhoi', 'Ri Bhoi', ARRAY['Ribhoi']::text[]),
    (77, 'Mizoram', 'Mamit', 'Mamit', '{}'::text[]),
    (78, 'Nagaland', 'Kiphire', 'Kiphire', '{}'::text[]),
    (79, 'Odisha', 'Dhenkanal', 'Dhenkanal', '{}'::text[]),
    (80, 'Odisha', 'Gajapati', 'Gajapati', '{}'::text[]),
    (81, 'Odisha', 'Kandhamal', 'Kandhamal', '{}'::text[]),
    (82, 'Odisha', 'Balangir', 'Balangir', ARRAY['Bolangir']::text[]),
    (83, 'Odisha', 'Kalahandi', 'Kalahandi', '{}'::text[]),
    (84, 'Odisha', 'Rayagada', 'Rayagada', '{}'::text[]),
    (85, 'Odisha', 'Koraput', 'Koraput', '{}'::text[]),
    (86, 'Odisha', 'Malkangiri', 'Malkangiri', '{}'::text[]),
    (87, 'Odisha', 'Nabarangpur', 'Nabarangpur', '{}'::text[]),
    (88, 'Odisha', 'Nuapada', 'Nuapada', '{}'::text[]),
    (89, 'Punjab', 'Moga', 'Moga', '{}'::text[]),
    (90, 'Punjab', 'Firozpur', 'Ferozepur', ARRAY['Firozpur']::text[]),
    (91, 'Rajasthan', 'Dholpur', 'Dholpur', '{}'::text[]),
    (92, 'Rajasthan', 'Karauli', 'Karauli', '{}'::text[]),
    (93, 'Rajasthan', 'Jaisalmer', 'Jaisalmer', '{}'::text[]),
    (94, 'Rajasthan', 'Sirohi', 'Sirohi', '{}'::text[]),
    (95, 'Rajasthan', 'Baran', 'Baran', '{}'::text[]),
    (96, 'Sikkim', 'West Sikkim', 'Gyalshing', ARRAY['West Sikkim']::text[]),
    (97, 'Tamil Nadu', 'Virudhunagar', 'Virudhunagar', '{}'::text[]),
    (98, 'Tamil Nadu', 'Ramanathapuram', 'Ramanathapuram', '{}'::text[]),
    (99, 'Telangana', 'Asifabad', 'Kumuram Bheem Asifabad', ARRAY['Asifabad','Komaram Bheem Asifabad']::text[]),
    (100, 'Telangana', 'Bhoopalapally', 'Jayashankar Bhupalpally', ARRAY['Bhoopalapally','Bhupalpally']::text[]),
    (101, 'Telangana', 'Bhadradri-Kothagudem', 'Bhadradri-Kothagudem', '{}'::text[]),
    (102, 'Tripura', 'Dhalai', 'Dhalai', '{}'::text[]),
    (103, 'Uttar Pradesh', 'Chitrakoot', 'Chitrakoot', '{}'::text[]),
    (104, 'Uttar Pradesh', 'Fatehpur', 'Fatehpur', '{}'::text[]),
    (105, 'Uttar Pradesh', 'Bahraich', 'Bahraich', '{}'::text[]),
    (106, 'Uttar Pradesh', 'Shrawasti', 'Shravasti', ARRAY['Shrawasti']::text[]),
    (107, 'Uttar Pradesh', 'Balrampur', 'Balrampur', '{}'::text[]),
    (108, 'Uttar Pradesh', 'Siddharthnagar', 'Siddharthnagar', ARRAY['Siddharth Nagar']::text[]),
    (109, 'Uttar Pradesh', 'Chandauli', 'Chandauli', '{}'::text[]),
    (110, 'Uttar Pradesh', 'Sonbhadra', 'Sonbhadra', '{}'::text[]),
    (111, 'Uttarakhand', 'Udham Singh Nagar', 'Udham Singh Nagar', '{}'::text[]),
    (112, 'Uttarakhand', 'Haridwar', 'Haridwar', '{}'::text[])
  ) AS t(sr, state, listed, name, aliases) LOOP
    SELECT id INTO v_state FROM locations
    WHERE kind = 'state' AND (lower(name) = lower(r.state)
                              OR EXISTS (SELECT 1 FROM unnest(aliases) a WHERE lower(a) = lower(r.state)))
    ORDER BY id LIMIT 1;
    IF v_state IS NULL THEN
      INSERT INTO locations (kind, name, parent_id) VALUES ('state', r.state, v_india) RETURNING id INTO v_state;
    END IF;

    SELECT id INTO v_dist FROM locations l
    WHERE l.kind = 'district' AND l.parent_id = v_state
      AND (lower(l.name) IN (lower(r.name), lower(r.listed))
           OR EXISTS (SELECT 1 FROM unnest(l.aliases) a WHERE lower(a) IN (lower(r.name), lower(r.listed))))
    ORDER BY l.id LIMIT 1;
    IF v_dist IS NULL THEN
      INSERT INTO locations (kind, name, parent_id, aliases)
      VALUES ('district', r.name, v_state, r.aliases) RETURNING id INTO v_dist;
    ELSE
      UPDATE locations l SET aliases = coalesce((
        SELECT array_agg(DISTINCT x) FROM unnest(l.aliases || r.aliases || ARRAY[r.name, r.listed]) x
        WHERE lower(x) <> lower(l.name)), '{}')
      WHERE l.id = v_dist;
    END IF;

    INSERT INTO location_designations (location_id, designation, programme, list_rank, name_as_listed,
                                       valid_from, source_name, fetched_at, as_of, notes)
    VALUES (v_dist, 'aspirational_district', 'Transformation of Aspirational Districts Programme (NITI Aayog)', r.sr, r.listed,
            DATE '2018-01-01', 'Aspirational Districts list (uploaded PDF)', TIMESTAMPTZ '2026-09-27', '2018 list',
            CASE WHEN r.name <> r.listed THEN 'Listed as ' || r.listed ELSE NULL END)
    ON CONFLICT (location_id, designation) DO UPDATE SET
      list_rank = EXCLUDED.list_rank, name_as_listed = EXCLUDED.name_as_listed, notes = EXCLUDED.notes;
  END LOOP;

  FOR r IN SELECT * FROM (VALUES ('Arunachal Pradesh'), ('Assam'), ('Manipur'), ('Meghalaya'), ('Mizoram'), ('Nagaland'), ('Sikkim'), ('Tripura')) AS t(state) LOOP
    SELECT id INTO v_state FROM locations WHERE kind = 'state' AND lower(name) = lower(r.state) ORDER BY id LIMIT 1;
    IF v_state IS NULL THEN
      INSERT INTO locations (kind, name, parent_id) VALUES ('state', r.state, v_india) RETURNING id INTO v_state;
    END IF;
    INSERT INTO location_designations (location_id, designation, programme, source_name, fetched_at)
    VALUES (v_state, 'north_east', 'North Eastern Region (North Eastern Council member states)',
            'Ministry of Development of North Eastern Region', TIMESTAMPTZ '2026-09-27')
    ON CONFLICT (location_id, designation) DO NOTHING;
  END LOOP;
END $$;


-- 5. Government schemes as tags (kind 'scheme'), from seed/data/reference/government_schemes.json
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-mgnrega', 'Mahatma Gandhi National Rural Employment Guarantee Act (MGNREGA)', 'scheme', 'mgnrega', 'scheme', '{"ministry": "Ministry of Rural Development", "maps_to": ["sector-livelihoods"]}'::jsonb, 0, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-day-nrlm', 'Deendayal Antyodaya Yojana - National Rural Livelihoods Mission (DAY-NRLM)', 'scheme', 'day-nrlm', 'scheme', '{"ministry": "Ministry of Rural Development", "maps_to": ["sector-livelihoods", "sector-financial-inclusion", "pop-shg-members"]}'::jsonb, 1, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-asrlm', 'Assam State Rural Livelihoods Mission (ASRLM)', 'scheme', 'asrlm', 'state_mission', '{"ministry": "Government of Assam", "maps_to": ["sector-livelihoods", "pop-shg-members"], "state": "Assam"}'::jsonb, 2, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-ddu-gky', 'Deen Dayal Upadhyaya Grameen Kaushalya Yojana (DDU-GKY)', 'scheme', 'ddu-gky', 'scheme', '{"ministry": "Ministry of Rural Development", "maps_to": ["sector-skilling", "pop-youth"]}'::jsonb, 3, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmkvy', 'Pradhan Mantri Kaushal Vikas Yojana (PMKVY)', 'scheme', 'pmkvy', 'scheme', '{"ministry": "Ministry of Skill Development and Entrepreneurship", "maps_to": ["sector-skilling", "pop-youth"]}'::jsonb, 4, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pm-kisan', 'Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)', 'scheme', 'pm-kisan', 'scheme', '{"ministry": "Ministry of Agriculture and Farmers Welfare", "maps_to": ["sector-agriculture-livelihoods", "pop-small-marginal-farmers"]}'::jsonb, 5, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmksy', 'Pradhan Mantri Krishi Sinchayee Yojana (PMKSY)', 'scheme', 'pmksy', 'scheme', '{"ministry": "Ministry of Agriculture and Farmers Welfare; Ministry of Jal Shakti", "maps_to": ["sector-agriculture-livelihoods", "sector-environment-nrm"]}'::jsonb, 6, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmfby', 'Pradhan Mantri Fasal Bima Yojana (PMFBY)', 'scheme', 'pmfby', 'scheme', '{"ministry": "Ministry of Agriculture and Farmers Welfare", "maps_to": ["sector-agriculture-livelihoods", "sector-financial-inclusion"]}'::jsonb, 7, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-midh', 'Mission for Integrated Development of Horticulture (MIDH)', 'scheme', 'midh', 'scheme', '{"ministry": "Ministry of Agriculture and Farmers Welfare", "maps_to": ["sector-agriculture-livelihoods"]}'::jsonb, 8, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-nlm', 'National Livestock Mission (NLM)', 'scheme', 'nlm', 'scheme', '{"ministry": "Department of Animal Husbandry and Dairying", "maps_to": ["sector-agriculture-livelihoods"]}'::jsonb, 9, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmmsy', 'Pradhan Mantri Matsya Sampada Yojana (PMMSY)', 'scheme', 'pmmsy', 'scheme', '{"ministry": "Department of Fisheries", "maps_to": ["sector-agriculture-livelihoods"]}'::jsonb, 10, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pm-vishwakarma', 'PM Vishwakarma', 'scheme', 'pm-vishwakarma', 'scheme', '{"ministry": "Ministry of Micro, Small and Medium Enterprises", "maps_to": ["sector-culture-craft", "sector-msme"]}'::jsonb, 11, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmay-g', 'Pradhan Mantri Awaas Yojana - Gramin (PMAY-G)', 'scheme', 'pmay-g', 'scheme', '{"ministry": "Ministry of Rural Development", "maps_to": ["sector-infrastructure"]}'::jsonb, 12, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-jjm', 'Jal Jeevan Mission (JJM)', 'scheme', 'jjm', 'scheme', '{"ministry": "Ministry of Jal Shakti", "maps_to": ["sector-water-sanitation"]}'::jsonb, 13, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-sbm-g', 'Swachh Bharat Mission - Grameen (SBM-G)', 'scheme', 'sbm-g', 'scheme', '{"ministry": "Ministry of Jal Shakti", "maps_to": ["sector-water-sanitation"]}'::jsonb, 14, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-nhm', 'National Health Mission (NHM)', 'scheme', 'nhm', 'scheme', '{"ministry": "Ministry of Health and Family Welfare", "maps_to": ["sector-health"]}'::jsonb, 15, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-poshan', 'POSHAN Abhiyaan', 'scheme', 'poshan', 'scheme', '{"ministry": "Ministry of Women and Child Development", "maps_to": ["sector-nutrition", "pop-children", "pop-women"]}'::jsonb, 16, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-samagra-shiksha', 'Samagra Shiksha', 'scheme', 'samagra-shiksha', 'scheme', '{"ministry": "Ministry of Education", "maps_to": ["sector-education", "pop-children"]}'::jsonb, 17, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
INSERT INTO tags (slug, label, kind, code, level, meta, sort_order, status)
VALUES ('scheme-pmjdy', 'Pradhan Mantri Jan Dhan Yojana (PMJDY)', 'scheme', 'pmjdy', 'scheme', '{"ministry": "Department of Financial Services", "maps_to": ["sector-financial-inclusion"]}'::jsonb, 18, 'active')
ON CONFLICT (slug) DO UPDATE SET label = EXCLUDED.label, kind = EXCLUDED.kind, code = EXCLUDED.code, level = EXCLUDED.level,
  meta = EXCLUDED.meta, sort_order = EXCLUDED.sort_order;
UPDATE tags SET parent_id = (SELECT id FROM tags WHERE slug = 'scheme-day-nrlm') WHERE slug = 'scheme-asrlm';

-- 6. Reference figures, from seed/data/reference/reference_figures.json
INSERT INTO reference_figures (kind, name, value, unit, period, notes, source_name, fetched_at)
SELECT 'overhead_norm', 'Cap on a company''s CSR administrative overheads', 5, '% of total CSR expenditure for the year', 'from FY2021-22', 'Applies to the company''s own CSR administration, not to an NGO''s project budget; funders set their own limits for grantee overheads.', 'Companies (Corporate Social Responsibility Policy) Rules, 2014, rule 7(1), as amended on 22 January 2021', TIMESTAMPTZ '2026-09-27'
WHERE NOT EXISTS (SELECT 1 FROM reference_figures WHERE name = 'Cap on a company''s CSR administrative overheads');

COMMIT;
