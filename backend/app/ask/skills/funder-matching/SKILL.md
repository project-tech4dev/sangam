---
name: funder-matching
description: Use when someone asks which funders an organisation could apply to, should approach, or fits — "Which funders can KABIL apply to?", "find funders for Goonj", "who should we pitch?". From the organisation's name to one compare_fit call that scores every funder in the catalog under the match-v2 rubric, ready to write up. The write-up itself is funder-shortlist-brief. When the user names the funders to judge, use funder-comparison instead.
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
catalog and replies in text:

| in the reply | meaning |
|---|---|
| `N funders checked` | every funder in the catalog |
| `scored N: …` | how many share a place or a theme, per tier: strong (75 or more), medium (55–74), weak (under 55) |
| `unknown across the N scored: …` | each criterion, and how many scored funders it was unknown for |
| numbered entries | the top strong and medium fits (up to 10), in full, ranked highest first |
| `- …` one-line entries | every other scored funder: score, tier and its first gap |
| `not scored, nothing in common recorded` | places or themes recorded on both sides, none shared |
| `not scored, the funder has nothing recorded` | no places and no themes recorded: unknown, not a poor fit |

The reply is complete for the write-up. Call compare_fit again only when the
user asks about one of the one-line funders in detail: then
`compare_fit(org_id, [its id])`, never the whole catalog again.

Each match carries seven criteria — theme 25, geography 15, population 15,
eligibility 20, relationship 10, funding size 10, capacity 5 — each met,
partial, fail or unknown. An unknown criterion is left out of the score, so
"66 of 90 judged points" is 73/100.

If it returns "compare_fit failed", say so with the error and stop. Never
judge the funders yourself instead.

If it returns "compare_fit refused", the user is not staff, a steward or an
admin of this organisation. Tell them running a match for it is for those
people, and stop. Never build a shortlist from db_query instead.

## 3. Write it up

Load funder-shortlist-brief and follow it, from this one reply.
