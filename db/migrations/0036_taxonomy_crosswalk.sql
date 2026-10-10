-- Which Schedule VII clause each sector tag belongs to, in tags.meta->>'maps_to'.
--
-- Orgs carry kind='sector' tags and research gives funders kind='csr_sector'
-- ones, so the two sides never met. This is the one hop between them, read by
-- Ask Sangam's funder shortlist. A JSON null is a decision — "no clause fits",
-- usually a population group rather than a theme — never a gap.
--
-- INSERT, not UPDATE: migrate runs before seed/seed.py creates these rows, so
-- an UPDATE would match nothing on a fresh database. The seed's own conflict
-- clause rewrites only label, which leaves meta alone in either order. Slugs
-- are seed.py's slugify(label), copied from the seeded table.

INSERT INTO tags (slug, label, kind, meta) VALUES
  ('agriculture', 'agriculture', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('animal-husbandry', 'Animal Husbandry', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('animal-welfare', 'Animal Welfare', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('art-culture', 'Art & Culture', 'sector', '{"maps_to": "csr-national-heritage-art-culture"}'),
  ('children', 'Children', 'sector', '{"maps_to": null}'),
  ('civic-issues', 'Civic Issues', 'sector', '{"maps_to": null}'),
  ('community-development', 'community development', 'sector', '{"maps_to": null}'),
  ('dairying-fisheries', 'Dairying & Fisheries', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('dalit-upliftment', 'Dalit Upliftment', 'sector', '{"maps_to": "csr-gender-equality-and-inequality"}'),
  ('differently-abled', 'Differently Abled', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('disaster-management', 'Disaster Management', 'sector', '{"maps_to": "csr-disaster-management"}'),
  ('drinking-water', 'Drinking Water', 'sector', '{"maps_to": "csr-hunger-poverty-health"}'),
  ('education', 'education', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('education-literacy', 'Education & Literacy', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('environment', 'environment', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('environment-forests', 'Environment & Forests', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('food-processing', 'Food Processing', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('health', 'health', 'sector', '{"maps_to": "csr-hunger-poverty-health"}'),
  ('health-family-welfare', 'Health & Family Welfare', 'sector', '{"maps_to": "csr-hunger-poverty-health"}'),
  ('land-resources', 'Land Resources', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('livelihoods', 'livelihoods', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('micro-finance-shgs', 'Micro Finance (SHGs)', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('minority-issues', 'Minority Issues', 'sector', '{"maps_to": "csr-gender-equality-and-inequality"}'),
  ('natural-resource-management', 'natural resource management', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('nutrition', 'nutrition', 'sector', '{"maps_to": "csr-hunger-poverty-health"}'),
  ('rural-development', 'rural development', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('rural-development-poverty-alleviation', 'Rural Development & Poverty Alleviation', 'sector', '{"maps_to": "csr-rural-development"}'),
  ('school-education', 'school education', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('science-technology', 'Science & Technology', 'sector', '{"maps_to": "csr-technology-incubators-and-rnd"}'),
  ('shg-collectivisation', 'SHG collectivisation', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('skill-development', 'skill development', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('sports', 'Sports', 'sector', '{"maps_to": "csr-sports"}'),
  ('sustainable-livelihoods', 'sustainable livelihoods', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('tourism', 'Tourism', 'sector', '{"maps_to": null}'),
  ('tribal-affairs', 'Tribal Affairs', 'sector', '{"maps_to": "csr-gender-equality-and-inequality"}'),
  ('vocational-training', 'Vocational Training', 'sector', '{"maps_to": "csr-education-and-livelihoods"}'),
  ('water-conservation', 'water conservation', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('water-resources', 'Water Resources', 'sector', '{"maps_to": "csr-environment-and-animal-welfare"}'),
  ('women-s-development-empowerment', 'Women''s Development & Empowerment', 'sector', '{"maps_to": "csr-gender-equality-and-inequality"}'),
  ('youth-affairs', 'Youth Affairs', 'sector', '{"maps_to": null}')
ON CONFLICT (slug) DO UPDATE SET meta = tags.meta || EXCLUDED.meta;
