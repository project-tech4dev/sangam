---
name: funder-matching
description: Use when someone asks which funders an organisation could apply to, should approach, or fits — "Which funders can KABIL apply to?", "find funders for Goonj", "who should we pitch?". The procedure from the organisation's name to a set of funder-assessor replies, each with a computed gate and score, ready to write up. The write-up itself is funder-shortlist-brief. When the user names the funders to judge, use funder-comparison instead.
---

# From an organisation to a shortlist

You narrow; the funder-assessor judges. The narrowing is one query, so it can
miss nothing and decide nothing. A funder it drops is not a poor fit: it is a
funder with nothing in common recorded yet.

## 1. Resolve the organisation

Find it by name or slug. If more than one organisation could be meant, ask
which before going on. Note its org_id.

## 2. Read what it has recorded

One query: its districts and states (org_locations → locations, as in the
assessor's `area` rule), its sector tags, and how many of those tags map to a
Schedule VII clause through tags.meta->>'maps_to'.

If it has no places, or no sector tags, say so once, up front. Every funder
is then "not recorded" on that side, for the same reason.

## 3. Narrow, in ONE db_query

One row per funder, every funder in the catalog. Select, for each:

- shared districts and shared states, from funder_footprints and funder_locations;
- whether the funder states pan-India or regional coverage;
- shared sector tags, and shared Schedule VII slugs against its csr_sector tags;
- how many places and how many sector or csr_sector tags the funder has at all.

Keep the columns to counts and short lists. If the result says rows were not
shown, query the missing funders again rather than working from a short list.

Then sort every funder into one of three groups:

| group | rule | what happens |
|---|---|---|
| candidate | shares a place or a theme | sent to the funder-assessor |
| nothing in common recorded | has places or themes, and shares none | counted, not assessed |
| nothing recorded | no places and no themes at all | counted and named, not assessed |

A funder that states pan-India or regional coverage counts as sharing a place:
it is a candidate, and the assessor decides whether a region includes the
organisation's states.

## 4. Judge the organisation once

Launch org-readiness for the organisation with the task tool, alone in its own
message, and wait for it. It judges the organisation's own registrations,
audits, board and track record once, and Sangam hands that judgement to every
funder-assessor, so they never re-judge it.

If org-readiness already ran for this organisation earlier in this
conversation, reuse it: say "readiness assessed earlier in this conversation"
with its time. Run it again only when the user has imported or recorded new
data for the organisation since.

## 5. Assess every candidate

Launch one funder-assessor per candidate with the task tool. Each task's
description names the organisation and the funder, with both ids:
"KABIL (org_id 9) against HDFC Bank Limited (funder_id 2)".

Launch them in waves: as many in one message as your instructions allow,
wait for that wave, then launch the next, until every candidate is done.

With more candidates than three waves' worth, assess those sharing the most
first, and say how many remain unassessed and that you can continue.

If a reply says org-readiness has not run for the organisation, go back to
step 4, then assess those funders again. If a task fails any other way or
returns no assessment, list that funder as "not assessed" with the error.
Never judge it yourself instead.

## 6. Write it up

Load funder-shortlist-brief and follow it. Bring the two counted groups from
step 3 with you: they are part of the answer.
