-- Import is open to members and stewards: who last saved each research row, so a caller's
-- "Researched recently" lists their own. The row stays shared and staff-only under RLS;
-- non-staff read it through the API, which leaves private findings out.
ALTER TABLE entity_research
    ADD COLUMN researched_by uuid REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX entity_research_researched_by ON entity_research (researched_by);
