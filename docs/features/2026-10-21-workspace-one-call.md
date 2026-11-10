# Funder Match and RFP Watch open with one call

## Context
Opening Funder Match or RFP Watch as a CSO admin shows "Loading…" for seconds. The SQL is not the cost
(the RFP feed runs in 5 ms on production as that admin). The screen makes two calls in a row, and on
Vercel almost every call starts a cold copy of the backend (~3.5 s, 1.5 s of it installing packages):

1. `useOrgChoices` fetches `/api/me` on every mount, though the `/ask` server page already fetched it.
2. Only then does the screen ask `/api/funder-matches?org=` or `/api/rfps/feed?org=`.

Funder Match's list also opens three transactions where one would do.

## M1: one PR
- **`/api/me` once.** The `/ask` page passes the `MeOut` it already fetched in `IndexPayload.me`;
  `AskWorkspace` hands it to Funder Match, RFP Watch and Media & Signals; `useOrgChoices(orgs, seed)`
  uses it and fetches only when the page could not (seed `null`). Same idea as the shared proposals store.
- **`?org=` optional** on `GET /api/funder-matches` and `GET /api/rfps/feed`, as `/api/news/stories`
  already treats it: omitted, the backend takes the caller's first organisation by name (the
  frontend's `choices[0]` for a member), resolved inside the same SQL. Nobody to default to is a 404.
  The feed gains `org_slug` so a caller that omitted it knows which org it got. The screens keep
  sending `?org=`; this serves any caller that has not looked up `/api/me`.
- **One transaction** for the Funder Match list: `repo.read_latest(pool, org)` runs `find_org`,
  `latest_run` and `list_matches` on one connection. The three keep their signatures for `create_run`.

Not here: proposal `_save` opens five transactions per autosave; a later PR.

## Exit gate
- Unit tests: the hook with and without a seed; each view makes no `/api/me` call when seeded;
  both routes with and without `org`; the list route reads through `read_latest`.
- After deploy, in Chrome: opening Funder Match sends `/api/funder-matches` and no `/api/me`.
