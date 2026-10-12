-- Media & Signals (features-plans/signals/2026-10-10-media-signals-design.md, section 3). Replaces news_mentions,
-- dropped at the end. Visibility is written by the pipeline, never computed on read.

CREATE TABLE news_stories (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  headline           text NOT NULL,
  headline_generated boolean NOT NULL DEFAULT false,
  original_headline  text,
  summary            text,
  published_on       date,
  date_source        text CHECK (date_source IN ('post_id', 'publisher', 'text')),
  content_kind       text CHECK (content_kind IN ('news', 'opinion', 'press_release', 'social_post', 'event',
                                                  'background', 'other')),
  is_news            boolean NOT NULL DEFAULT false,
  scope              text CHECK (scope IN ('district', 'state', 'north_east', 'national', 'international')),
  topic              text NOT NULL DEFAULT 'other'
                     CHECK (topic IN ('fcra', 'csr_funding', 'ngo_news', 'programme', 'governance', 'other')),
  feed               text,                         -- set on a topic story: fcra, csr_trends, ngo_north_east
  topic_match        real,
  topic_confidence   real,
  visibility         text CHECK (visibility IN ('listed', 'hidden')),  -- topic stories only
  sentiment          text CHECK (sentiment IN ('positive', 'neutral', 'negative')),
  place_names        text[] NOT NULL DEFAULT '{}', -- named places that matched no locations row
  main_link_id       bigint,
  main_host          text,
  first_seen_at      timestamptz NOT NULL DEFAULT now(),
  last_seen_at       timestamptz NOT NULL DEFAULT now(),
  source_url         text,
  source_name        text,
  fetched_at         timestamptz,
  content_hash       text,
  extractor_version  text,
  search             tsvector GENERATED ALWAYS AS (
                       to_tsvector('simple', coalesce(headline, '') || ' ' || coalesce(summary, '') || ' '
                                   || coalesce(main_host, ''))) STORED
);
CREATE INDEX news_stories_search ON news_stories USING gin (search);
CREATE INDEX news_stories_feed ON news_stories (feed, last_seen_at DESC) WHERE feed IS NOT NULL;

CREATE TABLE news_links (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url            text NOT NULL UNIQUE,
  host           text NOT NULL,
  source_type    text NOT NULL,
  original_title text,
  snippet        text CHECK (length(snippet) <= 1000),
  published_on   date,
  date_source    text CHECK (date_source IN ('post_id', 'publisher', 'text')),
  archive_url    text,
  fetched_at     timestamptz NOT NULL DEFAULT now(),
  source_name       text,                       -- the collector, e.g. tavily_news
  content_hash      text,                       -- of url, title and snippet: changes only when the content does
  extractor_version text,
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  run_id         bigint REFERENCES ingest_runs(id) ON DELETE SET NULL,
  story_id       bigint REFERENCES news_stories(id) ON DELETE SET NULL,
  search         tsvector GENERATED ALWAYS AS (
                   to_tsvector('simple', coalesce(original_title, '') || ' ' || coalesce(snippet, ''))) STORED
);
CREATE INDEX news_links_story ON news_links (story_id);
CREATE INDEX news_links_search ON news_links USING gin (search);
ALTER TABLE news_stories ADD CONSTRAINT news_stories_main_link
  FOREIGN KEY (main_link_id) REFERENCES news_links(id) ON DELETE SET NULL;

-- One row per link classified for one subject at one prompt version: "already seen" means "already scored for this one".
CREATE TABLE news_link_scores (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  link_id        bigint NOT NULL REFERENCES news_links(id) ON DELETE CASCADE,
  org_id         bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id      bigint REFERENCES funders(id) ON DELETE CASCADE,
  feed           text,
  prompt_version text NOT NULL,
  on_target      boolean NOT NULL,
  match          real NOT NULL,
  confidence     real NOT NULL,
  verdict        jsonb NOT NULL,
  classified_at  timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(org_id, funder_id, feed) = 1),
  UNIQUE NULLS NOT DISTINCT (link_id, org_id, funder_id, feed, prompt_version)
);

CREATE TABLE news_story_entities (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  story_id    bigint NOT NULL REFERENCES news_stories(id) ON DELETE CASCADE,
  org_id      bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id   bigint REFERENCES funders(id) ON DELETE CASCADE,
  match       real NOT NULL,
  confidence  real NOT NULL,
  stance      text CHECK (stance IN ('positive', 'neutral', 'negative')),
  signal_type text,
  visibility  text NOT NULL CHECK (visibility IN ('public', 'listed', 'hidden')),
  hidden_by   uuid REFERENCES users(id) ON DELETE SET NULL,
  hidden_at   timestamptz,
  CHECK (num_nonnulls(org_id, funder_id) = 1),
  UNIQUE NULLS NOT DISTINCT (story_id, org_id, funder_id)
);
CREATE INDEX news_story_entities_org ON news_story_entities (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX news_story_entities_funder ON news_story_entities (funder_id) WHERE funder_id IS NOT NULL;

CREATE TABLE news_story_locations (
  story_id    bigint NOT NULL REFERENCES news_stories(id) ON DELETE CASCADE,
  location_id bigint NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  PRIMARY KEY (story_id, location_id)
);

CREATE TABLE news_story_tags (
  story_id bigint NOT NULL REFERENCES news_stories(id) ON DELETE CASCADE,
  tag_id   bigint NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (story_id, tag_id)
);

-- Where each subject's last successful search reached. No row: never searched, so its first run goes back 90 days.
CREATE TABLE news_watch (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  org_id            bigint REFERENCES orgs(id) ON DELETE CASCADE,
  funder_id         bigint REFERENCES funders(id) ON DELETE CASCADE,
  feed              text,
  searched_through  date NOT NULL,
  first_searched_at timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(org_id, funder_id, feed) = 1),
  UNIQUE NULLS NOT DISTINCT (org_id, funder_id, feed)
);

-- A news run is claimed before it runs, so a second execute of the same run is refused rather than repeated.
ALTER TABLE ingest_runs ADD COLUMN claimed_at timestamptz;

-- Reads only; the pipeline writes as the owner, and hiding a match goes through a staff route.
GRANT SELECT ON news_stories, news_links, news_story_entities, news_story_locations, news_story_tags
  TO anon, authenticated;
GRANT SELECT ON news_link_scores, news_watch TO authenticated;
ALTER TABLE news_stories ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_link_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_story_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_story_locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_story_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_watch ENABLE ROW LEVEL SECURITY;

CREATE POLICY news_story_entities_anon ON news_story_entities FOR SELECT TO anon USING (visibility = 'public');
CREATE POLICY news_story_entities_auth ON news_story_entities FOR SELECT TO authenticated
  USING (visibility IN ('public', 'listed') OR (SELECT app.is_staff()));

-- A story reaches a reader through an entity link they may see; signed in, a listed topic story too.
CREATE POLICY news_stories_anon ON news_stories FOR SELECT TO anon
  USING (EXISTS (SELECT 1 FROM news_story_entities e WHERE e.story_id = news_stories.id));
CREATE POLICY news_stories_auth ON news_stories FOR SELECT TO authenticated
  USING (visibility = 'listed' OR (SELECT app.is_staff())
         OR EXISTS (SELECT 1 FROM news_story_entities e WHERE e.story_id = news_stories.id));

CREATE POLICY news_links_read ON news_links FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM news_stories s WHERE s.id = news_links.story_id));
CREATE POLICY news_story_locations_read ON news_story_locations FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM news_stories s WHERE s.id = news_story_locations.story_id));
CREATE POLICY news_story_tags_read ON news_story_tags FOR SELECT TO anon, authenticated
  USING (EXISTS (SELECT 1 FROM news_stories s WHERE s.id = news_story_tags.story_id));

CREATE POLICY news_link_scores_staff ON news_link_scores FOR SELECT TO authenticated USING ((SELECT app.is_staff()));
CREATE POLICY news_watch_staff ON news_watch FOR SELECT TO authenticated USING ((SELECT app.is_staff()));

-- news_mentions held GDELT hits that never linked to an organisation (0 rows on staging, 11 Oct); stories replace it.
DROP TABLE news_mentions;
