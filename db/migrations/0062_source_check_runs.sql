-- One row per change check run from the Scout screen or make source-check, so the screen can show the decision.
CREATE TABLE source_check_runs (
    run_id          uuid PRIMARY KEY,
    slug            text NOT NULL,
    -- free: fetch, hash, diff and evidence, no model. full: also the judge and the new-source search.
    depth           text NOT NULL CHECK (depth IN ('free', 'full')),
    decision        text CHECK (decision IN ('nothing to do', 'refresh', 'full pull', 'needs the judge')),
    requested_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    error           text,
    -- The partial update this run saved, waiting in Review & save.
    refresh_row_id  bigint REFERENCES entity_research(id) ON DELETE SET NULL,
    refresh_summary text
);
CREATE INDEX source_check_runs_slug ON source_check_runs (slug, started_at DESC);

-- What the screen shows per source: the paragraphs that changed and each fact's evidence verdict.
-- A free run stops before the judge, so a page whose facts all still hold stays 'differs'.
ALTER TABLE source_checks
    ADD COLUMN removed_text text[] NOT NULL DEFAULT '{}',
    ADD COLUMN added_text   text[] NOT NULL DEFAULT '{}',
    ADD COLUMN evidence     jsonb,
    DROP CONSTRAINT source_checks_status_check,
    ADD CONSTRAINT source_checks_status_check
        CHECK (status IN ('unchanged', 'differs', 'minor', 'changed', 'unverified', 'dead', 'new'));

-- Staff-only, like source_checks.
GRANT SELECT ON source_check_runs TO authenticated;
ALTER TABLE source_check_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_check_runs_read ON source_check_runs FOR SELECT TO authenticated
    USING ((SELECT app.is_staff()));
