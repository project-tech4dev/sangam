-- One tags table for every vocabulary: SDGs, sectors, population groups, CSR
-- Schedule VII sectors, government schemes and the domain trees.
-- Unblocks: python -m seed.taxonomy_seed

ALTER TABLE tags
  ADD COLUMN domain text,
  ADD COLUMN code text,
  ADD COLUMN level text,
  ADD COLUMN description text,
  ADD COLUMN meta jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('draft', 'active', 'deprecated')),
  ADD COLUMN replaced_by bigint REFERENCES tags(id),
  ADD COLUMN sort_order int;

-- Widen kind. The 40 existing rows are all 'sector' and stay valid; the loader
-- re-labels the Darpan ones to 'darpan_sector' and the research ones to 'theme'.
ALTER TABLE tags DROP CONSTRAINT tags_kind_check;
ALTER TABLE tags ADD CONSTRAINT tags_kind_check CHECK (kind IN (
  'sdg', 'sector', 'population', 'darpan_sector', 'theme',
  'domain', 'cell', 'csr_sector', 'scheme'));

ALTER TABLE tags ADD CONSTRAINT tags_domain_required
  CHECK (kind NOT IN ('domain', 'cell') OR domain IS NOT NULL);

CREATE INDEX tags_kind_domain_idx ON tags (kind, domain) WHERE status = 'active';
CREATE INDEX tags_parent_idx ON tags (parent_id);
