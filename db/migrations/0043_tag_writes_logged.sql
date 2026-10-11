-- Import now writes org_tags and program_tags, so a save's tags are logged like its other rows and undone with it.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['org_tags', 'program_tags']
    LOOP
        EXECUTE format('CREATE TRIGGER log_catalog_write AFTER INSERT OR UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION app.log_catalog_write()', t);
    END LOOP;
END $$;
