-- The Doc Vault (private uploads, requested-but-not-received documents) and the
-- left rail (conversations grouped by use case, shareable with the team).

ALTER TABLE documents
  ADD COLUMN is_public boolean NOT NULL DEFAULT true,   -- vault uploads are inserted false
  ADD COLUMN status text NOT NULL DEFAULT 'read'
    CHECK (status IN ('requested', 'received', 'read', 'scored', 'verified')),
  ADD COLUMN storage_path text,                         -- Supabase Storage key, '<org_id>/<file>'
  ADD COLUMN uploaded_by uuid REFERENCES users(id),
  ADD COLUMN is_ai_generated boolean NOT NULL DEFAULT false,
  ADD COLUMN as_of text,
  ADD COLUMN archive_url text,
  ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX documents_org_idx ON documents (org_id);

ALTER TABLE threads
  ADD COLUMN title text,
  ADD COLUMN use_case text NOT NULL DEFAULT 'ask'
    CHECK (use_case IN ('ask', 'proposal', 'signals', 'rfp_watch')),
  ADD COLUMN org_id bigint REFERENCES orgs(id),
  ADD COLUMN context jsonb NOT NULL DEFAULT '{}'::jsonb,  -- e.g. {"news_mention_id": 12}
  ADD COLUMN visibility text NOT NULL DEFAULT 'private'
    CHECK (visibility IN ('private', 'team', 'team_and_stewards')),
  ADD COLUMN updated_by uuid REFERENCES users(id),
  ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

-- There is nobody to share with until the thread names an org.
ALTER TABLE threads ADD CONSTRAINT threads_shared_needs_org
  CHECK (visibility = 'private' OR org_id IS NOT NULL);

CREATE INDEX threads_rail_idx ON threads (user_id, use_case, updated_at DESC);
CREATE INDEX threads_org_rail_idx ON threads (org_id, use_case, updated_at DESC)
  WHERE visibility <> 'private';
