-- Every distinct version of a page or report Scout has read, so a later check can tell whether it changed.
-- Written by the fetching tools; re-reading an unchanged source bumps last_seen_at instead of adding a row.
CREATE TABLE source_snapshots (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url            text NOT NULL,
    kind           text CHECK (kind IN ('page', 'document')),
    -- sha256 of the normalised text; named apart from documents.content_hash, which hashes bytes.
    text_hash      text NOT NULL,
    -- NULL when Storage was off or the upload failed.
    archive_key    text,
    first_seen_at  timestamptz NOT NULL DEFAULT now(),
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (url, text_hash)
);

-- moved() finds a promoted file's rows by archive_key.
CREATE INDEX source_snapshots_archive_key_idx ON source_snapshots (archive_key);

-- The versions a research run read; save_research writes it.
ALTER TABLE entity_research ADD COLUMN snapshot_ids bigint[];

-- Staff-only, like entity_research.
GRANT SELECT ON source_snapshots TO authenticated;
ALTER TABLE source_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_snapshots_read ON source_snapshots FOR SELECT TO authenticated
    USING ((SELECT app.is_staff()));
