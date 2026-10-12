# Media & Signals: news about the cohort, its funders and the sector

Status: proposal for review. No implementation plan yet; that follows sign-off. The build is one
end-to-end change (section 11): the pipeline, the Media & Signals page, the Registry "In the news" tab
and Import's news task, with no old news path left behind. The prototype is
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
| D5 | **Three bars, set in code** (`config.py`, like the model tiers) and never on a screen: listed for signed-in users at match ≥ 0.6 and confidence ≥ 0.8; public on a Registry profile at match ≥ 0.7 and confidence ≥ 0.9, news and events only; a **negative** story public only at match ≥ 0.9 and confidence ≥ 0.95. A **topic story** (General) is listed only at match ≥ 0.75: it has no organisation to vouch for it, and the trial's 0.6–0.7 topic verdicts were mostly off-topic (arrests, agitation, flood reviews). A negative story that clears that bar is worth publishing; whether to keep doing so is reviewed once there is real volume. |
| D6 | **Scores show as High, Medium or Low**, never as numbers. Match: High from 0.8, Medium from 0.6. Confidence: High from 0.9, Medium from 0.8. |
| D7 | **Every story is tagged with place, scope and topic**: the states and districts it names (mapped to `locations`), a scope (district, state, North East, national, international), a topic, the five sector domains where they apply, and a sentiment. |
| D8 | **"My area" is a plain rule, not a ranking.** For a signed-in member: stories in their organisations' states, plus FCRA and civil-society news from any North East state, plus national policy news that affects NGOs. National explainers and opinion stay out of it. One click widens to all of the North East, or everywhere. |
| D9 | **Headlines are written for weak titles.** A social post, or any link whose title is just "Instagram", hashtags or a file name, gets a factual headline written from the post. It is marked "Headline written by Sangam" and the original title is kept. |
| D10 | **Dates come from the best source available**, in order: the post ID (LinkedIn, Instagram, X), the publisher's date, the date the text gives. The source is stored. A date equal to the crawl day on a social post is treated as no date. |
| D11 | **Store summaries, never article text.** A story keeps its headline and a one-to-two sentence summary written by the classifier; the link and an archive link (news only) are the record. Article text is read during classification and discarded. Each link also keeps Tavily's own search snippet (the few sentences its index returns, capped at 1,000 characters), so a link can be scored for an organisation that joins later without fetching it again. |
| D12 | **List pages share one pattern** (section 7): lean cards with one always selected, one row of dropdown filters, a search box below, a sorted list that loads as you scroll. Media & Signals, Funder Match, Proposals and the Registry list all use the same components. |
| D13 | **Funder type is a fixed list**: Corporate CSR, Private or family foundation, International funder, Government. Whether CSR is spent in-house or through a company foundation is shown on the funder, not filtered on. Delivered with the Funder Match work, not this migration. |
| D14 | **A topic story that names a Registry organisation or funder is linked to it.** The topic prompt lists the Registry names a story mentions; each one is then scored by the entity prompt and gets its own entity link, so the story reaches that organisation's "In the news" tab and its members' list under the same bars as any other link. |
| D15 | **Repeat pulls are incremental, and every newcomer starts 90 days back.** Each organisation and funder is searched from where its last search ended; the first time it is searched, whenever it joined the Registry, the search goes back **90 days**. A link is scored once per organisation (per prompt version), so a link stored before an organisation joined is checked for it when it does, and a repeated link is never scored twice for the same one (section 2a). |
| D16 | **A pull starts from Scout, staff only, through the existing approval card.** "Get the latest news" fills the composer with "Get the latest news for everyone in Sangam", which staff may edit to names; the supervisor calls `run_import_now(sources="tavily_news", funders=<names or empty>)`, and the approval card shows the plan line before anything runs (section 2b). GDELT and India CSR are **parked**: their code and registry entries stay, nothing calls them. |

## 2. Pipeline

One run is one `ingest_runs` row (`requested_sources = {news}`), started from Import's existing
"Get the latest CSR news" task or by `make news-pull` (with `ENV` like every DB target). Scheduling is
later work; nothing here needs it.

1. **Search.** For each Registry organisation and funder, queries built from its name and `aliases`,
   with its registered district or state added for a name that is ambiguous on its own, over
   two scopes, the open web and an allowlist of CSR and North East outlets. For each topic feed, its
   queries. Tavily `/search`, `topic: news`, `days` = each record's own window (D15: from its
   `searched_through` date, or 90 days for a record never searched), `search_depth: advanced`,
   `include_raw_content`. Retries and a concurrency limit, as in the trial.
   For a LinkedIn, Instagram or X result, Tavily's title and content are the whole record: the
   pipeline never follows the link, and `archive_url` stays empty for social links.
2. **Drop seen pairs.** A link already scored for this organisation or funder, at the current prompt
   version, is not classified again; it only refreshes `last_seen_at`. A stored link that was never
   scored for this one is classified as new (section 2a).
3. **Classify each new link** with `UTILITY_MODEL` (Haiku 4.5), JSON only, against a versioned prompt:
   the entity prompt (the entity's profile and namesakes to reject) or the topic prompt. Through the
   Message Batches API, since nothing waits on it. Fields in section 3.
   A topic link that names Registry organisations or funders is then scored by the entity prompt
   for each of them (D14); each one that clears the listing bar gets an entity link.
4. **Fix dates and titles.** Post-ID dates (D10); headlines for weak titles (D9), `UTILITY_MODEL`.
5. **Group into stories.** New links are grouped with each other and with recent stories (the window
   plus 7 days) on the same entity or topic. The trial used `RESEARCH_MODEL` (Sonnet) over one bucket
   at a time; an exact-URL and normalised-title pass runs first so the model only sees real candidates.
6. **Tag places** by matching state and district names against `locations.name` and `aliases`. An
   unmatched name is kept on the story and counted in the run's notes, so the alias list can grow.
7. **Set visibility** from the bars (D5) on every entity link and every topic story.

### 2a. Repeat pulls and organisations that join later

Pulls keep happening as the Registry grows. Day one runs with organisations A and B; a later run has
A, B, C and D. The rule (D15):

- **Each record has a watermark.** `news_watch.searched_through` holds the date its last successful
  search covered. A run searches each record from that date to today, so A and B are searched only
  for what is new since their last run.
- **A newcomer starts 90 days back.** A record with no `news_watch` row, whenever it was added, is
  searched over the last 90 days on its first run. The row is written once its searches succeed, so
  a run that fails part-way catches up next time and nothing is skipped.
- **Stored links are checked for the newcomer.** Before searching the web for C, the run searches the
  links Sangam already holds (full-text over `original_title`, `snippet` and the story summary) for
  C's name and aliases, and classifies only those hits for C. A North East story pulled on day one that
  named C, before C was in the Registry, reaches C's "In the news" tab. Topic stories are included
  (D14).
- **A link is scored per organisation, not once.** `news_link_scores` records each (link, organisation
  or funder, prompt version) pair that was classified. A repeated link costs nothing for the
  organisations it was already scored for; a new organisation or a new prompt version scores only the
  missing pairs.
- **Stories still group across runs.** New links join recent stories (step 5), so a copy found today
  of yesterday's story lands under "also reported in", not as a second card.
- **A run can be limited to chosen organisations.** `ingest_runs.subjects` names them (Import's task,
  or `make news-pull ORG=<slug>`); the default is the whole Registry. Watermarks make the two kinds
  of run combine: a limited run advances only its subjects' watermarks.
- **Topic feeds keep watermarks too**, one `news_watch` row per feed, starting 90 days back like an
  organisation.

`media.json` gains a `tavily` source (access rule `licensed_api`, categories news and social) as
the route by which LinkedIn, Instagram and X items arrive. The platforms' own entries keep their rules,
which govern fetching from the platforms directly; the pipeline never does that.

The collector lives in `backend/app/ingest/adapters/` (a `tavily_news.py`), the classifier and
grouping in the ingest pipeline. The entity prompt describes each organisation from its Registry
record; the trial's hand-written notes on namesakes to reject are carried over for the records they
cover.

**GDELT and India CSR are parked, not deleted (D16).** Their adapters, extractors and source registry
entries stay in the repo, but they come out of `runner.ADAPTERS`, so no run, task or agent tool calls
them, and `list_import_sources` shows them as parked. Two consequences, written down so a revival
starts from the right place:

- GDELT wrote `news_mentions`, which this change drops. Reviving it means pointing its adapter at
  `news_links` through the section 2 pipeline (classification, grouping, visibility), not at a table.
- India CSR turned articles into `funders` and `funder_csr_years` rows, and so created funders from
  headlines (the "Global Capability Centres" row was one, deleted from staging on 11 Oct). If it
  returns it must only update funders already in the Registry, never create one. CSR figures meanwhile
  come from Import's funder research, which can read indiacsr.in like any other site.

### 2b. Starting a pull from Import

Import's third task card becomes **"Get the latest news"**: staff only (`tasksFor`), the same Scout
flow as the other tasks (D16). It replaces "Run an import from India CSR, 10 articles". The prototype
is version 41 (https://claude.ai/artifact/PiiVTnYXsDfAYYsk4b9sSM), approved as its third version.

- **The composer says whose news.** The card fills it with "Get the latest news for everyone in
  Sangam": every Registry organisation and funder that is not hidden, plus the topic feeds (FCRA,
  CSR trends, North East NGO news). Staff may edit it to names ("…for KABIL, SBI Foundation"); named
  records get only their own news, and only names already in the Registry count.
- **No window, no count, no feed choice.** Each record's window comes from its watermark (D15);
  cost follows searches, not results; the feeds follow from the choice of everyone.
- **The approval card is the check.** The supervisor calls `run_import_now` straight away; the
  existing card reads "Pull the latest news?", with one plan line from the plan route ("News for
  everyone in Sangam (17 organisations and funders), plus FCRA and North East sector news · about 116
  searches · about $6.50", or "No Registry record for: X") and the buttons "Pull the news" / "Don't
  pull". The run appears in Import's runs list like any other import, and the Media & Signals header
  reads "Last pull …" from the latest finished news run.
- **No sources card.** `choose_sources` decides what a researcher may read; a news run reads only
  Tavily under D2.

`make news-pull [ORG=<slug>] [ENV=…]` and the supervisor's `run_import_now` call the same code as the
route, so there is one way a pull runs. The task's prompt (`composePrompt`'s news branch and the
`NewsSource` type) goes, and `instructions.md` stops offering "Run an import from India CSR".

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
other web), `original_title`, `snippet` (Tavily's search snippet, at most 1,000 characters; D11),
`published_on`, `date_source`, `archive_url`, `fetched_at`, `run_id`, `story_id`, and a generated
`search` `tsvector` over title and snippet, for the look-back in section 2a.

**`news_link_scores`**: one row per link classified for one organisation, funder or topic feed:
`link_id`, exactly one of `org_id`, `funder_id` or `feed`, `prompt_version`, `match`, `confidence`,
`classified_at`. Unique on (link, subject, prompt version). It is what makes "already seen" mean
"already scored for this one" (section 2a); the entity links below are written from it.

**`news_watch`**: one row per organisation, funder or topic feed that has been searched: exactly one
of `org_id`, `funder_id` or `feed`, `searched_through` (date), `first_searched_at`. No row means the
record has never been searched, so its first run goes back 90 days (D15).

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
- The migration number is the next free one after the latest on master (`0041_catalog_writes` on 10 Oct; staging was at 0034).

## 4. Who sees what

| Viewer | Media & Signals page | Registry profile, "In the news" |
|---|---|---|
| Signed out | No access (sign-in prompt) | Public links only, newest first |
| Member or admin of an organisation | My organisations (their own), Funders, General with "My area" on | Public links only, as signed out |
| Steward | My organisations (all they steward), Funders, General with their states | Public links only, as signed out |
| Staff | Every cohort organisation, Funders, General on "Everywhere"; can hide a wrong match | Public links only, as signed out |
| Signed in, no organisation | Funders and General; My organisations explains how to be added | Public links only, as signed out |

"My organisations" comes from `org_members`; "my area" from `org_locations` of those organisations.
`org_locations` has rows on staging (11 Oct); `org_members` may still be empty, so a member's view needs people added first.

A Registry profile reads the same for everyone, signed in or out: only stories that clear the public bar.
Background items (not news) and hidden ones (below the bar, or marked a wrong match) reach no list
and no profile, staff's included; they stay stored for the agent and for re-scoring.

## 5. API

Three routes, in the usual router, repository and schema set:

- `GET /api/news/stories` (signed in): `bucket` (`org`, `funder`, `general`), `org`, `funder`, `area`
  (`mine`, `north_east`, `all`), `topic`, `sentiment`, `source` (`news`, `social`, `web`),
  `since` (`30d`, `all`), `q`, `cursor`, `limit` (default 20). Returns the page, `next_cursor`, and
  the three bucket counts under the same filters.
- `GET /api/orgs/{slug}/news` and `GET /api/funders/{slug}/news` (public): that entity's stories,
  newest first, cursor-paged. Public links only when signed out.
- `POST /api/news/stories/{story_id}/hide` (staff): hides one entity link (`org` or `funder` in the body).

Starting a pull (section 2b), staff only:

- `GET /api/ingest/news-runs/plan?names=` (comma-separated; none means everyone): read-only. Returns
  the records, how many go back 90 days, the searches, a cost estimate, and which names matched the
  Registry and which did not. The run itself starts through Scout's `run_import_now`, which writes one
  `ingest_runs` row and runs it to the end inside the turn; `make news-pull` does the same from a shell.

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
   on General, why it is in your area ("Assam", "Meghalaya · North East
   civil society", "National policy"); the headline linking to the main source; outlet, source type,
   date, state; "Headline written by Sangam" where it applies; the summary; "Also reported in N more"
   with every copy; Match and Confidence as High, Medium or Low; staff's "Hide: wrong match".

**Registry profile, "In the news"**: the existing `SectionCard` in `ProfileTabs.tsx`, fed from
`/api/orgs/{slug}/news` and `/api/funders/{slug}/news`, grouped by month, newest first. Public stories only, the same signed in or out; the rest are in Media & Signals.
The note says only confident matches appear.

## 7. One pattern for list pages

Media & Signals, Funder Match, Proposals and the Registry list are the same kind of page, and the
prototype shows all of them in one form.

**Already built (#151, on master):** `frontend/components/ui/ListPage.tsx` holds `BucketCards`,
`FilterRow`, `SearchBox` and `useShowMore` / `ListMore`, with the design-system looks below, and
Funder Match (`FunderMatchView.tsx`) and Proposals (`ProposalList.tsx`) use them. Media & Signals
reuses the three as they are.

**New with this work:** `useShowMore` pages through a list already in the browser, which suits a
few dozen funders but not thousands of stories. Media & Signals adds `useCursorList` beside it in
`ListPage.tsx`: it fetches the next page from the server near the end of the list (keyset cursor,
section 5), with the same `ListMore` button and end marker. The backend side is one helper in
`backend/app/repositories/` for keyset cursors and filtered counts.

Both are built as general list tools, not news-specific ones, because **Funder Match will need them
too.** Today it loads an organisation's whole latest run in one request and filters, counts and
searches in the browser, which is fine at a few hundred funders. When a run passes about **500
funders**, Funder Match moves to the same server paging (cursor on score, then funder; counts and
search in SQL) and a run saves only the funders it scored, with a count of the rest. Not part of this
build.

How each page uses them:

- **Media & Signals**: as section 6.
- **Funder Match**: cards All fits, Strong (75+), Medium (55–74); dropdowns Funder type (D13) and
  Proposal (has one or not yet); search over names and reasons; sorted by fit score. "Proposals
  started" stops being a card; Proposals is in the sidebar, and a funder card's "Proposals (N)" opens
  it filtered to that funder. The weak or no-fit list stays folded under All fits.
- **Proposals**: cards All, In progress, Ready; dropdowns Funder, Organisation (only when the viewer
  has more than one), Started; search over titles; newest first.
- **Registry**: its place pills become a dropdown in the same row.

**Design system.** The selected card and the changed dropdown went into "Sangam Design System v2"
with #151, and CLAUDE.md already says list pages use these components. Media & Signals' story card
and Scout's news approval card are new screens, so they go into the design system's UI kit in the same PR,
as CLAUDE.md requires.

## 8. Testing

- **Unit** (no database, as usual): the bars and visibility rule, including the stricter negative bar;
  the area rule (own state, North East civil society, national policy news, national explainers out);
  post-ID date decoding against known posts; cursor encoding and the order; weak-title detection;
  each record's search window (90 days with no `news_watch` row, otherwise from `searched_through`).
- **Integration**: the migration on a fresh database; RLS for signed out, member, staff (a signed-out
  read of a `listed` story returns nothing); search; counts equal the list length under every filter.
  Repeat pulls: run for A and B, then for A to D with the same links returned. The second run
  classifies nothing new for A and B, scores the stored links that name C or D for them, starts C and
  D at 90 days, and creates no second story for a copy. A run that fails part-way leaves the
  watermark where it was.
- **Classifier eval** (the `eval` tier, costs money): the trial CSV with `my_call` filled in becomes a
  golden set, moved from a local Downloads folder into the repo beside `tests/evals/`; namesake rejection and the topic prompt are scored against it, and a prompt or model
  change must not drop below the trial's results. The recall stories stay in it.
- **Import's news task**: unit tests for the plan's arithmetic (records, windows, searches, cost) and
  the selection rules (everyone brings the topic feeds; named records do not; names that match nothing
  are reported, never read as everyone); integration that the plan route writes nothing, a chat pull
  writes one `ingest_runs` row with its subjects, a non-staff caller gets 403, and nothing calls a parked adapter.
- **Frontend**: the list components under the existing lint and build; the prototype's click-through
  (every role, every filter, counts equal to the list, and Scout's news card and approval) is the acceptance
  check.

## 9. Cost

Per sweep at the trial's size (29 organisations and funders, 3 topic feeds, 154 searches): about $2.50 of Tavily
(advanced search, 2 credits each at $0.008) and about $5.40 of Haiku, plus under $0.50 for grouping
and headlines. The Batch API halves the Haiku part, and prompt caching of the system prompt and
profiles cuts it further, so about $5 a sweep. Cost follows the number of searches, so it grows with the
Registry (roughly 2 to 4 searches per record per run); running weekly with a 7-day window does not
much change it. A newcomer's first run costs about the same searches with a 90-day window, plus a
classification for each stored link that names it; later runs only classify what is new.

## 10. Open questions

For the team:

1. **The classifier model.** Haiku 4.5 is the default. A cheaper model can replace it only after it
   matches Haiku on the eval set (section 8); namesakes are where cheap models fail.

Settled since the first draft: social posts come through Tavily (D2); negative stories that clear D5's
bar are published, to be reviewed later; the Registry is the watchlist (D1); summaries are stored,
never article text (D11); a topic story that names a Registry organisation or funder is linked to it
(D14); repeat pulls are incremental and a newcomer starts 90 days back (D15); a pull starts from Scout through the approval card, staff only, with GDELT and India CSR parked (D16). Staging held 8 organisations and 5 funders on 11 Oct, so a first real run is possible.

## 11. What the build covers, end to end

One change, so no old news path is left anywhere:

| Area | Change |
|---|---|
| Data | New tables (section 3); `news_mentions` dropped, with every reader and writer moved in the same PR |
| Pipeline | `tavily_news` adapter, classification, grouping, places, visibility (section 2); repeat pulls and newcomers (2a) |
| Import | "Get the latest news" in Scout, its approval card and the plan route (2b, section 5); GDELT and India CSR parked; the news prompt and `NewsSource` removed; `instructions.md` and `list_import_sources` updated; news runs in the runs list |
| Media & Signals page | `MediaView.tsx` replaced by the section 6 page on the shared list components, plus `useCursorList` (section 7) |
| Registry | "In the news" on organisation and funder profiles (section 6) |
| Agent | The new tables in the SQL catalog with their defect lines; `[news:N]` citations |
| Design system | The story card and the news approval card in the UI kit |
| Prototype | Version 41 adds Scout's news card and approval, signed off before code (mock before build) |

## Out of scope

How often each record is searched as the Registry grows (a schedule per record; section 2a only
says from where), namesake notes for records that lack them, push alerts and a weekly digest (by email or WhatsApp), a ranked "For you" list, Facebook, scheduled
runs, storing article text, and the Funder Match and Proposals screens themselves (section 7 only
fixes how their lists look and filter).
