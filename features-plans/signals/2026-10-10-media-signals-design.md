# Media & Signals: news about the cohort, its funders and the sector

Status: proposal for review. No implementation plan yet; that follows sign-off. The prototype is
the Funder Match prototype artifact, version 40 (https://claude.ai/artifact/H1b4nv5ReQn8mvHg2HhPB5),
which carries Media & Signals, the public "In the news" tab, and the list pattern of section 7 on
Funder Match and Proposals. The trial data behind it is the 10 October pull (section 1).

## Why

Organisations in the North East cohort, and the people who support them, need to know three things
without reading the news every day: what is being said about their own organisation, what their
funders are doing, and what is changing in the sector around them (FCRA, CSR money, trouble at other
NGOs in the region). Sangam has a `news_mentions` table, but it holds GDELT hits that are almost never
linked to an entity, has no notion of a story told by several outlets, and assumes a person reviews
every item before it goes public. Nobody can review at that scale.

## 1. What the trial showed

A one-month pull (10 Sep to 10 Oct 2026) over a 29-entity watchlist (the 11 cohort CSOs and 16
funders from org-grant-intelligence, plus Axis Bank Foundation and Tata Trusts) and three topic feeds:

- **Sources.** Google News found almost nothing about the cohort, and namesakes everywhere. Tavily
  web search (`topic: news`, 30 days) reached the North East wires, Indian CSR media and social posts.
  Most of the cohort's own activity is on LinkedIn, Instagram and Facebook.
- **Volume.** 154 searches → 1,847 results → 1,415 unique → 386 kept (relevance ≥ 0.25) → 276 stories
  once copies are grouped; without Facebook, 281 links in 203 stories, 184 of them on target.
- **Classification.** With a per-entity profile naming the namesakes to reject (SATRA is not a
  Vaishnavite satra; KABIL is not Khanij Bidesh India Ltd), Haiku separated namesakes well. A recall
  check found all 5 known stories.
- **Topic feeds.** 56 FCRA items in 30 days (51 negative or restrictive), 33 CSR trend items, 13 items
  of negative NGO news in the North East. Nothing negative about a cohort organisation.
- **Dates.** Tavily gives no date for about 90% of social posts. LinkedIn, Instagram and X carry the
  posting time in the post ID; Facebook does not.
- **Cost.** About $8 for the full sweep: about $5.40 of Haiku and $2.50 of Tavily (section 9).

The trial files are in Downloads (`sangam-signals-trial-2026-10-10.csv`, one row per story, and
`sangam-signals-groups-2026-10-10.csv`, one row per link with its group) with a blank `my_call`
column for marking.

## Decisions

| # | Decision |
|---|---|
| D1 | **Two kinds of feed, and the Registry is the watchlist.** Entity feeds search by name for every Registry organisation and funder that is not hidden; there is no separate list, so anyone added to Sangam is searched for, and every story links to a record with a profile page. Topic feeds search for FCRA, CSR and funding, and NGO news in the North East, by state. |
| D2 | **Tavily is the collector**, for news and for LinkedIn, Instagram and X posts. Social posts are **obtained through Tavily's search index, never from the platforms**: Sangam does not fetch a linkedin.com, instagram.com or x.com page, does not archive one, and stores only what Tavily returns (the post's URL, title and snippet), the summary and headline written from it, and the scores. A post is kept only when it is about a watchlist organisation or funder. **Facebook is left out**: its posts carry no usable date and repeat what organisations post elsewhere. |
| D3 | **One story per event.** Copies of the same story (syndicated news, the same post on several platforms) are grouped under one story with a main link; the rest are listed as "also reported in". The main link is the best source: news before organisation sites before social. |
| D4 | **No manual review.** A story is shown or not by two scores the classifier gives each link to an entity or topic: **match** (is it about this?) and **confidence** (how sure). Staff can hide a wrong match; nothing waits for approval. |
| D5 | **Three bars, set in code** (`config.py`, like the model tiers) and never on a screen: listed for signed-in users at match ≥ 0.6 and confidence ≥ 0.8; public on a Registry profile at match ≥ 0.7 and confidence ≥ 0.9, news and events only; a **negative** story public only at match ≥ 0.9 and confidence ≥ 0.95. A negative story that clears that bar is worth publishing; whether to keep doing so is reviewed once there is real volume. |
| D6 | **Scores show as High, Medium or Low**, never as numbers. Match: High from 0.8, Medium from 0.6. Confidence: High from 0.9, Medium from 0.8. |
| D7 | **Every story is tagged with place, scope and topic**: the states and districts it names (mapped to `locations`), a scope (district, state, North East, national, international), a topic, the five sector domains where they apply, and a sentiment. |
| D8 | **"My area" is a plain rule, not a ranking.** For a signed-in member: stories in their organisations' states, plus FCRA and civil-society news from any North East state, plus national policy news that affects NGOs. National explainers and opinion stay out of it. One click widens to all of the North East, or everywhere. |
| D9 | **Headlines are written for weak titles.** A social post, or any link whose title is just "Instagram", hashtags or a file name, gets a factual headline written from the post. It is marked "Headline written by Sangam" and the original title is kept. |
| D10 | **Dates come from the best source available**, in order: the post ID (LinkedIn, Instagram, X), the publisher's date, the date the text gives. The source is stored. A date equal to the crawl day on a social post is treated as no date. |
| D11 | **Store the summary and headline, not the article text** (pending V, section 10). The link and an archive link are the record. |
| D12 | **List pages share one pattern** (section 7): lean cards with one always selected, one row of dropdown filters, a search box below, a sorted list that loads as you scroll. Media & Signals, Funder Match, Proposals and the Registry list all use the same components. |
| D13 | **Funder type is a fixed list**: Corporate CSR, Private or family foundation, International funder, Government. Whether CSR is spent in-house or through a company foundation is shown on the funder, not filtered on. Delivered with the Funder Match work, not this migration. |

## 2. Pipeline

One run is one `ingest_runs` row (`requested_sources = {news}`), started from Import's existing
"Get the latest CSR news" task or by `make news-pull` (with `ENV` like every DB target). Scheduling is
later work; nothing here needs it.

1. **Search.** For each Registry organisation and funder, queries built from its name and `aliases`,
   with its registered district or state added for a name that is ambiguous on its own, over
   two scopes, the open web and an allowlist of CSR and North East outlets. For each topic feed, its
   queries. Tavily `/search`, `topic: news`, `days` = the window (30 by default; 7 for a weekly run),
   `search_depth: advanced`, `include_raw_content`. Retries and a concurrency limit, as in the trial.
   For a LinkedIn, Instagram or X result, Tavily's title and content are the whole record: the
   pipeline never follows the link, and `archive_url` stays empty for social links.
2. **Drop seen links.** A link already stored is not classified again; it only refreshes `last_seen_at`.
3. **Classify each new link** with `UTILITY_MODEL` (Haiku 4.5), JSON only, against a versioned prompt:
   the entity prompt (the entity's profile and namesakes to reject) or the topic prompt. Through the
   Message Batches API, since nothing waits on it. Fields in section 3.
4. **Fix dates and titles.** Post-ID dates (D10); headlines for weak titles (D9), `UTILITY_MODEL`.
5. **Group into stories.** New links are grouped with each other and with recent stories (the window
   plus 7 days) on the same entity or topic. The trial used `RESEARCH_MODEL` (Sonnet) over one bucket
   at a time; an exact-URL and normalised-title pass runs first so the model only sees real candidates.
6. **Tag places** by matching state and district names against `locations.name` and `aliases`. An
   unmatched name is kept on the story and counted in the run's notes, so the alias list can grow.
7. **Set visibility** from the bars (D5) on every entity link and every topic story.

`media.json` gains a `tavily` source (access rule `licensed_api`, categories news and social) as
the route by which LinkedIn, Instagram and X items arrive. The platforms' own entries keep their rules,
which govern fetching from the platforms directly; the pipeline never does that.

The collector lives in `backend/app/ingest/adapters/` (a `tavily_news.py`), the classifier and
grouping in the ingest pipeline. The entity prompt describes each organisation from its Registry
record; the trial's hand-written notes on namesakes to reject are carried over for the records they
cover. **The same PR switches Import's news task over and retires
the GDELT and India CSR news path**: today `ingest/writer.py` writes their records into
`news_mentions`, so the table cannot go while they still write to it.

## 3. Data model

Staging (read on 10 Oct, read-only) has `news_mentions` with **0 rows**, and 0 `orgs`, so this is a
replacement, not a data move. New tables:

**`news_stories`**: one row per story.

| Column | Notes |
|---|---|
| `id` | |
| `headline`, `headline_generated` | The title shown; true when Sangam wrote it (D9) |
| `summary` | One or two sentences, from the classifier |
| `published_on`, `date_source` | `post_id`, `publisher`, `text`, or null |
| `content_kind` | `news`, `opinion`, `press_release`, `social_post`, `event`, `background`, `other` |
| `is_news` | Reports something that happened at a point in time |
| `scope` | `district`, `state`, `north_east`, `national`, `international` |
| `topic` | `fcra`, `csr_funding`, `ngo_news`, `programme`, `governance`, `other` |
| `topic_match`, `topic_confidence`, `visibility` | For topic stories with no entity: the scores and the resulting `listed` or `hidden` |
| `sentiment` | `positive`, `neutral`, `negative` |
| `place_names` | Names the classifier gave that matched no `locations` row |
| `main_link_id` | The link shown (D3) |
| `first_seen_at`, `last_seen_at` | |
| provenance | `source_url` (the main link), `source_name`, `fetched_at`, `content_hash`, `extractor_version` |
| `main_host` | The main link's outlet, copied here so search can cover it |
| `search` | Generated `tsvector` over headline, summary and `main_host`, for search |

**`news_links`**: every link, grouped under its story. `url` (unique), `host`, `source_type`
(print media, online news, CSR or sector media, organisation site, LinkedIn, Instagram, X, YouTube,
other web), `original_title`, `published_on`, `date_source`, `archive_url`, `fetched_at`,
`run_id`, `story_id`.

**`news_story_entities`**: a story's link to an organisation or a funder. `story_id`, exactly one of
`org_id` or `funder_id`, `match`, `confidence`, `stance` (toward that entity), `signal_type`,
`visibility` (`public`, `listed`, `hidden`), `hidden_by`, `hidden_at`. A story can name several
entities, each with its own scores.

**`news_story_locations`** (`story_id`, `location_id`) and **`news_story_tags`** (`story_id`,
`tag_id`, the five domains).

**Visibility is written, not computed on read.** The pipeline writes it from the bars, and
`make news-visibility` rewrites it when a bar changes. That keeps the database rules simple:

- Signed out: a story and its links only through a `public` entity link, and only on that entity's
  profile.
- Signed in: every `listed` or `public` row.
- Staff: everything, including `hidden`, and they alone can hide.

**What changes elsewhere.** Every reader and writer of `news_mentions` moves in the same PR as the
drop, because `verify_against_db()` raises at boot when the catalog names a missing table:

- Backend: `api/routes/news.py`, `schemas/news.py` (`NewsOut`, and the `news_mentions` count in the
  stats schema), `repositories/news.py` (`list_news`, and the `news_mentions` count in `stats()`,
  which the home page uses), `ingest/writer.py` and `ingest/runner.py` (the news write and the
  before/after count).
- The SQL catalog entry, its defect lines and the `_ROLE_ALIASES` entry in `catalog.py`; the tests
  that pin them (`test_sql_catalog.py`, `test_sql_render.py`) and the eval case
  `kabil-news-declines-when-unlinked` in `tests/evals/cases/golden.jsonl`, which becomes a case that
  answers.
- Frontend: `NewsRow` in `lib/api/types.ts`, the two Registry pages that fetch `/api/news?org=` and
  `?funder=`, `ProfileTabs.tsx`, the "News signals" count in `EvidenceRail.tsx`, and `MediaView.tsx`.
- Seed: `seed_news` and the GDELT CSVs it reads.
- The `public_rows` list in the RLS migration is history; the new tables get their own policies.
- The new tables join the catalog (a security decision, per CLAUDE.md), with defect lines where
  the data warrants them, for example "topic stories have no entity; a zero for an org does not
  mean nothing was said about its area".
- The citation marker for the agent is `[news:N]`, the story id.
- The migration number comes after `0038_research_saved` (staging is at 0034).

## 4. Who sees what

| Viewer | Media & Signals page | Registry profile, "In the news" |
|---|---|---|
| Signed out | No access (sign-in prompt) | Public links only, newest first |
| Member or admin of an organisation | My organisations (their own), Funders, General with "My area" on | Public links, plus "Below the public bar" for listed ones |
| Steward | My organisations (all they steward), Funders, General with their states | As a member |
| Staff | Every cohort organisation, Funders, General on "Everywhere"; can hide a wrong match | As a member, plus hidden ones marked |
| Signed in, no organisation | Funders and General; My organisations explains how to be added | As a member |

"My organisations" comes from `org_members`; "my area" from `org_locations` of those organisations.
Both are empty on staging today, so the first real test needs cohort data loaded.

## 5. API

Three routes, in the usual router, repository and schema set:

- `GET /api/news` (signed in): `bucket` (`org`, `funder`, `general`), `org`, `funder`, `area`
  (`mine`, `north_east`, `all`), `topic`, `sentiment`, `source` (`news`, `social`, `web`),
  `since` (`30d`, `all`), `q`, `cursor`, `limit` (default 20). Returns the page, `next_cursor`, and
  the three bucket counts under the same filters.
- `GET /api/orgs/{slug}/news` and `GET /api/funders/{slug}/news` (public): that entity's stories,
  newest first, cursor-paged. Public links only when signed out.
- `POST /api/news/{story_id}/hide` (staff): hides one entity link (`org` or `funder` in the body).

**Order and paging.** The list is ordered by match, then confidence, then date, then id, and paged
by keyset: the cursor carries the last row's four values, so the next page is "after this one". That
stays fast at any depth and neither skips nor repeats rows when new stories arrive mid-scroll.
Counts are one grouped `count` per bucket, run beside the first page; past 500 a card shows "500+".
Search is Postgres full-text on `news_stories.search` (GIN index). The current `PageParams`
(limit and offset) stays for the routes that use it.

## 6. Screens

**Media & Signals** (the Ask workspace's existing sidebar item; replaces `MediaView.tsx`):

1. Three lean cards: My organisations, Funders, General, each with its count under the current
   filters. One is always selected, shown dark sage with white text.
2. One row of dropdowns: Area and Topic on General, the organisation or funder picker on the other
   two, then Sentiment, Source, When. A dropdown is white at its default and dark sage with white
   text when moved off it. No counts in the options.
3. The search box, full width.
4. The list: 10 cards, more as you scroll, with a "Show more" button for keyboards and an end marker.
5. Each card: the organisation or funder chip (opens its profile) or the topic tag; sentiment;
   "Background" for non-news; on General, why it is in your area ("Assam", "Meghalaya · North East
   civil society", "National policy"); the headline linking to the main source; outlet, source type,
   date, state; "Headline written by Sangam" where it applies; the summary; "Also reported in N more"
   with every copy; Match and Confidence as High, Medium or Low; staff's "Hide: wrong match".

**Registry profile, "In the news"**: the existing `SectionCard` in `ProfileTabs.tsx`, fed from
`/api/orgs/{slug}/news` and `/api/funders/{slug}/news`, grouped by month, newest first. Signed in, a
second block lists the stories below the public bar. The note says only confident matches appear.

## 7. One pattern for list pages

Media & Signals, Funder Match, Proposals and the Registry list are the same kind of page, and the
prototype shows all of them in one form. The components:

| Component (`frontend/components/ui/`) | Does |
|---|---|
| `BucketCards` | Two to four lean cards; one always selected (dark sage, white text); counts follow the filters |
| `FilterRow` | Equal columns of dropdowns in one row, two columns on a phone; white at default, dark sage when changed |
| `SearchBox` | Full width, under the filters |
| `InfiniteList` and `useCursorList` | A page at a time, the next one loading near the end; a "Show more" button and an end marker |

The backend side is one helper in `backend/app/repositories/` for keyset cursors and filtered counts.

How each page uses them:

- **Media & Signals**: as section 6.
- **Funder Match**: cards All fits, Strong (75+), Medium (55–74); dropdowns Funder type (D13) and
  Proposal (has one or not yet); search over names and reasons; sorted by fit score. "Proposals
  started" stops being a card; Proposals is in the sidebar, and a funder card's "Proposals (N)" opens
  it filtered to that funder. The weak or no-fit list stays folded under All fits.
- **Proposals**: cards All, In progress, Ready; dropdowns Funder, Organisation (only when the viewer
  has more than one), Started; search over titles; newest first.
- **Registry**: its place pills become a dropdown in the same row.

**Design system first.** Two looks are new: the selected card (dark sage fill, white text) and the
changed dropdown (dark sage, white text and arrow). Both use existing colours (`--g700`, `--g200`,
`--g800`, white) and go into "Sangam Design System v2" before any component code, as the design
system rule in CLAUDE.md requires. CLAUDE.md gains a rule that list pages use these components.

## 8. Testing

- **Unit** (no database, as usual): the bars and visibility rule, including the stricter negative bar;
  the area rule (own state, North East civil society, national policy news, national explainers out);
  post-ID date decoding against known posts; cursor encoding and the order; weak-title detection.
- **Integration**: the migration on a fresh database; RLS for signed out, member, staff (a signed-out
  read of a `listed` story returns nothing); search; counts equal the list length under every filter.
- **Classifier eval** (the `eval` tier, costs money): the trial CSV with `my_call` filled in becomes a
  golden set, moved from a local Downloads folder into the repo beside `tests/evals/`; namesake rejection and the topic prompt are scored against it, and a prompt or model
  change must not drop below the trial's results. The recall stories stay in it.
- **Frontend**: the list components under the existing lint and build; the prototype's click-through
  (every role, every filter, counts equal to the list) is the acceptance check.

## 9. Cost

Per sweep at the trial's size (29 organisations and funders, 3 topic feeds, 154 searches): about $2.50 of Tavily
(advanced search, 2 credits each at $0.008) and about $5.40 of Haiku, plus under $0.50 for grouping
and headlines. The Batch API halves the Haiku part, and prompt caching of the system prompt and
profiles cuts it further, so about $5 a sweep. Cost follows the number of searches, so it grows with the
Registry (roughly 2 to 4 searches per record per run); running weekly with a 7-day window does not
much change it.

## 10. Open questions

For V, before storing anything (the brief asks for this):

1. **Storing summaries and headlines, not article text** (D11). Is a one-to-two sentence summary,
   written by the classifier, acceptable to store and show publicly with the link?

For the team:

2. **The classifier model.** Haiku 4.5 is the default. A cheaper model can replace it only after it
   matches Haiku on the eval set (section 8); namesakes are where cheap models fail.
3. **Topic stories that name a Registry organisation or funder.** The topic prompt already records
   which of them a story mentions (the trial found Rajiv Gandhi Foundation in two FCRA-cancellation stories,
   from March 2024). Should such a story also get an entity link, scored by the entity prompt, so it
   can reach that entity's profile and its members' list?

Settled since the first draft: social posts come through Tavily as in D2; negative stories that clear
D5's bar are published, to be reviewed later; the Registry is the watchlist (D1). Staging has no
organisations yet, so the first real run needs the cohort loaded.

## Out of scope

How the search scales as the Registry grows (how often each record is searched, and namesake notes
for records that lack them), push alerts and a weekly digest (by email or WhatsApp), a ranked "For you" list, Facebook, scheduled
runs, storing article text, and the Funder Match and Proposals screens themselves (section 7 only
fixes how their lists look and filter).
