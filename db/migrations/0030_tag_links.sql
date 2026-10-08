-- The theme taxonomy: its rows live in tags, its cross-references here.
--
-- tags holds one row per thing (domain, theme, sub_theme, lens, sdg, scheme,
-- csr_sector) and parent_id carries the domain -> theme -> sub_theme tree. A
-- sub-theme also reports to SDGs, files under a Schedule VII clause and names
-- government schemes; a lens adds an SDG. Each of those is a row here, so the
-- link is a foreign key rather than a slug inside tags.meta.
--
-- No relation column: the linked tag's kind says what the link means.
-- Loaded by: python -m seed.taxonomy_seed

CREATE TABLE tag_links (
  tag_id        bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  linked_tag_id bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  note          text,                -- e.g. the MCA sector name under a Schedule VII clause
  PRIMARY KEY (tag_id, linked_tag_id),
  CHECK (tag_id <> linked_tag_id)
);

CREATE INDEX tag_links_linked_idx ON tag_links (linked_tag_id);

-- Public, like tags: 0025's default privileges leave a new table closed until granted, 0027 the rule.
GRANT SELECT ON tag_links TO anon, authenticated;
ALTER TABLE tag_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY tag_links_read ON tag_links FOR SELECT TO anon, authenticated USING (true);

ALTER TABLE tags DROP CONSTRAINT tags_kind_check;
ALTER TABLE tags ADD CONSTRAINT tags_kind_check CHECK (kind IN (
  'sdg', 'sector', 'population', 'darpan_sector', 'theme',
  'domain', 'cell', 'csr_sector', 'scheme', 'sub_theme', 'lens'));
