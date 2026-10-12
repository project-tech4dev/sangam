---
name: news-brief
description: Use when the user asks what has changed, or what is in the news, for one organisation or funder — "what's new with KABIL?", "any news on SBI Foundation this month?", "has anything happened to Goonj lately?". Reads Sangam's Media & Signals stories for that record and writes a short brief, each line cited [news:N], naming the primary source behind any negative or regulatory story. Not for funder fit (funder-matching) or for news about a whole topic with no organisation named.
---

# What changed for one organisation or funder

## 1. Resolve the record

Find it by name in `orgs` or `funders`, aliases included. If the name could
mean two records, ask which. A company and its foundation are different
funders.

## 2. Read its stories

One `db_query`: `news_story_entities` joined to `news_stories` on `story_id`,
for that `org_id` or `funder_id`, with:

- `news_story_entities.visibility = 'public'`: the stories Sangam shows on the
  Registry profile. Lower-confidence matches stay on Media & Signals; say so
  in one line if the user wants more.
- `news_stories.is_news`, and `published_on` within the last 30 days unless
  the user gives another window.
- Newest first. Take `id`, `headline`, `summary`, `published_on`,
  `main_host`, `topic`, `content_kind`, and the entity row's `stance`,
  `match` and `confidence`.

## 3. When nothing comes back

Zero stories means nothing in Sangam's pulls, not that nothing happened. Get
the latest `max(fetched_at)` from `news_links` and say: "Nothing on <name> in
Sangam's news since <date>." Never say "no news".

## 4. Find the primary source, sparingly

For a story with `stance = 'negative'`, or `topic` of `fcra` or `governance`,
`fetch_url` its main link once (`news_links.url` where `id = main_link_id`)
to see what the article rests on: an MHA order, a court ruling, an MCA
filing, a company's own statement. Name it in words beside the line ("the
article cites an MHA order of 3 October"). At most two fetches per brief.
Web text carries no marker, so never present it as a database fact.

## 5. Write the brief

- Three to five lines, newest first. Each line is one story: what happened,
  the outlet, the date, then `[news:N]`. Two stories about one event are one
  line with both markers.
- Lead with anything negative or regulatory.
- Stance is the story's stance toward this record. Say match and confidence
  as High, Medium or Low, never the number.
- End with the window you read ("stories from 12 Sep to 12 Oct").

Example:

- MHA cancelled the FCRA licence on 3 Oct (The Sentinel, 5 Oct) [news:41]
  [news:44]. The article cites the MHA order itself.
- Ran a learning camp with 400 children in Kamrup (EastMojo, 28 Sep) [news:39].
