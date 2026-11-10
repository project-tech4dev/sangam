# Registry: page, filter and search on the server, with shared paging

Part of [#341](https://github.com/project-tech4dev/sangam/issues/341) (parent #338), on branch `perf/registry-speed`.
This covers the issue's step 3 only. The query fixes, precomputing the list and caching come later.

> **Changed in review.** The Registry went straight to one SQL query (`registry_page_sql`), so the Python
> path below (`matches()`, `FacetSpec`/`count_facets`/`count_by`, `slice_page`) was deleted rather than
> kept beside it: a filter added there passed every test while production ignored it. The SQL is tested
> against Postgres (`tests/test_registry_sql.py`); `facets.py` keeps only `ordered`. `fetch_page` moved
> to #366, its first user.

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

The paging code is also repeated. Ten repositories hand-write the same `COUNT(*) OVER ()` and
`LIMIT` / `OFFSET` (contacts, documents, funders, orgs, meta, partner lines, partner groups, programs, rfps,
scores), each route rebuilds `Page(...)` itself, and each list screen counts and filters in its own way.

## The approach

**Build paging, filtering and counting once, then reuse them.** The Registry is the first user.

- **Backend:** one shared paging function (limit, offset, total) and one generic paged response with counts
  and filter options. Routes stop repeating the same code.
- **Filters and counts:** one reusable structure for filters, bucket counts and dropdown options, for the
  Registry now and Funder Match and Media & Signals later.
- **Frontend:** one shared hook, `usePagedList`, loads the next batch as the person scrolls, instead of
  downloading everything up front.
- **The screen stays the same.** Same cards, dropdowns, search and scrolling list; only the data arrives in
  batches of 25.

What this fixes now, and what it doesn't:

- **Fixes now:** the download. The browser gets 25 rows at a time at any Registry size.
- **Doesn't fix yet:** server time. Each request still runs today's queries (~1 s warm). That's the issue's
  steps 1–2, later. The request and response defined here stay the same when they land, so the frontend
  won't change again.

## Done when

- [ ] The first Registry page sends **under 200 KB** (HTML + data), however many entities there are.
- [ ] Filters, search, bucket counts, dropdown options and the count line give the same answers as today.
- [ ] Search still finds a name from any part of a word ("dalgu" finds Udalguri).
- [ ] Scrolling to the end loads the next 25, until every match is shown.
- [ ] Back from a profile returns to the same filtered list (filters stay in the URL, as now).
- [ ] The shared backend paging function, paged response and `usePagedList` exist, with the Registry using them.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Search | Keep today's behaviour: a match anywhere in the text, not only at the start of a word. |
| 2 | Dropdown options and bucket counts | Unchanged from today: options are every value in the Registry, and the CSOs / Funders cards count every entity. The server sends them instead of the browser working them out. Options that narrow with the other filters ("Assam (12)") can come later without changing the API shape. |
| 3 | Count line | Unchanged: "12 match" or "53 in the Registry", and "25 of 53 shown" under the list. |
| 4 | Order | Unchanged: CSOs first, then funders, each A→Z. |
| 5 | Search delay | Ask the server ~250 ms after the last keystroke; a reply for an older search is dropped. |
| 6 | Paging on screen | Load more as you scroll (today's `ListMore`), 25 rows a batch (one constant). A filter or search change starts again from the first batch. No page numbers, no Previous / Next. |
| 7 | Paging pattern | Reuse the repo's existing pattern: `PageParams` (`limit` / `offset`, `backend/app/api/deps.py`) in, `Page[T]` (`items`, `total`, `limit`, `offset`, `backend/app/schemas/common.py`) out, as `/api/contacts`, `/api/documents` and `/api/meta` already do. No paging library. |
| 8 | Scope of this PR | Build the shared pieces and move the Registry onto them. The other routes and screens move in later PRs, one at a time (see "Later"). |

---

## Step 1 — Backend: shared paging

### The paging function (`backend/app/repositories/paging.py`, new)

One place for what ten repositories write by hand today:

```python
async def fetch_page(conn, sql: str, params: dict, page: PageParams) -> tuple[list[dict], int]:
    """Rows `sql` returns, one page of them, and how many it returns in all."""
    # wraps: SELECT *, COUNT(*) OVER () AS total FROM (<sql>) q ORDER BY ... LIMIT %(limit)s OFFSET %(offset)s

def slice_page(rows: list, page: PageParams) -> tuple[list, int]:
    """The same for a list already built in Python: rows[offset:offset + limit], len(rows)."""
```

- `fetch_page` is for repositories with one SQL query. The caller's SQL keeps its own `ORDER BY` and
  filters; the function adds the total and `LIMIT` / `OFFSET`.
- `slice_page` is for the Registry now, whose rows are built in Python. When the list becomes one query
  (issue step 2), the Registry switches to `fetch_page` and nothing outside the repository changes.
- In this PR only the Registry uses them. Moving the other ten repositories is later, one PR each, so a
  wrong result is easy to trace.

### The paged response (`backend/app/schemas/common.py`)

`Page[T]` stays as it is. A generic subclass adds what a list screen with cards and dropdowns needs:

```python
class Facet(BaseModel):
    value: str
    n: int

class FacetedPage(Page[T], Generic[T]):     # items, total, limit, offset from Page
    counts: dict[str, int] = {}              # the bucket cards, e.g. {"all", "org", "funder"}
    facets: dict[str, list[Facet]] = {}      # each dropdown's options, e.g. theme, population, sdg
```

The Registry returns `FacetedPage[RegistryRow]`. Funder Match and Media & Signals can return the same shape later.

### Filters and counts (`backend/app/repositories/facets.py`, new, pure)

A small reusable structure, no pool and no I/O, so it is easy to unit-test:

- `FacetSpec(name, values)`: a dropdown's name and a function giving a row's values for it
  (a row's theme domains, its populations, its SDGs, its states, its funder type).
- `count_facets(rows, specs) -> dict[str, list[Facet]]`: counts each value, most common first, then A→Z
  (SDGs by number). Today's dropdowns are built this way in the browser (`present()` in `rows.ts`).
- `count_by(rows, key) -> dict[str, int]`: the bucket cards, plus `all`.

Each screen keeps its own filter rules (`matches()` for the Registry); only the counting and option-building
is shared. Funder Match and Media & Signals filter different fields, so their rules stay theirs.

## Step 2 — Backend: the Registry API

Same path, `GET /api/registry`, new query parameters and response. The only caller is
`frontend/app/registry/page.tsx`, which changes in the same PR.

### Request

`?type=cso|funder&theme=&population=&sdg=&where=&reg=&ftype=&approach=&q=&limit=25&offset=0`

- The filter names are the ones `features/registry/filtersUrl.ts` already writes, so they pass straight through.
- `limit` / `offset` come from the existing `PageParams` (`page: PageParams = Depends()`): `limit` 1–100
  (default 50, the frontend always sends 25), `offset` ≥ 0. FastAPI's own validation answers 422 for a bad
  value, as on every other paged route. An offset past the end returns no items.

### Filtering: port `matches()` to Python

New pure functions in `backend/app/repositories/registry.py`:

- `Filters`, a dataclass built from the query string, with the same defaults as `DEFAULTS` in `filtersUrl.ts`.
- `matches(row, f)`, a line-for-line port of `rows.ts`: kind, theme (any theme's `domain`), population, sdg,
  works-in (`any` / `ne` / `out` / a state), registrations (orgs only), funder type and approach (funders
  only), and search.
- **Search** is today's rule exactly: `q` trimmed and lower-cased, found anywhere in `row["search"]` or
  the lower-cased name.
- `NORTH_EAST` becomes a backend constant. The frontend keeps its copy for the row text, and a test asserts
  the two lists match.

### Route (`backend/app/api/routes/registry.py`)

```python
@router.get("", response_model=FacetedPage[RegistryRow])
async def registry(pool: PoolDep, owner: OwnerPoolDep, page: PageParams = Depends(),
                   type: str = "all", theme: str = "all", ..., q: str = "", user_id=...):
```

1. Build `Filters` from the query parameters; `page` comes from `PageParams`.
2. `rows = await repo.registry_rows(pool, owner)`, unchanged.
3. `counts = count_by(rows, "kind")` and `facets = count_facets(rows, REGISTRY_FACETS)`, over every row, as
   the browser does today (decision 2).
4. Keep the rows `matches()` passes, sorted (CSOs first, then funders, each by `lower(name)`, then `id`), and
   `items, total = slice_page(matched, page)`.
5. Add research counts to the ≤25 rows returned, keeping today's "a research count is a hint, not the list"
   try/except. Today it runs for every entity on every load.
6. Drop `search` from each row (the browser no longer needs it) and return
   `FacetedPage(items=..., total=..., limit=page.limit, offset=page.offset, counts=..., facets=...)`.

## Step 3 — Frontend: shared hook

### `usePagedList` (`frontend/components/ui/ListPage.tsx`)

The offset sibling of the existing `useCursorList` (which Media & Signals uses for its cursor-paged stories),
with the same behaviour:

```ts
function usePagedList<T, P extends { items: T[]; total: number }>(
  resetKey: string,                                  // filters + search; a change starts again from offset 0
  load: (offset: number, limit: number) => Promise<P>,
  options?: { limit?: number; first?: P },           // `first`: the server-rendered first batch, so it isn't fetched twice
): { items: T[]; total: number; last: P | null; busy: boolean; error: string | null; more: (() => void) | null }
```

- `more` asks for `offset = items.length`; it is `null` while loading or once every match is shown.
- An answer for an older `resetKey` is dropped, as in `useCursorList`.
- It feeds the existing `ListMore`, which already calls `more` when the person scrolls near the end. No new
  component, so no design-system change.

## Step 4 — Frontend: the Registry

**`frontend/app/registry/page.tsx`** (server): read the filters from `searchParams`, call
`apiGet<RegistryPage>("/api/registry?" + params + "&limit=25&offset=0")`, and pass that first batch to
`RegistryClient`. The HTML now holds 25 rows, not the whole Registry.

**`frontend/features/registry/RegistryClient.tsx`**:
- Takes `first: RegistryPage` instead of `rows`.
- `usePagedList(resetKey, load, { limit: 25, first })`, where `load` calls `/api/registry` from the browser
  with the current filters and `offset`.
- Bucket cards from `counts`, dropdown options from `facets`, the count line from `total`. The labels and
  layout don't change.
- `ListMore` gets `shown = items.length`, `total`, and `onMore = more`.
- Search text stays local while typing, so the caret never waits; the URL, and so the request, updates
  250 ms after the last key.
- Removes the in-browser `rows.filter(matches)`, the `counts` built from `rows`, the `options` `useMemo`,
  and `useShowMore`.
- `Row` is unchanged: it reads the same `RegistryRow` fields.

**`frontend/features/registry/rows.ts`**: `kindLine`, `signal` and `NORTH_EAST` stay. `matches` and
`present` go once nothing imports them; their cases move to the backend tests.

**`frontend/lib/api`**: add `Page<T>`, `FacetedPage<T>` and `Facet` to match the backend;
`RegistryOut` becomes `RegistryPage = FacetedPage<RegistryRow>`; `RegistryRow` drops `search`.

## Step 5 — Design system

The screen doesn't change: same cards, dropdowns, search, count line and scrolling list, and no new component.
So no design-system update is needed; the PR body says so, as CLAUDE.md asks.

## Step 6 — Tests

| Tier | What |
|---|---|
| Backend, pure | `fetch_page` SQL wrapping (limit, offset, total; empty result); `slice_page` (slices, an offset past the end is empty); `count_facets` and `count_by` (counts, ordering, SDGs by number); Registry `matches()` for every filter, ported from `frontend/features/registry/__tests__/rows.test.ts`; search finds a middle-of-word match |
| Backend, route (`tests/test_registry.py`, `client_for`, repo monkeypatched) | params parse; `limit` 0 or over 100 and a negative `offset` → 422; response has `items` / `total` / `limit` / `offset` / `counts` / `facets`; `search` is not in the response; a research-count failure still returns the page |
| Frontend (Vitest) | `usePagedList`: first batch used without a fetch, `more` loads the next offset, a reset drops a stale answer, `more` is null at the end; Registry renders the items, counts and options from the response; typing waits 250 ms |
| Manual | `make up`, `make seed`; every filter, search ("dalgu"), scroll to the end, Back from a profile; signed in and signed out |

Coverage gate: 75% of changed lines, backend and frontend (`codecov.yml`).

## Step 7 — Document and open the PR

1. In the PR body: page size before and after (bytes of the first page's HTML and JSON).
2. `docs/ARCHITECTURE.md`: the Registry section (paged and filtered on the server, and why), and the shared
   paging pieces (`fetch_page`, `FacetedPage`, `usePagedList`) as the pattern a new list follows.
3. `docs/CHANGELOG.md`: one line under Registry.
4. `make wiki-update` (the route changed).
5. `/code-review`, `/security-review`, fix what they find, and say so in the PR body.

## Later (not this PR)

Moving the rest onto the shared pieces, one PR each:

- The ten repositories with hand-written `COUNT(*) OVER ()` / `LIMIT` / `OFFSET` onto `fetch_page`.
- `/api/orgs` and `/api/funders` from `LegacyPageParams` (a plain array, `total` dropped) to `PageParams` +
  `Page[T]`, updating their two callers (Ask, Settings).
- Proposals' list from `useShowMore` to `usePagedList`.
- Funder Match and Media & Signals: counts and options from `FacetedPage` instead of the browser.

The rest of #341:

- Fix the two slow queries (`entity_tags`, research counts).
- Precompute the list so a page is one query instead of rebuilding every row (issue step 2).
- Cache the list for signed-in visitors.
- `loading.tsx` skeletons; cache the user lookup; drop the per-checkout connection check.
