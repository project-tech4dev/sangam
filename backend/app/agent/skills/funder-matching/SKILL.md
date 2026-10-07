---
name: funder-matching
description: Use when someone asks which funders an organisation could apply to, should approach, or fits — "Which funders can KABIL apply to?", "find funders for Goonj", "who should we pitch?". From the organisation's name to one compare_fit call that judges and scores every funder in the catalog, ready to write up. The write-up itself is funder-shortlist-brief. When the user names the funders to judge, use funder-comparison instead.
---

# From an organisation to a shortlist

compare_fit judges; you resolve the name and write it up. It reads both sides
with fixed queries, so there is nothing to look up before it and nothing to
re-check after it.

## 1. Resolve the organisation

One db_query by name or slug, projecting orgs.id. If more than one
organisation could be meant, ask which before going on.

## 2. Call compare_fit once

`compare_fit(org_id)`, with no funder_ids. It considers every funder in the
catalog:

| in the reply | meaning |
|---|---|
| `assessed` | shares a place or a theme, or gives in a region whose states are not recorded: judged and scored, sorted by rank_key |
| `not_assessed.nothing_in_common_recorded` | has places or themes recorded, and shares none: counted |
| `not_assessed.nothing_recorded` | no places and no themes at all: named |
| `readiness` | the organisation's own twelve checks, the same for every funder |
| `what_to_record` | the organisation's gaps, as actions |

A funder that was not assessed is not a poor fit: it has nothing in common
recorded yet.

If it returns "compare_fit failed", say so with the error and stop. Never
judge the funders yourself instead.

## 3. Write it up

Load funder-shortlist-brief and follow it, from this one reply.
