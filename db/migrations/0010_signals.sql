-- Media monitoring becomes reviewable: social items, a vetting step so only
-- vetted items go public, and which weekly batch flagged an RFP match.

ALTER TABLE news_mentions
  ADD COLUMN kind text NOT NULL DEFAULT 'news' CHECK (kind IN ('news', 'press', 'social')),
  ADD COLUMN platform text,                        -- linkedin, x, youtube, ... for social items
  ADD COLUMN summary text,
  ADD COLUMN sentiment text CHECK (sentiment IN ('positive', 'neutral', 'negative')),
  ADD COLUMN review_status text NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending', 'vetted', 'rejected')),
  ADD COLUMN reviewed_by uuid REFERENCES users(id),
  ADD COLUMN reviewed_at timestamptz,
  ADD COLUMN archive_url text;
CREATE INDEX news_mentions_org_idx ON news_mentions (org_id);

ALTER TABLE rfp_matches ADD COLUMN week_of date;
CREATE INDEX rfp_matches_org_idx ON rfp_matches (org_id);
