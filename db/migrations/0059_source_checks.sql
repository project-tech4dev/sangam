-- What make source-check WRITE=1 found: one row per source per run, so a later step can act on it.
CREATE TABLE source_checks (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                uuid NOT NULL,  -- shared by every row of one run
    slug                  text NOT NULL,
    url                   text NOT NULL,
    checked_at            timestamptz NOT NULL DEFAULT now(),
    -- What it was compared with; NULL for a new source.
    baseline_snapshot_id  bigint REFERENCES source_snapshots(id) ON DELETE SET NULL,
    -- Today's version, archived and recorded when its fingerprint differed.
    new_snapshot_id       bigint REFERENCES source_snapshots(id) ON DELETE SET NULL,
    status                text NOT NULL
        CHECK (status IN ('unchanged', 'minor', 'changed', 'unverified', 'dead', 'new')),
    findings_intact       int NOT NULL DEFAULT 0,
    findings_broken       int NOT NULL DEFAULT 0,
    findings_unanchored   int NOT NULL DEFAULT 0,
    judge                 jsonb,  -- the judge's answer; NULL when it was not asked
    detail                text    -- HTTP status, refusal, the stages' reasons, or "archive failed"
);
CREATE INDEX source_checks_slug ON source_checks (slug, checked_at DESC);

-- Staff-only, like source_snapshots.
GRANT SELECT ON source_checks TO authenticated;
ALTER TABLE source_checks ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_checks_read ON source_checks FOR SELECT TO authenticated
    USING ((SELECT app.is_staff()));
