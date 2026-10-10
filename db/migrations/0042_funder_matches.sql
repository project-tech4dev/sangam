-- Funder Match's saved runs (docs/features/2026-10-10-funder-match-saved-runs.md). Staff, an org's stewards
-- and its admins run and save from the app; members read. Numbered 0042: 0039 to 0041 are on master.

-- 1. Orgs the caller may run a match for: admin and steward. A member reads the result but does not run it.
CREATE FUNCTION app.my_match_org_ids() RETURNS SETOF bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT m.org_id FROM org_members m JOIN users u ON u.id = m.user_id
  WHERE u.auth_user_id = auth.uid() AND m.role IN ('admin', 'steward')
$$;
REVOKE ALL ON FUNCTION app.my_match_org_ids() FROM public;
GRANT EXECUTE ON FUNCTION app.my_match_org_ids() TO anon, authenticated;

-- 2. One row per org × funder per run; a rerun adds rows and never edits old ones.
CREATE TABLE funder_matches (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id         uuid NOT NULL,
  org_id         bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id      bigint NOT NULL REFERENCES funders(id) ON DELETE CASCADE,
  run_at         timestamptz NOT NULL,
  run_by         uuid REFERENCES users(id) ON DELETE SET NULL,  -- NULL: written by make match
  rubric_version text NOT NULL,
  score          smallint CHECK (score BETWEEN 0 AND 100),     -- NULL: checked, nothing to score on
  card           jsonb NOT NULL,
  UNIQUE (run_id, funder_id)
);
CREATE INDEX funder_matches_latest ON funder_matches (org_id, run_at DESC);

CREATE TABLE funder_match_details (
  match_id bigint PRIMARY KEY REFERENCES funder_matches(id) ON DELETE CASCADE,
  detail   jsonb NOT NULL
);

-- 3. Read and insert only: there is no UPDATE or DELETE grant, so a saved run cannot be edited.
GRANT SELECT, INSERT ON funder_matches, funder_match_details TO authenticated;
GRANT USAGE ON SEQUENCE funder_matches_id_seq TO authenticated;
ALTER TABLE funder_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE funder_match_details ENABLE ROW LEVEL SECURITY;

CREATE POLICY funder_matches_read ON funder_matches FOR SELECT TO authenticated
  USING (org_id IN (SELECT app.my_org_ids()) OR (SELECT app.is_staff()));
CREATE POLICY funder_matches_insert ON funder_matches FOR INSERT TO authenticated
  WITH CHECK (
    (org_id IN (SELECT app.my_match_org_ids()) OR (SELECT app.is_staff()))
    AND run_by = (SELECT app.user_id())
  );

-- A detail follows its match: readable when the match is, written only beside a match the caller just wrote.
CREATE POLICY funder_match_details_read ON funder_match_details FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM funder_matches m WHERE m.id = match_id));
CREATE POLICY funder_match_details_insert ON funder_match_details FOR INSERT TO authenticated
  WITH CHECK (EXISTS (SELECT 1 FROM funder_matches m WHERE m.id = match_id AND m.run_by = (SELECT app.user_id())));
