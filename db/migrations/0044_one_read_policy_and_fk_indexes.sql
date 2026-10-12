-- users and org_members each had two permissive SELECT policies, both evaluated per row; fold them into one, and index three FKs the profile and matching joins read.
ALTER POLICY users_read ON users
    USING (id = (SELECT app.user_id()) OR (SELECT app.is_staff()) OR id IN (SELECT app.my_admin_org_member_ids()));
DROP POLICY IF EXISTS users_read_by_admin ON users;

ALTER POLICY org_members_read ON org_members
    USING (user_id = (SELECT app.user_id()) OR (SELECT app.is_staff()) OR org_id IN (SELECT app.my_admin_org_ids()));
DROP POLICY IF EXISTS org_members_read_by_admin ON org_members;

CREATE INDEX IF NOT EXISTS org_tags_tag_idx ON org_tags (tag_id);
CREATE INDEX IF NOT EXISTS funder_tags_tag_idx ON funder_tags (tag_id);
CREATE INDEX IF NOT EXISTS funder_activity_program_idx ON funder_activity (program_id);
