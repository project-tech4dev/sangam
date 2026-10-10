-- Who saved Import research into the catalog, and every catalog row each save wrote, so staff can undo
-- a save. A trigger logs the writes while a save has set sangam.promotion_id; nothing else is logged.
CREATE TABLE promotions (
    id           bigserial PRIMARY KEY,
    research_id  bigint REFERENCES entity_research(id) ON DELETE SET NULL,
    slug         text NOT NULL,
    promoted_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    promoted_at  timestamptz NOT NULL DEFAULT now(),
    undone_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    undone_at    timestamptz
);
CREATE INDEX promotions_slug ON promotions (slug, promoted_at DESC);
CREATE INDEX promotions_research ON promotions (research_id);

CREATE TABLE catalog_writes (
    id            bigserial PRIMARY KEY,
    promotion_id  bigint NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    table_name    text NOT NULL,
    action        text NOT NULL CHECK (action IN ('insert', 'update')),
    old_row       jsonb,
    new_row       jsonb NOT NULL,
    written_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_writes_promotion ON catalog_writes (promotion_id, id);

CREATE FUNCTION app.log_catalog_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    promotion bigint := nullif(current_setting('sangam.promotion_id', true), '')::bigint;
BEGIN
    IF promotion IS NULL OR (TG_OP = 'UPDATE' AND OLD IS NOT DISTINCT FROM NEW) THEN
        RETURN NULL;
    END IF;
    INSERT INTO catalog_writes (promotion_id, table_name, action, old_row, new_row)
    VALUES (promotion, TG_TABLE_NAME, lower(TG_OP),
            CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END, to_jsonb(NEW));
    RETURN NULL;
END $$;

-- The catalog tables promote() writes. Reference rows it may add on the way (locations, the
-- resolution queue) are left out: undoing a save does not remove a place or a queued name.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['funders', 'funder_csr_years', 'funder_activity', 'funder_locations',
                             'funder_tags', 'programs', 'metrics', 'contacts', 'rfps', 'rfp_locations',
                             'rfp_tags', 'documents', 'orgs', 'org_identifiers', 'org_financials',
                             'org_locations']
    LOOP
        EXECUTE format('CREATE TRIGGER log_catalog_write AFTER INSERT OR UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION app.log_catalog_write()', t);
    END LOOP;
END $$;

-- Staff-only, like entity_research.
ALTER TABLE promotions ENABLE ROW LEVEL SECURITY;
ALTER TABLE catalog_writes ENABLE ROW LEVEL SECURITY;
CREATE POLICY promotions_staff ON promotions FOR SELECT USING ((SELECT app.is_staff()));
CREATE POLICY catalog_writes_staff ON catalog_writes FOR SELECT USING ((SELECT app.is_staff()));
