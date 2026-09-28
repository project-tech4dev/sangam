-- Identity and membership: the link to Supabase Auth, the staff flag, and which
-- users belong to which org. Every private-read policy will resolve through these.

ALTER TABLE users
  ADD COLUMN auth_user_id uuid UNIQUE,             -- auth.users(id); no FK, the local container has no auth schema
  ADD COLUMN is_staff boolean NOT NULL DEFAULT false;

ALTER TABLE orgs ADD COLUMN registry_status text NOT NULL DEFAULT 'in_vetting'
  CHECK (registry_status IN ('placeholder', 'in_vetting', 'full_profile', 'hidden'));
ALTER TABLE funders ADD COLUMN registry_status text NOT NULL DEFAULT 'in_vetting'
  CHECK (registry_status IN ('placeholder', 'in_vetting', 'full_profile', 'hidden'));

-- A steward (an ecosystem player such as Node) reads an org's private data and
-- cannot write; deleting the row removes the access.
CREATE TABLE org_members (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  org_id bigint NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member', 'steward')),
  added_by uuid REFERENCES users(id),
  added_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, org_id)
);
CREATE INDEX org_members_org_idx ON org_members (org_id);

-- The local dev user is staff, so it keeps seeing everything once RLS lands.
UPDATE users SET is_staff = true WHERE id = '00000000-0000-0000-0000-000000000001';
