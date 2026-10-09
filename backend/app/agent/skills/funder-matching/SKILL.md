---
name: funder-matching
description: Use when someone asks which funders an organisation could apply to, should approach, or fits — "Which funders can KABIL apply to?", "find funders for Goonj", "who should we pitch?". From the organisation's name to one compare_fit call that scores every funder in the catalog under the match-v1 rubric, ready to write up. The write-up itself is funder-shortlist-brief. When the user names the funders to judge, use funder-comparison instead.
---

# From an organisation to a shortlist

compare_fit judges and scores; you resolve the name and write it up. It reads
both sides with fixed queries, so there is nothing to look up before it and
nothing to re-check after it.

## 1. Resolve the organisation

One db_query by name or slug, projecting orgs.id. If more than one
organisation could be meant, ask which before going on.

## 2. Call compare_fit once

`compare_fit(org_id)`, with no funder_ids. It checks every funder in the
catalog:

| in the reply | meaning |
|---|---|
| `funders_checked` | every funder in the catalog |
| `matches` | shares a place or a theme: scored out of 100 and ranked, highest first |
| `matches[].tier` | strong (75 or more), medium (55–74), weak (under 55) |
| `not_scored.nothing_in_common_recorded` | places or themes recorded on both sides, none shared |
| `not_scored.funder_has_nothing_recorded` | the funder has no places and no themes recorded: unknown, not a poor fit |

Each match carries seven criteria — theme 25, geography 15, population 15,
eligibility 20, relationship 10, funding size 10, capacity 5 — each met,
partial, fail or unknown. An unknown criterion is left out of the score, so
"66 of 90 judged points" is 73/100.

If it returns "compare_fit failed", say so with the error and stop. Never
judge the funders yourself instead.

## 3. Write it up

Load funder-shortlist-brief and follow it, from this one reply.
