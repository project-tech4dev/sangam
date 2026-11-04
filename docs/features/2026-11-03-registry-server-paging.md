# Registry: page, filter and search on the server

Part of [#341](https://github.com/project-tech4dev/sangam/issues/341) (parent #338), on branch `perf/registry-speed`.
This covers the issue's step 3 only. The query fixes, precomputing the list and caching come later.

## The problem

When someone opens the Registry, the server sends **every organisation and every funder** to the
browser at once, even though the screen shows only the first 20.

Today:

1. The backend builds a row for every org and funder and returns them all from `GET /api/registry`.
2. The Registry page passes all of them to the client component, so they reach the browser **twice**:
   once as JSON, and again embedded in the page HTML.
3. The browser does all the work: filtering by theme, state or SDG, searching by name, and counting
   results for the CSOs / Funders cards and the dropdowns.
4. The screen shows 20 rows, and 20 more each time you scroll. The rest were downloaded anyway.

**The fix:** the browser asks for one page (25 rows) at a time, and the server does the filtering,
searching and counting. The download stays small however big the Registry gets.

## The approach

The backend keeps building rows the way it does today (`registry_rows` in
`backend/app/repositories/registry.py`). Before answering, it filters, searches, counts and pages them
in Python, and returns one page of 25 rows plus the counts the screen needs. Previous / Next buttons move
between pages.

- **Fixes now:** the download. The browser gets 25 rows at any Registry size.
- **Doesn't fix yet:** server time. Each request still runs today's queries (~1 s warm). That's the issue's
  steps 1–2, later. The request and response defined here stay the same when they land, so the frontend
  won't change again.

## Done when

- [ ] The first Registry page sends **under 200 KB** (HTML + data), however many entities there are.
- [ ] Filters, search, bucket counts and the count line give the same answers as today's browser code.
- [ ] Search still finds a name from any part of a word ("dalgu" finds Udalguri).
- [ ] Back from a profile returns to the same filtered list and page (filters and page stay in the URL).
- [ ] The design system's Registry page matches the shipped screen.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Search | Keep today's behaviour: a match anywhere in the text, not only at the start of a word. |
| 2 | Dropdown options | **B.** Each dropdown lists only values that still match the *other* filters, with counts, e.g. "Assam (12)". It ignores its own filter, so you can switch Education → Health without clearing first. |
| 3 | Count line | "26–50 of 1,234" and "Page 2 of 50": matches for the filters and search, and where you are. |
| 4 | Order | Unchanged: CSOs first, then funders, each A→Z. |
| 5 | Search delay | Ask the server ~250 ms after the last keystroke; a reply for an older search is dropped. |
| 6 | Paging | Page numbers with Previous / Next buttons, 25 rows per page (one constant). A filter or search change goes back to page 1. |
| 7 | Paging pattern | Reuse the repo's existing pattern: `PageParams` (`limit` / `offset`, `backend/app/api/deps.py`) in, `Page[T]` (`items`, `total`, `limit`, `offset`, `backend/app/schemas/common.py`) out, as `/api/contacts`, `/api/documents` and `/api/meta` already do. No new paging parameters or response fields. |


---

## Step 1 — Backend: the paged API

Same path, `GET /api/registry`, new query parameters and response. The only caller is
`frontend/app/registry/page.tsx`, which changes in the same PR.

### Request

`?type=cso|funder&theme=&population=&sdg=&where=&reg=&ftype=&approach=&q=&limit=25&offset=0`

- The filter names are the ones `features/registry/filtersUrl.ts` already writes, so they pass straight through.
- `limit` / `offset` come from the existing `PageParams` (`page: PageParams = Depends()`): `limit` 1–100
  (default 50, the frontend always sends 25), `offset` ≥ 0. FastAPI's own validation answers 422 for a bad
  value, as on every other paged route. An offset past the end returns no items.

### Response (`backend/app/schemas/registry.py`)

```python
class RegistryFacet(ReadModel):
    value: str
    n: int

class RegistryPage(Page[RegistryRow]):     # items, total, limit, offset from the shared Page
    counts: dict[str, int]                  # {"all", "org", "funder"}: the bucket cards, every filter but kind
    facets: dict[str, list[RegistryFacet]]  # theme, population, sdg, where, ftype, approach
```

- `items`, `total`, `limit` and `offset` are the shared `Page[T]` from `backend/app/schemas/common.py`, the same
  response every other paged route returns. Only `counts` and `facets` are Registry-specific.
- `RegistryRow` loses `search`; the browser no longer needs it.
- Page numbers are worked out from the response, not sent: page = `offset / limit + 1`,
  pages = `max(1, ceil(total / limit))`.

### Filtering: port `matches()` to Python

New pure functions in `backend/app/repositories/registry.py` (no pool, no I/O, easy to unit-test):

- `Filters`, a dataclass parsed from the query string, with the same defaults as `DEFAULTS` in `filtersUrl.ts`.
- `matches(row, f, skip=None)`, a line-for-line port of `rows.ts`: kind, theme (any theme's `domain`),
  population, sdg, works-in (`any` / `ne` / `out` / a state), registrations (orgs only), funder type and
  approach (funders only), and search. `skip` names one filter to ignore; facets use it.
- **Search** is today's rule exactly: `q` trimmed and lower-cased, found anywhere in `row["search"]` or
  the lower-cased name.
- `NORTH_EAST` becomes a backend constant. The frontend keeps its copy for the row text, and a test asserts
  the two lists match.

### Counts and dropdown options (decision 2)

Over the rows `registry_rows` returns:

- `total`: rows passing every filter.
- `counts`: rows passing every filter except `kind`, counted per kind.
- `facets[x]`: rows passing every filter except `x` (`matches(row, f, skip=x)`), counted per value of `x`.
  Theme counts a row once per domain, population and sdg once per value, and `where` once per state, plus
  "North East" and "Outside the North East". Sort most common first, then A→Z; SDGs by number. A value
  with zero matches is left out, but the selected value always stays so the dropdown can show it.
- Funder-only facets (`ftype`, `approach`) appear only when `type=funder`; `reg` options stay fixed, as now.

### Paging

Sort the matching rows (CSOs first, then funders, each by `lower(name)`, then `id`), then slice with the
`PageParams` values:

```python
items = matched[page.offset:page.offset + page.limit]
total = len(matched)
```

When the list later moves to one SQL query (issue step 2), this slice becomes `COUNT(*) OVER () … LIMIT %(limit)s
OFFSET %(offset)s`, as `repositories/orgs.py` does today, and the request and response stay the same.

### Research counts, for the visible page only

`research_counts` runs today for every entity on every load. Now the route calls it for the ≤25 rows it
returns, keeping its existing "a research count is a hint, not the list" try/except.

### Route (`backend/app/api/routes/registry.py`)

```python
@router.get("", response_model=RegistryPage)
async def registry(pool: PoolDep, owner: OwnerPoolDep, page: PageParams = Depends(),
                   type: str = "all", theme: str = "all", ..., q: str = "", user_id=...) -> RegistryPage:
```

1. Build `Filters` from the query parameters; `page` comes from `PageParams`.
2. `rows = await repo.registry_rows(pool, owner)`, unchanged.
3. Compute `counts`, `facets`, `total`; filter, sort, slice with `page.offset` / `page.limit`.
4. Add research counts to those rows; drop `search`; return
   `RegistryPage(items=..., total=..., limit=page.limit, offset=page.offset, counts=..., facets=...)`.

## Step 2 — Frontend

**`frontend/app/registry/page.tsx`** (server): read `searchParams` (filters and `page`), turn the page number
into `limit=25&offset=(page - 1) * 25`, call `apiGet<RegistryPage>("/api/registry?" + params)`, and pass the
result to `RegistryClient`. The HTML now holds 25 rows, not the whole Registry. The browser's address keeps a
readable `?page=2`; only the API call uses `limit` / `offset`.

**`frontend/features/registry/RegistryClient.tsx`**:
- Takes `data: RegistryPage` instead of `rows`.
- Renders `data.items`; bucket counts come from `counts`, dropdown options from `facets` (labels gain "(n)").
- **Previous / Next** buttons and "26–50 of 1,234 · Page 2 of 50". A click sets `?page=` in the URL, and the
  server renders that page. Previous is disabled on page 1, Next on the last page.
- A filter or search change sets the new filter in the URL and drops `page`, so it goes back to page 1.
- Removes the in-browser `rows.filter(matches)`, the `counts` built from `rows`, the `options` `useMemo`, and
  `useShowMore` / `ListMore`.
- Search text stays local while typing, so the caret never waits; the URL updates 250 ms after the last key.
- `Row` is unchanged: it reads the same `RegistryRow` fields.

**Note:** CLAUDE.md's list-page pattern grows a list as you scroll (`ListMore`). The Registry moves to
Previous / Next, the only list that does, and there's no pager component yet: add one to the design system
first (Step 3), then to `components/ui/`.

**`frontend/features/registry/rows.ts`**: `kindLine`, `signal` and `NORTH_EAST` stay. `matches` and
`present` go once nothing imports them; their cases move to the backend tests.

**`frontend/lib/api`**: `RegistryOut` becomes `RegistryPage` (`items`, `total`, `limit`, `offset`, `counts`,
`facets`); `RegistryRow` drops `search`; add `RegistryFacet`.

## Step 3 — Design system sync

Same PR, as CLAUDE.md requires: the Registry page in `ui_kits/sangam-web/` and any component that changed
(dropdown counts, count line, the new pager), following `docs/DESIGN_SYSTEM.md`. No new token goes in
`globals.css` unless the design system has it first.

## Step 4 — Tests

| Tier | What |
|---|---|
| Backend, pure | `matches()` for every filter, ported from `frontend/features/registry/__tests__/rows.test.ts`; search finds a middle-of-word match; `skip`; facets (counts, ordering, the selected value kept, funder-only facets); paging (order, slices, `pages`, a page past the end is empty) |
| Backend, route (`tests/test_registry.py`, `client_for`, repo monkeypatched) | params parse; `limit` 0 or over 100 and a negative `offset` → 422; response has `Page`'s `items` / `total` / `limit` / `offset` plus `counts` / `facets`; `search` is not in the response; a research-count failure still returns the page |
| Frontend (Vitest, `.test.tsx`) | renders the page's items; counts and options come from the response; Next / Previous set `?page=` and are disabled at the ends; a filter change drops `page`; typing waits 250 ms |
| Manual | `make up`, `make seed`; every filter, search ("dalgu"), Next / Previous, Back from a profile; signed in and signed out |

Coverage gate: 75% of changed lines, backend and frontend (`codecov.yml`).

## Step 5 — Document and open the PR

1. In the PR body: page size before and after (bytes of the first page's HTML and JSON).
2. `docs/ARCHITECTURE.md`, Registry section: the list is paged and filtered on the server, and why (the issue's numbers).
3. `docs/CHANGELOG.md`: one line under Registry.
4. `make wiki-update` (the route changed).
5. `/code-review`, `/security-review`, fix what they find, and say so in the PR body.

## Later (rest of #341, not this plan)

- Fix the two slow queries (`entity_tags`, research counts).
- Precompute the list so a page is one query instead of rebuilding every row (issue step 2).
- Cache the list for signed-in visitors.
- Move `/api/orgs` and `/api/funders` from `LegacyPageParams` (plain array, `total` dropped) to `PageParams` +
  `Page[T]`, updating their two callers (Ask, Settings), so every list API follows the same pattern.
- `loading.tsx` skeletons; cache the user lookup; drop the per-checkout connection check.
